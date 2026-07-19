// RF-1 — message inbox API client.
import { api } from "./client";
import type { InboxFilters, InboxResponse, InboxThreadKind } from "./types";

export async function listInbox(
  filters: InboxFilters = {},
): Promise<InboxResponse> {
  const params: Record<string, string | number> = {};
  if (filters.kind) params.kind = filters.kind;
  if (filters.date_from) params.date_from = filters.date_from;
  if (filters.date_to) params.date_to = filters.date_to;
  if (filters.q) params.q = filters.q;
  if (filters.unread_only) params.unread_only = "1";
  if (filters.offset != null) params.offset = filters.offset;
  if (filters.page_size != null) params.page_size = filters.page_size;
  const response = await api.get<InboxResponse>("/inbox/", { params });
  return response.data;
}

export async function getInboxUnreadCount(): Promise<number> {
  const response = await api.get<{ unread_count: number }>(
    "/inbox/unread-count/",
  );
  return response.data.unread_count;
}

export async function markThreadRead(
  kind: InboxThreadKind,
  id: number,
): Promise<number> {
  const response = await api.post<{ unread_count: number }>("/inbox/mark-read/", {
    kind,
    id,
  });
  return response.data.unread_count;
}

// IA 2026-06-25 — mark every currently-visible thread read. Returns the
// (now zero) global unread count.
export async function markAllThreadsRead(): Promise<number> {
  const response = await api.post<{ unread_count: number }>(
    "/inbox/mark-all-read/",
  );
  return response.data.unread_count;
}

// RF-1 — a decoupled "the inbox unread count may have changed" signal.
// The sidebar badge listens for this and refreshes immediately, so a
// mark-read on a detail page updates the badge without a shared store.
export const INBOX_UNREAD_EVENT = "inbox-unread-refresh";

export function notifyInboxUnreadChanged(): void {
  window.dispatchEvent(new Event(INBOX_UNREAD_EVENT));
}
