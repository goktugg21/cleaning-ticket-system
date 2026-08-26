/**
 * W-LATE §1b — the late ladder, read ONCE on the client.
 *
 * The rule itself lives on the server (`tickets/lateness.py`): it needs
 * the widest planned window across a ticket's slots and the hours booked
 * against the job, neither of which a browser can know. What this module
 * owns is the READING of that answer — which rung, how many days, which
 * colour class, which order — so the strip, the quarantine bar, the week
 * card and the day modal all say the same thing about the same job.
 *
 * Its own module, like `entryHelpers`: a file that exports a component
 * AND a function loses fast refresh for the whole file, and these are
 * not components.
 */
import type { TFunction } from "i18next";

import type {
  LateLevel,
  WorkPlanEntry,
  WorkPlanEscalationStep,
  WorkPlanLateness,
} from "../../api/workPlan";

export interface LateFacts {
  level: LateLevel;
  /** Days late against the plan, else against the deadline. */
  daysLate: number;
  plannedDate: string | null;
  plannedDaysLate: number | null;
  deadline: string | null;
  deadlineDaysLate: number | null;
  anchor: string | null;
  anchorDays: number | null;
  hoursBooked: number;
  steps: WorkPlanEscalationStep[];
}

/** The rung this entry stands on, or null when it is not late. */
export function latenessOf(entry: WorkPlanEntry): LateFacts | null {
  const raw: WorkPlanLateness | undefined = entry.lateness;
  if (!raw || raw.level === null) return null;
  const hours = Number(raw.hours_booked);
  return {
    level: raw.level,
    daysLate: raw.days_late ?? 0,
    plannedDate: raw.planned_date,
    plannedDaysLate: raw.planned_days_late,
    deadline: raw.deadline,
    deadlineDaysLate: raw.deadline_days_late,
    anchor: raw.anchor,
    anchorDays: raw.anchor_days,
    hoursBooked: Number.isFinite(hours) ? hours : 0,
    steps: raw.escalation_steps ?? [],
  };
}

export function isLate(entry: WorkPlanEntry): boolean {
  return latenessOf(entry) !== null;
}

/** L3 — thirty days past the anchor with no hour booked. */
export function isQuarantined(entry: WorkPlanEntry): boolean {
  return latenessOf(entry)?.level === 3;
}

/** The severity class the design contract names: L1 orange, L2 red, L3
 *  dark bordeaux with the thick left inset. ONE map, iterated nowhere —
 *  a card asks for its own rung's class and nothing else. */
export const LATE_LEVEL_CLASS: Record<LateLevel, string> = {
  1: "wp-late-l1",
  2: "wp-late-l2",
  3: "wp-late-l3",
};

/** Left to right, ascending severity: the rung, then the days within the
 *  rung, then the title. Mirrors `lateness.sort_key` on the server, so a
 *  list the server already sorted comes out unchanged and a list the
 *  page assembled itself (the day modal's late half) comes out the same
 *  way. */
export function sortLate(entries: WorkPlanEntry[]): WorkPlanEntry[] {
  return [...entries]
    .map((entry) => ({ entry, facts: latenessOf(entry) }))
    .filter((pair): pair is { entry: WorkPlanEntry; facts: LateFacts } =>
      pair.facts !== null,
    )
    .sort((a, b) => {
      if (a.facts.level !== b.facts.level) return a.facts.level - b.facts.level;
      if (a.facts.daysLate !== b.facts.daysLate) {
        return a.facts.daysLate - b.facts.daysLate;
      }
      const byTitle = (a.entry.title || "").localeCompare(b.entry.title || "");
      if (byTitle !== 0) return byTitle;
      return a.entry.key.localeCompare(b.entry.key);
    })
    .map((pair) => pair.entry);
}

/** The step of a given kind that has fired, if any. */
export function escalationStep(
  facts: LateFacts,
  step: WorkPlanEscalationStep["step"],
): WorkPlanEscalationStep | undefined {
  return facts.steps.find((s) => s.step === step);
}

/**
 * "Dhr. X is geïnformeerd" / "X en 2 anderen zijn geïnformeerd".
 *
 * The names arrive resolved from the recipients the step actually
 * reached — display names, at render time. The honorific is part of the
 * display name only when the profile carries one; this app's user
 * record has no honorific field today, so the bare full name is what
 * renders, and nothing here invents a "Dhr." nobody typed.
 */
export function notifiedSentence(names: string[], t: TFunction): string {
  const clean = names.map((n) => n.trim()).filter(Boolean);
  if (clean.length === 0) return "";
  if (clean.length === 1) return t("late.notified_single", { name: clean[0] });
  return t("late.notified_others", { name: clean[0], count: clean.length - 1 });
}
