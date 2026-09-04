import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Plus, SlidersHorizontal } from "lucide-react";

import { api, getApiError } from "../../api/client";
import { BoundedList } from "../../components/BoundedList";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { ContractHoursBulkDialog } from "../../components/timesheets/ContractHoursBulkDialog";
import type { HourType, TimesheetEmployee } from "../../api/timesheets.types";
import type { BuildingAdmin } from "../../api/types";
import { hourTypeLabelFrom } from "../../lib/hourTypeLabel";
import { PATTERN_DAYS, patternLabel } from "../../lib/patternLabel";
import type { PatternDay } from "../../lib/patternLabel";
import { workTypeLabel } from "../../lib/workTypeLabel";

type Day = PatternDay;
type Status = "DRAFT" | "SAVED" | "APPROVED";

/**
 * W-HR1 §2 — the moves the server accepts, per current state.
 *
 * The rules live in `timesheets.models.ContractHours` and are enforced
 * by `POST /timesheets/contract-hours/<id>/status/`; this table only
 * OFFERS what will be accepted:
 *
 *   DRAFT    -> SAVED     submit for review
 *   SAVED    -> APPROVED  agreed
 *   SAVED    -> DRAFT     send back for a correction
 *   APPROVED -> SAVED     reopen (clears the approval)
 *
 * P-15 4.3 — §D.22: ONE button per row. The primary move is the row's
 * button; every other move (send back, delete, editing the days, the
 * fill flag) lives in the row's opened editor.
 */
const PRIMARY_ACTION: Record<Status, { to: Status; labelKey: string }> = {
  DRAFT: { to: "SAVED", labelKey: "contract_hours.action_submit" },
  SAVED: { to: "APPROVED", labelKey: "contract_hours.action_approve" },
  APPROVED: { to: "SAVED", labelKey: "contract_hours.action_reopen" },
};

interface ContractHoursRow {
  id: number;
  employee: number;
  employee_name: string;
  building: number | null;
  building_name: string | null;
  hour_type: number;
  hour_type_name: string;
  work_type: number | null;
  work_type_name: string | null;
  work_type_standard_slot: string | null;
  valid_from: string;
  valid_to: string | null;
  status: Status;
  is_locked: boolean;
  /** W12 — fill this person's weekly sheet from this agreement, every
   *  week inside the validity window (P-15 §0.2: only once APPROVED).
   *  Writable on the row's own PATCH; refused on an APPROVED row. */
  auto_fill: boolean;
  weekly_total: string;
  monday: string;
  tuesday: string;
  wednesday: string;
  thursday: string;
  friday: string;
  saturday: string;
  sunday: string;
}

/**
 * P-15 4.3 — the Agreed hours table, on the §D.22 list standard.
 *
 * The P-14 walk called the old shape "the old page in a tab": sixteen
 * columns (the STATUS column scrolled off-screen right at 1440 — the
 * S2 finding), seven of them DEAD inputs that accepted nothing until a
 * small Edit toggle was found, and five permanently unfolded filters.
 *
 * Now: SIX fact columns — Person · Building · Pattern (the seven days
 * compressed into words, "Mon–Fri · 8 h") · Total/week · Status ·
 * Valid — plus ONE button per row (the status road's next step).
 * The filters fold behind Filter. Opening a row (click) unfolds its
 * EDITOR: the seven day fields (live, no page-wide edit gate — a
 * field you can see is a field you can type in), the fill flag, and
 * the secondary moves (send back / delete). An APPROVED row's editor
 * states the immutability rule instead of offering dead controls.
 */
export function ContractHoursTab({
  companyId,
  buildings,
  employees,
  hourTypes,
}: {
  companyId: number | "";
  /** The FULL records: the picker in the bulk dialog shows a building's
   *  city and address, and an employee's email, so a name collision is
   *  resolvable. Trimming them to {id,name} here would push that
   *  problem onto the operator. */
  buildings: BuildingAdmin[];
  employees: TimesheetEmployee[];
  hourTypes: HourType[];
}) {
  const { t, i18n } = useTranslation("common");
  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";
  const formatDay = (value: string) =>
    new Date(`${value}T00:00:00`).toLocaleDateString(dateLocale, {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  const formatHours = (value: number) =>
    new Intl.NumberFormat(i18n.language, {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(value);
  const [rows, setRows] = useState<ContractHoursRow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const [workTypes, setWorkTypes] = useState<
    { id: number; name: string; standard_slot: string }[]
  >([]);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [rowToDelete, setRowToDelete] = useState<ContractHoursRow | null>(null);
  const deleteRef = useRef<ConfirmDialogHandle>(null);

  /** P-15 4.3 — the one opened row, and its typed day values. Keyed by
   *  row id so paging or a reload can never write another row's days. */
  const [openRowId, setOpenRowId] = useState<number | null>(null);
  const [dayEdits, setDayEdits] = useState<Record<Day, string> | null>(null);

  const [building, setBuilding] = useState<number | "">("");
  const [employee, setEmployee] = useState<number | "">("");
  const [hourType, setHourType] = useState<number | "">("");
  const [workTypeFilter, setWorkTypeFilter] = useState<number | "">("");
  const [validOn, setValidOn] = useState("");

  const filters = useMemo(
    () => ({
      company: companyId || undefined,
      building: building || undefined,
      employee: employee || undefined,
      hour_type: hourType || undefined,
      work_type: workTypeFilter || undefined,
      valid_on: validOn || undefined,
    }),
    [companyId, building, employee, hourType, workTypeFilter, validOn],
  );
  const activeFilterCount = [
    building,
    employee,
    hourType,
    workTypeFilter,
    validOn,
  ].filter((value) => value !== "" && value !== undefined).length;

  const requestKey = `${JSON.stringify(filters)}:${reloadKey}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    api
      .get("/timesheets/contract-hours/", { params: filters })
      .then((response) => {
        if (cancelled) return;
        setRows(response.data.results ?? response.data);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoadedKey(requestKey);
      });
    return () => {
      cancelled = true;
    };
  }, [filters, requestKey]);

  // The kind-of-work catalog for the fact line, the filter and the bulk
  // dialog. Its own read, not folded into the rows request: a catalog
  // changes when someone edits the catalog, not when a filter moves.
  useEffect(() => {
    let cancelled = false;
    api
      .get("/timesheets/work-types/", {
        params: { company: companyId || undefined, is_active: true },
      })
      .then((response) => {
        if (cancelled) return;
        const list = response.data.results ?? response.data;
        setWorkTypes(
          (list as { id: number; name: string; standard_slot?: string }[]).map(
            (row) => ({
              id: row.id,
              name: row.name,
              standard_slot: row.standard_slot ?? "",
            }),
          ),
        );
      })
      .catch(() => {
        // A missing catalog is not an error the operator can act on —
        // the fact line simply says "no kind of work", which is a
        // legal value. Failing the whole tab over it would be worse.
        if (!cancelled) setWorkTypes([]);
      });
    return () => {
      cancelled = true;
    };
  }, [companyId, reloadKey]);

  function toggleRow(row: ContractHoursRow) {
    if (openRowId === row.id) {
      setOpenRowId(null);
      setDayEdits(null);
      return;
    }
    setOpenRowId(row.id);
    setDayEdits({
      monday: row.monday,
      tuesday: row.tuesday,
      wednesday: row.wednesday,
      thursday: row.thursday,
      friday: row.friday,
      saturday: row.saturday,
      sunday: row.sunday,
    });
  }

  /**
   * W-HR1 §2 — move ONE row between the three states.
   *
   * The dedicated status endpoint, not a PATCH: the transition rules
   * live there, and it is also how an APPROVED row can be reopened
   * while staying immutable in every other respect.
   */
  async function moveStatus(row: ContractHoursRow, to: Status) {
    setBusy(true);
    setError("");
    try {
      await api.post(`/timesheets/contract-hours/${row.id}/status/`, {
        status: to,
      });
      setReloadKey((n) => n + 1);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  /** The fill flag, written on its own, immediately: it is a switch,
   *  not a typed value. */
  async function toggleAutoFill(row: ContractHoursRow) {
    setBusy(true);
    setError("");
    try {
      await api.patch(`/timesheets/contract-hours/${row.id}/`, {
        auto_fill: !row.auto_fill,
      });
      setReloadKey((n) => n + 1);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  /** P-15 4.3 — save the opened row's days. One row, one PATCH. */
  async function savePattern(row: ContractHoursRow) {
    if (!dayEdits) return;
    setBusy(true);
    setError("");
    try {
      const payload: Record<string, string> = {};
      for (const day of PATTERN_DAYS) payload[day] = String(dayEdits[day]);
      await api.patch(`/timesheets/contract-hours/${row.id}/`, payload);
      setOpenRowId(null);
      setDayEdits(null);
      setReloadKey((n) => n + 1);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(row: ContractHoursRow) {
    setBusy(true);
    setError("");
    try {
      await api.delete(`/timesheets/contract-hours/${row.id}/`);
      setRowToDelete(null);
      setOpenRowId(null);
      setDayEdits(null);
      setReloadKey((n) => n + 1);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  const statusTag = (row: ContractHoursRow) =>
    row.status === "APPROVED"
      ? "cell-tag-open"
      : row.status === "SAVED"
        ? "cell-tag-normal"
        : "cell-tag-muted";

  const patternWords = (row: ContractHoursRow) =>
    patternLabel(
      row,
      (day) => t(`contract_hours.day_${day}`),
      (hours) => t("contract_hours.pattern_hours", { hours: formatHours(hours) }),
    );

  return (
    <div data-testid="contract-hours-tab">
      {error && (
        <div className="alert-error" style={{ marginBottom: 12 }} role="alert">
          {error}
        </div>
      )}

      <div className="hours-tiles-head">
        <div>
          <span className="hours-tiles-title">{t("contract_hours.title")}</span>
          {/* Sprint 172 §3 — the counterpart line to the Entries tab's. */}
          <div className="section-head-sub">
            {t("contract_hours.subtitle")}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => setBulkOpen(true)}
            data-testid="contract-hours-bulk-open"
          >
            <Plus size={14} strokeWidth={2.5} />
            {t("contract_hours.bulk_open")}
          </button>
        </div>
      </div>

      {/* Sprint 169 §2 — said, not left blank. */}
      {workTypes.length === 0 && (
        <p className="muted small" data-testid="contract-hours-no-work-types">
          {t("work_types.none_yet")}
        </p>
      )}

      {/* P-15 4.3 — the five filters fold behind Filter (§D.22); the
          summary counts what is on so a narrowed list never looks
          like the whole one. */}
      <details
        className="filter-fold"
        open={activeFilterCount > 0}
        data-testid="contract-hours-filter-fold"
      >
        <summary className="filter-fold-summary" data-testid="contract-hours-filter-toggle">
          <SlidersHorizontal size={14} strokeWidth={2.4} aria-hidden="true" />
          {t("contract_hours.filter_fold")}
          {activeFilterCount > 0 && (
            <span className="filter-fold-count">
              {t("contract_hours.filter_fold_active", {
                count: activeFilterCount,
              })}
            </span>
          )}
        </summary>
        <form className="filter-bar" onSubmit={(event) => event.preventDefault()}>
        <div className="filter-field">
          <span className="filter-label">{t("building")}</span>
          <select
            className="filter-control"
            value={building}
            onChange={(e) =>
              setBuilding(e.target.value === "" ? "" : Number(e.target.value))
            }
            data-testid="contract-hours-filter-building"
          >
            <option value="">{t("contract_hours.all_buildings")}</option>
            {buildings.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <span className="filter-label">{t("contract_hours.employee")}</span>
          <select
            className="filter-control"
            value={employee}
            onChange={(e) =>
              setEmployee(e.target.value === "" ? "" : Number(e.target.value))
            }
            data-testid="contract-hours-filter-employee"
          >
            <option value="">{t("contract_hours.all_employees")}</option>
            {employees.map((person) => (
              <option key={person.id} value={person.id}>
                {person.full_name || person.email}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <span className="filter-label">{t("contract_hours.hour_type")}</span>
          <select
            className="filter-control"
            value={hourType}
            onChange={(e) =>
              setHourType(e.target.value === "" ? "" : Number(e.target.value))
            }
            data-testid="contract-hours-filter-hour-type"
          >
            <option value="">{t("contract_hours.all_hour_types")}</option>
            {hourTypes.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <span className="filter-label">{t("contract_hours.work_type")}</span>
          <select
            className="filter-control"
            value={workTypeFilter}
            onChange={(e) =>
              setWorkTypeFilter(
                e.target.value === "" ? "" : Number(e.target.value),
              )
            }
            data-testid="contract-hours-filter-work-type"
          >
            <option value="">{t("contract_hours.all_work_types")}</option>
            {workTypes.map((type) => (
              <option key={type.id} value={type.id}>
                {workTypeLabel(type.name, type.standard_slot, t)}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <span className="filter-label">{t("contract_hours.valid_on")}</span>
          <input
            className="filter-control"
            type="date"
            value={validOn}
            onChange={(e) => setValidOn(e.target.value)}
            data-testid="contract-hours-filter-valid-on"
          />
        </div>
        </form>
      </details>

      {loading && (
        <div
          className="skeleton-table"
          aria-hidden="true"
          data-testid="contract-hours-skeleton"
        >
          {[0, 1, 2, 3].map((row) => (
            <div className="skeleton-row" key={row}>
              <span className="skeleton-line" />
              <span className="skeleton-line" />
              <span className="skeleton-line" />
              <span className="skeleton-line" />
              <span className="skeleton-line" />
              <span className="skeleton-line" />
            </div>
          ))}
        </div>
      )}

      <BoundedList
        size="lg"
        count={Math.max(1, rows.length)}
        ariaLabel={t("contract_hours.tab")}
        testIdPrefix="contract-hours"
      >
      <div className="table-wrap admin-list-wrap">
        <table className="data-table data-table-dense data-table-fit">
          <thead>
            {/* P-15 4.3 — six facts and one button. STATUS sits beside
                VALID on every width (the S2 finding: it was column 14
                of 16, off-screen right at 1440). */}
            <tr>
              <th>{t("contract_hours.employee")}</th>
              <th>{t("building")}</th>
              <th>{t("contract_hours.pattern")}</th>
              <th className="contract-num">{t("contract_hours.total_week")}</th>
              <th>{t("status")}</th>
              <th>{t("contract_hours.validity")}</th>
              <th>{t("contract_hours.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const opened = openRowId === row.id;
              const primary = PRIMARY_ACTION[row.status];
              return (
              <Fragment key={row.id}>
              <tr
                data-testid={`contract-hours-row-${row.id}`}
                onClick={() => toggleRow(row)}
                style={{ cursor: "pointer" }}
                aria-expanded={opened}
              >
                <td className="td-subject">{row.employee_name}</td>
                <td>
                  {row.building_name ?? (
                    <span className="muted-empty">
                      {t("contract_hours.no_building")}
                    </span>
                  )}
                </td>
                <td>
                  <span data-testid={`contract-hours-pattern-${row.id}`}>
                    {patternWords(row) ?? (
                      <span className="muted-empty">
                        {t("contract_hours.no_days")}
                      </span>
                    )}
                  </span>
                  {/* The row's remaining facts, one muted line: what
                      the hours are OF, the report label, and whether
                      the pattern fills Enter hours. */}
                  <div className="muted small">
                    {hourTypeLabelFrom(
                      row.hour_type_name,
                      hourTypes.find((type) => type.id === row.hour_type)
                        ?.standard_slot,
                      t,
                    )}
                    {row.work_type_name
                      ? ` · ${workTypeLabel(row.work_type_name, row.work_type_standard_slot, t)}`
                      : ""}
                    {row.auto_fill
                      ? ` · ${t("contract_hours.auto_fill_column")}`
                      : ""}
                  </div>
                </td>
                <td className="contract-num">
                  <strong>{formatHours(Number(row.weekly_total) || 0)}</strong>
                </td>
                <td>
                  <span
                    className={`cell-tag ${statusTag(row)}`}
                    data-testid={`contract-hours-status-${row.id}`}
                  >
                    {t(`contract_hours.status_${row.status}`)}
                  </span>
                </td>
                <td className="td-date">
                  {row.valid_to
                    ? t("contract_hours.validity_range", {
                        from: formatDay(row.valid_from),
                        to: formatDay(row.valid_to),
                      })
                    : t("contract_hours.validity_open", {
                        from: formatDay(row.valid_from),
                      })}
                </td>
                <td onClick={(event) => event.stopPropagation()}>
                  {/* §D.22 — ONE button: the road's next step. */}
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => void moveStatus(row, primary.to)}
                    disabled={busy}
                    data-testid={`contract-hours-move-${row.id}-${primary.to}`}
                  >
                    {t(primary.labelKey)}
                  </button>
                </td>
              </tr>
              {opened && (
                <tr
                  key={`${row.id}-editor`}
                  data-testid={`contract-hours-editor-${row.id}`}
                >
                  <td colSpan={7} onClick={(event) => event.stopPropagation()}>
                    {row.is_locked ? (
                      /* An APPROVED row is immutable server-side
                         (`contract_hours_approved_immutable`); the
                         editor says the rule instead of offering
                         controls that 400. */
                      <p className="muted small" style={{ margin: "8px 0" }}>
                        {t("contract_hours.locked_note")}
                      </p>
                    ) : (
                      <div
                        style={{
                          display: "flex",
                          flexWrap: "wrap",
                          gap: 10,
                          alignItems: "flex-end",
                          padding: "8px 0",
                        }}
                      >
                        {PATTERN_DAYS.map((day) => (
                          <label key={day} className="muted small" style={{ display: "grid", gap: 4 }}>
                            {t(`contract_hours.day_${day}`)}
                            <input
                              className="field-input hours-week-grid-cell"
                              type="text"
                              inputMode="decimal"
                              value={dayEdits?.[day] ?? row[day]}
                              onChange={(event) =>
                                setDayEdits((current) => ({
                                  ...(current ?? {
                                    monday: row.monday,
                                    tuesday: row.tuesday,
                                    wednesday: row.wednesday,
                                    thursday: row.thursday,
                                    friday: row.friday,
                                    saturday: row.saturday,
                                    sunday: row.sunday,
                                  }),
                                  [day]: event.target.value,
                                }))
                              }
                              disabled={busy}
                              aria-label={`${row.employee_name} ${t(`contract_hours.day_${day}`)}`}
                              data-testid={`contract-hours-cell-${row.id}-${day}`}
                            />
                          </label>
                        ))}
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          onClick={() => void savePattern(row)}
                          disabled={busy}
                          data-testid={`contract-hours-save-${row.id}`}
                        >
                          {t("contract_hours.save_pattern")}
                        </button>
                      </div>
                    )}
                    <div
                      style={{
                        display: "flex",
                        flexWrap: "wrap",
                        gap: 12,
                        alignItems: "center",
                      }}
                    >
                      <label className="muted small" style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                        <input
                          type="checkbox"
                          checked={row.auto_fill}
                          disabled={row.is_locked || busy}
                          onChange={() => void toggleAutoFill(row)}
                          data-testid={`contract-hours-auto-fill-${row.id}`}
                        />
                        {t("contract_hours.auto_fill_label")}
                      </label>
                      <span className="muted small">
                        {t("contract_hours.auto_fill_hint")}
                      </span>
                      {row.status === "SAVED" && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => void moveStatus(row, "DRAFT")}
                          disabled={busy}
                          data-testid={`contract-hours-move-${row.id}-DRAFT`}
                        >
                          {t("contract_hours.action_send_back")}
                        </button>
                      )}
                      {/* An APPROVED agreement is not deleted from
                          here. Correcting one writes a NEW row from a
                          date; Reopen (the row's button) is the way
                          back. */}
                      {!row.is_locked && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => {
                            setRowToDelete(row);
                            deleteRef.current?.open();
                          }}
                          disabled={busy}
                          data-testid={`contract-hours-delete-${row.id}`}
                        >
                          {t("contract_hours.delete")}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              )}
              </Fragment>
              );
            })}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={7}>
                  <div className="empty-state" data-testid="contract-hours-empty">
                    <div className="empty-title">{t("contract_hours.empty")}</div>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => setBulkOpen(true)}
                      data-testid="contract-hours-empty-bulk-open"
                    >
                      {t("contract_hours.bulk_open")}
                    </button>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      </BoundedList>

      {bulkOpen && (
        <ContractHoursBulkDialog
          employees={employees}
          buildings={buildings}
          hourTypes={hourTypes.filter((type) => type.is_active)}
          workTypes={workTypes}
          companyId={companyId || null}
          onClose={() => setBulkOpen(false)}
          onSaved={() => {
            setBulkOpen(false);
            setReloadKey((n) => n + 1);
          }}
        />
      )}

      {/* Rendered unconditionally and driven entirely through the ref —
          CLAUDE.md's rule for the native dialog, and the reason a
          Sprint 118 page went inert. */}
      <ConfirmDialog
        ref={deleteRef}
        title={t("contract_hours.delete_title")}
        body={t("contract_hours.delete_body", {
          name: rowToDelete?.employee_name ?? "",
        })}
        confirmLabel={t("contract_hours.delete")}
        onConfirm={() => {
          if (rowToDelete) void remove(rowToDelete);
        }}
      />
    </div>
  );
}
