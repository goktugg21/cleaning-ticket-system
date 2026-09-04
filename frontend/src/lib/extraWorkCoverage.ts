/**
 * P-9 C4 — DOES THE PRICE COVER WHAT THE CUSTOMER ASKED FOR?
 *
 * The June 3 ruling stands: a quote need not mirror the cart. What the
 * screen owes the operator is the DIFFERENCE, said before the press
 * that sends, starts or approves the price — "the customer asked for 3
 * things, this price covers 2 of them". This module is the one
 * comparison behind the three ceremonies (`CoverageNotice` renders
 * it); it is pure so vitest can pin it.
 *
 * Matching rule: a quote line covers a cart line when both name the
 * same catalog service, or — for the free-text lines that have no
 * service — when their names are the same after trimming, collapsing
 * whitespace and case-folding. Service first, then name, so a quote
 * line the operator typed from the request's own words still counts.
 * Every quote line covers at most one cart line.
 */
import type { TFunction } from "i18next";

export interface CoverageLine {
  id: number;
  /** The catalog service behind the line, or null for a free-text line. */
  service: number | null;
  /** The line's name as the reader sees it. */
  label: string;
  /** DRF sends decimals as strings; a number is accepted too. */
  quantity: string | number;
  /** The unit, for the quantity sentence ("asked 2 h, priced 4 h"). */
  unit?: string;
}

export interface CoveragePair {
  cart: CoverageLine;
  quote: CoverageLine;
}

export interface QuantityDiff extends CoveragePair {
  asked: number;
  priced: number;
}

export interface CoverageResult {
  /** Cart lines the quote covers, with the quote line that covers each. */
  covered: CoveragePair[];
  /** Cart lines no quote line covers. */
  uncovered: CoverageLine[];
  /** Quote lines the customer did not ask for. */
  extra: CoverageLine[];
  /** Covered pairs whose quantities differ. */
  quantityDiffs: QuantityDiff[];
  /** Nothing missing, nothing extra, every quantity the same. */
  exact: boolean;
}

/** The name as it is compared: trimmed, whitespace collapsed, case-folded. */
export function foldLabel(label: string): string {
  return label.trim().replace(/\s+/g, " ").toLowerCase();
}

function toNumber(value: string | number): number {
  const n = typeof value === "number" ? value : Number.parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

export function compareCoverage(
  cartLines: readonly CoverageLine[],
  quoteLines: readonly CoverageLine[],
): CoverageResult {
  const remaining = [...quoteLines];
  const take = (predicate: (line: CoverageLine) => boolean): CoverageLine | null => {
    const index = remaining.findIndex(predicate);
    if (index === -1) return null;
    const [line] = remaining.splice(index, 1);
    return line;
  };

  const covered: CoveragePair[] = [];
  const uncovered: CoverageLine[] = [];
  // Pass 1 — by service. Pass 2 — by name, for what pass 1 left.
  const unmatched: CoverageLine[] = [];
  for (const cart of cartLines) {
    const quote =
      cart.service !== null
        ? take((line) => line.service !== null && line.service === cart.service)
        : null;
    if (quote) covered.push({ cart, quote });
    else unmatched.push(cart);
  }
  for (const cart of unmatched) {
    const wanted = foldLabel(cart.label);
    const quote =
      wanted === "" ? null : take((line) => foldLabel(line.label) === wanted);
    if (quote) covered.push({ cart, quote });
    else uncovered.push(cart);
  }
  // Keep the cart's own order in `covered` (pass 2 appended after pass 1).
  const order = new Map(cartLines.map((line, index) => [line.id, index]));
  covered.sort(
    (a, b) => (order.get(a.cart.id) ?? 0) - (order.get(b.cart.id) ?? 0),
  );

  const quantityDiffs: QuantityDiff[] = [];
  for (const pair of covered) {
    const asked = toNumber(pair.cart.quantity);
    const priced = toNumber(pair.quote.quantity);
    if (Math.abs(asked - priced) >= 0.005) {
      quantityDiffs.push({ ...pair, asked, priced });
    }
  }

  const extra = remaining;
  return {
    covered,
    uncovered,
    extra,
    quantityDiffs,
    exact:
      uncovered.length === 0 && extra.length === 0 && quantityDiffs.length === 0,
  };
}

/** Which ceremony the confirm belongs to; the primary button says what
 *  it does in that ceremony's verb. */
export type CoverageCeremony = "send" | "start" | "approve";

/** The primary button's label: the exact one when the price covers the
 *  request exactly, else the count it really acts on — "Send 2 of 3",
 *  "Start with 4 lines (1 extra)". */
export function coverageConfirmLabel(
  t: TFunction,
  coverage: CoverageResult | null,
  ceremony: CoverageCeremony,
  exactLabel: string,
): string {
  if (!coverage || coverage.exact) return exactLabel;
  const asked = coverage.covered.length + coverage.uncovered.length;
  if (coverage.uncovered.length > 0) {
    return t(`detail.coverage_${ceremony}_partial`, {
      covered: coverage.covered.length,
      asked,
    });
  }
  if (coverage.extra.length > 0) {
    return t(`detail.coverage_${ceremony}_extra`, {
      count: coverage.covered.length + coverage.extra.length,
      extra: coverage.extra.length,
    });
  }
  return exactLabel;
}

/** Trim a decimal string for a sentence: "2.00" -> "2", "2.50" -> "2.5". */
export function coverageQuantity(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Math.round(value * 100) / 100);
}
