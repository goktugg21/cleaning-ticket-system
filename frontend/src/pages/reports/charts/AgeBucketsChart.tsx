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
  const { data, loading, error, retry } = useReport({
    fetcher: fetchAgeBuckets,
    filters,
    refreshKey,
  });

  return (
    <section className="card" style={{ padding: "20px 22px", minHeight: 360 }}>
      <h3 className="section-title">Open tickets by age</h3>
      <p className="muted small" style={{ marginBottom: 8 }}>
        Open = not yet APPROVED or REJECTED. Includes
        WAITING_CUSTOMER_APPROVAL and REOPENED_BY_ADMIN.
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
            Retry
          </button>
        </div>
      )}
      {!loading && !error && data && (
        data.total_open === 0 ? (
          <div
            className="muted small"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: 240,
            }}
          >
            No open tickets in this scope.
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
                formatter={(value: number) => [value, "Open tickets"]}
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
          Total open: {data.total_open}
        </p>
      )}
    </section>
  );
}
