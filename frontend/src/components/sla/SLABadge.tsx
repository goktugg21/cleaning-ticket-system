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

const TOOLTIP_KEYS: Partial<Record<SLADisplayState, string>> = {
  HISTORICAL: "sla_tooltip_historical",
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

  const label = slaLabel(state);
  const time =
    state === "PAUSED" || state === "COMPLETED" || state === "HISTORICAL"
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
