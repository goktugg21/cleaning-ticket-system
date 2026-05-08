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
import { fetchTicketsByCustomer } from "../../../api/reports";
import { useReport } from "../../../hooks/useReport";
import { ExportButtons } from "./ExportButtons";

export interface ChartProps {
  filters: ReportFilters;
  refreshKey: number;
}

export function TicketsByCustomerChart({ filters, refreshKey }: ChartProps) {
  const { t } = useTranslation("reports");
  const { data, loading, error, retry } = useReport({
    fetcher: fetchTicketsByCustomer,
    filters,
    refreshKey,
  });

  // Customer is a customer-LOCATION (Sprint 3.6 / 3.5 decision), so two
  // rows that share `customer_name` at different buildings need to be
  // visibly distinct in the chart. Compose the y-axis label as
  // "<customer> · <building>" so the bar chart cannot silently merge
  // them.
  const chartData = (data?.buckets ?? []).map((b) => ({
    name:
      `${b.customer_name} · ${b.building_name}`.length > 30
        ? `${`${b.customer_name} · ${b.building_name}`.slice(0, 29)}…`
        : `${b.customer_name} · ${b.building_name}`,
    count: b.count,
    customer_id: b.customer_id,
    customer_name: b.customer_name,
    building_name: b.building_name,
    company_name: b.company_name,
  }));

  return (
    <section
      className="card"
      style={{ padding: "20px 22px", minHeight: 360 }}
      data-testid="chart-card-tickets-by-customer"
    >
      <h3 className="section-title">{t("tickets_by_customer_title")}</h3>
      <p className="muted small" style={{ marginBottom: 8 }}>
        {t("tickets_by_customer_subtitle")}
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
            {t("tickets_by_customer_empty")}
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
                width={180}
                tick={{ fontSize: 11 }}
              />
              <Tooltip
                formatter={(value: number) => [
                  value,
                  t("tickets_by_customer_tooltip_label"),
                ]}
                labelFormatter={(_label, payload) => {
                  const row = payload?.[0]?.payload as
                    | {
                        customer_name: string;
                        building_name: string;
                        company_name: string;
                      }
                    | undefined;
                  if (!row) return "";
                  return `${row.customer_name} (${row.building_name}, ${row.company_name})`;
                }}
              />
              <Bar dataKey="count" fill="#8b5cf6" />
            </BarChart>
          </ResponsiveContainer>
        )
      )}
      {!loading && !error && data && (
        <p className="muted small" style={{ marginTop: 8 }}>
          {t("tickets_by_customer_total", { count: data.total })}
        </p>
      )}
      <ExportButtons
        dimension="customer"
        filters={filters}
        disabled={loading || !!error}
      />
    </section>
  );
}
