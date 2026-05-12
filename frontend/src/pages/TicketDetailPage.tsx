import type { ChangeEvent, FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ChevronLeft,
  Clock,
  History,
  MapPin,
  MessageSquare,
  Paperclip,
  Trash2,
  TriangleAlert,
  UploadCloud,
  UserPlus,
  Users,
} from "lucide-react";
import { Trans, useTranslation } from "react-i18next";
import { api, getApiError } from "../api/client";
import {
  addTicketStaffAssignment,
  cancelStaffAssignmentRequest,
  createStaffAssignmentRequest,
  listAssignableStaff,
  listStaffAssignmentRequests,
  removeTicketStaffAssignment,
} from "../api/admin";
import type { AssignableStaff } from "../api/admin";
import type {
  AssignableManager,
  PaginatedResponse,
  TicketAttachment,
  TicketDetail,
  TicketMessage,
  TicketMessageType,
  TicketStatus,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ConfirmDialog } from "../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../components/ConfirmDialog";
import { SLABadge } from "../components/sla/SLABadge";
import { useFormatSLATime } from "../utils/useFormatSLATime";
import { useSLALabel } from "../utils/useSLALabel";

// Sprint 15: backend is the source of truth for which transitions are
// available. Previously the frontend carried a SUPER_ADMIN_UI_NEXT_STATUS
// table that hard-coded a SUPER_ADMIN's next-step buttons; that table
// could drift from `state_machine.ALLOWED_TRANSITIONS` and bypass the
// pair-aware customer-user / building-manager scope checks. The viewset
// now returns a per-role `allowed_next_statuses` for every role
// (SUPER_ADMIN included via the special-case branch in
// `state_machine.allowed_next_statuses`), so the page renders that list
// directly.
function getVisibleWorkflowStatuses(ticket: TicketDetail): TicketStatus[] {
  return ticket.allowed_next_statuses;
}

function isAdminCustomerDecisionOverride(
  currentStatus: TicketStatus,
  nextStatus: TicketStatus,
  role?: string,
): boolean {
  return (
    (role === "SUPER_ADMIN" || role === "COMPANY_ADMIN") &&
    currentStatus === "WAITING_CUSTOMER_APPROVAL" &&
    (nextStatus === "APPROVED" || nextStatus === "REJECTED")
  );
}

const ACCEPTED_ATTACHMENT_TYPES =
  ".jpg,.jpeg,.png,.webp,.heic,.heif,.pdf";
const MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024;

function formatDate(value: string | null): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

function getInitials(value: string | null | undefined): string {
  if (!value) return "—";
  const localPart = value.split("@")[0] || value;
  const parts = localPart
    .replace(/[._-]+/g, " ")
    .split(" ")
    .filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }
  return localPart.slice(0, 2).toUpperCase();
}

function humanName(email: string | null | undefined, fallback: string): string {
  if (!email) return fallback;
  const local = email.split("@")[0];
  return local
    .replace(/[._-]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function getFileExtension(filename: string): string {
  const parts = filename.split(".");
  if (parts.length < 2) return "FILE";
  return (parts.pop() || "FILE").slice(0, 4).toUpperCase();
}

// Sprint 22 final polish: status-history notes set by the seed
// (`seed_demo_data → IN_PROGRESS`) and any other transition note
// that contains a raw enum value or an internal marker string are
// not meant to be shown to demo users. We strip them at render
// time so the timeline reads cleanly. Operator-typed notes are
// preserved verbatim.
function sanitizeStatusNote(raw: string | null | undefined): string {
  if (!raw) return "";
  const trimmed = raw.trim();
  if (!trimmed) return "";
  // Drop notes that start with `seed_demo_data` (or contain the
  // legacy seed prefix anywhere). This matches the exact string
  // the canonical seed writes via apply_transition(..., note=…).
  if (/^seed_demo_data\b/i.test(trimmed)) return "";
  if (/seed_demo_data\s*→/i.test(trimmed)) return "";
  return trimmed;
}


export function TicketDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { me } = useAuth();
  const { t } = useTranslation(["ticket_detail", "common"]);
  const slaLabel = useSLALabel();
  const formatSLATime = useFormatSLATime();

  const tStatus = (status: TicketStatus | string | null): string => {
    if (!status) return t("status_default_created");
    return t(`common:status.${status.toLowerCase()}`);
  };

  const priorityLabelLong = (priority: string): string => {
    switch (priority) {
      case "URGENT":
        return t("priority_long_urgent");
      case "HIGH":
        return t("priority_long_high");
      default:
        return t("priority_long_normal");
    }
  };

  const adminDecisionOverrideMessage = (nextStatus: TicketStatus): string => {
    if (nextStatus === "APPROVED") return t("workflow_admin_override_approved");
    if (nextStatus === "REJECTED") return t("workflow_admin_override_rejected");
    return "";
  };

  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [messages, setMessages] = useState<TicketMessage[]>([]);
  const [attachments, setAttachments] = useState<TicketAttachment[]>([]);

  // Sprint 23B — Request-assignment state for STAFF users on a
  // ticket they have building visibility for but aren't yet
  // assigned to.
  //
  // Sprint 24C — instead of a one-way "submitted" flag, we now
  // track the actual PENDING request id so the staff user can
  // cancel it via the new modal. On ticket-detail mount we list
  // the staff user's requests and find one matching this ticket;
  // after a successful POST we set the id from the response; on
  // cancellation we clear it back to null so the "Request
  // assignment" button reappears (Sprint 23A's duplicate guard
  // only fires on still-PENDING rows).
  const [requestAssignmentBusy, setRequestAssignmentBusy] =
    useState(false);
  const [pendingRequestId, setPendingRequestId] =
    useState<number | null>(null);
  const [requestAssignmentError, setRequestAssignmentError] =
    useState("");
  const [requestAssignmentBanner, setRequestAssignmentBanner] =
    useState("");
  const [cancelRequestBusy, setCancelRequestBusy] = useState(false);
  const cancelRequestDialogRef = useRef<ConfirmDialogHandle>(null);

  const [loading, setLoading] = useState(true);
  const [statusNote, setStatusNote] = useState("");
  const [statusBusy, setStatusBusy] = useState<TicketStatus | null>(null);
  const [pendingAdminDecisionOverride, setPendingAdminDecisionOverride] =
    useState<TicketStatus | null>(null);

  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState<TicketMessageType>("PUBLIC_REPLY");
  const [sendingMessage, setSendingMessage] = useState(false);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [attachmentHidden, setAttachmentHidden] = useState(false);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const [downloadingAttachmentId, setDownloadingAttachmentId] =
    useState<number | null>(null);

  const [assignableManagers, setAssignableManagers] = useState<
    AssignableManager[]
  >([]);
  const [selectedAssigneeId, setSelectedAssigneeId] = useState<string>("");
  const [assigningTicket, setAssigningTicket] = useState(false);

  // Sprint 25A — admin/manager direct staff assignment.
  // `assignableStaff` is the candidate list pulled from the
  // `/tickets/<id>/assignable-staff/` endpoint (STAFF users with
  // an active StaffProfile + BuildingStaffVisibility on this ticket's
  // building). The block only renders for service-provider-side
  // actors (isStaff) — the same gate that governs the existing
  // BUILDING_MANAGER assignment dropdown for `ticket.assigned_to`.
  const [assignableStaff, setAssignableStaff] = useState<AssignableStaff[]>(
    [],
  );
  const [selectedStaffToAdd, setSelectedStaffToAdd] = useState<string>("");
  const [addingStaff, setAddingStaff] = useState(false);
  const [removingStaffId, setRemovingStaffId] = useState<number | null>(null);
  const [staffAssignmentError, setStaffAssignmentError] = useState("");
  const [staffAssignmentBanner, setStaffAssignmentBanner] = useState("");
  const [removeStaffTarget, setRemoveStaffTarget] = useState<{
    id: number;
    name: string;
  } | null>(null);
  const removeStaffDialogRef = useRef<ConfirmDialogHandle>(null);

  const [error, setError] = useState("");

  // Sprint 12 — soft-delete state. confirmText is what the operator
  // types into the dialog input; the confirm button only activates
  // when it matches the ticket number, preventing single-click
  // accidents. busy gates the network round-trip.
  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deletingTicket, setDeletingTicket] = useState(false);

  const isStaff =
    me?.role === "SUPER_ADMIN" ||
    me?.role === "COMPANY_ADMIN" ||
    me?.role === "BUILDING_MANAGER";

  // Sprint 12 — mirrors the backend `_user_can_soft_delete_ticket`
  // rule so the button only renders when the API will actually accept
  // the call. Backend stays the source of truth for security; this
  // is purely a UX gate.
  const canDeleteTicket =
    !!ticket &&
    !!me &&
    (me.role === "SUPER_ADMIN" ||
      me.role === "COMPANY_ADMIN" ||
      ticket.created_by === me.id);

  const loadTicket = useCallback(async () => {
    if (!id) return;
    try {
      const [ticketResponse, messageResponse, attachmentResponse] =
        await Promise.all([
          api.get<TicketDetail>(`/tickets/${id}/`),
          api.get<PaginatedResponse<TicketMessage>>(
            `/tickets/${id}/messages/`,
          ),
          api.get<PaginatedResponse<TicketAttachment>>(
            `/tickets/${id}/attachments/`,
          ),
        ]);
      setTicket(ticketResponse.data);
      setMessages(messageResponse.data.results);
      setAttachments(attachmentResponse.data.results);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    setLoading(true);
    loadTicket();
  }, [loadTicket]);

  useEffect(() => {
    setSelectedAssigneeId(
      ticket && ticket.assigned_to !== null
        ? String(ticket.assigned_to)
        : "",
    );
  }, [ticket?.id, ticket?.assigned_to]);

  useEffect(() => {
    setPendingAdminDecisionOverride(null);
  }, [ticket?.id, ticket?.status]);

  useEffect(() => {
    if (!isStaff || !id) return;
    let cancelled = false;
    api
      .get<AssignableManager[]>(`/tickets/${id}/assignable-managers/`)
      .then((response) => {
        if (!cancelled) setAssignableManagers(response.data);
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [id, isStaff]);

  // Sprint 25A — discover the eligible STAFF candidates for direct
  // admin/manager assignment. Filtered server-side to STAFF users
  // with an active StaffProfile + BuildingStaffVisibility on this
  // ticket's building, so the dropdown never offers an ineligible row.
  const reloadAssignableStaff = useCallback(async () => {
    if (!isStaff || !id) return;
    try {
      const data = await listAssignableStaff(Number(id));
      setAssignableStaff(data);
    } catch (err) {
      setStaffAssignmentError(getApiError(err));
    }
  }, [id, isStaff]);

  useEffect(() => {
    reloadAssignableStaff();
  }, [reloadAssignableStaff]);

  // Sprint 24C — discover the staff user's own PENDING request for
  // this ticket so the UI can show a Cancel button instead of the
  // submit-once banner. The backend's STAFF queryset is narrowed to
  // `staff=request.user`, so this list call is bounded to the
  // viewer's own requests.
  //
  // Sprint 24D — the viewset now declares `filterset_fields =
  // ["status", "ticket", "staff"]`, so we can ask for exactly the
  // single row we care about (`?ticket=<id>&status=PENDING`). The
  // backend's duplicate guard allows one PENDING per (staff, ticket),
  // so this returns 0 or 1 row regardless of pagination — fixing the
  // pre-24D bug where a staff user with >25 lifetime requests could
  // miss their own PENDING row if it fell off the first page.
  useEffect(() => {
    if (me?.role !== "STAFF" || !id) return;
    let cancelled = false;
    const numericId = Number(id);
    listStaffAssignmentRequests({
      ticket: numericId,
      status: "PENDING",
    })
      .then((response) => {
        if (cancelled) return;
        const match = response.results.find(
          (r) => r.ticket === numericId && r.status === "PENDING",
        );
        setPendingRequestId(match ? match.id : null);
      })
      .catch(() => {
        if (!cancelled) setPendingRequestId(null);
      });
    return () => {
      cancelled = true;
    };
  }, [id, me?.role]);

  const visibleNextStatuses = useMemo(
    () => (ticket ? getVisibleWorkflowStatuses(ticket) : []),
    [ticket],
  );

  async function submitAssignment(event: FormEvent) {
    event.preventDefault();
    if (!id) return;
    setError("");
    setAssigningTicket(true);
    try {
      const assignedTo =
        selectedAssigneeId === "" ? null : Number(selectedAssigneeId);
      const response = await api.post<TicketDetail>(
        `/tickets/${id}/assign/`,
        { assigned_to: assignedTo },
      );
      setTicket(response.data);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setAssigningTicket(false);
    }
  }

  function openDeleteDialog() {
    setDeleteConfirmText("");
    setError("");
    deleteDialogRef.current?.open();
  }

  async function confirmDeleteTicket() {
    if (!id || !ticket) return;
    setDeletingTicket(true);
    try {
      await api.delete(`/tickets/${id}/`);
      deleteDialogRef.current?.close();
      // Sprint 12: navigate back to dashboard so the soft-deleted
      // ticket disappears from view immediately. The ticket list will
      // refetch on mount and the row will not appear.
      navigate("/", { replace: true });
    } catch (err) {
      setError(
        t("delete_ticket_failed", { detail: getApiError(err) }),
      );
      deleteDialogRef.current?.close();
    } finally {
      setDeletingTicket(false);
    }
  }

  async function changeStatus(toStatus: TicketStatus) {
    if (!id || !ticket) return;

    setError("");

    const needsAdminDecisionOverride = isAdminCustomerDecisionOverride(
      ticket.status,
      toStatus,
      me?.role,
    );

    if (
      needsAdminDecisionOverride &&
      pendingAdminDecisionOverride !== toStatus
    ) {
      setPendingAdminDecisionOverride(toStatus);
      return;
    }

    if (
      me?.role === "CUSTOMER_USER" &&
      ticket.status === "WAITING_CUSTOMER_APPROVAL" &&
      toStatus === "REJECTED" &&
      !statusNote.trim()
    ) {
      setError(t("workflow_customer_rejection_required"));
      return;
    }

    setStatusBusy(toStatus);

    try {
      const response = await api.post<TicketDetail>(
        `/tickets/${id}/status/`,
        {
          to_status: toStatus,
          note: statusNote.trim(),
        },
      );

      setTicket(response.data);
      setStatusNote("");
      setPendingAdminDecisionOverride(null);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setStatusBusy(null);
    }
  }

  async function submitMessage(event: FormEvent) {
    event.preventDefault();
    if (!id || !message.trim()) return;
    setError("");
    setSendingMessage(true);
    try {
      await api.post(`/tickets/${id}/messages/`, {
        message: message.trim(),
        message_type: isStaff ? messageType : "PUBLIC_REPLY",
      });
      setMessage("");
      setMessageType("PUBLIC_REPLY");
      await loadTicket();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSendingMessage(false);
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    if (file && file.size > MAX_ATTACHMENT_SIZE_BYTES) {
      setSelectedFile(null);
      setError(t("attachment_too_large"));
      event.target.value = "";
      return;
    }
    setError("");
    setSelectedFile(file);
  }

  async function downloadAttachment(item: TicketAttachment) {
    if (!id) return;
    setError("");
    setDownloadingAttachmentId(item.id);
    try {
      const response = await api.get(
        `/tickets/${id}/attachments/${item.id}/download/`,
        { responseType: "blob" },
      );
      const blobUrl = URL.createObjectURL(response.data);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = item.original_filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(blobUrl);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setDownloadingAttachmentId(null);
    }
  }

  async function submitAttachment(event: FormEvent) {
    event.preventDefault();
    if (!id || !selectedFile) return;

    if (selectedFile.size > MAX_ATTACHMENT_SIZE_BYTES) {
      setError(t("attachment_too_large"));
      return;
    }

    setError("");
    setUploadingAttachment(true);

    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      if (isStaff) {
        formData.append("is_hidden", attachmentHidden ? "true" : "false");
      }
      await api.post(`/tickets/${id}/attachments/`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setSelectedFile(null);
      setAttachmentHidden(false);
      await loadTicket();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setUploadingAttachment(false);
    }
  }

  if (loading && !ticket) {
    return (
      <div>
        <Link to="/" className="link-back">
          <ChevronLeft size={14} strokeWidth={2.5} />
          {t("back_to_tickets")}
        </Link>
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
        {error && <div className="alert-error">{error}</div>}
      </div>
    );
  }

  if (!ticket) {
    return (
      <div>
        <Link to="/" className="link-back">
          <ChevronLeft size={14} strokeWidth={2.5} />
          {t("back_to_tickets")}
        </Link>
        <div className="alert-error">{error || t("ticket_not_found")}</div>
      </div>
    );
  }

  return (
    <div>
      <div className="detail-header">
        <div className="detail-header-top">
          <Link to="/" className="link-back">
            <ChevronLeft size={14} strokeWidth={2.5} />
            {t("back_to_tickets")}
          </Link>
          {canDeleteTicket && (
            <button
              type="button"
              className="btn btn-ghost btn-sm detail-delete-btn"
              onClick={openDeleteDialog}
              disabled={deletingTicket}
            >
              <Trash2 size={14} strokeWidth={2.2} />
              {t("delete_ticket_button")}
            </button>
          )}
        </div>
        <div className="detail-header-meta">
          <span className="detail-header-no">{ticket.ticket_no}</span>
          <span className={`badge badge-${ticket.priority.toLowerCase()}`}>
            {priorityLabelLong(ticket.priority)}
          </span>
          <span className={`badge badge-${ticket.status.toLowerCase()}`}>
            {tStatus(ticket.status)}
          </span>
        </div>
        <h1 className="detail-header-title">{ticket.title}</h1>
        <p className="detail-header-desc">{ticket.description}</p>
      </div>

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      <div className="detail-grid">
        <div className="detail-main">
          <div className="card">
            <div className="card-head-icon">
              <span className="card-head-icon-glyph">
                <Clock size={14} strokeWidth={2.2} />
              </span>
              <span className="card-head-icon-title">
                {t("card_activity_title")}
              </span>
            </div>
            <div className="timeline">
              {ticket.status_history.length === 0 ? (
                <div className="timeline-row" data-color="green">
                  <div className="timeline-dot" />
                  <div>
                    <div className="timeline-time">
                      {formatDate(ticket.created_at)}
                    </div>
                    <div className="timeline-text">
                      <Trans
                        i18nKey="ticket_detail:timeline_created"
                        values={{
                          name: humanName(
                            ticket.created_by_email,
                            t("unassigned"),
                          ),
                        }}
                        components={{ b: <b /> }}
                      />
                    </div>
                  </div>
                </div>
              ) : (
                ticket.status_history.map((entry, index) => (
                  <div
                    key={entry.id}
                    className="timeline-row"
                    data-color={
                      index === 0
                        ? "green"
                        : entry.new_status === "REJECTED"
                          ? "red"
                          : entry.new_status === "WAITING_CUSTOMER_APPROVAL"
                            ? "amber"
                            : "muted"
                    }
                  >
                    <div className="timeline-dot" />
                    <div>
                      <div className="timeline-time">
                        {formatDate(entry.created_at)}
                      </div>
                      <div className="timeline-text">
                        <b>
                          {humanName(
                            entry.changed_by_email,
                            t("unassigned"),
                          )}
                        </b>
                        {entry.old_status ? (
                          <>
                            {t("timeline_status_changed_from_to")}
                            <span
                              className={`pill ${entry.old_status === "OPEN" ? "open" : "progress"}`}
                            >
                              {tStatus(entry.old_status)}
                            </span>
                            {t("timeline_status_to")}
                            <span className="pill progress">
                              {tStatus(entry.new_status)}
                            </span>
                          </>
                        ) : (
                          <>
                            {t("timeline_created_as")}
                            <span className="pill progress">
                              {tStatus(entry.new_status)}
                            </span>
                          </>
                        )}
                        {(() => {
                          const cleaned = sanitizeStatusNote(entry.note);
                          return cleaned ? `. ${cleaned}` : ".";
                        })()}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-head-icon">
              <span className="card-head-icon-glyph">
                <MessageSquare size={14} strokeWidth={2.2} />
              </span>
              <span className="card-head-icon-title">
                {t("card_messages_title")}
              </span>
            </div>
            <form className="notes-composer-body" onSubmit={submitMessage}>
              <textarea
                className="notes-textarea"
                placeholder={
                  isStaff && messageType === "INTERNAL_NOTE"
                    ? t("composer_internal_placeholder")
                    : t("composer_public_placeholder")
                }
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                required
              />
              <div className="notes-actions">
                <div className="notes-tools">
                  {isStaff && (
                    <div className="composer-toggle" role="tablist">
                      <button
                        type="button"
                        role="tab"
                        aria-selected={messageType === "PUBLIC_REPLY"}
                        className={`composer-toggle-btn ${
                          messageType === "PUBLIC_REPLY" ? "active" : ""
                        }`}
                        onClick={() => setMessageType("PUBLIC_REPLY")}
                      >
                        {t("composer_public")}
                      </button>
                      <button
                        type="button"
                        role="tab"
                        aria-selected={messageType === "INTERNAL_NOTE"}
                        className={`composer-toggle-btn ${
                          messageType === "INTERNAL_NOTE"
                            ? "active internal"
                            : ""
                        }`}
                        onClick={() => setMessageType("INTERNAL_NOTE")}
                      >
                        {t("composer_internal")}
                      </button>
                    </div>
                  )}
                </div>
                <button
                  type="submit"
                  className="btn btn-primary btn-sm"
                  disabled={sendingMessage || !message.trim()}
                >
                  {sendingMessage ? t("sending") : t("post_message")}
                </button>
              </div>
            </form>

            {messages.length === 0 ? (
              <p
                style={{
                  padding: "0 22px 22px",
                  color: "var(--text-faint)",
                  fontSize: 13,
                }}
              >
                {t("no_messages")}
              </p>
            ) : (
              messages.map((item) => (
                <div
                  key={item.id}
                  className={`note-bubble ${
                    item.message_type === "INTERNAL_NOTE" ? "internal" : ""
                  }`}
                >
                  <div className="note-bubble-avatar">
                    {getInitials(item.author_email)}
                  </div>
                  <div>
                    <div className="note-bubble-head">
                      <span className="note-bubble-name">
                        {humanName(item.author_email, t("unassigned"))}
                      </span>
                      <span className="note-bubble-time">
                        {formatDate(item.created_at)}
                      </span>
                      <span
                        className={`note-bubble-tag ${
                          item.message_type === "PUBLIC_REPLY" ? "public" : ""
                        }`}
                      >
                        {item.message_type === "INTERNAL_NOTE"
                          ? t("tag_internal")
                          : t("tag_public")}
                      </span>
                    </div>
                    <div className="note-bubble-text">{item.message}</div>
                  </div>
                </div>
              ))
            )}
          </div>

          <div className="card">
            <div className="card-head-icon">
              <span className="card-head-icon-glyph">
                <Paperclip size={14} strokeWidth={2.2} />
              </span>
              <span className="card-head-icon-title">
                {t("card_attachments_title")}
              </span>
              <span className="card-head-icon-spacer" />
              <span className="card-head-icon-link">
                {t(
                  attachments.length === 1 ? "files_singular" : "files_plural",
                  { count: attachments.length },
                )}
              </span>
            </div>

            <div className="att-thumb-grid">
              {attachments.map((item) => (
                <div className="att-thumb" key={item.id}>
                  <button
                    type="button"
                    className={`att-thumb-tile ${item.is_hidden ? "internal" : ""}`}
                    onClick={() => downloadAttachment(item)}
                    disabled={downloadingAttachmentId === item.id}
                    aria-label={`Download ${item.original_filename}`}
                  >
                    <span className="att-thumb-ext">
                      {getFileExtension(item.original_filename)}
                    </span>
                    {item.is_hidden && (
                      <span className="att-thumb-internal-pill">
                        {t("internal_pill")}
                      </span>
                    )}
                  </button>
                  <div className="att-thumb-name">
                    {downloadingAttachmentId === item.id
                      ? t("downloading")
                      : item.original_filename}
                  </div>
                  <div className="att-thumb-size">
                    {formatBytes(item.file_size)} ·{" "}
                    {formatDate(item.created_at)}
                  </div>
                </div>
              ))}

              <label className="att-thumb-upload">
                <UploadCloud size={22} strokeWidth={2} />
                <span>
                  {selectedFile ? t("replace_selection") : t("upload_file")}
                </span>
                <input
                  type="file"
                  accept={ACCEPTED_ATTACHMENT_TYPES}
                  onChange={handleFileChange}
                  disabled={uploadingAttachment}
                />
              </label>
            </div>

            {selectedFile && (
              <form
                className="att-thumb-staged"
                onSubmit={submitAttachment}
              >
                <span className="att-thumb-staged-text">
                  {t("selected")} <b>{selectedFile.name}</b> ·{" "}
                  {formatBytes(selectedFile.size)}
                </span>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    flexWrap: "wrap",
                  }}
                >
                  {isStaff && (
                    <label className="login-check" style={{ margin: 0 }}>
                      <input
                        type="checkbox"
                        checked={attachmentHidden}
                        onChange={(event) =>
                          setAttachmentHidden(event.target.checked)
                        }
                        disabled={uploadingAttachment}
                      />
                      <span>{t("internal_only")}</span>
                    </label>
                  )}
                  <button
                    type="submit"
                    className="btn btn-primary btn-sm"
                    disabled={uploadingAttachment}
                  >
                    {uploadingAttachment ? t("uploading") : t("upload_button")}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>

        <div className="detail-side">
          <div className="card">
            <div className="section-head">
              <div
                className="section-head-title"
                style={{
                  fontSize: 11,
                  fontWeight: 800,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--text-faint)",
                }}
              >
                {t("card_assignment_title")}
              </div>
            </div>
            <div className="assign-body">
              <div className="assignee-row">
                <div className="assignee-avatar">
                  {getInitials(ticket.assigned_to_email || "unassigned@")}
                </div>
                <div className="assignee-info">
                  <span className="assignee-name">
                    {ticket.assigned_to_email
                      ? humanName(ticket.assigned_to_email, t("unassigned"))
                      : t("unassigned")}
                  </span>
                  <span className="assignee-role">
                    {ticket.assigned_to_email
                      ? t("operations_lead")
                      : t("awaiting_assignment")}
                  </span>
                </div>
              </div>

              {isStaff ? (
                <form
                  onSubmit={submitAssignment}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 10,
                  }}
                >
                  <select
                    className="assign-select"
                    value={selectedAssigneeId}
                    onChange={(event) =>
                      setSelectedAssigneeId(event.target.value)
                    }
                    disabled={assigningTicket}
                  >
                    <option value="">{t("unassigned")}</option>
                    {ticket.assigned_to !== null &&
                      !assignableManagers.some(
                        (m) => m.id === ticket.assigned_to,
                      ) && (
                        <option value={String(ticket.assigned_to)}>
                          {ticket.assigned_to_email ??
                            t("assignment_user_n", {
                              id: ticket.assigned_to,
                            })}
                          {t("assignment_current")}
                        </option>
                      )}
                    {assignableManagers.map((manager) => (
                      <option key={manager.id} value={manager.id}>
                        {manager.full_name?.trim() || manager.email}
                      </option>
                    ))}
                  </select>
                  <button
                    type="submit"
                    className="btn btn-secondary"
                    style={{ width: "100%" }}
                    disabled={
                      assigningTicket ||
                      selectedAssigneeId ===
                        (ticket.assigned_to !== null
                          ? String(ticket.assigned_to)
                          : "")
                    }
                  >
                    <UserPlus size={14} strokeWidth={2} />
                    {assigningTicket ? t("updating") : t("update_assignment")}
                  </button>
                </form>
              ) : null}
            </div>
          </div>

          {/* Sprint 23B — Assigned-staff list. Backend gates the
              contact-visibility per Customer.show_assigned_staff_*
              flags BEFORE returning to a CUSTOMER_USER; we just
              render what the API gives us. An empty array means
              no staff assigned yet. */}
          <div
            className="card"
            data-testid="assigned-staff-card"
          >
            <div className="section-head">
              <div
                className="section-head-title"
                style={{
                  fontSize: 11,
                  fontWeight: 800,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--text-faint)",
                }}
              >
                {t("assigned_staff_title")}
              </div>
            </div>
            <div className="assign-body">
              {ticket.assigned_staff.length === 0 ? (
                <p
                  className="muted small"
                  style={{ padding: "4px 0 12px" }}
                  data-testid="assigned-staff-empty"
                >
                  {t("assigned_staff_empty")}
                </p>
              ) : (
                <ul
                  className="assigned-staff-list"
                  style={{
                    listStyle: "none",
                    margin: 0,
                    padding: 0,
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                  }}
                  data-testid="assigned-staff-list"
                >
                  {ticket.assigned_staff.map((entry, index) => {
                    if ("anonymous" in entry && entry.anonymous) {
                      return (
                        <li
                          key={`anon-${index}`}
                          className="assignee-row"
                          data-testid="assigned-staff-anon"
                        >
                          <div className="assignee-avatar">·</div>
                          <div className="assignee-info">
                            <span className="assignee-name">
                              {t(entry.label_key)}
                            </span>
                          </div>
                        </li>
                      );
                    }
                    const named = entry as {
                      id: number;
                      full_name?: string;
                      email?: string;
                      phone?: string;
                    };
                    const displayName =
                      named.full_name ||
                      (named.email ? named.email.split("@")[0] : "—");
                    return (
                      <li
                        key={named.id}
                        className="assignee-row"
                        data-testid="assigned-staff-item"
                      >
                        <div className="assignee-avatar">
                          {getInitials(displayName)}
                        </div>
                        <div className="assignee-info">
                          <span className="assignee-name">{displayName}</span>
                          <span
                            className="assignee-role"
                            style={{ fontSize: 11 }}
                          >
                            {t("assigned_staff_role")}
                            {named.email ? ` · ${named.email}` : ""}
                            {named.phone ? ` · ${named.phone}` : ""}
                          </span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}

              {/* Sprint 25A — admin/manager direct staff assignment.
                  Same gate as the BUILDING_MANAGER assignment
                  dropdown above (`isStaff` = SUPER_ADMIN /
                  COMPANY_ADMIN / BUILDING_MANAGER). Hidden from
                  CUSTOMER_USER and STAFF. The candidate list is
                  server-filtered to STAFF users with active
                  StaffProfile + BuildingStaffVisibility on this
                  ticket's building. */}
              {isStaff && (() => {
                const assignedIds = new Set(
                  ticket.assigned_staff
                    .filter(
                      (entry) =>
                        !("anonymous" in entry && entry.anonymous),
                    )
                    .map((entry) => (entry as { id: number }).id),
                );
                const candidates = assignableStaff.filter(
                  (staff) => !assignedIds.has(staff.id),
                );
                async function handleAddStaff() {
                  if (!ticket || selectedStaffToAdd === "") return;
                  const staff = assignableStaff.find(
                    (s) => s.id === Number(selectedStaffToAdd),
                  );
                  setAddingStaff(true);
                  setStaffAssignmentError("");
                  setStaffAssignmentBanner("");
                  try {
                    await addTicketStaffAssignment(
                      ticket.id,
                      Number(selectedStaffToAdd),
                    );
                    setSelectedStaffToAdd("");
                    const name =
                      staff?.full_name ||
                      staff?.email ||
                      String(selectedStaffToAdd);
                    setStaffAssignmentBanner(
                      t("assigned_staff_admin_banner_added", { name }),
                    );
                    await loadTicket();
                    await reloadAssignableStaff();
                  } catch (err) {
                    setStaffAssignmentError(getApiError(err));
                  } finally {
                    setAddingStaff(false);
                  }
                }
                async function handleConfirmRemoveStaff() {
                  if (!ticket || !removeStaffTarget) return;
                  setRemovingStaffId(removeStaffTarget.id);
                  setStaffAssignmentError("");
                  try {
                    await removeTicketStaffAssignment(
                      ticket.id,
                      removeStaffTarget.id,
                    );
                    removeStaffDialogRef.current?.close();
                    setStaffAssignmentBanner(
                      t("assigned_staff_admin_banner_removed", {
                        name: removeStaffTarget.name,
                      }),
                    );
                    setRemoveStaffTarget(null);
                    await loadTicket();
                    await reloadAssignableStaff();
                  } catch (err) {
                    setStaffAssignmentError(getApiError(err));
                    removeStaffDialogRef.current?.close();
                  } finally {
                    setRemovingStaffId(null);
                  }
                }
                function openRemoveStaffDialog(staff: {
                  id: number;
                  name: string;
                }) {
                  setRemoveStaffTarget(staff);
                  removeStaffDialogRef.current?.open();
                }
                return (
                  <div
                    data-testid="assigned-staff-admin-block"
                    style={{
                      marginTop: 14,
                      paddingTop: 12,
                      borderTop: "1px solid var(--border)",
                      display: "flex",
                      flexDirection: "column",
                      gap: 8,
                    }}
                  >
                    <div
                      style={{
                        fontSize: 11,
                        fontWeight: 800,
                        letterSpacing: "0.08em",
                        textTransform: "uppercase",
                        color: "var(--text-faint)",
                      }}
                    >
                      {t("assigned_staff_admin_title")}
                    </div>
                    <p className="muted small" style={{ margin: 0 }}>
                      {t("assigned_staff_admin_desc")}
                    </p>

                    {/* Per-assignee remove buttons. Only for non-
                        anonymous rows; if the customer-visibility
                        flags hide the staff identity from a
                        CUSTOMER_USER, this whole block is hidden too
                        (isStaff gate above). */}
                    {ticket.assigned_staff.length > 0 && (
                      <ul
                        data-testid="assigned-staff-admin-list"
                        style={{
                          listStyle: "none",
                          margin: 0,
                          padding: 0,
                          display: "flex",
                          flexDirection: "column",
                          gap: 6,
                        }}
                      >
                        {ticket.assigned_staff.map((entry, index) => {
                          if ("anonymous" in entry && entry.anonymous) {
                            return null;
                          }
                          const named = entry as {
                            id: number;
                            full_name?: string;
                            email?: string;
                          };
                          const displayName =
                            named.full_name ||
                            (named.email
                              ? named.email.split("@")[0]
                              : "—");
                          const isThisRemoving =
                            removingStaffId === named.id;
                          return (
                            <li
                              key={`admin-row-${named.id}-${index}`}
                              data-testid="assigned-staff-admin-row"
                              data-staff-id={named.id}
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                                justifyContent: "space-between",
                                fontSize: 13,
                              }}
                            >
                              <span>{displayName}</span>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                disabled={isThisRemoving || addingStaff}
                                onClick={() =>
                                  openRemoveStaffDialog({
                                    id: named.id,
                                    name: displayName,
                                  })
                                }
                                data-testid="assigned-staff-admin-remove"
                              >
                                {isThisRemoving
                                  ? t("assigned_staff_admin_removing")
                                  : t("assigned_staff_admin_remove_button")}
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    )}

                    {/* Add dropdown + button. */}
                    <div
                      style={{
                        display: "flex",
                        gap: 6,
                        alignItems: "flex-end",
                        flexWrap: "wrap",
                      }}
                    >
                      <select
                        className="field-select"
                        value={selectedStaffToAdd}
                        onChange={(event) =>
                          setSelectedStaffToAdd(event.target.value)
                        }
                        disabled={addingStaff || candidates.length === 0}
                        data-testid="assigned-staff-admin-select"
                        style={{ flex: 1, minWidth: 0 }}
                      >
                        <option value="">
                          {candidates.length === 0
                            ? t("assigned_staff_admin_no_eligible")
                            : t(
                                "assigned_staff_admin_select_placeholder",
                              )}
                        </option>
                        {candidates.map((staff) => (
                          <option key={staff.id} value={String(staff.id)}>
                            {staff.full_name || staff.email}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        disabled={
                          addingStaff || selectedStaffToAdd === ""
                        }
                        onClick={handleAddStaff}
                        data-testid="assigned-staff-admin-add-button"
                      >
                        {addingStaff
                          ? t("assigned_staff_admin_adding")
                          : t("assigned_staff_admin_add_button")}
                      </button>
                    </div>

                    {staffAssignmentBanner && (
                      <p
                        className="muted small"
                        role="status"
                        data-testid="assigned-staff-admin-banner"
                        style={{ margin: 0 }}
                      >
                        {staffAssignmentBanner}
                      </p>
                    )}
                    {staffAssignmentError && (
                      <div
                        className="alert-error"
                        role="alert"
                        style={{ marginTop: 4 }}
                      >
                        {staffAssignmentError}
                      </div>
                    )}

                    <ConfirmDialog
                      ref={removeStaffDialogRef}
                      title={t(
                        "assigned_staff_admin_remove_dialog_title",
                        { name: removeStaffTarget?.name ?? "" },
                      )}
                      body={t(
                        "assigned_staff_admin_remove_dialog_body",
                        { name: removeStaffTarget?.name ?? "" },
                      )}
                      confirmLabel={t(
                        "assigned_staff_admin_remove_button",
                      )}
                      busyLabel={t("assigned_staff_admin_removing")}
                      onConfirm={handleConfirmRemoveStaff}
                      onCancel={() => setRemoveStaffTarget(null)}
                      busy={removingStaffId !== null}
                      destructive
                    />
                  </div>
                );
              })()}

              {/* Sprint 23B — STAFF-only "Request assignment"
                  button. Visible only when:
                    * the viewer's role is STAFF (CUSTOMER_USER and
                      OSIUS-side managers never see it),
                    * the staff user is NOT already assigned to this
                      ticket, and
                    * the local UI hasn't already POSTed a request
                      this session.
                  The backend separately enforces "active staff
                  profile + visibility for the ticket's building"
                  and 400s a duplicate. The UI flips to a friendly
                  message on duplicate so we don't let the user
                  repeatedly POST. */}
              {me?.role === "STAFF" && (() => {
                const alreadyAssigned = ticket.assigned_staff.some(
                  (entry) =>
                    !("anonymous" in entry && entry.anonymous) &&
                    (entry as { id: number }).id === me.id,
                );
                if (alreadyAssigned) return null;
                async function handleRequest() {
                  if (!ticket) return;
                  setRequestAssignmentBusy(true);
                  setRequestAssignmentError("");
                  setRequestAssignmentBanner("");
                  try {
                    const created = await createStaffAssignmentRequest(
                      ticket.id,
                    );
                    setPendingRequestId(created.id);
                    setRequestAssignmentBanner(
                      t("request_assignment_success"),
                    );
                  } catch (err) {
                    const message = getApiError(err);
                    // Backend returns "A pending request already exists."
                    // on duplicates. The pending-discovery effect should
                    // have set pendingRequestId already; flag the duplicate
                    // for clarity and let the next useEffect run catch up
                    // if it raced.
                    if (/pending request/i.test(message)) {
                      setRequestAssignmentError(
                        t("request_assignment_already_pending"),
                      );
                    } else {
                      setRequestAssignmentError(message);
                    }
                  } finally {
                    setRequestAssignmentBusy(false);
                  }
                }
                async function handleConfirmCancel() {
                  if (!pendingRequestId) return;
                  setCancelRequestBusy(true);
                  setRequestAssignmentError("");
                  try {
                    await cancelStaffAssignmentRequest(pendingRequestId);
                    cancelRequestDialogRef.current?.close();
                    setPendingRequestId(null);
                    setRequestAssignmentBanner(
                      t("request_assignment_cancelled_success"),
                    );
                  } catch (err) {
                    setRequestAssignmentError(getApiError(err));
                    cancelRequestDialogRef.current?.close();
                  } finally {
                    setCancelRequestBusy(false);
                  }
                }
                return (
                  <div
                    style={{
                      marginTop: 12,
                      display: "flex",
                      flexDirection: "column",
                      gap: 6,
                    }}
                    data-testid="request-assignment-wrap"
                  >
                    {pendingRequestId !== null ? (
                      // Sprint 24C — pending state with cancel option.
                      <div
                        data-testid="request-assignment-pending"
                        style={{ display: "flex", flexDirection: "column", gap: 6 }}
                      >
                        <p
                          className="muted small"
                          style={{ margin: 0, fontWeight: 600 }}
                        >
                          {t("request_assignment_pending_title")}
                        </p>
                        <p className="muted small" style={{ margin: 0 }}>
                          {t("request_assignment_pending_body")}
                        </p>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          disabled={cancelRequestBusy}
                          onClick={() => cancelRequestDialogRef.current?.open()}
                          data-testid="cancel-request-assignment-button"
                          style={{ alignSelf: "flex-start" }}
                        >
                          {cancelRequestBusy
                            ? t("request_assignment_cancelling")
                            : t("request_assignment_cancel")}
                        </button>
                      </div>
                    ) : (
                      <>
                        <p className="muted small" style={{ margin: 0 }}>
                          {t("request_assignment_hint")}
                        </p>
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          disabled={requestAssignmentBusy}
                          onClick={handleRequest}
                          data-testid="request-assignment-button"
                        >
                          {requestAssignmentBusy
                            ? t("requesting_assignment")
                            : t("request_assignment")}
                        </button>
                      </>
                    )}
                    {requestAssignmentBanner && (
                      <p
                        className="muted small"
                        role="status"
                        data-testid="request-assignment-banner"
                        style={{ marginTop: 4 }}
                      >
                        {requestAssignmentBanner}
                      </p>
                    )}
                    {requestAssignmentError && (
                      <div
                        className="alert-error"
                        role="alert"
                        style={{ marginTop: 6 }}
                      >
                        {requestAssignmentError}
                      </div>
                    )}
                    <ConfirmDialog
                      ref={cancelRequestDialogRef}
                      title={t("request_assignment_cancel_dialog_title")}
                      body={t("request_assignment_cancel_dialog_body")}
                      confirmLabel={t("request_assignment_cancel")}
                      busyLabel={t("request_assignment_cancelling")}
                      onConfirm={handleConfirmCancel}
                      busy={cancelRequestBusy}
                      destructive
                    />
                  </div>
                );
              })()}
            </div>
          </div>

          <div className="card">
            <div className="section-head">
              <div
                className="section-head-title"
                style={{
                  fontSize: 11,
                  fontWeight: 800,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--text-faint)",
                }}
              >
                {t("card_details_title")}
              </div>
            </div>
            <div style={{ padding: "14px 18px 16px" }}>
              <div className="detail-kv-list">
                <div className="detail-kv-row">
                  <span className="detail-kv-label">{t("details_location")}</span>
                  <span className="detail-kv-val">
                    <MapPin size={14} strokeWidth={2} />
                    {ticket.room_label || ticket.building_name}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">{t("details_customer")}</span>
                  <span className="detail-kv-val">
                    <Users size={14} strokeWidth={2} />
                    {ticket.customer_name}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">{t("details_category")}</span>
                  <span className="detail-kv-val">{ticket.type}</span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">{t("details_created_by")}</span>
                  <span className="detail-kv-val">
                    {ticket.created_by_email}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">{t("details_created")}</span>
                  <span className="detail-kv-val">
                    <Clock size={14} strokeWidth={2} />
                    {formatDate(ticket.created_at)}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">{t("details_first_response")}</span>
                  <span className="detail-kv-val">
                    {formatDate(ticket.first_response_at)}
                  </span>
                </div>
                {ticket.sent_for_approval_at && (
                  <div className="detail-kv-row">
                    <span className="detail-kv-label">{t("details_sent_for_approval")}</span>
                    <span className="detail-kv-val">
                      {formatDate(ticket.sent_for_approval_at)}
                    </span>
                  </div>
                )}
                {ticket.approved_at && (
                  <div className="detail-kv-row">
                    <span className="detail-kv-label">{t("details_approved")}</span>
                    <span className="detail-kv-val">
                      {formatDate(ticket.approved_at)}
                    </span>
                  </div>
                )}
                {ticket.closed_at && (
                  <div className="detail-kv-row">
                    <span className="detail-kv-label">{t("details_closed")}</span>
                    <span className="detail-kv-val">
                      {formatDate(ticket.closed_at)}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="section-head">
              <div
                className="section-head-title"
                style={{
                  fontSize: 11,
                  fontWeight: 800,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--text-faint)",
                }}
              >
                {t("card_sla_title")}
              </div>
            </div>
            <div style={{ padding: "16px 18px 18px" }}>
              <div className="sla-detail-row">
                <SLABadge
                  state={ticket.sla_display_state}
                  remainingSeconds={ticket.sla_remaining_business_seconds}
                  size="md"
                />
                <span style={{ color: "var(--text-2)", fontSize: 13 }}>
                  {slaLabel(ticket.sla_display_state)}
                  {ticket.sla_display_state !== "PAUSED" &&
                    ticket.sla_display_state !== "COMPLETED" &&
                    ticket.sla_display_state !== "HISTORICAL" &&
                    ticket.sla_remaining_business_seconds !== null && (
                      <>
                        {" — "}
                        {formatSLATime(
                          ticket.sla_remaining_business_seconds,
                        )}
                      </>
                    )}
                </span>
              </div>
              <div className="sla-detail-meta">
                {ticket.sla_due_at &&
                  ticket.sla_display_state !== "HISTORICAL" &&
                  ticket.sla_display_state !== "COMPLETED" && (
                    <>
                      <span className="sla-detail-meta-label">{t("sla_due_label")}</span>
                      <span className="sla-detail-meta-value">
                        {formatDate(ticket.sla_due_at)}
                      </span>
                    </>
                  )}
                {ticket.sla_paused_at && (
                  <>
                    <span className="sla-detail-meta-label">{t("sla_paused_since_label")}</span>
                    <span className="sla-detail-meta-value">
                      {formatDate(ticket.sla_paused_at)}
                    </span>
                  </>
                )}
                {ticket.sla_first_breached_at && (
                  <>
                    <span className="sla-detail-meta-label">{t("sla_first_breached_label")}</span>
                    <span className="sla-detail-meta-value">
                      {formatDate(ticket.sla_first_breached_at)}
                    </span>
                  </>
                )}
                {ticket.sla_completed_at && (
                  <>
                    <span className="sla-detail-meta-label">{t("sla_completed_label")}</span>
                    <span className="sla-detail-meta-value">
                      {formatDate(ticket.sla_completed_at)}
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="section-head">
              <div
                className="section-head-title"
                style={{
                  fontSize: 11,
                  fontWeight: 800,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--text-faint)",
                }}
              >
                {t("card_workflow_title")}
              </div>
            </div>
            <div className="workflow-body">
              {visibleNextStatuses.length === 0 ? (
                <p className="muted small">
                  {t("workflow_no_transitions")}
                </p>
              ) : (
                <>
                  <div className="field">
                    <label className="field-label" htmlFor="status-note">
                      {me?.role === "CUSTOMER_USER" &&
                      ticket.status === "WAITING_CUSTOMER_APPROVAL" &&
                      visibleNextStatuses.includes("REJECTED")
                        ? t("workflow_rejection_reason_label")
                        : t("workflow_status_note_label")}
                    </label>
                    <input
                      id="status-note"
                      className="field-input"
                      value={statusNote}
                      onChange={(event) => setStatusNote(event.target.value)}
                      placeholder={
                        me?.role === "CUSTOMER_USER" &&
                        ticket.status === "WAITING_CUSTOMER_APPROVAL" &&
                        visibleNextStatuses.includes("REJECTED")
                          ? t("workflow_rejection_reason_placeholder")
                          : t("workflow_status_note_placeholder")
                      }
                    />
                  </div>


                  {pendingAdminDecisionOverride && (
                    <div className="alert-warning">
                      {adminDecisionOverrideMessage(
                        pendingAdminDecisionOverride,
                      )}
                    </div>
                  )}

                  {me?.role === "CUSTOMER_USER" &&
                    ticket.status === "WAITING_CUSTOMER_APPROVAL" &&
                    visibleNextStatuses.includes("REJECTED") && (
                      <div className="alert-warning">
                        {t("workflow_customer_reject_warning")}
                      </div>
                    )}

                  <div className="status-actions">
                    {visibleNextStatuses.map((status) => (
                      <button
                        key={status}
                        type="button"
                        className="status-btn"
                        disabled={statusBusy !== null}
                        onClick={() => changeStatus(status)}
                      >
                        {statusBusy === status ? (
                          t("updating")
                        ) : (
                          <>
                            {t("workflow_move_to", { status: tStatus(status) })}
                            <span className="status-btn-arrow">→</span>
                          </>
                        )}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>

          <div className="card">
            <div className="card-head-icon">
              <span className="card-head-icon-glyph">
                <History size={14} strokeWidth={2.2} />
              </span>
              <span className="card-head-icon-title">
                {t("card_history_title")}
              </span>
              <span className="card-head-icon-spacer" />
              <span
                style={{
                  fontFamily: "var(--f-head)",
                  fontSize: 11,
                  fontWeight: 800,
                  letterSpacing: "0.06em",
                  color: "var(--text-faint)",
                }}
              >
                {ticket.status_history.length}
              </span>
            </div>
            <div className="history-list">
              {ticket.status_history.length === 0 ? (
                <p
                  className="muted small"
                  style={{ padding: "12px 0" }}
                >
                  {t("history_empty")}
                </p>
              ) : (
                ticket.status_history.map((item) => (
                  <div className="history-item" key={item.id}>
                    <div className="history-dot" />
                    <div>
                      <div className="history-change">
                        <span className="from">
                          {tStatus(item.old_status)}
                        </span>
                        <span className="arrow">→</span>
                        <b>{tStatus(item.new_status)}</b>
                      </div>
                      <div className="history-meta">
                        {item.changed_by_email} · {formatDate(item.created_at)}
                      </div>
                      {(() => {
                        const cleaned = sanitizeStatusNote(item.note);
                        return cleaned ? (
                          <div className="history-note">{cleaned}</div>
                        ) : null;
                      })()}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>

          {ticket.priority === "URGENT" && (
            <div className="card">
              <div className="card-head-icon">
                <span
                  className="card-head-icon-glyph"
                  style={{
                    background: "var(--red-soft)",
                    color: "var(--red)",
                  }}
                >
                  <TriangleAlert size={14} strokeWidth={2.2} />
                </span>
                <span className="card-head-icon-title">
                  {t("card_critical_title")}
                </span>
              </div>
              <p
                style={{
                  padding: "0 22px 18px",
                  fontSize: 13,
                  color: "var(--text-2)",
                  lineHeight: 1.55,
                }}
              >
                {t("card_critical_body")}
              </p>
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog
        ref={deleteDialogRef}
        title={t("delete_ticket_dialog_title", {
          ticket_no: ticket.ticket_no,
        })}
        body={
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <p style={{ margin: 0, lineHeight: 1.5 }}>
              {t("delete_ticket_dialog_body")}
            </p>
            <label
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                fontSize: 12,
                color: "var(--text-muted)",
              }}
            >
              <span>{t("delete_ticket_confirm_label")}</span>
              <input
                type="text"
                value={deleteConfirmText}
                onChange={(e) => setDeleteConfirmText(e.target.value)}
                placeholder={ticket.ticket_no ?? ""}
                autoFocus
                style={{
                  height: 34,
                  padding: "0 10px",
                  border: "1px solid var(--border)",
                  borderRadius: 6,
                  fontFamily: "inherit",
                  fontSize: 13,
                }}
              />
            </label>
          </div>
        }
        confirmLabel={t("delete_ticket_confirm_button")}
        busyLabel={t("delete_ticket_confirm_busy")}
        onConfirm={confirmDeleteTicket}
        onCancel={() => setDeleteConfirmText("")}
        busy={deletingTicket}
        confirmDisabled={
          deleteConfirmText.trim() !== (ticket.ticket_no ?? "").trim()
        }
        destructive
      />
    </div>
  );
}
