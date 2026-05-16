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
  ExtraWorkStatus,
  ExtraWorkStatusHistoryEntry,
  PaginatedResponse,
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
