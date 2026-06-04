import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useTranslation } from "react-i18next";
import type { ReportFilters } from "../../../api/reports";
import { fetchExtraWorkRevenue } from "../../../api/reports";
import type { ExtraWorkRevenueState } from "../../../api/reports.types";
import { useReport } from "../../../hooks/useReport";
import { formatMoney } from "../../../lib/intl";
import { ExportButtons } from "./ExportButtons";

export interface ChartProps {
  filters: ReportFilters;
  refreshKey: number;
}

// Fixed emphasis order: EARNED is the headline (realised money — the
// spawned ticket is closed), then IN_PROGRESS (committed but not yet
// closed), then the not-yet-won states. The grouping axis IS the revenue
// state; this is Extra Work's own reporting (SoT §7.2), not a ticket count.
const STATE_ORDER: ExtraWorkRevenueState[] = [
  "earned",
  "in_progress",
  "quoted_pipeline",
  "lost",
];

// Earned = green (headline), in_progress = blue, quoted_pipeline = amber,
// lost = muted gray. Mirrors the SLA-distribution palette.
const STATE_COLOR: Record<ExtraWorkRevenueState, string> = {
  earned: "#0B6B42",
  in_progress: "#2563eb",
  quoted_pipeline: "#9A5A00",
  lost: "#8A9B91",
};

export function ExtraWorkRevenueChart({ filters, refreshKey }: ChartProps) {
  const { t } = useTranslation("reports");
  const { data, loading, error, retry } = useReport({
    fetcher: fetchExtraWorkRevenue,
    filters,
    refreshKey,
  });

  // One row per revenue state. `total` is the billable amount incl. VAT —
  // the figure the backend `totals` aggregates. Parse the decimal string to
  // a number ONLY for the bar height; every visible amount goes through
  // formatMoney on the original string, so no money math happens here.
  const rows = data
    ? STATE_ORDER.map((state) => ({
        state,
        name: t(`ew_revenue_state_${state}`),
        total: Number.parseFloat(data.states[state].total),
        count: data.states[state].count,
      }))
    : [];

  const isEmpty = data ? data.totals.count === 0 : false;

  return (
    <section
      className="card"
      style={{ padding: "20px 22px", minHeight: 360, marginBottom: 16 }}
      data-testid="chart-card-extra-work-revenue"
    >
      <h3 className="section-title">{t("ew_revenue_title")}</h3>
      <p className="muted small" style={{ marginBottom: 8 }}>
        {t("ew_revenue_subtitle")}
      </p>

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

      {!loading && !error && data && isEmpty && (
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
          {t("ew_revenue_empty")}
        </div>
      )}

      {!loading && !error && data && !isEmpty && (
        <>
          {/* EARNED is the headline number; IN_PROGRESS sits beside it. */}
          <div
            data-testid="ew-revenue-kpis"
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 24,
              alignItems: "flex-end",
              marginBottom: 14,
            }}
          >
            <div data-testid="ew-revenue-earned">
              <div
                style={{
                  fontSize: 28,
                  fontWeight: 700,
                  lineHeight: 1.1,
                  color: STATE_COLOR.earned,
                }}
              >
                {formatMoney(data.states.earned.total)}
              </div>
              <div className="muted small" style={{ marginTop: 2 }}>
                {t("ew_revenue_state_earned")} ·{" "}
                {t("ew_revenue_requests", { count: data.states.earned.count })}
              </div>
            </div>
            <div data-testid="ew-revenue-in-progress">
              <div
                style={{
                  fontSize: 20,
                  fontWeight: 600,
                  lineHeight: 1.1,
                  color: STATE_COLOR.in_progress,
                }}
              >
                {formatMoney(data.states.in_progress.total)}
              </div>
              <div className="muted small" style={{ marginTop: 2 }}>
                {t("ew_revenue_state_in_progress")} ·{" "}
                {t("ew_revenue_requests", {
                  count: data.states.in_progress.count,
                })}
              </div>
            </div>
          </div>

          <ResponsiveContainer
            width="100%"
            height={Math.max(180, rows.length * 44)}
          >
            <BarChart
              data={rows}
              layout="vertical"
              margin={{ top: 8, right: 24, bottom: 8, left: 8 }}
            >
              <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
              <XAxis
                type="number"
                tick={{ fontSize: 11 }}
                tickFormatter={(value: number) => formatMoney(value)}
              />
              <YAxis
                type="category"
                dataKey="name"
                width={140}
                tick={{ fontSize: 11 }}
              />
              <Tooltip
                formatter={(value: number) => [
                  formatMoney(value),
                  t("ew_revenue_tooltip_amount"),
                ]}
              />
              <Bar dataKey="total">
                {rows.map((row) => (
                  <Cell key={row.state} fill={STATE_COLOR[row.state]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>

          <p className="muted small" style={{ marginTop: 8 }}>
            {t("ew_revenue_total", {
              amount: formatMoney(data.totals.total),
            })}{" "}
            · {t("ew_revenue_incl_vat")}
          </p>
        </>
      )}

      <ExportButtons
        dimension="extra_work_revenue"
        filters={filters}
        disabled={loading || !!error}
      />
    </section>
  );
}
