// Sprint 11/12 frontend — planned / recurring work API helpers.
//
// Thin axios wrappers over `/api/planned-work/` so page components carry
// no literal URL strings. Endpoint paths mirror
// `backend/planned_work/urls.py` 1:1 (the api client adds the `/api`
// prefix). Provider-only surface; the backend viewsets 403 STAFF /
// CUSTOMER_USER on every method.
import { api } from "./client";
import type { PaginatedResponse } from "./types";
import type {
  GenerateOccurrencesResult,
  ListPlannedOccurrencesParams,
  ListRecurringJobsParams,
  PlannedOccurrence,
  PlannedOccurrenceOverridePayload,
  RecurringJob,
  RecurringJobWritePayload,
} from "./plannedWork.types";

const JOBS_URL = "/planned-work/recurring-jobs/";
const OCCURRENCES_URL = "/planned-work/planned-occurrences/";

function cleanParams(
  input: Record<string, string | number | undefined>,
): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  for (const [key, value] of Object.entries(input)) {
    if (value === undefined || value === null || value === "") continue;
    out[key] = value;
  }
  return out;
}

// ---- RecurringJob ---------------------------------------------------------

// The list viewset does NOT filter server-side (no filterset_fields); the
// active/archived + scope narrowing happens client-side. We pull a
// generous page so a tenant's job set lands in one request.
export async function listRecurringJobs(
  params: ListRecurringJobsParams = {},
): Promise<PaginatedResponse<RecurringJob>> {
  const response = await api.get<PaginatedResponse<RecurringJob>>(JOBS_URL, {
    params: cleanParams({ page_size: 200, ...params }),
  });
  return response.data;
}

export async function getRecurringJob(
  id: number | string,
): Promise<RecurringJob> {
  const response = await api.get<RecurringJob>(`${JOBS_URL}${id}/`);
  return response.data;
}

// POST create. The backend serializes the response with the WRITE
// serializer (no `id`), so this returns void — callers navigate to the
// list and let it re-fetch the full read rows.
export async function createRecurringJob(
  payload: RecurringJobWritePayload,
): Promise<void> {
  await api.post(JOBS_URL, payload);
}

// PATCH update, then GET so the caller always receives a full read object
// (the PATCH response is the partial write-serializer shape).
export async function updateRecurringJob(
  id: number | string,
  payload: Partial<RecurringJobWritePayload>,
): Promise<RecurringJob> {
  await api.patch(`${JOBS_URL}${id}/`, payload);
  return getRecurringJob(id);
}

// DELETE = soft-archive (204). Prefer `archiveRecurringJob` when the UI
// wants the updated row back.
export async function deleteRecurringJob(id: number | string): Promise<void> {
  await api.delete(`${JOBS_URL}${id}/`);
}

export async function archiveRecurringJob(
  id: number | string,
): Promise<RecurringJob> {
  const response = await api.post<RecurringJob>(`${JOBS_URL}${id}/archive/`);
  return response.data;
}

export async function unarchiveRecurringJob(
  id: number | string,
): Promise<RecurringJob> {
  const response = await api.post<RecurringJob>(`${JOBS_URL}${id}/unarchive/`);
  return response.data;
}

// POST generate. `days_ahead` defaults to 14 server-side (max 365).
export async function generateOccurrences(
  id: number | string,
  daysAhead?: number,
): Promise<GenerateOccurrencesResult> {
  const body = daysAhead === undefined ? {} : { days_ahead: daysAhead };
  const response = await api.post<GenerateOccurrencesResult>(
    `${JOBS_URL}${id}/generate/`,
    body,
  );
  return response.data;
}

// ---- PlannedOccurrence ----------------------------------------------------

export async function listPlannedOccurrences(
  params: ListPlannedOccurrencesParams = {},
): Promise<PaginatedResponse<PlannedOccurrence>> {
  const response = await api.get<PaginatedResponse<PlannedOccurrence>>(
    OCCURRENCES_URL,
    { params: cleanParams({ page_size: 200, ...params }) },
  );
  return response.data;
}

export async function getPlannedOccurrence(
  id: number | string,
): Promise<PlannedOccurrence> {
  const response = await api.get<PlannedOccurrence>(`${OCCURRENCES_URL}${id}/`);
  return response.data;
}

export async function skipOccurrence(
  id: number | string,
  reason: string,
): Promise<PlannedOccurrence> {
  const response = await api.post<PlannedOccurrence>(
    `${OCCURRENCES_URL}${id}/skip/`,
    { reason },
  );
  return response.data;
}

export async function cancelOccurrence(
  id: number | string,
  reason: string,
): Promise<PlannedOccurrence> {
  const response = await api.post<PlannedOccurrence>(
    `${OCCURRENCES_URL}${id}/cancel/`,
    { reason },
  );
  return response.data;
}

export async function overrideOccurrence(
  id: number | string,
  payload: PlannedOccurrenceOverridePayload,
): Promise<PlannedOccurrence> {
  const response = await api.patch<PlannedOccurrence>(
    `${OCCURRENCES_URL}${id}/override/`,
    payload,
  );
  return response.data;
}
