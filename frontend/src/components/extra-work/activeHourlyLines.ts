/**
 * W17 — the active-hourly-line derivation behind ActualHoursPanel, in
 * its own module because the panel file may export ONLY components
 * (react-refresh rule). Both mounts of the panel (the Extra Work
 * detail's Hours tab and the ticket's Extra work card group) derive
 * their line set here, so the backend `final_amounts.
 * active_priced_lines` precedence (approved-proposal > INSTANT-cart >
 * legacy) has ONE frontend owner.
 */
import type {
  ExtraWorkRequestDetail,
  Proposal,
  ProposalDetail,
} from "../../api/types";

// Sprint 8A-fix — normalized hourly line shape the panel renders. Both
// cart line items (label = service_name) and approved-proposal lines
// (label = service_name ?? description) map into this; `id` is the
// line_id the actual-hours endpoint accepts for whichever active set.
export type ActualHoursLine = {
  id: number;
  label: string;
  actual_hours: string | null;
  /** W25 — the per-unit rate the line bills at, so the hours field can
   *  show its own arithmetic instead of a bare number. `null` when the
   *  source carries no per-unit rate (see the per-source note on
   *  `deriveActiveHourlyLines`) — such a row keeps a plain input and
   *  claims no math. */
  rate: number | null;
  /** W25 — the ORDERED quantity, which is what the backend bills when
   *  no actual hours are entered (`final_amounts.billable_quantity`
   *  substitutes `actual_hours` only when it is set). The panel needs
   *  it to preview the WHOLE set, not just the rows being typed in. */
  quantity: number | null;
};

// W25 — a source string is a finite number or it is nothing. Exported
// because both this module and TicketExtraWorkCards decide it the same
// way, and a second copy is a second answer waiting to drift.
export function finiteOrNull(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : null;
}

// Sprint 8A-fix — the active hourly line set a provider can enter
// actual hours for, following the backend `active_priced_lines`
// precedence exactly (approved-proposal > INSTANT-cart > legacy). The
// approved-proposal case was the P1 dead-end: its lines DO gate the
// operational ticket's completion (`actual_hours_required`) but the
// old INSTANT-only guard hid the entry UI.
//
// Approved-proposal selection mirrors `final_amounts.active_priced_lines`:
// the latest CUSTOMER_APPROVED proposal by customer_decided_at, then by
// id (both descending).
export function selectApprovedProposal(
  proposals: Proposal[],
): Proposal | null {
  const approved = proposals.filter((p) => p.status === "CUSTOMER_APPROVED");
  if (approved.length === 0) return null;
  return [...approved].sort((a, b) => {
    const ad = a.customer_decided_at ?? "";
    const bd = b.customer_decided_at ?? "";
    if (ad !== bd) return ad < bd ? 1 : -1;
    return b.id - a.id;
  })[0];
}

// W25 — WHERE THE PER-HOUR RATE LIVES, per source, measured against
// backend/extra_work/final_amounts.py::_line_unit_price:
//   * approved-proposal lines -> `unit_price` (the operator-typed
//     snapshot; the backend bills exactly this). Always present.
//   * INSTANT cart lines -> no persisted unit price exists on the row;
//     `contract_unit_price` is the serializer's live resolve of the
//     customer's contract, and is null for a NEEDS_PROPOSAL line.
//   * legacy `pricing_line_items` -> `unit_price` (operator-typed; the
//     backend bills exactly this — `_line_unit_price` falls through to
//     `line.unit_price` for the legacy kind). Hourly rows on this path
//     exist since P-13 I gave the legacy model its `actual_hours`
//     column (before that the branch returned [] by design).
// A line whose rate resolves to null keeps a plain input: no invented
// rate, no invented arithmetic.
//
// Normalized active hourly line set. Approved-proposal lines win;
// otherwise the INSTANT cart lines; otherwise none. The approved
// proposal's lines (with `actual_hours`) are NOT on the EW detail
// payload — the caller fetches that proposal's detail and passes it in
// (`null` while it is still loading, which reads as "no lines yet").
export function deriveActiveHourlyLines(
  ew: ExtraWorkRequestDetail | null,
  approvedProposal: Proposal | null,
  approvedProposalDetail: ProposalDetail | null,
): ActualHoursLine[] {
  if (!ew) return [];
  if (approvedProposal) {
    if (!approvedProposalDetail) return []; // detail still loading
    return approvedProposalDetail.lines
      .filter(
        (line) => line.is_approved_for_spawn && line.unit_type === "HOURS",
      )
      .map((line) => ({
        id: line.id,
        label: line.service_name ?? line.description,
        actual_hours: line.actual_hours ?? null,
        // A proposal line carries the operator-typed `unit_price`
        // snapshot, and that IS what the backend bills it at
        // (`final_amounts._line_unit_price` -> `line.unit_price`).
        rate: finiteOrNull(line.unit_price),
        quantity: finiteOrNull(line.quantity),
      }));
  }
  if (ew.routing_decision === "INSTANT") {
    return ew.line_items
      .filter((line) => line.unit_type === "HOURS")
      .map((line) => ({
        id: line.id,
        label: line.service_name,
        actual_hours: line.actual_hours,
        // A cart line has no persisted unit price of its own; the
        // serializer live-resolves the customer's contract row at read
        // time, and that is the only per-unit rate on this payload.
        // The Agreed table in TicketExtraWorkCards prices cart lines
        // the same way, so the two never name different rates.
        rate: finiteOrNull(line.contract_unit_price),
        quantity: finiteOrNull(line.quantity),
      }));
  }
  // P-13 I — the legacy pricing-items path, now that the column
  // exists. Mirrors `final_amounts.active_priced_lines`' third arm.
  return (ew.pricing_line_items ?? [])
    .filter((line) => line.unit_type === "HOURS")
    .map((line) => ({
      id: line.id,
      label: line.description,
      actual_hours: line.actual_hours ?? null,
      rate: finiteOrNull(line.unit_price),
      quantity: finiteOrNull(line.quantity),
    }));
}

// Remount key: changes whenever the persisted actual_hours change, so
// the panel re-seeds its inputs after a save WITHOUT a resync effect.
// Cart case keys off the refreshed EW's updated_at; proposal case off
// the approved lines' (id, actual_hours) signature.
export function actualHoursPanelKey(
  approvedProposal: Proposal | null,
  activeHourlyLines: ActualHoursLine[],
  ewUpdatedAt: string | undefined,
): string {
  return approvedProposal
    ? `prop:${approvedProposal.id}:${activeHourlyLines
        .map((line) => `${line.id}=${line.actual_hours ?? ""}`)
        .join(",")}`
    : `cart:${ewUpdatedAt ?? "none"}`;
}
