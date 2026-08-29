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
import { ticketStatusLabelKey } from "../../../lib/enumLabels";
import { fetchAgeBuckets } from "../../../api/reports";
import { useReport } from "../../../hooks/useReport";
import { ChartSkeleton } from "./ChartSkeleton";

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

  // Sprint 183 integration — the LAST consumer of the retired
  // `common:status.*` block. Agent B deleted six of those keys and had to
  // leave three alive purely because this one file was another agent's;
  // moving it here lets the whole vocabulary die. Every status name in the
  // app now comes from `ticketStatusLabelKey`, so the chart copy cannot
  // drift from the chips and badges it describes.
  const subtitle = t("age_buckets_subtitle", {
    approved: t(`common:${ticketStatusLabelKey("APPROVED")}`),
    rejected: t(`common:${ticketStatusLabelKey("REJECTED")}`),
    waiting: t(`common:${ticketStatusLabelKey("WAITING_CUSTOMER_APPROVAL")}`),
    reopened: t(`common:${ticketStatusLabelKey("REOPENED_BY_ADMIN")}`),
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
              <Bar isAnimationActive={false} dataKey="count">
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
