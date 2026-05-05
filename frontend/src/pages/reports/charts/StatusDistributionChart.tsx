import {
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import type { ReportFilters } from "../../../api/reports";
import { fetchStatusDistribution } from "../../../api/reports";
import { useReport } from "../../../hooks/useReport";

export interface ChartProps {
  filters: ReportFilters;
  refreshKey: number;
}

const STATUS_COLOR: Record<string, string> = {
  OPEN: "#3b82f6",
  IN_PROGRESS: "#f59e0b",
  WAITING_CUSTOMER_APPROVAL: "#8b5cf6",
  REJECTED: "#ef4444",
  APPROVED: "#10b981",
  CLOSED: "#6b7280",
  REOPENED_BY_ADMIN: "#ec4899",
};

const FALLBACK_COLOR = "#94a3b8";

export function StatusDistributionChart({ filters, refreshKey }: ChartProps) {
  const { data, loading, error, retry } = useReport({
    fetcher: fetchStatusDistribution,
    filters,
    refreshKey,
  });

  return (
    <section className="card" style={{ padding: "20px 22px", minHeight: 360 }}>
      <h3 className="section-title">Status distribution</h3>
      <p className="muted small" style={{ marginBottom: 8 }}>
        Snapshot of all tickets in scope. Not affected by date range.
      </p>

      {loading && <ChartSkeleton />}
      {error && <ChartError message={error} onRetry={retry} />}
      {!loading && !error && data && (
        data.total === 0 ? (
          <ChartEmpty message="No tickets in this scope." />
        ) : (
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie
                data={data.buckets}
                dataKey="count"
                nameKey="label"
                innerRadius={50}
                outerRadius={90}
                paddingAngle={2}
              >
                {data.buckets.map((bucket) => (
                  <Cell
                    key={bucket.status}
                    fill={STATUS_COLOR[bucket.status] ?? FALLBACK_COLOR}
                  />
                ))}
              </Pie>
              <Tooltip />
              <Legend
                verticalAlign="bottom"
                iconType="circle"
                wrapperStyle={{ fontSize: 12 }}
              />
            </PieChart>
          </ResponsiveContainer>
        )
      )}
      {!loading && !error && data && (
        <p className="muted small" style={{ marginTop: 8 }}>
          Total: {data.total}
        </p>
      )}
    </section>
  );
}

function ChartSkeleton() {
  return (
    <div className="loading-bar" style={{ marginTop: 12, height: 240 }}>
      <div className="loading-bar-fill" />
    </div>
  );
}

function ChartError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="alert-error" role="alert" style={{ marginTop: 12 }}>
      {message}{" "}
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        onClick={onRetry}
        style={{ marginLeft: 8 }}
      >
        Retry
      </button>
    </div>
  );
}

function ChartEmpty({ message }: { message: string }) {
  return (
    <div
      className="muted small"
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: 240,
      }}
    >
      {message}
    </div>
  );
}
