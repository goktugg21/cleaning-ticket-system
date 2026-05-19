// Sprint 26C — Extra Work API helpers.
//
// Thin axios wrappers so the page components don't carry literal
// URL strings. Endpoint paths mirror backend/extra_work/urls.py
// 1:1 and are mounted at `/api/extra-work/` (the api client adds
// the `/api` prefix).
import { api } from "./client";
import type {
  ExtraWorkPricingLineItem,
  ExtraWorkRequestCartCreatePayload,
  ExtraWorkRequestDetail,
  ExtraWorkRequestList,
  ExtraWorkStats,
  ExtraWorkStatsByBuildingResponse,
  ExtraWorkStatus,
  ExtraWorkStatusHistoryEntry,
  PaginatedResponse,
  Proposal,
  TicketList,
} from "./types";

export async function listExtraWork(): Promise<
  PaginatedResponse<ExtraWorkRequestList>
> {
  const response = await api.get<PaginatedResponse<ExtraWorkRequestList>>(
    "/extra-work/",
    { params: { page_size: 100 } },
  );
  return response.data;
}

export async function getExtraWork(
  id: number | string,
): Promise<ExtraWorkRequestDetail> {
  const response = await api.get<ExtraWorkRequestDetail>(`/extra-work/${id}/`);
  return response.data;
}

// Sprint 28 Batch 6 — cart-shaped create payload. The pre-batch-6
// `CreateExtraWorkPayload` shape (no `line_items`) is no longer
// emitted by the frontend; the backend keeps wire-level
// backwards-compatibility but the client always sends the cart shape.
export type CreateExtraWorkPayload = ExtraWorkRequestCartCreatePayload;

export async function createExtraWork(
  payload: ExtraWorkRequestCartCreatePayload,
): Promise<ExtraWorkRequestDetail> {
  const response = await api.post<ExtraWorkRequestDetail>(
    "/extra-work/",
    payload,
  );
  return response.data;
}

export interface TransitionPayload {
  to_status: ExtraWorkStatus;
  note?: string;
  is_override?: boolean;
  override_reason?: string;
  // Sprint 28 Batch 15.4 — required by the backend on CUSTOMER_USER-
  // driven CUSTOMER_REJECTED transitions; ignored on every other
  // path. Free-text reason captured via the RejectReasonDialog.
  customer_reject_reason?: string;
}

export async function transitionExtraWork(
  id: number | string,
  payload: TransitionPayload,
): Promise<ExtraWorkRequestDetail> {
  const response = await api.post<ExtraWorkRequestDetail>(
    `/extra-work/${id}/transition/`,
    payload,
  );
  return response.data;
}

export async function listExtraWorkPricing(
  id: number | string,
): Promise<ExtraWorkPricingLineItem[]> {
  const response = await api.get<ExtraWorkPricingLineItem[]>(
    `/extra-work/${id}/pricing-items/`,
  );
  return response.data;
}

export interface CreatePricingLineItemPayload {
  description: string;
  unit_type: string;
  quantity: string;
  unit_price: string;
  vat_rate: string;
  customer_visible_note?: string;
  internal_cost_note?: string;
}

export async function createExtraWorkPricingItem(
  id: number | string,
  payload: CreatePricingLineItemPayload,
): Promise<ExtraWorkPricingLineItem> {
  const response = await api.post<ExtraWorkPricingLineItem>(
    `/extra-work/${id}/pricing-items/`,
    payload,
  );
  return response.data;
}

export async function deleteExtraWorkPricingItem(
  id: number | string,
  lineItemId: number,
): Promise<void> {
  await api.delete(`/extra-work/${id}/pricing-items/${lineItemId}/`);
}

export async function listExtraWorkStatusHistory(
  id: number | string,
): Promise<ExtraWorkStatusHistoryEntry[]> {
  const response = await api.get<ExtraWorkStatusHistoryEntry[]>(
    `/extra-work/${id}/status-history/`,
  );
  return response.data;
}

// Sprint 28 Batch 9 — Extra Work dashboard aggregates.
//
// `GET /extra-work/stats/` returns the scope-respecting bucket summary
// for the calling user. `GET /extra-work/stats/by-building/` returns
// a flat list, one row per building visible to the caller. STAFF and
// other zero-scope actors receive `{total: 0, by_status: {}, ...}` and
// `[]` respectively — the dashboard renders an empty state in that case.
export async function getExtraWorkStats(): Promise<ExtraWorkStats> {
  const response = await api.get<ExtraWorkStats>("/extra-work/stats/");
  return response.data;
}

export async function getExtraWorkStatsByBuilding(): Promise<ExtraWorkStatsByBuildingResponse> {
  const response = await api.get<ExtraWorkStatsByBuildingResponse>(
    "/extra-work/stats/by-building/",
  );
  return response.data;
}

// Sprint 28 Batch 15.4 — proposal helpers used by the rebuilt
// detail page. The proposal builder UI itself is parked for a
// later batch; the detail page only needs to know whether an
// active SENT/ACCEPTED proposal exists so it can render the PDF-
// download button.
//
// Backend wire shapes:
//   GET  /extra-work/<ew>/proposals/        -> Proposal[]  (flat array, NOT paginated)
//   GET  /extra-work/<ew>/proposals/<id>/pdf/  -> binary PDF blob

export async function listProposalsForEw(
  ewId: number | string,
): Promise<Proposal[]> {
  const response = await api.get<Proposal[]>(
    `/extra-work/${ewId}/proposals/`,
  );
  return response.data;
}

export async function fetchProposalPdf(
  ewId: number | string,
  proposalId: number,
): Promise<Blob> {
  const response = await api.get<Blob>(
    `/extra-work/${ewId}/proposals/${proposalId}/pdf/`,
    { responseType: "blob" },
  );
  return response.data;
}

// ---------------------------------------------------------------------------
// Sprint 30 Batch 30.1 — spawned-tickets discovery via the new server-side
// filter.
//
// Backend `TicketFilter.extra_work_request` (sprint30) walks both spawn
// FK chains:
//   * `extra_work_request_item__extra_work_request_id` (cart route)
//   * `proposal_line__proposal__extra_work_request_id` (proposal route)
//
// Replaces the Sprint 29 Batch 29.8 client-side N+1 walk that fetched
// every customer+building-scoped ticket detail and filtered locally.
// Scope is still enforced server-side via `scope_tickets_for`.
export async function listSpawnedTickets(
  ewId: number,
): Promise<TicketList[]> {
  const response = await api.get<PaginatedResponse<TicketList>>("/tickets/", {
    params: { extra_work_request: ewId, page_size: 100 },
  });
  return response.data.results;
}

// ---------------------------------------------------------------------------
// Sprint 30 Batch 30.1 — provider-only retry of the legacy ticket-spawn
// helper.
//
// Recovers an EW that landed in CUSTOMER_APPROVED before the auto-spawn
// fix shipped. Backend gates on SUPER_ADMIN / COMPANY_ADMIN + status ==
// CUSTOMER_APPROVED + zero existing spawned tickets, and emits a stable
// `code` field on every 4xx response so the UI can pick a localized
// message.
export interface SpawnTicketsResponse {
  spawned_ticket_ids: number[];
  count: number;
}

export async function retrySpawnTicketsForExtraWork(
  ewId: number | string,
): Promise<SpawnTicketsResponse> {
  const response = await api.post<SpawnTicketsResponse>(
    `/extra-work/${ewId}/spawn/`,
  );
  return response.data;
}


