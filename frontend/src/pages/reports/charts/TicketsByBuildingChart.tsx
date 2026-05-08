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
import { fetchTicketsByBuilding } from "../../../api/reports";
import { useReport } from "../../../hooks/useReport";
import { ExportButtons } from "./ExportButtons";

export interface ChartProps {
  filters: ReportFilters;
  refreshKey: number;
}

export function TicketsByBuildingChart({ filters, refreshKey }: ChartProps) {
  const { t } = useTranslation("reports");
  const { data, loading, error, retry } = useReport({
    fetcher: fetchTicketsByBuilding,
    filters,
    refreshKey,
  });

  const chartData = (data?.buckets ?? []).map((b) => ({
    name:
      b.building_name.length > 30
        ? `${b.building_name.slice(0, 29)}…`
        : b.building_name,
    count: b.count,
    building_name: b.building_name,
    company_name: b.company_name,
  }));

  return (
    <section
      className="card"
      style={{ padding: "20px 22px", minHeight: 360 }}
      data-testid="chart-card-tickets-by-building"
    >
      <h3 className="section-title">{t("tickets_by_building_title")}</h3>
      <p className="muted small" style={{ marginBottom: 8 }}>
        {t("tickets_by_building_subtitle")}
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
        chartData.length === 0 ? (
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
            {t("tickets_by_building_empty")}
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
                width={160}
                tick={{ fontSize: 11 }}
              />
              <Tooltip
                formatter={(value: number) => [
                  value,
                  t("tickets_by_building_tooltip_label"),
                ]}
                labelFormatter={(_label, payload) => {
                  const row = payload?.[0]?.payload as
                    | { building_name: string; company_name: string }
                    | undefined;
                  if (!row) return "";
                  return `${row.building_name} — ${row.company_name}`;
                }}
              />
              <Bar dataKey="count" fill="#f59e0b" />
            </BarChart>
          </ResponsiveContainer>
        )
      )}
      {!loading && !error && data && (
        <p className="muted small" style={{ marginTop: 8 }}>
          {t("tickets_by_building_total", { count: data.total })}
        </p>
      )}
      <ExportButtons
        dimension="building"
        filters={filters}
        disabled={loading || !!error}
      />
    </section>
  );
}
