import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useTranslation } from "react-i18next";
import type { Granularity } from "../../../api/reports.types";
import type { ReportFilters } from "../../../api/reports";
import { fetchTicketsOverTime } from "../../../api/reports";
import { useReport } from "../../../hooks/useReport";

export interface ChartProps {
  filters: ReportFilters;
  refreshKey: number;
}

const GRANULARITY_KEY: Record<Granularity, string> = {
  day: "granularity_daily",
  week: "granularity_weekly",
  month: "granularity_monthly",
};

const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function formatTickEnglish(periodStart: string, granularity: Granularity, weekSuffix: string): string {
  const d = new Date(`${periodStart}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return periodStart;
  const month = MONTH_NAMES[d.getUTCMonth()];
  const day = d.getUTCDate();
  const year = d.getUTCFullYear();
  if (granularity === "day") return `${month} ${day}`;
  if (granularity === "week") return `${month} ${day} ${weekSuffix}`;
  return `${month} ${year}`;
}

export function TicketsOverTimeChart({ filters, refreshKey }: ChartProps) {
  const { t } = useTranslation("reports");
  const { data, loading, error, retry } = useReport({
    fetcher: fetchTicketsOverTime,
    filters,
    refreshKey,
  });

  // Month abbreviations stay English in both languages — they are recognized
  // across the operator audience and date locale-formatting is its own
  // initiative. Only the surrounding label text translates.
  const formatTick = (periodStart: string, granularity: Granularity) =>
    formatTickEnglish(periodStart, granularity, t("tick_week_suffix"));

  return (
    <section
      className="card"
      style={{ padding: "20px 22px", minHeight: 360 }}
      data-testid="chart-card-tickets-over-time"
    >
      <h3 className="section-title">{t("tickets_over_time_title")}</h3>
      {data && (
        <p className="muted small" style={{ marginBottom: 8 }}>
          {t("granularity_prefix", { value: t(GRANULARITY_KEY[data.granularity]) })}
        </p>
      )}

      {loading && (
        <div className="loading-bar" style={{ marginTop: 12, height: 240 }}>
          <div className="loading-bar-fill" />
        </div>
      )}
      {error && (
        <div className="alert-error" role="alert" style={{ marginTop: 12 }}>
          {error}{" "}
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={retry}
            style={{ marginLeft: 8 }}
          >
            {t("retry")}
          </button>
        </div>
      )}
      {!loading && !error && data && (
        data.total === 0 ? (
          <div
            className="muted small"
            data-testid="chart-empty"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: 240,
            }}
          >
            {t("tickets_over_time_empty")}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={data.series} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
              <XAxis
                dataKey="period_start"
                tickFormatter={(v: string) => formatTick(v, data.granularity)}
                tick={{ fontSize: 11 }}
              />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
              <Tooltip
                labelFormatter={(v: string) => formatTick(v, data.granularity)}
              />
              <Line
                type="monotone"
                dataKey="count"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )
      )}
      {!loading && !error && data && (
        <p className="muted small" style={{ marginTop: 8 }}>
          {t("tickets_over_time_total", { count: data.total })}
        </p>
      )}
    </section>
  );
}
