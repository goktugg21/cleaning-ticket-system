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
import { fetchExtraWorkRevenueByBuilding } from "../../../api/reports";
import { BoundedList } from "../../../components/BoundedList";
import { useReport } from "../../../hooks/useReport";
import { formatMoney } from "../../../lib/intl";
import { ExportButtons } from "./ExportButtons";
import { ChartSkeleton } from "./ChartSkeleton";

export interface ChartProps {
  filters: ReportFilters;
  refreshKey: number;
}

/**
 * Sprint 124 — one customer's Extra Work revenue split across that
 * customer's buildings. Structurally mirrors TicketsByBuildingChart
 * (one horizontal bar per building, same tooltip/company-name
 * convention), swapping ticket counts for money via
 * fetchExtraWorkRevenueByBuilding.
 *
 * The one deliberate deviation from TicketsByBuildingChart: the chart
 * is wrapped in BoundedList (size="lg", 420px cap) rather than growing
 * the page unboundedly with `chartData.length * 36`px of height. A
 * customer can have 18+ buildings in dev (B Amsterdam) — each bar still
 * renders at its normal, readable height inside the box; only the PAGE
 * stops growing once there are more buildings than the box can show at
 * once, and the box scrolls (CLAUDE.md #8: every list rendered from a
 * server collection must be bounded).
 */
export function ExtraWorkRevenueByBuildingChart({
  filters,
  refreshKey,
}: ChartProps) {
  const { t } = useTranslation("reports");
  const { data, loading, error, retry } = useReport({
    fetcher: fetchExtraWorkRevenueByBuilding,
    filters,
    refreshKey,
  });

  const chartData = (data?.buckets ?? []).map((b) => ({
    name:
      b.building_name.length > 30
        ? `${b.building_name.slice(0, 29)}…`
        : b.building_name,
    total: Number.parseFloat(b.total),
    building_name: b.building_name,
    company_name: b.company_name,
    count: b.count,
  }));

  return (
    <section
      className="card"
      style={{ padding: "20px 22px", minHeight: 360 }}
      data-testid="chart-card-extra-work-revenue-by-building"
    >
      <h3 className="section-title">{t("ew_revenue_by_building_title")}</h3>
      <p className="muted small" style={{ marginBottom: 8 }}>
        {t("ew_revenue_by_building_subtitle")}
      </p>

      {loading && (
        <ChartSkeleton />
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
      {!loading &&
        !error &&
        data &&
        (chartData.length === 0 ? (
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
            {t("ew_revenue_by_building_empty")}
          </div>
        ) : (
          <BoundedList
            size="lg"
            count={chartData.length}
            ariaLabel={t("ew_revenue_by_building_title")}
            testIdPrefix="ew-revenue-by-building"
          >
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
                <XAxis
                  type="number"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(value: number) => formatMoney(value)}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={160}
                  tick={{ fontSize: 11 }}
                />
                <Tooltip
                  formatter={(value: number) => [
                    formatMoney(value),
                    t("ew_revenue_by_building_tooltip_amount"),
                  ]}
                  labelFormatter={(_label, payload) => {
                    const row = payload?.[0]?.payload as
                      | { building_name: string; company_name: string }
                      | undefined;
                    if (!row) return "";
                    return `${row.building_name} — ${row.company_name}`;
                  }}
                />
                <Bar isAnimationActive={false} dataKey="total" fill="#0B6B42" />
              </BarChart>
            </ResponsiveContainer>
          </BoundedList>
        ))}
      {!loading && !error && data && (
        <p className="muted small" style={{ marginTop: 8 }}>
          {t("ew_revenue_by_building_total", {
            amount: formatMoney(data.totals.total),
          })}{" "}
          · {t("ew_revenue_incl_vat")}
        </p>
      )}

      <ExportButtons
        dimension="extra_work_revenue_by_building"
        filters={filters}
        disabled={loading || !!error}
      />
    </section>
  );
}
