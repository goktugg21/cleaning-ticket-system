/**
 * W8 §2 — what to do next, derived from the status.
 *
 * The owner: "I see Plan Work and then... what? I plan the work and it
 * just stays there? There's nothing guiding me toward the next step."
 *
 * The page used to offer whatever the backend listed in
 * `allowed_next_statuses`, in enum order, as a row of same-sized
 * buttons. That answers "what may I do" and never answers "what should
 * I do", and at UNDER_REVIEW it offered Plan work when the actual next
 * move is pricing the job.
 *
 * So the status resolves to exactly ONE move, and the header states it.
 * The full transition row still exists further down for the cases this
 * cannot know about (corrections, cancels, overrides); it simply stops
 * competing with the one move that is right almost every time.
 *
 * WHO IS WAITING IS A REAL ANSWER. A status where the move belongs to
 * somebody else resolves to `waiting: true` and NO button, naming who
 * is being waited on. A greyed-out button would say "you could do this
 * if you tried harder", which is false.
 *
 * The provider and the customer are looking at the same record and do
 * NOT have the same next move — the whole point of PRICING_PROPOSED is
 * that the ball is in the customer's court — so the actor is an input,
 * not an afterthought.
 */
import type {
  ExtraWorkRequestList,
  ExtraWorkStatus,
  TicketStatus,
} from "../../api/types";
import { daysSince, startsWhenPriced } from "../../lib/extraWorkTabs";

/** What the one button does. `none` pairs with a null label. */
export type NextStepAction =
  | { kind: "none" }
  | { kind: "transition"; to: ExtraWorkStatus }
  | { kind: "tab"; tab: "overview" | "money" | "people" }
  | { kind: "plan" }
  | { kind: "retrySpawn" };

export interface NextStep {
  /** The one sentence, as an i18n key in the `extra_work` namespace. */
  sentenceKey: string;
  /** Interpolation values for `sentenceKey` (e.g. the ticket number). */
  sentenceVars?: Record<string, string | number>;
  /** The one button, or null when the move is somebody else's. */
  buttonKey: string | null;
  action: NextStepAction;
  /** True when this record is parked waiting on another party. */
  waiting: boolean;
}

export interface NextStepInput {
  status: ExtraWorkStatus;
  /** Provider side (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER / STAFF). */
  isProvider: boolean;
  /** An operational ticket exists for this request. */
  hasSpawnedTickets: boolean;
  /** A live invoice covers this request. */
  isInvoiced: boolean;
  /**
   * W14 §2 — THE SERVER'S OWN LIST OF LEGAL MOVES, and the reason this
   * resolver stopped being a pure function of `status`.
   *
   * `status` alone is not enough to know what may be done, because the
   * state machine's guard is not only the (from, to) pair. Sprint 181
   * §1 makes `IN_PROGRESS -> COMPLETED` SYSTEM-ONLY the moment the
   * request has an operational ticket -- the ticket answers "is it
   * done?", and nothing else does. `allowed_next_statuses` is where
   * that answer arrives.
   *
   * MEASURED on the dev stack, extra work 6 (IN_PROGRESS, one ticket):
   *   GET  /api/extra-work/6/   -> allowed_next_statuses: ["CANCELLED"]
   *   POST /api/extra-work/6/transition/ {"to_status":"COMPLETED"}
   *        -> HTTP 400 {"code":"operational_status_follows_ticket"}
   * and this resolver, reading `status` alone, offered "Mark complete"
   * as the page's ONE primary button. Pressing it was the owner's bug.
   *
   * So a transition this list does not contain is never offered. A
   * button the server is certain to refuse is not a button.
   */
  allowedNextStatuses: ExtraWorkStatus[];
  /** The operational ticket's number, for the sentence that hands the
   *  move over to it. Null before a ticket exists. */
  ticketNo?: string | null;
  /**
   * W12 §3 — the OPERATIONAL status, once a ticket exists.
   *
   * The header badge four pixels away already shows the ticket's status
   * rather than the request's once there is a ticket, because that is
   * what "where is this?" means after work is scheduled. The sentence
   * has to resolve the same way or the two contradict each other on one
   * line. Null before a ticket exists.
   */
  ticketStatus?: TicketStatus | null;
  /**
   * The day the crew is expected. `provider_planned_date`, which is
   * also what moved the ticket's own schedule, so there is one date
   * here and not a second copy of it.
   */
  plannedDate?: string | null;
}

const WAITING: NextStep = {
  sentenceKey: "",
  buttonKey: null,
  action: { kind: "none" },
  waiting: true,
};

/**
 * The customer acts at exactly one status. Everywhere else the move is
 * the cleaning company's, and saying so is more useful than showing a
 * button that 403s.
 */
function customerNextStep(
  status: ExtraWorkStatus,
  ticketStatus: TicketStatus | null,
  plannedDate: string | null,
): NextStep {
  if (status === "PRICING_PROPOSED") {
    return {
      sentenceKey: "next.customer.pricing_proposed",
      buttonKey: "next.button.open_proposal",
      action: { kind: "tab", tab: "money" },
      waiting: false,
    };
  }
  if (status === "CANCELLED") {
    return { ...WAITING, sentenceKey: "next.cancelled" };
  }
  if (status === "CUSTOMER_REJECTED") {
    return { ...WAITING, sentenceKey: "next.customer.rejected" };
  }
  if (status === "COMPLETED") {
    return { ...WAITING, sentenceKey: "next.customer.completed" };
  }

  // W12 §3 — ONCE THERE IS A TICKET, THE TICKET IS WHAT IS HAPPENING.
  //
  // Every one of these used to collapse into "Waiting for the cleaning
  // company", which is true of all of them and useful about none. A
  // customer whose job is scheduled for 15 September and a customer
  // whose job is being done right now read the same eight words, so the
  // scheduled one rings to ask. Same resolution the status badge uses.
  if (ticketStatus) {
    switch (ticketStatus) {
      case "ACKNOWLEDGED":
        // The date is the whole point of telling them. Without one this
        // is still better than "waiting": somebody has it in hand.
        return {
          ...WAITING,
          sentenceKey: plannedDate
            ? "next.customer.acknowledged_dated"
            : "next.customer.acknowledged",
        };
      case "ON_HOLD":
        return { ...WAITING, sentenceKey: "next.customer.on_hold" };
      case "IN_PROGRESS":
        return { ...WAITING, sentenceKey: "next.customer.in_progress" };
      case "WAITING_MANAGER_REVIEW":
        return { ...WAITING, sentenceKey: "next.customer.being_checked" };
      case "WAITING_CUSTOMER_APPROVAL":
        return { ...WAITING, sentenceKey: "next.customer.your_approval" };
      case "APPROVED":
      case "CLOSED":
        return { ...WAITING, sentenceKey: "next.customer.completed" };
      case "REJECTED":
        return { ...WAITING, sentenceKey: "next.customer.redoing" };
      case "OPEN":
      case "REOPENED_BY_ADMIN":
      case "CONVERTED_TO_EXTRA_WORK":
        break;
    }
  }

  // Approved, no ticket yet: accepted and being scheduled.
  if (status === "CUSTOMER_APPROVED") {
    return { ...WAITING, sentenceKey: "next.customer.approved_scheduling" };
  }
  // REQUESTED / UNDER_REVIEW — we have it and are working out the price.
  return { ...WAITING, sentenceKey: "next.customer.waiting_on_provider" };
}

export function resolveNextStep(input: NextStepInput): NextStep {
  const step = resolveProposedStep(input);
  return withheldIfServerRefuses(step, input);
}

/**
 * W14 §2 — the last word, applied to whatever the resolver proposed.
 *
 * The resolver below reasons from the status, which is how it should
 * read. This function then checks the proposal against the only
 * authority on what is currently legal -- the server's
 * `allowed_next_statuses` -- and withdraws the button when the two
 * disagree.
 *
 * Withdrawing means NO BUTTON, plus a sentence naming who does own the
 * move. It deliberately does not fall back to some other button: if the
 * one move this record is waiting for belongs to a ticket, offering the
 * operator a different move instead is how a page teaches somebody to
 * press whatever is lit.
 *
 * Non-transition actions (open a tab, open the plan dialog, retry a
 * failed spawn) are not status changes and are never withheld here --
 * `allowed_next_statuses` has nothing to say about them.
 */
function withheldIfServerRefuses(
  step: NextStep,
  { status, allowedNextStatuses, hasSpawnedTickets, ticketNo }: NextStepInput,
): NextStep {
  if (step.action.kind !== "transition") return step;
  if (allowedNextStatuses.includes(step.action.to)) return step;

  // The one case with a real answer: the ticket owns "is it done?".
  if (status === "IN_PROGRESS" && hasSpawnedTickets) {
    return {
      ...WAITING,
      sentenceKey: ticketNo
        ? "next.in_progress_ticket_decides"
        : "next.in_progress_ticket_decides_unnumbered",
      sentenceVars: ticketNo ? { ticket: ticketNo } : undefined,
    };
  }
  // Anything else the server currently refuses: say so plainly rather
  // than showing a button that 400s.
  return { ...WAITING, sentenceKey: "next.move_not_available" };
}

function resolveProposedStep({
  status,
  isProvider,
  hasSpawnedTickets,
  isInvoiced,
  ticketStatus,
  plannedDate,
}: NextStepInput): NextStep {
  if (!isProvider) {
    return customerNextStep(
      status,
      ticketStatus ?? null,
      plannedDate ?? null,
    );
  }

  switch (status) {
    case "REQUESTED":
      return {
        sentenceKey: "next.requested",
        buttonKey: "next.button.start_review",
        action: { kind: "transition", to: "UNDER_REVIEW" },
        waiting: false,
      };

    // The owner's example, and the reason this resolver exists: at
    // UNDER_REVIEW the page offered Plan work. Nothing can be planned
    // before it is priced and accepted.
    case "UNDER_REVIEW":
      return {
        sentenceKey: "next.under_review",
        buttonKey: "next.button.prepare_proposal",
        action: { kind: "tab", tab: "money" },
        waiting: false,
      };

    case "PRICING_PROPOSED":
      return { ...WAITING, sentenceKey: "next.pricing_proposed" };

    case "CUSTOMER_APPROVED":
      // Approved with no ticket is broken data, not a stage. Advancing
      // it buries the fault; the repair is the only move that helps.
      if (!hasSpawnedTickets) {
        return {
          sentenceKey: "next.approved_no_ticket",
          buttonKey: "next.button.retry_scheduling",
          action: { kind: "retrySpawn" },
          waiting: false,
        };
      }
      return {
        sentenceKey: "next.customer_approved",
        buttonKey: "next.button.plan_work",
        action: { kind: "plan" },
        waiting: false,
      };

    case "IN_PROGRESS":
      return {
        sentenceKey: "next.in_progress",
        buttonKey: "next.button.mark_complete",
        action: { kind: "transition", to: "COMPLETED" },
        waiting: false,
      };

    case "COMPLETED":
      if (isInvoiced) {
        return { ...WAITING, sentenceKey: "next.completed_invoiced" };
      }
      return {
        sentenceKey: "next.completed",
        buttonKey: "next.button.set_billing_month",
        action: { kind: "tab", tab: "money" },
        waiting: false,
      };

    case "CUSTOMER_REJECTED":
      return {
        sentenceKey: "next.rejected",
        buttonKey: "next.button.review_again",
        action: { kind: "transition", to: "UNDER_REVIEW" },
        waiting: false,
      };

    case "CANCELLED":
      return { ...WAITING, sentenceKey: "next.cancelled" };
  }
}

// ---------------------------------------------------------------------------
// P-9 B — THE LIST'S ONE NEXT STEP PER ROW, from the same source as the
// detail page. The four-tab Extra work list ends every row with one
// button; the label keys are the `next.button.*` keys the header above
// already uses where the move is the same (price it, plan it, review
// again), plus the handful of list-only moves. `to` is the route the
// button opens: the list never transitions anything itself.
// ---------------------------------------------------------------------------
export interface ListNextStep {
  /** The button label, as an i18n key in the `extra_work` namespace. */
  buttonKey: string | null;
  /** The route the button opens. */
  to: string;
  tone?: "primary" | "secondary";
}

export interface ListNextStepContext {
  isProvider: boolean;
  /** YYYY-MM-DD, the reader's calendar day (`todayIso()`). */
  today: string;
}

/** A price the customer has sat on for this many calendar days earns a
 *  nudge. There is no reminder endpoint in this system: the button opens
 *  the request's messages, where the nudge is written. */
export const REMIND_CUSTOMER_AFTER_DAYS = 3;

export function listNextStep(
  row: ExtraWorkRequestList,
  ctx: ListNextStepContext,
): ListNextStep {
  const detail = `/extra-work/${row.id}`;
  const open: ListNextStep = {
    buttonKey: "next.button.open",
    to: detail,
    tone: "secondary",
  };

  if (!ctx.isProvider) {
    // A customer acts at exactly one phase (see `customerNextStep`).
    if (
      row.display_phase === "WAITING_YOUR_APPROVAL" ||
      row.display_phase === "WAITING_CUSTOMER_APPROVAL"
    ) {
      return {
        buttonKey: "next.button.open_proposal",
        to: `${detail}?tab=money`,
        tone: "primary",
      };
    }
    return open;
  }

  switch (row.display_phase) {
    case "WAITING_PRICE":
      return {
        buttonKey: startsWhenPriced(row)
          ? "next.button.price_and_start"
          : "next.button.prepare_proposal",
        to: `${detail}?tab=money`,
        tone: "primary",
      };

    case "WAITING_YOUR_APPROVAL":
    case "WAITING_CUSTOMER_APPROVAL": {
      const waited = daysSince(row.pricing_proposed_at, ctx.today);
      if (waited !== null && waited >= REMIND_CUSTOMER_AFTER_DAYS) {
        return {
          buttonKey: "next.button.remind_customer",
          to: `${detail}?tab=messages`,
          tone: "primary",
        };
      }
      return open;
    }

    case "REJECTED":
      return {
        buttonKey: "next.button.review_again",
        to: detail,
        tone: "primary",
      };

    case "WAITING_PLANNING":
      // The plan dialog lives on the detail page, behind its own
      // primary button; the list sends the reader there.
      return { buttonKey: "next.button.plan_work", to: detail, tone: "primary" };

    case "SCHEDULED":
    case "IN_EXECUTION":
      return open;

    case "WAITING_COMPLETION_APPROVAL": {
      // The finished work is checked on the ticket that did it.
      const ticket = row.spawned_tickets[0];
      return ticket
        ? {
            buttonKey: "next.button.check_work",
            to: `/tickets/${ticket.id}`,
            tone: "primary",
          }
        : open;
    }

    case "DONE":
      return {
        buttonKey: "next.button.go_to_invoices",
        to: "/invoices",
        tone: "primary",
      };

    case "INVOICED":
      return row.invoice_ref?.id
        ? {
            buttonKey: "next.button.open_invoice",
            to: `/invoices/${row.invoice_ref.id}`,
            tone: "secondary",
          }
        : {
            buttonKey: "next.button.go_to_invoices",
            to: "/invoices",
            tone: "secondary",
          };

    case "CANCELLED":
      return open;
  }
}
