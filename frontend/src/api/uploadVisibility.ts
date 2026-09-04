// W4-P — the two permission scopes for staff photo uploads.
//
// A worker's photo is INTERNAL by default and a provider promotes it one
// at a time. These two permissions are the "stop asking me" switch the
// owner asked for, and they differ ONLY in reach:
//
//   STANDING   — this person's uploads on EVERY ticket. Set on the
//                person's admin page. SUPER_ADMIN / COMPANY_ADMIN only.
//   PER-TICKET — this person's uploads on THIS ticket only. Set on the
//                Assignment card. Provider management with scope on the
//                ticket.
//
// THE RESOLUTION ORDER, which every screen must state the same way:
//
//   per-ticket  >  standing  >  per-work setting  >  default
//   Most specific wins. Any explicit grant makes the photo customer
//   visible. Internal is the default when nothing has been granted.
//
// So a per-ticket "no" beats a standing "yes" for that ticket, and a
// standing "yes" beats the absence of a per-work setting. The server
// resolves it (backend/tickets/attachment_visibility.py) and returns the
// answer in `effective_visibility` / `effective_source` — do NOT
// re-derive it client-side. A second copy of a resolution order is a
// second answer.
//
// `uploads_customer_visible` is a TRI-STATE everywhere it appears:
// true = grant, false = refusal, null = no decision at this scope (the
// next rung down answers). Writing null CLEARS the decision; it is not
// the same as writing false.
//
// Mirrors backend/tickets/views_upload_visibility.py:
//   GET   /api/tickets/upload-visibility/standing/?user_id=<id>
//   PATCH /api/tickets/upload-visibility/standing/<user_id>/
//   GET   /api/tickets/<ticket_id>/upload-visibility/
//   PATCH /api/tickets/<ticket_id>/upload-visibility/<user_id>/
//
// Both PATCH surfaces refuse the actor's OWN user id with 403
// `upload_visibility_self_grant_forbidden`: granting is privileged and
// never self-service.
import { api } from "./client";
import type {
  TicketUploadVisibility,
  TicketUploadVisibilityPerson,
  UploadVisibilityGrantState,
} from "./types";

export async function getStandingUploadVisibility(
  userId: number | string,
): Promise<UploadVisibilityGrantState> {
  const { data } = await api.get<UploadVisibilityGrantState>(
    "/tickets/upload-visibility/standing/",
    { params: { user_id: userId } },
  );
  return data;
}

export async function setStandingUploadVisibility(
  userId: number | string,
  uploadsCustomerVisible: boolean | null,
  reason = "",
): Promise<UploadVisibilityGrantState> {
  const { data } = await api.patch<UploadVisibilityGrantState>(
    `/tickets/upload-visibility/standing/${userId}/`,
    { uploads_customer_visible: uploadsCustomerVisible, reason },
  );
  return data;
}

export async function getTicketUploadVisibility(
  ticketId: number | string,
): Promise<TicketUploadVisibility> {
  const { data } = await api.get<TicketUploadVisibility>(
    `/tickets/${ticketId}/upload-visibility/`,
  );
  return data;
}

export async function setTicketUploadVisibility(
  ticketId: number | string,
  userId: number | string,
  uploadsCustomerVisible: boolean | null,
  reason = "",
): Promise<TicketUploadVisibilityPerson> {
  const { data } = await api.patch<TicketUploadVisibilityPerson>(
    `/tickets/${ticketId}/upload-visibility/${userId}/`,
    { uploads_customer_visible: uploadsCustomerVisible, reason },
  );
  return data;
}
