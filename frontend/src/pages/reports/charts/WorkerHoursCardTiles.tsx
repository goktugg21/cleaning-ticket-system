import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../../api/client";
import { currentIsoWeek } from "../../../lib/isoWeek";

/**
 * Sprint 172 §4 — the four figures on the Worker hour report's card.
 *
 * The card was a title, two lines and an Open button while every
 * neighbour in the grid carried a chart, so it read as a placeholder.
 * These are the SAME four the modal computes — rows, total hours,
 * weeks, workers — over the same default span, so the card and the
 * modal cannot disagree about the period they describe.
 *
 * Deliberately not a chart: the report's grain is a table of twenty
 * columns and there is no single series in it that a bar would tell the
 * truth about. Four figures answer "is there anything in here" without
 * inventing a shape the data does not have.
 */
export function WorkerHoursCardTiles({ refreshKey }: { refreshKey: number }) {
  const { t } = useTranslation("reports");
  const start = currentIsoWeek();
  const firstWeek = Math.max(1, start.isoWeek - 3);
  const [totals, setTotals] = useState<{
    rows: number;
    hours: string;
    weeks: number;
    workers: number;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get("/reports/worker-hours/", {
        params: { year: start.isoYear, week: firstWeek, weeks: 4 },
      })
      .then((response) => {
        if (!cancelled) setTotals(response.data.totals);
      })
      .catch(() => {
        // A failed read leaves the tiles at their dashes rather than
        // putting an error banner on a card whose job is a summary.
        if (!cancelled) setTotals(null);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  const tiles = [
    { key: "rows", value: totals ? String(totals.rows) : "—" },
    { key: "hours", value: totals ? totals.hours : "—" },
    { key: "weeks", value: totals ? String(totals.weeks) : "—" },
    { key: "workers", value: totals ? String(totals.workers) : "—" },
  ];

  return (
    <div
      className="hours-tile-row"
      data-testid="worker-hours-card-tiles"
      style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}
    >
      {tiles.map((tile) => (
        <div key={tile.key} className="hours-tile">
          <span className="hours-tile-label">
            {t(`worker_hours.tile_${tile.key}`)}
          </span>
          <span className="hours-tile-value">{tile.value}</span>
        </div>
      ))}
    </div>
  );
}
