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
import { Fragment, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import { saveWeekGrid } from "../../api/timesheets";
import type { HourType, TimeEntry } from "../../api/timesheets.types";
import type { BuildingAdmin } from "../../api/types";
import { isoWeekDays, toDateString } from "../../lib/isoWeek";
import type { IsoWeek } from "../../lib/isoWeek";

/** One person the grid writes for. */
/** One changed cell the grid collected. Exported because a caller that
 *  supplies `onSaveCells` receives these and decides where they go —
 *  see the prop's own comment for why that indirection exists. */
export interface GridCell {
  employee: number;
  hour_type: number;
  building: number | null;
  date: string;
  hours: string;
  /** Sprint 177 §7 — the JOB these hours were worked on, travelling with
   *  the cell so the operator never restates it. Omitted entirely when
   *  the row is not tagged to a job: the endpoint reads key presence, and
   *  sending an empty string would store a source nobody can filter on. */
  source_type?: string;
  source_id?: number | null;
}

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
  /** True for a row the SETUP or `+ Add type` created, which has no
   *  saved entry behind it: those are the only rows that may simply be
   *  dropped. */
  added?: boolean;
  /** Sprint 166 §1 — TRUE only for a row the operator added with
   *  `+ Add type`.
   *
   *  `added` cannot answer this: it is true for the wizard's seeded
   *  rows as well, which is exactly why two previous attempts at the
   *  fill rule got it wrong by reaching for timing instead. The owner's
   *  rule is about WHERE a row came from, not WHEN, so the row is
   *  marked at creation rather than inferred later. */
  manual?: boolean;
  /** Sprint 177 §7 — the job this row's hours belong to, or "" for
   *  untagged work. Part of the row IDENTITY (see `rowKey`), because
   *  hours on the stairwell repaint and hours on nothing in particular
   *  are two facts and must not be summed onto one line. */
  sourceType: string;
  sourceId: number | null;
  /** "YYYY-MM-DD" -> the raw text of the saved entry. Text, not number,
   *  so a half-typed "1." survives a re-render. */
  cells: Record<string, string>;
}

function rowKey(
  hourTypeId: number | "",
  buildingId: number | "",
  sourceType: string = "",
  sourceId: number | null = null,
) {
  // The SOURCE is part of the key for the same reason the approval tab
  // keys on it: two jobs at one building on one hour type are two rows.
  return `${hourTypeId}:${buildingId}:${sourceType}:${sourceId ?? ""}`;
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
  seedSources = [],
  weekClosed,
  onSaved,
  onCancel,
  onSaveCells,
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
  /** Sprint 177 §7 — the JOBS chosen in the setup, if any. Each becomes
   *  its own seeded row so the hours land already attributed. Empty (the
   *  default, and what every pre-177 caller passes) seeds one untagged
   *  row exactly as before, so no existing screen changes shape. */
  seedSources?: { source_type: string; source_id: number | null }[];
  /** The hour types chosen in the setup. Empty falls back to the first
   *  active type. */
  weekClosed: boolean;
  onSaved: (changed: number) => void | Promise<void>;
  /** Sprint 168 §1 — where the collected cells GO.
   *
   *  Left out, they go to `saveWeekGrid` and become TimeEntry rows,
   *  which is what every existing caller wants. Supplied, the caller
   *  writes them itself and returns how many changed.
   *
   *  This exists so the contract-hours bulk dialog can use THIS grid
   *  rather than a second one that looks the same. The two are the same
   *  shape — same blocks, same fill line, same `+ Add type`, same
   *  Sprint 166 rule that a manually added row is never touched by the
   *  fill — and a copy is how those four behaviours drift apart. What
   *  genuinely differs between them is only the destination, so only
   *  the destination is a parameter. */
  onSaveCells?: (cells: GridCell[]) => Promise<number>;
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

  /** Sprint 162 §1b — what has been typed into the apply-to-all row,
   *  per weekday. Kept only so the row shows what was typed; the value
   *  is pushed into every cell the moment it is typed, so this is a
   *  display echo and never a second source of truth for the hours. */
  const [applyRow, setApplyRow] = useState<Record<string, string>>({});

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
    // Sprint 162 §1c — a block opens with ONE default hour-type row and
    // the operator reaches any other through `+ Add type`. The setup's
    // hour-type choice is gone, so there is nothing else to seed from.
    const seedTypes = defaultHourType ? [defaultHourType] : [];

    const out: GridRow[] = [];
    for (const employee of employees) {
      const byKey = new Map<string, GridRow>();
      const put = (row: GridRow) => {
        if (!byKey.has(row.key)) byKey.set(row.key, row);
      };

      for (const entry of entriesByEmployee[employee.id] ?? []) {
        const entrySourceType = entry.source_type || "";
        const entrySourceId = entry.source_id ?? null;
        const key = rowKey(
          entry.hour_type,
          entry.building ?? "",
          entrySourceType,
          entrySourceId,
        );
        put({
          id: rowId(employee.id, key),
          employeeId: employee.id,
          employeeName: employee.name,
          key,
          hourTypeId: entry.hour_type,
          buildingId: entry.building ?? "",
          sourceType: entrySourceType,
          sourceId: entrySourceId,
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
          // Sprint 177 §7 — one seeded row per JOB the setup named, and
          // one untagged row when it named none. An operator who picked
          // two jobs gets a line for each, so the hours land already
          // attributed instead of needing a source typed afterwards.
          const seats: { type: string; id: number | null }[] =
            seedSources.length > 0
              ? seedSources.map((source) => ({
                  type: source.source_type,
                  id: source.source_id,
                }))
              : [{ type: "", id: null }];
          for (const source of seats) {
            const key = rowKey(hourType.id, seat, source.type, source.id);
            put({
              id: rowId(employee.id, key),
              employeeId: employee.id,
              employeeName: employee.name,
              key,
              hourTypeId: hourType.id,
              buildingId: seat,
              sourceType: source.type,
              sourceId: source.id,
              cells: {},
              added: true,
            });
          }
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
    seedSources,
    // `hourTypes` is no longer read here: the seed is `defaultHourType`,
    // which is derived from it and is its own dependency. It went with
    // the wizard's hour-type step (§1c).
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

  /**
   * Sprint 162 §1 — the grid as BLOCKS, one per (worker, building).
   *
   * The reference's shape, and the reason the row controls could go: a
   * block's building is a property OF the block, printed once as a
   * label, so there is no per-row building to change. Inside a block
   * each row is one hour type, and the only way to reach another type
   * is `+ Add type`, which is also why the setup no longer asks for
   * types up front.
   *
   * Derived from `rows`, so nothing here is a second copy of the grid's
   * data; the blocks are a grouping of it.
   */
  const blocks = useMemo(() => {
    const byBlock = new Map<
      string,
      {
        id: string;
        employeeId: number;
        employeeName: string;
        buildingId: number | "";
        rows: GridRow[];
      }
    >();
    for (const row of rows) {
      const id = `${row.employeeId}:${row.buildingId === "" ? "none" : row.buildingId}`;
      if (!byBlock.has(id)) {
        byBlock.set(id, {
          id,
          employeeId: row.employeeId,
          employeeName: row.employeeName,
          buildingId: row.buildingId,
          rows: [],
        });
      }
      byBlock.get(id)!.rows.push(row);
    }
    return [...byBlock.values()];
  }, [rows]);

  /**
   * Sprint 162 §1b — type a number under a weekday and it lands in that
   * weekday for EVERY row below.
   *
   * It overwrites a cell that already has a value, deliberately: the
   * operator typed into the "everyone" row on purpose, and a fill that
   * skipped the cells already filled would be the confusing behaviour
   * the owner asked us not to build.
   */
  /**
   * Sprint 166 §1 — the fill rule, third statement and the final one.
   *
   * **Rows added with `+ Add type` are NEVER filled. Not the ones added
   * afterwards, and not the ones added beforehand.** Timing does not
   * enter into it, which is precisely what the two earlier attempts got
   * wrong: Sprint 164 filled new rows, Sprint 165 filled the rows that
   * existed at the moment of typing — and that still filled a manual
   * row created BEFORE the operator typed.
   *
   * So the fill applies to the rows the WIZARD created (and to the
   * saved rows behind them), never to the operator's own additions. The
   * distinction is recorded on the row at creation as `manual`, because
   * `added` is true for both kinds and inferring it from ordering is
   * how this went wrong twice.
   *
   * Sprint 172 §1 — the inputs KEEP their typed values, reversing
   * Sprint 165's display fix.
   *
   * That fix was sound when it was made and its premise has since gone.
   * It cleared the box because an input reading "4" was a claim about
   * the GRID's state, and that claim stopped being true the moment a
   * row was added — the box said 4 while a new row sat empty.
   *
   * Sprint 166 settled that the fill only ever touches the rows the
   * WIZARD created, and the label says exactly that ("Fill the default
   * rows"). So the box no longer claims anything about rows it never
   * touches: 4 in the box means "the default rows carry 4", which stays
   * true when a manual row is added beside them. The contradiction the
   * clearing existed to avoid cannot occur any more.
   *
   * And the clearing had a cost the owner hit immediately: typing into
   * one day's box and clicking the next one wiped the first, so filling
   * a week meant watching your own work disappear.
   */
  function applyToAllDay(dayKey: string, value: string) {
    // Kept until the dialog closes or the operator clears it. Applying
    // is still immediate — this is a record of what was filled, not a
    // pending edit waiting on a commit.
    setApplyRow((current) => ({ ...current, [dayKey]: value }));
    setEdits((current) => {
      const next = { ...current };
      for (const row of rows) {
        // Sprint 166 §1 — a row the operator added with `+ Add type` is
        // NEVER filled. Not the ones added afterwards, and not the ones
        // added beforehand: timing is irrelevant, which is what both
        // earlier attempts got wrong.
        if (row.manual) continue;
        next[cellKey(row.id, dayKey)] = value;
      }
      return next;
    });
  }

  /** Add one hour-type row to a block. The block already fixes the
   *  employee and the building, so the type is the only choice left —
   *  which is the whole point of the shape. */
  function addTypeToBlock(
    block: {
      employeeId: number;
      employeeName: string;
      buildingId: number | "";
      /** Sprint 177 §7 — an hour type added to a job-tagged block belongs
       *  to that job. Without this the new row would be untagged and the
       *  operator would have to say so again, which is the exact thing
       *  this section exists to stop. */
      sourceType?: string;
      sourceId?: number | null;
    },
    hourTypeId: number,
  ) {
    const blockSourceType = block.sourceType ?? "";
    const blockSourceId = block.sourceId ?? null;
    const key = rowKey(
      hourTypeId,
      block.buildingId,
      blockSourceType,
      blockSourceId,
    );
    if (
      rows.some((r) => r.employeeId === block.employeeId && r.key === key)
    ) {
      setError(t("hours_week_grid.row_exists"));
      return;
    }
    setError("");
    // Sprint 165 §3 — a row added AFTER the fill starts empty. Sprint
    // 164 had it inherit; the owner has asked three times for the other
    // behaviour, and the contradiction that inheritance was solving is
    // handled in the display instead (the all-rows inputs clear).
    const newRowId = rowId(block.employeeId, key);
    setExtraRows((current) => ({
      ...current,
      [block.employeeId]: [
        ...(current[block.employeeId] ?? []),
        {
          id: newRowId,
          employeeId: block.employeeId,
          employeeName: block.employeeName,
          key,
          hourTypeId,
          buildingId: block.buildingId,
          sourceType: blockSourceType,
          sourceId: blockSourceId,
          cells: {},
          added: true,
          // Sprint 166 §1 — the mark that keeps this row out of the
          // fill, forever and regardless of when it was added.
          manual: true,
        },
      ],
    }));
  }

  function removeRow(row: GridRow) {
    setExtraRows((current) => ({
      ...current,
      [row.employeeId]: (current[row.employeeId] ?? []).filter(
        (r) => r.key !== row.key,
      ),
    }));
  }


  async function handleSave() {
    if (employees.length === 0) return;
    setBusy(true);
    setError("");
    setBanner("");

    // Send only the cells that CHANGED. Resending every cell would
    // rewrite untouched rows — pointless writes, each one re-snapshotting
    // the multiplier for no reason.
    const cells: GridCell[] = [];
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
          // Sprint 177 §7 — only when the row IS tagged. Spread rather
          // than a null literal so an untagged row omits the keys
          // entirely; the endpoint reads presence.
          ...(row.sourceType
            ? { source_type: row.sourceType, source_id: row.sourceId }
            : {}),
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
      let changed: number;
      if (onSaveCells) {
        changed = await onSaveCells(cells);
      } else {
        // ONE request for the whole grid, however many people are in
        // it. The endpoint is all-or-nothing, so a week that half-saved
        // across three employees is not a state this can reach.
        const result = await saveWeekGrid({
          company: companyId ?? undefined,
          iso_year: week.isoYear,
          iso_week: week.isoWeek,
          cells,
        });
        changed = result.created + result.updated + result.deleted;
      }
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

      {/* Sprint 162 §1b — ONE apply-to-all row, and it lives INSIDE the
          table, in the same columns as the data. The bar it replaces
          had six controls (hour type, building, hours, scope, Fill, Add
          row) that between them could not do the one thing an operator
          wants: put a number on a weekday for everybody. Typing in a day
          cell here does exactly that and nothing else. */}
      {/* Sprint 163 §1 — the table's own head, the way the reference
          labels it: what this is, how many rows it holds, and what an
          empty grid does. The caption describes OUR behaviour — a row
          left blank is simply not written — rather than borrowing the
          reference's sentence about seeding one hour on Monday, which
          is not what ours does. */}
      <div className="hours-week-table-head">
        <span className="hours-week-table-title">
          {t("hours_week_grid.table_title")}
        </span>
        <span className="cell-tag cell-tag-muted">
          {t("hours_week_grid.assignment_count", { count: rows.length })}
        </span>
        <span className="muted small hours-week-table-hint">
          {t("hours_week_grid.empty_hint")}
        </span>
      </div>

      <div className="table-wrap hours-week-table-wrap">
        <table className="data-table data-table-dense hours-week-grid-table">
          <thead>
            <tr>
              <th>{t("hours_week_grid.worker")}</th>
              <th>{t("hours_week_grid.building")}</th>
              <th>{t("hours_week_grid.hour_type")}</th>
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
            <tr
              className="hours-week-apply-row"
              data-testid="hours-week-apply-row"
            >
              <th scope="row" colSpan={3} className="hours-week-apply-label">
                {t("hours_week_grid.apply_all_label")}
              </th>
              {dayKeys.map((dayKey, dayIndex) => (
                <th key={dayKey} style={{ textAlign: "right" }}>
                  <input
                    className="field-input hours-week-grid-cell"
                    type="text"
                    inputMode="decimal"
                    value={applyRow[dayKey] ?? ""}
                    onChange={(event) =>
                      applyToAllDay(dayKey, event.target.value)
                    }
                    onKeyDown={(event) => {
                      // Enter must not submit the surrounding form; the
                      // value is already applied as it is typed.
                      if (event.key === "Enter") event.preventDefault();
                    }}
                    disabled={busy || weekClosed}
                    aria-label={t("hours_week_grid.apply_all_day", {
                      day: dayLabel(days[dayIndex]),
                    })}
                    data-testid={`hours-week-apply-${dayKey}`}
                  />
                </th>
              ))}
              <th />
              <th />
            </tr>
          </thead>
          <tbody>
            {blocks.length === 0 && (
              <tr>
                <td colSpan={dayKeys.length + 5} className="muted small">
                  {t("hours_week_grid.empty_block")}
                </td>
              </tr>
            )}
            {blocks.map((block) => (
              <Fragment key={block.id}>
                {block.rows.map((row, dayRowIndex) => (
                  <tr
                    key={row.id}
                    data-testid={`hours-week-row-${row.id}`}
                    className={
                      dayRowIndex === 0 ? "hours-week-group-first" : undefined
                    }
                  >
                    {/* Sprint 163 §1 — worker and building are COLUMNS,
                        printed on the group's first row and left blank
                        on its continuation rows. They used to be a
                        block-header banner, which meant nothing lined
                        up and the eye had to re-anchor at every group. */}
                    <td className="td-subject hours-week-identity">
                      {dayRowIndex === 0 ? block.employeeName : ""}
                    </td>
                    <td className="hours-week-identity">
                      {dayRowIndex === 0 ? buildingName(block.buildingId) : ""}
                    </td>
                    <td className="td-subject">
                      {/* A chip, not a dropdown. The dropdown only ever
                          existed on rows added in this session, so the
                          rows the wizard produced rendered plain text and
                          the control the owner clicked was not there. */}
                      <span
                        className="cell-tag cell-tag-normal"
                        data-testid={`hours-week-row-type-${row.id}`}
                      >
                        {hourTypeName(row.hourTypeId)}
                      </span>
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
                          onClick={() => removeRow(row)}
                          disabled={busy}
                          aria-label={t("hours_week_grid.remove_type", {
                            hourType: hourTypeName(row.hourTypeId),
                          })}
                          data-testid={`hours-week-remove-row-${row.id}`}
                        >
                          {t("hours_week_grid.remove_row")}
                        </button>
                      )}
                      {dayRowIndex < 0 && null}
                    </td>
                  </tr>
                ))}
                <tr className="hours-week-add-type-row">
                  <td colSpan={dayKeys.length + 3}>
                    {/* The ONLY way an hour type is chosen, which is how
                        the reference does it — and why the wizard no
                        longer asks for types up front. */}
                    <AddTypeControl
                      blockId={block.id}
                      options={hourTypes.filter(
                        (hourType) =>
                          !block.rows.some((r) => r.hourTypeId === hourType.id),
                      )}
                      disabled={busy || weekClosed}
                      addLabel={t("hours_week_grid.add_type")}
                      chooseLabel={t("hours_week_grid.hour_type")}
                      onAdd={(hourTypeId) =>
                        addTypeToBlock(block, hourTypeId)
                      }
                    />
                  </td>
                  <td
                    className="hours-week-group-total"
                    data-testid={`hours-week-block-total-${block.id}`}
                  >
                    {formatTotal(
                      block.rows.reduce((sum, row) => sum + rowTotal(row), 0),
                    )}
                  </td>
                  <td />
                </tr>
              </Fragment>
            ))}

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


/**
 * Sprint 162 §1 — `+ Add type`, the only place an hour type is chosen.
 *
 * A button that becomes a select on click rather than a select that is
 * always sitting there: the block already knows the employee and the
 * building, so this is a one-field decision and a permanently-open
 * dropdown per block would put back exactly the control-per-row noise
 * this sprint removed.
 *
 * Its own component so each block owns its open state; one shared
 * "which block is open" flag in the parent would be a second thing to
 * keep in step with the blocks themselves.
 */
function AddTypeControl({
  blockId,
  options,
  disabled,
  addLabel,
  chooseLabel,
  onAdd,
}: {
  blockId: string;
  options: { id: number; name: string }[];
  disabled?: boolean;
  addLabel: string;
  chooseLabel: string;
  onAdd: (hourTypeId: number) => void;
}) {
  const [open, setOpen] = useState(false);

  // Every type is already on the block: there is nothing to add, and a
  // button that opens an empty list is worse than no button.
  if (options.length === 0) return null;

  if (!open) {
    return (
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        onClick={() => setOpen(true)}
        disabled={disabled}
        data-testid={`hours-week-add-type-${blockId}`}
      >
        {addLabel}
      </button>
    );
  }

  return (
    <select
      className="field-input hours-week-add-type-select"
      defaultValue=""
      autoFocus
      disabled={disabled}
      aria-label={chooseLabel}
      onChange={(event) => {
        if (event.target.value === "") return;
        onAdd(Number(event.target.value));
        setOpen(false);
      }}
      onBlur={() => setOpen(false)}
      data-testid={`hours-week-add-type-select-${blockId}`}
    >
      <option value="">{chooseLabel}</option>
      {options.map((option) => (
        <option key={option.id} value={option.id}>
          {option.name}
        </option>
      ))}
    </select>
  );
}
