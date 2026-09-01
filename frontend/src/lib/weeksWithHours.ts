// P-9 D3 — pure helpers for "which weeks hold saved hours"
// (`GET /api/timesheets/weeks/with-hours/`). No React, no API — the
// `src/lib/` convention; the two Hours pages and the week strip share
// them so they cannot disagree about which week counts as "last".

import type { WeekWithHours } from "../api/timesheets.types";
import type { IsoWeek } from "./isoWeek";
import { isoWeekOf } from "./isoWeek";

/** How many ISO weeks a year has (52 or 53). 28 December always falls
 *  in the year's last ISO week, so its week number is the count. */
export function isoWeeksInYear(isoYear: number): number {
  return isoWeekOf(new Date(isoYear, 11, 28)).isoWeek;
}

function isBefore(a: WeekWithHours, week: IsoWeek): boolean {
  return (
    a.iso_year < week.isoYear ||
    (a.iso_year === week.isoYear && a.iso_week < week.isoWeek)
  );
}

function isLater(a: WeekWithHours, b: WeekWithHours): boolean {
  return (
    a.iso_year > b.iso_year ||
    (a.iso_year === b.iso_year && a.iso_week > b.iso_week)
  );
}

/** The latest week BEFORE `week` that holds hours, or null. Reads one
 *  year's answer, so on week 1 a previous-year week is not found — the
 *  sentence then says the year holds nothing yet, which is true of the
 *  year. */
export function lastSavedWeekBefore(
  weeks: readonly WeekWithHours[],
  week: IsoWeek,
): WeekWithHours | null {
  let best: WeekWithHours | null = null;
  for (const candidate of weeks) {
    if (!isBefore(candidate, week)) continue;
    if (best === null || isLater(candidate, best)) best = candidate;
  }
  return best;
}

/** "312.00" -> "312", "12.50" -> "12,5" (nl) / "12.5" (en). The server
 *  sends two decimals; a sentence does not need the trailing zeros. */
export function formatHours(hours: string, locale: string): string {
  const parsed = Number(hours);
  if (!Number.isFinite(parsed)) return hours;
  return parsed.toLocaleString(locale, { maximumFractionDigits: 2 });
}
