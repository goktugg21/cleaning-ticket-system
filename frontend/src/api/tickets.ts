// Ticket API helpers.
//
// Thin axios wrappers so page components don't carry literal URL
// strings. Endpoint paths mirror `backend/tickets/urls.py` 1:1 and are
// mounted at `/api/tickets/` (the api client adds the `/api` prefix).
import { api } from "./client";
import type {
  TicketConvertToExtraWorkPayload,
  TicketConvertToExtraWorkResponse,
} from "./types";

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
