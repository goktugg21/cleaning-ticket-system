import { Pause } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { SLADisplayState } from "../../utils/sla";
import { useDeadlineText } from "../../utils/useSLALabel";

interface SLABadgeProps {
  state: SLADisplayState;
  remainingSeconds: number | null;
  size?: "sm" | "md";
  /**
   * W7 DESIGN 3 — `plain` renders the same sentence as coloured TEXT
   * instead of as a pill.
   *
   * A chip is a control: it filters, or it is at least clickable. This
   * one never was — it stated a fact — and on the ticket list it sat in
   * a row with a priority chip, a status chip and an origin chip, four
   * pills deep, which is what the owner means by "a paragraph wearing
   * chips". In a TABLE the column heading already says what the value
   * is, so the pill was carrying no information the header did not.
   *
   * The detail page keeps the pill: there it is a single figure in a
   * card with no column heading above it, so the surface is what marks
   * it as a value.
   */
  variant?: "pill" | "plain";
}

// The two states whose meaning is not self-evident from the words alone
// get a hover explanation. Sprint 181 §4 left HISTORICAL out because the
// badge did not render at all; W7 renders it ("No deadline"), so the
// sentence explaining WHY it has none comes back with it.
const TOOLTIP_KEYS: Partial<Record<SLADisplayState, string>> = {
  PAUSED: "sla_tooltip_paused",
  COMPLETED: "sla_tooltip_completed",
  HISTORICAL: "sla_tooltip_historical",
};

export function SLABadge({
  state,
  remainingSeconds,
  size = "sm",
  variant = "pill",
}: SLABadgeProps) {
  const { t } = useTranslation("common");
  const deadlineText = useDeadlineText();

  // W7 BUG 3 — HISTORICAL used to return null here, which is why the
  // owner sees "an SLA column with nothing in it" on some rows. A blank
  // cell in a column with a heading reads as missing data or as a broken
  // screen; the ticket genuinely has no deadline, so the cell says
  // exactly that. Nothing is a worse answer than a short true sentence.
  const text = deadlineText(state, remainingSeconds);
  const tooltipKey = TOOLTIP_KEYS[state];
  // Tooltip strings live in common.json as optional keys; absence falls
  // through to undefined (no tooltip).
  const title = tooltipKey ? t(tooltipKey, { defaultValue: "" }) : undefined;

  const className =
    variant === "plain"
      ? `sla-text sla-text-${state.toLowerCase()}`
      : `sla-badge sla-badge-${state.toLowerCase()}` +
        (size === "md" ? " sla-badge-md" : "");

  return (
    <span className={className} title={title || undefined}>
      {state === "PAUSED" && (
        <Pause size={11} strokeWidth={2.4} aria-hidden="true" />
      )}
      <span className="sla-badge-label">{text}</span>
    </span>
  );
}
