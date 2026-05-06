import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useTranslation } from "react-i18next";
import type { ReportFilters } from "../../../api/reports";
import { fetchManagerThroughput } from "../../../api/reports";
import { useReport } from "../../../hooks/useReport";

export interface ChartProps {
  filters: ReportFilters;
  refreshKey: number;
}

export function ManagerThroughputChart({ filters, refreshKey }: ChartProps) {
  const { t } = useTranslation("reports");
  const { data, loading, error, retry } = useReport({
    fetcher: fetchManagerThroughput,
    filters,
    refreshKey,
  });

  // Recharts horizontal bar wants `layout="vertical"` (axes swap roles).
  // Truncate long names so the y-axis doesn't blow out the card.
  const chartData = (data?.managers ?? []).map((m) => ({
    name: m.full_name.length > 24 ? `${m.full_name.slice(0, 23)}…` : m.full_name,
    resolved_count: m.resolved_count,
    full_name: m.full_name,
    email: m.email,
  }));

  return (
    <section
      className="card"
      style={{ padding: "20px 22px", minHeight: 360 }}
      data-testid="chart-card-manager-throughput"
    >
      <h3 className="section-title">{t("manager_throughput_title")}</h3>
      <p className="muted small" style={{ marginBottom: 8 }}>
        {t("manager_throughput_subtitle")}
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
      {!loading && !error && data && (
        data.managers.length === 0 ? (
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
            {t("manager_throughput_empty")}
          </div>
        ) : (
          <ResponsiveContainer
            width="100%"
            height={Math.max(160, chartData.length * 36)}
          >
            <BarChart
              data={chartData}
              layout="vertical"
              margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
            >
              <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
              <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
              <YAxis
                type="category"
                dataKey="name"
                width={140}
                tick={{ fontSize: 11 }}
              />
              <Tooltip
                formatter={(value: number) => [value, t("manager_throughput_tooltip_label")]}
                labelFormatter={(_label, payload) => {
                  const row = payload?.[0]?.payload as
                    | { full_name: string; email: string }
                    | undefined;
                  if (!row) return "";
                  return `${row.full_name} — ${row.email}`;
                }}
              />
              <Bar dataKey="resolved_count" fill="#10b981" />
            </BarChart>
          </ResponsiveContainer>
        )
      )}
    </section>
  );
}
