/**
 * P-13 A (W1) — the billing-day picker's value model, extracted from
 * `CustomerFacturatieSection` so the Invoices page's "Set a billing
 * day" dialog and the customer settings page share ONE representation
 * (a second copy is a second answer waiting to drift). In `lib/`
 * because the section file may export only components
 * (react-refresh) — the `useCompanyScope` precedent.
 *
 * Picker value: "" (unset), "1".."28" (a specific day of month), or
 * "last" (last of month). FIRST_OF_MONTH stays a valid enum but is
 * shown as day 1 (they are equivalent). Days cap at 28 so the day
 * exists in every month.
 */
import type { InvoiceDayRule } from "../api/types";

export const DAY_OF_MONTH_OPTIONS = Array.from(
  { length: 28 },
  (_, i) => i + 1,
);

export interface BillingDayFacts {
  /** Absent/`undefined` reads as unset — `CustomerAdmin` serialises
   *  the pair optionally. */
  invoice_day_of_month?: number | null;
  invoice_day_rule?: InvoiceDayRule | "";
}

export function initialDaySelection(c: BillingDayFacts): string {
  if (c.invoice_day_of_month != null) return String(c.invoice_day_of_month);
  if (c.invoice_day_rule === "LAST_OF_MONTH") return "last";
  if (c.invoice_day_rule === "FIRST_OF_MONTH") return "1"; // first === day 1
  return "";
}

// One canonical representation per selection so a reload shows the same
// choice: a specific day stores invoice_day_of_month and clears the
// rule; last-of-month stores the rule and clears the day; unset clears
// both.
export function daySelectionToPayload(sel: string): {
  invoice_day_rule: InvoiceDayRule | "";
  invoice_day_of_month: number | null;
} {
  if (sel === "last") {
    return { invoice_day_rule: "LAST_OF_MONTH", invoice_day_of_month: null };
  }
  if (sel === "") {
    return { invoice_day_rule: "", invoice_day_of_month: null };
  }
  return { invoice_day_rule: "", invoice_day_of_month: Number(sel) };
}
