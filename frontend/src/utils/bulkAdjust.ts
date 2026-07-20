// #108 Part C — display-only preview of a bulk price adjustment
// (raise or lower, percent or fixed). Shared by the customer-pricing
// and services bulk-adjust modals so both show the same numbers. The
// backend's Decimal HALF_UP result is authoritative; this preview uses
// plain JS rounding and exists purely so the operator can see the
// effect before applying.

export type BulkAdjustMode = "percent" | "fixed";
export type BulkAdjustDirection = "raise" | "lower";

// Returns the adjusted price rounded to 2dp, or null when the amount
// (or the old price) does not parse to a usable number.
export function previewAdjustedPrice(
  oldPrice: string,
  mode: BulkAdjustMode,
  amount: string,
  direction: BulkAdjustDirection,
): number | null {
  const amountNumber = Number(amount);
  const oldNumber = Number(oldPrice);
  if (!Number.isFinite(amountNumber) || amountNumber <= 0) return null;
  if (!Number.isFinite(oldNumber)) return null;
  const signed = direction === "raise" ? amountNumber : -amountNumber;
  const result =
    mode === "percent" ? oldNumber * (1 + signed / 100) : oldNumber + signed;
  return Math.round(result * 100) / 100;
}
