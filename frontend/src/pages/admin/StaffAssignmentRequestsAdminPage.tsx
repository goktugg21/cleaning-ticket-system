import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { getApiError } from "../../api/client";
import {
  approveStaffAssignmentRequest,
  listStaffAssignmentRequests,
  rejectStaffAssignmentRequest,
} from "../../api/admin";
import type {
  StaffAssignmentRequest,
  StaffAssignmentRequestStatus,
} from "../../api/types";

/**
 * Sprint 23B — minimal review queue for staff-initiated
 * assignment requests. The backend at
 * `/api/staff-assignment-requests/` already gates the queryset by
 * role (SUPER_ADMIN sees all; COMPANY_ADMIN sees its company;
 * BUILDING_MANAGER sees its buildings; CUSTOMER_USER + STAFF see
 * nothing or only their own respectively). This page lists what
 * the API returns and lets a reviewer approve / reject pending
 * requests in one click.
 *
 * Out of scope for 23B:
 *  - inline cancel (no staff-side cancel endpoint yet)
 *  - reviewer-note input modal (we send "" today; spec only
 *    requires the API path to accept it)
 *  - filtering by building, by staff name, by date range
 *
 * Those are deferred to Sprint 23C.
 */

type Filter = "pending" | "all";

const STATUS_LABEL_KEY: Record<StaffAssignmentRequestStatus, string> = {
  PENDING: "staff_requests.status_pending",
  APPROVED: "staff_requests.status_approved",
  REJECTED: "staff_requests.status_rejected",
  CANCELLED: "staff_requests.status_cancelled",
};

const STATUS_CLASS: Record<StaffAssignmentRequestStatus, string> = {
  PENDING: "cell-tag-in_progress",
  APPROVED: "cell-tag-open",
  REJECTED: "cell-tag-rejected",
  CANCELLED: "cell-tag-closed",
};

function formatTimestamp(value: string): string {
  try {
    return new Date(value).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

export function StaffAssignmentRequestsAdminPage() {
  const { t } = useTranslation("common");
  const [requests, setRequests] = useState<StaffAssignmentRequest[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("pending");
  const [reviewBusyId, setReviewBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params: { status?: StaffAssignmentRequestStatus } = {};
      if (filter === "pending") params.status = "PENDING";
      const response = await listStaffAssignmentRequests(params);
      setRequests(response.results);
      setCount(response.count);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleApprove(id: number) {
    setReviewBusyId(id);
    setError("");
    try {
      await approveStaffAssignmentRequest(id);
      await load();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setReviewBusyId(null);
    }
  }

  async function handleReject(id: number) {
    setReviewBusyId(id);
    setError("");
    try {
      await rejectStaffAssignmentRequest(id);
      await load();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setReviewBusyId(null);
    }
  }

  const countLabel = useMemo(
    () =>
      t(
        count === 1
          ? "staff_requests.count_one"
          : "staff_requests.count_other",
        { count },
      ),
    [count, t],
  );

  return (
    <div data-testid="staff-requests-page">
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("nav.admin_group")}
          </div>
          <h2 className="page-title">{t("staff_requests.title")}</h2>
          <p className="page-sub">
            {loading ? t("staff_requests.subtitle_loading") : countLabel}
          </p>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={load}
            disabled={loading}
            data-testid="staff-requests-refresh"
          >
            <RefreshCw size={14} strokeWidth={2.5} />
            {t("refresh")}
          </button>
        </div>
      </div>

      <p
        className="page-sub"
        style={{ marginTop: -8, marginBottom: 16, maxWidth: 720 }}
      >
        {t("staff_requests.intro")}
      </p>

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      <div className="card" style={{ overflow: "hidden" }}>
        <div className="filter-bar">
          <div className="filter-field">
            <span className="filter-label">{t("status")}</span>
            <select
              className="filter-control"
              value={filter}
              onChange={(event) => setFilter(event.target.value as Filter)}
              data-testid="staff-requests-filter"
            >
              <option value="pending">
                {t("staff_requests.filter_pending")}
              </option>
              <option value="all">{t("staff_requests.filter_all")}</option>
            </select>
          </div>
        </div>

        {loading && (
          <div className="loading-bar" style={{ margin: 0 }}>
            <div className="loading-bar-fill" />
          </div>
        )}

        {/* Sprint 23C hardening: the desktop table is wrapped in
            `admin-list-wrap` so the existing @media (max-width: 600px)
            CSS rule hides it on phones and the `.admin-card-list`
            sibling below takes over. Same pattern as
            /admin/{users,customers,buildings,...}. Without this, the
            table's min-width: 860px (from index.css) plus the card
            header + filter bar push the page over 430px and the
            workspace develops a horizontal scrollbar. */}
        <div className="table-wrap admin-list-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("staff_requests.col_when")}</th>
                <th>{t("staff_requests.col_staff")}</th>
                <th>{t("staff_requests.col_ticket")}</th>
                <th>{t("staff_requests.col_status")}</th>
                <th aria-label={t("staff_requests.col_actions")} />
              </tr>
            </thead>
            <tbody>
              {requests.map((req) => (
                <tr key={req.id} data-testid="staff-request-row">
                  <td className="td-date">
                    {formatTimestamp(req.requested_at)}
                  </td>
                  <td>{req.staff_email}</td>
                  <td>
                    <Link to={`/tickets/${req.ticket}`}>
                      {req.ticket_no || `#${req.ticket}`} · {req.ticket_title}
                    </Link>
                  </td>
                  <td>
                    <span className={`cell-tag ${STATUS_CLASS[req.status]}`}>
                      <i />
                      {t(STATUS_LABEL_KEY[req.status])}
                    </span>
                  </td>
                  <td>
                    {req.status === "PENDING" ? (
                      <div style={{ display: "flex", gap: 6 }}>
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          disabled={reviewBusyId === req.id}
                          onClick={() => handleApprove(req.id)}
                          data-testid={`approve-${req.id}`}
                        >
                          {reviewBusyId === req.id
                            ? t("staff_requests.reviewing")
                            : t("staff_requests.approve")}
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          disabled={reviewBusyId === req.id}
                          onClick={() => handleReject(req.id)}
                          data-testid={`reject-${req.id}`}
                        >
                          {t("staff_requests.reject")}
                        </button>
                      </div>
                    ) : (
                      <span className="muted small">
                        {req.reviewer_email ?? "—"}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Sprint 23C hardening: mobile-parallel card list. CSS shows
            this only at <=600px (admin-card-list); on desktop the
            table above is visible. Card rows are NOT wrapped in an
            <a> because the actions are buttons, not a navigation
            target; the inner ticket-no still links to the ticket. */}
        <ul
          className="admin-card-list"
          data-testid="staff-requests-card-list"
          aria-label={t("staff_requests.title")}
        >
          {requests.map((req) => (
            <li
              key={req.id}
              className="admin-card"
              data-testid="staff-request-card"
            >
              <div className="admin-card-link" style={{ cursor: "default" }}>
                <div className="admin-card-head">
                  <Link
                    to={`/tickets/${req.ticket}`}
                    className="admin-card-title"
                  >
                    {req.ticket_no || `#${req.ticket}`} · {req.ticket_title}
                  </Link>
                  <span className={`cell-tag ${STATUS_CLASS[req.status]}`}>
                    <i />
                    {t(STATUS_LABEL_KEY[req.status])}
                  </span>
                </div>
                <dl className="admin-card-meta">
                  <div className="admin-card-meta-row">
                    <dt>{t("staff_requests.col_when")}</dt>
                    <dd>{formatTimestamp(req.requested_at)}</dd>
                  </div>
                  <div className="admin-card-meta-row">
                    <dt>{t("staff_requests.col_staff")}</dt>
                    <dd>{req.staff_email}</dd>
                  </div>
                  {req.status !== "PENDING" && req.reviewer_email && (
                    <div className="admin-card-meta-row">
                      <dt>{t("staff_requests.col_reviewer")}</dt>
                      <dd>{req.reviewer_email}</dd>
                    </div>
                  )}
                </dl>
                {req.status === "PENDING" && (
                  <div
                    className="admin-card-actions"
                    style={{ display: "flex", gap: 6 }}
                  >
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={reviewBusyId === req.id}
                      onClick={() => handleApprove(req.id)}
                      data-testid={`approve-card-${req.id}`}
                    >
                      {reviewBusyId === req.id
                        ? t("staff_requests.reviewing")
                        : t("staff_requests.approve")}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      disabled={reviewBusyId === req.id}
                      onClick={() => handleReject(req.id)}
                      data-testid={`reject-card-${req.id}`}
                    >
                      {t("staff_requests.reject")}
                    </button>
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>

        {!loading && requests.length === 0 && (
          <div className="empty-state" data-testid="staff-requests-empty">
            <div className="empty-icon">·</div>
            <div className="empty-title">
              {filter === "pending"
                ? t("staff_requests.empty_title")
                : t("staff_requests.empty_filtered_title")}
            </div>
            <p className="empty-sub">
              {filter === "pending"
                ? t("staff_requests.empty_desc")
                : t("staff_requests.empty_filtered_desc")}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
