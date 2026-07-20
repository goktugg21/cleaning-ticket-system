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
import { listCompanies } from "../api/admin";
import { useAuth } from "../auth/AuthContext";
import {
  getCompanySubscriptions,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  notificationHref,
  setCompanySubscription,
} from "../api/notifications";
import type { CompanyAdmin, Notification } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { Toggle } from "../components/Toggle";
import { formatRelative } from "../lib/intl";

export function NotificationsPage() {
  const { t } = useTranslation("common");
  const { me } = useAuth();
  const navigate = useNavigate();
  const [items, setItems] = useState<Notification[]>([]);
  const [count, setCount] = useState(0);
  const [unread, setUnread] = useState(0);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [markingAll, setMarkingAll] = useState(false);

  // #109 Part D — SA-only: provider-company filter (switches the feed
  // into the read-only view-as mode) + per-company subscription state.
  // Hidden for every other role; fetches never fire for non-SA.
  const isSuperAdmin = me?.role === "SUPER_ADMIN";
  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companyFilter, setCompanyFilter] = useState<number | "">("");
  const [subscribedIds, setSubscribedIds] = useState<Set<number>>(
    () => new Set(),
  );
  const [subscriptionBusy, setSubscriptionBusy] = useState(false);
  const viewAsMode = isSuperAdmin && companyFilter !== "";

  useEffect(() => {
    if (!isSuperAdmin) return;
    let cancelled = false;
    Promise.all([
      listCompanies({ page_size: 200 }),
      getCompanySubscriptions(),
    ])
      .then(([companyData, subscribed]) => {
        if (cancelled) return;
        setCompanies(companyData.results);
        setSubscribedIds(new Set(subscribed));
      })
      .catch(() => {
        // The selector simply stays empty on failure; the own feed
        // below is unaffected.
      });
    return () => {
      cancelled = true;
    };
  }, [isSuperAdmin]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const data = await listNotifications({
          page,
          ...(viewAsMode ? { company: companyFilter as number } : {}),
        });
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
  }, [page, viewAsMode, companyFilter]);

  const handleSelect = useCallback(
    async (notification: Notification) => {
      if (viewAsMode) {
        // #109 Part D — view-as rows are read-only (they belong to
        // other recipients); deep-link without touching read state.
        const href = notificationHref(notification);
        if (href) navigate(href);
        return;
      }
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
    [navigate, viewAsMode],
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
          !viewAsMode ? (
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
          ) : undefined
        }
      />

      {/* #109 Part D — SA-only: company view-as filter + the
          per-company subscribe Toggle (platform rule: a boolean state
          is a Toggle). Hidden for every other role. */}
      {isSuperAdmin && (
        <div
          className="card"
          style={{
            padding: 16,
            marginBottom: 16,
            display: "flex",
            flexWrap: "wrap",
            gap: 16,
            alignItems: "flex-end",
          }}
          data-testid="notifications-sa-controls"
        >
          <label className="field" style={{ minWidth: 240 }}>
            <span className="field-label">
              {t("notifications.company_filter_label")}
            </span>
            <select
              className="field-select"
              value={companyFilter === "" ? "" : String(companyFilter)}
              onChange={(event) => {
                setPage(1);
                setCompanyFilter(
                  event.target.value === ""
                    ? ""
                    : Number(event.target.value),
                );
              }}
              data-testid="notifications-company-filter"
            >
              <option value="">
                {t("notifications.company_filter_own")}
              </option>
              {companies.map((company) => (
                <option key={company.id} value={String(company.id)}>
                  {company.name}
                </option>
              ))}
            </select>
          </label>
          {viewAsMode && (
            <>
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  paddingBottom: 6,
                }}
              >
                <Toggle
                  checked={subscribedIds.has(companyFilter as number)}
                  disabled={subscriptionBusy}
                  onChange={async (event) => {
                    const next = event.target.checked;
                    const companyId = companyFilter as number;
                    setSubscriptionBusy(true);
                    try {
                      await setCompanySubscription(companyId, next);
                      setSubscribedIds((prev) => {
                        const draft = new Set(prev);
                        if (next) draft.add(companyId);
                        else draft.delete(companyId);
                        return draft;
                      });
                    } catch (err) {
                      setError(getApiError(err));
                    } finally {
                      setSubscriptionBusy(false);
                    }
                  }}
                  data-testid="notifications-subscribe-toggle"
                />
                <span>{t("notifications.subscribe_toggle")}</span>
              </label>
              <span className="muted small" style={{ paddingBottom: 10 }}>
                {t("notifications.company_view_hint")}
              </span>
            </>
          )}
        </div>
      )}

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
            description={
              // IA 2026-06-25 — SA-only explainer: an empty SA feed is BY
              // DESIGN (the fan-out deliberately excludes SUPER_ADMIN;
              // only directed messages reach them), not a defect.
              me?.role === "SUPER_ADMIN"
                ? t("notifications.sa_empty_hint")
                : t("notifications.empty_sub")
            }
            testId="notification-empty"
          />
        ) : (
          <div className="notif-page-list">
            {items.map((notification) => (
              <button
                key={notification.id}
                type="button"
                className={`notif-page-row${
                  !viewAsMode && !notification.is_read
                    ? " notif-page-row-unread"
                    : ""
                }`}
                onClick={() => handleSelect(notification)}
                data-testid="notification-row"
              >
                {!viewAsMode && !notification.is_read && (
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
