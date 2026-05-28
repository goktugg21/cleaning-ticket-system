/**
 * Sprint 28 Batch 15.1 — shared status badge.
 *
 * Wraps the existing `.badge-*` and `.cell-tag-*` CSS so each status
 * resolves to (a) a translated label and (b) a tone color in one
 * call. Pages should pass the raw enum string; this component looks
 * up the label key and tone for them.
 *
 * Two visual variants:
 *   - `variant="pill"`  → rounded badge with leading dot (default)
 *   - `variant="cell"`  → tighter inline form for table cells
 *
 * The label can be overridden via the `label` prop when a page wants
 * to inject context (e.g. "Override applied"). When omitted, the
 * component resolves the i18n key from the enum maps in
 * `lib/enumLabels.ts`.
 */
import { useTranslation } from "react-i18next";
import {
  extraWorkStatusLabelKey,
  extraWorkStatusTone,
  priorityLabelKey,
  priorityTone,
  ticketStatusLabelKey,
  ticketStatusTone,
  type StatusTone,
} from "../lib/enumLabels";
import type {
  ExtraWorkStatusValue,
  TicketStatus,
} from "../api/types";

type TicketStatusInput = { kind: "ticket"; value: TicketStatus | string };
type ExtraWorkStatusInput = {
  kind: "extra-work";
  value: ExtraWorkStatusValue | string;
};
type PriorityInput = {
  kind: "priority";
  value: "NORMAL" | "HIGH" | "URGENT" | string;
};
type GenericInput = {
  kind: "generic";
  tone: StatusTone;
  /** Required for generic — caller supplies its own translated label. */
  label: string;
};

type StatusBadgeInput =
  | TicketStatusInput
  | ExtraWorkStatusInput
  | PriorityInput
  | GenericInput;

export interface StatusBadgeProps {
  status: StatusBadgeInput;
  /** Visual variant. Default `"pill"`. */
  variant?: "pill" | "cell";
  /** Override the resolved label (rarely needed). */
  label?: string;
  testId?: string;
}

function toneToCellClass(tone: StatusTone): string {
  switch (tone) {
    case "open":
      return "cell-tag-open";
    case "progress":
      return "cell-tag-in_progress";
    case "waiting":
      return "cell-tag-waiting_customer_approval";
    case "approved":
      return "cell-tag-approved";
    case "rejected":
      return "cell-tag-rejected";
    case "closed":
      return "cell-tag-closed";
    case "reopened":
      return "cell-tag-reopened_by_admin";
    case "neutral":
    default:
      return "cell-tag-normal";
  }
}

function toneToBadgeClass(tone: StatusTone): string {
  switch (tone) {
    case "open":
    case "progress":
      return "badge-open";
    case "waiting":
      return "badge-waiting_customer_approval";
    case "approved":
      return "badge-approved";
    case "rejected":
      return "badge-rejected";
    case "closed":
      return "badge-closed";
    case "reopened":
      return "badge-reopened_by_admin";
    case "neutral":
    default:
      return "badge-normal";
  }
}

export function StatusBadge({
  status,
  variant = "pill",
  label,
  testId,
}: StatusBadgeProps) {
  const { t } = useTranslation("common");
  let tone: StatusTone;
  let resolvedLabel: string;

  switch (status.kind) {
    case "ticket":
      tone = ticketStatusTone(status.value);
      resolvedLabel = label ?? t(ticketStatusLabelKey(status.value));
      break;
    case "extra-work":
      tone = extraWorkStatusTone(status.value);
      resolvedLabel = label ?? t(extraWorkStatusLabelKey(status.value));
      break;
    case "priority":
      tone = priorityTone(status.value);
      resolvedLabel = label ?? t(priorityLabelKey(status.value));
      break;
    case "generic":
      tone = status.tone;
      resolvedLabel = label ?? status.label;
      break;
  }

  if (variant === "cell") {
    return (
      <span className={`cell-tag ${toneToCellClass(tone)}`} data-testid={testId}>
        <i />
        {resolvedLabel}
      </span>
    );
  }

  return (
    <span className={`badge ${toneToBadgeClass(tone)}`} data-testid={testId}>
      {resolvedLabel}
    </span>
  );
}

