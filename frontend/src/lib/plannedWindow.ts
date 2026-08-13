/**
 * Sprint 177 §1 — how a planned window reads when one end is missing.
 *
 * The window is `preferred_date` (its start, the customer's wish) through
 * `planned_end_date` (its end). Either can be null, and the render that
 * shipped in Sprint 173 only handled two of the four combinations:
 *
 *     {start ? fmt(start) : "—"}{end ? ` – ${fmt(end)}` : ""}
 *
 * With an end and NO start that prints `— – 16 Aug 2026`: an em dash
 * standing in for the missing start, then the range separator, then the
 * date. The owner read it as a stray line before the date, which is
 * exactly what it looks like. A range with one end missing is not a range.
 *
 * So the four cases are enumerated here instead of falling out of two
 * independent ternaries. This is a pure function over already-formatted
 * strings — it takes the formatter rather than calling `formatDate`
 * itself, so it stays free of the i18n/locale layer and can be unit
 * tested by passing an identity function.
 *
 * It lives in `lib/` rather than in the page because §6's Work Plan cards
 * show the same window on a card that may appear outside its planned
 * week, and two copies of this would drift the way the original two
 * ternaries did.
 */

export interface PlannedWindowLabels {
  /** What to show when neither end is known. Usually an em dash. */
  empty: string;
  /**
   * How to say "no start, ends on this date". A sentence fragment, not a
   * range: "Until 16 Aug 2026". Takes the formatted end date.
   */
  endOnly: (formattedEnd: string) => string;
}

/**
 * Render a planned window as one of four shapes:
 *
 *   both ends  -> "10 Aug 2026 – 16 Aug 2026"
 *   start only -> "10 Aug 2026"          (one planned day, not a range)
 *   end only   -> "Until 16 Aug 2026"    (an end, said as an end)
 *   neither    -> "—"
 *
 * `start` / `end` are the raw ISO date strings off the API (null when
 * unset); `formatDate` is the caller's locale-aware formatter.
 */
export function formatPlannedWindow(
  start: string | null | undefined,
  end: string | null | undefined,
  formatDate: (iso: string) => string,
  labels: PlannedWindowLabels,
): string {
  if (start && end) {
    // En dash with spaces, the typographic convention for a range, and
    // the separator the original used.
    return `${formatDate(start)} – ${formatDate(end)}`;
  }
  if (start) return formatDate(start);
  if (end) return labels.endOnly(formatDate(end));
  return labels.empty;
}
