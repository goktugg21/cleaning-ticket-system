// Ticket "Responsible managers" — the per-ticket M:N TicketManagerAssignment
// surface (distinct from the single ticket.assigned_to primary pointer).
// Mirrors backend/tickets/views_manager_assignments.py:
//   GET    /api/tickets/<id>/manager-assignments/            list (paginated)
//   POST   /api/tickets/<id>/manager-assignments/            {user_ids:[...]} -> add
//   DELETE /api/tickets/<id>/manager-assignments/<user_id>/  remove
//
// PROVIDER-MANAGEMENT ONLY: the backend admits SUPER_ADMIN / COMPANY_ADMIN /
// BUILDING_MANAGER holding the building's `osius.ticket.assign_staff` and
// 403s STAFF + CUSTOMER_USER (even on LIST). Callers MUST gate on the
// provider-management role and treat a LIST 403 as "hide the section".
import { api } from "./client";
import type { PaginatedResponse } from "./types";

export interface TicketManagerAssignment {
  id: number;
  ticket: number;
  user_id: number;
  user_email: string;
  user_full_name: string;
  assigned_by_id: number | null;
  assigned_by_email: string | null;
  assigned_at: string;
}

export async function listManagerAssignments(
  ticketId: number | string,
): Promise<TicketManagerAssignment[]> {
  const response = await api.get<PaginatedResponse<TicketManagerAssignment>>(
    `/tickets/${ticketId}/manager-assignments/`,
  );
  return response.data.results;
}

// Add one or more responsible managers in a single all-or-nothing POST.
// The caller refetches the list afterwards rather than relying on the
// response shape.
export async function addManagerAssignments(
  ticketId: number | string,
  userIds: number[],
): Promise<void> {
  await api.post(`/tickets/${ticketId}/manager-assignments/`, {
    user_ids: userIds,
  });
}

export async function removeManagerAssignment(
  ticketId: number | string,
  userId: number,
): Promise<void> {
  await api.delete(`/tickets/${ticketId}/manager-assignments/${userId}/`);
}
