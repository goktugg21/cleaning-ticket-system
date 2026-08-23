/**
 * W5-B — the row that stands for a whole day-by-day series.
 *
 * WHAT IT SAYS, AND WHY EACH NUMBER IS THE ONE IT IS
 * --------------------------------------------------
 * A series of twelve weekly visits is one job an operator agreed once.
 * Twelve identical-looking rows is not a useful way to show that, so
 * the members fold under one row carrying the standard title, the
 * member count and the spread across statuses.
 *
 * **Every count here describes the WHOLE series**, including members on
 * another page of results, because the server computes them from the
 * series rather than from the page. That is deliberate and it is the
 * thing the reference system gets wrong: over there the member with
 * `group_sequence == 1` is treated as a header row and the list's
 * status filter branches on it, so "a group header is returned if ANY
 * sibling matches" — which is why their list counts and their own
 * statistics endpoint disagree, and why a filter for two statuses
 * returns a row that is in neither.
 *
 * The count of members ON THIS PAGE is shown separately, and only when
 * it differs from the total. Hiding the difference would be the same
 * lie in a smaller font: an operator who expands a series expecting
 * twelve rows and sees four needs to know why before they conclude
 * eight were deleted.
 *
 * COLLAPSED IS NOT HIDDEN. Expanding is one click and the members
 * render as ordinary rows through the list's own `renderRow`, so a
 * member is never a second-class row with fewer columns.
 */
import { useTranslation } from "react-i18next";

import type { ExtraWorkGroupSummary } from "../../api/types";
import { StatusBadge } from "../StatusBadge";

export function SeriesHeaderRow({
  group,
  onThisPage,
  columns,
  open,
  onToggle,
}: {
  group: ExtraWorkGroupSummary;
  /** How many members the CURRENT page happens to contain. */
  onThisPage: number;
  /** Column span. Callers pass a deliberately over-large number: the
   *  Extra Work table has four conditional columns, so a counted span
   *  would be a second list to keep in step. HTML clamps an over-large
   *  colSpan to the real row width. */
  columns: number;
  open: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const partial = onThisPage < group.member_count;

  return (
    <tr
      className="ew-series-header"
      data-testid="extra-work-series-header"
      data-group-id={group.id}
    >
      <td colSpan={columns}>
        <div className="ew-series-header-inner">
          <button
            type="button"
            className="btn btn-ghost btn-sm ew-series-toggle"
            aria-expanded={open}
            onClick={onToggle}
            data-testid="extra-work-series-toggle"
          >
            <span aria-hidden="true">{open ? "▾" : "▸"}</span>{" "}
            {group.standard_title}
          </button>

          <span
            className="badge ew-series-count"
            data-testid="extra-work-series-count"
          >
            {t("series.member_count", { count: group.member_count })}
          </span>

          {/* Only when the page does not hold the whole series. See the
              header comment: the gap is the thing worth saying. */}
          {partial && (
            <span
              className="muted small"
              data-testid="extra-work-series-partial"
            >
              {t("series.on_this_page", {
                shown: onThisPage,
                total: group.member_count,
              })}
            </span>
          )}

          <span className="ew-series-statuses">
            {group.status_counts.map((entry) => (
              <span key={entry.status} className="ew-series-status">
                <StatusBadge
                  status={{ kind: "extra-work", value: entry.status }}
                  testId={`ew-series-status-${group.id}-${entry.status}`}
                />
                <span className="ew-series-status-count">{entry.count}</span>
              </span>
            ))}
          </span>
        </div>
      </td>
    </tr>
  );
}
