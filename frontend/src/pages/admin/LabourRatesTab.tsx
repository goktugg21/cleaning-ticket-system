import type { FormEvent } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  createEmployeeHourlyRate,
  deleteEmployeeHourlyRate,
  listEmployeeHourlyRates,
  updateEmployeeHourlyRate,
} from "../../api/labourRates";
import type { EmployeeHourlyRate } from "../../api/labourRates";
import { listTimesheetEmployees } from "../../api/timesheets";
import type { TimesheetEmployee } from "../../api/timesheets.types";
import { BoundedList } from "../../components/BoundedList";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { useToast } from "../../components/ToastProvider";

interface LabourRatesTabProps {
  /** True when a SUPER_ADMIN must disambiguate (2+ provider companies). */
  companyRequired?: boolean;
  /** The company the host page has resolved. `""` means "the host is
   *  choosing and has not resolved one yet" — the same distinction
   *  `HourTypesTab` documents. */
  selectedCompany: number | "";
}

interface RateFormState {
  employee: string;
  hourly_rate: string;
  valid_from: string;
  note: string;
}

const EMPTY_FORM: RateFormState = {
  employee: "",
  hourly_rate: "",
  valid_from: "",
  note: "",
};

/** Today as an ISO date, for the "what is the rate right now" column. */
function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/**
 * The rate in force on `onDate` — the LATEST row starting on or before
 * it, which is the identical rule the server applies when it costs an
 * hour (`reports.labour_cost.RateBook.rate_on`).
 *
 * Rows arrive newest-first from the API (`Meta.ordering` is
 * `-valid_from, -id`), so this is a find, not a sort. It is a READ of
 * what the server will do, never a second source of truth: no cost
 * figure on any screen is computed here.
 */
function rateInForce(
  rows: EmployeeHourlyRate[],
  onDate: string,
): EmployeeHourlyRate | undefined {
  return rows.find((row) => row.valid_from <= onDate);
}

/**
 * W4-R — "Uurtarieven", the per-person hourly rate tab.
 *
 * ## Why this tab is on the HOURS page and what it says out loud
 *
 * The rate is stored and applied in `reports`, NOT in `timesheets` —
 * that module records hours and weighted hours and never computes
 * money, and a test walks its every file to keep it that way. But the
 * person setting a rate is the person who manages hours, so making them
 * hunt for a separate screen would be a filing decision imposed on an
 * operator. The tab therefore leads with a sentence saying exactly where
 * each number lives (the plan's decision 12: "the UI must say where each
 * number comes from"), so nobody looks for a wage field on a timesheet.
 *
 * ## Recording a raise is ADDING a row, not editing one
 *
 * That is the whole design and the form says so. A rate is dated: the
 * row in force on the day of an hour is what costs that hour, so a new
 * rate from a new date leaves every earlier cost figure exactly where it
 * was. Editing a row instead means "this row was typed wrong" and DOES
 * re-price the period it covers — which is why the edit form warns, and
 * why every write here lands on the audit log.
 *
 * ## Who can even see this
 *
 * SUPER_ADMIN and COMPANY_ADMIN. The host route already admits only
 * those two (`TimesheetsRoute manager`), and the endpoints refuse
 * everyone else independently — a BUILDING_MANAGER included, on
 * purpose. A wage is personal data and hiding a field in a screen while
 * the API still returns it is a decoration, not a permission.
 */
export function LabourRatesTab({
  companyRequired = false,
  selectedCompany,
}: LabourRatesTabProps) {
  const { t } = useTranslation("common");
  const { push: pushToast } = useToast();

  const [employees, setEmployees] = useState<TimesheetEmployee[]>([]);
  const [rates, setRates] = useState<EmployeeHourlyRate[]>([]);
  const [loadError, setLoadError] = useState("");
  const [form, setForm] = useState<RateFormState>(EMPTY_FORM);
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);
  const [historyFor, setHistoryFor] = useState<number | "">("");
  const [editing, setEditing] = useState<EmployeeHourlyRate | null>(null);
  const [editRate, setEditRate] = useState("");
  const pendingDelete = useRef<EmployeeHourlyRate | null>(null);
  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);

  // Derived `loading` — the pattern this page's other tabs use, so a
  // company switch never renders the previous company's rows as if they
  // were this one's. `blocked` short-circuits it: with no company
  // chosen nothing is fetched, so "still loading" would be a wait that
  // never ends.
  const fetchKey = String(selectedCompany);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const blocked = companyRequired && selectedCompany === "";
  const loading = !blocked && loadedKey !== fetchKey;

  /** The two reads this tab lives on, as one promise. */
  const fetchAll = useCallback(() => {
    const company = selectedCompany === "" ? undefined : selectedCompany;
    return Promise.all([
      listTimesheetEmployees(selectedCompany),
      listEmployeeHourlyRates(company === undefined ? {} : { company }),
    ]);
  }, [selectedCompany]);

  // The load, as a PROMISE CHAIN with a cancelled flag — the exact shape
  // `HourTypesTab` and the other tabs on this page use, and it is the
  // shape for a reason: CLAUDE.md §3 forbids synchronous setState in an
  // effect body, and `react-hooks/set-state-in-effect` enforces it. An
  // `async` helper called from the effect trips the rule even when every
  // setState in it sits after an `await`; setState inside a `.then`
  // callback does not, because the callback genuinely is not the effect
  // body. The baseline is exactly 44 and this sprint adds none.
  useEffect(() => {
    if (blocked) return;
    let cancelled = false;
    fetchAll()
      .then(([people, rows]) => {
        if (cancelled) return;
        setLoadError("");
        setEmployees(people);
        setRates(rows);
        setLoadedKey(fetchKey);
      })
      .catch((error) => {
        if (cancelled) return;
        setLoadError(getApiError(error));
        setEmployees([]);
        setRates([]);
        setLoadedKey(fetchKey);
      });
    return () => {
      cancelled = true;
    };
  }, [blocked, fetchAll, fetchKey]);

  /**
   * Re-read after a mutation. NOT called from an effect — a save handler
   * awaits it — so it may set state directly, and it is a separate
   * function from the effect above rather than a shared one precisely
   * because the two live under different rules.
   */
  const refresh = useCallback(async () => {
    if (blocked) return;
    try {
      const [people, rows] = await fetchAll();
      setLoadError("");
      setEmployees(people);
      setRates(rows);
    } catch (error) {
      setLoadError(getApiError(error));
    } finally {
      setLoadedKey(fetchKey);
    }
  }, [blocked, fetchAll, fetchKey]);

  const today = todayIso();
  const rowsFor = (employeeId: number) =>
    rates.filter((row) => row.employee === employeeId);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setFormError("");
    if (selectedCompany === "") {
      setFormError(t("labour_rates.company_required"));
      return;
    }
    setSaving(true);
    try {
      await createEmployeeHourlyRate({
        company: selectedCompany,
        employee: Number(form.employee),
        hourly_rate: form.hourly_rate.trim(),
        valid_from: form.valid_from,
        note: form.note.trim(),
      });
      setForm(EMPTY_FORM);
      await refresh();
      pushToast({ variant: "success", title: t("labour_rates.saved") });
    } catch (error) {
      setFormError(getApiError(error));
    } finally {
      setSaving(false);
    }
  }

  async function handleEditSave(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    setSaving(true);
    setFormError("");
    try {
      await updateEmployeeHourlyRate(editing.id, {
        hourly_rate: editRate.trim(),
      });
      setEditing(null);
      await refresh();
      pushToast({ variant: "success", title: t("labour_rates.corrected") });
    } catch (error) {
      setFormError(getApiError(error));
    } finally {
      setSaving(false);
    }
  }

  function askDelete(row: EmployeeHourlyRate) {
    pendingDelete.current = row;
    deleteDialogRef.current?.open();
  }

  async function handleConfirmDelete() {
    const row = pendingDelete.current;
    pendingDelete.current = null;
    if (!row) return;
    try {
      await deleteEmployeeHourlyRate(row.id);
      await refresh();
      pushToast({ variant: "success", title: t("labour_rates.deleted") });
    } catch (error) {
      pushToast({ variant: "error", title: getApiError(error) });
    }
  }

  const historyRows = historyFor === "" ? [] : rowsFor(historyFor);

  return (
    <div data-testid="labour-rates-tab">
      {/* The plan's decision 12, said on the screen rather than left to
          be discovered: hours are recorded in one module and priced in
          another, and there is no wage field on a timesheet. */}
      <p className="muted" data-testid="labour-rates-seam-note">
        {t("labour_rates.seam_note")}
      </p>

      {loadError && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {loadError}
        </div>
      )}

      {blocked ? (
        <p className="muted">{t("labour_rates.pick_company")}</p>
      ) : loading ? (
        // Not the previous company's people under this company's
        // heading. A stale row here is a person's WAGE attributed to
        // the wrong employer, which is worse than a moment of nothing.
        <p className="muted">{t("loading")}</p>
      ) : (
        <>
          <section className="card card-detail-pad" style={{ marginBottom: 16 }}>
            <h3>{t("labour_rates.current_heading")}</h3>
            <p className="muted">{t("labour_rates.current_hint")}</p>
            <BoundedList
              /* W5 fix 5 — `lg`, not `md`. Six rows of this table are
                 taller than the 320px `md` window (each row carries a
                 button), so a table nobody would call long scrolled
                 inside a page that already scrolls. It keeps a bound:
                 employees is a SERVER collection and CLAUDE.md's rule
                 is that those are never rendered unbounded — a real
                 tenant has hundreds. `lg` is the existing 420px step,
                 not a new value. */
              size="lg"
              count={employees.length}
              ariaLabel={t("labour_rates.current_heading")}
              testIdPrefix="labour-rates-current"
              className="table-wrap"
              emptyState={<p className="muted">{t("labour_rates.no_people")}</p>}
            >
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t("labour_rates.col_employee")}</th>
                    <th>{t("labour_rates.col_current_rate")}</th>
                    <th>{t("labour_rates.col_since")}</th>
                    <th>{t("labour_rates.col_history")}</th>
                  </tr>
                </thead>
                <tbody>
                  {employees.map((person) => {
                    const own = rowsFor(person.id);
                    const inForce = rateInForce(own, today);
                    return (
                      <tr key={person.id} data-testid={`labour-rate-row-${person.id}`}>
                        <td>{person.full_name || person.email}</td>
                        <td data-testid={`labour-rate-value-${person.id}`}>
                          {/* NEVER a 0,00 stand-in. "No rate set" and
                              "costs nothing" are different claims and
                              must never render the same. */}
                          {inForce ? (
                            `€ ${inForce.hourly_rate}`
                          ) : (
                            <span className="muted">
                              {t("labour_rates.no_rate")}
                            </span>
                          )}
                        </td>
                        <td>{inForce ? inForce.valid_from : "—"}</td>
                        <td>
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() =>
                              setHistoryFor(
                                historyFor === person.id ? "" : person.id,
                              )
                            }
                          >
                            {/* `n`, not `count`: an i18next `count`
                                option engages plural resolution and
                                looks for `_one` / `_other` keys that do
                                not exist here. */}
                            {t("labour_rates.show_history", {
                              n: own.length,
                            })}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </BoundedList>
          </section>

          {historyFor !== "" && (
            <section className="card card-detail-pad" style={{ marginBottom: 16 }}>
              <h3>{t("labour_rates.history_heading")}</h3>
              <p className="muted">{t("labour_rates.history_hint")}</p>
              <BoundedList
                size="md"
                count={historyRows.length}
                ariaLabel={t("labour_rates.history_heading")}
                testIdPrefix="labour-rates-history"
                className="table-wrap"
                emptyState={
                  <p className="muted">{t("labour_rates.no_history")}</p>
                }
              >
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{t("labour_rates.col_from")}</th>
                      <th>{t("labour_rates.col_rate")}</th>
                      <th>{t("labour_rates.col_note")}</th>
                      <th>{t("labour_rates.col_recorded_by")}</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {historyRows.map((row) => (
                      <tr key={row.id} data-testid={`labour-rate-history-${row.id}`}>
                        <td>{row.valid_from}</td>
                        <td>{`€ ${row.hourly_rate}`}</td>
                        <td>{row.note || "—"}</td>
                        <td>{row.created_by_name}</td>
                        <td>
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => {
                              setEditing(row);
                              setEditRate(row.hourly_rate);
                            }}
                          >
                            {t("labour_rates.correct_button")}
                          </button>{" "}
                          <button
                            type="button"
                            className="btn btn-sm btn-danger"
                            onClick={() => askDelete(row)}
                          >
                            {t("labour_rates.delete_button")}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </BoundedList>
            </section>
          )}

          <section className="card card-detail-pad">
            <h3>{t("labour_rates.new_heading")}</h3>
            {/* The sentence that makes the model make sense: a raise is
                a NEW row from a NEW date, and that is what keeps old
                work costing what it cost. */}
            <p className="muted">{t("labour_rates.new_hint")}</p>
            <form onSubmit={handleCreate}>
              <div className="field">
                <label className="field-label" htmlFor="labour-rate-employee">
                  {t("labour_rates.col_employee")}
                </label>
                <select
                  id="labour-rate-employee"
                  className="field-input"
                  data-testid="labour-rate-employee"
                  value={form.employee}
                  required
                  onChange={(event) =>
                    setForm({ ...form, employee: event.target.value })
                  }
                >
                  <option value="">{t("labour_rates.pick_employee")}</option>
                  {employees.map((person) => (
                    <option key={person.id} value={person.id}>
                      {person.full_name || person.email}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="field-label" htmlFor="labour-rate-amount">
                  {t("labour_rates.col_rate")}
                </label>
                <input
                  id="labour-rate-amount"
                  className="field-input"
                  data-testid="labour-rate-amount"
                  type="number"
                  step="0.01"
                  min="0.01"
                  required
                  value={form.hourly_rate}
                  onChange={(event) =>
                    setForm({ ...form, hourly_rate: event.target.value })
                  }
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="labour-rate-from">
                  {t("labour_rates.col_from")}
                </label>
                <input
                  id="labour-rate-from"
                  className="field-input"
                  data-testid="labour-rate-from"
                  type="date"
                  required
                  value={form.valid_from}
                  onChange={(event) =>
                    setForm({ ...form, valid_from: event.target.value })
                  }
                />
              </div>
              <div className="field">
                <label className="field-label" htmlFor="labour-rate-note">
                  {t("labour_rates.col_note")}
                </label>
                <input
                  id="labour-rate-note"
                  className="field-input"
                  data-testid="labour-rate-note"
                  type="text"
                  maxLength={255}
                  value={form.note}
                  onChange={(event) =>
                    setForm({ ...form, note: event.target.value })
                  }
                />
              </div>
              {formError && (
                <div className="alert-error" role="alert">
                  {formError}
                </div>
              )}
              <button
                type="submit"
                className="btn btn-primary"
                data-testid="labour-rate-submit"
                disabled={saving || loading}
              >
                {t("labour_rates.add_button")}
              </button>
            </form>
          </section>

          {/* Conditionally mounted overlay, like every other editing
              modal on this page. The ConfirmDialog below stays native
              and ref-driven and is rendered UNCONDITIONALLY — the two
              are deliberately different things (CLAUDE.md §3). */}
          {editing && (
            <section className="card card-detail-pad" style={{ marginTop: 16 }}>
              <h3>{t("labour_rates.correct_heading")}</h3>
              <p className="muted">{t("labour_rates.correct_warning")}</p>
              <form onSubmit={handleEditSave}>
                <div className="field">
                  <label className="field-label" htmlFor="labour-rate-correct">
                    {t("labour_rates.col_rate")}
                  </label>
                  <input
                    id="labour-rate-correct"
                    className="field-input"
                    data-testid="labour-rate-correct"
                    type="number"
                    step="0.01"
                    min="0.01"
                    required
                    value={editRate}
                    onChange={(event) => setEditRate(event.target.value)}
                  />
                </div>
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={saving}
                >
                  {t("labour_rates.correct_save")}
                </button>{" "}
                <button
                  type="button"
                  className="btn"
                  onClick={() => setEditing(null)}
                >
                  {t("labour_rates.cancel")}
                </button>
              </form>
            </section>
          )}
        </>
      )}

      <ConfirmDialog
        ref={deleteDialogRef}
        title={t("labour_rates.delete_confirm_title")}
        body={t("labour_rates.delete_confirm_body")}
        confirmLabel={t("labour_rates.delete_button")}
        onConfirm={handleConfirmDelete}
        onCancel={() => {
          pendingDelete.current = null;
        }}
      />
    </div>
  );
}
