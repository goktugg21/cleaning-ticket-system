import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, getApiError } from "../api/client";
import type { PaginatedResponse, TicketList } from "../api/types";
import { useAuth } from "../auth/AuthContext";

export function DashboardPage() {
  const { me, logout } = useAuth();
  const [tickets, setTickets] = useState<TicketList[]>([]);
  const [error, setError] = useState("");

  async function loadTickets() {
    try {
      const response = await api.get<PaginatedResponse<TicketList>>("/tickets/");
      setTickets(response.data.results);
    } catch (err) {
      setError(getApiError(err));
    }
  }

  useEffect(() => {
    loadTickets();
  }, []);

  return (
    <main className="page">
      <header className="topbar">
        <div>
          <p className="eyebrow">Dashboard</p>
          <h1>Tickets</h1>
          <p className="muted">
            {me?.email} · {me?.role}
          </p>
        </div>

        <div className="actions">
          <Link className="button secondary" to="/tickets/new">New ticket</Link>
          <button className="secondary" onClick={logout}>Logout</button>
        </div>
      </header>

      {error && <div className="error">{error}</div>}

      <section className="card">
        <div className="table">
          <div className="table-row table-head">
            <span>No</span>
            <span>Title</span>
            <span>Status</span>
            <span>Building</span>
            <span>Customer</span>
          </div>

          {tickets.map((ticket) => (
            <Link to={`/tickets/${ticket.id}`} className="table-row table-link" key={ticket.id}>
              <span>{ticket.ticket_no}</span>
              <span>{ticket.title}</span>
              <span><b className={`badge ${ticket.status.toLowerCase()}`}>{ticket.status}</b></span>
              <span>{ticket.building_name}</span>
              <span>{ticket.customer_name}</span>
            </Link>
          ))}

          {tickets.length === 0 && <p className="empty">No tickets yet.</p>}
        </div>
      </section>
    </main>
  );
}
