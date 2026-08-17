// Ticket API helpers.
//
// Thin axios wrappers so page components don't carry literal URL
// strings. Endpoint paths mirror `backend/tickets/urls.py` 1:1 and are
// mounted at `/api/tickets/` (the api client adds the `/api` prefix).
import { api } from "./client";
import type {
  AssignmentCandidate,
  ExtraWorkBulkAssignResult,
  PaginatedResponse,
  TicketBulkStatusResponse,
  TicketConvertToExtraWorkPayload,
  TicketConvertToExtraWorkResponse,
  TicketDetail,
  TicketList,
  WorkCategory,
} from "./types";

// M6.1 (frontend) — provider customer-detail ticket lists. The backend
// `TicketFilter` supports `customer` (exact), `type` (exact/`in`), and
// `exclude_type` (CSV); scope is still enforced server-side via
// `scope_tickets_for`. The customer-detail sub-tabs pass:
//   * tickets:   { customer, exclude_type: "REPORT" }
//   * meldingen: { customer, type: "REPORT" }
export interface ListTicketsParams {
  customer?: number;
  type?: string;
  /** Sprint 185 E §1 — narrow to one KIND OF WORK. The filter is the
   *  whole point of the catalog: a taxonomy whose values do not reach
   *  the filters is a dropdown. */
  category?: number;
  exclude_type?: string;
  // Sprint 111 — building-manager "My tickets": narrows to tickets the
  // caller MANAGES (union of the legacy `Ticket.assigned_to` FK and the
  // responsible-manager `TicketManagerAssignment` M:N). Backend filter:
  // `tickets/filters.py::TicketFilter.my_managed`. Runs on top of
  // `scope_tickets_for`, so it can only narrow within the caller's scope.
  my_managed?: boolean;
}

// M6.1 + M6 review — provider customer-detail ticket lists. Drill-in
// surface: gather EVERY matching row (following `next`) so the table and
// its count never silently truncate at one page. Bounded to avoid an
// unbounded loop on a malformed `next`.
const MAX_PAGES = 100;

export async function listAllTickets(
  params: ListTicketsParams = {},
): Promise<TicketList[]> {
  const all: TicketList[] = [];
  let page = 1;
  for (let i = 0; i < MAX_PAGES; i++) {
    const response = await api.get<PaginatedResponse<TicketList>>("/tickets/", {
      params: { page_size: 100, ...params, page },
    });
    all.push(...response.data.results);
    if (!response.data.next) break;
    page += 1;
  }
  return all;
}

// Sprint 7B (frontend) — convert a normal ticket into a NEW Extra Work
// request. This is a DEDICATED endpoint, NOT a status transition: the
// backend supersedes the source ticket to CONVERTED_TO_EXTRA_WORK AND
// creates an ExtraWorkRequest in one atomic operation. Posting
// `CONVERTED_TO_EXTRA_WORK` to the generic /status/ endpoint would only
// flip the status without ever creating the request, so the convert
// surface must always go through here.
//
// Provider-only (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER) +
// convertible status (OPEN / IN_PROGRESS / REOPENED_BY_ADMIN); the
// backend enforces both and returns stable `code` fields on 4xx
// (`conversion_forbidden_for_role`, `conversion_forbidden_scope`,
// `ticket_already_converted`, `ticket_not_convertible`).
export async function convertTicketToExtraWork(
  ticketId: number | string,
  payload: TicketConvertToExtraWorkPayload,
): Promise<TicketConvertToExtraWorkResponse> {
  const response = await api.post<TicketConvertToExtraWorkResponse>(
    `/tickets/${ticketId}/convert-to-extra-work/`,
    payload,
  );
  return response.data;
}

// Sprint 7 (frontend) — bulk manager-confirm. Provider management
// advances many WAITING_MANAGER_REVIEW tickets to
// WAITING_CUSTOMER_APPROVAL in one call. The backend
// (`TicketViewSet.bulk_status`) applies PER-ITEM semantics: it always
// returns HTTP 200 with a succeeded/failed breakdown, so the caller
// inspects `failed` rather than relying on the HTTP status. v1 fixes
// the target at WAITING_CUSTOMER_APPROVAL (the only permitted bulk leg).
export async function bulkConfirmTickets(
  ticketIds: number[],
): Promise<TicketBulkStatusResponse> {
  const response = await api.post<TicketBulkStatusResponse>(
    "/tickets/bulk-status/",
    { ticket_ids: ticketIds, to_status: "WAITING_CUSTOMER_APPROVAL" },
  );
  return response.data;
}

// ---- Sprint 158/159 — people on a ticket ------------------------------

/** The people who may be assigned to THIS ticket in THIS role, from the
 *  server's own eligibility helper (`buildings.assignment_eligibility`).
 *
 *  Deliberately not "the company's employees": eligibility comes from
 *  the ticket's BUILDING and differs per role, and the picker must call
 *  the same helper the write validator uses or it will offer options
 *  that always fail (Sprint 152.1 §1a). */
export async function listTicketAssignmentCandidates(
  ticketId: number,
  role: "WORKER" | "MANAGER",
): Promise<AssignmentCandidate[]> {
  const response = await api.get<AssignmentCandidate[]>(
    `/tickets/${ticketId}/assignments/candidates/`,
    { params: { role } },
  );
  return response.data;
}

/** Sprint 159 §2 — assign managers AND workers to many tickets in ONE
 *  call. All-or-nothing server-side across BOTH roles: an ineligible
 *  manager rejects the workers with it, so there is no half-staffed
 *  state for the caller to reconcile. */
export async function bulkAssignTickets(payload: {
  tickets: number[];
  managers?: number[];
  workers?: number[];
  mode?: "assign" | "unassign";
}): Promise<ExtraWorkBulkAssignResult> {
  const response = await api.post<ExtraWorkBulkAssignResult>(
    "/tickets/bulk-assign/",
    payload,
  );
  return response.data;
}

// ---------------------------------------------------------------------------
// Sprint 185 E §1 — the work-category catalog, and one melding's category
// ---------------------------------------------------------------------------

/** Every work category this actor may see, newest catalog shape.
 *
 *  `is_active` narrows to the ones still OFFERABLE, which is what a
 *  picker wants; the meldingen FILTER deliberately asks for all of them,
 *  because an archived category still has last month's meldingen on it
 *  and they must stay findable. */
export async function listWorkCategories(params?: {
  company?: number | "";
  is_active?: "true" | "false";
}): Promise<WorkCategory[]> {
  const response = await api.get<{ results: WorkCategory[] }>(
    "/tickets/categories/",
    { params },
  );
  return response.data.results;
}

/** Set or CLEAR one melding's category.
 *
 *  `null` clears it and is a real edit — "this was tagged wrong" has to
 *  be expressible or the first mistake is permanent. A dedicated action
 *  rather than a PATCH on the ticket because the ticket viewset carries
 *  no update mixin: every single-field ticket edit in this system is its
 *  own endpoint. */
export async function setTicketCategory(
  ticketId: number,
  categoryId: number | null,
): Promise<TicketDetail> {
  const response = await api.patch<TicketDetail>(
    `/tickets/${ticketId}/category/`,
    { category: categoryId },
  );
  return response.data;
}
