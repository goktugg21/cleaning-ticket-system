import type { FormEvent } from "react";
import { useEffect, useState } from "react";
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

export function TicketDetailPage() {
  const { id } = useParams();
  const { me } = useAuth();

  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [messages, setMessages] = useState<TicketMessage[]>([]);
  const [statusNote, setStatusNote] = useState("");
  const [message, setMessage] = useState("");
  const [messageType, setMessageType] = useState<TicketMessageType>("PUBLIC_REPLY");
  const [error, setError] = useState("");

  const isStaff =
    me?.role === "SUPER_ADMIN" ||
    me?.role === "COMPANY_ADMIN" ||
    me?.role === "BUILDING_MANAGER";

  async function loadTicket() {
    if (!id) return;

    const [ticketResponse, messageResponse] = await Promise.all([
      api.get<TicketDetail>(`/tickets/${id}/`),
      api.get<PaginatedResponse<TicketMessage>>(`/tickets/${id}/messages/`),
    ]);

    setTicket(ticketResponse.data);
    setMessages(messageResponse.data.results);
  }

  useEffect(() => {
    loadTicket().catch((err) => setError(getApiError(err)));
  }, [id]);

  async function changeStatus(toStatus: TicketStatus) {
    if (!id) return;
    setError("");

    try {
      const response = await api.post<TicketDetail>(`/tickets/${id}/status/`, {
        to_status: toStatus,
        note: statusNote,
      });
      setTicket(response.data);
      setStatusNote("");
    } catch (err) {
      setError(getApiError(err));
    }
  }

  async function submitMessage(event: FormEvent) {
    event.preventDefault();
    if (!id) return;
    setError("");

    try {
      await api.post(`/tickets/${id}/messages/`, {
        message,
        message_type: isStaff ? messageType : "PUBLIC_REPLY",
      });
      setMessage("");
      await loadTicket();
    } catch (err) {
      setError(getApiError(err));
    }
  }

  if (!ticket) {
    return (
      <main className="page">
        <Link to="/" className="button secondary">Back</Link>
        <p>Loading...</p>
        {error && <div className="error">{error}</div>}
      </main>
    );
  }

  return (
    <main className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">{ticket.ticket_no}</p>
          <h1>{ticket.title}</h1>
          <p className="muted">
            {ticket.building_name} · {ticket.customer_name}
          </p>
        </div>

        <Link className="button secondary" to="/">Back</Link>
      </header>

      {error && <div className="error">{error}</div>}

      <section className="grid detail-grid">
        <div className="card">
          <h2>Ticket</h2>
          <p>{ticket.description}</p>

          <dl className="meta">
            <div><dt>Status</dt><dd><b className={`badge ${ticket.status.toLowerCase()}`}>{ticket.status}</b></dd></div>
            <div><dt>Priority</dt><dd>{ticket.priority}</dd></div>
            <div><dt>Type</dt><dd>{ticket.type}</dd></div>
            <div><dt>Room</dt><dd>{ticket.room_label || "-"}</dd></div>
            <div><dt>Created by</dt><dd>{ticket.created_by_email}</dd></div>
            <div><dt>Assigned to</dt><dd>{ticket.assigned_to_email || "-"}</dd></div>
          </dl>
        </div>

        <div className="card">
          <h2>Workflow</h2>

          <label>
            Status note
            <input
              value={statusNote}
              onChange={(event) => setStatusNote(event.target.value)}
              placeholder="Optional note"
            />
          </label>

          <div className="status-actions">
            {ticket.allowed_next_statuses.map((status) => (
              <button key={status} onClick={() => changeStatus(status)}>
                Move to {status}
              </button>
            ))}

            {ticket.allowed_next_statuses.length === 0 && (
              <p className="muted">No allowed next status for your role.</p>
            )}
          </div>
        </div>
      </section>

      <section className="grid detail-grid">
        <div className="card">
          <h2>Messages</h2>

          <div className="messages">
            {messages.map((item) => (
              <article className={`message ${item.message_type === "INTERNAL_NOTE" ? "internal" : ""}`} key={item.id}>
                <div className="message-head">
                  <b>{item.author_email}</b>
                  <span>{item.message_type}</span>
                </div>
                <p>{item.message}</p>
              </article>
            ))}

            {messages.length === 0 && <p className="empty">No messages yet.</p>}
          </div>
        </div>

        <div className="card">
          <h2>Add message</h2>

          <form className="form" onSubmit={submitMessage}>
            {isStaff && (
              <label>
                Message type
                <select
                  value={messageType}
                  onChange={(event) => setMessageType(event.target.value as TicketMessageType)}
                >
                  <option value="PUBLIC_REPLY">PUBLIC_REPLY</option>
                  <option value="INTERNAL_NOTE">INTERNAL_NOTE</option>
                </select>
              </label>
            )}

            <label>
              Message
              <textarea
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                required
              />
            </label>

            <button>Send message</button>
          </form>
        </div>
      </section>

      <section className="card">
        <h2>Status history</h2>
        <div className="history">
          {ticket.status_history.map((item) => (
            <div className="history-item" key={item.id}>
              <b>{item.old_status} → {item.new_status}</b>
              <span>{item.changed_by_email}</span>
              <p>{item.note || "-"}</p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
