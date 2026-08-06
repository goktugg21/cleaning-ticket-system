import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useTranslation } from "react-i18next";

import type {
  TimesheetSummary,
  TimesheetSummaryBuildingBucket,
  TimesheetSummaryEmployeeBucket,
} from "../../api/timesheets.types";
import { NO_BUILDING_MARKER } from "../../api/timesheets.types";

/**
 * Sprint 152.2 — the Overview tab's four graphs.
 *
 * Presentational only. Unlike `src/pages/reports/charts/*`, which each
 * fetch their own dimension through `useReport`, these take the summary
 * payload the Overview tab has ALREADY loaded — four components fetching
 * the identical `/summary/` response four times would be four times the
 * work for one screen, and would let the graphs disagree with the tables
 * beside them mid-refresh.
 *
 * Everything else follows those components: `ResponsiveContainer`, the
 * same `#e5e7eb` grid, the same flat hex fills from their palette, the
 * same card + title + subtitle + empty-state shape. No new charting
 * library, no new palette, no hand-rolled SVG.
 */

// The reports charts' palette, reused verbatim rather than re-picked.
const SERIES_BLUE = "#3b82f6";
const SERIES_AMBER = "#f59e0b";
const SERIES_GREEN = "#10b981";
const CATEGORICAL = [
  "#3b82f6",
  "#f59e0b",
  "#10b981",
  "#8b5cf6",
  "#ef4444",
  "#ec4899",
  "#14b8a6",
  "#6b7280",
];
const OTHER_COLOR = "#94a3b8";

/**
 * How many bars a categorical chart draws before the tail is collapsed.
 *
 * A tenant with 200 employees must not render 200 bars — the same rule
 * `BoundedList` applies to lists, for the same reason: a surface that
 * "looks fine on seed data and breaks on real data" is the defect, not
 * the data. The TABLES below the charts keep every row, so nothing is
 * hidden: the chart is the summary, the table is the record.
 */
const TOP_N = 10;

interface Slice {
  name: string;
  hours: number;
  isOther?: boolean;
}

/**
 * Take the top N by hours and collapse the rest into one "Other" bar.
 * Returns the slices plus how many rows were folded in, so the caption
 * can say so rather than leaving the reader to assume they are seeing
 * everything.
 */
function boundSlices(rows: Slice[]): { slices: Slice[]; hiddenCount: number } {
  if (rows.length <= TOP_N) return { slices: rows, hiddenCount: 0 };
  const sorted = [...rows].sort((a, b) => b.hours - a.hours);
  const head = sorted.slice(0, TOP_N);
  const tail = sorted.slice(TOP_N);
  const otherHours = tail.reduce((total, row) => total + row.hours, 0);
  return {
    slices: [
      ...head,
      // Rounded at the point of DISPLAY only — the sum itself is done in
      // full precision above.
      { name: "", hours: Math.round(otherHours * 100) / 100, isOther: true },
    ],
    hiddenCount: tail.length,
  };
}

function truncate(label: string): string {
  return label.length > 28 ? `${label.slice(0, 27)}…` : label;
}

function ChartEmpty({ message }: { message: string }) {
  return (
    <div
      className="muted small"
      data-testid="hours-chart-empty"
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: 200,
      }}
    >
      {message}
    </div>
  );
}

function ChartCard({
  title,
  subtitle,
  testId,
  children,
}: {
  title: string;
  subtitle?: string;
  testId: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className="card"
      style={{ padding: "18px 20px", minHeight: 300 }}
      data-testid={testId}
    >
      <h4 className="section-title" style={{ margin: 0 }}>
        {title}
      </h4>
      {subtitle && (
        <p className="muted small" style={{ margin: "4px 0 8px" }}>
          {subtitle}
        </p>
      )}
      {children}
    </section>
  );
}

export interface HoursChartsProps {
  summary: TimesheetSummary;
}

export function HoursCharts({ summary }: HoursChartsProps) {
  const { t } = useTranslation("common");

  const noBuildingLabel = t("hours_admin.no_building");

  const weekData = useMemo(
    () =>
      // Chronological, oldest first — the API returns newest-first for
      // the table, and a trend chart read right-to-left is a trap.
      [...summary.by_week]
        .sort((a, b) =>
          a.iso_year === b.iso_year
            ? a.iso_week - b.iso_week
            : a.iso_year - b.iso_year,
        )
        .map((bucket) => ({
          name: `${bucket.iso_year}-W${String(bucket.iso_week).padStart(2, "0")}`,
          hours: Number(bucket.hours),
        })),
    [summary.by_week],
  );

  const employeeBound = useMemo(
    () =>
      boundSlices(
        summary.by_employee.map((bucket: TimesheetSummaryEmployeeBucket) => ({
          name: bucket.employee_name,
          hours: Number(bucket.hours),
        })),
      ),
    [summary.by_employee],
  );

  const buildingBound = useMemo(
    () =>
      boundSlices(
        summary.by_building.map((bucket: TimesheetSummaryBuildingBucket) => ({
          // The API sends a sentinel, not a label, so the language is
          // chosen here.
          name:
            bucket.building_name === NO_BUILDING_MARKER
              ? noBuildingLabel
              : bucket.building_name,
          hours: Number(bucket.hours),
        })),
      ),
    [summary.by_building, noBuildingLabel],
  );

  const hourTypeData = useMemo(
    () =>
      summary.by_hour_type.map((bucket) => ({
        name: bucket.hour_type_name,
        hours: Number(bucket.hours),
      })),
    [summary.by_hour_type],
  );

  const otherLabel = t("hours_admin.chart_other");
  const hoursLabel = t("hours_admin.chart_hours_label");

  function withOtherName(slices: Slice[]) {
    return slices.map((slice) =>
      slice.isOther ? { ...slice, name: otherLabel } : slice,
    );
  }

  function topNote(hiddenCount: number) {
    return hiddenCount > 0
      ? t("hours_admin.chart_top_note", { top: TOP_N, hidden: hiddenCount })
      : undefined;
  }

  const employeeSlices = withOtherName(employeeBound.slices);
  const buildingSlices = withOtherName(buildingBound.slices);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
        gap: 16,
        marginBottom: 16,
      }}
      data-testid="hours-charts"
    >
      <ChartCard
        title={t("hours_admin.chart_by_week_title")}
        subtitle={t("hours_admin.chart_by_week_subtitle")}
        testId="hours-chart-by-week"
      >
        {weekData.length === 0 ? (
          <ChartEmpty message={t("hours_admin.chart_empty")} />
        ) : (
          <ResponsiveContainer width="100%" height={240}>
            <BarChart
              data={weekData}
              margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
            >
              <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip formatter={(value: number) => [value, hoursLabel]} />
              <Bar dataKey="hours" fill={SERIES_BLUE} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      <ChartCard
        title={t("hours_admin.chart_by_employee_title")}
        subtitle={
          topNote(employeeBound.hiddenCount) ??
          t("hours_admin.chart_by_employee_subtitle")
        }
        testId="hours-chart-by-employee"
      >
        {employeeSlices.length === 0 ? (
          <ChartEmpty message={t("hours_admin.chart_empty")} />
        ) : (
          <ResponsiveContainer
            width="100%"
            height={Math.max(160, employeeSlices.length * 30)}
          >
            <BarChart
              data={employeeSlices}
              layout="vertical"
              margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
            >
              <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
              <XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis
                type="category"
                dataKey="name"
                width={150}
                tick={{ fontSize: 11 }}
                tickFormatter={truncate}
              />
              <Tooltip formatter={(value: number) => [value, hoursLabel]} />
              <Bar dataKey="hours">
                {employeeSlices.map((slice, index) => (
                  <Cell
                    key={slice.name || `slice-${index}`}
                    fill={slice.isOther ? OTHER_COLOR : SERIES_GREEN}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      <ChartCard
        title={t("hours_admin.chart_by_building_title")}
        subtitle={
          topNote(buildingBound.hiddenCount) ??
          t("hours_admin.chart_by_building_subtitle")
        }
        testId="hours-chart-by-building"
      >
        {buildingSlices.length === 0 ? (
          <ChartEmpty message={t("hours_admin.chart_empty")} />
        ) : (
          <ResponsiveContainer
            width="100%"
            height={Math.max(160, buildingSlices.length * 30)}
          >
            <BarChart
              data={buildingSlices}
              layout="vertical"
              margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
            >
              <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
              <XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis
                type="category"
                dataKey="name"
                width={150}
                tick={{ fontSize: 11 }}
                tickFormatter={truncate}
              />
              <Tooltip formatter={(value: number) => [value, hoursLabel]} />
              <Bar dataKey="hours">
                {buildingSlices.map((slice, index) => (
                  <Cell
                    key={slice.name || `slice-${index}`}
                    fill={slice.isOther ? OTHER_COLOR : SERIES_AMBER}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </ChartCard>

      <ChartCard
        title={t("hours_admin.chart_by_hour_type_title")}
        subtitle={t("hours_admin.chart_by_hour_type_subtitle")}
        testId="hours-chart-by-hour-type"
      >
        {hourTypeData.length === 0 ? (
          <ChartEmpty message={t("hours_admin.chart_empty")} />
        ) : (
          /* A donut, matching `StatusDistributionChart`'s idiom for a
             small categorical split. Hour types are a handful of rows by
             domain reality (the standard set is six), so this one needs
             no top-N bound — unlike employees and buildings, which grow
             with the tenant. */
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie
                data={hourTypeData}
                dataKey="hours"
                nameKey="name"
                innerRadius={50}
                outerRadius={85}
                paddingAngle={2}
              >
                {hourTypeData.map((slice, index) => (
                  <Cell
                    key={slice.name}
                    fill={CATEGORICAL[index % CATEGORICAL.length]}
                  />
                ))}
              </Pie>
              <Tooltip formatter={(value: number) => [value, hoursLabel]} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
            </PieChart>
          </ResponsiveContainer>
        )}
      </ChartCard>
    </div>
  );
}
