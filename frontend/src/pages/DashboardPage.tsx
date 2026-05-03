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
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
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

  return (
    <>
      <header className="page-head">
        <div>
          <p className="eyebrow">Dashboard</p>
          <h1>Tickets</h1>
          <p className="muted">
            {loading
              ? "Loading…"
              : `${count} total · ${tickets.length} shown · page ${page} of ${pageCount}`}
          </p>
        </div>

        <div className="actions">
          <button
            type="button"
            className="secondary"
            onClick={loadTickets}
            disabled={loading}
          >
            ⟳ Refresh
          </button>
          <Link className="button" to="/tickets/new">
            ＋ New ticket
          </Link>
        </div>
      </header>

      <section className="card">
        <form className="filter-bar" onSubmit={handleSearchSubmit}>
          <label className="filter">
            <span>Status</span>
            <select
              value={statusFilter}
              onChange={(event) =>
                handleStatusChange(event.target.value as TicketStatus | "")
              }
            >
              <option value="">All</option>
              {STATUS_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {STATUS_LABEL[option]}
                </option>
              ))}
            </select>
          </label>

          <label className="filter">
            <span>Priority</span>
            <select
              value={priorityFilter}
              onChange={(event) =>
                handlePriorityChange(event.target.value as Priority | "")
              }
            >
              <option value="">All</option>
              {PRIORITY_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <label className="filter filter-grow">
            <span>Search</span>
            <input
              type="search"
              placeholder="Ticket no, title, description…"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </label>

          <div className="filter-actions">
            <button type="submit" className="secondary">
              Apply
            </button>
            {hasActiveFilters && (
              <button type="button" className="ghost" onClick={clearFilters}>
                Clear
              </button>
            )}
          </div>
        </form>
      </section>

      {error && <div className="error">{error}</div>}

      <section className="card">
        <div className="table">
          <div className="table-row table-head">
            <span>No</span>
            <span>Title</span>
            <span>Status</span>
            <span>Priority</span>
            <span>Building</span>
            <span>Customer</span>
            <span>Created</span>
          </div>

          {tickets.map((ticket) => (
            <Link
              to={`/tickets/${ticket.id}`}
              className="table-row table-link"
              key={ticket.id}
            >
              <span className="mono">{ticket.ticket_no}</span>
              <span className="cell-strong">{ticket.title}</span>
              <span>
                <b className={`badge status-${ticket.status.toLowerCase()}`}>
                  {STATUS_LABEL[ticket.status]}
                </b>
              </span>
              <span>
                <b className={`badge priority-${ticket.priority.toLowerCase()}`}>
                  {ticket.priority}
                </b>
              </span>
              <span>{ticket.building_name}</span>
              <span>{ticket.customer_name}</span>
              <span className="muted small">{formatDate(ticket.created_at)}</span>
            </Link>
          ))}

          {!loading && tickets.length === 0 && (
            <p className="empty">
              {hasActiveFilters
                ? "No tickets match the current filters."
                : "No tickets yet."}
            </p>
          )}
        </div>

        <div className="pagination">
          <button
            type="button"
            className="secondary"
            disabled={loading || !previous || page <= 1}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
          >
            ← Previous
          </button>

          <span className="muted small">
            Page {page} of {pageCount}
          </span>

          <button
            type="button"
            className="secondary"
            disabled={loading || !next}
            onClick={() => setPage((current) => current + 1)}
          >
            Next →
          </button>
        </div>
      </section>
    </>
  );
}
