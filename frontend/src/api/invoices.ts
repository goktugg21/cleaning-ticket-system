// Invoicing Phase 4b — Invoice API helpers.
//
// Thin axios wrappers so the Facturen page + invoice-detail page don't
// carry literal URL strings. Endpoint paths mirror the Phase-4a
// `backend/invoicing/views.py::InvoiceViewSet` 1:1 (mounted at
// `/api/invoices/`; the api client adds the `/api` prefix). Every endpoint
// is provider-operator-gated + tenant-scoped server-side.
import { api } from "./client";
import type {
  CustomerInvoice,
  Invoice,
  InvoiceDueRow,
  InvoiceGranularity,
  InvoiceLine,
  InvoiceStatus,
  PaginatedResponse,
} from "./types";

export interface ListInvoicesParams {
  customer?: number;
  building?: number;
  status?: InvoiceStatus;
  period_year?: number;
  period_month?: number;
  page?: number;
  page_size?: number;
}

export async function listInvoices(
  params: ListInvoicesParams = {},
): Promise<PaginatedResponse<Invoice>> {
  const response = await api.get<PaginatedResponse<Invoice>>("/invoices/", {
    params: { page_size: 100, ...params },
  });
  return response.data;
}

// Sprint 120 — FacturenPage (listInvoices' one caller) never reads `.count`,
// only `.results`-derived data, so a bare array is sufficient; mirrors
// api/extraWork.ts::listAllExtraWork's exhaustive-fetch template (accumulate
// until `next` is null, hard iteration cap so a backend paging bug cannot
// loop forever). Fetch EVERY matching row so the list, its KPI totals, and
// its CSV export never silently truncate at one page.
export async function listAllInvoices(
  params: ListInvoicesParams = {},
): Promise<Invoice[]> {
  const all: Invoice[] = [];
  let page = 1;
  for (let i = 0; i < 100; i++) {
    const response = await api.get<PaginatedResponse<Invoice>>("/invoices/", {
      params: { page_size: 100, ...params, page },
    });
    all.push(...response.data.results);
    if (!response.data.next) break;
    page += 1;
  }
  return all;
}

export async function getInvoice(id: number | string): Promise<Invoice> {
  const response = await api.get<Invoice>(`/invoices/${id}/`);
  return response.data;
}

// GET /api/invoices/due/ — the informational "who's due" list (flat array,
// NOT paginated).
export async function getInvoiceDueList(): Promise<InvoiceDueRow[]> {
  const response = await api.get<InvoiceDueRow[]>("/invoices/due/");
  return response.data;
}

// ---- Sprint 182 §2 — the invoice preview -----------------------------
//
// "If this were cut now, your invoice would be this." Provider-only,
// nothing stored server-side, recomputed on every call, and it NEVER
// carries an invoice number — numbering happens at Send and has to stay
// gapless, so there is no `number` (and no `id`) on these shapes at all.
//
// The types are declared HERE rather than in `api/types.ts` because that
// file belongs to another agent this sprint. Local on purpose; if the
// preview surface outlives this sprint they belong in types.ts.
export interface InvoicePreviewLine {
  extra_work: number;
  description: string;
  line_subtotal: string;
  line_vat: string;
  line_total: string;
}

export interface InvoicePreviewInvoice {
  /** null = addressed to the customer organisation, not to a building. */
  building: number | null;
  building_name: string | null;
  department: number | null;
  work_type: number | null;
  granularity: InvoiceGranularity;
  subtotal_amount: string;
  vat_amount: string;
  total_amount: string;
  line_count: number;
  lines: InvoicePreviewLine[];
}

export interface InvoicePreview {
  customer: number;
  customer_name: string;
  period_year: number;
  period_month: number;
  /** ISO timestamp — a preview is a photograph, not a promise. */
  computed_at: string;
  invoice_count: number;
  /** Sprint 183 §2 — why there is nothing, when there is nothing. The
   *  same diagnosis the /due/ panel carries, from the same server-side
   *  function, so the two screens cannot explain one emptiness two
   *  ways. Optional so an older server still renders. */
  nothing_reason?: {
    reason:
      | "NO_EXTRA_WORK"
      | "NONE_FINISHED"
      | "ALL_INVOICED"
      | "NOT_IN_PERIOD"
      | "NOTHING_TO_EXPLAIN";
    unbilled_count: number;
    finished_count: number;
    invoiced_count: number;
  };
  invoices: InvoicePreviewInvoice[];
}

export interface GetInvoicePreviewParams {
  customer: number;
  year?: number;
  month?: number;
  granularity?: InvoiceGranularity;
}

// GET /api/invoices/preview/ — the planned invoices. Not paginated: the
// response is one customer's plan, which is a handful of rows.
export async function getInvoicePreview(
  params: GetInvoicePreviewParams,
): Promise<InvoicePreview> {
  const response = await api.get<InvoicePreview>("/invoices/preview/", {
    params,
  });
  return response.data;
}

// ---- Sprint 182 §3 — the billing target + split ----------------------
//
// WHO the invoice is addressed to, and HOW FINELY it splits: two
// questions that used to share one dropdown.
//
// Declared and called from here rather than through
// `api/admin.ts::updateCustomer`, whose `CustomerWritePayload` lives in
// `api/types.ts` — another agent's file this sprint. Same endpoint, same
// server-side permission gate (OSIUS-admin on write); only the payload
// type is local.
export type InvoiceBillingTarget = "BUILDING" | "CUSTOMER";
export type InvoiceSplit = "NONE" | "DEPARTMENT_WORK_TYPE";

/** Sprint 183 §1 — the legacy three-value vocabulary the API still
 *  speaks on the wire.
 *
 *  We kept sending `granularity` rather than teaching the generate
 *  endpoint the pair: the endpoint already accepts this field and the
 *  customer serializer already translates a legacy write, so one
 *  translation in one direction is cheaper and lower-risk than a new
 *  request shape. The UI speaks the pair on both screens; only the wire
 *  is legacy. */
export function granularityFor(
  target: InvoiceBillingTarget,
  split: InvoiceSplit,
): InvoiceGranularity {
  if (target === "CUSTOMER") return "CUSTOMER";
  return split === "DEPARTMENT_WORK_TYPE"
    ? "PER_BUILDING_DEPARTMENT_WORK_TYPE"
    : "PER_BUILDING";
}

/** The inverse, for seeding the generate dialog from a saved
 *  granularity when the server predates the pair. */
export function pairForGranularity(granularity: string | null | undefined): {
  target: InvoiceBillingTarget;
  split: InvoiceSplit;
} {
  if (granularity === "PER_BUILDING") {
    return { target: "BUILDING", split: "NONE" };
  }
  if (granularity === "PER_BUILDING_DEPARTMENT_WORK_TYPE") {
    return { target: "BUILDING", split: "DEPARTMENT_WORK_TYPE" };
  }
  return { target: "CUSTOMER", split: "NONE" };
}

export interface CustomerBillingSettingsPayload {
  invoice_day_rule?: string;
  invoice_day_of_month?: number | null;
  invoice_billing_target?: InvoiceBillingTarget;
  invoice_split?: InvoiceSplit;
}

/** The billing fields as the server now returns them. `invoice_
 *  granularity_default` is still serialised but is DERIVED from the pair
 *  and read-only — writing the pair is the only way to change it. */
export interface CustomerBillingSettings {
  invoice_day_rule: string;
  invoice_day_of_month: number | null;
  invoice_billing_target: InvoiceBillingTarget;
  invoice_split: InvoiceSplit;
  invoice_granularity_default: InvoiceGranularity;
}

export async function updateCustomerBillingSettings<T>(
  customerId: number,
  payload: CustomerBillingSettingsPayload,
): Promise<T> {
  const response = await api.patch<T>(`/customers/${customerId}/`, payload);
  return response.data;
}

/** The same plan as a stamped PDF. `download=pdf`, NOT `format=pdf` —
 *  DRF reserves `format` for content negotiation and would 404. */
export async function fetchInvoicePreviewPdf(
  params: GetInvoicePreviewParams,
): Promise<Blob> {
  const response = await api.get("/invoices/preview/", {
    params: { ...params, download: "pdf" },
    responseType: "blob",
  });
  return response.data as Blob;
}

export interface GenerateInvoicesPayload {
  customer: number;
  year: number;
  month: number;
  // Omit to use the customer's billing target + split (resolved
  // server-side per Extra Work row, Sprint 182 §3).
  granularity?: InvoiceGranularity;
}

// POST /api/invoices/generate/ — returns the created DRAFT invoice(s) (201).
export async function generateInvoices(
  payload: GenerateInvoicesPayload,
): Promise<Invoice[]> {
  const response = await api.post<Invoice[]>("/invoices/generate/", payload);
  return response.data;
}

// Lifecycle transitions (provider-operator; server enforces the forward-only
// DRAFT -> ISSUED -> SENT order + SENT immutability). reverse returns a NEW
// negated counter-invoice (201).
export async function issueInvoice(id: number): Promise<Invoice> {
  const response = await api.post<Invoice>(`/invoices/${id}/issue/`);
  return response.data;
}

export async function sendInvoice(id: number): Promise<Invoice> {
  const response = await api.post<Invoice>(`/invoices/${id}/send/`);
  return response.data;
}

// POST /api/invoices/<id>/unissue/ — ISSUED -> DRAFT ("back to concept").
// Numberless under number-at-send, so this strands no gapless number; the
// server rejects a reversal or an already-numbered row (400).
export async function unissueInvoice(id: number): Promise<Invoice> {
  const response = await api.post<Invoice>(`/invoices/${id}/unissue/`);
  return response.data;
}

export async function reverseInvoice(id: number): Promise<Invoice> {
  const response = await api.post<Invoice>(`/invoices/${id}/reverse/`);
  return response.data;
}

// DELETE /api/invoices/<id>/ — soft-delete a DRAFT + release its claimed EW.
export async function deleteDraftInvoice(id: number): Promise<void> {
  await api.delete(`/invoices/${id}/`);
}

// Draft line editing (all DRAFT-only server-side). Money fields are decimal
// strings; omitted keys are left unchanged on PATCH.
export interface InvoiceLineWritePayload {
  description?: string;
  quantity?: string;
  unit_price?: string;
  vat_pct?: string;
  period_year?: number | null;
  period_month?: number | null;
  performed_on?: string | null;
}

export async function addInvoiceLine(
  id: number,
  body: InvoiceLineWritePayload,
): Promise<InvoiceLine> {
  const response = await api.post<InvoiceLine>(`/invoices/${id}/lines/`, body);
  return response.data;
}

export async function updateInvoiceLine(
  id: number,
  lineId: number,
  body: InvoiceLineWritePayload,
): Promise<InvoiceLine> {
  const response = await api.patch<InvoiceLine>(
    `/invoices/${id}/lines/${lineId}/`,
    body,
  );
  return response.data;
}

// DELETE a line — if it is EW-linked the server releases that EW back to
// unbilled.
export async function removeInvoiceLine(
  id: number,
  lineId: number,
): Promise<void> {
  await api.delete(`/invoices/${id}/lines/${lineId}/`);
}

// PATCH /api/invoices/<id>/ — the DRAFT page-1 meta (hand-written summary +
// the optional free-text fee). optional_fee_amount null clears the fee.
export interface InvoiceMetaPayload {
  summary_text?: string;
  optional_fee_label?: string;
  optional_fee_amount?: string | null;
}

export async function updateInvoiceMeta(
  id: number,
  body: InvoiceMetaPayload,
): Promise<Invoice> {
  const response = await api.patch<Invoice>(`/invoices/${id}/`, body);
  return response.data;
}

// GET /api/invoices/<id>/pdf/ — the two-page Dutch PDF as a blob (for an
// inline object-URL preview / download).
export async function fetchInvoicePdf(id: number | string): Promise<Blob> {
  const response = await api.get<Blob>(`/invoices/${id}/pdf/`, {
    responseType: "blob",
  });
  return response.data;
}

// ---------------------------------------------------------------------------
// Phase 5 — the CUSTOMER read helpers (GET /api/invoices/my/...). A
// CUSTOMER_USER's own SENT invoices only; the backend redacts + scopes. The
// list is a flat array (not paginated).
// ---------------------------------------------------------------------------
export async function listMyInvoices(): Promise<CustomerInvoice[]> {
  const response = await api.get<CustomerInvoice[]>("/invoices/my/");
  return response.data;
}

export async function getMyInvoice(
  id: number | string,
): Promise<CustomerInvoice> {
  const response = await api.get<CustomerInvoice>(`/invoices/my/${id}/`);
  return response.data;
}

export async function fetchMyInvoicePdf(id: number | string): Promise<Blob> {
  const response = await api.get<Blob>(`/invoices/my/${id}/pdf/`, {
    responseType: "blob",
  });
  return response.data;
}
