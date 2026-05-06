import {
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { useTranslation } from "react-i18next";
import type { ReportFilters } from "../../../api/reports";
import { fetchSLADistribution } from "../../../api/reports";
import type { SLADisplayState } from "../../../api/reports.types";
import { useReport } from "../../../hooks/useReport";

export interface ChartProps {
  filters: ReportFilters;
  refreshKey: number;
}

// Active states (top of the priority list) get the SLA badge palette from
// B2; COMPLETED and HISTORICAL stay muted gray to de-emphasize them in the
// donut without hiding them.
const SLA_STATE_COLOR: Record<SLADisplayState, string> = {
  ON_TRACK: "#0B6B42",   // --green
  AT_RISK: "#9A5A00",    // --amber
  BREACHED: "#C0392B",   // --red
  PAUSED: "#0F6B5E",     // --teal
  COMPLETED: "#556259",  // --closed
  HISTORICAL: "#8A9B91", // --text-faint
};

export function SLADistributionChart({ filters, refreshKey }: ChartProps) {
  const { t } = useTranslation("reports");
  const { data, loading, error, retry } = useReport({
    fetcher: fetchSLADistribution,
    filters,
    refreshKey,
  });

  return (
    <section
      className="card"
      style={{ padding: "20px 22px", minHeight: 360 }}
      data-testid="chart-card-sla-distribution"
    >
      <h3 className="section-title">{t("sla_dist_title")}</h3>
      <p className="muted small" style={{ marginBottom: 8 }}>
        {t("sla_dist_subtitle")}
      </p>

      {loading && <ChartSkeleton />}
      {error && <ChartError message={error} onRetry={retry} retryLabel={t("retry")} />}
      {!loading && !error && data && (
        data.total === 0 ? (
          <ChartEmpty message={t("sla_dist_empty")} />
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
                    key={bucket.state}
                    fill={SLA_STATE_COLOR[bucket.state]}
                  />
                ))}
              </Pie>
              <Tooltip
                formatter={(value: number, name: string) => {
                  const pct =
                    data.total > 0
                      ? `${((value / data.total) * 100).toFixed(1)}%`
                      : "0%";
                  return [`${value} (${pct})`, name];
                }}
              />
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
          {t("sla_dist_total", { count: data.total })}
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

function ChartError({
  message,
  onRetry,
  retryLabel,
}: {
  message: string;
  onRetry: () => void;
  retryLabel: string;
}) {
  return (
    <div className="alert-error" role="alert" style={{ marginTop: 12 }}>
      {message}{" "}
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        onClick={onRetry}
        style={{ marginLeft: 8 }}
      >
        {retryLabel}
      </button>
    </div>
  );
}

function ChartEmpty({ message }: { message: string }) {
  return (
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
      {message}
    </div>
  );
}
