/**
 * FE-2 / FE-3 (Addendum D §D.4) — the folded timeline, rendered.
 *
 * One meerwerk, one story: the request's events and its spawned
 * ticket's milestones as ONE chronological list, from
 * `GET /api/extra-work/<id>/timeline/`. The customer tracker (FE-2)
 * and the provider detail (FE-3) draw the SAME list with the same
 * words (`common:timeline.*`) — one component, two mounts, so the two
 * readers of one job can never be told two stories.
 *
 * Bounded (CLAUDE.md): the entries are a server collection, so the
 * list scrolls inside itself past the named height.
 */
import { useTranslation } from "react-i18next";

import type { ExtraWorkTimelineEntry } from "../../api/extraWork";
import { formatDateTime } from "../../lib/intl";
import { BoundedList } from "../BoundedList";

export function MeerwerkTimeline({
  entries,
  ariaLabel,
  testIdPrefix,
}: {
  entries: ExtraWorkTimelineEntry[];
  ariaLabel: string;
  testIdPrefix: string;
}) {
  const { t } = useTranslation("common");
  return (
    <BoundedList
      size="md"
      count={entries.length}
      ariaLabel={ariaLabel}
      testIdPrefix={testIdPrefix}
    >
      <ol className="meerwerk-timeline">
        {entries.map((entry, index) => (
          <li
            key={`${entry.event}-${index}`}
            className="meerwerk-timeline-row"
            data-testid={`${testIdPrefix}-row`}
            data-event={entry.event}
          >
            <span className="meerwerk-timeline-when">
              {entry.at ? formatDateTime(entry.at) : "—"}
            </span>
            <span className="meerwerk-timeline-label">
              {t(`timeline.${entry.event}`)}
            </span>
            {entry.actor && <span className="muted small">{entry.actor}</span>}
          </li>
        ))}
      </ol>
    </BoundedList>
  );
}
