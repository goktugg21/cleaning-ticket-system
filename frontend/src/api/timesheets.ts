// Sprint 152 — client for the employee-hours module
// (`backend/timesheets/`). Its own file rather than an extension of
// `admin.ts`: the module is independent on the backend and the frontend
// mirrors that, so nothing here reaches into ticket / extra-work
// clients and nothing there needs to reach in here.

import { api } from "./client";
import type { PaginatedResponse } from "./types";
import type {
  ContractHoursPattern,
  HourType,
  HourTypeWritePayload,
  StandardSetResult,
  TimeEntry,
  TimeEntryFilters,
  TimeEntryWritePayload,
  TimesheetEmployee,
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
// Employees (the admin entry form's picker)
// ---------------------------------------------------------------------------

/**
 * The employees hours may be filed against, for ONE provider company.
 *
 * NOT `listProviderEmployees` from `admin.ts`: that endpoint takes no
 * company and returns no company either, so for a SUPER_ADMIN it mixes
 * tenants into one dropdown where every wrong pick 400s. This one
 * resolves through the same helper the write path validates against, so
 * everything it offers is accepted.
 *
 * `UnboundedPagination` server-side — a company's workforce is bounded
 * by domain reality — so the flat array is returned and the caller
 * never pages.
 */
export async function listTimesheetEmployees(
  company?: number | "",
): Promise<TimesheetEmployee[]> {
  const response = await api.get<PaginatedResponse<TimesheetEmployee>>(
    "/timesheets/employees/",
    { params: cleanParams({ company }) },
  );
  return response.data.results;
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

/**
 * Sprint 154 §M — save a whole week of hours in ONE request.
 *
 * All-or-nothing on the server: one invalid cell rolls the entire week
 * back, so there is no partial-success shape to handle here. A closed
 * week refuses the whole grid with the server's own `week_closed`
 * message, which the caller surfaces verbatim.
 *
 * `hours: "0"` CLEARS a cell (deletes the row). A cell the grid does not
 * send is left untouched, so saving a filtered view can never wipe rows
 * the operator could not see.
 */
export async function saveWeekGrid(payload: {
  /** The DEFAULT employee for cells that omit one. Sprint 154 sent only
   *  this; Sprint 155 sends it per cell so one request can file several
   *  people's weeks. Both shapes are accepted by the endpoint. */
  employee?: number | null;
  company?: number | null;
  iso_year: number;
  iso_week: number;
  cells: {
    employee?: number | null;
    hour_type: number;
    building?: number | null;
    date: string;
    hours: string;
    /** Sprint 180 §3 — the same hole as `TimeEntryWritePayload`, on the
     *  bulk path. The grid has attached a job to every cell it sends
     *  since Sprint 177 §7 (`GridCell.source_type` / `source_id`), and
     *  since Sprint 179B the endpoint keys a row on that pair — but
     *  this wire type never mentioned it, so the one place that
     *  documents what `bulk-week` accepts was missing the field that
     *  decides WHICH row a cell addresses. Optional, because an
     *  untagged cell omits both keys entirely and the endpoint reads
     *  key presence. */
    source_type?: string;
    source_id?: number | null;
  }[];
}): Promise<{ created: number; updated: number; deleted: number }> {
  const response = await api.post<{
    created: number;
    updated: number;
    deleted: number;
  }>("/timesheets/entries/bulk-week/", payload);
  return response.data;
}

// ---------------------------------------------------------------------------
// Week locks
// ---------------------------------------------------------------------------

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

/** W10 — materialise one week from the standing agreements.
 *
 *  Idempotent, so the week view calls it every time a week is opened:
 *  that is what makes a sheet arrive filled without anybody pressing
 *  anything. The rules (validity window, closed weeks, and never
 *  touching a week somebody has already worked in) live on the server.
 */
export async function fillWeekFromContracts(payload: {
  iso_year: number;
  iso_week: number;
  company?: number | "";
  /** W12 — fill ONE person's week. A manager may name anybody; for
   *  everybody else the server ignores this and uses the caller, so
   *  **My hours** simply omits it. */
  employee?: number | "";
}): Promise<{ created: number; skipped_existing: number }> {
  const response = await api.post("/timesheets/entries/fill-week/", cleanParams(payload));
  return response.data;
}

/**
 * W12 §5 — this employee's standing agreements in force during a date
 * window.
 *
 * `employee` is a filter, not a permission: the endpoint restricts a
 * non-manager to their own rows regardless of what is asked for, so
 * this cannot be turned into a way to read a colleague's contract by
 * changing one number in the request.
 */
export async function listContractHoursPatterns(params: {
  employee: number;
  valid_between_start: string;
  valid_between_end: string;
}): Promise<ContractHoursPattern[]> {
  const response = await api.get<{ results: ContractHoursPattern[] }>(
    "/timesheets/contract-hours/",
    { params: cleanParams(params) },
  );
  return response.data.results ?? [];
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
