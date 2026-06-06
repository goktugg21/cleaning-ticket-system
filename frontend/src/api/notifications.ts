// M1 — in-app notification client over the B1 feed
// (backend/notifications/views.py) + the B3 directed-recipients endpoint
// (backend/tickets/views.py::TicketMessageRecipientsView). Every feed
// endpoint is recipient-scoped to the caller server-side.
import { api } from "./client";
import type {
  MessageRecipient,
  Notification,
  NotificationListResponse,
  TicketMessageType,
} from "./types";

/** Derive the in-app deep-link route from whichever source the
 * notification carries. ticket -> ticket detail; extra_work -> EW detail
 * (wired for B4; no EW notifications exist yet). Returns null when neither
 * source is set (un-routable). */
export function notificationHref(notification: Notification): string | null {
  if (notification.ticket != null) return `/tickets/${notification.ticket}`;
  if (notification.extra_work != null)
    return `/extra-work/${notification.extra_work}`;
  return null;
}

export async function listNotifications(
  params?: { page?: number },
): Promise<NotificationListResponse> {
  const response = await api.get<NotificationListResponse>("/notifications/", {
    params,
  });
  return response.data;
}

export async function getUnreadCount(): Promise<number> {
  const response = await api.get<{ unread_count: number }>(
    "/notifications/unread-count/",
  );
  return response.data.unread_count;
}

export async function markNotificationRead(id: number): Promise<void> {
  await api.post(`/notifications/${id}/read/`);
}

export async function markAllNotificationsRead(): Promise<number> {
  const response = await api.post<{ updated: number }>(
    "/notifications/read-all/",
  );
  return response.data.updated;
}

export async function getMessageRecipients(
  ticketId: number | string,
  messageType: TicketMessageType,
): Promise<MessageRecipient[]> {
  const response = await api.get<{ results: MessageRecipient[] }>(
    `/tickets/${ticketId}/message-recipients/`,
    { params: { message_type: messageType } },
  );
  return response.data.results;
}
