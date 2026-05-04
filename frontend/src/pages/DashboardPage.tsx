import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
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

interface BuildingLoadRow {
  name: string;
  total: number;
  urgent: number;
  high: number;
  normal: number;
}

// TODO(backend): replace with GET /api/stats/health-score.
// Deterministic UI-side score until backend exposes a health endpoint.
// Formula: 100 - (urgent * 8) - (waitingApproval * 3) - (high * 4), clamped [0, 100].
function deriveHealthScore(tickets: TicketList[]): number {
  if (tickets.length === 0) return 100;

  const openUrgent = tickets.filter(
    (t) =>
      t.priority === "URGENT" &&
      t.status !== "CLOSED" &&
      t.status !== "APPROVED" &&
      t.status !== "REJECTED",
  ).length;
  const openHigh = tickets.filter(
    (t) =>
      t.priority === "HIGH" &&
      t.status !== "CLOSED" &&
      t.status !== "APPROVED" &&
      t.status !== "REJECTED",
  ).length;
  const waitingApproval = tickets.filter(
    (t) => t.status === "WAITING_CUSTOMER_APPROVAL",
  ).length;

  const score = 100 - openUrgent * 8 - waitingApproval * 3 - openHigh * 4;
  return Math.max(0, Math.min(100, score));
}

// TODO(backend): replace with GET /api/stats/load-by-building.
// Derived UI-side from the visible ticket page until backend exposes per-building counts.
function deriveBuildingLoad(tickets: TicketList[]): BuildingLoadRow[] {
  const map = new Map<string, BuildingLoadRow>();

  for (const ticket of tickets) {
    if (
      ticket.status === "CLOSED" ||
      ticket.status === "APPROVED" ||
      ticket.status === "REJECTED"
    ) {
      continue;
    }
    const key = ticket.building_name || "Unassigned";
    const row =
      map.get(key) ?? { name: key, total: 0, urgent: 0, high: 0, normal: 0 };
    row.total += 1;
    if (ticket.priority === "URGENT") row.urgent += 1;
    else if (ticket.priority === "HIGH") row.high += 1;
    else row.normal += 1;
    map.set(key, row);
  }

  return Array.from(map.values()).sort((a, b) => b.total - a.total);
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

  const healthScore = useMemo(() => deriveHealthScore(tickets), [tickets]);
  const buildingLoad = useMemo(() => deriveBuildingLoad(tickets), [tickets]);

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

  const ringRadius = 54;
  const ringCircumference = 2 * Math.PI * ringRadius;
  const ringDash = (healthScore / 100) * ringCircumference;
  const ringRest = ringCircumference - ringDash;

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
          <div className="kpi-label">Visible tickets</div>
          <div className="kpi-row-2">
            <div className="kpi-value">{stats.visible}</div>
          </div>
          <div className="kpi-meta">{count} total in current scope</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Active work</div>
          <div className="kpi-row-2">
            <div className="kpi-value">{stats.active}</div>
          </div>
          <div className="kpi-meta">Open, reopened, or in progress</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">Awaiting approval</div>
          <div className="kpi-row-2">
            <div className="kpi-value">{stats.waitingApproval}</div>
          </div>
          <div className="kpi-meta">Needs customer response</div>
        </div>
        <div className="kpi-card kpi-urgent">
          <div className="kpi-label">Urgent</div>
          <div className="kpi-row-2">
            <div className="kpi-value">{stats.urgent}</div>
          </div>
          <div className="kpi-meta">High attention tickets</div>
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
          <div className="card health-card">
            <div className="section-head">
              <div>
                <div className="section-head-title">Facility health</div>
                <div className="section-head-sub">Queue pressure score</div>
              </div>
              <span
                style={{
                  fontFamily: "var(--f-head)",
                  fontSize: 10,
                  fontWeight: 800,
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                  color: "var(--green-2)",
                  display: "flex",
                  alignItems: "center",
                  gap: 5,
                }}
              >
                <span
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: "50%",
                    background: "var(--green)",
                    display: "inline-block",
                  }}
                />
                Live
              </span>
            </div>
            <div className="health-inner">
              <div className="ring-wrap">
                <svg className="ring-svg" viewBox="0 0 120 120">
                  <circle className="ring-track" cx="60" cy="60" r={ringRadius} />
                  <circle
                    className="ring-fill"
                    cx="60"
                    cy="60"
                    r={ringRadius}
                    strokeDasharray={`${ringDash.toFixed(1)} ${ringRest.toFixed(1)}`}
                  />
                </svg>
                <div className="ring-center">
                  <div className="ring-val">{healthScore}%</div>
                  <div className="ring-label">
                    {healthScore >= 80
                      ? "Stable"
                      : healthScore >= 60
                        ? "Watch"
                        : "Stressed"}
                  </div>
                </div>
              </div>
              <div className="health-stats">
                <div className="health-stat">
                  <div className="health-stat-val">{stats.closed}</div>
                  <div className="health-stat-label">Closed</div>
                </div>
                <div className="health-stat">
                  <div
                    className="health-stat-val"
                    style={{ color: "var(--red)" }}
                  >
                    {stats.urgent}
                  </div>
                  <div className="health-stat-label">Urgent</div>
                </div>
              </div>
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
                <div className="section-head-sub">Open tickets, current view</div>
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
                {buildingLoad.length} sites
              </span>
            </div>
            <div style={{ padding: "16px 20px 18px" }}>
              {buildingLoad.length === 0 ? (
                <p className="muted small">
                  No open tickets in the current scope.
                </p>
              ) : (
                <div className="bld-list">
                  {buildingLoad.slice(0, 5).map((row) => {
                    const total = Math.max(row.total, 1);
                    return (
                      <div key={row.name}>
                        <div className="bld-row-head">
                          <span className="bld-row-name">{row.name}</span>
                          <span className="bld-row-count">{row.total} open</span>
                        </div>
                        <div className="bld-bar">
                          {row.urgent > 0 && (
                            <div
                              className="bld-bar-seg urg"
                              style={{ width: `${(row.urgent / total) * 100}%` }}
                            />
                          )}
                          {row.high > 0 && (
                            <div
                              className="bld-bar-seg hi"
                              style={{ width: `${(row.high / total) * 100}%` }}
                            />
                          )}
                          {row.normal > 0 && (
                            <div
                              className="bld-bar-seg no"
                              style={{ width: `${(row.normal / total) * 100}%` }}
                            />
                          )}
                        </div>
                        <div className="bld-row-foot">
                          {row.urgent > 0 && (
                            <span className="urg">{row.urgent} urgent</span>
                          )}
                          {row.high > 0 && (
                            <span className="hi">{row.high} high</span>
                          )}
                          {row.normal > 0 && (
                            <span className="no">{row.normal} normal</span>
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
