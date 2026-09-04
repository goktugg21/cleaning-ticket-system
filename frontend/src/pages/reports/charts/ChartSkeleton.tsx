// FE-7 (§D.6.10) — the chart cards' mid-state. A chart-shaped block of
// skeleton lines in the same 240px the chart will take, so the card
// holds its shape while the answer is on its way; never a 3px bar in an
// empty box, never the word "Loading".
export function ChartSkeleton({ height = 240 }: { height?: number }) {
  return (
    <div
      className="skeleton-lines chart-skeleton"
      style={{ height, marginTop: 12, padding: "18px 0 0" }}
      aria-hidden="true"
      data-testid="chart-skeleton"
    >
      <span className="skeleton-line" style={{ width: "38%" }} />
      <span className="skeleton-line" style={{ width: "72%" }} />
      <span className="skeleton-line" style={{ width: "55%" }} />
      <span className="skeleton-line" style={{ width: "84%" }} />
      <span className="skeleton-line" style={{ width: "46%" }} />
    </div>
  );
}
