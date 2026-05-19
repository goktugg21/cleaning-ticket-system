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
  TicketDetail,
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
// Sprint 29 Batch 29.8 — spawned-tickets discovery helper.
//
// The backend exposes the spawn linkage as
// `Ticket.extra_work_request_item -> ExtraWorkRequestItem.extra_work_request`,
// but neither `TicketFilter` (no `extra_work_request_item__*` filter) nor
// `TicketListSerializer` (no `extra_work_origin` field) admits a direct
// query. The detail serializer DOES expose `extra_work_origin` with the
// parent EW id, so we narrow the candidate set with the available
// `customer` + `building` filters (these are guaranteed to match for any
// spawned ticket — the spawn helpers inherit both from the parent EW),
// then resolve each candidate via `GET /api/tickets/<id>/` and keep the
// ones whose `extra_work_origin.extra_work_request_id` matches.
//
// This is intentionally limited to scopes the calling user can see:
// `scope_tickets_for` already filters the list, and the detail call
// returns 403/404 for out-of-scope ids. Any per-id failure is treated
// as "not a spawned ticket" and silently skipped so a partial result
// still renders.
//
// Test debt (Sprint 29 Batch 29.8): this is a client-side N+1 walk. A
// future backend slot should add either a `TicketFilter.extra_work_request`
// filter or a dedicated `/api/extra-work/<id>/spawned-tickets/` endpoint
// and the helper should be collapsed to a single call.
export async function listSpawnedTickets(
  ewId: number,
  customerId: number,
  buildingId: number,
): Promise<TicketList[]> {
  const candidateResponse = await api.get<PaginatedResponse<TicketList>>(
    "/tickets/",
    {
      params: {
        customer: customerId,
        building: buildingId,
        page_size: 100,
      },
    },
  );
  const candidates = candidateResponse.data.results;
  const matched: TicketList[] = [];
  for (const candidate of candidates) {
    try {
      const detailResponse = await api.get<TicketDetail>(
        `/tickets/${candidate.id}/`,
      );
      const origin = detailResponse.data.extra_work_origin;
      if (origin && origin.extra_work_request_id === ewId) {
        matched.push(candidate);
      }
    } catch {
      // Out-of-scope or missing detail — skip silently; the panel
      // renders whatever resolved successfully.
    }
  }
  return matched;
}


