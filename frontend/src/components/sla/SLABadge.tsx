import { Pause } from "lucide-react";
import {
  formatSLATime,
  SLA_DISPLAY_STATE_LABEL,
  type SLADisplayState,
} from "../../utils/sla";

interface SLABadgeProps {
  state: SLADisplayState;
  remainingSeconds: number | null;
  size?: "sm" | "md";
}

const TOOLTIPS: Partial<Record<SLADisplayState, string>> = {
  HISTORICAL: "This ticket predates the SLA engine.",
  PAUSED: "Waiting on customer; SLA clock paused.",
  COMPLETED: "Ticket reached a terminal status.",
};

export function SLABadge({
  state,
  remainingSeconds,
  size = "sm",
}: SLABadgeProps) {
  const label = SLA_DISPLAY_STATE_LABEL[state];
  const time =
    state === "PAUSED" || state === "COMPLETED" || state === "HISTORICAL"
      ? ""
      : formatSLATime(remainingSeconds);
  const className =
    `sla-badge sla-badge-${state.toLowerCase()}` +
    (size === "md" ? " sla-badge-md" : "");
  const title = TOOLTIPS[state];
  return (
    <span className={className} title={title}>
      {state === "PAUSED" && (
        <Pause size={11} strokeWidth={2.4} aria-hidden="true" />
      )}
      <span className="sla-badge-label">{label}</span>
      {time && <span className="sla-badge-time">{time}</span>}
    </span>
  );
}
