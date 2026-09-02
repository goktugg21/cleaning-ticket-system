/**
 * P-13 B — billed hours against agreed hours, in one place.
 *
 * Two consumers, one arithmetic:
 *   * the Money tab's amber line — "6.5 h worked against 6 h agreed —
 *     €21.00 more than the customer approved", ALWAYS shown when the
 *     billed amount differs from the agreed one;
 *   * the Save-hours confirm — over 25% of the agreed total or over
 *     €100 more, the save asks first. WARN ONLY (the owner's ruling,
 *     2026-09-02): the save never blocks and no new quote is ever
 *     required.
 *
 * Pure and vitest-pinned.
 */

export interface OverQuoteFacts {
  /** Σ ordered quantity over the hourly lines. */
  agreedHours: number;
  /** Σ billable quantity (worked hours where entered, else ordered). */
  workedHours: number;
  /** Σ (billable − ordered) × rate, ex VAT. Positive = more than the
   *  customer approved. */
  deltaAmount: number;
}

/** The facts over the hourly lines. `worked` is the hours that WOULD
 *  bill (typed, or stored actual_hours, or the ordered quantity). A
 *  line with no rate or no quantity makes the money delta unknowable —
 *  null, never a partial sum. */
export function overQuoteFacts(
  lines: {
    rate: number | null;
    quantity: number | null;
    worked: number | null;
  }[],
): OverQuoteFacts | null {
  let agreedHours = 0;
  let workedHours = 0;
  let delta = 0;
  for (const line of lines) {
    if (line.rate === null || line.quantity === null) return null;
    const worked = line.worked ?? line.quantity;
    agreedHours += line.quantity;
    workedHours += worked;
    delta += round2((worked - line.quantity) * line.rate);
  }
  return {
    agreedHours: round2(agreedHours),
    workedHours: round2(workedHours),
    deltaAmount: round2(delta),
  };
}

/** The confirm threshold: MORE than the customer approved by over 25%
 *  of the agreed ex-VAT total, or by over €100. Billing less never
 *  asks. */
export function overQuoteNeedsConfirm(
  deltaAmount: number,
  agreedExTotal: number | null,
): boolean {
  if (deltaAmount <= 0) return false;
  if (deltaAmount > 100) return true;
  if (agreedExTotal !== null && agreedExTotal > 0) {
    return deltaAmount > 0.25 * agreedExTotal;
  }
  return false;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
