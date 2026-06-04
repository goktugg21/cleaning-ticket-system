// Sprint 14A — unified ticket audit timeline client.
//
// Thin wrapper over GET /api/audit/tickets/<id>/timeline/
// (backend/audit/views_ticket_timeline.py). PROVIDER-AUDIT ONLY: the
// backend's IsTicketAuditConsumer admits SUPER_ADMIN / COMPANY_ADMIN /
// BUILDING_MANAGER and 403s STAFF + CUSTOMER_USER. Callers MUST gate on the
// provider-audit role before invoking this (mirror `isProviderManagementRole`)
// so STAFF / CUSTOMER_USER never trigger a 403 and never see provider-internal
// audit detail. An out-of-scope / unknown ticket returns 404.
import { api } from "./client";
import type { TicketAuditTimeline } from "./types";

export async function getTicketAuditTimeline(
  ticketId: number | string,
): Promise<TicketAuditTimeline> {
  const response = await api.get<TicketAuditTimeline>(
    `/audit/tickets/${ticketId}/timeline/`,
  );
  return response.data;
}
