/**
 * Sprint 183 §4 — the summary chips, as ONE list that both the render
 * and the filter read.
 *
 * Deriving the order from a literal in one place and the behaviour from
 * a switch in another is the split CLAUDE.md warns about (the Sprint 126
 * headerless column): a new chip cannot be half-added here.
 *
 * Its own module for the same reason as `entryHelpers` — a constant
 * exported beside a component costs the file its fast refresh.
 */
import type { WorkPlanCounts, WorkPlanEntry } from "../../api/workPlan";

/** `""` is "everything in this week"; the rest narrow it. Every one of
 *  them has a SERVER-side count behind it. */
export type ChipKey = "" | "overdue" | "open" | "in_progress" | "done" | "blocked";

export const CHIPS: {
  key: ChipKey;
  label: string;
  count: (c: WorkPlanCounts) => number;
  /** OVERDUE is a warning rather than a bucket, and is tinted only while
   *  it is non-zero and not itself the active filter. */
  warn?: boolean;
}[] = [
  { key: "", label: "chip_total", count: (c) => c.total },
  { key: "overdue", label: "chip_overdue", count: (c) => c.overdue, warn: true },
  { key: "open", label: "chip_open", count: (c) => c.open },
  { key: "in_progress", label: "chip_in_progress", count: (c) => c.in_progress },
  { key: "done", label: "chip_done", count: (c) => c.done },
  { key: "blocked", label: "chip_blocked", count: (c) => c.blocked },
];

export function matchesChip(entry: WorkPlanEntry, chip: ChipKey): boolean {
  if (chip === "") return true;
  if (chip === "overdue") return entry.is_overdue;
  if (chip === "open") return entry.state === "OPEN";
  if (chip === "in_progress") return entry.state === "IN_PROGRESS";
  if (chip === "done") return entry.state === "DONE";
  return entry.state === "BLOCKED";
}
