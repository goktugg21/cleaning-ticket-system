import { Pause } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { SLADisplayState } from "../../utils/sla";
import { useFormatSLATime } from "../../utils/useFormatSLATime";
import { useSLALabel } from "../../utils/useSLALabel";

interface SLABadgeProps {
  state: SLADisplayState;
  remainingSeconds: number | null;
  size?: "sm" | "md";
}

// Sprint 181 §4 — no HISTORICAL entry: that state no longer renders a
// badge, so it can have no tooltip.
const TOOLTIP_KEYS: Partial<Record<SLADisplayState, string>> = {
  PAUSED: "sla_tooltip_paused",
  COMPLETED: "sla_tooltip_completed",
};

export function SLABadge({
  state,
  remainingSeconds,
  size = "sm",
}: SLABadgeProps) {
  const { t } = useTranslation("common");
  const slaLabel = useSLALabel();
  const formatSLATime = useFormatSLATime();

  // Sprint 181 §4 — HISTORICAL renders NOTHING.
  //
  // It means "this ticket predates the SLA engine", which is a fact
  // about our migration, not about the ticket. No operator action
  // depends on it, and a badge reading "Historical" beside a workflow
  // status is one more word to decode in the exact cell §4 exists to
  // simplify. On crmtest all 79 historical tickets are already
  // soft-deleted, so this branch is reachable only by a legacy row.
  //
  // The whole badge goes, not just its label: an empty pill in the SLA
  // column would be a colour that means nothing, which is worse. After
  // every hook has run, so the early return cannot change hook order.
  if (state === "HISTORICAL") return null;

  const label = slaLabel(state);
  const time =
    state === "PAUSED" || state === "COMPLETED"
      ? ""
      : formatSLATime(remainingSeconds);
  const className =
    `sla-badge sla-badge-${state.toLowerCase()}` +
    (size === "md" ? " sla-badge-md" : "");
  const tooltipKey = TOOLTIP_KEYS[state];
  // Tooltip strings live in common.json as optional keys; absence falls
  // through to undefined (no tooltip).
  const title = tooltipKey ? t(tooltipKey, { defaultValue: "" }) : undefined;
  return (
    <span className={className} title={title || undefined}>
      {state === "PAUSED" && (
        <Pause size={11} strokeWidth={2.4} aria-hidden="true" />
      )}
      <span className="sla-badge-label">{label}</span>
      {time && <span className="sla-badge-time">{time}</span>}
    </span>
  );
}
