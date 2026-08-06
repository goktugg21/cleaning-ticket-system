// Sprint 152 — client for the employee-hours module
// (`backend/timesheets/`). Its own file rather than an extension of
// `admin.ts`: the module is independent on the backend and the frontend
// mirrors that, so nothing here reaches into ticket / extra-work
// clients and nothing there needs to reach in here.

import { api } from "./client";
import type { PaginatedResponse } from "./types";
import type {
  HourType,
  HourTypeWritePayload,
  StandardSetResult,
  TimeEntry,
  TimeEntryFilters,
  TimeEntryWritePayload,
  TimesheetSummary,
  WeekLock,
  WeekStatus,
} from "./timesheets.types";

/**
 * Drop empty / undefined params so an unset filter is ABSENT from the
 * query string rather than sent as `""`. The backend's
 * `parse_int_param` treats "" as absent too, so this is belt and
 * braces — but it also keeps the URLs readable in the network tab,
 * which is where a filter bug is diagnosed.
 */
// Generic over the caller's own filter INTERFACE rather than typed as
// `Record<string, ...>`: an interface has no index signature, so it is
// not assignable to a Record parameter and every call site would need a
// cast. `T extends object` accepts the interfaces directly and keeps
// them checked at their own declarations, which is where a typo in a
// filter name should be caught.
function cleanParams<T extends object>(params: T): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    out[key] = String(value);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Hour types
// ---------------------------------------------------------------------------

export interface HourTypeListParams {
  company?: number | "";
  is_active?: boolean;
}

/**
 * The hour-type list is `UnboundedPagination` server-side (a company's
 * hour types are a handful of rows by domain reality), so this returns
 * the flat array and the caller never pages. Same shape as
 * `listManagedUnits`.
 */
export async function listHourTypes(
  params: HourTypeListParams = {},
): Promise<HourType[]> {
  const response = await api.get<PaginatedResponse<HourType>>(
    "/timesheets/hour-types/",
    { params: cleanParams(params) },
  );
  return response.data.results;
}

export async function createHourType(
  payload: HourTypeWritePayload,
): Promise<HourType> {
  const response = await api.post<HourType>(
    "/timesheets/hour-types/",
    payload,
  );
  return response.data;
}

export async function updateHourType(
  id: number,
  payload: Partial<HourTypeWritePayload>,
): Promise<HourType> {
  const response = await api.patch<HourType>(
    `/timesheets/hour-types/${id}/`,
    payload,
  );
  return response.data;
}

export async function deleteHourType(id: number): Promise<void> {
  await api.delete(`/timesheets/hour-types/${id}/`);
}

/**
 * Create the standard Dutch six, skipping names the company already
 * has. Idempotent server-side, so a double click adds nothing the
 * second time — the response says how many were created vs skipped so
 * the UI can report which of the two actually happened.
 */
export async function addStandardHourTypes(
  company?: number | "",
): Promise<StandardSetResult> {
  const response = await api.post<StandardSetResult>(
    "/timesheets/hour-types/standard-set/",
    company === "" || company === undefined ? {} : { company },
  );
  return response.data;
}

// ---------------------------------------------------------------------------
// Time entries
// ---------------------------------------------------------------------------

/**
 * Paginated (`StandardResultsSetPagination`) — a year of one company's
 * hours is tens of thousands of rows, so the full response shape is
 * returned and the admin table drives real prev/next off it.
 */
export async function listTimeEntries(
  filters: TimeEntryFilters = {},
): Promise<PaginatedResponse<TimeEntry>> {
  const response = await api.get<PaginatedResponse<TimeEntry>>(
    "/timesheets/entries/",
    { params: cleanParams(filters) },
  );
  return response.data;
}

export async function createTimeEntry(
  payload: TimeEntryWritePayload,
): Promise<TimeEntry> {
  const response = await api.post<TimeEntry>("/timesheets/entries/", payload);
  return response.data;
}

export async function updateTimeEntry(
  id: number,
  payload: Partial<TimeEntryWritePayload>,
): Promise<TimeEntry> {
  const response = await api.patch<TimeEntry>(
    `/timesheets/entries/${id}/`,
    payload,
  );
  return response.data;
}

export async function deleteTimeEntry(id: number): Promise<void> {
  await api.delete(`/timesheets/entries/${id}/`);
}

// ---------------------------------------------------------------------------
// Week locks
// ---------------------------------------------------------------------------

export async function listWeekLocks(params: {
  company?: number | "";
  iso_year?: number;
}): Promise<WeekLock[]> {
  const response = await api.get<PaginatedResponse<WeekLock>>(
    "/timesheets/weeks/",
    { params: cleanParams(params) },
  );
  return response.data.results;
}

/**
 * Ask about ONE week. The list cannot answer this: absence of a lock
 * row means OPEN, so an empty week appears in neither collection and a
 * week picker needs a definite answer on every navigation.
 */
export async function fetchWeekStatus(params: {
  iso_year: number;
  iso_week: number;
  company?: number | "";
}): Promise<WeekStatus> {
  const response = await api.get<WeekStatus>("/timesheets/weeks/status/", {
    params: cleanParams(params),
  });
  return response.data;
}

export async function closeWeek(payload: {
  iso_year: number;
  iso_week: number;
  company?: number | "";
}): Promise<WeekLock> {
  const response = await api.post<WeekLock>("/timesheets/weeks/close/", {
    iso_year: payload.iso_year,
    iso_week: payload.iso_week,
    ...(payload.company === "" || payload.company === undefined
      ? {}
      : { company: payload.company }),
  });
  return response.data;
}

export async function reopenWeek(payload: {
  iso_year: number;
  iso_week: number;
  company?: number | "";
}): Promise<void> {
  await api.post("/timesheets/weeks/reopen/", {
    iso_year: payload.iso_year,
    iso_week: payload.iso_week,
    ...(payload.company === "" || payload.company === undefined
      ? {}
      : { company: payload.company }),
  });
}

// ---------------------------------------------------------------------------
// Summary + export
// ---------------------------------------------------------------------------

export async function fetchTimesheetSummary(
  filters: TimeEntryFilters = {},
): Promise<TimesheetSummary> {
  const response = await api.get<TimesheetSummary>("/timesheets/summary/", {
    params: cleanParams(filters),
  });
  return response.data;
}

/**
 * Download the summary as CSV. Same filters as the JSON fetch and the
 * entries list, so the file and the screen always describe the same
 * set. Mirrors `reports.ts::downloadDimensionExport` — including
 * reading the filename back out of Content-Disposition rather than
 * re-deriving it client-side, so the server owns the name.
 */
export async function downloadTimesheetSummaryCsv(
  filters: TimeEntryFilters = {},
): Promise<void> {
  const response = await api.get("/timesheets/summary/export.csv", {
    params: cleanParams(filters),
    responseType: "blob",
  });
  const contentDisposition = response.headers["content-disposition"] ?? "";
  const match = /filename="?([^"]+)"?/i.exec(contentDisposition);
  const filename = match ? match[1] : "employee-hours.csv";
  const blobUrl = window.URL.createObjectURL(response.data as Blob);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(blobUrl);
}
