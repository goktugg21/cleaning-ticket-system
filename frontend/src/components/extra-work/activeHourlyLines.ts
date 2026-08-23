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
};

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
      }));
  }
  if (ew.routing_decision === "INSTANT") {
    return ew.line_items
      .filter((line) => line.unit_type === "HOURS")
      .map((line) => ({
        id: line.id,
        label: line.service_name,
        actual_hours: line.actual_hours,
      }));
  }
  return [];
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
