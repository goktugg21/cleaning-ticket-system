/**
 * W10 — a destination explains why THESE rows and not others.
 *
 * Tickets, Chargeable work and Extra Work are three doors onto one set
 * of records. Each door pre-sets a filter, and until now none of them
 * said which. The Tickets page's own subtitle read "Everything you are
 * allowed to see" while the page was in fact showing open, ordinary
 * tickets with chargeable work excluded — so the one sentence on screen
 * was not merely vague, it was false.
 *
 * This derives the sentence FROM the state the query is actually built
 * from, so it cannot describe a different list than the one below it.
 * Same rule the dashboard's queue rows already follow; generalised to
 * the doors nobody arrives through by clicking a queue.
 *
 * ## What it deliberately does NOT mention
 *
 * The narrowings the reader chose with a labelled control that already
 * says what it does — search, priority, category, "only mine". Those
 * were removed from this line in W8 for the right reason: a control
 * that needs a sentence explaining it is a broken control. What is
 * restored here is only the scope the ROUTE imposed, which has no
 * control at all and therefore nothing else to say it.
 */
import type { TicketStatus } from "../api/types";

export type WorkScope = "tickets" | "chargeable" | "all";

export interface ListScopeInput {
  /** The work axis actually sent as `is_extra_work`. */
  work: WorkScope;
  /** The status actually sent, or "" for every status. */
  status: TicketStatus | "";
  /** `hide_finished_extra_work` is on. Only meaningful where chargeable
   *  rows can appear at all. */
  hidesFinished: boolean;
}

export interface ListScope {
  /** i18n key in the `dashboard` namespace. */
  key: string;
  /** Appended only when it is true of the rows below. */
  hiddenKey: string | null;
}

/**
 * One short sentence, plus at most one clause about what is held back.
 *
 * The status is NOT spelled into the sentence: the status tiles are
 * directly above it, the chosen one is visibly selected, and a sentence
 * repeating it would be the screen saying one thing twice.
 */
export function listScope({
  work,
  status,
  hidesFinished,
}: ListScopeInput): ListScope {
  const anyStatus = status === "";

  // Chargeable rows are only reachable on two of the three scopes, so
  // the "finished are hidden" clause is only true on those.
  const chargeableVisible = work === "chargeable" || work === "all";

  return {
    key:
      work === "chargeable"
        ? anyStatus
          ? "scope.chargeable"
          : "scope.chargeable_status"
        : work === "all"
          ? anyStatus
            ? "scope.all"
            : "scope.all_status"
          : anyStatus
            ? "scope.tickets"
            : "scope.tickets_status",
    hiddenKey:
      chargeableVisible && hidesFinished ? "scope.hidden_finished" : null,
  };
}
