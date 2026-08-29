// Sprint 152 — ISO week arithmetic for the employee-hours UI.
//
// Pure functions, no React, no API — the `src/lib/` convention. The
// backend derives `iso_year` / `iso_week` from the date itself
// (`TimeEntry.save`), so these exist only so the week PICKER can name a
// week before any entry in it exists, and so a week can be labelled with
// its real dates.
//
// ISO 8601, matching Python's `date.isocalendar()` exactly: weeks start
// on MONDAY, and week 1 is the week containing the first Thursday of the
// year. That last rule is why a naive "day-of-year / 7" is wrong and why
// `isoYear` can differ from the calendar year — 2027-01-01 falls in ISO
// week 53 of 2026.

export interface IsoWeek {
  isoYear: number;
  isoWeek: number;
}

/** Format a Date as a "YYYY-MM-DD" string in LOCAL time.
 *
 * Deliberately not `toISOString().slice(0, 10)`: that converts to UTC
 * first, so anywhere east of Greenwich a local midnight becomes the
 * PREVIOUS day — the entry would be filed against the wrong date, and in
 * the worst case the wrong week.
 */
export function toDateString(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** Parse a "YYYY-MM-DD" string into a LOCAL-midnight Date (see above). */
export function fromDateString(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, (month ?? 1) - 1, day ?? 1);
}

/** The ISO year + week a date falls in. Mirrors `date.isocalendar()`. */
export function isoWeekOf(date: Date): IsoWeek {
  // Work on a copy at local midnight so a DST shift inside the day
  // cannot move the result.
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  // Shift to the THURSDAY of this week: ISO week N is the week whose
  // Thursday falls in year N, which makes the year and the week number
  // fall out of the same single adjustment.
  const dayOfWeek = (target.getDay() + 6) % 7; // Monday = 0
  target.setDate(target.getDate() - dayOfWeek + 3);
  const isoYear = target.getFullYear();
  const firstThursday = new Date(isoYear, 0, 4);
  const firstDayOfWeek = (firstThursday.getDay() + 6) % 7;
  firstThursday.setDate(firstThursday.getDate() - firstDayOfWeek + 3);
  const isoWeek =
    1 +
    Math.round(
      (target.getTime() - firstThursday.getTime()) / (7 * 24 * 3600 * 1000),
    );
  return { isoYear, isoWeek };
}

/** The MONDAY of a given ISO week. Inverse of `isoWeekOf`. */
export function isoWeekStart({ isoYear, isoWeek }: IsoWeek): Date {
  // Jan 4th is always in ISO week 1, in every year — the cheapest
  // anchor there is.
  const jan4 = new Date(isoYear, 0, 4);
  const jan4DayOfWeek = (jan4.getDay() + 6) % 7;
  const week1Monday = new Date(isoYear, 0, 4 - jan4DayOfWeek);
  return new Date(
    week1Monday.getFullYear(),
    week1Monday.getMonth(),
    week1Monday.getDate() + (isoWeek - 1) * 7,
  );
}

/** The seven dates of an ISO week, Monday first. */
export function isoWeekDays(week: IsoWeek): Date[] {
  const monday = isoWeekStart(week);
  return Array.from(
    { length: 7 },
    (_unused, index) =>
      new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + index),
  );
}

/** Move N weeks forward (or back, with a negative delta).
 *
 * Goes through a real DATE rather than incrementing `isoWeek` directly,
 * so crossing a year boundary lands correctly whether the year it
 * leaves had 52 or 53 ISO weeks — a number the caller should never have
 * to know.
 */
export function shiftIsoWeek(week: IsoWeek, delta: number): IsoWeek {
  const monday = isoWeekStart(week);
  const shifted = new Date(
    monday.getFullYear(),
    monday.getMonth(),
    monday.getDate() + delta * 7,
  );
  return isoWeekOf(shifted);
}

/** "2026-W32" — the label, and the value of the native week input. */
export function formatIsoWeek({ isoYear, isoWeek }: IsoWeek): string {
  return `${isoYear}-W${String(isoWeek).padStart(2, "0")}`;
}

/** Parse "2026-W32" back into an `IsoWeek`; null when unparseable. */
export function parseIsoWeek(value: string): IsoWeek | null {
  const match = /^(\d{4})-W(\d{1,2})$/.exec(value.trim());
  if (!match) return null;
  const isoYear = Number(match[1]);
  const isoWeek = Number(match[2]);
  if (isoWeek < 1 || isoWeek > 53) return null;
  return { isoYear, isoWeek };
}

/** The ISO week containing today. */
export function currentIsoWeek(): IsoWeek {
  return isoWeekOf(new Date());
}

/**
 * Sum a list of decimal-STRING amounts and return a 2-decimal string.
 *
 * Cent-integer arithmetic rather than float addition: `0.1 + 0.2` is
 * famously not `0.3` in IEEE754, and a weekly total is exactly the place
 * a stray 0.30000000000000004 would surface. Two decimals is the
 * backend's own precision for `hours` and `multiplier`, so nothing is
 * lost by working in hundredths.
 */
export function sumDecimalStrings(values: string[]): string {
  const hundredths = values.reduce((total, value) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return total;
    return total + Math.round(parsed * 100);
  }, 0);
  return (hundredths / 100).toFixed(2);
}

/**
 * P-3 §A.3 — a planned DAY as the schedule endpoint should receive it.
 *
 * A naive local datetime at midnight, no zone suffix. DRF reads a naive
 * datetime in the SERVER's zone (Europe/Amsterdam), so the day that was
 * picked is the day that is stored, whatever zone the browser runs in —
 * `toISOString()` converted the browser's midnight to UTC first, which
 * from a browser east of Amsterdam filed the plan under the previous
 * evening. Midnight is the convention every reader treats as "a day,
 * not a time": the schedule card shows no clock for it and the server
 * answers `start_time: null`.
 */
export function plannedDayIso(day: string, time?: string): string {
  return `${day}T${time && time.trim() ? time : "00:00"}:00`;
}
