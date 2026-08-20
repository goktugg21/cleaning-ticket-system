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
import type { ExtraWorkStatus } from "../../api/types";

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
function customerNextStep(status: ExtraWorkStatus): NextStep {
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
  return { ...WAITING, sentenceKey: "next.customer.waiting_on_provider" };
}

export function resolveNextStep({
  status,
  isProvider,
  hasSpawnedTickets,
  isInvoiced,
}: NextStepInput): NextStep {
  if (!isProvider) return customerNextStep(status);

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
