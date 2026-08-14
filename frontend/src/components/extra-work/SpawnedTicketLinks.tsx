/**
 * Sprint 181 §1b — the spawned ticket number(s), rendered in ONE place.
 *
 * An Extra Work with two tickets rendered `TCK-2026-000207TCK-2026-000208`
 * — same family as `Draft0` and `hiddenShow all`: a list joined with
 * nothing between the items. Sprint 180 put a `marginRight` on each link
 * and left it at that, which is a gap that depends on the cell it lands
 * in rather than a separator that is part of the text.
 *
 * There were three renderers for this one fact (the list table, the list's
 * mobile card, and the detail page's Details card), each with its own
 * idea of a separator. Now there is one, which is the point of the sprint
 * it belongs to.
 *
 * ## The overflow rule
 *
 * One ticket per Extra Work is the normal case — Sprint 6A made the spawn
 * create exactly one — so more than one is a legacy shape, not a design.
 * A cell must not grow with it (CLAUDE.md: never render a list from a
 * server collection without a bound). So: up to `max` numbers as links,
 * then `+N` for the rest, with every number in the `title` for whoever
 * needs it. The detail page passes a higher `max` because it has the room
 * and it is where somebody goes to see all of them.
 */
import { Link } from "react-router-dom";

import type { ExtraWorkSpawnedTicket } from "../../api/types";

/** The separator, as TEXT rather than as spacing. A middot survives
 *  copy-paste, line wrapping and a cell with no CSS of its own — which
 *  is exactly what went wrong when this was a margin. */
const SEPARATOR = " · ";

export function SpawnedTicketLinks({
  tickets,
  max = 2,
  emptyLabel,
}: {
  tickets: ExtraWorkSpawnedTicket[];
  /** How many to link before collapsing the rest into "+N". */
  max?: number;
  /** Rendered when there are none. Omit for an em dash. */
  emptyLabel?: string;
}) {
  if (tickets.length === 0) {
    return <span className="muted-empty">{emptyLabel ?? "—"}</span>;
  }

  const label = (ticket: ExtraWorkSpawnedTicket) =>
    ticket.ticket_no ?? `#${ticket.id}`;
  const shown = tickets.slice(0, max);
  const hidden = tickets.length - shown.length;

  return (
    <span title={tickets.map(label).join(SEPARATOR)}>
      {shown.map((ticket, index) => (
        <span key={ticket.id}>
          {index > 0 && SEPARATOR}
          <Link
            to={`/tickets/${ticket.id}`}
            // The list rows are clickable; without this a click on the
            // ticket number would navigate to the Extra Work instead of
            // to the ticket the operator actually aimed at.
            onClick={(event) => event.stopPropagation()}
          >
            {label(ticket)}
          </Link>
        </span>
      ))}
      {hidden > 0 && (
        <span className="muted small">{`${SEPARATOR}+${hidden}`}</span>
      )}
    </span>
  );
}
