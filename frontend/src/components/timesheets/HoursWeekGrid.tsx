/**
 * Sprint 159 §1 — the week grid, rebuilt to the reference shape.
 *
 * ## What this is now
 *
 * ONE table. One row per (employee, building, hour type), seven day
 * columns, a row total, a grand total, Save. That is the shape of the
 * system the owner sent, and it is what four previous rounds kept
 * adding controls around instead of arriving at.
 *
 * ## What was REMOVED, and why removal was the fix
 *
 * Sprints 155-158 each answered a complaint by adding a control, and
 * the result was three surfaces that filled cells and two that added
 * rows:
 *
 *  - a per-employee BLOCK with its own table, name row and total
 *    (155 §5) — now one table with an Employee column;
 *  - a per-employee "fill this weekday for all my rows" input row
 *    (156 §6d);
 *  - a GLOBAL "fill this weekday for everybody" row above the blocks
 *    (158 §5b) — the same idea a second time, one level up;
 *  - row-selection checkboxes plus a second hours box and an "apply to
 *    N selected" button (158 §5e) — a third way to fill;
 *  - a per-employee "Add row" button (155) alongside the bar's own.
 *
 * Nothing they did is lost: Fill writes a value across the rows it
 * matches, which is what all three fill surfaces were for, and Add row
 * adds rows, which is what both add surfaces were for. Sprint 158's
 * split of those two verbs was right and is kept — it is the one thing
 * from those rounds that survives unchanged.
 *
 * ## The bug the owner reported ("bulk adding works oddly")
 *
 * Reproduced on the built app before it was touched, driving the real
 * UI: set the week up with two employees and two buildings, choose an
 * hour type in the bar, leave the building select on its default, press
 * **Add row** — the banner says *"0 rows added"* and nothing happens.
 *
 * The cause: Sprint 158 §5c relabelled the building select's empty
 * option "Every building" so FILL would read it as "do not narrow", and
 * left ADD ROW reading the same value as "no building". So one control
 * meant two different things depending on which button you pressed.
 * With a "no building" row already seeded, Add row found nothing
 * missing and reported zero; without one, it would have silently
 * created a *no-building* row while the control said "every building".
 *
 * The fix is to give the empty value ONE meaning, "all buildings", in
 * both directions: Fill does not narrow, and Add row adds the hour type
 * at every building already in the grid. "No building" is now its own
 * explicit option rather than a value you reach by choosing nothing.
 *
 * ## Rules that do not bend
 *
 * Every cell is written through the normal `TimeEntry` save path
 * (`saveWeekGrid` -> the serializer), so `multiplier_snapshot` and the
 * derived `iso_year`/`iso_week` are written server-side. A closed week
 * is refused THERE (`week_closed`) and this grid surfaces that message
 * verbatim; the read-only state below is a courtesy, not the
 * enforcement.
 *
 * Date handling goes through `lib/isoWeek.ts` exclusively — it matches
 * Python's `isocalendar()` and `toDateString` formats in LOCAL time.
 * `toISOString()` is never used: it converts to UTC first, so east of
 * Greenwich a local midnight becomes the previous day and the entry
 * lands in the wrong day, sometimes the wrong week.
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

/**
 * The bar's "no building" choice. `TimeEntry.building` is nullable BY
 * DESIGN and stays that way — this is a UI value for choosing null, and
 * it never leaves this component.
 *
 * It is a STRING sentinel and not `""` on purpose: `""` is "all
 * buildings", and the whole reported bug was those two sharing a value.
 */
const NO_BUILDING = "none";

/** One row of the table: one employee, one hour type, one building. */
interface GridRow {
  /** Unique across the table. Employee first, because the same (hour
   *  type, building) pair exists under several people. */
  id: string;
  employeeId: number;
  employeeName: string;
  /** The (hourType, building) part of the id — the row's identity
   *  WITHIN one employee, which is what Add row and Fill match on. */
  key: string;
  hourTypeId: number | "";
  buildingId: number | "";
  /** True for a row the SETUP or Add row created, which has no saved
   *  entry behind it: those are the only rows that may be retargeted or
   *  simply dropped. */
  added?: boolean;
  /** "YYYY-MM-DD" -> the raw text of the saved entry. Text, not number,
   *  so a half-typed "1." survives a re-render. */
  cells: Record<string, string>;
}

function rowKey(hourTypeId: number | "", buildingId: number | "") {
  return `${hourTypeId}:${buildingId}`;
}

function rowId(employeeId: number, key: string) {
  return `${employeeId}|${key}`;
}

function cellKey(rowIdValue: string, day: string) {
  return `${rowIdValue}|${day}`;
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
  seedBuildingIds,
  seedHourTypeIds,
  weekClosed,
  onSaved,
  onCancel,
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
  /** The buildings chosen in the setup. `null` is a legitimate member
   *  ("no building"), which is why this is `(number | null)[]`. Rows
   *  that ALREADY have entries this week are reconciled rather than
   *  duplicated. */
  seedBuildingIds: (number | null)[];
  /** The hour types chosen in the setup. Empty falls back to the first
   *  active type. */
  seedHourTypeIds: number[];
  weekClosed: boolean;
  onSaved: (changed: number) => void | Promise<void>;
  /** Rendered next to Save when given. The modal supplies it so the
   *  footer reads "Cancel / Save"; My hours does not. */
  onCancel?: () => void;
}) {
  const { t, i18n } = useTranslation("common");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [banner, setBanner] = useState("");
  /** Rows the operator added, keyed by employee. No saved entry behind
   *  them yet. */
  const [extraRows, setExtraRows] = useState<Record<number, GridRow[]>>({});
  const [edits, setEdits] = useState<Record<string, string>>({});

  // The Fill / Add row bar's own inputs. Not part of the grid's data.
  const [barHourType, setBarHourType] = useState<number | "">("");
  const [barBuilding, setBarBuilding] = useState<string>("");
  const [barHours, setBarHours] = useState("");
  const [barScope, setBarScope] = useState<"week" | "weekdays">("weekdays");

  // The hour type a SEEDED row opens on: the first active type, which
  // for every company that has run the standard set is "Normale uren".
  const defaultHourType = hourTypes[0];

  const days = useMemo(() => isoWeekDays(week), [week]);
  const dayKeys = useMemo(() => days.map(toDateString), [days]);

  /**
   * Every row of the table, DERIVED from the existing entries plus the
   * setup's seeds plus whatever was added. Derived rather than held in
   * state, so re-fetching after a save cannot leave a stale grid behind
   * — and so no effect has to sync props into state (CLAUDE.md §3).
   */
  const rows: GridRow[] = useMemo(() => {
    const seedTypes =
      seedHourTypeIds.length > 0
        ? hourTypes.filter((h) => seedHourTypeIds.includes(h.id))
        : defaultHourType
          ? [defaultHourType]
          : [];

    const out: GridRow[] = [];
    for (const employee of employees) {
      const byKey = new Map<string, GridRow>();
      const put = (row: GridRow) => {
        if (!byKey.has(row.key)) byKey.set(row.key, row);
      };

      for (const entry of entriesByEmployee[employee.id] ?? []) {
        const key = rowKey(entry.hour_type, entry.building ?? "");
        put({
          id: rowId(employee.id, key),
          employeeId: employee.id,
          employeeName: employee.name,
          key,
          hourTypeId: entry.hour_type,
          buildingId: entry.building ?? "",
          cells: {},
        });
        byKey.get(key)!.cells[entry.date] = String(entry.hours);
      }

      // One row per (building, hour type) from the setup. RECONCILED,
      // never appended: a pair that already has entries this week is the
      // operator's real data and a blank second row would be a duplicate
      // of it.
      for (const buildingId of seedBuildingIds) {
        const seat = buildingId ?? "";
        for (const hourType of seedTypes) {
          const key = rowKey(hourType.id, seat);
          put({
            id: rowId(employee.id, key),
            employeeId: employee.id,
            employeeName: employee.name,
            key,
            hourTypeId: hourType.id,
            buildingId: seat,
            cells: {},
            added: true,
          });
        }
      }

      for (const extra of extraRows[employee.id] ?? []) put(extra);
      out.push(...byKey.values());
    }
    return out;
  }, [
    employees,
    entriesByEmployee,
    extraRows,
    seedBuildingIds,
    seedHourTypeIds,
    hourTypes,
    defaultHourType,
  ]);

  const cellValue = (row: GridRow, dayKey: string) =>
    edits[cellKey(row.id, dayKey)] ?? row.cells[dayKey] ?? "";

  const setCell = (row: GridRow, dayKey: string, value: string) =>
    setEdits((current) => ({ ...current, [cellKey(row.id, dayKey)]: value }));

  const rowTotal = (row: GridRow) =>
    dayKeys.reduce((sum, key) => sum + parseHours(cellValue(row, key)), 0);

  const grandTotal = rows.reduce((sum, row) => sum + rowTotal(row), 0);

  const hourTypeName = (id: number | "") =>
    hourTypes.find((h) => h.id === id)?.name ?? String(id);

  const buildingName = (id: number | "") =>
    id === ""
      ? t("hours_week_grid.no_building")
      : (buildings.find((b) => b.id === id)?.name ?? String(id));

  /** The buildings this grid is actually about: every distinct building
   *  already on a row. That is what "all buildings" means HERE — the
   *  ones in front of the operator, not every building the company owns. */
  const gridBuildingIds = useMemo(() => {
    const seen = new Set<number | "">();
    for (const row of rows) seen.add(row.buildingId);
    return [...seen];
  }, [rows]);

  /**
   * Retarget an ADDED row's hour type or building.
   *
   * ADDED rows only. A row that already has saved entries behind it
   * keeps its type and building as text: changing them there would not
   * move the existing entries (they are keyed on the old pair
   * server-side), it would leave them where they were and open a second
   * row, which looks exactly like data loss.
   *
   * The row's key encodes the pair, so retargeting means re-keying — and
   * the pending edits under the old key move with it, or the numbers
   * already typed would vanish.
   */
  function retargetRow(
    row: GridRow,
    next: { hourTypeId?: number | ""; buildingId?: number | "" },
  ) {
    const hourTypeId = next.hourTypeId ?? row.hourTypeId;
    const buildingId = next.buildingId ?? row.buildingId;
    const nextKey = rowKey(hourTypeId, buildingId);
    if (nextKey === row.key) return;
    // Refuse a collision rather than merging two rows silently.
    if (rows.some((r) => r.employeeId === row.employeeId && r.key === nextKey)) {
      setError(t("hours_week_grid.row_exists"));
      return;
    }
    setError("");
    const nextId = rowId(row.employeeId, nextKey);
    setExtraRows((current) => ({
      ...current,
      [row.employeeId]: (current[row.employeeId] ?? []).map((r) =>
        r.key === row.key
          ? { ...r, id: nextId, key: nextKey, hourTypeId, buildingId }
          : r,
      ),
    }));
    setEdits((current) => {
      const moved: Record<string, string> = {};
      const prefix = `${row.id}|`;
      for (const [key, value] of Object.entries(current)) {
        moved[
          key.startsWith(prefix) ? cellKey(nextId, key.slice(prefix.length)) : key
        ] = value;
      }
      return moved;
    });
  }

  /** The building the bar names, as a row value. `""` (all buildings)
   *  has no single answer and is handled by each caller. */
  const barBuildingId: number | "" | null =
    barBuilding === "" ? null : barBuilding === NO_BUILDING ? "" : Number(barBuilding);

  /**
   * **FILL** — write the value into cells that ALREADY EXIST. It adds
   * nothing; that is Add row's job, and Sprint 158 split them because
   * one button doing both meant the operator could not tell which they
   * were getting.
   *
   * The matching rows are worked out HERE, not inside the setState
   * updater: a counter incremented inside the updater is still zero when
   * the next line runs, and Sprint 158's first measured run proved it —
   * ten cells filled and a banner reading "no row has that hour type".
   *
   * Nothing here reaches the server. Everything lands in `edits` and is
   * written by Save, so a mis-click is undone by not saving.
   */
  function fillMatchingRows() {
    if (barHourType === "") return;
    const targetDays = barScope === "weekdays" ? dayKeys.slice(0, 5) : dayKeys;
    const targets: string[] = [];
    for (const row of rows) {
      if (row.hourTypeId !== barHourType) continue;
      // A chosen building NARROWS. "All buildings" does not.
      if (barBuildingId !== null && row.buildingId !== barBuildingId) continue;
      for (const day of targetDays) targets.push(cellKey(row.id, day));
    }

    if (targets.length > 0) {
      setEdits((current) => {
        const next = { ...current };
        for (const key of targets) next[key] = barHours;
        return next;
      });
    }
    setBanner(
      targets.length === 0
        ? t("hours_week_grid.fill_no_match")
        : t("hours_week_grid.fill_done", { count: targets.length }),
    );
  }

  /**
   * **ADD ROW** — the other half. Adds the chosen (hour type, building)
   * to every employee that does not already have it, and fills nothing.
   *
   * With "all buildings" chosen it adds the hour type at every building
   * already in the grid, which is what the words say. That is the fix
   * for the reported bug: the empty value used to mean "no building"
   * here and "every building" in Fill, so pressing Add row with the
   * default selection either did nothing or quietly produced a
   * no-building row.
   */
  function addRows() {
    if (barHourType === "") return;
    // "All buildings" over an EMPTY grid has no buildings to enumerate,
    // so it falls back to the no-building row rather than doing nothing
    // and reporting that every row already existed.
    const targetBuildings: (number | "")[] =
      barBuildingId !== null
        ? [barBuildingId]
        : gridBuildingIds.length > 0
          ? gridBuildingIds
          : [""];
    // Counted OUTSIDE the updater, for the same reason as Fill.
    const missing: GridRow[] = [];
    for (const employee of employees) {
      for (const buildingId of targetBuildings) {
        const key = rowKey(barHourType, buildingId);
        const exists =
          rows.some((r) => r.employeeId === employee.id && r.key === key) ||
          missing.some((r) => r.employeeId === employee.id && r.key === key);
        if (exists) continue;
        missing.push({
          id: rowId(employee.id, key),
          employeeId: employee.id,
          employeeName: employee.name,
          key,
          hourTypeId: barHourType,
          buildingId,
          cells: {},
          added: true,
        });
      }
    }
    if (missing.length > 0) {
      setExtraRows((current) => {
        const next = { ...current };
        for (const row of missing) {
          next[row.employeeId] = [...(next[row.employeeId] ?? []), row];
        }
        return next;
      });
    }
    setBanner(
      missing.length === 0
        ? t("hours_week_grid.rows_all_present")
        : t("hours_week_grid.rows_added", { count: missing.length }),
    );
  }

  async function handleSave() {
    if (employees.length === 0) return;
    setBusy(true);
    setError("");
    setBanner("");

    // Send only the cells that CHANGED. Resending every cell would
    // rewrite untouched rows — pointless writes, each one re-snapshotting
    // the multiplier for no reason.
    const cells: {
      employee: number;
      hour_type: number;
      building: number | null;
      date: string;
      hours: string;
    }[] = [];
    for (const row of rows) {
      if (row.hourTypeId === "") continue;
      for (const dayKey of dayKeys) {
        const key = cellKey(row.id, dayKey);
        if (!(key in edits)) continue;
        const original = row.cells[dayKey] ?? "";
        if (parseHours(edits[key]) === parseHours(original)) continue;
        cells.push({
          employee: row.employeeId,
          hour_type: row.hourTypeId,
          building: row.buildingId === "" ? null : row.buildingId,
          date: dayKey,
          // "0" is meaningful: it CLEARS the cell server-side.
          hours: String(parseHours(edits[key])),
        });
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
      // three employees is not a state this can reach.
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
      await onSaved(changed);
    } catch (err) {
      // Verbatim — including the server's own `week_closed` wording.
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  /** Just the weekday name — "ma" / "Mon", for the scope labels. */
  const dayShort = (date: Date) =>
    date.toLocaleDateString(i18n.language === "nl" ? "nl-NL" : "en-US", {
      weekday: "short",
    });

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

  // My hours renders this for exactly one person, where a column
  // repeating their own name on every row is noise.
  const showEmployeeColumn = employees.length > 1;

  return (
    <div data-testid="hours-week-grid">
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

      {/* The apply-to-all line. Two verbs, two buttons, and the building
          select means the same thing to both of them. */}
      <div className="hours-week-apply-bar" data-testid="hours-week-apply-bar">
        <span className="hours-week-apply-label">
          {t("hours_week_grid.bar_label")}
        </span>
        <select
          className="field-input"
          value={barHourType === "" ? "" : String(barHourType)}
          onChange={(event) =>
            setBarHourType(
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
          value={barBuilding}
          onChange={(event) => setBarBuilding(event.target.value)}
          disabled={busy || weekClosed}
          aria-label={t("hours_week_grid.building")}
          data-testid="hours-week-apply-building"
        >
          {/* ONE meaning for each value, in both directions. "All
              buildings" does not narrow a Fill and adds the hour type at
              every building in the grid; "No building" is its own
              explicit choice rather than a value you reach by choosing
              nothing. That pairing is the reported bug's fix. */}
          <option value="">{t("hours_week_grid.every_building")}</option>
          <option value={NO_BUILDING}>{t("hours_week_grid.no_building")}</option>
          {buildings.map((building) => (
            <option key={building.id} value={String(building.id)}>
              {building.name}
            </option>
          ))}
        </select>
        <input
          className="field-input"
          type="text"
          inputMode="decimal"
          value={barHours}
          onChange={(event) => setBarHours(event.target.value)}
          placeholder={t("hours_week_grid.hours_placeholder")}
          disabled={busy || weekClosed}
          aria-label={t("hours_week_grid.apply_hours")}
          style={{ width: 80 }}
          data-testid="hours-week-apply-hours"
        />
        <select
          className="field-input"
          value={barScope}
          onChange={(event) =>
            setBarScope(event.target.value as "week" | "weekdays")
          }
          disabled={busy || weekClosed}
          aria-label={t("hours_week_grid.apply_scope")}
          data-testid="hours-week-apply-scope"
        >
          <option value="weekdays">
            {t("hours_week_grid.apply_scope_weekdays", {
              from: dayShort(days[0]),
              to: dayShort(days[4]),
            })}
          </option>
          <option value="week">
            {t("hours_week_grid.apply_scope_week", {
              from: dayShort(days[0]),
              to: dayShort(days[6]),
            })}
          </option>
        </select>
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={fillMatchingRows}
          disabled={busy || weekClosed || barHourType === ""}
          data-testid="hours-week-fill-button"
        >
          {t("hours_week_grid.fill_button")}
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={addRows}
          disabled={busy || weekClosed || barHourType === ""}
          data-testid="hours-week-add-row-button"
        >
          {t("hours_week_grid.add_row_button")}
        </button>
      </div>

      <div className="table-wrap">
        <table className="data-table data-table-dense hours-week-grid-table">
          <thead>
            <tr>
              {showEmployeeColumn && <th>{t("hours_week_grid.employee")}</th>}
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
                <td
                  colSpan={dayKeys.length + (showEmployeeColumn ? 5 : 4)}
                  className="muted small"
                >
                  {t("hours_week_grid.empty_block")}
                </td>
              </tr>
            )}
            {rows.map((row, index) => {
              // The name is printed once per person, not once per row:
              // four rows all repeating "Ahmet Yilmaz" is the noise the
              // per-employee blocks used to avoid, and this keeps that
              // without keeping five tables.
              const firstOfEmployee =
                index === 0 || rows[index - 1].employeeId !== row.employeeId;
              return (
                <tr key={row.id} data-testid={`hours-week-row-${row.id}`}>
                  {showEmployeeColumn && (
                    <td className="td-subject">
                      {firstOfEmployee ? row.employeeName : ""}
                    </td>
                  )}
                  <td className="td-subject">
                    {row.added ? (
                      <select
                        className="field-input hours-week-row-select"
                        value={String(row.hourTypeId)}
                        onChange={(event) =>
                          retargetRow(row, {
                            hourTypeId: Number(event.target.value),
                          })
                        }
                        disabled={busy || weekClosed}
                        aria-label={t("hours_week_grid.hour_type")}
                        data-testid={`hours-week-row-hour-type-${row.id}`}
                      >
                        {hourTypes.map((hourType) => (
                          <option key={hourType.id} value={hourType.id}>
                            {hourType.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      hourTypeName(row.hourTypeId)
                    )}
                  </td>
                  <td>
                    {row.added ? (
                      <select
                        className="field-input hours-week-row-select"
                        value={String(row.buildingId)}
                        onChange={(event) =>
                          retargetRow(row, {
                            buildingId:
                              event.target.value === ""
                                ? ""
                                : Number(event.target.value),
                          })
                        }
                        disabled={busy || weekClosed}
                        aria-label={t("hours_week_grid.building")}
                        data-testid={`hours-week-row-building-${row.id}`}
                      >
                        <option value="">
                          {t("hours_week_grid.no_building")}
                        </option>
                        {buildings.map((building) => (
                          <option key={building.id} value={building.id}>
                            {building.name}
                          </option>
                        ))}
                      </select>
                    ) : (
                      buildingName(row.buildingId)
                    )}
                  </td>
                  {dayKeys.map((dayKey, dayIndex) => (
                    <td key={dayKey} style={{ textAlign: "right" }}>
                      <input
                        className="field-input hours-week-grid-cell"
                        type="text"
                        inputMode="decimal"
                        value={cellValue(row, dayKey)}
                        onChange={(event) =>
                          setCell(row, dayKey, event.target.value)
                        }
                        disabled={busy || weekClosed}
                        aria-label={t("hours_week_grid.cell_label_person", {
                          person: row.employeeName,
                          hourType: hourTypeName(row.hourTypeId),
                          day: dayLabel(days[dayIndex]),
                        })}
                        data-testid={`hours-week-cell-${row.id}-${dayKey}`}
                      />
                    </td>
                  ))}
                  <td
                    style={{ textAlign: "right", fontWeight: 700 }}
                    data-testid={`hours-week-row-total-${row.id}`}
                  >
                    {formatTotal(rowTotal(row))}
                  </td>
                  <td>
                    {/* An added-but-unsaved row can be dropped; a row
                        that exists on the server is cleared by zeroing
                        its cells, not by removing it from the grid —
                        removing it here would look like a delete that
                        never happened. */}
                    {row.added && (
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() =>
                          setExtraRows((current) => ({
                            ...current,
                            [row.employeeId]: (
                              current[row.employeeId] ?? []
                            ).filter((r) => r.key !== row.key),
                          }))
                        }
                        disabled={busy}
                        data-testid={`hours-week-remove-row-${row.id}`}
                      >
                        {t("hours_week_grid.remove_row")}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

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
        <span className="hours-week-grand-total" data-testid="hours-week-total">
          {t("hours_week_grid.grand_total", {
            hours: formatTotal(grandTotal),
            count: employees.length,
          })}
        </span>
        <div style={{ display: "flex", gap: 8 }}>
          {onCancel && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={onCancel}
              disabled={busy}
              data-testid="hours-week-grid-cancel"
            >
              {t("cancel")}
            </button>
          )}
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
    </div>
  );
}
