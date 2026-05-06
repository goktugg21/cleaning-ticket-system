import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Granularity } from "../../../api/reports.types";
import type { ReportFilters } from "../../../api/reports";
import { fetchSLABreachRateOverTime } from "../../../api/reports";
import { useReport } from "../../../hooks/useReport";

export interface ChartProps {
  filters: ReportFilters;
  refreshKey: number;
}

const GRANULARITY_LABEL: Record<Granularity, string> = {
  day: "daily",
  week: "weekly",
  month: "monthly",
};

const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function formatTick(periodStart: string, granularity: Granularity): string {
  const d = new Date(`${periodStart}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return periodStart;
  const month = MONTH_NAMES[d.getUTCMonth()];
  const day = d.getUTCDate();
  const year = d.getUTCFullYear();
  if (granularity === "day") return `${month} ${day}`;
  if (granularity === "week") return `${month} ${day} (wk)`;
  return `${month} ${year}`;
}

function rateToPct(rate: number): number {
  // recharts dataKey reads numbers; Y axis ticks format to "%".
  return Math.round(rate * 1000) / 10;
}

export function SLABreachRateChart({ filters, refreshKey }: ChartProps) {
  const { data, loading, error, retry } = useReport({
    fetcher: fetchSLABreachRateOverTime,
    filters,
    refreshKey,
  });

  const totalTickets = data
    ? data.buckets.reduce((acc, b) => acc + b.total, 0)
    : 0;

  const series = data
    ? data.buckets.map((b) => ({
        period_start: b.period_start,
        rate_pct: rateToPct(b.breach_rate),
        total: b.total,
        breached: b.breached,
      }))
    : [];

  // h3.sla-chart-title (see SLADistributionChart) so the existing admin
  // Playwright smoke runner does not pick these up. B4 extends the smoke.
  return (
    <section className="card" style={{ padding: "20px 22px", minHeight: 360 }}>
      <h3 className="sla-chart-title">SLA breach rate over time</h3>
      {data && (
        <p className="muted small" style={{ marginBottom: 8 }}>
          Granularity · {GRANULARITY_LABEL[data.granularity]} · share of
          tickets created in each bucket that ever breached
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
            Retry
          </button>
        </div>
      )}
      {!loading && !error && data && (
        totalTickets === 0 ? (
          <div
            className="muted small"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: 240,
            }}
          >
            No tickets in this range.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={series} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
              <XAxis
                dataKey="period_start"
                tickFormatter={(v: string) => formatTick(v, data.granularity)}
                tick={{ fontSize: 11 }}
              />
              <YAxis
                domain={[0, 100]}
                tickFormatter={(v: number) => `${v}%`}
                tick={{ fontSize: 11 }}
              />
              <Tooltip
                labelFormatter={(v: string) => formatTick(v, data.granularity)}
                formatter={(_value, _name, item) => {
                  const point = item.payload as {
                    rate_pct: number;
                    breached: number;
                    total: number;
                  };
                  return [
                    `${point.rate_pct}% (${point.breached} / ${point.total})`,
                    "Breach rate",
                  ];
                }}
              />
              <Line
                type="monotone"
                dataKey="rate_pct"
                stroke="#C0392B"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )
      )}
      {!loading && !error && data && (
        <p className="muted small" style={{ marginTop: 8 }}>
          Tickets in range: {totalTickets}
        </p>
      )}
    </section>
  );
}
