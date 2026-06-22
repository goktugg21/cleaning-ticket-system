// Sprint 26C — Extra Work API helpers.
//
// Thin axios wrappers so the page components don't carry literal
// URL strings. Endpoint paths mirror backend/extra_work/urls.py
// 1:1 and are mounted at `/api/extra-work/` (the api client adds
// the `/api` prefix).
import { api } from "./client";
import type {
  EwMessage,
  EwMessageRecipient,
  EwMessageType,
  EwMessageVisibility,
  ExtraWorkPreviewPayload,
  ExtraWorkPreviewResponse,
  ExtraWorkPricingLineItem,
  ExtraWorkRequestCartCreatePayload,
  ExtraWorkRequestDetail,
  ExtraWorkRequestIntent,
  ExtraWorkRequestList,
  ExtraWorkStats,
  ExtraWorkStatsByBuildingResponse,
  ExtraWorkStatus,
  ExtraWorkStatusHistoryEntry,
  ExtraWorkUnitType,
  PaginatedResponse,
  Proposal,
  ProposalDetail,
  ProposalLine,
  ProposalStatus,
  TicketList,
} from "./types";

// Sprint 28 follow-up — backend `ExtraWorkRequestFilter` (see
// `backend/extra_work/filters.py`) exposes `customer`, `building`,
// `status`, `routing_decision` as query-param filters; the
// scope-respecting `get_queryset` runs first so a CUSTOMER_USER
// passing a foreign `customer=` just gets zero rows rather than a
// 403. We accept the filter shape here as optional params — existing
// callers (`ExtraWorkListPage`) continue to call `listExtraWork()`
// with no args and the request shape stays identical to pre-this-
// change.
export interface ListExtraWorkParams {
  customer?: number;
  building?: number;
  status?: ExtraWorkStatus;
  routing_decision?: "INSTANT" | "PROPOSAL";
  request_intent?: ExtraWorkRequestIntent;
  created_by?: number;
  billing_period?: string; // "YYYY-MM" — server buckets on COALESCE(invoice_date, completion date)
  invoice_status?: "completed" | "invoiced";
  page_size?: number;
}

export async function listExtraWork(
  params: ListExtraWorkParams = {},
): Promise<PaginatedResponse<ExtraWorkRequestList>> {
  const response = await api.get<PaginatedResponse<ExtraWorkRequestList>>(
    "/extra-work/",
    { params: { page_size: 100, ...params } },
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

// Sprint 5 (frontend) — non-mutating cart preview / classification.
// COMPUTE-ONLY: the backend persists NO ExtraWorkRequest. Returns the
// per-line price classification (the customer's OWN agreed price only —
// provider defaults never leak), cart-level flags, and the
// backend-gated `allowed_intents` + `default_intent` that drive the
// create page's intent selector. When `payload.request_intent` is set,
// the response also carries `requested_intent_allowed`
// (+ `requested_intent_error` on rejection). Mirrors the create cart's
// scope + permission gate (`backend/extra_work/views.py::preview`).
export async function getExtraWorkPreview(
  payload: ExtraWorkPreviewPayload,
): Promise<ExtraWorkPreviewResponse> {
  const response = await api.post<ExtraWorkPreviewResponse>(
    "/extra-work/preview/",
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

// M4 (2c) invoice run — mark/clear every EARNED, not-yet-invoiced EW that
// bills in a given company+month. `invoiced_count` comes back from mark,
// `cleared_count` from clear; both return the affected `ew_ids`.
export interface InvoiceRunResult {
  invoiced_count?: number;
  cleared_count?: number;
  ew_ids: number[];
}

export async function markExtraWorkInvoiced(body: {
  company: number;
  year: number;
  month: number;
}): Promise<InvoiceRunResult> {
  const response = await api.post<InvoiceRunResult>(
    "/extra-work/mark-invoiced/",
    body,
  );
  return response.data;
}

export async function clearExtraWorkInvoiced(body: {
  company: number;
  year: number;
  month: number;
}): Promise<InvoiceRunResult> {
  const response = await api.post<InvoiceRunResult>(
    "/extra-work/clear-invoiced/",
    body,
  );
  return response.data;
}

// M4 (2b) provider-only billing-month override. invoice_date = "YYYY-MM-DD"
// sets the billing month; null reverts to the completion-month default.
export async function updateExtraWorkBilling(
  id: number | string,
  body: { invoice_date: string | null },
): Promise<ExtraWorkRequestDetail> {
  const response = await api.patch<ExtraWorkRequestDetail>(
    `/extra-work/${id}/billing/`,
    body,
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

// Proposal detail — the only response shape that carries the per-record
// `actions` block AND the nested `lines` array (the list endpoint above
// returns the lean `ProposalListSerializer` without either). Fetched
// separately when the EW detail page needs to gate proposal-scoped
// controls (Send / Cancel / Direct Publish / Edit Lines) or render the
// proposal's pricing breakdown read-only.
export async function getProposalDetail(
  ewId: number | string,
  proposalId: number,
): Promise<ProposalDetail> {
  const response = await api.get<ProposalDetail>(
    `/extra-work/${ewId}/proposals/${proposalId}/`,
  );
  return response.data;
}

// Direct-publish — the new atomic endpoint added by backend commit
// fff79c1. Backend (atomic in one transaction):
//   1. DRAFT -> SENT
//   2. SENT -> CUSTOMER_APPROVED as provider override
//   3. Parent EW reaches CUSTOMER_APPROVED
//   4. Operational tickets spawn via the existing post-approval hook
// `override_reason` is REQUIRED — backend returns 400 with stable code
// `override_reason_required` when blank/whitespace. Mirror that check
// in the UI before submitting.
export async function directPublishProposal(
  ewId: number | string,
  proposalId: number,
  payload: { override_reason: string; note?: string },
): Promise<Proposal> {
  const response = await api.post<Proposal>(
    `/extra-work/${ewId}/proposals/${proposalId}/direct-publish/`,
    payload,
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

// ---------------------------------------------------------------------------
// Sprint 31 (frontend) — proposal builder write helpers. Read helpers
// (listProposalsForEw / getProposalDetail) already exist above. On
// create with no `lines`, the backend auto-seeds one ProposalLine per
// cart item, pre-filling contract prices (SoT §8.3); the provider then
// edits the custom lines and sends. All line CRUD is DRAFT-only +
// provider-only (backend-enforced).
// ---------------------------------------------------------------------------

export interface ProposalLineWritePayload {
  // A catalog line (`service` set) or a custom/ad-hoc line. Omitted on
  // PATCH leaves the field unchanged.
  service?: number | null;
  description: string;
  quantity: string;
  unit_type: ExtraWorkUnitType;
  unit_price: string;
  vat_pct: string;
  customer_explanation?: string;
  internal_note?: string;
  is_approved_for_spawn?: boolean;
}

// POST /extra-work/<ew>/proposals/ — provider-only create. With an
// empty body the backend auto-seeds lines from the cart. Returns the
// full ProposalDetail (lines + per-record actions).
export async function createProposal(
  ewId: number | string,
  payload: { lines?: ProposalLineWritePayload[] } = {},
): Promise<ProposalDetail> {
  const response = await api.post<ProposalDetail>(
    `/extra-work/${ewId}/proposals/`,
    payload,
  );
  return response.data;
}

export async function createProposalLine(
  ewId: number | string,
  proposalId: number,
  payload: ProposalLineWritePayload,
): Promise<ProposalLine> {
  const response = await api.post<ProposalLine>(
    `/extra-work/${ewId}/proposals/${proposalId}/lines/`,
    payload,
  );
  return response.data;
}

export async function updateProposalLine(
  ewId: number | string,
  proposalId: number,
  lineId: number,
  payload: Partial<ProposalLineWritePayload>,
): Promise<ProposalLine> {
  const response = await api.patch<ProposalLine>(
    `/extra-work/${ewId}/proposals/${proposalId}/lines/${lineId}/`,
    payload,
  );
  return response.data;
}

export async function deleteProposalLine(
  ewId: number | string,
  proposalId: number,
  lineId: number,
): Promise<void> {
  await api.delete(
    `/extra-work/${ewId}/proposals/${proposalId}/lines/${lineId}/`,
  );
}

// POST /extra-work/<ew>/proposals/<id>/transition/ — DRAFT -> SENT (and
// other proposal transitions). SEND-time preconditions (every custom
// line priced, cart coverage) are validated backend-side.
export async function transitionProposal(
  ewId: number | string,
  proposalId: number,
  payload: {
    to_status: ProposalStatus;
    note?: string;
    // Provider-driven SENT -> CUSTOMER_APPROVED / CUSTOMER_REJECTED is an
    // override: the backend coerces is_override and REQUIRES a non-blank
    // override_reason (400 `override_reason_required`). Customer-driven
    // decisions omit both.
    is_override?: boolean;
    override_reason?: string;
  },
): Promise<Proposal> {
  const response = await api.post<Proposal>(
    `/extra-work/${ewId}/proposals/${proposalId}/transition/`,
    payload,
  );
  return response.data;
}

// ---------------------------------------------------------------------------
// M1 B6 — Extra Work message thread.
// ---------------------------------------------------------------------------
interface CreateEwMessagePayload {
  message: string;
  message_type: EwMessageType;
  directed_to?: number[];
  visibility_mode?: EwMessageVisibility;
}

/** GET /api/extra-work/<id>/messages/ — the chokepoint-filtered thread
 * (flat array, like proposals). */
export async function listEwMessages(
  ewId: number | string,
): Promise<EwMessage[]> {
  const response = await api.get<EwMessage[]>(
    `/extra-work/${ewId}/messages/`,
  );
  return response.data;
}

/** POST /api/extra-work/<id>/messages/ — create a message on the thread. */
export async function createEwMessage(
  ewId: number | string,
  payload: CreateEwMessagePayload,
): Promise<EwMessage> {
  const response = await api.post<EwMessage>(
    `/extra-work/${ewId}/messages/`,
    payload,
  );
  return response.data;
}

/** GET /api/extra-work/<id>/message-recipients/?message_type=<tier> — the
 * side-aware directed_to candidates for the composer picker. */
export async function getEwMessageRecipients(
  ewId: number | string,
  messageType: EwMessageType,
): Promise<EwMessageRecipient[]> {
  const response = await api.get<{ results: EwMessageRecipient[] }>(
    `/extra-work/${ewId}/message-recipients/`,
    { params: { message_type: messageType } },
  );
  return response.data.results;
}


