import { useEffect, useMemo, useState } from "react";
import { Download } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api, getApiError } from "../../api/client";
import { hourTypeLabelFrom } from "../../lib/hourTypeLabel";
import { currentIsoWeek } from "../../lib/isoWeek";

const DAYS = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
] as const;

interface WorkerHoursRow {
  iso_week: number;
  employee_id: number;
  employee_name: string;
  // Sprint 172 §5 — every reference column. `null` means "we hold no
  // value", which the table renders as an em dash; a zero would be a
  // claim, and a blank cell would be indistinguishable from a bug.
  personnel_number: string | null;
  cost_centre_name: string | null;
  cost_centre_code: string | null;
  order_number: string | null;
  place: string | null;
  action: string | null;
  debtor: string | null;
  is_authorised: boolean;
  hour_type_code: string | null;
  contracted_hours: string | null;
  travel_costs: string | null;
  building_id: number | null;
  building_name: string | null;
  hour_type_id: number;
  hour_type_name: string;
  hour_type_standard_slot: string;
  monday: string;
  tuesday: string;
  wednesday: string;
  thursday: string;
  friday: string;
  saturday: string;
  sunday: string;
  total: string;
}

interface Payload {
  iso_year: number;
  first_week: number;
  week_count: number;
  from: string;
  to: string;
  weeks: number[];
  rows: WorkerHoursRow[];
  totals: { rows: number; hours: string; weeks: number; workers: number };
}

/**
 * Sprint 171 §4 — the Worker Hour Report.
 *
 * The accounting breakdown at the end of the hours chain: entries,
 * contract hours, approval, and now the report that comes out of them.
 *
 * A year and a span of weeks, a tab per week (the reference shows four
 * at a time), four tiles, and a row per (week, worker, building, hour
 * type) with Mon–Sun and a total.
 *
 * The week tabs FILTER what is already loaded rather than re-fetching:
 * the payload covers the whole span, so switching weeks is free and the
 * tiles stay about the period rather than flickering per tab.
 */
/** An absent value is an em dash, never a blank cell and never a zero
 *  standing in for "unknown" — a blank reads as a bug and a zero reads
 *  as a measurement. */
function dash(value: string | null | undefined) {
  return value ? (
    value
  ) : (
    <span className="muted-empty">—</span>
  );
}

export function WorkerHoursView() {
  const { t } = useTranslation(["reports", "common"]);
  const start = currentIsoWeek();
  const [year, setYear] = useState(start.isoYear);
  const [firstWeek, setFirstWeek] = useState(Math.max(1, start.isoWeek - 3));
  const [weekCount, setWeekCount] = useState(4);
  const [activeWeek, setActiveWeek] = useState<number | "">("");
  const [payload, setPayload] = useState<Payload | null>(null);
  const [error, setError] = useState("");

  const requestKey = `${year}:${firstWeek}:${weekCount}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    api
      .get<Payload>("/reports/worker-hours/", {
        params: { year, week: firstWeek, weeks: weekCount },
      })
      .then((response) => {
        if (cancelled) return;
        setPayload(response.data);
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
  }, [year, firstWeek, weekCount, requestKey]);

  /** Every week in the SPAN, not only the ones with rows — a week with
   *  nothing in it is a fact the reader needs, and a tab strip that
   *  silently omits it looks like the span was shorter. */
  const weekTabs = useMemo(
    () =>
      Array.from({ length: weekCount }, (_, index) => firstWeek + index).filter(
        (week) => week <= 53,
      ),
    [firstWeek, weekCount],
  );

  const rows = useMemo(() => {
    const all = payload?.rows ?? [];
    return activeWeek === "" ? all : all.filter((r) => r.iso_week === activeWeek);
  }, [payload, activeWeek]);

  const exportUrl = (fmt: "csv" | "pdf") =>
    `/reports/worker-hours/export.${fmt}?year=${year}&week=${firstWeek}&weeks=${weekCount}`;

  async function download(fmt: "csv" | "pdf") {
    const response = await api.get(exportUrl(fmt), { responseType: "blob" });
    const href = URL.createObjectURL(response.data as Blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = `worker-hours-${year}-W${firstWeek}.${fmt}`;
    anchor.click();
    URL.revokeObjectURL(href);
  }

  const tiles = [
    { key: "rows", value: String(payload?.totals.rows ?? 0) },
    { key: "hours", value: payload?.totals.hours ?? "0.00" },
    { key: "weeks", value: String(payload?.totals.weeks ?? 0) },
    { key: "workers", value: String(payload?.totals.workers ?? 0) },
  ];

  return (
    <div data-testid="worker-hours-view">
      {error && (
        <div className="alert-error" style={{ marginBottom: 12 }} role="alert">
          {error}
        </div>
      )}

      <form className="filter-bar" onSubmit={(event) => event.preventDefault()}>
        <div className="filter-field">
          <span className="filter-label">{t("worker_hours.year")}</span>
          <input
            className="filter-control"
            type="number"
            value={year}
            onChange={(event) => setYear(Number(event.target.value))}
            data-testid="worker-hours-year"
          />
        </div>
        <div className="filter-field">
          <span className="filter-label">{t("worker_hours.first_week")}</span>
          <input
            className="filter-control"
            type="number"
            min={1}
            max={53}
            value={firstWeek}
            onChange={(event) => setFirstWeek(Number(event.target.value))}
            data-testid="worker-hours-first-week"
          />
        </div>
        <div className="filter-field">
          <span className="filter-label">{t("worker_hours.span")}</span>
          <select
            className="filter-control"
            value={weekCount}
            onChange={(event) => setWeekCount(Number(event.target.value))}
            data-testid="worker-hours-span"
          >
            {[1, 4, 8, 13].map((n) => (
              <option key={n} value={n}>
                {t("worker_hours.weeks_n", { count: n })}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => void download("csv")}
            disabled={loading}
            data-testid="worker-hours-export-csv"
          >
            <Download size={14} strokeWidth={2.5} />
            {t("worker_hours.export_excel")}
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => void download("pdf")}
            disabled={loading}
            data-testid="worker-hours-export-pdf"
          >
            <Download size={14} strokeWidth={2.5} />
            {t("worker_hours.export_pdf")}
          </button>
        </div>
      </form>

      <div
        className="hours-tile-row"
        data-testid="worker-hours-tiles"
        style={{ gridTemplateColumns: "repeat(4, minmax(0, 1fr))" }}
      >
        {tiles.map((tile) => (
          <div key={tile.key} className="hours-tile">
            <span className="hours-tile-label">
              {t(`worker_hours.tile_${tile.key}`)}
            </span>
            <span className="hours-tile-value">{tile.value}</span>
          </div>
        ))}
      </div>

      {/* The week tab strip. It filters what is already loaded — the
          payload covers the whole span, so switching weeks costs no
          request and the tiles stay about the period. */}
      <div
        className="composer-toggle"
        role="tablist"
        style={{ marginBottom: 12 }}
        data-testid="worker-hours-week-tabs"
      >
        <button
          type="button"
          role="tab"
          aria-selected={activeWeek === ""}
          className={`composer-toggle-btn ${activeWeek === "" ? "active" : ""}`}
          onClick={() => setActiveWeek("")}
          data-testid="worker-hours-week-all"
        >
          {t("worker_hours.all_weeks")}
        </button>
        {weekTabs.map((week) => (
          <button
            key={week}
            type="button"
            role="tab"
            aria-selected={activeWeek === week}
            className={`composer-toggle-btn ${activeWeek === week ? "active" : ""}`}
            onClick={() => setActiveWeek(week)}
            data-testid={`worker-hours-week-${week}`}
          >
            W{week}
          </button>
        ))}
      </div>

      {loading && (
        <div className="loading-bar" style={{ margin: 0 }}>
          <div className="loading-bar-fill" />
        </div>
      )}

      <div className="table-wrap admin-list-wrap">
        <table className="data-table data-table-dense hours-comparison-table">
          <thead>
            <tr>
              <th>{t("worker_hours.col_week")}</th>
              <th>{t("worker_hours.col_personnel")}</th>
              <th>{t("worker_hours.col_worker")}</th>
              <th>{t("worker_hours.col_cost_centre")}</th>
              <th>{t("worker_hours.col_cost_code")}</th>
              <th>{t("worker_hours.col_order")}</th>
              <th>{t("worker_hours.col_place")}</th>
              <th>{t("worker_hours.col_action")}</th>
              <th>{t("worker_hours.col_debtor")}</th>
              <th>{t("worker_hours.col_authorised")}</th>
              <th>{t("worker_hours.col_hour_code")}</th>
              <th>{t("worker_hours.col_hour_type")}</th>
              <th className="contract-num">
                {t("worker_hours.col_contracted")}
              </th>
              <th className="contract-num">{t("worker_hours.col_travel")}</th>
              {DAYS.map((day) => (
                <th key={day} className="contract-num">
                  {t(`common:contract_hours.day_${day}`)}
                </th>
              ))}
              <th className="contract-num">{t("worker_hours.col_total")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={`${row.iso_week}:${row.employee_id}:${row.building_id ?? 0}:${row.hour_type_id}`}
                data-testid="worker-hours-row"
              >
                <td>W{row.iso_week}</td>
                <td>{dash(row.personnel_number)}</td>
                <td className="td-subject">{row.employee_name}</td>
                <td>{dash(row.cost_centre_name)}</td>
                <td>{dash(row.cost_centre_code)}</td>
                <td>{dash(row.order_number)}</td>
                <td>{dash(row.place)}</td>
                <td>{dash(row.action)}</td>
                <td>{dash(row.debtor)}</td>
                <td>
                  {row.is_authorised ? (
                    t("worker_hours.yes")
                  ) : (
                    <span className="muted-empty">—</span>
                  )}
                </td>
                <td>{dash(row.hour_type_code)}</td>
                <td>
                  {hourTypeLabelFrom(
                    row.hour_type_name,
                    row.hour_type_standard_slot,
                    t,
                  )}
                </td>
                <td className="contract-num">{dash(row.contracted_hours)}</td>
                <td className="contract-num">{dash(row.travel_costs)}</td>
                {DAYS.map((day) => (
                  <td key={day} className="contract-num">
                    {row[day]}
                  </td>
                ))}
                <td className="contract-num">
                  <strong>{row.total}</strong>
                </td>
              </tr>
            ))}
            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={22} className="muted">
                  {t("worker_hours.empty")}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Stated on screen, not only in a sprint report: the reference
          carries columns we hold no data for, and an empty column that
          looks like data is worse than an absent one. */}
      <p className="muted small" data-testid="worker-hours-missing-note">
        {t("worker_hours.missing_columns")}
      </p>
    </div>
  );
}
