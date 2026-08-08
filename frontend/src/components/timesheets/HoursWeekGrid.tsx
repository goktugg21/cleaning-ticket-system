/**
 * Sprint 154 §M — enter a whole week of hours at once.
 *
 * Ramazan works by week, not by entry. Filing a normal week today means
 * opening the single-entry modal five to twenty times; this is one grid
 * and one Save.
 *
 * Shape: one ROW per (hour type, building) pair, one COLUMN per day
 * Mon–Sun, a Total column and a row of column totals. Building is
 * per-row and optional, which is what lets the same hour type appear
 * twice in a week for two different sites.
 *
 * Date handling goes through `lib/isoWeek.ts` exclusively — it already
 * matches Python's `isocalendar()`, and `toDateString` formats in LOCAL
 * time. `toISOString()` is never used here: it converts to UTC first, so
 * anywhere east of Greenwich a local midnight becomes the previous day
 * and the entry lands in the wrong day, sometimes the wrong week.
 *
 * The server stays the authority. A closed week is refused there
 * (`week_closed`), and this grid surfaces that message verbatim rather
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

/** One grid row: an hour type, an optional building, and seven cells. */
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
  employeeId,
  companyId,
  hourTypes,
  buildings,
  entries,
  weekClosed,
  onSaved,
}: {
  week: IsoWeek;
  /** Null when the caller has not picked an employee yet. */
  employeeId: number | null;
  companyId?: number | null;
  hourTypes: HourType[];
  buildings: BuildingAdmin[];
  /** The week's EXISTING entries, so the grid opens pre-filled. */
  entries: TimeEntry[];
  weekClosed: boolean;
  onSaved: () => void | Promise<void>;
}) {
  const { t, i18n } = useTranslation("common");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [banner, setBanner] = useState("");
  // Extra rows the operator added that have no entry behind them yet.
  const [extraRows, setExtraRows] = useState<GridRow[]>([]);
  const [edits, setEdits] = useState<Record<string, string>>({});

  const days = useMemo(() => isoWeekDays(week), [week]);
  const dayKeys = useMemo(() => days.map(toDateString), [days]);

  // Rows DERIVED from the existing entries, plus whatever the operator
  // added. Derived rather than held in state, so re-fetching after a save
  // cannot leave a stale grid behind — and so no effect has to sync
  // props into state (CLAUDE.md §3).
  const rows: GridRow[] = useMemo(() => {
    const byKey = new Map<string, GridRow>();
    for (const entry of entries) {
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
    for (const extra of extraRows) {
      if (!byKey.has(extra.key)) byKey.set(extra.key, extra);
    }
    return [...byKey.values()];
  }, [entries, extraRows]);

  const cellValue = (row: GridRow, dayKey: string) => {
    const editKey = `${row.key}|${dayKey}`;
    return edits[editKey] ?? row.cells[dayKey] ?? "";
  };

  const setCell = (row: GridRow, dayKey: string, value: string) =>
    setEdits((current) => ({ ...current, [`${row.key}|${dayKey}`]: value }));

  const rowTotal = (row: GridRow) =>
    dayKeys.reduce((sum, key) => sum + parseHours(cellValue(row, key)), 0);

  const columnTotal = (dayKey: string) =>
    rows.reduce((sum, row) => sum + parseHours(cellValue(row, dayKey)), 0);

  const weekTotal = dayKeys.reduce((sum, key) => sum + columnTotal(key), 0);

  const hourTypeName = (id: number | "") =>
    hourTypes.find((h) => h.id === id)?.name ?? String(id);

  function addRow() {
    const usedKeys = new Set(rows.map((r) => r.key));
    // First hour type that does not already have a no-building row.
    const candidate = hourTypes.find(
      (h) => !usedKeys.has(rowKey(h.id, "")),
    );
    if (!candidate) return;
    setExtraRows((current) => [
      ...current,
      {
        key: rowKey(candidate.id, ""),
        hourTypeId: candidate.id,
        buildingId: "",
        cells: {},
      },
    ]);
  }

  async function handleSave() {
    if (employeeId === null) return;
    setBusy(true);
    setError("");
    setBanner("");

    // Send only the cells that CHANGED. A grid that resent every cell
    // would rewrite untouched rows — pointless writes, and every one of
    // them re-snapshots the multiplier for no reason.
    const cells: {
      hour_type: number;
      building: number | null;
      date: string;
      hours: string;
    }[] = [];
    for (const row of rows) {
      if (row.hourTypeId === "") continue;
      for (const dayKey of dayKeys) {
        const editKey = `${row.key}|${dayKey}`;
        if (!(editKey in edits)) continue;
        const original = row.cells[dayKey] ?? "";
        const next = edits[editKey];
        if (parseHours(next) === parseHours(original)) continue;
        cells.push({
          hour_type: row.hourTypeId,
          building: row.buildingId === "" ? null : row.buildingId,
          date: dayKey,
          // "0" is meaningful: it CLEARS the cell server-side.
          hours: String(parseHours(next)),
        });
      }
    }

    if (cells.length === 0) {
      setBanner(t("hours_week_grid.no_changes"));
      setBusy(false);
      return;
    }

    try {
      const result = await saveWeekGrid({
        employee: employeeId,
        company: companyId ?? undefined,
        iso_year: week.isoYear,
        iso_week: week.isoWeek,
        cells,
      });
      const changed = result.created + result.updated + result.deleted;
      setEdits({});
      setExtraRows([]);
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

  if (employeeId === null) {
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
            {rows.map((row) => (
              <tr key={row.key}>
                <td className="td-subject">{hourTypeName(row.hourTypeId)}</td>
                <td>
                  {row.buildingId === ""
                    ? t("hours_week_grid.no_building")
                    : (buildings.find((b) => b.id === row.buildingId)?.name ??
                      String(row.buildingId))}
                </td>
                {dayKeys.map((dayKey, index) => (
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
                      aria-label={t("hours_week_grid.cell_label", {
                        hourType: hourTypeName(row.hourTypeId),
                        day: dayLabel(days[index]),
                      })}
                      data-testid={`hours-week-cell-${row.key}-${dayKey}`}
                    />
                  </td>
                ))}
                <td
                  style={{ textAlign: "right", fontWeight: 700 }}
                  data-testid={`hours-week-row-total-${row.key}`}
                >
                  {formatTotal(rowTotal(row))}
                </td>
                <td>
                  {/* An added-but-unsaved row can be dropped; a row that
                      exists on the server is cleared by zeroing its
                      cells, not by removing it from the grid — removing
                      it here would look like a delete that never
                      happened. */}
                  {extraRows.some((r) => r.key === row.key) && (
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() =>
                        setExtraRows((current) =>
                          current.filter((r) => r.key !== row.key),
                        )
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
          <tfoot>
            <tr>
              <td colSpan={2} style={{ fontWeight: 700 }}>
                {t("hours_week_grid.week_total")}
              </td>
              {dayKeys.map((dayKey) => (
                <td
                  key={dayKey}
                  style={{ textAlign: "right", fontWeight: 700 }}
                  data-testid={`hours-week-col-total-${dayKey}`}
                >
                  {formatTotal(columnTotal(dayKey))}
                </td>
              ))}
              <td
                style={{ textAlign: "right", fontWeight: 800 }}
                data-testid="hours-week-total"
              >
                {formatTotal(weekTotal)}
              </td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 8,
          marginTop: 12,
          flexWrap: "wrap",
        }}
      >
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={addRow}
          disabled={busy || weekClosed}
          data-testid="hours-week-grid-add-row"
        >
          {t("hours_week_grid.add_row")}
        </button>
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
