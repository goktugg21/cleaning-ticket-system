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
import type { ExtraWorkStatus, TicketStatus } from "../../api/types";

/** What the one button does. `none` pairs with a null label. */
export type NextStepAction =
  | { kind: "none" }
  | { kind: "transition"; to: ExtraWorkStatus }
  | { kind: "tab"; tab: "overview" | "money" | "hours" | "people" }
  | { kind: "plan" }
  | { kind: "retrySpawn" };

export interface NextStep {
  /** The one sentence, as an i18n key in the `extra_work` namespace. */
  sentenceKey: string;
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

export function resolveNextStep({
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
