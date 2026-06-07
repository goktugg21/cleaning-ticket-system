/**
 * M1 B3 — topbar notification bell.
 *
 * Sits in the topbar beside the UserMenu. Polls the feed (mount + on
 * navigation + every POLL_MS; NO websockets) and shows an unread badge.
 * Clicking opens a dropdown of the most recent notifications; clicking one
 * marks it read and deep-links to its source. "See all" navigates to the
 * full /notifications page. Mirrors the UserMenu open/close (click-outside +
 * Escape) pattern.
 *
 * M1 B7 — the same poll drives a soft-green toast for notifications that
 * arrive AFTER the tab is open. A high-water-mark (by id) suppresses the
 * existing backlog on first load and guarantees each notification toasts at
 * most once. 1..N new in a single poll surface as individual toasts; a larger
 * burst collapses to one aggregate toast. Real push (WebSocket/SSE) is
 * deferred to the production-deploy phase; the POLL_MS interval is the latency.
 */
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bell } from "lucide-react";
import { formatRelative } from "../lib/intl";
import {
  diffNewNotifications,
  listNotifications,
  markNotificationRead,
  notificationHref,
} from "../api/notifications";
import type { Notification } from "../api/types";
import { useToast } from "./ToastProvider";
import type { ToastInput } from "./ToastProvider";

// Shortened poll (was 60s) so a newly-arrived notification surfaces as a toast
// within ~one interval. Real push is deferred to the production-deploy phase.
const POLL_MS = 15_000;
const PANEL_LIMIT = 8;
// 1..N new in a single poll -> that many individual toasts; strictly above this
// -> one aggregate "N new notifications" toast (never a wall of toasts).
const TOAST_BURST_CAP = 3;
// One-time-per-tab-session guard for the login backlog greeting (B9). Stored in
// sessionStorage so a mid-session reload doesn't re-flood; a fresh tab (new
// login) greets again.
const GREETED_KEY = "cleanops.notifGreeted";

export function NotificationBell() {
  const { t } = useTranslation("common");
  const navigate = useNavigate();
  const location = useLocation();
  const { push } = useToast();
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<Notification[]>([]);
  const [loadingItems, setLoadingItems] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  // B7 live-toast state. lastSeenIdRef is the high-water-mark (max notification
  // id seen so far); initializedRef guards the very first poll so the existing
  // backlog never toasts. Both are refs so they survive effect re-subscribes
  // (navigation) without re-arming or double-firing the toast.
  const lastSeenIdRef = useRef<number | null>(null);
  const initializedRef = useRef<boolean>(false);

  // Mark read (best-effort) + deep-link. Shared by the panel item click AND
  // the B7 toast onClick so the two paths never drift.
  const openNotification = useCallback(
    async (notification: Notification) => {
      setOpen(false);
      if (!notification.is_read) {
        setItems((prev) =>
          prev.map((item) =>
            item.id === notification.id ? { ...item, is_read: true } : item,
          ),
        );
        setUnread((value) => Math.max(0, value - 1));
        try {
          await markNotificationRead(notification.id);
        } catch {
          // Best-effort: the deep-link still navigates.
        }
      }
      const href = notificationHref(notification);
      if (href) navigate(href);
    },
    [navigate],
  );

  // Build the toast content for a notification. Headline = the ticket / EW
  // NAME (falling back to a Ticket-no reference, then a generic label); the
  // message goes on the description line. Shared by BOTH the live poll path
  // and the login backlog so the two never drift.
  const notificationToastInput = useCallback(
    (n: Notification): ToastInput => {
      const name =
        n.ticket_title ||
        n.extra_work_title ||
        (n.ticket_no
          ? t("notifications.toast_ticket_ref", { no: n.ticket_no })
          : "") ||
        t("notifications.toast_new");
      return {
        variant: "success",
        title: name,
        description: n.summary,
        onClick: () => {
          openNotification(n);
        },
      };
    },
    [t, openNotification],
  );

  // Feed poll: refresh on mount, on each navigation, and on a light interval.
  // It yields BOTH the items (badge list + B7 detection) and the unread count.
  // setState lives inside the async closure (not the effect body), so this does
  // not trip react-hooks/set-state-in-effect.
  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const data = await listNotifications();
        if (cancelled) return;
        const feed = data.results;
        const { newItems, maxId } = diffNewNotifications(
          lastSeenIdRef.current,
          feed,
        );
        lastSeenIdRef.current = maxId;
        setUnread(data.unread_count);
        setItems(feed.slice(0, PANEL_LIMIT));
        // First poll establishes the high-water-mark (set above) AND greets
        // with the unread backlog ONCE per tab-session (B9, Option B): a
        // mid-session reload/navigation never re-floods, and because the mark
        // is already set the greeted backlog never re-toasts on later polls.
        if (!initializedRef.current) {
          initializedRef.current = true;
          let greeted = false;
          try {
            greeted = sessionStorage.getItem(GREETED_KEY) === "1";
          } catch {
            // sessionStorage unavailable -> we can't dedupe across reloads, so
            // stay silent rather than risk re-flooding on every load.
            greeted = true;
          }
          if (!greeted && data.unread_count > 0) {
            try {
              sessionStorage.setItem(GREETED_KEY, "1");
            } catch {
              // Best-effort: still show this single greeting.
            }
            const unreadItems = feed.filter((x) => !x.is_read); // newest-first
            const shown = unreadItems.slice(0, TOAST_BURST_CAP);
            shown.forEach((x) => push(notificationToastInput(x)));
            const more = data.unread_count - shown.length;
            if (more > 0) {
              push({
                variant: "success",
                title: t("notifications.toast_unread_more", { count: more }),
                onClick: () => navigate("/notifications"),
              });
            }
          }
          return;
        }
        if (newItems.length === 0) return;
        if (newItems.length <= TOAST_BURST_CAP) {
          for (const n of newItems) {
            push(notificationToastInput(n));
          }
        } else {
          push({
            variant: "success",
            title: t("notifications.toast_many", { count: newItems.length }),
            onClick: () => navigate("/notifications"),
          });
        }
      } catch {
        // Transient — the next tick / navigation retries.
      }
    };
    refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [location.pathname, push, notificationToastInput, navigate, t]);

  // Close on click-outside.
  useEffect(() => {
    if (!open) return;
    function onPointer(event: MouseEvent) {
      const root = wrapRef.current;
      if (root && event.target instanceof Node && !root.contains(event.target)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onPointer);
    return () => document.removeEventListener("mousedown", onPointer);
  }, [open]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  // Load the recent list + refresh the count whenever the panel opens.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    const load = async () => {
      setLoadingItems(true);
      try {
        const data = await listNotifications();
        if (cancelled) return;
        setItems(data.results.slice(0, PANEL_LIMIT));
        setUnread(data.unread_count);
      } catch {
        if (!cancelled) setItems([]);
      } finally {
        if (!cancelled) setLoadingItems(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [open]);

  const seeAll = useCallback(() => {
    setOpen(false);
    navigate("/notifications");
  }, [navigate]);

  const badge = unread > 9 ? "9+" : String(unread);

  return (
    <div className="notif-bell-wrap" ref={wrapRef}>
      <button
        type="button"
        ref={triggerRef}
        className="notif-bell"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={
          unread > 0
            ? t("notifications.bell_aria_unread", { count: unread })
            : t("notifications.bell_aria")
        }
        onClick={() => setOpen((value) => !value)}
        data-testid="topbar-notification-bell"
      >
        <Bell size={18} strokeWidth={2} />
        {unread > 0 && (
          <span className="notif-badge" data-testid="topbar-notification-badge">
            {badge}
          </span>
        )}
      </button>

      {open && (
        <div
          id={panelId}
          role="menu"
          className="notif-panel"
          data-testid="topbar-notification-panel"
        >
          <div className="notif-panel-head">
            <span className="notif-panel-title">{t("notifications.title")}</span>
          </div>
          <div className="notif-panel-body">
            {loadingItems ? (
              <div className="notif-panel-empty">{t("notifications.loading")}</div>
            ) : items.length === 0 ? (
              <div className="notif-panel-empty">{t("notifications.empty")}</div>
            ) : (
              items.map((notification) => (
                <button
                  key={notification.id}
                  type="button"
                  role="menuitem"
                  className={`notif-item${
                    notification.is_read ? "" : " notif-item-unread"
                  }`}
                  onClick={() => openNotification(notification)}
                >
                  <span className="notif-item-main">
                    <span className="notif-item-summary">
                      {notification.summary}
                    </span>
                    <span className="notif-item-meta">
                      {formatRelative(notification.created_at)}
                      {notification.is_directed && (
                        <span className="notif-item-directed">
                          {" · "}
                          {t("notifications.for_you")}
                        </span>
                      )}
                    </span>
                  </span>
                  {!notification.is_read && (
                    <span className="notif-item-dot" aria-hidden="true" />
                  )}
                </button>
              ))
            )}
          </div>
          <button type="button" className="notif-panel-seeall" onClick={seeAll}>
            {t("notifications.see_all")}
          </button>
        </div>
      )}
    </div>
  );
}
