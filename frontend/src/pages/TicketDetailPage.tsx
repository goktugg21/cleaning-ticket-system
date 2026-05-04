import type { ChangeEvent, FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ChevronLeft,
  Clock,
  History,
  MapPin,
  MessageSquare,
  Paperclip,
  TriangleAlert,
  UploadCloud,
  UserPlus,
  Users,
} from "lucide-react";
import { api, getApiError } from "../api/client";
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

const STATUS_LABEL: Record<TicketStatus, string> = {
  OPEN: "Open",
  IN_PROGRESS: "In progress",
  WAITING_CUSTOMER_APPROVAL: "Waiting approval",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  CLOSED: "Closed",
  REOPENED_BY_ADMIN: "Reopened",
};

const SUPER_ADMIN_UI_NEXT_STATUS: Record<TicketStatus, TicketStatus[]> = {
  OPEN: ["IN_PROGRESS"],
  IN_PROGRESS: ["WAITING_CUSTOMER_APPROVAL"],
  WAITING_CUSTOMER_APPROVAL: ["APPROVED", "REJECTED"],
  APPROVED: ["CLOSED"],
  CLOSED: ["REOPENED_BY_ADMIN"],
  REJECTED: ["IN_PROGRESS"],
  REOPENED_BY_ADMIN: ["IN_PROGRESS"],
};

function getVisibleWorkflowStatuses(
  ticket: TicketDetail,
  role?: string,
): TicketStatus[] {
  if (role === "SUPER_ADMIN") {
    return SUPER_ADMIN_UI_NEXT_STATUS[ticket.status] ?? [];
  }

  return ticket.allowed_next_statuses;
}

function isAdminCustomerDecisionOverride(
  currentStatus: TicketStatus,
  nextStatus: TicketStatus,
  role?: string,
): boolean {
  return (
    role === "SUPER_ADMIN" &&
    currentStatus === "WAITING_CUSTOMER_APPROVAL" &&
    (nextStatus === "APPROVED" || nextStatus === "REJECTED")
  );
}

function adminDecisionOverrideMessage(nextStatus: TicketStatus): string {
  if (nextStatus === "APPROVED") {
    return "Normally the customer should approve this ticket. Click the button again to approve it as Super Admin override.";
  }

  if (nextStatus === "REJECTED") {
    return "Normally the customer should reject this ticket and explain why. Click the button again to reject it as Super Admin override.";
  }

  return "";
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

function humanName(email: string | null | undefined): string {
  if (!email) return "Unassigned";
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

function getStatusLabel(status: string | null): string {
  if (!status) return "Created";
  return STATUS_LABEL[status as TicketStatus] ?? status;
}

function priorityLabelLong(priority: string): string {
  switch (priority) {
    case "URGENT":
      return "Critical Priority";
    case "HIGH":
      return "High Priority";
    default:
      return "Normal Priority";
  }
}


// TODO(backend): replace with GET /api/tickets/:id/sla — UI derives SLA targets
// from priority until backend exposes a real SLA tracker payload.
function deriveSlaSummary(priority: string): {
  target: string;
  consumedPct: number;
  consumedLabel: string;
  level: string;
} {
  switch (priority) {
    case "URGENT":
      return {
        target: "1 h",
        consumedPct: 78,
        consumedLabel: "1 h 14 m",
        level: "Critical",
      };
    case "HIGH":
      return {
        target: "4 h",
        consumedPct: 52,
        consumedLabel: "3 h 22 m",
        level: "High",
      };
    case "LOW":
      return {
        target: "48 h",
        consumedPct: 24,
        consumedLabel: "11 h 30 m",
        level: "Routine",
      };
    default:
      return {
        target: "24 h",
        consumedPct: 38,
        consumedLabel: "9 h 06 m",
        level: "Standard",
      };
  }
}

export function TicketDetailPage() {
  const { id } = useParams();
  const { me } = useAuth();

  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [messages, setMessages] = useState<TicketMessage[]>([]);
  const [attachments, setAttachments] = useState<TicketAttachment[]>([]);

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

  const [error, setError] = useState("");

  const isStaff =
    me?.role === "SUPER_ADMIN" ||
    me?.role === "COMPANY_ADMIN" ||
    me?.role === "BUILDING_MANAGER";



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

  const sla = useMemo(
    () => (ticket ? deriveSlaSummary(ticket.priority) : null),
    [ticket],
  );

  const visibleNextStatuses = useMemo(
    () => (ticket ? getVisibleWorkflowStatuses(ticket, me?.role) : []),
    [ticket, me?.role],
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
      setError("Please write the rejection reason in the status note field first.");
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
      setError("Attachment file size cannot exceed 10 MB.");
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
      setError("Attachment file size cannot exceed 10 MB.");
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
          Back to tickets
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
          Back to tickets
        </Link>
        <div className="alert-error">{error || "Ticket not found."}</div>
      </div>
    );
  }

  return (
    <div>
      <div className="detail-header">
        <Link to="/" className="link-back">
          <ChevronLeft size={14} strokeWidth={2.5} />
          Back to tickets
        </Link>
        <div className="detail-header-meta">
          <span className="detail-header-no">{ticket.ticket_no}</span>
          <span className={`badge badge-${ticket.priority.toLowerCase()}`}>
            {priorityLabelLong(ticket.priority)}
          </span>
          <span className={`badge badge-${ticket.status.toLowerCase()}`}>
            {STATUS_LABEL[ticket.status]}
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
              <span className="card-head-icon-title">Activity Timeline</span>
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
                      <b>{humanName(ticket.created_by_email)}</b> created the
                      ticket.
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
                        <b>{humanName(entry.changed_by_email)}</b>
                        {entry.old_status ? (
                          <>
                            {" "}changed status from{" "}
                            <span
                              className={`pill ${entry.old_status === "OPEN" ? "open" : "progress"}`}
                            >
                              {getStatusLabel(entry.old_status)}
                            </span>{" "}
                            to{" "}
                            <span className="pill progress">
                              {getStatusLabel(entry.new_status)}
                            </span>
                          </>
                        ) : (
                          <>
                            {" "}created the ticket as{" "}
                            <span className="pill progress">
                              {getStatusLabel(entry.new_status)}
                            </span>
                          </>
                        )}
                        {entry.note ? `. ${entry.note}` : "."}
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
                Messages &amp; internal notes
              </span>
            </div>
            <form className="notes-composer-body" onSubmit={submitMessage}>
              <textarea
                className="notes-textarea"
                placeholder={
                  isStaff && messageType === "INTERNAL_NOTE"
                    ? "Internal note — not visible to customers."
                    : "Write a reply…"
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
                        Public reply
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
                        Internal note
                      </button>
                    </div>
                  )}
                </div>
                <button
                  type="submit"
                  className="btn btn-primary btn-sm"
                  disabled={sendingMessage || !message.trim()}
                >
                  {sendingMessage ? "Sending…" : "Post message"}
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
                No messages yet. Be the first to reply.
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
                        {humanName(item.author_email)}
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
                          ? "Internal note"
                          : "Public reply"}
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
              <span className="card-head-icon-title">Attachments</span>
              <span className="card-head-icon-spacer" />
              <span className="card-head-icon-link">
                {attachments.length} file{attachments.length === 1 ? "" : "s"}
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
                      <span className="att-thumb-internal-pill">Internal</span>
                    )}
                  </button>
                  <div className="att-thumb-name">
                    {downloadingAttachmentId === item.id
                      ? "Downloading…"
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
                  {selectedFile ? "Replace selection" : "Upload File"}
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
                  Selected: <b>{selectedFile.name}</b> ·{" "}
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
                      <span>Internal only</span>
                    </label>
                  )}
                  <button
                    type="submit"
                    className="btn btn-primary btn-sm"
                    disabled={uploadingAttachment}
                  >
                    {uploadingAttachment ? "Uploading…" : "Upload"}
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
                Assignment
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
                      ? humanName(ticket.assigned_to_email)
                      : "Unassigned"}
                  </span>
                  <span className="assignee-role">
                    {ticket.assigned_to_email
                      ? "Operations lead"
                      : "Awaiting assignment"}
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
                    <option value="">Unassigned</option>
                    {ticket.assigned_to !== null &&
                      !assignableManagers.some(
                        (m) => m.id === ticket.assigned_to,
                      ) && (
                        <option value={String(ticket.assigned_to)}>
                          {ticket.assigned_to_email ??
                            `User #${ticket.assigned_to}`}
                          {" (current)"}
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
                    {assigningTicket ? "Updating…" : "Update assignment"}
                  </button>
                </form>
              ) : null}
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
                Ticket details
              </div>
            </div>
            <div style={{ padding: "14px 18px 16px" }}>
              <div className="detail-kv-list">
                <div className="detail-kv-row">
                  <span className="detail-kv-label">Location</span>
                  <span className="detail-kv-val">
                    <MapPin size={14} strokeWidth={2} />
                    {ticket.room_label || ticket.building_name}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">Customer</span>
                  <span className="detail-kv-val">
                    <Users size={14} strokeWidth={2} />
                    {ticket.customer_name}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">Category</span>
                  <span className="detail-kv-val">{ticket.type}</span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">Created by</span>
                  <span className="detail-kv-val">
                    {ticket.created_by_email}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">Created</span>
                  <span className="detail-kv-val">
                    <Clock size={14} strokeWidth={2} />
                    {formatDate(ticket.created_at)}
                  </span>
                </div>
                <div className="detail-kv-row">
                  <span className="detail-kv-label">First response</span>
                  <span className="detail-kv-val">
                    {formatDate(ticket.first_response_at)}
                  </span>
                </div>
                {ticket.sent_for_approval_at && (
                  <div className="detail-kv-row">
                    <span className="detail-kv-label">Sent for approval</span>
                    <span className="detail-kv-val">
                      {formatDate(ticket.sent_for_approval_at)}
                    </span>
                  </div>
                )}
                {ticket.approved_at && (
                  <div className="detail-kv-row">
                    <span className="detail-kv-label">Approved</span>
                    <span className="detail-kv-val">
                      {formatDate(ticket.approved_at)}
                    </span>
                  </div>
                )}
                {ticket.closed_at && (
                  <div className="detail-kv-row">
                    <span className="detail-kv-label">Closed</span>
                    <span className="detail-kv-val">
                      {formatDate(ticket.closed_at)}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>

          {sla && (
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
                  SLA tracker
                </div>
              </div>
              <div style={{ padding: "16px 18px 18px" }}>
                <div className="sla-tracker-row">
                  <span className="sla-tracker-label">Resolution time</span>
                  <span className="sla-tracker-value">
                    {sla.consumedLabel}
                  </span>
                </div>
                <div className="sla-bar">
                  <div
                    className="sla-bar-fill"
                    style={{ width: `${sla.consumedPct}%` }}
                  />
                </div>
                <div className="sla-tracker-foot">
                  Target: {sla.target} · {sla.level}
                </div>
              </div>
            </div>
          )}

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
                Workflow
              </div>
            </div>
            <div className="workflow-body">
              {visibleNextStatuses.length === 0 ? (
                <p className="muted small">
                  No status transitions available for your role.
                </p>
              ) : (
                <>
                  <div className="field">
                    <label className="field-label" htmlFor="status-note">
                      {me?.role === "CUSTOMER_USER" &&
                      ticket.status === "WAITING_CUSTOMER_APPROVAL" &&
                      visibleNextStatuses.includes("REJECTED")
                        ? "Rejection reason (required if rejecting)"
                        : "Status note (optional)"}
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
                          ? "Explain why you reject this ticket"
                          : "Add a short note for the audit trail"
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
                        If you reject this ticket, please write the reason in
                        the status note field first.
                      </div>
                    )}

                  <div className="status-actions">
                    {visibleNextStatuses.map((status) => {
                      const isOverrideConfirm =
                        pendingAdminDecisionOverride &&
                        ticket.status === "WAITING_CUSTOMER_APPROVAL" &&
                        status === "APPROVED" &&
                        (me?.role === "SUPER_ADMIN" ||
                          me?.role === "COMPANY_ADMIN");

                      return (
                        <button
                          key={status}
                          type="button"
                          className="status-btn"
                          disabled={statusBusy !== null}
                          onClick={() => changeStatus(status)}
                        >
                          {statusBusy === status ? (
                            "Updating…"
                          ) : (
                            <>
                              {isOverrideConfirm
                                ? <>
                              Move to {STATUS_LABEL[status]}
                              <span className="status-btn-arrow">→</span>
                            </>
                                : `Move to ${STATUS_LABEL[status]}`}
                              <span className="status-btn-arrow">→</span>
                            </>
                          )}
                        </button>
                      );
                    })}
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
              <span className="card-head-icon-title">Status history</span>
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
                  No status changes yet.
                </p>
              ) : (
                ticket.status_history.map((item) => (
                  <div className="history-item" key={item.id}>
                    <div className="history-dot" />
                    <div>
                      <div className="history-change">
                        <span className="from">
                          {getStatusLabel(item.old_status)}
                        </span>
                        <span className="arrow">→</span>
                        <b>{getStatusLabel(item.new_status)}</b>
                      </div>
                      <div className="history-meta">
                        {item.changed_by_email} · {formatDate(item.created_at)}
                      </div>
                      {item.note && (
                        <div className="history-note">{item.note}</div>
                      )}
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
                <span className="card-head-icon-title">Critical priority</span>
              </div>
              <p
                style={{
                  padding: "0 22px 18px",
                  fontSize: 13,
                  color: "var(--text-2)",
                  lineHeight: 1.55,
                }}
              >
                This ticket is flagged urgent. Prioritise dispatch and update
                the customer once an operator is on site.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
