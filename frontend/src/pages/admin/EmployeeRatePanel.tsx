import type { FormEvent } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import type { EmployeeHourlyRate } from "../../api/labourRates";
import { BoundedList } from "../../components/BoundedList";
import { formatMoney } from "../../lib/intl";

/** The round number of hours the form's worked example multiplies by.
 *  Ten, because it is the figure a reader can divide back out in their
 *  head to check the rate — which is the whole point of showing it. */
const PREVIEW_HOURS = 10;

export interface NewRatePayload {
  hourly_rate: string;
  valid_from: string;
  note: string;
}

export interface EmployeeRatePanelProps {
  employeeName: string;
  /** This person's rows only, newest-first (the API's own ordering). */
  rates: EmployeeHourlyRate[];
  /** True when no company is resolved, so a rate cannot be filed. The
   *  READ still works — history is shown; only the form is blocked. */
  companyBlocked: boolean;
  busy: boolean;
  error: string;
  onCreate: (payload: NewRatePayload) => void;
  onCorrect: (row: EmployeeHourlyRate, hourlyRate: string) => void;
  onDelete: (row: EmployeeHourlyRate) => void;
}

/**
 * W-HR1 §3 — the per-person cost of an hour, on the person's own row.
 *
 * ## Where this came from and why it moved
 *
 * This was the "Kosten per uur" TAB on /admin/hours: a company-wide
 * table of every employee, with a rate form under it that began by
 * asking which employee you meant. Every operator who reaches it has
 * already picked a person — on the Employees page, which is where a
 * person's employment type, buildings and account already live. The
 * audit's verdict was that the tab existed only because the person who
 * sets a rate is the person who manages hours; that is a fact about
 * PEOPLE, not about hours, so the rate follows the person.
 *
 * What is left of the tab is exactly this: the history, and one action
 * that adds a row from a date. The employee picker is gone because the
 * row you expanded IS the answer, and the "N of M people have a rate"
 * banner is gone because the Employees table now shows the rate in a
 * column, where the same fact is countable by eye and per person.
 *
 * ## Recording a raise is ADDING a row, not editing one
 *
 * A rate is dated: the row in force on the day of an hour is what costs
 * that hour, so a new rate from a new date leaves every earlier cost
 * figure exactly where it was. Editing a row instead means "this row
 * was typed wrong" and DOES re-price the period it covers — which is
 * why the correction form warns, and why every write here is audited.
 *
 * ## Who sees it
 *
 * The caller gates this on `isProviderAdmin`. A wage is personal data;
 * `/api/reports/employee-hourly-rates/` 403s a BUILDING_MANAGER and a
 * STAFF member independently, and this panel is never rendered for
 * them — the hiding is a courtesy, the 403 is the permission.
 *
 * Presentational: every read and every write belongs to the page, which
 * owns the data and the delete confirmation. A native <dialog> must not
 * live inside a conditionally-mounted subtree (CLAUDE.md §3 — the
 * Sprint 118 frozen-screen bug), and this panel is exactly such a
 * subtree.
 */
export function EmployeeRatePanel({
  employeeName,
  rates,
  companyBlocked,
  busy,
  error,
  onCreate,
  onCorrect,
  onDelete,
}: EmployeeRatePanelProps) {
  const { t } = useTranslation("common");
  const [hourlyRate, setHourlyRate] = useState("");
  const [validFrom, setValidFrom] = useState("");
  const [note, setNote] = useState("");
  const [correcting, setCorrecting] = useState<EmployeeHourlyRate | null>(null);
  const [correctedRate, setCorrectedRate] = useState("");

  /** What PREVIEW_HOURS hours of this person's time will report as.
   *  `null` until there is a usable rate to multiply, so an untouched
   *  form shows nothing. NOT A SECOND MONEY RULE: it multiplies a rate
   *  by a round ten to illustrate the unit, and no cost figure anywhere
   *  is taken from it. */
  const parsed = Number.parseFloat(hourlyRate.replace(",", "."));
  const previewCost =
    Number.isFinite(parsed) && parsed > 0
      ? (parsed * PREVIEW_HOURS).toFixed(2)
      : null;

  function submitNew(event: FormEvent) {
    event.preventDefault();
    onCreate({
      hourly_rate: hourlyRate.trim(),
      valid_from: validFrom,
      note: note.trim(),
    });
    setHourlyRate("");
    setValidFrom("");
    setNote("");
  }

  function submitCorrection(event: FormEvent) {
    event.preventDefault();
    if (!correcting) return;
    onCorrect(correcting, correctedRate.trim());
    setCorrecting(null);
  }

  return (
    <div
      className="card-detail-pad"
      data-testid="employee-rate-panel"
      style={{ padding: "14px 18px" }}
    >
      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 12 }}>
          {error}
        </div>
      )}

      <div className="form-section-title">
        {t("labour_rates.history_heading")} — {employeeName}
      </div>

      {/* Bounded, like every list over a server collection
          (CLAUDE.md #8). `sm`: this is one person's rate history, and a
          long-serving employee's twenty raises scroll rather than push
          the rest of the directory off screen. */}
      <BoundedList
        size="sm"
        count={rates.length}
        ariaLabel={t("labour_rates.history_heading")}
        testIdPrefix="employee-rate-history"
        className="table-wrap"
        emptyState={
          <p className="muted small" style={{ margin: "6px 0 0" }}>
            {t("labour_rates.no_history")}
          </p>
        }
      >
        <table className="data-table data-table-dense">
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
            {rates.map((row) => (
              <tr key={row.id} data-testid={`employee-rate-row-${row.id}`}>
                <td>{row.valid_from}</td>
                <td>{`€ ${row.hourly_rate}`}</td>
                <td className="muted small">{row.note || "—"}</td>
                <td className="muted small">{row.created_by_name}</td>
                <td>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      disabled={busy}
                      data-testid={`employee-rate-correct-${row.id}`}
                      onClick={() => {
                        setCorrecting(row);
                        setCorrectedRate(row.hourly_rate);
                      }}
                    >
                      {t("labour_rates.correct_button")}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      disabled={busy}
                      data-testid={`employee-rate-delete-${row.id}`}
                      onClick={() => onDelete(row)}
                    >
                      {t("labour_rates.delete_button")}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </BoundedList>

      {/* W-E §3 — WHERE THE NUMBER COMES OUT. A rate is read in exactly
          one place (`reports/labour_cost.py`, surfaced as Labour cost on
          an Extra Work's Hours tab). Naming the destination is also what
          says the rate never reaches a customer price: the place it does
          reach is named, and it is not an invoice. */}
      <p className="muted small" data-testid="employee-rate-where">
        {t("labour_rates.where_prefix")}{" "}
        <Link to="/extra-work" className="link">
          {t("labour_rates.where_link")}
        </Link>
        {t("labour_rates.where_suffix")}
      </p>

      {correcting ? (
        <form onSubmit={submitCorrection} data-testid="employee-rate-correct-form">
          <div className="form-section-title">
            {t("labour_rates.correct_heading")}
          </div>
          <p className="muted small" style={{ marginTop: 0 }}>
            {t("labour_rates.correct_warning")}
          </p>
          <div className="field">
            <label className="field-label" htmlFor="employee-rate-correct-input">
              {t("labour_rates.col_rate")}
            </label>
            <input
              id="employee-rate-correct-input"
              className="field-input"
              data-testid="employee-rate-correct-input"
              type="number"
              step="0.01"
              min="0.01"
              required
              value={correctedRate}
              onChange={(event) => setCorrectedRate(event.target.value)}
            />
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="submit"
              className="btn btn-primary btn-sm"
              disabled={busy}
              data-testid="employee-rate-correct-save"
            >
              {t("labour_rates.correct_save")}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => setCorrecting(null)}
            >
              {t("labour_rates.cancel")}
            </button>
          </div>
        </form>
      ) : (
        <form onSubmit={submitNew} data-testid="employee-rate-new-form">
          <div className="form-section-title">
            {t("labour_rates.new_heading")}
          </div>
          {companyBlocked ? (
            <p className="muted small" style={{ marginTop: 0 }}>
              {t("labour_rates.pick_company")}
            </p>
          ) : (
            <>
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 12,
                  alignItems: "flex-end",
                }}
              >
                <div className="field" style={{ margin: 0, minWidth: 160 }}>
                  <label className="field-label" htmlFor="employee-rate-amount">
                    {t("labour_rates.col_rate")}
                  </label>
                  <input
                    id="employee-rate-amount"
                    className="field-input"
                    data-testid="employee-rate-amount"
                    type="number"
                    step="0.01"
                    min="0.01"
                    required
                    value={hourlyRate}
                    onChange={(event) => setHourlyRate(event.target.value)}
                  />
                </div>
                <div className="field" style={{ margin: 0, minWidth: 160 }}>
                  <label className="field-label" htmlFor="employee-rate-from">
                    {t("labour_rates.col_from")}
                  </label>
                  <input
                    id="employee-rate-from"
                    className="field-input"
                    data-testid="employee-rate-from"
                    type="date"
                    required
                    value={validFrom}
                    onChange={(event) => setValidFrom(event.target.value)}
                  />
                </div>
                <div className="field" style={{ margin: 0, minWidth: 200 }}>
                  <label className="field-label" htmlFor="employee-rate-note">
                    {t("labour_rates.col_note")}
                  </label>
                  <input
                    id="employee-rate-note"
                    className="field-input"
                    data-testid="employee-rate-note"
                    type="text"
                    maxLength={255}
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                  />
                </div>
                <button
                  type="submit"
                  className="btn btn-primary btn-sm"
                  data-testid="employee-rate-submit"
                  disabled={busy}
                >
                  {t("labour_rates.add_button")}
                </button>
              </div>

              {/* THE CONSEQUENCE, WORKED OUT, WHERE THE DECISION IS
                  MADE: type a number and see what ten hours of this
                  person's time will report as, and from when. It
                  appears only once there is something to compute. */}
              {previewCost !== null && (
                <p className="muted small" data-testid="employee-rate-preview">
                  {t("labour_rates.preview", {
                    hours: PREVIEW_HOURS,
                    amount: formatMoney(previewCost),
                    from: validFrom || t("labour_rates.preview_no_date"),
                  })}
                </p>
              )}
            </>
          )}
        </form>
      )}
    </div>
  );
}
