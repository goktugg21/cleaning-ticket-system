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
import { Link } from "react-router-dom";

import { getApiError } from "../../api/client";
import type { HourSourceOption } from "../../api/reports";
import { saveWeekGrid } from "../../api/timesheets";
import type { HourType, TimeEntry } from "../../api/timesheets.types";
import type { BuildingAdmin } from "../../api/types";
import { hourSourceLabel } from "../../lib/hourSource";
import { isoWeekDays, toDateString } from "../../lib/isoWeek";
import type { IsoWeek } from "../../lib/isoWeek";
import { RowJobPicker } from "./RowJobPicker";
import type { RowJobSource } from "./RowJobPicker";
import { acceptsHoursInput, isFillTarget, parseHours } from "./gridRules";
import { jobTitleFirst } from "./jobTitle";

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

/** hours2 Part 3 — one PROPOSED row for one person: a building and a
 *  job, from that person's own assignments. The grid seeds it on the
 *  default hour type, reconciled against the week's saved rows exactly
 *  as the wizard's seeds are. */
export interface GridSeedRow {
  building: number | null;
  /** "" for an untagged row; "OTHER" / "CONTRACT" for the type-only
   *  buckets; "TICKET" / "EXTRA_WORK" with an id for a record. */
  source_type: string;
  source_id: number | null;
}

/** W-HOURS4 Task 1c — what a row's "+ link a job" picker may offer.
 *
 *  The grid renders the picker and owns the row's identity; the CALLER
 *  owns the answers, because they come from reads the grid must not
 *  make (`timesheets` resolves no job titles — `reports/` does). Both
 *  are per (person, building): "This week" is that person's proposal
 *  for that building in the caller's week; `search` is free text over
 *  the open work the person may book against. */
export interface GridJobPicker {
  thisWeek: (
    employeeId: number,
    buildingId: number | null,
  ) => HourSourceOption[];
  search: (
    employeeId: number,
    buildingId: number | null,
    query: string,
  ) => Promise<HourSourceOption[]>;
  /** The open popover's bottom edge, for `usePickerReserve`. */
  onOpenChange?: (listBottom: number | null) => void;
}

/** P-11 B2 — one seeded line's identity, the key `seedTypeChoice`
 *  remembers the chosen hour type under. */
function seedSeatKey(
  employeeId: number,
  seat: number | "",
  sourceType: string,
  sourceId: number | null,
) {
  return `${employeeId}:${seat === "" ? "none" : seat}:${sourceType}:${sourceId ?? ""}`;
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

/** Stable empty default for `sourceOptions`, so a caller that has none
 *  does not hand this component a fresh array on every render. */
const NO_SOURCE_OPTIONS: HourSourceOption[] = [];

/** The same stable-default trick for `quietDays` (W12 §5). */
const NO_QUIET_DAYS: string[] = [];

/** And for `seedRowsByEmployee` (hours2 Part 3). */
const NO_SEED_ROWS: Record<number, GridSeedRow[]> = {};

/** One BLOCK of the table: one (employee, building, job), holding one
 *  row per hour type. Derived from `rows` — see `blocks` below. */
interface GridBlock {
  id: string;
  employeeId: number;
  employeeName: string;
  buildingId: number | "";
  sourceType: string;
  sourceId: number | null;
  /** P-8R C — TRUE for a job-linked block that is NOT the person's own
   *  pair row: it renders as a CHILD under the person's standard rows
   *  ("on Ticket #374"), never beside them as a look-alike. */
  child: boolean;
  rows: GridRow[];
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

// W12 §4 / P-11 B2 — the keystroke rule, the parse rule and the fill
// predicate are PURE and live in `gridRules.ts`, where vitest pins
// them.

function formatTotal(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value);
}

export function HoursWeekGrid({
  week,
  employees,
  companyId,
  hourTypes,
  buildings,
  entriesByEmployee,
  seedBuildingIds,
  personBuildingIds,
  personHasApprovedPattern,
  seedSources = [],
  seedRowsByEmployee = NO_SEED_ROWS,
  sourceOptions = NO_SOURCE_OPTIONS,
  jobBillingFacts,
  showHead = true,
  showApplyRow = true,
  quietDays = NO_QUIET_DAYS,
  weekClosed,
  saveBlockedReason = null,
  onSaved,
  onCancel,
  onSaveCells,
  onDirtyChange,
  jobPicker,
  setupBuildingCount,
  patternMode = false,
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
  /** P-12 B1 — the buildings each person can be BOOKED at, keyed by
   *  employee id: the grant wall for the admin dialog (the
   *  week-assignments read), the person's own scoped building list on
   *  My hours. It feeds "+ Add a line"'s building choice — the header's
   *  picks (`seedBuildingIds`) were empty whenever the grid opened from
   *  the week card's Edit, so the select offered only "No building".
   *  A person with no entry here falls back to the seed list. */
  personBuildingIds?: Record<number, number[]>;
  /** P-15 §0.2 — only APPROVED patterns fill the sheet. When a person
   *  answers `false` here, their band says why the standard lines are
   *  empty, with the door to Agreed hours. Omitted (My hours, older
   *  callers): no line. */
  personHasApprovedPattern?: Record<number, boolean>;
  /** P-15 4.5(d) — the agreed-hours PATTERN dialog's frame: weekday
   *  headers without dates, and the Save button says "Save pattern". */
  patternMode?: boolean;
  /** Sprint 177 §7 — the JOBS chosen in the setup, if any. Each becomes
   *  its own seeded row so the hours land already attributed. Empty (the
   *  default, and what every pre-177 caller passes) seeds one untagged
   *  row exactly as before, so no existing screen changes shape. */
  seedSources?: { source_type: string; source_id: number | null }[];
  /** hours2 Part 3 — PER-PERSON seeds, beside the shared ones above.
   *
   *  The admin week wizard used to seed the same (buildings x jobs)
   *  product under every selected person, which offered a cleaner rows
   *  in buildings they cannot enter and on jobs they are not on. It now
   *  proposes each person's OWN rows — their assignments that week, the
   *  job's building prefilled — and hands them over here, keyed by
   *  employee id. Additive: a caller that passes nothing (My hours, the
   *  contract-hours dialog) seeds exactly as before. Reconciled against
   *  saved rows by the same `put()` as every other seed, so a proposal
   *  that already has hours this week is the operator's real row, not
   *  a blank twin of it. */
  seedRowsByEmployee?: Record<number, GridSeedRow[]>;
  /** Sprint 179B §2 — the jobs the JOB COLUMN reads its titles from.
   *
   *  A `TimeEntry` stores `(source_type, source_id)` and resolves
   *  neither: `timesheets` may not import `tickets` or `extra_work`, so
   *  turning an id into a title belongs to `reports/`
   *  (`reports/hour_sources.py` says so at length). This component is on
   *  the same side of that line — it is handed the resolved list and
   *  never looks a job up itself. A pair that is not in the list falls
   *  back to the backend's own shape for an id that no longer resolves,
   *  "Ticket #41". */
  sourceOptions?: HourSourceOption[];
  /** P-12 B5 (§D.24 rule 6) — where a job line's hours GO, keyed
   *  `SOURCE_TYPE:id`: the customer whose next invoice they feed and
   *  that customer's billing day. Read on the job child's sub-line. */
  jobBillingFacts?: Record<
    string,
    { customer_name: string | null; invoice_day: number | "LAST_OF_MONTH" | null }
  >;
  /** W12 §2 — whether the grid prints its own title, row count and
   *  hints above the table.
   *
   *  On the admin week wizard it is the only heading there is. On **My
   *  hours** the page header two centimetres above already names the
   *  week and the person, so the strip restated it and then spent two
   *  sentences explaining grid mechanics to somebody who came to type
   *  five numbers. */
  showHead?: boolean;
  /** W12 §3 — whether the fill-a-whole-weekday row is offered.
   *
   *  "Put 8 on Tuesday for every row" is an ADMIN verb: it earns its
   *  place above a crew of nine and it needs a rule stated
   *  (`apply_all_hint`) to be usable at all. A worker filling their own
   *  week has one or two rows in front of them, for which the verb is
   *  "type 8 twice" — so on that page the control is absent rather than
   *  present-and-explained. */
  showApplyRow?: boolean;
  /** W12 §5 — the days this person is NOT scheduled to work, as
   *  "YYYY-MM-DD" keys.
   *
   *  They stay typeable: covering a Saturday shift is exactly when an
   *  accurate hour matters. They simply stop looking like the other
   *  five. The caller decides which days these are, because the fact
   *  belongs to the caller's data (`ContractHours`' seven columns), not
   *  to a table that renders whatever week it is handed. */
  quietDays?: string[];
  /** The hour types chosen in the setup. Empty falls back to the first
   *  active type. */
  weekClosed: boolean;
  /** W-FIX1 B1 — a reason Save is refused that is not the week lock
   *  (an invalid setup field). Rendered beside the button. */
  saveBlockedReason?: string | null;
  /** P-12 B4 — beside the count, WHO was saved and how many hours were
   *  written for each (the sum of the changed cells' new values), so
   *  the page's Done banner can say "Saved: Ahmet 5 h, Gökhan 2 h" and
   *  highlight those people. Optional for callers that only count. */
  onSaved: (
    changed: number,
    saved?: { employee: number; hours: number }[],
  ) => void | Promise<void>;
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
  /** Sprint 180 §2 — "there are typed hours in here that are not saved".
   *
   *  A modal caller needs this to decide whether Escape may close it: a
   *  window-level Escape listener that always closes is how an hour of
   *  typing died on one keystroke, with no warning and nothing to
   *  recover. Reported from the event handlers that cause it, never
   *  from an effect — a synchronous setState in an effect body is what
   *  CLAUDE.md and `react-hooks/set-state-in-effect` both forbid. */
  onDirtyChange?: (dirty: boolean) => void;
  /** W-HOURS4 Task 1c — when given, every (person, building) pair row
   *  the caller seeded carries "+ link a job (optional)" under the
   *  person's name, and the Job COLUMN is not rendered: the tag on the
   *  row is the one place the job is said. Absent (My hours, the
   *  contract-hours dialog), the grid is exactly as it was. */
  jobPicker?: GridJobPicker;
  /** P-8R C — how many buildings the SETUP chose. When given, the head's
   *  one count line explains itself — "2 people × 2 buildings = 4
   *  standard rows (+2 job rows)" — instead of printing a bare row
   *  count. The people are `employees`; the standard and job rows are
   *  counted from the blocks below. Absent (My hours, the contract-hours
   *  dialog), the plain count stays. */
  setupBuildingCount?: number;
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

  /** P-11 B2 — the hour type a SEEDED row currently shows, keyed by
   *  the seed's identity (`seedSeatKey`). The type is a select ON the
   *  line now; a seeded row is re-derived every render, so the choice
   *  must live beside the seeds or the change would evaporate. Absent
   *  = the default type. `setRowType` moves any typed cells along with
   *  the change, exactly as the old job retag did. */
  const [seedTypeChoice, setSeedTypeChoice] = useState<Record<string, number>>(
    {},
  );

  // The hour type a SEEDED row opens on: the first active type, which
  // for every company that has run the standard set is "Normale uren".
  const defaultHourType = hourTypes[0];

  const days = useMemo(() => isoWeekDays(week), [week]);
  const dayKeys = useMemo(() => days.map(toDateString), [days]);
  /** W12 §5 — membership test for the day columns, built once. */
  const quiet = useMemo(() => new Set(quietDays), [quietDays]);

  /**
   * Every row of the table, DERIVED from the existing entries plus the
   * setup's seeds plus whatever was added. Derived rather than held in
   * state, so re-fetching after a save cannot leave a stale grid behind
   * — and so no effect has to sync props into state (CLAUDE.md §3).
   */
  const rows: GridRow[] = useMemo(() => {
    // Sprint 162 §1c — a seeded line opens on ONE hour type. P-11 B2 —
    // the type is a SELECT on the line now, so the seed reads the
    // operator's choice (`seedTypeChoice`) and falls back to the
    // default; a second type on the same line's job or building is a
    // second line, added per person.
    const seededType = (
      employeeId: number,
      seat: number | "",
      sourceType: string,
      sourceId: number | null,
    ): HourType | undefined => {
      const chosen =
        seedTypeChoice[seedSeatKey(employeeId, seat, sourceType, sourceId)];
      return (
        (chosen !== undefined
          ? hourTypes.find((hourType) => hourType.id === chosen)
          : undefined) ?? defaultHourType
      );
    };

    const out: GridRow[] = [];
    for (const employee of employees) {
      const byKey = new Map<string, GridRow>();
      const put = (row: GridRow) => {
        if (!byKey.has(row.key)) byKey.set(row.key, row);
      };

      for (const entry of entriesByEmployee[employee.id] ?? []) {
        // W-HOURS5 Task 6 — a saved entry nobody tagged is stored as
        // `OTHER` with no id (the model's default), while a seed nobody
        // tagged is "" in this grid's vocabulary. Both mean "no job".
        // Read as two identities they made two rows: the saved general
        // row AND a blank twin from the seed, whose save would have
        // REPLACED the saved hours (bulk-week keys on the same absent
        // job). Normalised here, at the one place entries enter, so the
        // seed reconciles onto the saved row as every seed should.
        const entrySourceId = entry.source_id ?? null;
        const entrySourceType =
          entry.source_type === "OTHER" && entrySourceId === null
            ? ""
            : entry.source_type || "";
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
      // W-FIX1 D9 (audit F29) — the pairs that already have a SAVED row
      // this week, by (hour type, building) alone. An auto-filled week
      // stores its rows as CONTRACT/<agreement>; W-HOURS5 6b folded only
      // the untagged OTHER row onto the untagged seed, so those weeks
      // opened with the saved block AND a blank general twin, and typing
      // into the twin doubled the day. An untagged seed now yields to
      // any saved row of its pair.
      // P-8R C — ...but only to a saved row that IS the pair's own
      // standard row: an untagged one, or an auto-filled CONTRACT row
      // (D9's case). A saved row linked to a JOB (ticket / extra work)
      // is a child of the pair, not its stand-in: without this the
      // person x building pair whose only saved hours were on jobs had
      // no standard row at all, and the count read "1 person x 2
      // buildings = 1 standard row" on crmtest (P-8R walk).
      const savedPairs = new Set(
        [...byKey.values()]
          .filter((row) => row.sourceType === "" || row.sourceType === "CONTRACT")
          .map((row) => `${row.hourTypeId}|${row.buildingId}`),
      );

      // One row per (building, hour type) from the setup. RECONCILED,
      // never appended: a pair that already has entries this week is the
      // operator's real data and a blank second row would be a duplicate
      // of it.
      for (const buildingId of seedBuildingIds) {
        const seat = buildingId ?? "";
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
          const hourType = seededType(employee.id, seat, source.type, source.id);
          if (!hourType) continue;
          if (source.type === "" && savedPairs.has(`${hourType.id}|${seat}`)) {
            continue;
          }
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

      // hours2 Part 3 — this person's own proposals, one row per
      // (building, job). `put()` keeps the saved row when one exists
      // for the same key.
      for (const seed of seedRowsByEmployee[employee.id] ?? []) {
        const seat = seed.building ?? "";
        const sourceType = seed.source_type;
        const sourceId = seed.source_id;
        const hourType = seededType(employee.id, seat, sourceType, sourceId);
        if (!hourType) continue;
        if (sourceType === "" && savedPairs.has(`${hourType.id}|${seat}`)) {
          continue;
        }
        const key = rowKey(hourType.id, seat, sourceType, sourceId);
        put({
          id: rowId(employee.id, key),
          employeeId: employee.id,
          employeeName: employee.name,
          key,
          hourTypeId: hourType.id,
          buildingId: seat,
          sourceType,
          sourceId,
          cells: {},
          added: true,
        });
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
    seedRowsByEmployee,
    seedTypeChoice,
    hourTypes,
    defaultHourType,
  ]);

  const cellValue = (row: GridRow, dayKey: string) =>
    edits[cellKey(row.id, dayKey)] ?? row.cells[dayKey] ?? "";

  const setCell = (row: GridRow, dayKey: string, value: string) => {
    // W12 §4 — a rejected keystroke leaves the state alone, so the
    // character simply never lands. See `acceptsHoursInput`.
    if (!acceptsHoursInput(value)) return;
    setEdits((current) => ({ ...current, [cellKey(row.id, dayKey)]: value }));
    // Sprint 180 §2 — told, never derived in an effect. Every path that
    // can create an unsaved value says so from its own event handler,
    // and `handleSave` says the opposite when the grid is clean again.
    onDirtyChange?.(true);
  };

  const rowTotal = (row: GridRow) =>
    dayKeys.reduce((sum, key) => sum + parseHours(cellValue(row, key)), 0);

  const grandTotal = rows.reduce((sum, row) => sum + rowTotal(row), 0);

  // P-11 B2 — the footer's count ("4 standard lines empty — not
  // saved.") and the fill row's own ("it lands on the 4 standard
  // lines below"). A standard line is a seeded or saved line with no
  // job on it — exactly the set the fill writes.
  const standardLineCount = rows.filter(isFillTarget).length;
  const emptyStandardCount = rows.filter(
    (row) => isFillTarget(row) && rowTotal(row) === 0,
  ).length;

  const personTotal = (employeeId: number) =>
    rows.reduce(
      (sum, row) => (row.employeeId === employeeId ? sum + rowTotal(row) : sum),
      0,
    );

  /** The type option's words: the catalogue name, with the multiplier
   *  shown when it weighs anything ("Weekend uren ×1.5"). The
   *  multiplier weighs the person's hours for the reports; it prices
   *  nothing — the one sentence about that is on the dialog. */
  const typeOptionLabel = (hourType: HourType) => {
    const multiplier = Number(hourType.multiplier);
    if (!Number.isFinite(multiplier) || multiplier === 1) return hourType.name;
    return `${hourType.name} ×${String(Number(multiplier.toFixed(2)))}`;
  };

  /** P-11 B2 — a timesheet is typed, not clicked: Enter moves DOWN the
   *  column (Tab already moves along the row). The next row in render
   *  order; the fill row hands off to the first data row. */
  function focusCellBelow(fromRowId: string | null, dayKey: string) {
    const ordered = blocks.flatMap((block) => block.rows);
    const index =
      fromRowId === null
        ? -1
        : ordered.findIndex((row) => row.id === fromRowId);
    const next = ordered[index + 1];
    if (!next) return;
    const el = document.querySelector<HTMLInputElement>(
      `[data-testid="hours-week-cell-${CSS.escape(next.id)}-${dayKey}"]`,
    );
    el?.focus();
    el?.select();
  }

  const hourTypeName = (id: number | "") =>
    hourTypes.find((h) => h.id === id)?.name ??
    t("my_hours.field_hour_type_empty");

  const buildingName = (id: number | "") =>
    id === ""
      ? t("hours_week_grid.no_building")
      : (buildings.find((b) => b.id === id)?.name ??
        t("hours_week_grid.no_building"));

  /** Sprint 179B §2 — which JOB a row belongs to, in words. The rule
   *  itself is in `lib/hourSourceLabel`, because the My hours list needs
   *  the same three cases and a second copy of them would drift. */
  const sourceName = (sourceType: string, sourceId: number | null) =>
    hourSourceLabel(
      sourceType,
      sourceId,
      sourceOptions,
      t,
      t("hours_week_grid.no_source"),
    );

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
  // Plain derivation, deliberately not `useMemo`: the React-compiler
  // lint (`preserve-manual-memoization`) cannot keep a manual memo
  // over this shape (the ExtraWorkListPage precedent), and grouping a
  // few hundred rows costs nothing per render.
  const blocks = (() => {
    const byBlock = new Map<string, GridBlock>();
    for (const row of rows) {
      // Sprint 179B §2 — the JOB is part of the block, not just of the
      // row. Two reasons, and the second is a bug this closes:
      //
      //  - the block prints its identity once, on its first row, so a
      //    job that were only a row property would have to repeat on
      //    every line to be readable;
      //  - `+ Add type` adds a row to a BLOCK. Sprint 177 §7 wrote that
      //    "an hour type added to a job-tagged block belongs to that
      //    job" and read `block.sourceType` to do it — but the block
      //    object never carried one, so the value was always undefined
      //    and every added row came out untagged. Grouping by the job
      //    makes that sentence true instead of aspirational, and there
      //    is now exactly one job a new row could inherit.
      const id = [
        row.employeeId,
        row.buildingId === "" ? "none" : row.buildingId,
        row.sourceType || "none",
        row.sourceId ?? "none",
      ].join(":");
      if (!byBlock.has(id)) {
        byBlock.set(id, {
          id,
          employeeId: row.employeeId,
          employeeName: row.employeeName,
          buildingId: row.buildingId,
          sourceType: row.sourceType,
          sourceId: row.sourceId,
          child: false,
          rows: [],
        });
      }
      byBlock.get(id)!.rows.push(row);
    }
    // P-8R C — the STANDARD rows are the backbone. Per person, the
    // untagged blocks and the person's own pair row (tagged or not)
    // come first; every other job-linked block is a CHILD and follows
    // them. `rows` is already grouped per employee in `employees`
    // order, so the sort only has to keep that grouping and move the
    // children to the end of their person; the third key keeps the
    // original order inside each half.
    const order = new Map(employees.map((employee, index) => [employee.id, index]));
    // P-11 B2 — EVERY job-linked block is a child now: the mockup's
    // shape is standard lines first, job lines indented under them
    // with a tag. The per-row job picker went with the pair concept —
    // a job line is ADDED per person, never linked onto a standard row.
    return [...byBlock.values()]
      .map((block, index) => ({
        block: { ...block, child: block.sourceType !== "" },
        index,
      }))
      .sort(
        (a, b) =>
          (order.get(a.block.employeeId) ?? 0) -
            (order.get(b.block.employeeId) ?? 0) ||
          Number(a.block.child) - Number(b.block.child) ||
          a.index - b.index,
      )
      .map(({ block }) => block);
  })();

  /** P-8R C — the two halves of the one count line. A block, not a
   *  row: "+ Add type" adds a LINE to a block and must not turn
   *  "2 × 2 = 4" into "2 × 2 = 5". */
  const standardBlockCount = blocks.filter((block) => !block.child).length;
  const jobBlockCount = blocks.length - standardBlockCount;

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
    // W12 §4 — the same field rule as a data cell: this box writes into
    // the same cells and must not be the way "g" gets into seven of
    // them at once.
    if (!acceptsHoursInput(value)) return;
    // Kept until the dialog closes or the operator clears it. Applying
    // is still immediate — this is a record of what was filled, not a
    // pending edit waiting on a commit.
    setApplyRow((current) => ({ ...current, [dayKey]: value }));
    setEdits((current) => {
      const next = { ...current };
      for (const row of rows) {
        // Sprint 166 §1 + P-11 B2 — the standard lines only; the
        // same predicate the fill row's sentence counts with.
        if (!isFillTarget(row)) continue;
        next[cellKey(row.id, dayKey)] = value;
      }
      return next;
    });
    // Sprint 180 §2 — the fill line writes into the same `edits` a cell
    // does, so it makes the grid just as unsaved.
    onDirtyChange?.(true);
  }

  /** P-11 B2 — add one LINE for one person: a building or a job, on an
   *  hour type. The one add affordance the grid has ("+ Add a line for
   *  Ahmet — another hour type on the same job, another building, or a
   *  job"), replacing the per-block "+ Add type" pseudo-rows. */
  function addLine(
    employee: GridEmployee,
    choice: {
      buildingId: number | "";
      sourceType: string;
      sourceId: number | null;
      hourTypeId: number;
    },
  ) {
    const key = rowKey(
      choice.hourTypeId,
      choice.buildingId,
      choice.sourceType,
      choice.sourceId,
    );
    if (rows.some((r) => r.employeeId === employee.id && r.key === key)) {
      setError(t("hours_week_grid.row_exists"));
      return;
    }
    setError("");
    // Sprint 165 §3 — a row added AFTER the fill starts empty.
    setExtraRows((current) => ({
      ...current,
      [employee.id]: [
        ...(current[employee.id] ?? []),
        {
          id: rowId(employee.id, key),
          employeeId: employee.id,
          employeeName: employee.name,
          key,
          hourTypeId: choice.hourTypeId,
          buildingId: choice.buildingId,
          sourceType: choice.sourceType,
          sourceId: choice.sourceId,
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

  /**
   * P-11 B2 — change the hour type ON a line.
   *
   * The type is part of a row's KEY (`rowKey`), so a change turns the
   * line into a different row. Everything already typed — and, on a
   * SAVED row, the saved days — moves onto the new key in the same
   * handler (the old cells clear to "0", which deletes server-side),
   * exactly the mechanics the old job retag used: no hour vanishes
   * because the type was corrected after it was typed.
   */
  function setRowType(row: GridRow, nextTypeId: number) {
    if (nextTypeId === row.hourTypeId) return;
    const newKey = rowKey(nextTypeId, row.buildingId, row.sourceType, row.sourceId);
    const newId = rowId(row.employeeId, newKey);
    if (
      rows.some((r) => r.employeeId === row.employeeId && r.key === newKey)
    ) {
      setError(t("hours_week_grid.row_exists"));
      return;
    }
    setError("");
    setEdits((current) => {
      const moved = { ...current };
      for (const dayKey of dayKeys) {
        const from = cellKey(row.id, dayKey);
        const saved = row.added ? undefined : row.cells[dayKey];
        const hasEdit = from in moved;
        if (!hasEdit && saved === undefined) continue;
        const value = hasEdit ? moved[from] : (saved as string);
        if (hasEdit) delete moved[from];
        if (saved !== undefined) moved[from] = "0";
        moved[cellKey(newId, dayKey)] = value;
      }
      return moved;
    });
    if (row.manual) {
      setExtraRows((current) => ({
        ...current,
        [row.employeeId]: (current[row.employeeId] ?? []).map((extra) =>
          extra.key === row.key
            ? { ...extra, key: newKey, id: newId, hourTypeId: nextTypeId }
            : extra,
        ),
      }));
    } else if (row.added) {
      // A seeded line: remember the choice beside the seeds, so the
      // re-derivation lands on the same key the cells moved to.
      setSeedTypeChoice((current) => ({
        ...current,
        [seedSeatKey(row.employeeId, row.buildingId, row.sourceType, row.sourceId)]:
          nextTypeId,
      }));
    } else {
      // A SAVED row: its entry-derived line stays (zeroed — "0"
      // deletes on save); the moved cells need a line to live on.
      setExtraRows((current) => ({
        ...current,
        [row.employeeId]: [
          ...(current[row.employeeId] ?? []),
          {
            id: newId,
            employeeId: row.employeeId,
            employeeName: row.employeeName,
            key: newKey,
            hourTypeId: nextTypeId,
            buildingId: row.buildingId,
            sourceType: row.sourceType,
            sourceId: row.sourceId,
            cells: {},
            added: true,
            manual: true,
          },
        ],
      }));
    }
    onDirtyChange?.(true);
  }

  /** P-11 B2 — a JOB line's identity, the mockup's child shape: a
   *  coloured kind tag ("Ticket" / "Extra work"), the job's name, and
   *  a sub-line with the building — plus, on an extra-work line, the
   *  one sentence linking the two hour concepts: these hours are also
   *  what the customer is billed for (B3). */
  function renderChildLabel(block: GridBlock) {
    const label = sourceName(block.sourceType, block.sourceId);
    const isExtraWork = block.sourceType === "EXTRA_WORK";
    // P-12 B5 — where these hours go next, in words: the customer's
    // next invoice and its day. Falls back to the P-11 sentence when
    // the caller has no billing facts for the job.
    const facts = jobBillingFacts?.[`${block.sourceType}:${block.sourceId}`];
    const invoiceSub = facts?.customer_name
      ? facts.invoice_day === "LAST_OF_MONTH"
        ? t("hours_week_grid.job_invoice_sub_last", {
            customer: facts.customer_name,
          })
        : typeof facts.invoice_day === "number"
          ? t("hours_week_grid.job_invoice_sub", {
              customer: facts.customer_name,
              day: facts.invoice_day,
            })
          : t("hours_week_grid.job_invoice_sub_noday", {
              customer: facts.customer_name,
            })
      : isExtraWork
        ? t("hours_week_grid.ew_billed_sub")
        : null;
    return (
      <span
        className="hours-week-child"
        data-testid={`hours-week-part-${block.id}`}
      >
        <span
          className={`hours-week-kind-tag${isExtraWork ? " hours-week-kind-tag-ew" : ""}`}
        >
          {t(isExtraWork ? "hour_source.EXTRA_WORK" : "hour_source.TICKET")}
        </span>
        <span
          className="hours-week-child-title"
          title={label}
          data-testid={`hours-week-job-${block.id}-saved`}
        >
          {jobTitleFirst(label)}
        </span>
        <span className="hours-week-line-sub">
          {[
            block.buildingId === "" ? null : buildingName(block.buildingId),
            invoiceSub,
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </span>
    );
  }


  async function handleSave() {
    if (employees.length === 0 || saveBlockedReason) return;
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
      // Sprint 180 §2 — saved is clean: Escape may close again.
      onDirtyChange?.(false);
      setBanner(t("hours_week_grid.saved", { count: changed }));
      // P-12 B4 — who was saved, with the hours the save wrote (the
      // changed cells' new values; a cleared cell contributes 0 but
      // still lists the person, so "removed their hours" is sayable).
      const savedByEmployee = new Map<number, number>();
      for (const cell of cells) {
        savedByEmployee.set(
          cell.employee,
          (savedByEmployee.get(cell.employee) ?? 0) + parseHours(cell.hours),
        );
      }
      await onSaved(
        changed,
        [...savedByEmployee].map(([employee, hours]) => ({ employee, hours })),
      );
    } catch (err) {
      // Verbatim — including the server's own `week_closed` wording.
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  // P-15 4.5(d) — a PATTERN dialog borrows this grid as a frame only:
  // its headers are weekdays without dates (a dateless weekly pattern
  // entered under concrete dates read as a week's entry), and its Save
  // says what it saves.
  const dayLabel = (date: Date) =>
    date.toLocaleDateString(i18n.language === "nl" ? "nl-NL" : "en-US", {
      weekday: "short",
      ...(patternMode ? {} : { day: "2-digit", month: "2-digit" }),
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
      {showHead && (
      <div className="hours-week-table-head">
        <span className="hours-week-table-title">
          {t("hours_week_grid.table_title")}
        </span>
        <span className="cell-tag cell-tag-muted" data-testid="hours-week-count">
          {/* P-8R C — the ONE count (P-7 S1.1 made the grid's count the
              only one), and it explains itself when the caller says how
              many buildings the setup chose: "2 people × 2 buildings =
              4 standard rows (+2 job rows)". The bare count stays for
              the callers that have no setup. */}
          {setupBuildingCount === undefined
            ? t("hours_week_grid.assignment_count", { count: rows.length })
            : t("hours_week_grid.count_explained", {
                people: t("hours_week_grid.count_people", {
                  count: employees.length,
                }),
                buildings: t("hours_week_grid.count_buildings", {
                  count: setupBuildingCount,
                }),
                standard: t("hours_week_grid.count_standard", {
                  count: standardBlockCount,
                }),
                jobs:
                  jobBlockCount > 0
                    ? t("hours_week_grid.count_jobs", { count: jobBlockCount })
                    : "",
              }).trim()}
        </span>
        {/* P-11 B2 — "Rows without hours are not saved" moved to the
            footer, with the count ("4 standard lines empty — not
            saved."), where the Save it talks about is. */}
      </div>
      )}

      <div className="table-wrap hours-week-table-wrap">
        <table className="data-table data-table-dense hours-week-grid-table">
          {/* P-11 B2 — ONE table, and every row is a row OF it, so the
              columns line up by construction: Line · Hour type · seven
              days · Week. The fill row is the first body row (the
              owner's alignment complaint was structural, not CSS); the
              old Worker/Building/Job columns folded into the Line cell
              under a person band. Named columns so the modal can fix
              their widths (`.week-entry-modal .hours-week-col-*`). */}
          <colgroup>
            <col className="hours-week-col-what" />
            <col className="hours-week-col-type" />
            {dayKeys.map((dayKey) => (
              <col key={dayKey} className="hours-week-col-day" />
            ))}
            <col className="hours-week-col-total" />
          </colgroup>
          <thead>
            <tr>
              <th>{t("hours_week_grid.line")}</th>
              <th>{t("hours_week_grid.hour_type")}</th>
              {days.map((day, index) => (
                <th
                  key={dayKeys[index]}
                  style={{ textAlign: "right" }}
                  /* W12 §5 — a day this person is not scheduled for is
                     printed quieter than the five they are. The column
                     still accepts hours; it just stops claiming to
                     expect them. */
                  className={
                    quiet.has(dayKeys[index])
                      ? "hours-week-day-quiet"
                      : undefined
                  }
                >
                  {dayLabel(day)}
                </th>
              ))}
              <th style={{ textAlign: "right" }}>
                {t("hours_week_grid.week")}
              </th>
            </tr>
          </thead>
          <tbody>
            {/* P-11 B2 — the fill row is the FIRST BODY ROW of the one
                table: its inputs sit in the day columns because they
                ARE the day columns. It lands on the standard lines
                only — never on job lines, never on a line the operator
                added (Sprint 166 §1). */}
            {showApplyRow && (
              <tr
                className="hours-week-fill-row"
                data-testid="hours-week-apply-row"
              >
                <td className="hours-week-fill-what">
                  <span className="hours-week-apply-label">
                    {t("hours_week_grid.apply_all_label")}
                  </span>
                  <span className="hours-week-apply-hint">
                    {t("hours_week_grid.apply_all_hint", {
                      count: standardLineCount,
                    })}
                  </span>
                </td>
                <td className="hours-week-fill-dash">—</td>
                {dayKeys.map((dayKey, dayIndex) => (
                  <td
                    key={dayKey}
                    style={{ textAlign: "right" }}
                    className={
                      quiet.has(dayKey) ? "hours-week-day-quiet" : undefined
                    }
                  >
                    <input
                      className="field-input hours-week-grid-cell"
                      type="text"
                      inputMode="decimal"
                      value={applyRow[dayKey] ?? ""}
                      onChange={(event) =>
                        applyToAllDay(dayKey, event.target.value)
                      }
                      onKeyDown={(event) => {
                        // Enter must not submit the surrounding form;
                        // it hands off DOWN the column instead.
                        if (event.key === "Enter") {
                          event.preventDefault();
                          focusCellBelow(null, dayKey);
                        }
                      }}
                      disabled={busy || weekClosed}
                      aria-label={t("hours_week_grid.apply_all_day", {
                        day: dayLabel(days[dayIndex]),
                      })}
                      data-testid={`hours-week-apply-${dayKey}`}
                    />
                  </td>
                ))}
                <td className="hours-week-fill-dash" style={{ textAlign: "right" }}>
                  —
                </td>
              </tr>
            )}
            {blocks.length === 0 &&
              (employees.length === 0 || weekClosed) && (
              <tr>
                <td colSpan={dayKeys.length + 3} className="muted small">
                  {t("hours_week_grid.empty_block")}
                </td>
              </tr>
            )}
            {blocks.map((block, blockIndex) => {
              // P-11 B2 — ONE GROUP PER PERSON: a band with the name
              // and the person's week total, their standard lines
              // under it, then their job lines as children (indent +
              // kind tag), then ONE "+ Add a line for {person}" row.
              const firstOfPerson =
                blockIndex === 0 ||
                blocks[blockIndex - 1].employeeId !== block.employeeId;
              const lastOfPerson =
                blockIndex === blocks.length - 1 ||
                blocks[blockIndex + 1].employeeId !== block.employeeId;
              const child = block.child;
              const employee: GridEmployee = {
                id: block.employeeId,
                name: block.employeeName,
              };
              return (
              <Fragment key={block.id}>
                {firstOfPerson && (
                  <tr
                    className="hours-week-person"
                    data-testid={`hours-week-person-${block.employeeId}`}
                  >
                    <td colSpan={dayKeys.length + 2}>
                      {block.employeeName}
                      {/* P-15 §0.2 — only approved patterns fill; say
                          why this person's standard lines are empty. */}
                      {personHasApprovedPattern?.[block.employeeId] ===
                        false && (
                        <span
                          className="muted small hours-week-line-sub"
                          data-testid={`hours-week-no-pattern-${block.employeeId}`}
                          style={{ display: "block", fontWeight: 400 }}
                        >
                          {t("hours_week_grid.no_approved_pattern")}{" "}
                          <Link to="/admin/hours/agreed">
                            {t("hours_week_grid.no_approved_pattern_link")}
                          </Link>
                        </span>
                      )}
                    </td>
                    <td
                      className="hours-week-group-total"
                      data-testid={`hours-week-person-total-${block.employeeId}`}
                    >
                      {t("hours_week_grid.person_total", {
                        hours: formatTotal(
                          personTotal(block.employeeId),
                          i18n.language,
                        ),
                      })}
                    </td>
                  </tr>
                )}
                {block.rows.map((row, dayRowIndex) => (
                  <tr
                    key={row.id}
                    data-testid={`hours-week-row-${row.id}`}
                    data-child={child ? "true" : undefined}
                    className={
                      dayRowIndex === 0
                        ? child
                          ? "hours-week-child-first"
                          : "hours-week-group-first"
                        : undefined
                    }
                  >
                    {/* The LINE: a building (standard hours) or a job
                        (kind tag + name + building), printed on the
                        block's first row; a second hour type on the
                        same line continues it quietly below. */}
                    <td
                      className={
                        child
                          ? "td-subject hours-week-identity hours-week-child-cell"
                          : "td-subject hours-week-identity hours-week-std-cell"
                      }
                    >
                      {dayRowIndex === 0 && child && renderChildLabel(block)}
                      {dayRowIndex === 0 && !child && (
                        <span className="hours-week-std">
                          {buildingName(block.buildingId)}
                          <span className="hours-week-line-sub">
                            {t("hours_week_grid.standard_sub")}
                          </span>
                        </span>
                      )}
                      {/* A line the operator added and has not saved
                          can be taken away again; a saved line is
                          cleared by emptying its hours. */}
                      {row.manual && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm hours-week-remove"
                          onClick={() => removeRow(row)}
                          disabled={busy}
                          aria-label={t("hours_week_grid.remove_type", {
                            hourType: hourTypeName(row.hourTypeId),
                          })}
                          data-testid={`hours-week-remove-row-${row.id}`}
                        >
                          ×
                        </button>
                      )}
                    </td>
                    <td className="hours-week-type-cell">
                      {/* P-11 B2 — the hour type is a SELECT on every
                          line, from the company's own catalogue with
                          the multiplier shown. Changing it moves the
                          line's hours with it (`setRowType`). */}
                      <select
                        className="field-input hours-week-type-select"
                        value={row.hourTypeId === "" ? "" : String(row.hourTypeId)}
                        onChange={(event) =>
                          setRowType(row, Number(event.target.value))
                        }
                        disabled={busy || weekClosed}
                        aria-label={t("hours_week_grid.cell_type_label", {
                          person: row.employeeName,
                        })}
                        data-testid={`hours-week-row-type-${row.id}`}
                      >
                        {hourTypes.map((hourType) => (
                          <option key={hourType.id} value={String(hourType.id)}>
                            {typeOptionLabel(hourType)}
                          </option>
                        ))}
                      </select>
                    </td>
                    {dayKeys.map((dayKey, dayIndex) => (
                      <td key={dayKey} style={{ textAlign: "right" }}>
                        <input
                          className={[
                            "field-input hours-week-grid-cell",
                            quiet.has(dayKey) ? "hours-week-cell-quiet" : "",
                            cellValue(row, dayKey).trim() !== ""
                              ? "hours-week-cell-set"
                              : "",
                          ]
                            .filter(Boolean)
                            .join(" ")}
                          type="text"
                          inputMode="decimal"
                          value={cellValue(row, dayKey)}
                          onChange={(event) =>
                            setCell(row, dayKey, event.target.value)
                          }
                          onKeyDown={(event) => {
                            // P-11 B2 — a timesheet is typed: Enter
                            // moves down the column, Tab along the row.
                            if (event.key === "Enter") {
                              event.preventDefault();
                              focusCellBelow(row.id, dayKey);
                            }
                          }}
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
                      {formatTotal(rowTotal(row), i18n.language)}
                    </td>
                  </tr>
                ))}
                {lastOfPerson && !weekClosed && (
                  <tr className="hours-week-add-row">
                    <td colSpan={dayKeys.length + 3}>
                      <AddLineControl
                        employee={employee}
                        buildings={buildings}
                        bookableIds={
                          personBuildingIds?.[employee.id] ??
                          seedBuildingIds.filter(
                            (id): id is number => id !== null,
                          )
                        }
                        hourTypes={hourTypes}
                        typeOptionLabel={typeOptionLabel}
                        jobPicker={jobPicker}
                        disabled={busy}
                        t={t}
                        onAdd={(choice) => addLine(employee, choice)}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
              );
            })}
            {/* P-12 walk fix (§D.24 rule 2's promise kept) — a person
                with NO rows still gets their band and the "+ Add a
                line" door. With no buildings chosen in the setup
                nothing is seeded, and on the crmtest walk Start here
                preselected exactly the five people with no hours —
                whom the grid then offered no way to type for. The
                add-line's building choice is their own bookable list
                (B1), so the door is real. */}
            {!weekClosed &&
              employees
                .filter(
                  (employee) =>
                    !blocks.some((block) => block.employeeId === employee.id),
                )
                .map((employee) => (
                  <Fragment key={`empty-${employee.id}`}>
                    <tr
                      className="hours-week-person"
                      data-testid={`hours-week-person-${employee.id}`}
                    >
                      <td colSpan={dayKeys.length + 2}>
                        {employee.name}
                        {/* P-15 §0.2 — the no-rows band says it too. */}
                        {personHasApprovedPattern?.[employee.id] ===
                          false && (
                          <span
                            className="muted small hours-week-line-sub"
                            data-testid={`hours-week-no-pattern-${employee.id}`}
                            style={{ display: "block", fontWeight: 400 }}
                          >
                            {t("hours_week_grid.no_approved_pattern")}{" "}
                            <Link to="/admin/hours/agreed">
                              {t("hours_week_grid.no_approved_pattern_link")}
                            </Link>
                          </span>
                        )}
                      </td>
                      <td
                        className="hours-week-group-total"
                        data-testid={`hours-week-person-total-${employee.id}`}
                      >
                        {t("hours_week_grid.person_total", {
                          hours: formatTotal(0, i18n.language),
                        })}
                      </td>
                    </tr>
                    <tr className="hours-week-add-row">
                      <td colSpan={dayKeys.length + 3}>
                        <AddLineControl
                          employee={employee}
                          buildings={buildings}
                          bookableIds={
                            personBuildingIds?.[employee.id] ??
                            seedBuildingIds.filter(
                              (id): id is number => id !== null,
                            )
                          }
                          hourTypes={hourTypes}
                          typeOptionLabel={typeOptionLabel}
                          jobPicker={jobPicker}
                          disabled={busy}
                          t={t}
                          onAdd={(choice) => addLine(employee, choice)}
                        />
                      </td>
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
            hours: formatTotal(grandTotal, i18n.language),
            count: employees.length,
          })}
        </span>
        {/* P-11 B2 — "rows without hours are not saved", said with the
            count, beside the Save it is about. */}
        {emptyStandardCount > 0 && (
          <span
            className="muted small"
            data-testid="hours-week-empty-standard"
          >
            {t("hours_week_grid.empty_standard", {
              count: emptyStandardCount,
            })}
          </span>
        )}
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
          {saveBlockedReason && (
            <span
              className="form-error small"
              data-testid="hours-week-grid-save-blocked"
            >
              {saveBlockedReason}
            </span>
          )}
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleSave}
            disabled={busy || weekClosed || !!saveBlockedReason}
            data-testid="hours-week-grid-save"
          >
            {busy
              ? t("admin_form.saving")
              : patternMode
                ? t("contract_hours.save_pattern")
                : t("hours_week_grid.save")}
          </button>
        </div>
      </div>
    </div>
  );
}


/**
 * P-11 B2 — "+ Add a line for {person}", the grid's ONE add
 * affordance, replacing the per-block "+ Add type" pseudo-rows and the
 * per-row "+ link a job (optional)" picker.
 *
 * A link that unfolds into a small inline form: a building (the
 * setup's buildings plus "no building"), an optional job (the caller's
 * own picker, where one is supplied — the admin dialog; My hours and
 * the contract-hours dialog add building lines only), and the hour
 * type. Its own component so each person owns their open state.
 */
function AddLineControl({
  employee,
  buildings,
  bookableIds,
  hourTypes,
  typeOptionLabel,
  jobPicker,
  disabled,
  t,
  onAdd,
}: {
  employee: GridEmployee;
  buildings: BuildingAdmin[];
  /** P-12 B1 — the buildings this PERSON can be booked at (the grant
   *  wall / the person's own scoped list), not the header's picks. */
  bookableIds: number[];
  hourTypes: HourType[];
  typeOptionLabel: (hourType: HourType) => string;
  jobPicker?: GridJobPicker;
  disabled?: boolean;
  t: (key: string, options?: Record<string, unknown>) => string;
  onAdd: (choice: {
    buildingId: number | "";
    sourceType: string;
    sourceId: number | null;
    hourTypeId: number;
  }) => void;
}) {
  const [open, setOpen] = useState(false);
  const [buildingId, setBuildingId] = useState<string>("none");
  const [job, setJob] = useState<RowJobSource | null>(null);
  const [hourTypeId, setHourTypeId] = useState<string>(
    hourTypes[0] ? String(hourTypes[0].id) : "",
  );

  // P-12 B1 — the buildings offered are the ones the person can be
  // booked at, by name; "No building" is a real seat and comes LAST.
  // With exactly one choice there is no select: the line takes it and
  // the label says which.
  const buildingName = (id: number) =>
    buildings.find((building) => building.id === id)?.name ?? String(id);
  const seats: { value: string; label: string }[] = [
    ...bookableIds.map((id) => ({ value: String(id), label: buildingName(id) })),
    { value: "none", label: t("hours_week_grid.no_building") },
  ];
  const onlySeat = bookableIds.length === 0 ? seats[0] : bookableIds.length === 1 ? seats[0] : null;

  if (!open) {
    return (
      <span className="hours-week-add-line">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => {
            // Default to the person's first bookable building (the seat
            // the standard lines are seeded from), not to "none".
            setBuildingId(seats[0].value);
            setOpen(true);
          }}
          disabled={disabled}
          data-testid={`hours-week-add-line-${employee.id}`}
        >
          {t("hours_week_grid.add_line", { person: employee.name })}
        </button>
        <span className="muted small">{t("hours_week_grid.add_line_hint")}</span>
      </span>
    );
  }

  return (
    <span className="hours-week-add-line-form" data-testid={`hours-week-add-line-form-${employee.id}`}>
      {onlySeat ? (
        <span
          className="hours-week-add-line-only muted small"
          data-testid={`hours-week-add-line-building-${employee.id}`}
          data-only-seat={onlySeat.value}
        >
          {t("hours_week_grid.add_line_one_building", { building: onlySeat.label })}
        </span>
      ) : (
        <select
          className="field-input hours-week-type-select"
          value={buildingId}
          onChange={(event) => setBuildingId(event.target.value)}
          aria-label={t("hours_week_grid.building")}
          data-testid={`hours-week-add-line-building-${employee.id}`}
        >
          {seats.map((seat) => (
            <option key={seat.value} value={seat.value}>
              {seat.label}
            </option>
          ))}
        </select>
      )}
      {jobPicker && (
        <RowJobPicker
          tag={job}
          tagLabel={job ? t("hours_week_grid.add_line_job_chosen") : ""}
          tagTooltip=""
          thisWeek={jobPicker.thisWeek(
            employee.id,
            buildingId === "none" ? null : Number(buildingId),
          )}
          search={(query) =>
            jobPicker.search(
              employee.id,
              buildingId === "none" ? null : Number(buildingId),
              query,
            )
          }
          onChange={(next) => setJob(next)}
          onOpenChange={jobPicker.onOpenChange}
          disabled={disabled}
          ariaLabel={t("hours_week_grid.add_line_job", {
            person: employee.name,
          })}
          testId={`hours-week-add-line-job-${employee.id}`}
        />
      )}
      <select
        className="field-input hours-week-type-select"
        value={hourTypeId}
        onChange={(event) => setHourTypeId(event.target.value)}
        aria-label={t("hours_week_grid.hour_type")}
        data-testid={`hours-week-add-line-type-${employee.id}`}
      >
        {hourTypes.map((hourType) => (
          <option key={hourType.id} value={String(hourType.id)}>
            {typeOptionLabel(hourType)}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="btn btn-secondary btn-sm"
        disabled={disabled || hourTypeId === ""}
        onClick={() => {
          onAdd({
            buildingId: buildingId === "none" ? "" : Number(buildingId),
            sourceType: job?.source_type ?? "",
            sourceId: job?.source_id ?? null,
            hourTypeId: Number(hourTypeId),
          });
          setOpen(false);
          setJob(null);
        }}
        data-testid={`hours-week-add-line-confirm-${employee.id}`}
      >
        {t("hours_week_grid.add_line_confirm")}
      </button>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        onClick={() => {
          setOpen(false);
          setJob(null);
        }}
        data-testid={`hours-week-add-line-cancel-${employee.id}`}
      >
        {t("cancel")}
      </button>
    </span>
  );
}
