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

export interface GenerateInvoicesPayload {
  customer: number;
  year: number;
  month: number;
  // Omit to use the customer's invoice_granularity_default (server-side).
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
