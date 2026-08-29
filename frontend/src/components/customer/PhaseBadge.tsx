/**
 * FE-2 (Addendum D §D.4) — the phase, as the customer reads it.
 *
 * The value comes from the server's `display_phase` — this component
 * only translates and tints it. No client-side phase inference, ever.
 */
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type {
  ExtraWorkDisplayPhase,
  TicketDisplayPhase,
} from "../../api/types";

type Kind = "ew" | "ticket";

/** Which visual tone a phase carries. "action" = the viewer must act. */
function toneOf(phase: string): "action" | "progress" | "done" | "bad" {
  switch (phase) {
    case "WAITING_YOUR_APPROVAL":
    case "WAITING_COMPLETION_APPROVAL":
      return "action";
    case "DONE":
    case "INVOICED":
      return "done";
    case "REJECTED":
    case "CANCELLED":
      return "bad";
    default:
      return "progress";
  }
}

/** P-2 ruling 1 — ONE phase value, two labels: the customer reads
 *  "Goedgekeurd — wordt ingepland" where the provider reads "Nog in te
 *  plannen". A customer surface passes `customer`; the customer key
 *  falls back to the shared one for every other phase. */
function labelKeys(kind: Kind, phase: string, customer: boolean): string[] {
  return customer
    ? [`phase.${kind}_customer.${phase}`, `phase.${kind}.${phase}`]
    : [`phase.${kind}.${phase}`];
}

export function PhaseBadge({
  kind,
  phase,
  testId,
  customer = false,
}: {
  kind: Kind;
  phase: ExtraWorkDisplayPhase | TicketDisplayPhase;
  testId?: string;
  customer?: boolean;
}) {
  const { t } = useTranslation("common");
  return (
    <span
      className={`phase-badge phase-badge-${toneOf(phase)}`}
      data-testid={testId ?? "phase-badge"}
      data-phase={phase}
    >
      {t(labelKeys(kind, phase, customer))}
    </span>
  );
}

/** The banner a detail page opens with: the phase, said once, large.
 *
 *  FE-3 — the same banner opens the PROVIDER detail pages. `sub`
 *  replaces the customer-voiced "what happens next" line with the
 *  provider's own sentence, and `action` is the ONE primary action
 *  (§D.6 rule 3), rendered inside the banner so "what is this / what
 *  happens next / what can I do" are read in one place (§D.0). */
export function PhaseBanner({
  kind,
  phase,
  testId,
  sub,
  action,
  customer = false,
}: {
  kind: Kind;
  phase: ExtraWorkDisplayPhase | TicketDisplayPhase;
  testId?: string;
  sub?: ReactNode;
  action?: ReactNode;
  customer?: boolean;
}) {
  const { t } = useTranslation("common");
  return (
    <div
      className={`phase-banner phase-banner-${toneOf(phase)}`}
      data-testid={testId ?? "phase-banner"}
      data-phase={phase}
      role="status"
    >
      <div className="phase-banner-text">
        <span className="phase-banner-label">{t(labelKeys(kind, phase, customer))}</span>
        <span className="phase-banner-sub">
          {sub ?? t(`phase.${kind}_next.${phase}`)}
        </span>
      </div>
      {action != null && (
        <div className="phase-banner-action" data-testid={`${testId ?? "phase-banner"}-action`}>
          {action}
        </div>
      )}
    </div>
  );
}
