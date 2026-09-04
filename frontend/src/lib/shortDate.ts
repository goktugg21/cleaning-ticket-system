/**
 * P-10 A4 — DATES ARE SHORT. One formatter for every day the schedule
 * prints: `Wed 26 Aug` (nl `wo 26 aug`) — weekday short, day, month
 * short, the year only when it differs from today's; a range as
 * `Sun 30 Aug – Wed 9 Sep`; a clock only when a person set one
 * (`Today 09:00`). P-9's "Wednesday, September 2" went everywhere on
 * the page and no three of them fitted a 210px column.
 *
 * Pure: the caller passes the locale and today (the SERVER's today,
 * "YYYY-MM-DD", never the browser's — P-3 §A.3). Every input is a
 * server-decided DAY string; the explicit midnight keeps `Date` from
 * reading it as UTC and printing the previous day east of Greenwich.
 */

const DASH = "—";

function parseDay(iso: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null;
  const date = new Date(`${iso}T00:00:00`);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** "Wed 26 Aug", or "Wed 26 Aug 2025" when the year is not today's.
 *  Assembled from `formatToParts` in a FIXED order (weekday · day ·
 *  month [· year]) so the house shape holds in every locale — en-US
 *  would otherwise say "Wed, Aug 26" — and the month's trailing period
 *  ("aug.") is dropped. */
export function shortDay(iso: string | null | undefined, locale: string, todayIso: string): string {
  if (!iso) return DASH;
  const date = parseDay(iso);
  if (!date) return DASH;
  const sameYear = iso.slice(0, 4) === todayIso.slice(0, 4);
  try {
    const parts = new Intl.DateTimeFormat(locale, {
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
    }).formatToParts(date);
    const pick = (type: Intl.DateTimeFormatPartTypes) =>
      (parts.find((part) => part.type === type)?.value ?? "").replace(/\.$/, "");
    const out = [pick("weekday"), pick("day"), pick("month")];
    if (!sameYear) out.push(pick("year"));
    return out.filter(Boolean).join(" ");
  } catch {
    return DASH;
  }
}

/** "Sun 30 Aug – Wed 9 Sep"; one day when the ends are the same or
 *  the end is missing. */
export function shortRange(
  start: string | null | undefined,
  end: string | null | undefined,
  locale: string,
  todayIso: string,
): string {
  if (!start) return end ? shortDay(end, locale, todayIso) : DASH;
  if (!end || end === start) return shortDay(start, locale, todayIso);
  return `${shortDay(start, locale, todayIso)} – ${shortDay(end, locale, todayIso)}`;
}

/** The day with its clock when a person set one: "Wed 26 Aug 09:00". */
export function shortDayTime(
  iso: string | null | undefined,
  time: string | null | undefined,
  locale: string,
  todayIso: string,
): string {
  const day = shortDay(iso, locale, todayIso);
  return time ? `${day} ${time}` : day;
}

/** Whole days between two server days, signed (`b - a`). */
export function daysBetween(a: string, b: string): number {
  const da = parseDay(a);
  const db = parseDay(b);
  if (!da || !db) return 0;
  return Math.round((db.getTime() - da.getTime()) / 86_400_000);
}
