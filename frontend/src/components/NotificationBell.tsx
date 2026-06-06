/**
 * M1 B3 — topbar notification bell.
 *
 * Sits in the topbar beside the UserMenu. Polls the unread count
 * (mount + 60s interval + on navigation; NO websockets) and shows a
 * badge. Clicking opens a dropdown of the most recent notifications;
 * clicking one marks it read and deep-links to its source. "See all"
 * navigates to the full /notifications page. Mirrors the UserMenu
 * open/close (click-outside + Escape) pattern.
 */
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Bell } from "lucide-react";
import { formatRelative } from "../lib/intl";
import {
  getUnreadCount,
  listNotifications,
  markNotificationRead,
  notificationHref,
} from "../api/notifications";
import type { Notification } from "../api/types";

const POLL_MS = 60_000;
const PANEL_LIMIT = 8;

export function NotificationBell() {
  const { t } = useTranslation("common");
  const navigate = useNavigate();
  const location = useLocation();
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<Notification[]>([]);
  const [loadingItems, setLoadingItems] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  // Unread count: refresh on mount, on each navigation, and on a light
  // interval. setState lives inside the async closure (not the effect
  // body), so this does not trip react-hooks/set-state-in-effect.
  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const count = await getUnreadCount();
        if (!cancelled) setUnread(count);
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
  }, [location.pathname]);

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

  const handleSelect = useCallback(
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
                  onClick={() => handleSelect(notification)}
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
