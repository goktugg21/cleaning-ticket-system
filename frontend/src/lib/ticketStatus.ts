/**
 * Sprint 182 §1 — the ticket statuses, as ONE exported constant.
 *
 * ## What went wrong
 *
 * `DashboardPage.tsx` carried a hand-written `STATUS_OPTIONS` array of
 * EIGHT statuses while `TicketStatus` has NINE. The ninth,
 * `CONVERTED_TO_EXTRA_WORK`, was missing — so the status chips, the
 * status dropdown and the "Status breakdown" panel all silently omitted
 * it while the "All" tile counted `stats.total`, which includes it. That
 * is the owner's "ALL says 142 but the chips add up to 138": the chips
 * were not wrong about any status, they were missing one.
 *
 * CLAUDE.md already records this exact failure from Sprint 126 — a
 * hardcoded array literal defeats TypeScript's exhaustiveness checking,
 * a `documents` permission group rendered a headerless column, and it
 * stayed invisible for three sprints. An array literal cannot be checked
 * for completeness; a `Record` over the union can.
 *
 * ## So this is a Record, and the order is derived from it
 *
 * `TICKET_STATUS_SPEC` is `Record<TicketStatus, …>`. Add a member to the
 * `TicketStatus` union and the compiler fails HERE, in one place, before
 * anything renders. The ordered arrays below are DERIVED from it, so
 * there is no second list to forget.
 *
 * ## Why one status is not in the ticket list
 *
 * The owner decided it: a ticket converted to an Extra Work is removed
 * from the ticket list entirely. Its work did not finish — it became
 * something else, and it is tracked from there. Keeping it as a ninth
 * chip would have made the arithmetic add up while leaving a queue on
 * screen that nobody works.
 *
 * The rule that matters either way is that the total and the chips agree.
 * `visibleTicketTotal` is the other half of that: it subtracts exactly
 * the statuses this file hides, from the same source the chips count, so
 * the two cannot drift apart. `ticketListStatusParam` is the third half —
 * the query that makes the ROWS agree with both.
 */
import type { TicketStats, TicketStatus } from "../api/types";

interface TicketStatusSpec {
  /** Render order. Values are spaced so a future status can slot in. */
  rank: number;
  /**
   * Does the ticket LIST work in this status — as a chip, as a dropdown
   * option, and as rows?
   */
  inTicketList: boolean;
}

const TICKET_STATUS_SPEC: Record<TicketStatus, TicketStatusSpec> = {
  OPEN: { rank: 10, inTicketList: true },
  IN_PROGRESS: { rank: 20, inTicketList: true },
  // Sprint 7 — the manager-review queue is surfaced so provider
  // management can preset the list to the bulk-confirm view.
  WAITING_MANAGER_REVIEW: { rank: 30, inTicketList: true },
  WAITING_CUSTOMER_APPROVAL: { rank: 40, inTicketList: true },
  APPROVED: { rank: 50, inTicketList: true },
  REJECTED: { rank: 60, inTicketList: true },
  CLOSED: { rank: 70, inTicketList: true },
  REOPENED_BY_ADMIN: { rank: 80, inTicketList: true },
  // Sprint 182 §1 — the one the array forgot, and the one that does not
  // belong on the ticket list. See the module docstring.
  CONVERTED_TO_EXTRA_WORK: { rank: 90, inTicketList: false },
};

function byRank(a: TicketStatus, b: TicketStatus): number {
  return TICKET_STATUS_SPEC[a].rank - TICKET_STATUS_SPEC[b].rank;
}

/** Every ticket status, in render order. */
export const TICKET_STATUS_ORDER: readonly TicketStatus[] = (
  Object.keys(TICKET_STATUS_SPEC) as TicketStatus[]
).sort(byRank);

/** The statuses the ticket list offers and counts. */
export const TICKET_LIST_STATUSES: readonly TicketStatus[] =
  TICKET_STATUS_ORDER.filter((status) => TICKET_STATUS_SPEC[status].inTicketList);

/** The statuses the ticket list drops. Exported so the total can subtract
 *  exactly what the chips omit rather than a number written twice. */
export const TICKET_LIST_HIDDEN_STATUSES: readonly TicketStatus[] =
  TICKET_STATUS_ORDER.filter(
    (status) => !TICKET_STATUS_SPEC[status].inTicketList,
  );

/**
 * The `?status__in=` value that narrows the ROWS to what the chips count.
 *
 * Server-side, so the narrowing survives pagination — filtering the
 * current page in the client would leave `count` (and therefore the
 * pager) describing a different set than the rows above it.
 */
export const ticketListStatusParam = (): string =>
  TICKET_LIST_STATUSES.join(",");

/**
 * The total the "All" tile shows: every ticket in scope MINUS the
 * statuses the list does not work in.
 *
 * Derived from `by_status`, the same map the chips read, so "All" and the
 * chips are two views of one object and cannot disagree. Returns -1 when
 * there are no stats yet, which is what `StatusTiles` renders as an em
 * dash rather than as a wrong number.
 */
export function visibleTicketTotal(stats: TicketStats | null): number {
  if (!stats) return -1;
  const hidden = TICKET_LIST_HIDDEN_STATUSES.reduce(
    (sum, status) => sum + (stats.by_status[status] ?? 0),
    0,
  );
  return stats.total - hidden;
}
