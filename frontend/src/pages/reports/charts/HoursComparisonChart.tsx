import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useTranslation } from "react-i18next";

import { api, getApiError } from "../../../api/client";
import { ChartSkeleton } from "./ChartSkeleton";

interface ComparisonRow {
  building: number | null;
  building_name: string;
  contracted_hours: string;
  worked_hours: string;
  difference: string;
}

/**
 * Sprint 171 §1 — the contracted-vs-worked comparison as a CHART CARD,
 * inside the chart grid, next to its neighbours.
 *
 * It was a full-width banner sitting above the charts, which made it
 * read as one odd thing rather than one of the reports. Same card
 * shell, same header treatment, same grid stroke, same
 * `ResponsiveContainer`, same empty state as `TicketsByBuildingChart` —
 * so the row reads as one set of tiles.
 *
 * ## Bounded, like its neighbours
 *
 * Top N buildings by contracted hours plus ONE aggregated "Other" bar,
 * with the caption saying how many were folded in. That is the Sprint
 * 152.2 rule and the reason it exists: a chart that looks fine on four
 * buildings is unreadable on forty. The MODAL's table keeps every row —
 * the bound is a rendering decision, never a data one.
 *
 * A grouped bar (contracted beside worked) is the obvious reading of a
 * comparison; the difference is the gap between the pair and does not
 * need a third bar to be seen.
 */
const TOP_N = 8;

export function HoursComparisonChart({
  refreshKey,
  onOpen,
}: {
  refreshKey: number;
  /** Clicking the card opens the modal with the full table. */
  onOpen: () => void;
}) {
  const { t } = useTranslation(["reports", "common"]);
  const now = new Date();
  const [rows, setRows] = useState<ComparisonRow[]>([]);
  const [error, setError] = useState("");

  const requestKey = `${refreshKey}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    api
      .get("/reports/hours-comparison/", {
        params: { year: now.getFullYear(), month: now.getMonth() + 1 },
      })
      .then((response) => {
        if (cancelled) return;
        setRows(response.data.rows ?? []);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoadedKey(requestKey);
      });
    return () => {
      cancelled = true;
    };
    // `now` is derived per render on purpose — the card always shows the
    // CURRENT month and the modal is where a month is chosen.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

  const { chartData, folded } = useMemo(() => {
    const sorted = [...rows].sort(
      (a, b) => Number(b.contracted_hours) - Number(a.contracted_hours),
    );
    const head = sorted.slice(0, TOP_N).map((row) => ({
      name:
        row.building_name.length > 24
          ? `${row.building_name.slice(0, 23)}…`
          : row.building_name || t("hours_comparison.no_building"),
      full: row.building_name,
      contracted: Number(row.contracted_hours) || 0,
      worked: Number(row.worked_hours) || 0,
    }));
    const tail = sorted.slice(TOP_N);
    if (tail.length > 0) {
      head.push({
        name: t("hours_comparison.other_bar"),
        full: t("hours_comparison.other_bar"),
        contracted: tail.reduce(
          (sum, row) => sum + (Number(row.contracted_hours) || 0),
          0,
        ),
        worked: tail.reduce(
          (sum, row) => sum + (Number(row.worked_hours) || 0),
          0,
        ),
      });
    }
    return { chartData: head, folded: tail.length };
  }, [rows, t]);

  return (
    <section
      className="card"
      style={{ padding: "20px 22px", minHeight: 360 }}
      data-testid="chart-card-hours-comparison"
    >
      <h3 className="section-title">{t("hours_comparison.title")}</h3>
      <p className="muted small" style={{ marginBottom: 8 }}>
        {t("hours_comparison.subtitle")}
      </p>

      {loading && (
        <ChartSkeleton />
      )}
      {error && (
        <div className="alert-error" role="alert" style={{ marginTop: 12 }}>
          {error}
        </div>
      )}
      {!loading &&
        !error &&
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
            {t("hours_comparison.empty")}
          </div>
        ) : (
          <ResponsiveContainer
            width="100%"
            height={Math.max(160, chartData.length * 44)}
          >
            <BarChart
              data={chartData}
              layout="vertical"
              margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
            >
              <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" />
              <XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis
                type="category"
                dataKey="name"
                width={140}
                tick={{ fontSize: 11 }}
              />
              <Tooltip
                labelFormatter={(_label, payload) =>
                  (payload?.[0]?.payload as { full?: string } | undefined)
                    ?.full ?? ""
                }
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar isAnimationActive={false}
                dataKey="contracted"
                name={t("hours_comparison.col_contracted")}
                fill="#2563eb"
              />
              <Bar isAnimationActive={false}
                dataKey="worked"
                name={t("hours_comparison.col_worked")}
                fill="#f59e0b"
              />
            </BarChart>
          </ResponsiveContainer>
        ))}

      {!loading && !error && folded > 0 && (
        <p
          className="muted small"
          style={{ marginTop: 8 }}
          data-testid="hours-comparison-chart-folded"
        >
          {t("hours_comparison.folded", { count: folded })}
        </p>
      )}

      <div style={{ marginTop: 10 }}>
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={onOpen}
          data-testid="open-hours-comparison"
        >
          {t("hours_comparison.open")}
        </button>
      </div>
    </section>
  );
}
