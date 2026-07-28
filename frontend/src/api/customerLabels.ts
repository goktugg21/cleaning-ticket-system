// Sprint 128 — typed client for the per-customer Extra Work label lists
// (Department + WorkType).
//
// Backend: backend/customers/views_labels.py, mounted under
// /api/customers/<customerId>/departments/ and /work-types/. Provider write
// (SA / CA-own-company); customer users with access + BUILDING_MANAGERs who
// can see the customer READ (to populate the create / relabel dropdowns).
// Coded errors come back as { detail, code } — use `labelErrorCode`.
import axios from "axios";

import { api } from "./client";
import type { CustomerLabel } from "./types";

// The two lists share one shape and one CRUD surface; `kind` selects the
// URL segment so the page + hooks stay DRY (mirrors the backend abstract
// base + shared view mixin).
export type LabelKind = "department" | "work_type";

function segment(kind: LabelKind): string {
  return kind === "department" ? "departments" : "work-types";
}

function base(customerId: number | string, kind: LabelKind): string {
  return `/customers/${customerId}/${segment(kind)}`;
}

export interface ListLabelsParams {
  // The picker requests only active rows; the management page omits this to
  // also show archived rows (so they stay reactivatable).
  is_active?: boolean;
}

export async function listLabels(
  customerId: number | string,
  kind: LabelKind,
  params: ListLabelsParams = {},
): Promise<CustomerLabel[]> {
  const response = await api.get<{ results: CustomerLabel[] }>(
    `${base(customerId, kind)}/`,
    { params },
  );
  return response.data.results;
}

export interface LabelWritePayload {
  name?: string;
  description?: string;
  is_active?: boolean;
}

export async function createLabel(
  customerId: number | string,
  kind: LabelKind,
  payload: LabelWritePayload,
): Promise<CustomerLabel> {
  const response = await api.post<CustomerLabel>(
    `${base(customerId, kind)}/`,
    payload,
  );
  return response.data;
}

export async function updateLabel(
  customerId: number | string,
  kind: LabelKind,
  labelId: number,
  payload: LabelWritePayload,
): Promise<CustomerLabel> {
  const response = await api.patch<CustomerLabel>(
    `${base(customerId, kind)}/${labelId}/`,
    payload,
  );
  return response.data;
}

export async function deleteLabel(
  customerId: number | string,
  kind: LabelKind,
  labelId: number,
): Promise<void> {
  await api.delete(`${base(customerId, kind)}/${labelId}/`);
}

/** The stable `code` from a labels API error ({ detail, code }), or null when
 *  the error is not a coded response. */
export function labelErrorCode(error: unknown): string | null {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data;
    if (data && typeof data === "object" && "code" in data) {
      const code = (data as { code?: unknown }).code;
      if (typeof code === "string") return code;
    }
  }
  return null;
}
