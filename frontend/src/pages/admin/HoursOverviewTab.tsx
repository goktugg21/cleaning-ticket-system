import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  closeWeek,
  fetchTimesheetSummary,
  fetchWeekStatus,
  listTimeEntries,
  listWeekLocks,
  reopenWeek,
} from "../../api/timesheets";
import type {
  HourType,
  TimeEntry,
  TimeEntryFilters,
  TimesheetEmployee,
  TimesheetSummary,
  WeekLock,
  WeekStatus,
} from "../../api/timesheets.types";
import { NO_BUILDING_MARKER } from "../../api/timesheets.types";
import type { BuildingAdmin } from "../../api/types";
import { BoundedList } from "../../components/BoundedList";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { useToast } from "../../components/ToastProvider";
import {
  currentIsoWeek,
  formatIsoWeek,
  fromDateString,
  isoWeekDays,
  isoWeekOf,
  shiftIsoWeek,
  toDateString,
} from "../../lib/isoWeek";
import type { IsoWeek } from "../../lib/isoWeek";
import { HoursCharts } from "./HoursCharts";
import { HoursFilterRow } from "./HoursFilterRow";
import type { HoursFilterValues } from "./HoursFilterRow";

/**
 * Sprint 152.2 — the "Overzicht" / "Overview" tab (was "Weken").
 *
 * ## This tab is READ-ONLY with respect to hours
 *
 * Stated here because it is a design decision, not an omission. Time
 * entries are created and edited on the ENTRIES tab; nothing here
 * mutates a `TimeEntry` — no add button, no row actions, no edit form.
 * This is the analytical surface: pick a period, filter it, read what
 * happened. Keeping the two apart means an operator exploring a report
 * cannot change the data underneath it by a misplaced click, and it
 * keeps this file free of the write paths (snapshot, week lock,
 * eligibility) that make the entries tab what it is.
 *
 * The ONE thing it still writes is the WEEK LOCK, which belongs here:
 * closing a week is an act on a PERIOD, not on an entry, and this is
 * the surface that has a period selected.
 *
 * ## One query shape
 *
 * The period selector has two MODES — a week stepper and a from/to
 * range — but both resolve to the same `date_from` / `date_to` pair
 * before anything is fetched (a week resolves to its Monday and Sunday
 * through the existing `isoWeek` helpers). There is one query shape
 * downstream, not two code paths that must be kept in step.
 */

type PeriodMode = "week" | "range";

interface RangeState {
  from: string;
  to: string;
}

const EMPTY_FILTERS: HoursFilterValues = {
  employee: "",
  hour_type: "",
  building: "",
};

function monthStart(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function monthEnd(date: Date): Date {
  // Day 0 of the NEXT month is the last day of this one — no table of
  // month lengths and no leap-year special case.
  return new Date(date.getFullYear(), date.getMonth() + 1, 0);
}

/**
 * The quick presets. Shortcuts only — the from/to inputs stay usable for
 * an arbitrary span, which is the actual requirement ("3 months and 24
 * days" was the owner's own example). A preset list that was the ONLY
 * way in would answer a narrower question than the one being asked.
 */
function presetRange(key: string): RangeState {
  const today = new Date();
  switch (key) {
    case "this_month":
      return {
        from: toDateString(monthStart(today)),
        to: toDateString(monthEnd(today)),
      };
    case "last_month": {
      const previous = new Date(today.getFullYear(), today.getMonth() - 1, 1);
      return {
        from: toDateString(monthStart(previous)),
        to: toDateString(monthEnd(previous)),
      };
    }
    case "last_3_months": {
      const start = new Date(today.getFullYear(), today.getMonth() - 2, 1);
      return {
        from: toDateString(monthStart(start)),
        to: toDateString(monthEnd(today)),
      };
    }
    case "this_year":
      return {
        from: toDateString(new Date(today.getFullYear(), 0, 1)),
        to: toDateString(new Date(today.getFullYear(), 11, 31)),
      };
    default:
      return { from: "", to: "" };
  }
}

const PRESET_KEYS = [
  "this_month",
  "last_month",
  "last_3_months",
  "this_year",
] as const;

export interface HoursOverviewTabProps {
  selectedCompany?: number | "";
  employees: TimesheetEmployee[];
  hourTypes: HourType[];
  buildings: BuildingAdmin[];
}

export function HoursOverviewTab({
  selectedCompany = "",
  employees,
  hourTypes,
  buildings,
}: HoursOverviewTabProps) {
  const { t, i18n } = useTranslation("common");
  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";
  const { push: pushToast } = useToast();

  const [mode, setMode] = useState<PeriodMode>("week");
  const [week, setWeek] = useState<IsoWeek>(() => currentIsoWeek());
  const [range, setRange] = useState<RangeState>(() =>
    presetRange("this_month"),
  );
  const [filters, setFilters] = useState<HoursFilterValues>(EMPTY_FILTERS);

  const [summary, setSummary] = useState<TimesheetSummary | null>(null);
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [entryCount, setEntryCount] = useState(0);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [status, setStatus] = useState<WeekStatus | null>(null);
  const [locks, setLocks] = useState<WeekLock[]>([]);
  const [loadError, setLoadError] = useState("");
  const [actionBusy, setActionBusy] = useState(false);

  const closeDialogRef = useRef<ConfirmDialogHandle>(null);
  const reopenDialogRef = useRef<ConfirmDialogHandle>(null);

  const weekDays = useMemo(() => isoWeekDays(week), [week]);

  // BOTH modes resolve here, once. Everything downstream sees a plain
  // date pair and never learns which control produced it.
  const period = useMemo(
    () =>
      mode === "week"
        ? { date_from: toDateString(weekDays[0]), date_to: toDateString(weekDays[6]) }
        : { date_from: range.from, date_to: range.to },
    [mode, weekDays, range],
  );

  const queryFilters: TimeEntryFilters = useMemo(
    () => ({
      company: selectedCompany,
      employee: filters.employee,
      hour_type: filters.hour_type,
      building: filters.building,
      date_from: period.date_from,
      date_to: period.date_to,
    }),
    [selectedCompany, filters, period],
  );

  // Derived `loading` — never a `setLoading(true)` in an effect body
  // (CLAUDE.md; `react-hooks/set-state-in-effect`).
  const fetchKey = `${JSON.stringify(queryFilters)}|${page}|${mode}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading = loadedKey !== fetchKey;

  const periodLabel = useMemo(() => {
    const options: Intl.DateTimeFormatOptions = {
      day: "2-digit",
      month: "short",
      year: "numeric",
    };
    const from = period.date_from
      ? fromDateString(period.date_from).toLocaleDateString(dateLocale, options)
      : "…";
    const to = period.date_to
      ? fromDateString(period.date_to).toLocaleDateString(dateLocale, options)
      : "…";
    return `${from} – ${to}`;
  }, [period, dateLocale]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchTimesheetSummary(queryFilters),
      listTimeEntries({ ...queryFilters, page }),
      listWeekLocks({ company: selectedCompany }),
      // Only asked in WEEK mode — a range has no single lock state, and
      // asking anyway would mean interpreting an answer nothing renders.
      mode === "week"
        ? fetchWeekStatus({
            iso_year: week.isoYear,
            iso_week: week.isoWeek,
            company: selectedCompany,
          })
        : Promise.resolve(null),
    ])
      .then(([summaryPayload, entryPage, lockRows, weekStatus]) => {
        if (cancelled) return;
        setSummary(summaryPayload);
        setEntries(entryPage.results);
        setEntryCount(entryPage.count);
        setHasNext(Boolean(entryPage.next));
        setLocks(lockRows);
        setStatus(weekStatus);
        setLoadError("");
        setLoadedKey(fetchKey);
      })
      .catch((err) => {
        if (cancelled) return;
        // Includes the backend's `timesheet_period_invalid` 400 — which,
        // before Sprint 152.2, was an unhandled 500 here.
        setLoadError(getApiError(err));
        setLoadedKey(fetchKey);
      });
    return () => {
      cancelled = true;
    };
  }, [queryFilters, page, mode, week, selectedCompany, fetchKey]);

  /** Re-read after a week lock action. Never throws — see the entries tab. */
  async function refresh() {
    try {
      const [summaryPayload, lockRows, weekStatus] = await Promise.all([
        fetchTimesheetSummary(queryFilters),
        listWeekLocks({ company: selectedCompany }),
        mode === "week"
          ? fetchWeekStatus({
              iso_year: week.isoYear,
              iso_week: week.isoWeek,
              company: selectedCompany,
            })
          : Promise.resolve(null),
      ]);
      setSummary(summaryPayload);
      setLocks(lockRows);
      setStatus(weekStatus);
      setLoadError("");
    } catch {
      setLoadError(t("admin.refresh_after_save_failed"));
    }
  }

  // Any change to what is being asked returns to page 1 — done in the
  // HANDLERS, not an effect. A narrower filter left on page 3 of the old
  // result set renders as "no results", which reads as a broken filter.
  function patchFilters(patch: Partial<HoursFilterValues>) {
    setFilters((prev) => ({ ...prev, ...patch }));
    setPage(1);
  }

  function applyMode(next: PeriodMode) {
    setMode(next);
    setPage(1);
  }

  function applyWeek(next: IsoWeek) {
    setWeek(next);
    setPage(1);
  }

  function applyRange(next: RangeState) {
    setRange(next);
    setPage(1);
  }

  async function handleConfirmClose() {
    setActionBusy(true);
    try {
      await closeWeek({
        iso_year: week.isoYear,
        iso_week: week.isoWeek,
        company: selectedCompany,
      });
      await refresh();
      closeDialogRef.current?.close();
      pushToast({
        variant: "success",
        title: t("weeks.close_done", { week: formatIsoWeek(week) }),
      });
    } catch (err) {
      setLoadError(getApiError(err));
      closeDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  async function handleConfirmReopen() {
    setActionBusy(true);
    try {
      await reopenWeek({
        iso_year: week.isoYear,
        iso_week: week.isoWeek,
        company: selectedCompany,
      });
      await refresh();
      reopenDialogRef.current?.close();
      pushToast({
        variant: "success",
        title: t("weeks.reopen_done", { week: formatIsoWeek(week) }),
      });
    } catch (err) {
      setLoadError(getApiError(err));
      reopenDialogRef.current?.close();
    } finally {
      setActionBusy(false);
    }
  }

  const isClosed = status?.is_closed ?? false;
  const hasData = (summary?.total_entries ?? 0) > 0;

  function buildingLabel(name: string): string {
    return name === NO_BUILDING_MARKER ? t("hours_admin.no_building") : name;
  }

  return (
    <>
      {/* ---- Period selector ------------------------------------- */}
      <div className="card" style={{ padding: "16px 18px", marginBottom: 16 }}>
        <div
          className="composer-toggle"
          role="tablist"
          aria-label={t("overview.period_mode_aria")}
          style={{ marginBottom: 12 }}
        >
          <button
            type="button"
            role="tab"
            aria-selected={mode === "week"}
            className={`composer-toggle-btn ${mode === "week" ? "active" : ""}`}
            data-testid="overview-mode-week"
            onClick={() => applyMode("week")}
          >
            {t("overview.mode_week")}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "range"}
            className={`composer-toggle-btn ${mode === "range" ? "active" : ""}`}
            data-testid="overview-mode-range"
            onClick={() => applyMode("range")}
          >
            {t("overview.mode_range")}
          </button>
        </div>

        {mode === "week" ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              flexWrap: "wrap",
            }}
          >
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              data-testid="overview-prev-week"
              onClick={() => applyWeek(shiftIsoWeek(week, -1))}
            >
              {t("my_hours.previous_week")}
            </button>
            <div style={{ minWidth: 210, textAlign: "center" }}>
              <div style={{ fontWeight: 600 }} data-testid="overview-week-label">
                {formatIsoWeek(week)}
              </div>
              <div className="muted small">{periodLabel}</div>
            </div>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              data-testid="overview-next-week"
              onClick={() => applyWeek(shiftIsoWeek(week, 1))}
            >
              {t("my_hours.next_week")}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              data-testid="overview-this-week"
              onClick={() => applyWeek(currentIsoWeek())}
            >
              {t("my_hours.this_week")}
            </button>
            <div className="field" style={{ margin: 0, minWidth: 170 }}>
              <label className="sr-only" htmlFor="overview-week-jump">
                {t("my_hours.jump_to_week")}
              </label>
              <input
                id="overview-week-jump"
                className="field-input"
                type="date"
                data-testid="overview-week-jump"
                value={toDateString(weekDays[0])}
                onChange={(event) => {
                  if (!event.target.value) return;
                  applyWeek(isoWeekOf(fromDateString(event.target.value)));
                }}
              />
            </div>
          </div>
        ) : (
          <>
            <div
              style={{
                display: "flex",
                gap: 12,
                flexWrap: "wrap",
                alignItems: "flex-end",
              }}
            >
              <div className="field" style={{ margin: 0, minWidth: 170 }}>
                <label className="field-label" htmlFor="overview-range-from">
                  {t("hours_admin.filter_date_from")}
                </label>
                <input
                  id="overview-range-from"
                  className="field-input"
                  type="date"
                  value={range.from}
                  onChange={(event) =>
                    applyRange({ ...range, from: event.target.value })
                  }
                  data-testid="overview-range-from"
                />
              </div>
              <div className="field" style={{ margin: 0, minWidth: 170 }}>
                <label className="field-label" htmlFor="overview-range-to">
                  {t("hours_admin.filter_date_to")}
                </label>
                <input
                  id="overview-range-to"
                  className="field-input"
                  type="date"
                  value={range.to}
                  onChange={(event) =>
                    applyRange({ ...range, to: event.target.value })
                  }
                  data-testid="overview-range-to"
                />
              </div>
            </div>
            <div
              style={{
                display: "flex",
                gap: 8,
                flexWrap: "wrap",
                marginTop: 10,
              }}
            >
              {/* Shortcuts, never the only way in — an arbitrary span is
                  the point of this mode. */}
              {PRESET_KEYS.map((key) => (
                <button
                  key={key}
                  type="button"
                  className="btn btn-ghost btn-sm"
                  data-testid={`overview-preset-${key}`}
                  onClick={() => applyRange(presetRange(key))}
                >
                  {t(`overview.preset_${key}`)}
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      {/* ---- Filters --------------------------------------------- */}
      <div
        className="card"
        style={{ padding: "16px 18px", marginBottom: 16 }}
        data-testid="overview-filters"
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 12,
          }}
        >
          <HoursFilterRow
            values={filters}
            onChange={patchFilters}
            employees={employees}
            hourTypes={hourTypes}
            buildings={buildings}
            idPrefix="overview"
          />
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            marginTop: 12,
          }}
        >
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="overview-filters-reset"
            onClick={() => {
              setFilters(EMPTY_FILTERS);
              setPage(1);
            }}
          >
            {t("hours_admin.filter_reset")}
          </button>
        </div>
      </div>

      {loadError && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {loadError}
        </div>
      )}

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : (
        <>
          {/* ---- Totals ------------------------------------------ */}
          {summary && (
            <section
              className="card"
              style={{ padding: "18px 22px", marginBottom: 16 }}
              data-testid="overview-totals"
            >
              <h3 className="section-title" style={{ margin: 0 }}>
                {t("overview.totals_title")}
              </h3>
              <p className="muted small" style={{ margin: "4px 0 12px" }}>
                {periodLabel}
              </p>
              {!hasData ? (
                <p
                  className="muted"
                  style={{ margin: 0 }}
                  data-testid="overview-empty"
                >
                  {t("overview.empty_period")}
                </p>
              ) : (
                <div className="detail-kv-list">
                  <div className="detail-kv-row">
                    <span className="detail-kv-label">
                      {t("hours_admin.summary_entries")}
                    </span>
                    <span
                      className="detail-kv-val"
                      data-testid="overview-total-entries"
                    >
                      {summary.total_entries}
                    </span>
                  </div>
                  <div className="detail-kv-row">
                    <span className="detail-kv-label">
                      {t("hours_admin.summary_hours")}
                    </span>
                    <span
                      className="detail-kv-val"
                      data-testid="overview-total-hours"
                    >
                      {summary.total_hours}
                    </span>
                  </div>
                  <div className="detail-kv-row">
                    <span className="detail-kv-label">
                      {t("hours_admin.summary_weighted")}
                    </span>
                    <span
                      className="detail-kv-val"
                      data-testid="overview-total-weighted"
                    >
                      {summary.total_weighted_hours}
                    </span>
                  </div>
                </div>
              )}
            </section>
          )}

          {/* ---- Graphs ------------------------------------------ */}
          {summary && hasData && <HoursCharts summary={summary} />}

          {/* ---- Breakdown tables -------------------------------- */}
          {summary && hasData && (
            <section
              className="card"
              style={{ padding: "18px 22px", marginBottom: 16 }}
              data-testid="overview-breakdowns"
            >
              <h3 className="section-title" style={{ margin: 0 }}>
                {t("overview.breakdowns_title")}
              </h3>
              <p className="muted small" style={{ margin: "4px 0 8px" }}>
                {t("overview.breakdowns_subtitle")}
              </p>

              <h4 className="eyebrow" style={{ margin: "18px 0 8px" }}>
                {t("overview.by_employee")}
              </h4>
              <div className="table-wrap">
                <table
                  className="data-table"
                  data-testid="overview-table-by-employee"
                >
                  <thead>
                    <tr>
                      <th>{t("hours_admin.col_employee")}</th>
                      <th>{t("hours_admin.col_entries")}</th>
                      <th>{t("hours_admin.col_hours")}</th>
                      <th>{t("hours_admin.col_weighted")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.by_employee.map((bucket) => (
                      <tr key={bucket.employee} data-testid="overview-employee-row">
                        <td>{bucket.employee_name}</td>
                        <td className="muted small">{bucket.entries}</td>
                        <td>{bucket.hours}</td>
                        <td className="muted">{bucket.weighted_hours}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <h4 className="eyebrow" style={{ margin: "18px 0 8px" }}>
                {t("overview.by_building")}
              </h4>
              <div className="table-wrap">
                <table
                  className="data-table"
                  data-testid="overview-table-by-building"
                >
                  <thead>
                    <tr>
                      <th>{t("hours_admin.col_building")}</th>
                      <th>{t("hours_admin.col_entries")}</th>
                      <th>{t("hours_admin.col_hours")}</th>
                      <th>{t("hours_admin.col_weighted")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.by_building.map((bucket) => (
                      <tr
                        key={bucket.building ?? "none"}
                        data-testid="overview-building-row"
                      >
                        <td>{buildingLabel(bucket.building_name)}</td>
                        <td className="muted small">{bucket.entries}</td>
                        <td>{bucket.hours}</td>
                        <td className="muted">{bucket.weighted_hours}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <h4 className="eyebrow" style={{ margin: "18px 0 8px" }}>
                {t("hours_admin.report_by_hour_type")}
              </h4>
              <div className="table-wrap">
                <table
                  className="data-table"
                  data-testid="overview-table-by-hour-type"
                >
                  <thead>
                    <tr>
                      <th>{t("hours_admin.col_hour_type")}</th>
                      <th>{t("hours_admin.col_current_multiplier")}</th>
                      <th>{t("hours_admin.col_entries")}</th>
                      <th>{t("hours_admin.col_hours")}</th>
                      <th>{t("hours_admin.col_weighted_from_snapshot")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.by_hour_type.map((bucket) => (
                      <tr key={bucket.hour_type}>
                        <td>{bucket.hour_type_name}</td>
                        <td className="muted small">
                          x{bucket.current_multiplier}
                        </td>
                        <td className="muted small">{bucket.entries}</td>
                        <td>{bucket.hours}</td>
                        <td className="muted">{bucket.weighted_hours}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <h4 className="eyebrow" style={{ margin: "18px 0 8px" }}>
                {t("hours_admin.report_by_week")}
              </h4>
              <div className="table-wrap">
                <table
                  className="data-table"
                  data-testid="overview-table-by-week"
                >
                  <thead>
                    <tr>
                      <th>{t("hours_admin.col_week")}</th>
                      <th>{t("hours_admin.col_period")}</th>
                      <th>{t("hours_admin.col_entries")}</th>
                      <th>{t("hours_admin.col_hours")}</th>
                      <th>{t("hours_admin.col_weighted")}</th>
                      <th>{t("hours_admin.col_week_status")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.by_week.map((bucket) => (
                      <tr
                        key={`${bucket.iso_year}-${bucket.iso_week}`}
                        data-closed={bucket.is_closed ? "true" : "false"}
                      >
                        <td>
                          {bucket.iso_year}-W
                          {String(bucket.iso_week).padStart(2, "0")}
                        </td>
                        <td className="muted small">
                          {bucket.week_start} – {bucket.week_end}
                        </td>
                        <td className="muted small">{bucket.entries}</td>
                        <td>{bucket.hours}</td>
                        <td className="muted">{bucket.weighted_hours}</td>
                        <td>
                          <span
                            className={
                              bucket.is_closed
                                ? "badge badge-closed"
                                : "badge badge-approved"
                            }
                          >
                            {bucket.is_closed
                              ? t("weeks.status_closed")
                              : t("weeks.status_open")}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {/* ---- Read-only entries ------------------------------- */}
          <section
            className="card"
            style={{ marginBottom: 16 }}
            data-testid="overview-entries"
          >
            <div style={{ padding: "18px 22px 0" }}>
              <h3 className="section-title" style={{ margin: 0 }}>
                {t("overview.entries_title")}
              </h3>
              <p className="muted small" style={{ margin: "4px 0 8px" }}>
                {t("overview.entries_subtitle")}
              </p>
            </div>
            {/* Bounded AND server-paginated: a 3-month range at a real
                tenant is thousands of rows, so neither alone is enough —
                pagination keeps the RESPONSE sane, BoundedList keeps the
                page from growing without limit. */}
            <BoundedList
              size="lg"
              count={entries.length}
              ariaLabel={t("overview.entries_aria")}
              testIdPrefix="overview-entries"
              className="table-wrap"
              emptyState={
                <div
                  style={{ padding: "24px", textAlign: "center" }}
                  className="muted"
                  data-testid="overview-entries-empty"
                >
                  {t("overview.empty_period")}
                </div>
              }
            >
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t("hours_admin.col_date")}</th>
                    <th>{t("hours_admin.col_employee")}</th>
                    <th>{t("hours_admin.col_hour_type")}</th>
                    <th>{t("hours_admin.col_hours")}</th>
                    <th>{t("hours_admin.col_weighted")}</th>
                    <th>{t("hours_admin.col_building")}</th>
                    <th>{t("hours_admin.col_note")}</th>
                  </tr>
                </thead>
                <tbody>
                  {entries.map((entry) => (
                    <tr key={entry.id} data-testid="overview-entry-row">
                      <td>
                        {fromDateString(entry.date).toLocaleDateString(
                          dateLocale,
                          { day: "2-digit", month: "short", year: "numeric" },
                        )}
                      </td>
                      <td>{entry.employee_name}</td>
                      <td>{entry.hour_type_name}</td>
                      <td>{entry.hours}</td>
                      <td className="muted">{entry.weighted_hours}</td>
                      <td className="muted small">
                        {entry.building_name ?? "—"}
                      </td>
                      <td className="muted small">{entry.note || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </BoundedList>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                padding: "12px 16px",
              }}
            >
              <span className="muted small">
                {t("hours_admin.pagination_summary", {
                  shown: entries.length,
                  total: entryCount,
                })}
              </span>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  data-testid="overview-entries-prev"
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                  disabled={page <= 1}
                >
                  {t("hours_admin.prev_page")}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  data-testid="overview-entries-next"
                  onClick={() => setPage((current) => current + 1)}
                  disabled={!hasNext}
                >
                  {t("hours_admin.next_page")}
                </button>
              </div>
            </div>
          </section>
        </>
      )}

      {/* ---- Week close / reopen ------------------------------- */}
      <div
        className="alert-info"
        role="note"
        style={{ marginBottom: 16 }}
        data-testid="weeks-explainer"
      >
        <p style={{ margin: "0 0 6px" }}>
          <strong>{t("weeks.explainer_close_title")}</strong>{" "}
          {t("weeks.explainer_close_body")}
        </p>
        <p style={{ margin: 0 }}>
          <strong>{t("weeks.explainer_reopen_title")}</strong>{" "}
          {t("weeks.explainer_reopen_body")}
        </p>
      </div>

      <div className="card" style={{ padding: "18px 22px", marginBottom: 16 }}>
        <div className="eyebrow" style={{ marginBottom: 10 }}>
          {t("weeks.picker_title")}
        </div>
        {mode === "week" ? (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              flexWrap: "wrap",
            }}
          >
            <span
              className={isClosed ? "badge badge-closed" : "badge badge-approved"}
              data-testid="weeks-status-badge"
              data-closed={isClosed ? "true" : "false"}
            >
              {loading
                ? t("weeks.status_loading")
                : isClosed
                  ? t("weeks.status_closed")
                  : t("weeks.status_open")}
            </span>
            <span className="muted small">{formatIsoWeek(week)}</span>
            {isClosed && status?.lock && (
              <span className="muted small" data-testid="weeks-closed-by">
                {t("weeks.closed_by", {
                  name: status.lock.closed_by_name,
                  when: new Date(status.lock.closed_at).toLocaleString(
                    dateLocale,
                    {
                      day: "2-digit",
                      month: "short",
                      year: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    },
                  ),
                })}
              </span>
            )}
            <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
              {isClosed ? (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  data-testid="weeks-reopen-button"
                  onClick={() => reopenDialogRef.current?.open()}
                  disabled={loading || actionBusy}
                >
                  {t("weeks.reopen_button")}
                </button>
              ) : (
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  data-testid="weeks-close-button"
                  onClick={() => closeDialogRef.current?.open()}
                  disabled={loading || actionBusy}
                >
                  {t("weeks.close_button")}
                </button>
              )}
            </div>
          </div>
        ) : (
          /* Range mode: SAY why the control is absent rather than
             disabling it without explanation or silently dropping it. A
             lock is per week; a 97-day range has no single lock state to
             act on. */
          <p
            className="muted small"
            style={{ margin: 0 }}
            data-testid="weeks-range-mode-note"
          >
            {t("weeks.range_mode_note")}
          </p>
        )}
      </div>

      <div className="card" data-testid="weeks-lock-list">
        <BoundedList
          size="md"
          count={locks.length}
          ariaLabel={t("weeks.list_aria")}
          testIdPrefix="weeks-locks"
          className="table-wrap"
          emptyState={
            <div
              style={{ padding: "32px 24px", textAlign: "center" }}
              data-testid="weeks-locks-empty"
            >
              <h3 style={{ marginBottom: 8 }}>{t("weeks.empty_title")}</h3>
              <p className="muted" style={{ margin: 0 }}>
                {t("weeks.empty_description")}
              </p>
            </div>
          }
        >
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("weeks.col_week")}</th>
                <th>{t("weeks.col_company")}</th>
                <th>{t("weeks.col_closed_at")}</th>
                <th>{t("weeks.col_closed_by")}</th>
              </tr>
            </thead>
            <tbody>
              {locks.map((lock) => (
                <tr
                  key={lock.id}
                  data-testid="weeks-lock-row"
                  data-lock-id={lock.id}
                >
                  <td>
                    {formatIsoWeek({
                      isoYear: lock.iso_year,
                      isoWeek: lock.iso_week,
                    })}
                  </td>
                  <td className="muted small">{lock.company_name}</td>
                  <td className="muted small">
                    {new Date(lock.closed_at).toLocaleString(dateLocale, {
                      day: "2-digit",
                      month: "short",
                      year: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </td>
                  <td className="muted small">{lock.closed_by_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </BoundedList>
      </div>

      {/* Unconditionally rendered and ref-driven (CLAUDE.md §3), in BOTH
          modes: a native <dialog> mounted behind a condition is invisible
          and its trigger looks dead. */}
      <ConfirmDialog
        ref={closeDialogRef}
        title={t("weeks.close_confirm_title", { week: formatIsoWeek(week) })}
        body={t("weeks.close_confirm_body")}
        confirmLabel={t("weeks.close_button")}
        onConfirm={handleConfirmClose}
        busy={actionBusy}
      />

      <ConfirmDialog
        ref={reopenDialogRef}
        title={t("weeks.reopen_confirm_title", { week: formatIsoWeek(week) })}
        body={t("weeks.reopen_confirm_body")}
        confirmLabel={t("weeks.reopen_button")}
        onConfirm={handleConfirmReopen}
        busy={actionBusy}
        destructive
      />
    </>
  );
}
