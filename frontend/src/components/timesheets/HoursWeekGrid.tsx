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
  /** True for a row the SETUP created rather than the operator or the
   *  server. Seeded rows are retargetable and droppable exactly like
   *  added ones — they have no saved entry behind them either. */
  seeded?: boolean;
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

/** Sprint 158 §5e — a selected row, across employees. */
function rowSelectionKey(employeeId: number, row: string) {
  return `${employeeId}|${row}`;
}

function splitRowSelection(composite: string): [number, string] {
  const cut = composite.indexOf("|");
  return [Number(composite.slice(0, cut)), composite.slice(cut + 1)];
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
  /** Sprint 157 §1 — the buildings chosen in the Set up week modal.
   *  `null` is a legitimate member ("no building"), which is why this is
   *  `(number | null)[]` and not `number[]`.
   *
   *  The grid opens one row per (employee, building) pair, exactly as
   *  the reference system opens one row per worker-building pair. Rows
   *  that ALREADY have entries this week are reconciled rather than
   *  duplicated — see `rowsByEmployee`. */
  seedBuildingIds: (number | null)[];
  /** Sprint 158 §5d — the hour types chosen in the setup modal. Empty
   *  falls back to the first active type, which is what Sprint 157 did
   *  implicitly. */
  seedHourTypeIds: number[];
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
  // Sprint 158 §5e — inline bulk edit. A selected row is identified by
  // "employeeId|rowKey", because a row key alone is not unique across
  // employees.
  const [selectedRowKeys, setSelectedRowKeys] = useState<string[]>([]);
  const [inlineValue, setInlineValue] = useState("");

  // The apply-to-all bar's own inputs. Not part of the grid's data.
  const [bulkHourType, setBulkHourType] = useState<number | "">("");
  const [bulkBuilding, setBulkBuilding] = useState<number | "">("");
  const [bulkHours, setBulkHours] = useState("");
  const [bulkScope, setBulkScope] = useState<"week" | "weekdays">("weekdays");

  // The hour type a SEEDED row opens on. The first active type, which
  // for every company that has run the standard set is "Normale uren" —
  // the one an operator would have picked anyway. It is editable on the
  // row (Sprint 156 §6c), so this is a starting point and not a
  // decision made on their behalf.
  const defaultHourType = hourTypes[0];

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
      // Sprint 157 §1 — one row per (employee, building) pair from the
      // setup modal.
      //
      // RECONCILED, not appended: if this employee already has any row
      // at that building this week — because they have saved entries
      // there — the pair is already represented and a blank second row
      // would be a duplicate of it. That is §1.5, and it is why the
      // check is on the BUILDING rather than on the full row key: the
      // hour type of the existing rows is whatever was really worked,
      // and the seed's default type has no claim to displace it.
      // Sprint 158 §5d — one row per (building, hour type) from the
      // setup. With no hour type chosen this falls back to the first
      // active one, which is exactly Sprint 157's behaviour.
      const seedTypes =
        seedHourTypeIds.length > 0
          ? hourTypes.filter((h) => seedHourTypeIds.includes(h.id))
          : defaultHourType
            ? [defaultHourType]
            : [];
      for (const buildingId of seedBuildingIds) {
        const seatId = buildingId ?? "";
        for (const hourType of seedTypes) {
          const key = rowKey(hourType.id, seatId);
          // RECONCILE: an existing row for this exact pair is the
          // operator's real data and is never duplicated.
          if (byKey.has(key)) continue;
          byKey.set(key, {
            key,
            hourTypeId: hourType.id,
            buildingId: seatId,
            cells: {},
            seeded: true,
          });
        }
      }
      for (const extra of extraRows[employee.id] ?? []) {
        if (!byKey.has(extra.key)) byKey.set(extra.key, extra);
      }
      out[employee.id] = [...byKey.values()];
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

  /** True for a row the operator just added, which has no saved entry
   *  behind it yet — the only rows whose hour type and building may be
   *  retargeted, and the only ones that can simply be dropped. */
  const isAddedRow = (employeeId: number, key: string) =>
    (extraRows[employeeId] ?? []).some((r) => r.key === key) ||
    (rowsByEmployee[employeeId] ?? []).some(
      (r) => r.key === key && r.seeded,
    );

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

  /** Sprint 156 §6c — retarget an ADDED row's hour type or building.
   *
   * Sprint 155 picked both for you at Add-row time and gave you no way
   * to change either, so a row could not be pointed at a building at all
   * — which made the optional `TimeEntry.building` unreachable from the
   * one surface that fills a whole week.
   *
   * ADDED rows only. A row that already has saved entries behind it
   * keeps its type and building as text: changing them there would not
   * move the existing entries (they are keyed on the old pair
   * server-side), it would silently leave them where they were and open
   * a second row, which looks exactly like data loss.
   *
   * The row's key encodes the pair, so retargeting means re-keying — and
   * the pending edits under the old key have to move with it or the
   * numbers the operator already typed would vanish.
   */
  function retargetRow(
    employeeId: number,
    row: GridRow,
    next: { hourTypeId?: number | ""; buildingId?: number | "" },
  ) {
    const hourTypeId = next.hourTypeId ?? row.hourTypeId;
    const buildingId = next.buildingId ?? row.buildingId;
    const nextKey = rowKey(hourTypeId, buildingId);
    if (nextKey === row.key) return;
    // Refuse a collision rather than merging two rows silently.
    if ((rowsByEmployee[employeeId] ?? []).some((r) => r.key === nextKey)) {
      setError(t("hours_week_grid.row_exists"));
      return;
    }
    setError("");
    setExtraRows((current) => ({
      ...current,
      [employeeId]: (current[employeeId] ?? []).map((r) =>
        r.key === row.key ? { ...r, key: nextKey, hourTypeId, buildingId } : r,
      ),
    }));
    setEdits((current) => {
      const moved: Record<string, string> = {};
      for (const [key, value] of Object.entries(current)) {
        const prefix = cellKey(employeeId, row.key, "");
        moved[
          key.startsWith(prefix)
            ? cellKey(employeeId, nextKey, key.slice(prefix.length))
            : key
        ] = value;
      }
      return moved;
    });
  }

  /** Sprint 156 §6d — the TOP box of a day column: one value into that
   *  weekday for every row of this employee at once.
   *
   *  The reference system the owner sent stacks two boxes per day, and
   *  the distinction is the point: the top one is "everybody on this
   *  day", the ones below are the individual rows. Writing into `edits`
   *  for every row makes the per-row boxes update visibly, so the
   *  relationship is shown rather than described.
   */
  function fillDayForEmployee(employeeId: number, dayKey: string, value: string) {
    const rows = rowsByEmployee[employeeId] ?? [];
    setEdits((current) => {
      const next = { ...current };
      for (const row of rows) {
        if (row.hourTypeId === "") continue;
        next[cellKey(employeeId, row.key, dayKey)] = value;
      }
      return next;
    });
  }

  /** Sprint 158 §5a/§5c — **FILL**. Writes the value into cells that
   *  ALREADY EXIST. It adds nothing.
   *
   *  What it used to do, and why the owner called it misleading: it
   *  added a row to every selected employee that did not already have
   *  the chosen (hour type, building) pair, and then filled it. Pressing
   *  a button labelled "apply to all" and getting new rows is not what
   *  the words say.
   *
   *  §5c, reproduced from the code before changing it: the old version
   *  keyed on the PAIR, and the bar's building defaults to "no
   *  building" while seeded rows carry a real one. So applying to an
   *  hour type that already existed at a building produced a SECOND row
   *  for the same hour type — `Normale uren` twice, one with a building
   *  and one without — because `hourType:building` and `hourType:` are
   *  different keys. That is the misbehaviour; matching on hour type and
   *  treating the building as an optional narrowing is the fix.
   *
   *  Nothing here reaches the server. Everything lands in `edits` and is
   *  written by Save, so a mis-click is undone by not saving.
   */
  function fillMatchingRows() {
    if (bulkHourType === "") return;
    const targetDays = bulkScope === "weekdays" ? dayKeys.slice(0, 5) : dayKeys;

    // The matching rows are worked out HERE, not inside the setState
    // updater. A counter incremented inside the updater is still zero
    // when the next line runs — React has not invoked it yet — and the
    // first measured run of this code proved it: ten cells were filled
    // and the banner said "no row has that hour type". A control that
    // misreports what it did is the same class of defect as the one
    // §5a/§5c are about, so it is fixed rather than left as cosmetic.
    const targets: string[] = [];
    for (const employee of employees) {
      for (const row of rowsByEmployee[employee.id] ?? []) {
        if (row.hourTypeId !== bulkHourType) continue;
        // A chosen building NARROWS; an empty choice means "every row of
        // this hour type", not "only the row that has no building". That
        // is the §5c fix.
        if (bulkBuilding !== "" && row.buildingId !== bulkBuilding) continue;
        for (const day of targetDays) {
          targets.push(cellKey(employee.id, row.key, day));
        }
      }
    }

    if (targets.length > 0) {
      setEdits((current) => {
        const next = { ...current };
        for (const key of targets) next[key] = bulkHours;
        return next;
      });
    }

    // Say so rather than doing nothing silently: with no matching row
    // there is nothing to fill, and the operator wants Add row.
    setBanner(
      targets.length === 0
        ? t("hours_week_grid.fill_no_match")
        : t("hours_week_grid.fill_done", { count: targets.length }),
    );
  }

  /** Sprint 158 §5a — **ADD ROW**, the other half, now separate and
   *  labelled for what it does. Adds the chosen (hour type, building)
   *  row to every selected employee that does not already have it, and
   *  does NOT fill anything. */
  function addRowToAll() {
    if (bulkHourType === "") return;
    const key = rowKey(bulkHourType, bulkBuilding);
    // Counted OUTSIDE the updater, for the same reason as Fill above.
    const missing = employees.filter(
      (employee) =>
        !(rowsByEmployee[employee.id] ?? []).some((r) => r.key === key),
    );
    if (missing.length > 0) {
      setExtraRows((current) => {
        const next = { ...current };
        for (const employee of missing) {
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
    }
    setBanner(t("hours_week_grid.rows_added", { count: missing.length }));
  }

  /** Sprint 158 §5b — the GLOBAL row, above the names. One value into
   *  that weekday for EVERY row of EVERY employee in the grid.
   *
   *  Sprint 156 put a box at the top of each employee's own table; this
   *  is that idea finished — it belongs to no employee and reads as
   *  global because it sits above all of them. */
  function fillDayForEveryone(dayKey: string, value: string) {
    setEdits((current) => {
      const next = { ...current };
      for (const employee of employees) {
        for (const row of rowsByEmployee[employee.id] ?? []) {
          if (row.hourTypeId === "") continue;
          next[cellKey(employee.id, row.key, dayKey)] = value;
        }
      }
      return next;
    });
  }

  /** Sprint 158 §5e — inline bulk edit. Set every SELECTED row's chosen
   *  days at once, on the page, without opening anything. */
  function fillSelectedRows(value: string) {
    const targetDays = bulkScope === "weekdays" ? dayKeys.slice(0, 5) : dayKeys;
    setEdits((current) => {
      const next = { ...current };
      for (const composite of selectedRowKeys) {
        const [employeeId, rowKeyPart] = splitRowSelection(composite);
        for (const day of targetDays) {
          next[cellKey(employeeId, rowKeyPart, day)] = value;
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

  /** Just the weekday name — "ma" / "Mon". Used by the §6b scope
   *  labels, which name the day span instead of a category. */
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
      {/* Sprint 158 §5a/§5f — ONE line, and the two actions are now
          two buttons that say what they do. "Fill" writes into cells
          that exist; "Add row" creates a row. Sprint 157's single
          "Apply to all" did both and the owner could not tell which he
          was getting. §5f: the strip stays on one line — it scrolls
          inside itself rather than wrapping. */}
      <div className="hours-week-apply-bar" data-testid="hours-week-apply-bar">
        <span className="hours-week-apply-label">
          {t("hours_week_grid.bar_label")}
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
          {/* "Every building" rather than "no building": in the FILL
              direction an empty choice means "do not narrow", which is
              the §5c fix. */}
          <option value="">{t("hours_week_grid.every_building")}</option>
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
          style={{ width: 80 }}
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
          disabled={busy || weekClosed || bulkHourType === ""}
          data-testid="hours-week-fill-button"
        >
          {t("hours_week_grid.fill_button")}
        </button>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={addRowToAll}
          disabled={busy || weekClosed || bulkHourType === ""}
          data-testid="hours-week-add-row-button"
        >
          {t("hours_week_grid.add_row_button")}
        </button>
        {/* §5e — the inline bulk edit, on the SAME line. */}
        <span className="hours-week-bar-sep" aria-hidden="true" />
        <input
          className="field-input"
          type="text"
          inputMode="decimal"
          value={inlineValue}
          onChange={(event) => setInlineValue(event.target.value)}
          placeholder={t("hours_week_grid.hours_placeholder")}
          disabled={busy || weekClosed || selectedRowKeys.length === 0}
          aria-label={t("hours_week_grid.selected_value")}
          style={{ width: 80 }}
          data-testid="hours-week-inline-value"
        />
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => fillSelectedRows(inlineValue)}
          disabled={busy || weekClosed || selectedRowKeys.length === 0}
          data-testid="hours-week-inline-apply"
        >
          {t("hours_week_grid.apply_to_selected", {
            count: selectedRowKeys.length,
          })}
        </button>
      </div>

      {/* Sprint 158 §5b — the GLOBAL row. It belongs to no employee and
          sits above every block, so what it does is legible from where
          it is: type a number and that weekday is set for everybody. */}
      <div className="hours-week-global-row" data-testid="hours-week-global-row">
        <span className="hours-week-global-label">
          {t("hours_week_grid.global_row_label")}
        </span>
        {dayKeys.map((dayKey, index) => (
          <label key={dayKey} className="hours-week-global-cell">
            <span className="hours-week-global-day">{dayShort(days[index])}</span>
            <input
              className="field-input hours-week-grid-cell"
              type="text"
              inputMode="decimal"
              // Not bound to state: this box is a verb, not a value. It
              // pushes into the rows below, and those rows are where the
              // number then lives.
              defaultValue=""
              onChange={(event) =>
                fillDayForEveryone(dayKey, event.target.value)
              }
              disabled={busy || weekClosed}
              aria-label={t("hours_week_grid.global_cell_label", {
                day: dayLabel(days[index]),
              })}
              data-testid={`hours-week-global-${dayKey}`}
            />
          </label>
        ))}
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
                    {/* Sprint 158 §5e — row selection, for the inline
                        bulk edit in the bar above. */}
                    <th className="th-select">
                      <input
                        type="checkbox"
                        checked={
                          rows.length > 0 &&
                          rows.every((r) =>
                            selectedRowKeys.includes(
                              rowSelectionKey(employee.id, r.key),
                            ),
                          )
                        }
                        onChange={(event) => {
                          const keys = rows.map((r) =>
                            rowSelectionKey(employee.id, r.key),
                          );
                          setSelectedRowKeys((current) =>
                            event.target.checked
                              ? [...new Set([...current, ...keys])]
                              : current.filter((k) => !keys.includes(k)),
                          );
                        }}
                        disabled={busy || weekClosed || rows.length === 0}
                        aria-label={employee.name}
                        data-testid={`hours-week-select-all-${employee.id}`}
                      />
                    </th>
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
                      <td colSpan={dayKeys.length + 5} className="muted small">
                        {t("hours_week_grid.empty_block")}
                      </td>
                    </tr>
                  )}
                  {/* Sprint 156 §6d — the TOP box of every day column.
                      Typing here writes that day into EVERY row below at
                      once; the boxes underneath stay the individual
                      per-row values.

                      The distinction is made visible rather than left to
                      be discovered: its own tinted band, a label that
                      says "all rows", and a divider under it. The
                      owner's §6b complaint was that a control whose
                      meaning you must infer is a broken control, and a
                      second row of identical-looking boxes would be
                      exactly that. */}
                  {rows.length > 0 && (
                    <tr className="hours-week-fill-row">
                      <td className="td-subject" colSpan={3}>
                        {t("hours_week_grid.fill_row_label")}
                      </td>
                      {dayKeys.map((dayKey, index) => (
                        <td key={dayKey} style={{ textAlign: "right" }}>
                          <input
                            className="field-input hours-week-grid-cell"
                            type="text"
                            inputMode="decimal"
                            // Deliberately NOT bound to state: this box
                            // is a verb, not a value. It pushes what you
                            // type into the rows below, and those rows
                            // are where the value then lives — so it
                            // holds nothing of its own to get out of
                            // step with them.
                            defaultValue=""
                            placeholder={t("hours_week_grid.fill_row_hint")}
                            onChange={(event) =>
                              fillDayForEmployee(
                                employee.id,
                                dayKey,
                                event.target.value,
                              )
                            }
                            disabled={busy || weekClosed}
                            aria-label={t("hours_week_grid.fill_row_aria", {
                              person: employee.name,
                              day: dayLabel(days[index]),
                            })}
                            data-testid={`hours-week-fill-${employee.id}-${dayKey}`}
                          />
                        </td>
                      ))}
                      <td />
                      <td />
                    </tr>
                  )}
                  {rows.map((row) => (
                    <tr key={row.key}>
                      <td className="td-select">
                        <input
                          type="checkbox"
                          checked={selectedRowKeys.includes(
                            rowSelectionKey(employee.id, row.key),
                          )}
                          onChange={() => {
                            const key = rowSelectionKey(employee.id, row.key);
                            setSelectedRowKeys((current) =>
                              current.includes(key)
                                ? current.filter((k) => k !== key)
                                : [...current, key],
                            );
                          }}
                          disabled={busy || weekClosed}
                          aria-label={hourTypeName(row.hourTypeId)}
                          data-testid={`hours-week-row-select-${employee.id}-${row.key}`}
                        />
                      </td>
                      <td className="td-subject">
                        {isAddedRow(employee.id, row.key) ? (
                          <select
                            className="field-input hours-week-row-select"
                            value={String(row.hourTypeId)}
                            onChange={(event) =>
                              retargetRow(employee.id, row, {
                                hourTypeId: Number(event.target.value),
                              })
                            }
                            disabled={busy || weekClosed}
                            aria-label={t("hours_week_grid.hour_type")}
                            data-testid={`hours-week-row-hour-type-${employee.id}-${row.key}`}
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
                        {/* Sprint 156 §6c — a row can carry a building.
                            `TimeEntry.building` has always been optional
                            and stays optional ("No building" is the
                            first option), but Sprint 155 gave no way to
                            set it, so the field was unreachable from the
                            one surface that fills a whole week. */}
                        {isAddedRow(employee.id, row.key) ? (
                          <select
                            className="field-input hours-week-row-select"
                            value={String(row.buildingId)}
                            onChange={(event) =>
                              retargetRow(employee.id, row, {
                                buildingId:
                                  event.target.value === ""
                                    ? ""
                                    : Number(event.target.value),
                              })
                            }
                            disabled={busy || weekClosed}
                            aria-label={t("hours_week_grid.building")}
                            data-testid={`hours-week-row-building-${employee.id}-${row.key}`}
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
                        {isAddedRow(employee.id, row.key) && (
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
