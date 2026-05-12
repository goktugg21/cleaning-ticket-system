import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";

/**
 * Sprint 23B — minimal review queue for staff-initiated
 * assignment requests. The backend at
 * `/api/staff-assignment-requests/` already gates the queryset by
 * role (SUPER_ADMIN sees all; COMPANY_ADMIN sees its company;
 * BUILDING_MANAGER sees its buildings; CUSTOMER_USER + STAFF see
 * nothing or only their own respectively). This page lists what
 * the API returns and lets a reviewer approve / reject pending
 * requests via a confirmation modal.
 *
 * Sprint 24B — the one-click approve/reject path is replaced with
 * a proper review modal that collects an optional reviewer note
 * before posting. The reviewer_note travels back on the response
 * and is rendered next to the reviewer email on reviewed rows
 * (both desktop table and mobile card). The pre-24B "send empty
 * note" UX was acceptable for the spec but offered no audit value
 * for the requesting staff member — Sprint 24B closes that gap
 * without changing the backend contract (the API already accepted
 * the note since Sprint 23A).
 */

type Filter = "pending" | "all";
type ReviewAction = "approve" | "reject";

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

function ticketLabel(req: StaffAssignmentRequest): string {
  return `${req.ticket_no || `#${req.ticket}`} · ${req.ticket_title}`;
}

export function StaffAssignmentRequestsAdminPage() {
  const { t } = useTranslation("common");
  const [requests, setRequests] = useState<StaffAssignmentRequest[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("pending");

  // Sprint 24B — review modal state. `target` holds the row being
  // reviewed; `action` says whether we're approving or rejecting.
  // The note textarea is a separate React state so cancelling does
  // not clear it mid-typing on accidental escape, while opening a
  // fresh dialog resets it.
  const [reviewTarget, setReviewTarget] =
    useState<StaffAssignmentRequest | null>(null);
  const [reviewAction, setReviewAction] = useState<ReviewAction>("approve");
  const [reviewerNote, setReviewerNote] = useState("");
  const [reviewBusy, setReviewBusy] = useState(false);
  const [successBanner, setSuccessBanner] = useState("");
  const reviewDialogRef = useRef<ConfirmDialogHandle>(null);

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

  function openReviewDialog(
    req: StaffAssignmentRequest,
    action: ReviewAction,
  ) {
    setReviewTarget(req);
    setReviewAction(action);
    setReviewerNote("");
    setError("");
    setSuccessBanner("");
    // Defer the showModal call to after the dialog body re-renders with
    // the fresh target — useImperativeHandle's open() is synchronous so
    // a microtask is enough.
    queueMicrotask(() => reviewDialogRef.current?.open());
  }

  async function submitReview() {
    if (!reviewTarget) return;
    setReviewBusy(true);
    setError("");
    const note = reviewerNote.trim();
    const targetSnapshot = reviewTarget;
    const actionSnapshot = reviewAction;
    try {
      if (actionSnapshot === "approve") {
        await approveStaffAssignmentRequest(targetSnapshot.id, note);
        setSuccessBanner(
          t("staff_requests.banner_approved", {
            staff: targetSnapshot.staff_email,
            ticket: ticketLabel(targetSnapshot),
          }),
        );
      } else {
        await rejectStaffAssignmentRequest(targetSnapshot.id, note);
        setSuccessBanner(
          t("staff_requests.banner_rejected", {
            staff: targetSnapshot.staff_email,
            ticket: ticketLabel(targetSnapshot),
          }),
        );
      }
      reviewDialogRef.current?.close();
      setReviewTarget(null);
      await load();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setReviewBusy(false);
    }
  }

  function cancelReviewDialog() {
    if (reviewBusy) return;
    setReviewTarget(null);
    setReviewerNote("");
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

  const reviewDialogTitle = useMemo(() => {
    if (!reviewTarget) return "";
    return reviewAction === "approve"
      ? t("staff_requests.review_dialog_approve_title")
      : t("staff_requests.review_dialog_reject_title");
  }, [reviewAction, reviewTarget, t]);

  const reviewDialogConfirmLabel = useMemo(() => {
    return reviewAction === "approve"
      ? t("staff_requests.approve")
      : t("staff_requests.reject");
  }, [reviewAction, t]);

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

      {successBanner && (
        <div
          className="alert-info"
          style={{ marginBottom: 16 }}
          role="status"
          data-testid="staff-requests-success-banner"
        >
          {successBanner}
        </div>
      )}

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
            sibling below takes over. Sprint 24B adds a Reviewer note
            column so reviewed rows surface the persisted note inline. */}
        <div className="table-wrap admin-list-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("staff_requests.col_when")}</th>
                <th>{t("staff_requests.col_staff")}</th>
                <th>{t("staff_requests.col_ticket")}</th>
                <th>{t("staff_requests.col_status")}</th>
                <th>{t("staff_requests.col_reviewer_note")}</th>
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
                    <Link to={`/tickets/${req.ticket}`}>{ticketLabel(req)}</Link>
                  </td>
                  <td>
                    <span className={`cell-tag ${STATUS_CLASS[req.status]}`}>
                      <i />
                      {t(STATUS_LABEL_KEY[req.status])}
                    </span>
                  </td>
                  <td>
                    {req.status === "PENDING" ? (
                      <span className="muted small">—</span>
                    ) : req.reviewer_note ? (
                      <span data-testid="staff-request-reviewer-note">
                        {req.reviewer_note}
                      </span>
                    ) : (
                      <span className="muted small">
                        {t("staff_requests.reviewer_note_empty")}
                      </span>
                    )}
                  </td>
                  <td>
                    {req.status === "PENDING" ? (
                      <div style={{ display: "flex", gap: 6 }}>
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          disabled={reviewBusy}
                          onClick={() => openReviewDialog(req, "approve")}
                          data-testid={`approve-${req.id}`}
                        >
                          {t("staff_requests.approve")}
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          disabled={reviewBusy}
                          onClick={() => openReviewDialog(req, "reject")}
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
            target; the inner ticket-no still links to the ticket.
            Sprint 24B adds a Reviewer-note meta-row for reviewed
            cards so the persisted note surfaces alongside the
            reviewer's email. */}
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
                    {ticketLabel(req)}
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
                  {req.status !== "PENDING" && (
                    <div className="admin-card-meta-row">
                      <dt>{t("staff_requests.col_reviewer_note")}</dt>
                      <dd>
                        {req.reviewer_note ? (
                          <span data-testid="staff-request-reviewer-note-mobile">
                            {req.reviewer_note}
                          </span>
                        ) : (
                          <span className="muted small">
                            {t("staff_requests.reviewer_note_empty")}
                          </span>
                        )}
                      </dd>
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
                      disabled={reviewBusy}
                      onClick={() => openReviewDialog(req, "approve")}
                      data-testid={`approve-card-${req.id}`}
                    >
                      {t("staff_requests.approve")}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      disabled={reviewBusy}
                      onClick={() => openReviewDialog(req, "reject")}
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

      {/* Sprint 24B — review modal. We pass a JSX body so the
          textarea can be a real <textarea> bound to the parent
          state. ConfirmDialog renders its body inside the
          <dialog> already, so accessibility / focus trap come
          for free. */}
      <ConfirmDialog
        ref={reviewDialogRef}
        title={reviewDialogTitle}
        confirmLabel={reviewDialogConfirmLabel}
        busyLabel={t("staff_requests.reviewing")}
        onConfirm={submitReview}
        onCancel={cancelReviewDialog}
        busy={reviewBusy}
        body={
          reviewTarget ? (
            <div data-testid="staff-requests-review-dialog">
              <p style={{ marginBottom: 12 }}>
                {t(
                  reviewAction === "approve"
                    ? "staff_requests.review_dialog_approve_intro"
                    : "staff_requests.review_dialog_reject_intro",
                  {
                    staff: reviewTarget.staff_email,
                    ticket: ticketLabel(reviewTarget),
                  },
                )}
              </p>
              <dl
                className="admin-card-meta"
                style={{ marginBottom: 12, fontSize: 13 }}
              >
                <div className="admin-card-meta-row">
                  <dt>{t("staff_requests.review_dialog_meta_staff")}</dt>
                  <dd>{reviewTarget.staff_email}</dd>
                </div>
                <div className="admin-card-meta-row">
                  <dt>{t("staff_requests.review_dialog_meta_ticket")}</dt>
                  <dd>{ticketLabel(reviewTarget)}</dd>
                </div>
                <div className="admin-card-meta-row">
                  <dt>{t("staff_requests.review_dialog_meta_when")}</dt>
                  <dd>{formatTimestamp(reviewTarget.requested_at)}</dd>
                </div>
              </dl>
              <label
                className="field-label"
                htmlFor="staff-review-reviewer-note"
              >
                {t("staff_requests.reviewer_note_label")}
              </label>
              <textarea
                id="staff-review-reviewer-note"
                className="field-input"
                rows={3}
                value={reviewerNote}
                onChange={(event) => setReviewerNote(event.target.value)}
                placeholder={t(
                  "staff_requests.reviewer_note_placeholder",
                )}
                disabled={reviewBusy}
                data-testid="staff-review-reviewer-note"
                style={{ resize: "vertical", width: "100%" }}
              />
            </div>
          ) : (
            // Body must be a defined ReactNode even when target is
            // null so the dialog's initial render does not error;
            // a closed dialog never paints this branch.
            <span />
          )
        }
      />
    </div>
  );
}
