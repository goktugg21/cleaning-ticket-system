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

/**
 * Pure high-water-mark diff for the B7 live toast. `items` is the feed page
 * (newest-first). Returns the notifications strictly newer than `prevMaxId`
 * (newest-first) plus the new high-water-mark.
 *
 * - `maxId` = the greatest id across `items`, never regressing below
 *   `prevMaxId` (monotonic). Falls back to `prevMaxId` when `items` is empty.
 * - When `prevMaxId` is null (first load) `newItems` is empty: the existing
 *   backlog must never toast — the first poll only establishes the mark.
 *
 * Notification ids are monotonic PKs, so id ordering == arrival ordering.
 * Pure (no React) so it is unit-testable in isolation.
 */
export function diffNewNotifications(
  prevMaxId: number | null,
  items: Notification[],
): { newItems: Notification[]; maxId: number | null } {
  const maxId = items.reduce<number | null>(
    (acc, item) => (acc === null || item.id > acc ? item.id : acc),
    prevMaxId,
  );
  const newItems =
    prevMaxId === null ? [] : items.filter((item) => item.id > prevMaxId);
  return { newItems, maxId };
}

export async function listNotifications(
  // #109 Part D — `company` switches the feed into the SA-only
  // view-as-company mode (deduplicated per event, view-only). The
  // backend ignores the param for non-SA callers.
  params?: { page?: number; company?: number },
): Promise<NotificationListResponse> {
  const response = await api.get<NotificationListResponse>("/notifications/", {
    params,
  });
  return response.data;
}

// #109 Part D — SA-only per-company subscription state. Sprint 122 (Part C)
// adds emailEnabledIds: the SUBSET of subscribedIds where the caller also
// opted into email (a company can only be in emailEnabledIds if it is also
// in subscribedIds — email_enabled lives on the same subscription row).
export interface CompanySubscriptionState {
  subscribedIds: number[];
  emailEnabledIds: number[];
}

export async function getCompanySubscriptions(): Promise<CompanySubscriptionState> {
  const response = await api.get<{
    subscribed_company_ids: number[];
    email_enabled_company_ids: number[];
  }>("/notifications/company-subscriptions/");
  return {
    subscribedIds: response.data.subscribed_company_ids,
    emailEnabledIds: response.data.email_enabled_company_ids,
  };
}

export async function setCompanySubscription(
  companyId: number,
  subscribed: boolean,
): Promise<void> {
  if (subscribed) {
    await api.put(`/notifications/company-subscriptions/${companyId}/`);
  } else {
    await api.delete(`/notifications/company-subscriptions/${companyId}/`);
  }
}

// Sprint 122 (Part C) — the SEPARATE email opt-in for the same per-company
// subscription row (subscribing in-app does not imply this). Requires an
// existing subscription; toggle it from the SA settings UI alongside the
// subscribe Toggle, never standalone.
export async function setCompanyEmailSubscription(
  companyId: number,
  emailEnabled: boolean,
): Promise<void> {
  await api.put(`/notifications/company-subscriptions/${companyId}/`, {
    email_enabled: emailEnabled,
  });
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
