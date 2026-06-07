/**
 * M1 B3 — full notifications page (/notifications).
 *
 * The user's own notifications, newest first, paginated. Each row shows
 * the summary, relative time, a "for you" marker when directed, and
 * read/unread styling. Clicking a row marks it read and deep-links to its
 * source. "Mark all as read" clears the unread state. The topbar bell is
 * the primary entry; this is the "See all" destination.
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { BellOff, CheckCheck } from "lucide-react";

import { getApiError } from "../api/client";
import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  notificationHref,
} from "../api/notifications";
import type { Notification } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { formatRelative } from "../lib/intl";

export function NotificationsPage() {
  const { t } = useTranslation("common");
  const navigate = useNavigate();
  const [items, setItems] = useState<Notification[]>([]);
  const [count, setCount] = useState(0);
  const [unread, setUnread] = useState(0);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [markingAll, setMarkingAll] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const data = await listNotifications({ page });
        if (cancelled) return;
        setItems(data.results);
        setCount(data.count);
        setUnread(data.unread_count);
        setHasNext(Boolean(data.next));
      } catch (err) {
        if (!cancelled) setError(getApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [page]);

  const handleSelect = useCallback(
    async (notification: Notification) => {
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
          // Best-effort: still navigate.
        }
      }
      const href = notificationHref(notification);
      if (href) navigate(href);
    },
    [navigate],
  );

  const handleMarkAll = useCallback(async () => {
    setMarkingAll(true);
    try {
      await markAllNotificationsRead();
      setItems((prev) => prev.map((item) => ({ ...item, is_read: true })));
      setUnread(0);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setMarkingAll(false);
    }
  }, []);

  return (
    <div data-testid="notifications-page">
      <PageHeader
        eyebrow={t("notifications.eyebrow")}
        title={t("notifications.title")}
        subtitle={t("notifications.subtitle")}
        actions={
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={handleMarkAll}
            disabled={markingAll || unread === 0}
            data-testid="notification-mark-all"
          >
            <CheckCheck size={15} strokeWidth={2} />
            {t("notifications.mark_all_read")}
          </button>
        }
      />

      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}

      <div className="card">
        {loading ? (
          <div className="notif-panel-empty">{t("notifications.loading")}</div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={BellOff}
            title={t("notifications.empty")}
            description={t("notifications.empty_sub")}
            testId="notification-empty"
          />
        ) : (
          <div className="notif-page-list">
            {items.map((notification) => (
              <button
                key={notification.id}
                type="button"
                className={`notif-page-row${
                  notification.is_read ? "" : " notif-page-row-unread"
                }`}
                onClick={() => handleSelect(notification)}
                data-testid="notification-row"
              >
                {!notification.is_read && (
                  <span className="notif-item-dot" aria-hidden="true" />
                )}
                <span className="notif-page-row-main">
                  <span className="notif-page-row-summary">
                    {notification.summary}
                  </span>
                  <span className="notif-page-row-meta">
                    {formatRelative(notification.created_at)}
                    {notification.ticket_no ? ` · ${notification.ticket_no}` : ""}
                    {notification.is_directed && (
                      <span className="notif-item-directed">
                        {" · "}
                        {t("notifications.for_you")}
                      </span>
                    )}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      {(page > 1 || hasNext) && (
        <div className="pager" style={{ marginTop: 12 }}>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setPage((value) => Math.max(1, value - 1))}
            disabled={page <= 1 || loading}
          >
            {t("notifications.prev")}
          </button>
          <span className="muted small" style={{ alignSelf: "center" }}>
            {t("notifications.page_of", {
              page,
              total: Math.max(1, Math.ceil(count / 25)),
            })}
          </span>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => setPage((value) => value + 1)}
            disabled={!hasNext || loading}
          >
            {t("notifications.next")}
          </button>
        </div>
      )}
    </div>
  );
}
