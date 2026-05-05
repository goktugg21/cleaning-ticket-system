import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { api, getApiError } from "../api/client";
import type {
  PaginatedResponse,
  TicketList,
  TicketStats,
  TicketStatsByBuildingResponse,
  TicketStatsByBuildingRow,
  TicketStatus,
} from "../api/types";

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

function priorityCellClass(priority: string): string {
  return `cell-tag cell-tag-${priority.toLowerCase()}`;
}

function statusCellClass(status: TicketStatus): string {
  return `cell-tag cell-tag-${status.toLowerCase()}`;
}

function priorityLabel(priority: string): string {
  if (!priority) return "Normal";
  return priority.charAt(0) + priority.slice(1).toLowerCase();
}

export function DashboardPage() {
  const navigate = useNavigate();
  const [tickets, setTickets] = useState<TicketList[]>([]);
  const [count, setCount] = useState(0);
  const [next, setNext] = useState<string | null>(null);
  const [previous, setPrevious] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const [stats, setStats] = useState<TicketStats | null>(null);
  const [byBuilding, setByBuilding] = useState<TicketStatsByBuildingRow[] | null>(
    null,
  );

  const [statusFilter, setStatusFilter] = useState<TicketStatus | "">("");
  const [priorityFilter, setPriorityFilter] = useState<Priority | "">("");
  const [searchInput, setSearchInput] = useState("");
  const [searchActive, setSearchActive] = useState("");

  const pageCount = Math.max(1, Math.ceil(count / PAGE_SIZE));

  const queryParams = useMemo(() => {
    const params: Record<string, string | number> = { page };
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

  const loadStats = useCallback(async () => {
    try {
      const response = await api.get<TicketStats>("/tickets/stats/");
      setStats(response.data);
    } catch {
      // Stats card just goes blank if the endpoint fails; ticket list still works.
    }
  }, []);

  const loadStatsByBuilding = useCallback(async () => {
    try {
      const response = await api.get<TicketStatsByBuildingResponse>(
        "/tickets/stats/by-building/",
      );
      setByBuilding(response.data);
    } catch {
      // Same posture as loadStats: card empties out if the endpoint fails.
    }
  }, []);

  useEffect(() => {
    loadStats();
    loadStatsByBuilding();
  }, [loadStats, loadStatsByBuilding]);

  function handleSearchSubmit(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setSearchActive(searchInput);
  }

  function clearFilters() {
    setPage(1);
    setStatusFilter("");
    setPriorityFilter("");
    setSearchInput("");
    setSearchActive("");
  }

  const hasActiveFilters = Boolean(
    statusFilter || priorityFilter || searchActive,
  );

  const kpis = useMemo(() => {
    if (stats) {
      const closed = stats.by_status.CLOSED ?? 0;
      const active = stats.my_open;
      return {
        active,
        waitingApproval: stats.waiting_customer_approval,
        urgent: stats.urgent,
        closed,
        total: stats.total,
      };
    }
    return null;
  }, [stats]);

  const focusItems = useMemo(
    () =>
      tickets
        .filter((t) => t.priority === "URGENT" || t.priority === "HIGH")
        .filter(
          (t) =>
            t.status !== "CLOSED" &&
            t.status !== "APPROVED" &&
            t.status !== "REJECTED",
        )
        .slice(0, 4),
    [tickets],
  );

  return (
    <div>
      <div className="page-header">
        <div>
          <nav className="breadcrumb" aria-label="Breadcrumb">
            <span>Site</span>
            <span className="breadcrumb-sep">›</span>
            <span>Operations</span>
            <span className="breadcrumb-sep">›</span>
            <span className="breadcrumb-current">Tickets overview</span>
          </nav>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            Dashboard
          </div>
          <h2 className="page-title">Ticket Management</h2>
          <p className="page-sub">
            {loading
              ? "Loading operational ticket data…"
              : `${count} total tickets · ${tickets.length} visible · page ${page} of ${pageCount}`}
          </p>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={loadTickets}
            disabled={loading}
          >
            <RefreshCw size={14} strokeWidth={2.5} />
            Refresh
          </button>
          <Link className="btn btn-primary btn-sm" to="/tickets/new">
            <Plus size={14} strokeWidth={2.5} />
            New ticket
          </Link>
        </div>
      </div>

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      <div className="kpi-row">
        <div className="kpi-card">
          <div className="kpi-label">Total in scope</div>
          <div className="kpi-row-2">
            <div className="kpi-value">{kpis ? kpis.total : "—"}</div>
          </div>
          <div className="kpi-meta">All tickets you can access</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Active work</div>
          <div className="kpi-row-2">
            <div className="kpi-value">{kpis ? kpis.active : "—"}</div>
          </div>
          <div className="kpi-meta">Open, in progress, waiting, reopened</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Awaiting approval</div>
          <div className="kpi-row-2">
            <div className="kpi-value">{kpis ? kpis.waitingApproval : "—"}</div>
          </div>
          <div className="kpi-meta">Needs customer response</div>
        </div>
        <div className="kpi-card kpi-urgent">
          <div className="kpi-label">Urgent open</div>
          <div className="kpi-row-2">
            <div className="kpi-value">{kpis ? kpis.urgent : "—"}</div>
          </div>
          <div className="kpi-meta">Urgent tickets not closed</div>
        </div>
      </div>

      <div className="dash-grid">
        <div className="dash-main">
          <div className="card" style={{ overflow: "hidden" }}>
            <div className="section-head">
              <div>
                <div className="section-head-title">
                  Recent operational tickets
                </div>
                <div className="section-head-sub">
                  Live queue from your current permission scope
                </div>
              </div>
              <span
                style={{
                  fontFamily: "var(--f-head)",
                  fontSize: 11,
                  fontWeight: 800,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  color: "var(--green-2)",
                }}
              >
                {tickets.length} rows
              </span>
            </div>

            <form className="filter-bar" onSubmit={handleSearchSubmit}>
              <div className="filter-field">
                <span className="filter-label">Status</span>
                <select
                  className="filter-control"
                  value={statusFilter}
                  onChange={(event) => {
                    setPage(1);
                    setStatusFilter(event.target.value as TicketStatus | "");
                  }}
                >
                  <option value="">All statuses</option>
                  {STATUS_OPTIONS.map((status) => (
                    <option key={status} value={status}>
                      {STATUS_LABEL[status]}
                    </option>
                  ))}
                </select>
              </div>
              <div className="filter-field">
                <span className="filter-label">Priority</span>
                <select
                  className="filter-control"
                  value={priorityFilter}
                  onChange={(event) => {
                    setPage(1);
                    setPriorityFilter(event.target.value as Priority | "");
                  }}
                >
                  <option value="">All priorities</option>
                  {PRIORITY_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {priorityLabel(option)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="filter-field search">
                <span className="filter-label">Search</span>
                <input
                  className="filter-control"
                  type="search"
                  placeholder="Ticket no, title, customer…"
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                />
              </div>
              <div className="filter-actions">
                <button type="submit" className="btn btn-secondary btn-sm">
                  Apply
                </button>
                {hasActiveFilters && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={clearFilters}
                  >
                    Clear
                  </button>
                )}
              </div>
            </form>

            {loading && (
              <div className="loading-bar" style={{ margin: 0 }}>
                <div className="loading-bar-fill" />
              </div>
            )}

            <div className="table-wrap">
              <table className="data-table">
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
                    <tr
                      key={ticket.id}
                      className="ticket-row-clickable"
                      role="link"
                      tabIndex={0}
                      onClick={() => navigate(`/tickets/${ticket.id}`)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          navigate(`/tickets/${ticket.id}`);
                        }
                      }}
                    >
                      <td>
                        <Link to={`/tickets/${ticket.id}`} className="td-id">
                          {ticket.ticket_no}
                        </Link>
                      </td>
                      <td className="td-subject">
                        <Link to={`/tickets/${ticket.id}`}>{ticket.title}</Link>
                      </td>
                      <td>
                        <span className={priorityCellClass(ticket.priority)}>
                          <i />
                          {priorityLabel(ticket.priority)}
                        </span>
                      </td>
                      <td>
                        <span className={statusCellClass(ticket.status)}>
                          <i />
                          {STATUS_LABEL[ticket.status]}
                        </span>
                      </td>
                      <td className="td-facility">{ticket.building_name}</td>
                      <td className="td-customer">{ticket.customer_name}</td>
                      <td className="td-date">
                        {formatDate(ticket.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {!loading && tickets.length === 0 && (
                <div className="empty-state">
                  <div className="empty-icon">＋</div>
                  <div className="empty-title">
                    {hasActiveFilters
                      ? "No matching tickets"
                      : "No tickets yet"}
                  </div>
                  <p className="empty-sub">
                    {hasActiveFilters
                      ? "Try clearing filters or searching for another ticket number, title, or customer."
                      : "Create the first ticket to start tracking requests, complaints, and reports."}
                  </p>
                  {hasActiveFilters ? (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={clearFilters}
                    >
                      Clear filters
                    </button>
                  ) : (
                    <Link className="btn btn-primary btn-sm" to="/tickets/new">
                      Create ticket
                    </Link>
                  )}
                </div>
              )}
            </div>

            <div className="pagination">
              <span className="pagination-info">
                Showing {tickets.length} of {count} tickets · Page {page} of{" "}
                {pageCount}
              </span>
              <div className="pagination-controls">
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={loading || !previous || page <= 1}
                  onClick={() =>
                    setPage((current) => Math.max(1, current - 1))
                  }
                >
                  Previous
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={loading || !next}
                  onClick={() => setPage((current) => current + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="dash-side">
          <div className="card">
            <div className="section-head">
              <div>
                <div className="section-head-title">Status breakdown</div>
                <div className="section-head-sub">All tickets in your scope</div>
              </div>
            </div>
            <div style={{ padding: "14px 18px 18px" }}>
              {!stats ? (
                <p className="muted small">Loading…</p>
              ) : (
                <div className="bld-list">
                  {(
                    [
                      ["OPEN", "Open"],
                      ["IN_PROGRESS", "In progress"],
                      ["WAITING_CUSTOMER_APPROVAL", "Waiting approval"],
                      ["APPROVED", "Approved"],
                      ["REJECTED", "Rejected"],
                      ["CLOSED", "Closed"],
                      ["REOPENED_BY_ADMIN", "Reopened"],
                    ] as const
                  ).map(([key, label]) => {
                    const value = stats.by_status[key] ?? 0;
                    return (
                      <div key={key} className="bld-row-head">
                        <span className="bld-row-name">{label}</span>
                        <span className="bld-row-count">{value}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          <div className="card">
            <div className="section-head">
              <div>
                <div className="section-head-title">Urgent focus</div>
                <div className="section-head-sub">
                  Tickets requiring attention
                </div>
              </div>
              <span
                style={{
                  fontFamily: "var(--f-head)",
                  fontSize: 13,
                  fontWeight: 800,
                  color: "var(--red)",
                }}
              >
                {focusItems.length}
              </span>
            </div>
            <div className="focus-list">
              {focusItems.length > 0 ? (
                focusItems.map((ticket) => (
                  <Link
                    key={ticket.id}
                    to={`/tickets/${ticket.id}`}
                    className="focus-item"
                  >
                    <span className="focus-item-title">{ticket.title}</span>
                    <span className="focus-item-meta">
                      {ticket.building_name} ·{" "}
                      {STATUS_LABEL[ticket.status]}
                    </span>
                  </Link>
                ))
              ) : (
                <p className="focus-empty">
                  No urgent or high priority tickets in current scope.
                </p>
              )}
            </div>
          </div>

          <div className="card">
            <div className="section-head">
              <div>
                <div className="section-head-title">Load by building</div>
                <div className="section-head-sub">Open / in progress / awaiting customer</div>
              </div>
              <span
                style={{
                  fontFamily: "var(--f-head)",
                  fontSize: 11,
                  fontWeight: 700,
                  color: "var(--text-faint)",
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                }}
              >
                {byBuilding ? `${byBuilding.length} sites` : ""}
              </span>
            </div>
            <div style={{ padding: "16px 20px 18px" }}>
              {byBuilding === null ? (
                <p className="muted small">Loading…</p>
              ) : byBuilding.length === 0 ? (
                <p className="muted small">
                  No buildings in your current scope.
                </p>
              ) : (
                <div className="bld-list">
                  {byBuilding.slice(0, 5).map((row) => {
                    const active =
                      row.open + row.in_progress + row.waiting_customer_approval;
                    const total = Math.max(active, 1);
                    return (
                      <div key={row.building_id}>
                        <div className="bld-row-head">
                          <span className="bld-row-name">{row.building_name}</span>
                          <span className="bld-row-count">{active} active</span>
                        </div>
                        <div className="bld-bar">
                          {row.open > 0 && (
                            <div
                              className="bld-bar-seg no"
                              style={{ width: `${(row.open / total) * 100}%` }}
                            />
                          )}
                          {row.in_progress > 0 && (
                            <div
                              className="bld-bar-seg hi"
                              style={{ width: `${(row.in_progress / total) * 100}%` }}
                            />
                          )}
                          {row.waiting_customer_approval > 0 && (
                            <div
                              className="bld-bar-seg urg"
                              style={{
                                width: `${(row.waiting_customer_approval / total) * 100}%`,
                              }}
                            />
                          )}
                        </div>
                        <div className="bld-row-foot">
                          {row.open > 0 && (
                            <span className="no">{row.open} open</span>
                          )}
                          {row.in_progress > 0 && (
                            <span className="hi">{row.in_progress} in progress</span>
                          )}
                          {row.waiting_customer_approval > 0 && (
                            <span className="urg">
                              {row.waiting_customer_approval} awaiting customer
                            </span>
                          )}
                          {row.urgent > 0 && (
                            <span className="urg">{row.urgent} urgent</span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
