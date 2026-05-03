import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, getApiError } from "../api/client";
import type { PaginatedResponse, TicketList, TicketStatus } from "../api/types";

type Priority = "NORMAL" | "HIGH" | "URGENT";

const PAGE_SIZE = 25;

const STATUS_OPTIONS: TicketStatus[] = [
  "OPEN",
  "IN_PROGRESS",
  "WAITING_CUSTOMER_APPROVAL",
  "APPROVED",
  "REJECTED",
  "CLOSED",
  "REOPENED_BY_ADMIN",
];

const PRIORITY_OPTIONS: Priority[] = ["NORMAL", "HIGH", "URGENT"];

const STATUS_LABEL: Record<TicketStatus, string> = {
  OPEN: "Open",
  IN_PROGRESS: "In progress",
  WAITING_CUSTOMER_APPROVAL: "Waiting approval",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  CLOSED: "Closed",
  REOPENED_BY_ADMIN: "Reopened",
};

function formatDate(value: string): string {
  try {
    return new Date(value).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
    });
  } catch {
    return value;
  }
}

function statusClass(status: TicketStatus): string {
  return `badge status-${status.toLowerCase()}`;
}

function priorityClass(priority: Priority): string {
  return `badge priority-${priority.toLowerCase()}`;
}

export function DashboardPage() {
  const [tickets, setTickets] = useState<TicketList[]>([]);
  const [count, setCount] = useState(0);
  const [next, setNext] = useState<string | null>(null);
  const [previous, setPrevious] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const [statusFilter, setStatusFilter] = useState<TicketStatus | "">("");
  const [priorityFilter, setPriorityFilter] = useState<Priority | "">("");
  const [searchInput, setSearchInput] = useState("");
  const [searchActive, setSearchActive] = useState("");

  const pageCount = Math.max(1, Math.ceil(count / PAGE_SIZE));

  const queryParams = useMemo(() => {
    const params: Record<string, string | number> = {
      page,
    };

    if (statusFilter) params.status = statusFilter;
    if (priorityFilter) params.priority = priorityFilter;
    if (searchActive.trim()) params.search = searchActive.trim();

    return params;
  }, [page, statusFilter, priorityFilter, searchActive]);

  const loadTickets = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const response = await api.get<PaginatedResponse<TicketList>>("/tickets/", {
        params: queryParams,
      });

      setTickets(response.data.results);
      setCount(response.data.count);
      setNext(response.data.next);
      setPrevious(response.data.previous);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setLoading(false);
    }
  }, [queryParams]);

  useEffect(() => {
    loadTickets();
  }, [loadTickets]);

  function handleSearchSubmit(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setSearchActive(searchInput);
  }

  function handleStatusChange(value: TicketStatus | "") {
    setPage(1);
    setStatusFilter(value);
  }

  function handlePriorityChange(value: Priority | "") {
    setPage(1);
    setPriorityFilter(value);
  }

  function clearFilters() {
    setPage(1);
    setStatusFilter("");
    setPriorityFilter("");
    setSearchInput("");
    setSearchActive("");
  }

  const hasActiveFilters = Boolean(statusFilter || priorityFilter || searchActive);

  const stats = useMemo(() => {
    const active = tickets.filter((ticket) =>
      ["OPEN", "REOPENED_BY_ADMIN", "IN_PROGRESS"].includes(ticket.status),
    ).length;

    const waitingApproval = tickets.filter(
      (ticket) => ticket.status === "WAITING_CUSTOMER_APPROVAL",
    ).length;

    const urgent = tickets.filter((ticket) => ticket.priority === "URGENT").length;
    const closed = tickets.filter((ticket) => ticket.status === "CLOSED").length;

    return {
      active,
      waitingApproval,
      urgent,
      closed,
      visible: tickets.length,
    };
  }, [tickets]);

  const healthScore = count === 0
    ? 100
    : Math.max(56, Math.min(98, Math.round(((stats.visible - stats.urgent) / Math.max(stats.visible, 1)) * 100)));

  return (
    <>
      <section className="enterprise-dashboard-head">
        <div>
          <nav className="enterprise-breadcrumb">
            <span>Site</span>
            <span>›</span>
            <span>Main campus</span>
            <span>›</span>
            <b>Operations overview</b>
          </nav>

          <p className="enterprise-eyebrow">Dashboard</p>
          <h2>Ticket Management</h2>
          <p>
            {loading
              ? "Loading operational ticket data…"
              : `${count} total tickets · ${tickets.length} visible · page ${page} of ${pageCount}`}
          </p>
        </div>

        <div className="enterprise-head-actions">
          <button
            type="button"
            className="button secondary"
            onClick={loadTickets}
            disabled={loading}
          >
            Refresh
          </button>
          <Link className="button" to="/tickets/new">
            New ticket
          </Link>
        </div>
      </section>

      <section className="enterprise-kpi-grid" aria-label="Ticket summary">
        <article className="enterprise-kpi-card">
          <div>
            <p>Visible tickets</p>
            <strong>{stats.visible}</strong>
            <span>{count} total in current scope</span>
          </div>
          <i>▦</i>
        </article>

        <article className="enterprise-kpi-card">
          <div>
            <p>Active work</p>
            <strong>{stats.active}</strong>
            <span>Open, reopened, or in progress</span>
          </div>
          <i>◷</i>
        </article>

        <article className="enterprise-kpi-card">
          <div>
            <p>Waiting approval</p>
            <strong>{stats.waitingApproval}</strong>
            <span>Needs customer response</span>
          </div>
          <i>✓</i>
        </article>

        <article className="enterprise-kpi-card urgent">
          <div>
            <p>Urgent</p>
            <strong>{stats.urgent}</strong>
            <span>High attention tickets</span>
          </div>
          <i>!</i>
        </article>
      </section>

      <div className="enterprise-dashboard-grid">
        <section className="enterprise-card enterprise-table-card">
          <div className="enterprise-card-head">
            <div>
              <h3>Recent operational tickets</h3>
              <p>Live ticket queue from the current permission scope.</p>
            </div>
            <span>{loading ? "Syncing…" : `${tickets.length} rows`}</span>
          </div>

          <form className="enterprise-filter-bar" onSubmit={handleSearchSubmit}>
            <label>
              <span>Status</span>
              <select
                value={statusFilter}
                onChange={(event) =>
                  handleStatusChange(event.target.value as TicketStatus | "")
                }
              >
                <option value="">All statuses</option>
                {STATUS_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {STATUS_LABEL[option]}
                  </option>
                ))}
              </select>
            </label>

            <label>
              <span>Priority</span>
              <select
                value={priorityFilter}
                onChange={(event) =>
                  handlePriorityChange(event.target.value as Priority | "")
                }
              >
                <option value="">All priorities</option>
                {PRIORITY_OPTIONS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>

            <label className="filter-search">
              <span>Search</span>
              <input
                type="search"
                placeholder="Ticket no, title, description…"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
              />
            </label>

            <div className="filter-actions">
              <button type="submit" className="button secondary compact">
                Apply
              </button>
              {hasActiveFilters && (
                <button type="button" className="button ghost compact" onClick={clearFilters}>
                  Clear
                </button>
              )}
            </div>
          </form>

          {error && <div className="error">{error}</div>}

          <div className="enterprise-table-wrap">
            <table className="enterprise-ticket-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Subject</th>
                  <th>Priority</th>
                  <th>Status</th>
                  <th>Facility</th>
                  <th>Customer</th>
                  <th>Created</th>
                </tr>
              </thead>

              <tbody>
                {tickets.map((ticket) => (
                  <tr key={ticket.id}>
                    <td>
                      <Link to={`/tickets/${ticket.id}`} className="ticket-id">
                        {ticket.ticket_no}
                      </Link>
                    </td>
                    <td>
                      <Link to={`/tickets/${ticket.id}`} className="ticket-subject">
                        {ticket.title}
                      </Link>
                    </td>
                    <td>
                      <span className={priorityClass(ticket.priority as Priority)}>
                        {ticket.priority}
                      </span>
                    </td>
                    <td>
                      <span className={statusClass(ticket.status)}>
                        {STATUS_LABEL[ticket.status]}
                      </span>
                    </td>
                    <td>{ticket.building_name}</td>
                    <td>{ticket.customer_name}</td>
                    <td>{formatDate(ticket.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {!loading && tickets.length === 0 && (
              <div className="enterprise-empty-state">
                <strong>{hasActiveFilters ? "No matching tickets" : "No tickets yet"}</strong>
                <p>
                  {hasActiveFilters
                    ? "Try clearing filters or searching for another ticket number, title, or customer."
                    : "Create the first ticket to start tracking requests, complaints, and reports."}
                </p>
                {hasActiveFilters ? (
                  <button type="button" className="button secondary" onClick={clearFilters}>
                    Clear filters
                  </button>
                ) : (
                  <Link className="button" to="/tickets/new">
                    Create ticket
                  </Link>
                )}
              </div>
            )}
          </div>

          <div className="enterprise-pagination">
            <button
              type="button"
              className="button secondary compact"
              disabled={loading || !previous || page <= 1}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
            >
              Previous
            </button>

            <span>
              Page {page} of {pageCount}
            </span>

            <button
              type="button"
              className="button secondary compact"
              disabled={loading || !next}
              onClick={() => setPage((current) => current + 1)}
            >
              Next
            </button>
          </div>
        </section>

        <aside className="enterprise-side-panel">
          <section className="enterprise-card health-card">
            <div className="enterprise-card-head">
              <div>
                <h3>Facility health</h3>
                <p>Operational queue pressure</p>
              </div>
              <span>Live</span>
            </div>

            <div className="health-ring" style={{ "--score": healthScore } as React.CSSProperties}>
              <div>
                <strong>{healthScore}%</strong>
                <span>Stable</span>
              </div>
            </div>

            <div className="health-split">
              <div>
                <span>Closed</span>
                <strong>{stats.closed}</strong>
              </div>
              <div>
                <span>Urgent</span>
                <strong>{stats.urgent}</strong>
              </div>
            </div>
          </section>

          <section className="enterprise-card focus-card">
            <div className="enterprise-card-head">
              <div>
                <h3>Urgent focus</h3>
                <p>Tickets requiring attention</p>
              </div>
              <span>{stats.urgent}</span>
            </div>

            <div className="focus-list">
              {tickets
                .filter((ticket) => ticket.priority === "URGENT" || ticket.priority === "HIGH")
                .slice(0, 4)
                .map((ticket) => (
                  <Link to={`/tickets/${ticket.id}`} key={ticket.id} className="focus-item">
                    <b>{ticket.title}</b>
                    <span>{ticket.building_name} · {STATUS_LABEL[ticket.status]}</span>
                  </Link>
                ))}

              {tickets.filter((ticket) => ticket.priority === "URGENT" || ticket.priority === "HIGH").length === 0 && (
                <p className="muted small">No urgent or high priority tickets in the visible queue.</p>
              )}
            </div>
          </section>

          <section className="enterprise-card map-card">
            <div className="map-preview">
              <div className="map-grid"></div>
              <div className="map-pin">Main campus</div>
            </div>
            <div className="map-caption">
              <h3>Site distribution</h3>
              <p>Cleaning requests grouped by facility context.</p>
            </div>
          </section>
        </aside>
      </div>
    </>
  );
}
