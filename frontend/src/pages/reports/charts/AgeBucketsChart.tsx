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
import { fetchAgeBuckets } from "../../../api/reports";
import { useReport } from "../../../hooks/useReport";

export interface ChartProps {
  filters: ReportFilters;
  refreshKey: number;
}

// Cool to warm; one color per age bucket in canonical order.
const BUCKET_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444"];

export function AgeBucketsChart({ filters, refreshKey }: ChartProps) {
  const { t } = useTranslation(["reports", "common"]);
  const { data, loading, error, retry } = useReport({
    fetcher: fetchAgeBuckets,
    filters,
    refreshKey,
  });

  // Subtitle stitches the four status names from the shared common.status.*
  // namespace so the chart copy matches the labels rendered everywhere else
  // (status filter, ticket detail header, etc.). Avoids leaking raw enum
  // values like APPROVED / WAITING_CUSTOMER_APPROVAL into user copy.
  const subtitle = t("age_buckets_subtitle", {
    approved: t("common:status.approved"),
    rejected: t("common:status.rejected"),
    waiting: t("common:status.waiting_customer_approval"),
    reopened: t("common:status.reopened_by_admin"),
  });

  return (
    <section
      className="card"
      style={{ padding: "20px 22px", minHeight: 360 }}
      data-testid="chart-card-age-buckets"
    >
      <h3 className="section-title">{t("age_buckets_title")}</h3>
      <p className="muted small" style={{ marginBottom: 8 }}>
        {subtitle}
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
        data.total_open === 0 ? (
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
            {t("age_buckets_empty")}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart
              data={data.buckets}
              margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
            >
              <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
              <Tooltip
                formatter={(value: number) => [value, t("age_buckets_tooltip_label")]}
              />
              <Bar dataKey="count">
                {data.buckets.map((bucket, idx) => (
                  <Cell
                    key={bucket.key}
                    fill={BUCKET_COLORS[idx] ?? BUCKET_COLORS[BUCKET_COLORS.length - 1]}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )
      )}
      {!loading && !error && data && (
        <p className="muted small" style={{ marginTop: 8 }}>
          {t("age_buckets_total", { count: data.total_open })}
        </p>
      )}
    </section>
  );
}
