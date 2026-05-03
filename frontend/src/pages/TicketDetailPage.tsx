import type { FormEvent } from "react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, getApiError } from "../api/client";
import type {
  PaginatedResponse,
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

function formatDate(value: string | null): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export function TicketDetailPage() {
  const { id } = useParams();
  const { me } = useAuth();

  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [messages, setMessages] = useState<TicketMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusNote, setStatusNote] = useState("");
  const [statusBusy, setStatusBusy] = useState<TicketStatus | null>(null);
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState<TicketMessageType>("PUBLIC_REPLY");
  const [sendingMessage, setSendingMessage] = useState(false);
  const [error, setError] = useState("");

  const isStaff =
    me?.role === "SUPER_ADMIN" ||
    me?.role === "COMPANY_ADMIN" ||
    me?.role === "BUILDING_MANAGER";

  const loadTicket = useCallback(async () => {
    if (!id) return;
    try {
      const [ticketResponse, messageResponse] = await Promise.all([
        api.get<TicketDetail>(`/tickets/${id}/`),
        api.get<PaginatedResponse<TicketMessage>>(`/tickets/${id}/messages/`),
      ]);
      setTicket(ticketResponse.data);
      setMessages(messageResponse.data.results);
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

  async function changeStatus(toStatus: TicketStatus) {
    if (!id) return;
    setError("");
    setStatusBusy(toStatus);
    try {
      const response = await api.post<TicketDetail>(`/tickets/${id}/status/`, {
        to_status: toStatus,
        note: statusNote,
      });
      setTicket(response.data);
      setStatusNote("");
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

  if (loading && !ticket) {
    return (
      <>
        <header className="page-head">
          <Link to="/" className="link-back">
            ← Back to tickets
          </Link>
        </header>
        <p className="muted">Loading ticket…</p>
        {error && <div className="error">{error}</div>}
      </>
    );
  }

  if (!ticket) {
    return (
      <>
        <header className="page-head">
          <Link to="/" className="link-back">
            ← Back to tickets
          </Link>
        </header>
        <div className="error">{error || "Ticket not found."}</div>
      </>
    );
  }

  return (
    <>
      <header className="page-head">
        <div>
          <Link to="/" className="link-back">
            ← Back to tickets
          </Link>
          <p className="eyebrow mono">{ticket.ticket_no}</p>
          <h1>{ticket.title}</h1>
          <p className="muted">
            {ticket.building_name} · {ticket.customer_name}
          </p>
        </div>

        <div className="actions">
          <span className={`badge status-${ticket.status.toLowerCase()} large`}>
            {STATUS_LABEL[ticket.status]}
          </span>
          <span className={`badge priority-${ticket.priority.toLowerCase()} large`}>
            {ticket.priority}
          </span>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      <div className="grid detail-grid">
        <section className="card">
          <h2>Description</h2>
          <p className="ticket-description">{ticket.description}</p>

          <dl className="meta">
            <div>
              <dt>Type</dt>
              <dd>{ticket.type}</dd>
            </div>
            <div>
              <dt>Room</dt>
              <dd>{ticket.room_label || "—"}</dd>
            </div>
            <div>
              <dt>Created by</dt>
              <dd>{ticket.created_by_email}</dd>
            </div>
            <div>
              <dt>Assigned to</dt>
              <dd>{ticket.assigned_to_email || "—"}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{formatDate(ticket.created_at)}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd>{formatDate(ticket.updated_at)}</dd>
            </div>
            <div>
              <dt>First response</dt>
              <dd>{formatDate(ticket.first_response_at)}</dd>
            </div>
            <div>
              <dt>Sent for approval</dt>
              <dd>{formatDate(ticket.sent_for_approval_at)}</dd>
            </div>
            <div>
              <dt>Approved</dt>
              <dd>{formatDate(ticket.approved_at)}</dd>
            </div>
            <div>
              <dt>Closed</dt>
              <dd>{formatDate(ticket.closed_at)}</dd>
            </div>
          </dl>
        </section>

        <section className="card">
          <h2>Workflow</h2>

          {ticket.allowed_next_statuses.length === 0 ? (
            <p className="muted">No status transitions available for your role.</p>
          ) : (
            <>
              <label>
                <span>Status note (optional)</span>
                <input
                  value={statusNote}
                  onChange={(event) => setStatusNote(event.target.value)}
                  placeholder="Add a short note for the audit trail"
                />
              </label>

              <div className="status-actions">
                {ticket.allowed_next_statuses.map((status) => (
                  <button
                    key={status}
                    onClick={() => changeStatus(status)}
                    disabled={statusBusy !== null}
                    className={`status-btn status-${status.toLowerCase()}`}
                  >
                    {statusBusy === status
                      ? "Updating…"
                      : `Move to ${STATUS_LABEL[status]}`}
                  </button>
                ))}
              </div>
            </>
          )}
        </section>
      </div>

      <section className="card">
        <h2>Messages</h2>

        <div className="messages">
          {messages.length === 0 && (
            <p className="empty">No messages yet. Be the first to reply.</p>
          )}

          {messages.map((item) => (
            <article
              className={`message ${
                item.message_type === "INTERNAL_NOTE" ? "internal" : ""
              }`}
              key={item.id}
            >
              <div className="message-head">
                <b>{item.author_email}</b>
                <span>
                  {item.message_type === "INTERNAL_NOTE"
                    ? "Internal note"
                    : "Public reply"}{" "}
                  · {formatDate(item.created_at)}
                </span>
              </div>
              <p>{item.message}</p>
            </article>
          ))}
        </div>

        <form className="form message-form" onSubmit={submitMessage}>
          {isStaff && (
            <fieldset className="message-type-toggle">
              <legend className="sr-only">Message type</legend>
              <label className={messageType === "PUBLIC_REPLY" ? "active" : ""}>
                <input
                  type="radio"
                  name="message_type"
                  value="PUBLIC_REPLY"
                  checked={messageType === "PUBLIC_REPLY"}
                  onChange={() => setMessageType("PUBLIC_REPLY")}
                />
                Public reply
              </label>
              <label className={messageType === "INTERNAL_NOTE" ? "active" : ""}>
                <input
                  type="radio"
                  name="message_type"
                  value="INTERNAL_NOTE"
                  checked={messageType === "INTERNAL_NOTE"}
                  onChange={() => setMessageType("INTERNAL_NOTE")}
                />
                Internal note
              </label>
            </fieldset>
          )}

          <label>
            <span>Your message</span>
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder={
                isStaff && messageType === "INTERNAL_NOTE"
                  ? "Internal note — not visible to customer users."
                  : "Write a reply…"
              }
              required
            />
          </label>

          <div className="actions">
            <button disabled={sendingMessage || !message.trim()}>
              {sendingMessage ? "Sending…" : "Send message"}
            </button>
          </div>
        </form>
      </section>

      <section className="card">
        <h2>Status history</h2>
        <div className="history">
          {ticket.status_history.length === 0 && (
            <p className="empty">No status changes yet.</p>
          )}
          {ticket.status_history.map((item) => (
            <div className="history-item" key={item.id}>
              <b>
                {item.old_status || "—"} → {item.new_status}
              </b>
              <span>
                {item.changed_by_email} · {formatDate(item.created_at)}
              </span>
              <p>{item.note || "—"}</p>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}
