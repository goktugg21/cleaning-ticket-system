/**
 * FE-2 (Addendum D §D.4) — the phase, as the customer reads it.
 *
 * The value comes from the server's `display_phase` — this component
 * only translates and tints it. No client-side phase inference, ever.
 */
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

export function PhaseBadge({
  kind,
  phase,
  testId,
}: {
  kind: Kind;
  phase: ExtraWorkDisplayPhase | TicketDisplayPhase;
  testId?: string;
}) {
  const { t } = useTranslation("common");
  return (
    <span
      className={`phase-badge phase-badge-${toneOf(phase)}`}
      data-testid={testId ?? "phase-badge"}
      data-phase={phase}
    >
      {t(`phase.${kind}.${phase}`)}
    </span>
  );
}

/** The banner a detail page opens with: the phase, said once, large. */
export function PhaseBanner({
  kind,
  phase,
  testId,
}: {
  kind: Kind;
  phase: ExtraWorkDisplayPhase | TicketDisplayPhase;
  testId?: string;
}) {
  const { t } = useTranslation("common");
  return (
    <div
      className={`phase-banner phase-banner-${toneOf(phase)}`}
      data-testid={testId ?? "phase-banner"}
      data-phase={phase}
      role="status"
    >
      <span className="phase-banner-label">{t(`phase.${kind}.${phase}`)}</span>
      <span className="phase-banner-sub">{t(`phase.${kind}_next.${phase}`)}</span>
    </div>
  );
}
