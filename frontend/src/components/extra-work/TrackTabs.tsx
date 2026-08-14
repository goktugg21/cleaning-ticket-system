/**
 * Sprint 180 §1 — the two lives of an Extra Work, as two tracks.
 *
 * An Extra Work has a commercial life (quote, price, approval) and an
 * operational one (scheduled, started, done), and the list showed both
 * on one line, so nobody could tell them apart. The dividing question
 * is exactly one thing — has an operational ticket been born from this
 * extra work? — and this control is where the operator answers it.
 *
 * Deliberately NOT `StatusTiles`. That component is shared with the
 * tickets list and models a filter over ONE dimension with an "All"
 * escape; these are two mutually exclusive VIEWS of the same set, each
 * with its own columns (Quote & price shows no invoice state at all,
 * because a row with no ticket cannot be invoiceable yet, and showing
 * invoice state there is precisely what confused people). Bending the
 * shared component to carry that would change the tickets list too.
 *
 * The CSS is `.status-tile*`, reused verbatim rather than copied: the
 * two controls sit on the same page and a second near-identical
 * vocabulary for "a selectable box with a count" is how two screens
 * start looking different for no reason.
 */

export type ExtraWorkTrack = "QUOTE" | "STARTED";

export interface TrackTab {
  value: ExtraWorkTrack;
  label: string;
  count: number;
  /** Rows on this track that need attention — rendered as a marker
   *  beside the count. 0 renders nothing. */
  anomalyCount?: number;
  anomalyTitle?: string;
}

export function TrackTabs({
  tabs,
  active,
  onChange,
  testIdPrefix,
}: {
  tabs: TrackTab[];
  active: ExtraWorkTrack;
  onChange: (value: ExtraWorkTrack) => void;
  testIdPrefix: string;
}) {
  return (
    <div
      className="status-tile-row"
      role="tablist"
      data-testid={`${testIdPrefix}-tabs`}
    >
      {tabs.map((tab) => {
        const isActive = tab.value === active;
        return (
          <button
            key={tab.value}
            type="button"
            role="tab"
            // A track is a VIEW, not a filter, so there is no × and no
            // clearing: one of the two is always selected. `aria-selected`
            // rather than `aria-pressed` says exactly that to a screen
            // reader.
            aria-selected={isActive}
            className={
              isActive ? "status-tile status-tile-active" : "status-tile"
            }
            onClick={() => onChange(tab.value)}
            data-testid={`${testIdPrefix}-tab-${tab.value}`}
          >
            <span className="status-tile-label">
              {tab.label}
              {tab.anomalyCount ? (
                <span
                  className="cell-tag cell-tag-rejected"
                  style={{ marginLeft: 6 }}
                  title={tab.anomalyTitle}
                  data-testid={`${testIdPrefix}-tab-${tab.value}-anomaly`}
                >
                  {tab.anomalyCount}
                </span>
              ) : null}
            </span>
            <span className="status-tile-count">{tab.count}</span>
          </button>
        );
      })}
    </div>
  );
}
