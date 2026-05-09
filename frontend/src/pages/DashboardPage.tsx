import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, getApiError } from "../api/client";
import type {
  PaginatedResponse,
  TicketList,
  TicketStats,
  TicketStatsByBuildingResponse,
  TicketStatsByBuildingRow,
  TicketStatus,
} from "../api/types";
import { SLABadge } from "../components/sla/SLABadge";

type SLAFilterValue =
  | ""
  | "on_track"
  | "at_risk"
  | "breached"
  | "paused"
  | "completed"
  | "historical";

type Priority = "NORMAL" | "HIGH" | "URGENT";

const PAGE_SIZE = 25;

// Sprint 12: dashboard data refreshes silently every minute. Picked
// 60s as a balance between "fresh enough that the operator does not
// have to click refresh after a state change" and "not so chatty that
// the API logs fill with noise from idle dashboards". Filters / pagination /
// search state are NOT touched by the refresh — only the network reads
// repeat with the current params.
const AUTO_REFRESH_INTERVAL_MS = 60_000;

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

// SLA filter values are URL params; the labels are read from common.json
// (sla.on_track etc.) at render time so the dropdown matches the active
// language.
const SLA_FILTER_VALUES: Exclude<SLAFilterValue, "">[] = [
  "on_track",
  "at_risk",
  "breached",
  "paused",
  "completed",
  "historical",
];

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

export function DashboardPage() {
  const navigate = useNavigate();
  const { t } = useTranslation(["dashboard", "common"]);
  const tStatus = (status: TicketStatus) =>
    t(`common:status.${status.toLowerCase()}`);
  const tPriority = (priority: string) =>
    t(`common:priority.${priority.toLowerCase()}`);
  const tSLAFilter = (value: Exclude<SLAFilterValue, "">) =>
    t(`common:sla.${value}`);

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
  // Sprint 12: lastUpdated is set after every successful loader run
  // (manual refresh, filter change, or background interval). Rendered
  // as a small indicator in the page header. The "now" tick state
  // forces the relative-time string to recompute every 30s without
  // re-fetching anything.
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [now, setNow] = useState<Date>(() => new Date());

  const [statusFilter, setStatusFilter] = useState<TicketStatus | "">("");
  const [priorityFilter, setPriorityFilter] = useState<Priority | "">("");
  const [searchInput, setSearchInput] = useState("");
  const [searchActive, setSearchActive] = useState("");

  const [searchParams, setSearchParams] = useSearchParams();
  const slaFilter: SLAFilterValue = (() => {
    const raw = searchParams.get("sla") || "";
    const allowed: SLAFilterValue[] = [
      "",
      "on_track",
      "at_risk",
      "breached",
      "paused",
      "completed",
      "historical",
    ];
    return allowed.includes(raw as SLAFilterValue)
      ? (raw as SLAFilterValue)
      : "";
  })();
  const setSlaFilter = useCallback(
    (value: SLAFilterValue) => {
      const next = new URLSearchParams(searchParams);
      if (value) {
        next.set("sla", value);
      } else {
        next.delete("sla");
      }
      setSearchParams(next, { replace: true });
      setPage(1);
    },
    [searchParams, setSearchParams],
  );
  const [adminRequiredBanner, setAdminRequiredBanner] = useState(false);

  useEffect(() => {
    if (searchParams.get("admin_required") === "ok") {
      setAdminRequiredBanner(true);
      const next = new URLSearchParams(searchParams);
      next.delete("admin_required");
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const pageCount = Math.max(1, Math.ceil(count / PAGE_SIZE));

  const queryParams = useMemo(() => {
    const params: Record<string, string | number> = { page };
    if (statusFilter) params.status = statusFilter;
    if (priorityFilter) params.priority = priorityFilter;
    if (searchActive.trim()) params.search = searchActive.trim();
    if (slaFilter) params.sla = slaFilter;
    return params;
  }, [page, statusFilter, priorityFilter, searchActive, slaFilter]);

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
      setLastUpdated(new Date());
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

  // Sprint 12: silent auto-refresh every 60s. Always exactly ONE
  // interval per mount of this page; cleanup on unmount; cleanup on
  // dependency change (so a new query-params combination installs a
  // fresh timer aligned to the new fetch). The interval fires the
  // same three loaders the manual Refresh button uses, so filters /
  // pagination / SLA state are preserved automatically.
  useEffect(() => {
    const handle = window.setInterval(() => {
      loadTickets();
      loadStats();
      loadStatsByBuilding();
    }, AUTO_REFRESH_INTERVAL_MS);
    return () => {
      window.clearInterval(handle);
    };
  }, [loadTickets, loadStats, loadStatsByBuilding]);

  // Tick "now" every 30s so the "Updated Xs ago" string recomputes
  // without re-fetching. Cheap; no network. Same lifecycle as the
  // refresher above.
  useEffect(() => {
    const handle = window.setInterval(() => {
      setNow(new Date());
    }, 30_000);
    return () => {
      window.clearInterval(handle);
    };
  }, []);

  const lastUpdatedLabel = useMemo(() => {
    if (!lastUpdated) return "";
    const diff = Math.max(0, Math.floor((now.getTime() - lastUpdated.getTime()) / 1000));
    if (diff < 10) return t("last_updated_just_now");
    if (diff < 60) return t("last_updated_seconds_ago", { seconds: diff });
    const minutes = Math.floor(diff / 60);
    return t("last_updated_minutes_ago", { minutes });
  }, [lastUpdated, now, t]);

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
    setSlaFilter("");
  }

  const hasActiveFilters = Boolean(
    statusFilter || priorityFilter || searchActive || slaFilter,
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
            <span>{t("breadcrumb_site")}</span>
            <span className="breadcrumb-sep">›</span>
            <span>{t("breadcrumb_operations")}</span>
            <span className="breadcrumb-sep">›</span>
            <span className="breadcrumb-current">{t("breadcrumb_current")}</span>
          </nav>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("eyebrow")}
          </div>
          <h2 className="page-title">{t("title")}</h2>
          <p className="page-sub">
            {loading
              ? t("loading_data")
              : t("subtitle_counts", {
                  count,
                  visible: tickets.length,
                  page,
                  pages: pageCount,
                })}
          </p>
        </div>
        <div className="page-header-actions">
          {lastUpdatedLabel && (
            <span
              className="last-updated"
              aria-live="polite"
              title={lastUpdated ? lastUpdated.toLocaleString() : undefined}
            >
              {lastUpdatedLabel}
            </span>
          )}
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={loadTickets}
            disabled={loading}
          >
            <RefreshCw size={14} strokeWidth={2.5} />
            {t("common:refresh")}
          </button>
          <Link className="btn btn-primary btn-sm" to="/tickets/new">
            <Plus size={14} strokeWidth={2.5} />
            {t("new_ticket")}
          </Link>
        </div>
      </div>

      {adminRequiredBanner && (
        <div
          className="alert-info"
          style={{ marginBottom: 16 }}
          role="status"
          data-testid="admin-required-banner"
        >
          {t("admin_required_banner")}
        </div>
      )}

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      <div className="kpi-row">
        <div className="kpi-card">
          <div className="kpi-label">{t("kpi_total_label")}</div>
          <div className="kpi-row-2">
            <div className="kpi-value">{kpis ? kpis.total : "—"}</div>
          </div>
          <div className="kpi-meta">{t("kpi_total_meta")}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">{t("kpi_active_label")}</div>
          <div className="kpi-row-2">
            <div className="kpi-value">{kpis ? kpis.active : "—"}</div>
          </div>
          <div className="kpi-meta">{t("kpi_active_meta")}</div>
        </div>
        <div className="kpi-card">
          <div className="kpi-label">{t("kpi_awaiting_label")}</div>
          <div className="kpi-row-2">
            <div className="kpi-value">{kpis ? kpis.waitingApproval : "—"}</div>
          </div>
          <div className="kpi-meta">{t("kpi_awaiting_meta")}</div>
        </div>
        <div className="kpi-card kpi-urgent">
          <div className="kpi-label">{t("kpi_urgent_label")}</div>
          <div className="kpi-row-2">
            <div className="kpi-value">{kpis ? kpis.urgent : "—"}</div>
          </div>
          <div className="kpi-meta">{t("kpi_urgent_meta")}</div>
        </div>
      </div>

      <div className="dash-grid">
        <div className="dash-main">
          <div className="card" style={{ overflow: "hidden" }}>
            <div className="section-head">
              <div>
                <div className="section-head-title">
                  {t("section_recent_title")}
                </div>
                <div className="section-head-sub">
                  {t("section_recent_sub")}
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
                {t("rows_label", { count: tickets.length })}
              </span>
            </div>

            <form className="filter-bar" onSubmit={handleSearchSubmit}>
              <div className="filter-field">
                <span className="filter-label">{t("common:status")}</span>
                <select
                  className="filter-control"
                  value={statusFilter}
                  onChange={(event) => {
                    setPage(1);
                    setStatusFilter(event.target.value as TicketStatus | "");
                  }}
                >
                  <option value="">{t("common:all_statuses")}</option>
                  {STATUS_OPTIONS.map((status) => (
                    <option key={status} value={status}>
                      {tStatus(status)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="filter-field">
                <span className="filter-label">{t("common:priority")}</span>
                <select
                  className="filter-control"
                  value={priorityFilter}
                  onChange={(event) => {
                    setPage(1);
                    setPriorityFilter(event.target.value as Priority | "");
                  }}
                >
                  <option value="">{t("common:all_priorities")}</option>
                  {PRIORITY_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {tPriority(option)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="filter-field">
                <span className="filter-label">{t("common:sla")}</span>
                <select
                  className="filter-control"
                  value={slaFilter}
                  onChange={(event) =>
                    setSlaFilter(event.target.value as SLAFilterValue)
                  }
                >
                  <option value="">{t("common:all_sla_states")}</option>
                  {SLA_FILTER_VALUES.map((value) => (
                    <option key={value} value={value}>
                      {tSLAFilter(value)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="filter-field search">
                <span className="filter-label">{t("common:search")}</span>
                <input
                  className="filter-control"
                  type="search"
                  placeholder={t("search_placeholder")}
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                />
              </div>
              <div className="filter-actions">
                <button type="submit" className="btn btn-secondary btn-sm">
                  {t("common:apply")}
                </button>
                {hasActiveFilters && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={clearFilters}
                  >
                    {t("common:clear")}
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
                    <th>{t("common:ticket_no")}</th>
                    <th>{t("common:subject")}</th>
                    <th>{t("common:priority")}</th>
                    <th>{t("common:status")}</th>
                    <th>{t("common:sla")}</th>
                    <th>{t("common:facility")}</th>
                    <th>{t("common:customer")}</th>
                    <th>{t("common:created")}</th>
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
                          {tPriority(ticket.priority)}
                        </span>
                      </td>
                      <td>
                        <span className={statusCellClass(ticket.status)}>
                          <i />
                          {tStatus(ticket.status)}
                        </span>
                      </td>
                      <td>
                        <SLABadge
                          state={ticket.sla_display_state}
                          remainingSeconds={ticket.sla_remaining_business_seconds}
                        />
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
                      ? t("empty_no_match_title")
                      : t("empty_no_tickets_title")}
                  </div>
                  <p className="empty-sub">
                    {hasActiveFilters
                      ? t("empty_no_match_sub")
                      : t("empty_no_tickets_sub")}
                  </p>
                  {hasActiveFilters ? (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={clearFilters}
                    >
                      {t("clear_filters")}
                    </button>
                  ) : (
                    <Link className="btn btn-primary btn-sm" to="/tickets/new">
                      {t("create_ticket_cta")}
                    </Link>
                  )}
                </div>
              )}
            </div>

            <div className="pagination">
              <span className="pagination-info">
                {t("pagination_info", {
                  visible: tickets.length,
                  count,
                  page,
                  pages: pageCount,
                })}
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
                  {t("common:previous")}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  disabled={loading || !next}
                  onClick={() => setPage((current) => current + 1)}
                >
                  {t("common:next")}
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="dash-side">
          <div className="card">
            <div className="section-head">
              <div>
                <div className="section-head-title">
                  {t("section_status_title")}
                </div>
                <div className="section-head-sub">
                  {t("section_status_sub")}
                </div>
              </div>
            </div>
            <div style={{ padding: "14px 18px 18px" }}>
              {!stats ? (
                <p className="muted small">{t("loading")}</p>
              ) : (
                <div className="bld-list">
                  {STATUS_OPTIONS.map((key) => {
                    const value = stats.by_status[key] ?? 0;
                    return (
                      <div key={key} className="bld-row-head">
                        <span className="bld-row-name">{tStatus(key)}</span>
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
                <div className="section-head-title">
                  {t("section_focus_title")}
                </div>
                <div className="section-head-sub">
                  {t("section_focus_sub")}
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
                      {ticket.building_name} · {tStatus(ticket.status)}
                    </span>
                  </Link>
                ))
              ) : (
                <p className="focus-empty">{t("focus_empty")}</p>
              )}
            </div>
          </div>

          <div className="card">
            <div className="section-head">
              <div>
                <div className="section-head-title">
                  {t("section_byb_title")}
                </div>
                <div className="section-head-sub">
                  {t("section_byb_sub")}
                </div>
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
                {byBuilding ? t("byb_sites", { count: byBuilding.length }) : ""}
              </span>
            </div>
            <div style={{ padding: "16px 20px 18px" }}>
              {byBuilding === null ? (
                <p className="muted small">{t("loading")}</p>
              ) : byBuilding.length === 0 ? (
                <p className="muted small">{t("byb_no_buildings")}</p>
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
                          <span className="bld-row-count">
                            {t("byb_active_count", { count: active })}
                          </span>
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
                            <span className="no">
                              {t("byb_open", { count: row.open })}
                            </span>
                          )}
                          {row.in_progress > 0 && (
                            <span className="hi">
                              {t("byb_in_progress", { count: row.in_progress })}
                            </span>
                          )}
                          {row.waiting_customer_approval > 0 && (
                            <span className="urg">
                              {t("byb_awaiting_customer", {
                                count: row.waiting_customer_approval,
                              })}
                            </span>
                          )}
                          {row.urgent > 0 && (
                            <span className="urg">
                              {t("byb_urgent", { count: row.urgent })}
                            </span>
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
