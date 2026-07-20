// Ticket API helpers.
//
// Thin axios wrappers so page components don't carry literal URL
// strings. Endpoint paths mirror `backend/tickets/urls.py` 1:1 and are
// mounted at `/api/tickets/` (the api client adds the `/api` prefix).
import { api } from "./client";
import type {
  PaginatedResponse,
  TicketBulkStatusResponse,
  TicketConvertToExtraWorkPayload,
  TicketConvertToExtraWorkResponse,
  TicketList,
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
