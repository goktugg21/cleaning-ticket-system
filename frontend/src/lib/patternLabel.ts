/**
 * P-15 4.3 — the seven-day pattern, compressed into words.
 *
 * The Agreed hours table used to spend seven columns on the pattern
 * (as dead inputs, the S2 finding); §D.22 wants ONE column that reads
 * like the agreement: "Mon–Fri · 8 h", or "Mon–Thu · 8 h, Fri · 6 h"
 * when the days differ. Zero days are not part of the agreement and
 * are skipped; an all-zero pattern answers null so the cell can say
 * "no days yet" in its own words.
 *
 * A pure module so the compression is vitest-pinned without a DOM.
 */

export const PATTERN_DAYS = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
] as const;

export type PatternDay = (typeof PATTERN_DAYS)[number];

export interface PatternGroup {
  /** First and last day of a consecutive run with the same hours. */
  from: PatternDay;
  to: PatternDay;
  /** The run's hours, as a number (parsed from the API's string). */
  hours: number;
}

/** Consecutive same-hours runs, zero days skipped; [] when empty. */
export function patternGroups(
  days: Record<PatternDay, string | number>,
): PatternGroup[] {
  const groups: PatternGroup[] = [];
  for (const day of PATTERN_DAYS) {
    const hours = Number(days[day]) || 0;
    if (hours <= 0) continue;
    const last = groups[groups.length - 1];
    if (
      last &&
      last.hours === hours &&
      PATTERN_DAYS.indexOf(day) ===
        PATTERN_DAYS.indexOf(last.to) + 1
    ) {
      last.to = day;
    } else {
      groups.push({ from: day, to: day, hours });
    }
  }
  return groups;
}

/**
 * The words: "Mon–Fri · 8 h" (one run), "Mon–Thu · 8 h, Fri · 6 h"
 * (several), null for an all-zero pattern. `dayLabel` and `hoursLabel`
 * come from the caller's i18n so the module stays pure.
 */
export function patternLabel(
  days: Record<PatternDay, string | number>,
  dayLabel: (day: PatternDay) => string,
  hoursLabel: (hours: number) => string,
): string | null {
  const groups = patternGroups(days);
  if (groups.length === 0) return null;
  return groups
    .map((group) =>
      group.from === group.to
        ? `${dayLabel(group.from)} · ${hoursLabel(group.hours)}`
        : `${dayLabel(group.from)}–${dayLabel(group.to)} · ${hoursLabel(group.hours)}`,
    )
    .join(", ");
}
