/**
 * P-11 B2 — the week grid's pure rules, out of the component so vitest
 * can pin them (the unit runner is node-env, lib tests only).
 *
 *  - what counts as typed HOURS (`acceptsHoursInput` / `parseHours`);
 *  - which lines the FILL row writes (`isFillTarget`): the standard
 *    lines only — never a job line, never a line the operator added.
 *    The fill row's own sentence ("it lands on the N standard lines
 *    below, not on job lines") is computed from the same predicate, so
 *    the sentence and the behaviour cannot disagree.
 */

/**
 * W12 §4 — is this something a person could have typed while typing a
 * NUMBER OF HOURS? Two integer digits (a day has 24 hours), one
 * separator of either kind, two decimals. The field rejects the
 * KEYSTROKE instead of the value: a rejected character never appears.
 */
const HOURS_INPUT = /^\d{0,2}([.,]\d{0,2})?$/;

export function acceptsHoursInput(raw: string): boolean {
  return HOURS_INPUT.test(raw);
}

export function parseHours(raw: string): number {
  // Accept both "7,5" and "7.5": the Dutch keyboard produces a comma
  // and an operator typing their own decimal separator is not making a
  // mistake.
  const cleaned = raw.trim().replace(",", ".");
  if (cleaned === "") return 0;
  const value = Number(cleaned);
  return Number.isFinite(value) && value > 0 ? value : 0;
}

/** The two facts of a row the fill rule reads. */
export interface FillableRow {
  /** Sprint 166 §1 — TRUE only for a line the operator added; such a
   *  line is never filled, whenever it was added. */
  manual?: boolean;
  /** "" for a standard line; "TICKET"/"EXTRA_WORK"/… for a job line. */
  sourceType: string;
}

/** Sprint 166 §1 + P-11 B2 — the fill row writes the STANDARD lines:
 *  not a line the operator added, not a job line. */
export function isFillTarget(row: FillableRow): boolean {
  return !row.manual && row.sourceType === "";
}

/** The count the fill row's sentence and the footer's "N standard
 *  lines empty" both read. */
export function fillTargetCount(rows: readonly FillableRow[]): number {
  return rows.filter(isFillTarget).length;
}

/** A line's week total over its cells, `parseHours`'d — the same sum
 *  the row's Week column, the person band and the footer print. */
export function sumHours(values: readonly string[]): number {
  return values.reduce((sum, value) => sum + parseHours(value), 0);
}
