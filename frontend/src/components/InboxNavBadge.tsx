// RF-1 — the sidebar "Berichten" unread badge.
//
// Mirrors the NotificationBell cadence: refresh on mount, on every
// navigation, and every 15s; plus an immediate refresh whenever a
// mark-read fires the INBOX_UNREAD_EVENT (from the inbox or a detail
// page). All setState runs inside an async function, never synchronously
// in the effect body.
import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";

import { getInboxUnreadCount, INBOX_UNREAD_EVENT } from "../api/inbox";

const POLL_MS = 15_000;

export function InboxNavBadge() {
  const [count, setCount] = useState(0);
  const location = useLocation();

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const next = await getInboxUnreadCount();
        if (!cancelled) setCount(next);
      } catch {
        // Silent — a transient failure must not break the sidebar.
      }
    }
    void refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    const onEvent = () => {
      void refresh();
    };
    window.addEventListener(INBOX_UNREAD_EVENT, onEvent);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener(INBOX_UNREAD_EVENT, onEvent);
    };
  }, [location.pathname]);

  if (count <= 0) return null;
  return <span className="nav-badge">{count > 9 ? "9+" : count}</span>;
}
