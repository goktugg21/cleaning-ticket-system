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
  /**
   * W14 §2 — CAN A TICKET IN THIS STATUS BE IN THE ARCHIVE?
   *
   * Mirrors `backend/tickets/models.py::TERMINAL_TICKET_STATUSES`, which
   * is what `TicketViewSet.archive` checks before it will file anything
   * away:
   *
   *     if ticket.status not in TERMINAL_TICKET_STATUSES:
   *         ... code="archive_not_finished"
   *
   * So the archive cannot contain an OPEN ticket, or an IN_PROGRESS
   * one, or one ON_HOLD — the server refuses. The chip row above the
   * list did not know that and drew all ten anyway; the owner opened
   * the archive and asked "why am I seeing normal ticket status chips
   * while the archive chip is selected?"
   *
   * A `Record` field rather than a second array, for the reason the
   * module docstring gives: add a status to the union and the compiler
   * asks here whether it is archivable, instead of a hand-kept list
   * silently omitting it.
   */
  archivable: boolean;
}

const TICKET_STATUS_SPEC: Record<TicketStatus, TicketStatusSpec> = {
  OPEN: { rank: 10, inTicketList: true, archivable: false },
  // W10 §1 — slots between OPEN and IN_PROGRESS. The ranks were spaced
  // in tens for exactly this, so nothing else had to move.
  ACKNOWLEDGED: { rank: 15, inTicketList: true, archivable: false },
  IN_PROGRESS: { rank: 20, inTicketList: true, archivable: false },
  // W10 §2 — ON THE LIST, deliberately. A held job must stay somewhere
  // somebody looks; `inTicketList: false` would make this status the
  // hiding place the brief warned about, and the chip is what stops it.
  ON_HOLD: { rank: 25, inTicketList: true, archivable: false },
  // Sprint 7 — the manager-review queue is surfaced so provider
  // management can preset the list to the bulk-confirm view.
  WAITING_MANAGER_REVIEW: { rank: 30, inTicketList: true, archivable: false },
  WAITING_CUSTOMER_APPROVAL: { rank: 40, inTicketList: true, archivable: false },
  APPROVED: { rank: 50, inTicketList: true, archivable: true },
  REJECTED: { rank: 60, inTicketList: true, archivable: true },
  CLOSED: { rank: 70, inTicketList: true, archivable: true },
  REOPENED_BY_ADMIN: { rank: 80, inTicketList: true, archivable: false },
  // Sprint 182 §1 — the one the array forgot, and the one that does not
  // belong on the ticket list. See the module docstring.
  CONVERTED_TO_EXTRA_WORK: { rank: 90, inTicketList: false, archivable: true },
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

/**
 * W14 §2 — the statuses the ARCHIVE can hold, in render order.
 *
 * The archive is not the working list with a flag on it; it is a
 * different pile with a different vocabulary, and the server decides
 * which statuses can reach it. Ten chips over a pile that can only hold
 * four is not "the archive filtered" — it is the working list's chips
 * drawn over somebody else's rows.
 *
 * `CONVERTED_TO_EXTRA_WORK` IS here even though `inTicketList` is false:
 * `TicketViewSet.archive` accepts it (it is in
 * `TERMINAL_TICKET_STATUSES`), so such a ticket can genuinely be in the
 * archive, and a chip row that omitted it would hide rows the archive
 * holds. The working list drops it because its work became something
 * else and nobody works that queue; the archive is exactly where a
 * finished-by-becoming-something-else ticket belongs.
 */
export const TICKET_ARCHIVE_STATUSES: readonly TicketStatus[] =
  TICKET_STATUS_ORDER.filter((status) => TICKET_STATUS_SPEC[status].archivable);

/** The `?status__in=` value that narrows the ARCHIVE's rows to what its
 *  chips count — the archive's own axis, for the same reason
 *  `ticketListStatusParam` exists for the working list. */
export const ticketArchiveStatusParam = (): string =>
  TICKET_ARCHIVE_STATUSES.join(",");

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
/**
 * W14 §2 — the ARCHIVE's "All" tile.
 *
 * `stats` is already fetched with `archived=true`, so `total` IS the
 * archive's total. It is NOT `visibleTicketTotal`: that subtracts the
 * statuses the working list hides, and the one it hides —
 * `CONVERTED_TO_EXTRA_WORK` — is a status the archive shows. Reusing it
 * here would make "All" smaller than the chips beside it add up to,
 * which is the arithmetic failure the whole module exists to prevent.
 */
export function archivedTicketTotal(stats: TicketStats | null): number {
  if (!stats) return -1;
  return stats.total;
}

export function visibleTicketTotal(stats: TicketStats | null): number {
  if (!stats) return -1;
  const hidden = TICKET_LIST_HIDDEN_STATUSES.reduce(
    (sum, status) => sum + (stats.by_status[status] ?? 0),
    0,
  );
  return stats.total - hidden;
}
