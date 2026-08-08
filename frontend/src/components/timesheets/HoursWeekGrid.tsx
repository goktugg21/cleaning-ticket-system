/**
 * Sprint 155 §5 — enter a whole week, for SEVERAL people, at once.
 *
 * Sprint 154 shipped this grid with one fault the owner put his finger
 * on precisely: the Hours page's employee FILTER was also the target of
 * "enter a week". One single-select control answered two different
 * questions — "whose rows am I looking at" and "whose week am I
 * writing" — so changing the filter silently changed what Save would
 * write, and entering two people's weeks was impossible without
 * switching in between.
 *
 * The fix is structural, not cosmetic. This component no longer knows
 * anything about the filter: it renders a BLOCK per employee it is
 * given, and the caller owns which employees those are. On the admin
 * page that is a multi-select of its own; on My hours it is exactly one
 * person, which is why the same component serves both.
 *
 * Shape, per employee block: one ROW per (hour type, building) pair, one
 * COLUMN per day Mon-Sun, a row total, an employee total, and a grand
 * total across every block. "Apply to all" fills one value across every
 * day of every selected employee — the single most useful control in
 * the reference system the owner sent, and the reason multi-select is
 * worth having at all.
 *
 * What is deliberately NOT copied from that reference system: contract
 * hours, "valid from" windows, and a work type on the hour row. We have
 * no such model. A `TimeEntry` is employee + date + hour type + hours +
 * optional building + note, and inventing the rest here would put a
 * second, fictional model in front of the real one.
 *
 * Date handling goes through `lib/isoWeek.ts` exclusively — it already
 * matches Python's `isocalendar()`, and `toDateString` formats in LOCAL
 * time. `toISOString()` is never used: it converts to UTC first, so
 * anywhere east of Greenwich a local midnight becomes the previous day
 * and the entry lands in the wrong day, sometimes the wrong week.
 *
 * The server stays the authority. A closed week is refused there
 * (`week_closed`) and this grid surfaces that message VERBATIM rather
 * than paraphrasing it. The read-only state below is a courtesy so the
 * operator is not invited to type into cells that cannot be saved — it
 * is not the enforcement.
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { saveWeekGrid } from "../../api/timesheets";
import type { HourType, TimeEntry } from "../../api/timesheets.types";
import type { BuildingAdmin } from "../../api/types";
import { isoWeekDays, toDateString } from "../../lib/isoWeek";
import type { IsoWeek } from "../../lib/isoWeek";

/** One person the grid writes for. */
export interface GridEmployee {
  id: number;
  name: string;
}

/** One row inside one employee's block. */
interface GridRow {
  key: string;
  hourTypeId: number | "";
  buildingId: number | "";
  /** "YYYY-MM-DD" -> the raw text in the cell. Text, not number, so a
   *  half-typed "1." survives a re-render. */
  cells: Record<string, string>;
}

function rowKey(hourTypeId: number | "", buildingId: number | "") {
  return `${hourTypeId}:${buildingId}`;
}

/** The edit map's key. Employee FIRST, because the same (hour type,
 *  building) row exists under several people and their cells must never
 *  collide — that collision is the multi-employee version of the exact
 *  bug this sprint is fixing. */
function cellKey(employeeId: number, row: string, day: string) {
  return `${employeeId}|${row}|${day}`;
}

function parseHours(raw: string): number {
  // Accept both "7,5" and "7.5": the Dutch keyboard produces a comma and
  // an operator typing their own decimal separator is not making a
  // mistake.
  const cleaned = raw.trim().replace(",", ".");
  if (cleaned === "") return 0;
  const value = Number(cleaned);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

function formatTotal(value: number): string {
  return value.toFixed(2).replace(/\.00$/, "");
}

export function HoursWeekGrid({
  week,
  employees,
  companyId,
  hourTypes,
  buildings,
  entriesByEmployee,
  weekClosed,
  onSaved,
}: {
  week: IsoWeek;
  /** Whose weeks this grid writes. Empty = nothing chosen yet. */
  employees: GridEmployee[];
  companyId?: number | null;
  hourTypes: HourType[];
  buildings: BuildingAdmin[];
  /** The week's EXISTING entries per employee, so the grid opens
   *  pre-filled. Missing key = that employee's week is empty. */
  entriesByEmployee: Record<number, TimeEntry[]>;
  weekClosed: boolean;
  onSaved: () => void | Promise<void>;
}) {
  const { t, i18n } = useTranslation("common");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [banner, setBanner] = useState("");
  // Rows the operator added that have no entry behind them yet, keyed by
  // employee.
  const [extraRows, setExtraRows] = useState<Record<number, GridRow[]>>({});
  const [edits, setEdits] = useState<Record<string, string>>({});

  // The apply-to-all bar's own inputs. Not part of the grid's data.
  const [bulkHourType, setBulkHourType] = useState<number | "">("");
  const [bulkBuilding, setBulkBuilding] = useState<number | "">("");
  const [bulkHours, setBulkHours] = useState("");
  const [bulkScope, setBulkScope] = useState<"week" | "weekdays">("weekdays");

  const days = useMemo(() => isoWeekDays(week), [week]);
  const dayKeys = useMemo(() => days.map(toDateString), [days]);

  // Rows DERIVED from the existing entries, plus whatever the operator
  // added. Derived rather than held in state, so re-fetching after a
  // save cannot leave a stale grid behind — and so no effect has to sync
  // props into state (CLAUDE.md §3).
  const rowsByEmployee: Record<number, GridRow[]> = useMemo(() => {
    const out: Record<number, GridRow[]> = {};
    for (const employee of employees) {
      const byKey = new Map<string, GridRow>();
      for (const entry of entriesByEmployee[employee.id] ?? []) {
        const key = rowKey(entry.hour_type, entry.building ?? "");
        if (!byKey.has(key)) {
          byKey.set(key, {
            key,
            hourTypeId: entry.hour_type,
            buildingId: entry.building ?? "",
            cells: {},
          });
        }
        byKey.get(key)!.cells[entry.date] = String(entry.hours);
      }
      for (const extra of extraRows[employee.id] ?? []) {
        if (!byKey.has(extra.key)) byKey.set(extra.key, extra);
      }
      out[employee.id] = [...byKey.values()];
    }
    return out;
  }, [employees, entriesByEmployee, extraRows]);

  const cellValue = (employeeId: number, row: GridRow, dayKey: string) =>
    edits[cellKey(employeeId, row.key, dayKey)] ?? row.cells[dayKey] ?? "";

  const setCell = (
    employeeId: number,
    row: GridRow,
    dayKey: string,
    value: string,
  ) =>
    setEdits((current) => ({
      ...current,
      [cellKey(employeeId, row.key, dayKey)]: value,
    }));

  const rowTotal = (employeeId: number, row: GridRow) =>
    dayKeys.reduce(
      (sum, key) => sum + parseHours(cellValue(employeeId, row, key)),
      0,
    );

  const employeeTotal = (employeeId: number) =>
    (rowsByEmployee[employeeId] ?? []).reduce(
      (sum, row) => sum + rowTotal(employeeId, row),
      0,
    );

  const grandTotal = employees.reduce(
    (sum, employee) => sum + employeeTotal(employee.id),
    0,
  );

  const hourTypeName = (id: number | "") =>
    hourTypes.find((h) => h.id === id)?.name ?? String(id);

  const buildingName = (id: number | "") =>
    id === ""
      ? t("hours_week_grid.no_building")
      : (buildings.find((b) => b.id === id)?.name ?? String(id));

  function addRow(employeeId: number) {
    const used = new Set((rowsByEmployee[employeeId] ?? []).map((r) => r.key));
    // First hour type that does not already have a no-building row.
    const candidate = hourTypes.find((h) => !used.has(rowKey(h.id, "")));
    if (!candidate) return;
    setExtraRows((current) => ({
      ...current,
      [employeeId]: [
        ...(current[employeeId] ?? []),
        {
          key: rowKey(candidate.id, ""),
          hourTypeId: candidate.id,
          buildingId: "",
          cells: {},
        },
      ],
    }));
  }

  /** The reference system's most useful control: one value, every day,
   *  every selected person. It writes into `edits` and into `extraRows`
   *  for the pairs that do not exist yet — it does NOT save. Nothing
   *  here reaches the server until the operator presses Save, so a
   *  mis-click is undone by not saving. */
  function applyToAll() {
    if (bulkHourType === "") return;
    const targetDays =
      bulkScope === "weekdays" ? dayKeys.slice(0, 5) : dayKeys;
    const key = rowKey(bulkHourType, bulkBuilding);

    setExtraRows((current) => {
      const next = { ...current };
      for (const employee of employees) {
        const exists = (rowsByEmployee[employee.id] ?? []).some(
          (r) => r.key === key,
        );
        if (exists) continue;
        next[employee.id] = [
          ...(next[employee.id] ?? []),
          {
            key,
            hourTypeId: bulkHourType,
            buildingId: bulkBuilding,
            cells: {},
          },
        ];
      }
      return next;
    });

    setEdits((current) => {
      const next = { ...current };
      for (const employee of employees) {
        for (const day of targetDays) {
          next[cellKey(employee.id, key, day)] = bulkHours;
        }
      }
      return next;
    });
  }

  async function handleSave() {
    if (employees.length === 0) return;
    setBusy(true);
    setError("");
    setBanner("");

    // Send only the cells that CHANGED. A grid that resent every cell
    // would rewrite untouched rows — pointless writes, and every one of
    // them re-snapshots the multiplier for no reason.
    const cells: {
      employee: number;
      hour_type: number;
      building: number | null;
      date: string;
      hours: string;
    }[] = [];
    for (const employee of employees) {
      for (const row of rowsByEmployee[employee.id] ?? []) {
        if (row.hourTypeId === "") continue;
        for (const dayKey of dayKeys) {
          const key = cellKey(employee.id, row.key, dayKey);
          if (!(key in edits)) continue;
          const original = row.cells[dayKey] ?? "";
          if (parseHours(edits[key]) === parseHours(original)) continue;
          cells.push({
            employee: employee.id,
            hour_type: row.hourTypeId,
            building: row.buildingId === "" ? null : row.buildingId,
            date: dayKey,
            // "0" is meaningful: it CLEARS the cell server-side.
            hours: String(parseHours(edits[key])),
          });
        }
      }
    }

    if (cells.length === 0) {
      setBanner(t("hours_week_grid.no_changes"));
      setBusy(false);
      return;
    }

    try {
      // ONE request for the whole grid, however many people are in it.
      // The endpoint is all-or-nothing, so a week that half-saved across
      // three employees — leaving the operator to work out which — is
      // not a state this can reach.
      const result = await saveWeekGrid({
        company: companyId ?? undefined,
        iso_year: week.isoYear,
        iso_week: week.isoWeek,
        cells,
      });
      const changed = result.created + result.updated + result.deleted;
      setEdits({});
      setExtraRows({});
      setBanner(t("hours_week_grid.saved", { count: changed }));
      await onSaved();
    } catch (err) {
      // Verbatim — including the server's own `week_closed` wording.
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  const dayLabel = (date: Date) =>
    date.toLocaleDateString(i18n.language === "nl" ? "nl-NL" : "en-US", {
      weekday: "short",
      day: "2-digit",
      month: "2-digit",
    });

  if (employees.length === 0) {
    return (
      <p className="muted small" data-testid="hours-week-grid-no-employee">
        {t("hours_week_grid.pick_employee")}
      </p>
    );
  }

  if (hourTypes.length === 0) {
    return (
      <p className="muted small" data-testid="hours-week-grid-no-hour-types">
        {t("hours_week_grid.no_hour_types")}
      </p>
    );
  }

  return (
    <div data-testid="hours-week-grid">
      <p className="muted small" style={{ marginTop: 0, marginBottom: 12 }}>
        {t("hours_week_grid.intro")}
      </p>

      {weekClosed && (
        <div
          className="alert-info"
          role="status"
          style={{ marginBottom: 12 }}
          data-testid="hours-week-grid-closed"
        >
          {t("hours_week_grid.week_closed")}
        </div>
      )}

      {error && (
        <div
          className="alert-error"
          role="alert"
          style={{ marginBottom: 12 }}
          data-testid="hours-week-grid-error"
        >
          {error}
        </div>
      )}

      {banner && (
        <div
          className="alert-info"
          role="status"
          style={{ marginBottom: 12 }}
          data-testid="hours-week-grid-banner"
        >
          {banner}
        </div>
      )}

      {/* Apply to all. Offered whenever the grid has more than one row's
          worth of work to do — which for a single person is still the
          fastest way to file a normal week. */}
      <div className="hours-week-apply-bar" data-testid="hours-week-apply-bar">
        <span className="hours-week-apply-label">
          {t("hours_week_grid.apply_to_all")}
        </span>
        <select
          className="field-input"
          value={bulkHourType === "" ? "" : String(bulkHourType)}
          onChange={(event) =>
            setBulkHourType(
              event.target.value === "" ? "" : Number(event.target.value),
            )
          }
          disabled={busy || weekClosed}
          aria-label={t("hours_week_grid.hour_type")}
          data-testid="hours-week-apply-hour-type"
        >
          <option value="">{t("hours_week_grid.hour_type")}</option>
          {hourTypes.map((hourType) => (
            <option key={hourType.id} value={hourType.id}>
              {hourType.name}
            </option>
          ))}
        </select>
        <select
          className="field-input"
          value={bulkBuilding === "" ? "" : String(bulkBuilding)}
          onChange={(event) =>
            setBulkBuilding(
              event.target.value === "" ? "" : Number(event.target.value),
            )
          }
          disabled={busy || weekClosed}
          aria-label={t("hours_week_grid.building")}
          data-testid="hours-week-apply-building"
        >
          <option value="">{t("hours_week_grid.no_building")}</option>
          {buildings.map((building) => (
            <option key={building.id} value={building.id}>
              {building.name}
            </option>
          ))}
        </select>
        <input
          className="field-input"
          type="text"
          inputMode="decimal"
          value={bulkHours}
          onChange={(event) => setBulkHours(event.target.value)}
          placeholder={t("hours_week_grid.hours_placeholder")}
          disabled={busy || weekClosed}
          aria-label={t("hours_week_grid.apply_hours")}
          style={{ width: 90 }}
          data-testid="hours-week-apply-hours"
        />
        <select
          className="field-input"
          value={bulkScope}
          onChange={(event) =>
            setBulkScope(event.target.value as "week" | "weekdays")
          }
          disabled={busy || weekClosed}
          aria-label={t("hours_week_grid.apply_scope")}
          data-testid="hours-week-apply-scope"
        >
          <option value="weekdays">
            {t("hours_week_grid.apply_scope_weekdays")}
          </option>
          <option value="week">{t("hours_week_grid.apply_scope_week")}</option>
        </select>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={applyToAll}
          disabled={busy || weekClosed || bulkHourType === ""}
          data-testid="hours-week-apply-button"
        >
          {t("hours_week_grid.apply_button", { count: employees.length })}
        </button>
      </div>

      {employees.map((employee) => {
        const rows = rowsByEmployee[employee.id] ?? [];
        return (
          <div
            key={employee.id}
            className="hours-week-block"
            data-testid={`hours-week-block-${employee.id}`}
          >
            <div className="hours-week-block-head">
              <span className="hours-week-block-name">{employee.name}</span>
              <span
                className="hours-week-block-total"
                data-testid={`hours-week-employee-total-${employee.id}`}
              >
                {t("hours_week_grid.employee_total", {
                  hours: formatTotal(employeeTotal(employee.id)),
                })}
              </span>
            </div>

            <div className="table-wrap">
              <table className="data-table data-table-dense hours-week-grid-table">
                <thead>
                  <tr>
                    <th>{t("hours_week_grid.hour_type")}</th>
                    <th>{t("hours_week_grid.building")}</th>
                    {days.map((day, index) => (
                      <th key={dayKeys[index]} style={{ textAlign: "right" }}>
                        {dayLabel(day)}
                      </th>
                    ))}
                    <th style={{ textAlign: "right" }}>
                      {t("hours_week_grid.total")}
                    </th>
                    <th aria-label={t("hours_week_grid.remove_row")} />
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 && (
                    <tr>
                      <td colSpan={dayKeys.length + 4} className="muted small">
                        {t("hours_week_grid.empty_block")}
                      </td>
                    </tr>
                  )}
                  {rows.map((row) => (
                    <tr key={row.key}>
                      <td className="td-subject">
                        {hourTypeName(row.hourTypeId)}
                      </td>
                      <td>{buildingName(row.buildingId)}</td>
                      {dayKeys.map((dayKey, index) => (
                        <td key={dayKey} style={{ textAlign: "right" }}>
                          <input
                            className="field-input hours-week-grid-cell"
                            type="text"
                            inputMode="decimal"
                            value={cellValue(employee.id, row, dayKey)}
                            onChange={(event) =>
                              setCell(
                                employee.id,
                                row,
                                dayKey,
                                event.target.value,
                              )
                            }
                            disabled={busy || weekClosed}
                            aria-label={t("hours_week_grid.cell_label_person", {
                              person: employee.name,
                              hourType: hourTypeName(row.hourTypeId),
                              day: dayLabel(days[index]),
                            })}
                            data-testid={`hours-week-cell-${employee.id}-${row.key}-${dayKey}`}
                          />
                        </td>
                      ))}
                      <td
                        style={{ textAlign: "right", fontWeight: 700 }}
                        data-testid={`hours-week-row-total-${employee.id}-${row.key}`}
                      >
                        {formatTotal(rowTotal(employee.id, row))}
                      </td>
                      <td>
                        {/* An added-but-unsaved row can be dropped; a row
                            that exists on the server is cleared by
                            zeroing its cells, not by removing it from
                            the grid — removing it here would look like a
                            delete that never happened. */}
                        {(extraRows[employee.id] ?? []).some(
                          (r) => r.key === row.key,
                        ) && (
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            onClick={() =>
                              setExtraRows((current) => ({
                                ...current,
                                [employee.id]: (
                                  current[employee.id] ?? []
                                ).filter((r) => r.key !== row.key),
                              }))
                            }
                            disabled={busy}
                          >
                            {t("hours_week_grid.remove_row")}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => addRow(employee.id)}
              disabled={busy || weekClosed}
              style={{ marginTop: 8 }}
              data-testid={`hours-week-add-row-${employee.id}`}
            >
              {t("hours_week_grid.add_row")}
            </button>
          </div>
        );
      })}

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 8,
          marginTop: 16,
          flexWrap: "wrap",
        }}
      >
        <span
          className="hours-week-grand-total"
          data-testid="hours-week-total"
        >
          {t("hours_week_grid.grand_total", {
            hours: formatTotal(grandTotal),
            count: employees.length,
          })}
        </span>
        {/* ONE Save for the whole grid — every employee, every row. */}
        <button
          type="button"
          className="btn btn-primary"
          onClick={handleSave}
          disabled={busy || weekClosed}
          data-testid="hours-week-grid-save"
        >
          {busy ? t("admin_form.saving") : t("hours_week_grid.save")}
        </button>
      </div>
    </div>
  );
}
