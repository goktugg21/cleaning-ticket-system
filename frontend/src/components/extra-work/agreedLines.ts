/**
 * P-13 A (W3) — the Agreement's lines on ONE VAT basis.
 *
 * The old inline derivation showed a proposal line's `line_total`
 * (INCL VAT) and a legacy line's `total` (INCL VAT) in the same
 * Amount column where an INSTANT cart line showed `unit price ×
 * quantity` (EX VAT) — €31.48 quoted rendered as €38.09 on one path
 * and €252.00 stayed €252.00 on another. One basis now: EX VAT per
 * line, and ONE pair of totals (ex + incl) under the table.
 *
 * Pure and vitest-pinned on all three paths. Follows the same
 * precedence walk as the money totals (approved proposal > INSTANT
 * cart > legacy pricing rows — `final_amounts.active_priced_lines`),
 * so "Agreed" can never name a different set than the amounts under
 * it.
 */
import type {
  ExtraWorkRequestDetail,
  Proposal,
  ProposalDetail,
} from "../../api/types";

import { round2 } from "../../lib/pricingRow";

import { finiteOrNull } from "./activeHourlyLines";

export interface AgreedLine {
  id: number;
  label: string;
  quantity: string | null;
  /** The per-unit price the line bills at (ex VAT), or null when the
   *  source carries none. P-13 B — block 1 renders qty × unit = amount. */
  unitPrice: number | null;
  /** The line's unit type ("HOURS", "FIXED", …) so the Worked block
   *  can split hourly from fixed lines. */
  unitType: string;
  /** EX-VAT line amount, or null when the line has no price yet (an
   *  em dash, never a zero — zero is a legal price). */
  amount: number | null;
}

export interface AgreedTotals {
  /** Sum of the lines, ex VAT. */
  ex: number;
  /** The same lines with their VAT. */
  incl: number;
}

export function agreedLines(
  ew: ExtraWorkRequestDetail,
  approvedProposal: Proposal | null,
  approvedProposalDetail: ProposalDetail | null,
): { rows: AgreedLine[]; totals: AgreedTotals | null } {
  if (approvedProposal) {
    const lines = (approvedProposalDetail?.lines ?? []).filter(
      (line) => line.is_approved_for_spawn,
    );
    const rows = lines.map((line) => ({
      id: line.id,
      label: line.service_name ?? line.description,
      quantity: line.quantity ?? null,
      unitPrice: finiteOrNull(line.unit_price),
      unitType: String(line.unit_type),
      // The stored EX-VAT subtotal — the backend's own rounding.
      amount: finiteOrNull(line.line_subtotal),
    }));
    return { rows, totals: sumStored(lines.map((line) => [line.line_subtotal, line.line_total])) };
  }

  if (ew.routing_decision === "INSTANT") {
    const rows = ew.line_items.map((line) => {
      const price = finiteOrNull(line.contract_unit_price);
      const qty = finiteOrNull(line.quantity);
      return {
        id: line.id,
        label: line.service_name || line.custom_description,
        quantity: line.quantity ?? null,
        unitPrice: price,
        unitType: String(line.unit_type),
        amount: price !== null && qty !== null ? round2(price * qty) : null,
      };
    });
    // A cart line carries no stored totals; mirror the backend's
    // per-line rounding (subtotal first, VAT derived from it). Any
    // line without a resolved price or VAT makes the totals unknowable
    // — null, never a partial sum dressed as a total.
    let ex = 0;
    let incl = 0;
    for (const line of ew.line_items) {
      const price = finiteOrNull(line.contract_unit_price);
      const qty = finiteOrNull(line.quantity);
      const vat = finiteOrNull(line.contract_vat_pct);
      if (price === null || qty === null || vat === null) {
        return { rows, totals: null };
      }
      const sub = round2(price * qty);
      ex = round2(ex + sub);
      incl = round2(incl + sub + round2((sub * vat) / 100));
    }
    return { rows, totals: rows.length > 0 ? { ex, incl } : null };
  }

  const legacy = ew.pricing_line_items;
  const rows = legacy.map((line) => ({
    id: line.id,
    label: line.description,
    quantity: line.quantity ?? null,
    unitPrice: finiteOrNull(line.unit_price),
    unitType: String(line.unit_type),
    // The stored EX-VAT subtotal (was `total`, incl VAT — the W3 bug).
    amount: finiteOrNull(line.subtotal),
  }));
  return { rows, totals: sumStored(legacy.map((line) => [line.subtotal, line.total])) };
}

function sumStored(
  pairs: [string | null | undefined, string | null | undefined][],
): AgreedTotals | null {
  if (pairs.length === 0) return null;
  let ex = 0;
  let incl = 0;
  for (const [sub, total] of pairs) {
    const s = finiteOrNull(sub);
    const t = finiteOrNull(total);
    if (s === null || t === null) return null;
    ex = round2(ex + s);
    incl = round2(incl + t);
  }
  return { ex, incl };
}
