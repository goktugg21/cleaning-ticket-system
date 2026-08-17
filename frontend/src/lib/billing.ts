// RF-18 (#107) — shared billing math, extracted verbatim from
// InvoicesPage so the dashboard's month-billing widget and the
// Facturen page cannot drift. Pure functions over the EW list shape.
import type { ExtraWorkRequestList } from "../api/types";

export function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

// Final-with-quoted-fallback (the backend revenue rule): an EW that
// bills this month is earned, so prefer the final (actual-hours)
// amounts and fall back to the quoted estimate only when final is NULL.
export function rowAmounts(r: ExtraWorkRequestList): {
  subtotal: number;
  vat: number;
  total: number;
} {
  const num = (v: string | null | undefined): number => {
    const n = v != null ? Number.parseFloat(v) : NaN;
    return Number.isFinite(n) ? n : 0;
  };
  if (r.final_total_amount != null) {
    return {
      subtotal: num(r.final_subtotal_amount),
      vat: num(r.final_vat_amount),
      total: num(r.final_total_amount),
    };
  }
  return {
    subtotal: num(r.subtotal_amount),
    vat: num(r.vat_amount),
    total: num(r.total_amount),
  };
}

// Sprint 188 — "has anyone priced this yet?" is NOT the same question as
// "does this cost zero". Free work and a goodwill line are ordinary
// business, so a row at 0.00 may be a real answer; a row nobody has
// priced is an absence and must read as one (an em dash), never as
// EUR 0,00.
//
// DISPLAY ONLY. Sums keep treating an unpriced row as zero, because zero
// is what it contributes — `sumRows` below is deliberately untouched, and
// so is `rowAmounts`, which stays the ONE billing-total rule.
//
// The field is optional on the type, so an older cached payload cannot
// blank out a real amount: absent means "assume priced".
export function isPriced(r: ExtraWorkRequestList): boolean {
  return r.is_priced !== false;
}

export interface GroupTotals {
  count: number;
  open: number;
  invoiced: number;
  subtotal: number;
  vat: number;
  total: number;
}

export function sumRows(rows: ExtraWorkRequestList[]): GroupTotals {
  const totals: GroupTotals = {
    count: rows.length,
    open: 0,
    invoiced: 0,
    subtotal: 0,
    vat: 0,
    total: 0,
  };
  for (const r of rows) {
    if (r.is_invoiced === true) totals.invoiced += 1;
    else totals.open += 1;
    const a = rowAmounts(r);
    totals.subtotal += a.subtotal;
    totals.vat += a.vat;
    totals.total += a.total;
  }
  return totals;
}

// RF-18 — the widget needs the open-vs-invoiced money split, not just
// the row counts: sum the totals per bucket.
export function splitOpenInvoiced(rows: ExtraWorkRequestList[]): {
  openTotal: number;
  invoicedTotal: number;
} {
  let openTotal = 0;
  let invoicedTotal = 0;
  for (const r of rows) {
    const a = rowAmounts(r);
    if (r.is_invoiced === true) invoicedTotal += a.total;
    else openTotal += a.total;
  }
  return { openTotal, invoicedTotal };
}
