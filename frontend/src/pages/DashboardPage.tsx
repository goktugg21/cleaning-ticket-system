import type { CSSProperties, FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Layers, Plus, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, getApiError } from "../api/client";
import {
  getExtraWorkStats,
  getExtraWorkStatsByBuilding,
} from "../api/extraWork";
import type {
  ExtraWorkStats,
  ExtraWorkStatsByBuildingResponse,
  ExtraWorkStatusValue,
  PaginatedResponse,
  TicketList,
  TicketStats,
  TicketStatsByBuildingResponse,
  TicketStatsByBuildingRow,
  TicketStatus,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
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

// Sprint 12: dashboard data refreshes silently every minute.
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

// Sprint 28 Batch 9 — Extra Work status vocabulary for the dashboard
// breakdown.
const EXTRA_WORK_STATUS_ORDER: ExtraWorkStatusValue[] = [
  "REQUESTED",
  "UNDER_REVIEW",
  "PRICING_PROPOSED",
  "CUSTOMER_APPROVED",
  "CUSTOMER_REJECTED",
  "CANCELLED",
];

const EXTRA_WORK_STATUS_KEY: Record<ExtraWorkStatusValue, string> = {
  REQUESTED: "extra_work_status_requested",
  UNDER_REVIEW: "extra_work_status_under_review",
  PRICING_PROPOSED: "extra_work_status_pricing_proposed",
  CUSTOMER_APPROVED: "extra_work_status_customer_approved",
  // Sprint 29 Batch 29.8 — operational segment dashboard labels.
  IN_PROGRESS: "extra_work_status_in_progress",
  COMPLETED: "extra_work_status_completed",
  CUSTOMER_REJECTED: "extra_work_status_customer_rejected",
  CANCELLED: "extra_work_status_cancelled",
};

const PRIORITY_OPTIONS: Priority[] = ["NORMAL", "HIGH", "URGENT"];

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

// SoT (Osius_Source_of_Truth_FINAL_2026-05-30) §1.4 + §7.1 — an
// Extra Work-origin ticket "must not disappear into the normal ticket
// list" and the dashboard "must make Extra Work origin impossible to
// miss". This single, prominent pill marks an EW-spawned ticket
// identically in every dashboard rendering (the operational queue, the
// fuller ticket table, the mobile cards) and deep-links to the parent
// Extra Work request. `stopPropagation` keeps the click from also
// triggering the row/card's own navigation to the ticket.
function ExtraWorkOriginPill({
  ewId,
  testId,
  style,
}: {
  ewId: number;
  testId: string;
  style?: CSSProperties;
}) {
  const { t } = useTranslation("dashboard");
  return (
    <Link
      to={`/extra-work/${ewId}`}
      className="work-type-pill work-type-pill-extra-work work-type-pill-link"
      title={t("ticket_row_extra_work_origin_title")}
      data-testid={testId}
      style={style}
      onClick={(event) => event.stopPropagation()}
    >
      <Layers size={12} strokeWidth={2.5} aria-hidden />
      {t("ops_type_extra_work")}
    </Link>
  );
}

/**
 * Sprint 28 Batch 13 (rework) — unified operations dashboard.
 *
 * Replaces the prior "two pasted dashboards" composition. The screen
 * is now ONE coherent operations command center with three bands:
 *
 *   1. A 5-card top KPI strip (`.operations-kpi-grid`) — Total open
 *      work, Active tickets, Active extra work, Awaiting approval,
 *      Urgent. All derived client-side from existing TicketStats +
 *      ExtraWorkStats (no client-side aggregation across pages).
 *   2. A work-strip segmented control (`.work-strip`) — All work /
 *      Tickets only / Extra work only, URL-backed `?view=`.
 *   3. A work-layout grid (`.work-layout`, 1fr + 340px) — content
 *      varies by view (unified Recent ops table in `view=all`, the
 *      existing Sprint 12 surface in `view=tickets`, the existing EW
 *      surface in `view=extra-work`).
 */
export function DashboardPage() {
  const navigate = useNavigate();
  const { me } = useAuth();
  const { t } = useTranslation(["dashboard", "common"]);
  const userRole = me?.role ?? null;
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
  const [extraWorkStats, setExtraWorkStats] = useState<ExtraWorkStats | null>(
    null,
  );
  const [extraWorkByBuilding, setExtraWorkByBuilding] =
    useState<ExtraWorkStatsByBuildingResponse | null>(null);
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

  // Sprint 28 Batch 13 (rework) — URL-backed work-view segmented
  // control. The "all" view renders one unified Recent operational
  // items table (tickets share columns with an Extra Work shortcut
  // row); "tickets" and "extra-work" each focus a single half of the
  // operation. Defaults to "all" and never appears in the URL when
  // the active value is "all" (cleaner deep links).
  type WorkView = "all" | "tickets" | "extra-work";
  const workView: WorkView = (() => {
    const raw = searchParams.get("view") || "";
    if (raw === "tickets" || raw === "extra-work") return raw;
    return "all";
  })();
  const setWorkView = useCallback(
    (value: WorkView) => {
      const nextParams = new URLSearchParams(searchParams);
      if (value === "all") {
        nextParams.delete("view");
      } else {
        nextParams.set("view", value);
      }
      setSearchParams(nextParams, { replace: true });
    },
    [searchParams, setSearchParams],
  );
  const showTickets = workView === "all" || workView === "tickets";
  const showExtraWork = workView === "all" || workView === "extra-work";
  const setSlaFilter = useCallback(
    (value: SLAFilterValue) => {
      const nextSearch = new URLSearchParams(searchParams);
      if (value) {
        nextSearch.set("sla", value);
      } else {
        nextSearch.delete("sla");
      }
      setSearchParams(nextSearch, { replace: true });
      setPage(1);
    },
    [searchParams, setSearchParams],
  );
  const [adminRequiredBanner, setAdminRequiredBanner] = useState(false);

  useEffect(() => {
    if (searchParams.get("admin_required") === "ok") {
      setAdminRequiredBanner(true);
      const nextSearch = new URLSearchParams(searchParams);
      nextSearch.delete("admin_required");
      setSearchParams(nextSearch, { replace: true });
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
    if (!showTickets) return;
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
  }, [queryParams, showTickets]);

  useEffect(() => {
    loadTickets();
  }, [loadTickets]);

  const loadStats = useCallback(async () => {
    try {
      const response = await api.get<TicketStats>("/tickets/stats/");
      setStats(response.data);
    } catch {
      // KPI cards fall back to "—" placeholders if the endpoint fails.
    }
  }, []);

  const loadStatsByBuilding = useCallback(async () => {
    if (!showTickets) return;
    try {
      const response = await api.get<TicketStatsByBuildingResponse>(
        "/tickets/stats/by-building/",
      );
      setByBuilding(response.data);
    } catch {
      // Card empties out if the endpoint fails.
    }
  }, [showTickets]);

  const loadExtraWorkStats = useCallback(async () => {
    try {
      const data = await getExtraWorkStats();
      setExtraWorkStats(data);
    } catch {
      // KPI cards fall back to placeholders.
    }
  }, []);

  const loadExtraWorkStatsByBuilding = useCallback(async () => {
    if (!showExtraWork) return;
    try {
      const data = await getExtraWorkStatsByBuilding();
      setExtraWorkByBuilding(data);
    } catch {
      // Card empties out if the endpoint fails.
    }
  }, [showExtraWork]);

  useEffect(() => {
    // Top KPI row needs BOTH ticket and extra-work stats regardless of
    // the active work-view (it is a 5-card unified row), so the stats
    // loaders run unconditionally. The byBuilding loaders are still
    // view-gated so we skip wasted network reads when the side panel
    // is not on screen.
    loadStats();
    loadStatsByBuilding();
    loadExtraWorkStats();
    loadExtraWorkStatsByBuilding();
  }, [
    loadStats,
    loadStatsByBuilding,
    loadExtraWorkStats,
    loadExtraWorkStatsByBuilding,
  ]);

  useEffect(() => {
    const handle = window.setInterval(() => {
      loadTickets();
      loadStats();
      loadStatsByBuilding();
      loadExtraWorkStats();
      loadExtraWorkStatsByBuilding();
    }, AUTO_REFRESH_INTERVAL_MS);
    return () => {
      window.clearInterval(handle);
    };
  }, [
    loadTickets,
    loadStats,
    loadStatsByBuilding,
    loadExtraWorkStats,
    loadExtraWorkStatsByBuilding,
  ]);

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

  // Sprint 28 Batch 13 (rework) — operations-level KPI summary. Derived
  // from existing TicketStats + ExtraWorkStats; no client-side
  // aggregation across multiple result pages (forbidden by §2). When
  // either stats endpoint has not yet resolved we render "—" sentinels
  // to avoid layout jumps.
  const opsKpis = useMemo(() => {
    const ticketsActive = stats?.my_open ?? null;
    const ticketsAwaitingApproval = stats?.waiting_customer_approval ?? null;
    const ticketsUrgent = stats?.urgent ?? null;
    const ewActive = extraWorkStats?.active ?? null;
    const ewAwaitingCustomer = extraWorkStats?.awaiting_customer_approval ?? null;
    const ewAwaitingPricing = extraWorkStats?.awaiting_pricing ?? null;
    const ewUrgent = extraWorkStats?.urgent ?? null;

    const totalOpen =
      ticketsActive !== null && ewActive !== null
        ? ticketsActive + ewActive
        : null;
    const awaiting =
      ticketsAwaitingApproval !== null &&
      ewAwaitingCustomer !== null &&
      ewAwaitingPricing !== null
        ? ticketsAwaitingApproval + ewAwaitingCustomer + ewAwaitingPricing
        : null;
    const urgent =
      ticketsUrgent !== null && ewUrgent !== null
        ? ticketsUrgent + ewUrgent
        : null;
    return {
      totalOpen,
      ticketsActive,
      ewActive,
      awaiting,
      urgent,
    };
  }, [stats, extraWorkStats]);

  const fmt = (value: number | null): string =>
    value === null ? "—" : String(value);

  const ewOpenCount = extraWorkStats?.active ?? 0;
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

      <div className="operations-dashboard">
        {/* Top KPI strip — five cards, single visual block. Derived
            from existing stats endpoints; never aggregated from a
            single page of /tickets/ results. */}
        <div
          className="operations-kpi-grid"
          data-testid="dashboard-ops-kpi-row"
        >
          <div className="kpi-card" data-testid="dashboard-ops-kpi-total">
            <div className="kpi-label">{t("ops_kpi_total_open_label")}</div>
            <div className="kpi-row-2">
              <div className="kpi-value">{fmt(opsKpis.totalOpen)}</div>
            </div>
            <div className="kpi-meta">{t("ops_kpi_total_open_meta")}</div>
          </div>
          <div className="kpi-card" data-testid="dashboard-ops-kpi-tickets">
            <div className="kpi-label">{t("ops_kpi_tickets_label")}</div>
            <div className="kpi-row-2">
              <div className="kpi-value">{fmt(opsKpis.ticketsActive)}</div>
            </div>
            <div className="kpi-meta">{t("ops_kpi_tickets_meta")}</div>
          </div>
          <div className="kpi-card" data-testid="dashboard-ops-kpi-extra-work">
            <div className="kpi-label">{t("ops_kpi_extra_work_label")}</div>
            <div className="kpi-row-2">
              <div className="kpi-value">{fmt(opsKpis.ewActive)}</div>
            </div>
            <div className="kpi-meta">{t("ops_kpi_extra_work_meta")}</div>
          </div>
          <div className="kpi-card" data-testid="dashboard-ops-kpi-awaiting">
            <div className="kpi-label">{t("ops_kpi_awaiting_label")}</div>
            <div className="kpi-row-2">
              <div className="kpi-value">{fmt(opsKpis.awaiting)}</div>
            </div>
            <div className="kpi-meta">{t("ops_kpi_awaiting_meta")}</div>
          </div>
          <div
            className="kpi-card kpi-urgent"
            data-testid="dashboard-ops-kpi-urgent"
          >
            <div className="kpi-label">{t("ops_kpi_urgent_label")}</div>
            <div className="kpi-row-2">
              <div className="kpi-value">{fmt(opsKpis.urgent)}</div>
            </div>
            <div className="kpi-meta">{t("ops_kpi_urgent_meta")}</div>
          </div>
        </div>

        {/* Work-strip — segmented control band. URL-backed. */}
        <div
          className="work-strip"
          role="group"
          aria-label={t("work_view_label")}
          data-testid="dashboard-work-view-toggle"
        >
          <span className="work-strip-label">{t("work_view_label")}</span>
          <div className="work-strip-toggle">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              aria-pressed={workView === "all"}
              data-testid="dashboard-work-view-all"
              onClick={() => setWorkView("all")}
            >
              {t("work_view_all")}
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              aria-pressed={workView === "tickets"}
              data-testid="dashboard-work-view-tickets"
              onClick={() => setWorkView("tickets")}
            >
              {t("work_view_tickets")}
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              aria-pressed={workView === "extra-work"}
              data-testid="dashboard-work-view-extra-work"
              onClick={() => setWorkView("extra-work")}
            >
              {t("work_view_extra_work")}
            </button>
          </div>
        </div>

        {/* Work area — three layouts depending on workView. */}
        {workView === "all" && showTickets && (
          <section
            className="work-layout"
            data-testid="dashboard-tickets-section"
          >
            <div className="dash-main">
              <div
                className="card"
                data-testid="dashboard-recent-ops"
                style={{ overflow: "hidden" }}
              >
                <div className="section-head">
                  <div>
                    <div className="section-head-title">
                      {t("ops_recent_title")}
                    </div>
                    <div className="section-head-sub">
                      {t("ops_recent_sub")}
                    </div>
                  </div>
                  <Link
                    to="/?view=tickets"
                    className="btn btn-ghost btn-sm"
                    style={{ fontWeight: 600 }}
                  >
                    {t("ops_recent_view_all_tickets")}
                  </Link>
                </div>

                {loading && (
                  <div className="loading-bar" style={{ margin: 0 }}>
                    <div className="loading-bar-fill" />
                  </div>
                )}

                <div className="table-wrap ticket-list-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>{t("common:type")}</th>
                        <th>{t("common:subject")}</th>
                        <th>{t("common:customer")}</th>
                        <th>{t("common:facility")}</th>
                        <th>{t("common:status")}</th>
                        <th>{t("common:updated")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tickets.slice(0, 8).map((ticket) => (
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
                            {ticket.extra_work_origin ? (
                              <ExtraWorkOriginPill
                                ewId={
                                  ticket.extra_work_origin
                                    .extra_work_request_id
                                }
                                testId="ticket-queue-extra-work-origin"
                              />
                            ) : (
                              <span className="work-type-pill work-type-pill-ticket">
                                {t("ops_type_ticket")}
                              </span>
                            )}
                          </td>
                          <td className="td-subject">
                            <Link to={`/tickets/${ticket.id}`}>
                              {ticket.title}
                            </Link>
                            {userRole === "STAFF" &&
                              me?.id != null &&
                              ticket.assigned_to === me.id && (
                                <span
                                  className="cell-tag cell-tag-open"
                                  style={{ marginLeft: 8 }}
                                  data-testid="ticket-row-assigned-to-you"
                                >
                                  <i />
                                  {t("common:tickets.assigned_to_you")}
                                </span>
                              )}
                          </td>
                          <td className="td-customer">{ticket.customer_name}</td>
                          <td className="td-facility">{ticket.building_name}</td>
                          <td>
                            <span className={statusCellClass(ticket.status)}>
                              <i />
                              {tStatus(ticket.status)}
                            </span>
                          </td>
                          <td className="td-date">
                            {formatDate(ticket.updated_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {!loading && tickets.length === 0 && (
                  <div className="empty-state">
                    <div className="empty-icon">＋</div>
                    <div className="empty-title">
                      {t("empty_no_tickets_title")}
                    </div>
                    <p className="empty-sub">{t("empty_no_tickets_sub")}</p>
                    <Link className="btn btn-primary btn-sm" to="/tickets/new">
                      {t("create_ticket_cta")}
                    </Link>
                  </div>
                )}

                {/* Extra-work shortcut row inside the same card.
                    Honestly reflects the API limitation (no mixed-
                    feed endpoint) without inventing a second
                    "section". */}
                <div className="recent-ops-extra-work-row">
                  <span>
                    {ewOpenCount > 0
                      ? t("ops_recent_extra_work_link", { count: ewOpenCount })
                      : t("ops_recent_extra_work_link_zero")}
                  </span>
                  <Link to="/extra-work">
                    {t("work_view_extra_work")}
                  </Link>
                </div>
              </div>
            </div>

            <div className="dash-side">
              <div className="card">
                <div className="section-head">
                  <div>
                    <div className="section-head-title">
                      {t("ops_byb_tickets_title")}
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
                    {byBuilding
                      ? t("byb_sites", { count: byBuilding.length })
                      : ""}
                  </span>
                </div>
                <div style={{ padding: "14px 18px 18px" }}>
                  {byBuilding === null ? (
                    <p className="muted small">{t("loading")}</p>
                  ) : byBuilding.length === 0 ? (
                    <p className="muted small">{t("byb_no_buildings")}</p>
                  ) : (
                    <div className="bld-list">
                      {byBuilding.slice(0, 5).map((row) => {
                        const active =
                          row.open +
                          row.in_progress +
                          row.waiting_customer_approval;
                        const total = Math.max(active, 1);
                        return (
                          <div key={row.building_id}>
                            <div className="bld-row-head">
                              <span className="bld-row-name">
                                {row.building_name}
                              </span>
                              <span className="bld-row-count">
                                {t("byb_active_count", { count: active })}
                              </span>
                            </div>
                            <div className="bld-bar">
                              {row.open > 0 && (
                                <div
                                  className="bld-bar-seg no"
                                  style={{
                                    width: `${(row.open / total) * 100}%`,
                                  }}
                                />
                              )}
                              {row.in_progress > 0 && (
                                <div
                                  className="bld-bar-seg hi"
                                  style={{
                                    width: `${(row.in_progress / total) * 100}%`,
                                  }}
                                />
                              )}
                              {row.waiting_customer_approval > 0 && (
                                <div
                                  className="bld-bar-seg urg"
                                  style={{
                                    width: `${
                                      (row.waiting_customer_approval / total) *
                                      100
                                    }%`,
                                  }}
                                />
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>

              {/* Sprint 28 Batch 13 rework: the Extra Work side card
                  in view=all wears the legacy `dashboard-extra-work-
                  section` testid so the existing Sprint 28 Batch 9
                  smoke spec (which asserts the section is present
                  alongside the tickets section) keeps resolving. The
                  card is visually a peer side-card under the
                  unified KPI strip — not a "pasted dashboard". */}
              <section
                className="card"
                data-testid="dashboard-extra-work-section"
              >
                <div className="section-head">
                  <div>
                    <div className="section-head-title">
                      {t("ops_byb_extra_work_title")}
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
                    {extraWorkByBuilding
                      ? t("byb_sites", {
                          count: extraWorkByBuilding.length,
                        })
                      : ""}
                  </span>
                </div>
                <div style={{ padding: "14px 18px 18px" }}>
                  {extraWorkByBuilding === null ? (
                    <p className="muted small">{t("loading")}</p>
                  ) : extraWorkByBuilding.length === 0 ? (
                    <p className="muted small">
                      {t("extra_work_byb_no_buildings")}
                    </p>
                  ) : (
                    <div className="bld-list">
                      {extraWorkByBuilding.slice(0, 5).map((row) => (
                        <div key={row.building_id}>
                          <div className="bld-row-head">
                            <span className="bld-row-name">
                              {row.building_name}
                            </span>
                            <span className="bld-row-count">
                              {t("extra_work_byb_active_count", {
                                count: row.active,
                              })}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </section>
            </div>
          </section>
        )}

        {workView === "tickets" && (
          <section
            className="work-layout"
            data-testid="dashboard-tickets-section"
          >
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

                <div className="table-wrap ticket-list-wrap">
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
                            <Link
                              to={`/tickets/${ticket.id}`}
                              className="td-id"
                            >
                              {ticket.ticket_no}
                            </Link>
                            {ticket.extra_work_origin && (
                              <ExtraWorkOriginPill
                                ewId={
                                  ticket.extra_work_origin
                                    .extra_work_request_id
                                }
                                testId="ticket-row-extra-work-origin"
                                style={{ marginLeft: 8 }}
                              />
                            )}
                          </td>
                          <td className="td-subject">
                            <Link to={`/tickets/${ticket.id}`}>
                              {ticket.title}
                            </Link>
                            {userRole === "STAFF" &&
                              me?.id != null &&
                              ticket.assigned_to === me.id && (
                                <span
                                  className="cell-tag cell-tag-open"
                                  style={{ marginLeft: 8 }}
                                  data-testid="ticket-row-assigned-to-you"
                                >
                                  <i />
                                  {t("common:tickets.assigned_to_you")}
                                </span>
                              )}
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
                              remainingSeconds={
                                ticket.sla_remaining_business_seconds
                              }
                            />
                          </td>
                          <td className="td-facility">
                            {ticket.building_name}
                          </td>
                          <td className="td-customer">
                            {ticket.customer_name}
                          </td>
                          <td className="td-date">
                            {formatDate(ticket.created_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Sprint 22 — phone-width card mirror of the ticket
                    table. Kept in DOM regardless of viewport so the
                    existing testid contracts continue to resolve. */}
                <ul
                  className="ticket-card-list"
                  data-testid="ticket-card-list"
                  aria-label={t("section_recent_title")}
                >
                  {tickets.map((ticket) => (
                    <li key={ticket.id} className="ticket-card">
                      {ticket.extra_work_origin && (
                        <ExtraWorkOriginPill
                          ewId={
                            ticket.extra_work_origin.extra_work_request_id
                          }
                          testId="ticket-card-extra-work-origin"
                          style={{ marginBottom: 8 }}
                        />
                      )}
                      <Link
                        to={`/tickets/${ticket.id}`}
                        className="ticket-card-link"
                        aria-label={`${ticket.ticket_no} — ${ticket.title}`}
                      >
                        <div className="ticket-card-head">
                          <span className="ticket-card-id">
                            {ticket.ticket_no}
                          </span>
                          <span className={priorityCellClass(ticket.priority)}>
                            <i />
                            {tPriority(ticket.priority)}
                          </span>
                        </div>
                        <div className="ticket-card-title">
                          {ticket.title}
                          {userRole === "STAFF" &&
                            me?.id != null &&
                            ticket.assigned_to === me.id && (
                              <span
                                className="cell-tag cell-tag-open"
                                style={{ marginLeft: 8 }}
                                data-testid="ticket-card-assigned-to-you"
                              >
                                <i />
                                {t("common:tickets.assigned_to_you")}
                              </span>
                            )}
                        </div>
                        <div className="ticket-card-pills">
                          <span className={statusCellClass(ticket.status)}>
                            <i />
                            {tStatus(ticket.status)}
                          </span>
                          <SLABadge
                            state={ticket.sla_display_state}
                            remainingSeconds={
                              ticket.sla_remaining_business_seconds
                            }
                          />
                        </div>
                        <dl className="ticket-card-meta">
                          <div className="ticket-card-meta-row">
                            <dt>{t("common:facility")}</dt>
                            <dd className="td-facility">
                              {ticket.building_name}
                            </dd>
                          </div>
                          <div className="ticket-card-meta-row">
                            <dt>{t("common:customer")}</dt>
                            <dd className="td-customer">
                              {ticket.customer_name}
                            </dd>
                          </div>
                          <div className="ticket-card-meta-row">
                            <dt>{t("common:created")}</dt>
                            <dd>{formatDate(ticket.created_at)}</dd>
                          </div>
                        </dl>
                      </Link>
                    </li>
                  ))}
                </ul>

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
                      {t("ops_byb_tickets_title")}
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
                          row.open +
                          row.in_progress +
                          row.waiting_customer_approval;
                        const total = Math.max(active, 1);
                        return (
                          <div key={row.building_id}>
                            <div className="bld-row-head">
                              <span className="bld-row-name">
                                {row.building_name}
                              </span>
                              <span className="bld-row-count">
                                {t("byb_active_count", { count: active })}
                              </span>
                            </div>
                            <div className="bld-bar">
                              {row.open > 0 && (
                                <div
                                  className="bld-bar-seg no"
                                  style={{
                                    width: `${(row.open / total) * 100}%`,
                                  }}
                                />
                              )}
                              {row.in_progress > 0 && (
                                <div
                                  className="bld-bar-seg hi"
                                  style={{
                                    width: `${(row.in_progress / total) * 100}%`,
                                  }}
                                />
                              )}
                              {row.waiting_customer_approval > 0 && (
                                <div
                                  className="bld-bar-seg urg"
                                  style={{
                                    width: `${
                                      (row.waiting_customer_approval / total) *
                                      100
                                    }%`,
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
                                  {t("byb_in_progress", {
                                    count: row.in_progress,
                                  })}
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
            </div>
          </section>
        )}

        {showExtraWork && workView === "extra-work" && (
          <section
            className="work-layout"
            data-testid="dashboard-extra-work-section"
          >
            <div className="dash-main">
              <div className="card">
                <div className="section-head">
                  <div>
                    <div className="section-head-title">
                      {t("ops_byb_extra_work_title")}
                    </div>
                    <div className="section-head-sub">
                      {t("extra_work_byb_sub")}
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
                    {extraWorkByBuilding
                      ? t("byb_sites", { count: extraWorkByBuilding.length })
                      : ""}
                  </span>
                </div>
                <div style={{ padding: "16px 20px 18px" }}>
                  {extraWorkStats === null ? (
                    <p className="muted small">{t("loading")}</p>
                  ) : extraWorkStats.total === 0 ? (
                    <div
                      className="empty-state"
                      data-testid="dashboard-extra-work-section-empty"
                    >
                      <div className="empty-icon">＋</div>
                      <div className="empty-title">
                        {t("extra_work_section_empty")}
                      </div>
                    </div>
                  ) : extraWorkByBuilding === null ? (
                    <p className="muted small">{t("loading")}</p>
                  ) : extraWorkByBuilding.length === 0 ? (
                    <p className="muted small">
                      {t("extra_work_byb_no_buildings")}
                    </p>
                  ) : (
                    <div className="bld-list">
                      {extraWorkByBuilding.map((row) => (
                        <div key={row.building_id}>
                          <div className="bld-row-head">
                            <span className="bld-row-name">
                              {row.building_name}
                            </span>
                            <span className="bld-row-count">
                              {t("extra_work_byb_active_count", {
                                count: row.active,
                              })}
                            </span>
                          </div>
                          <div className="bld-row-foot">
                            {row.awaiting_pricing > 0 && (
                              <span className="hi">
                                {t("extra_work_byb_awaiting_pricing", {
                                  count: row.awaiting_pricing,
                                })}
                              </span>
                            )}
                            {row.awaiting_customer_approval > 0 && (
                              <span className="urg">
                                {t("extra_work_byb_awaiting_customer", {
                                  count: row.awaiting_customer_approval,
                                })}
                              </span>
                            )}
                            {row.urgent > 0 && (
                              <span className="urg">
                                {t("extra_work_byb_urgent", {
                                  count: row.urgent,
                                })}
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
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
                      {t("extra_work_section_sub")}
                    </div>
                  </div>
                </div>
                <div style={{ padding: "14px 18px 18px" }}>
                  {extraWorkStats === null ? (
                    <p className="muted small">{t("loading")}</p>
                  ) : (
                    <div className="bld-list">
                      {EXTRA_WORK_STATUS_ORDER.map((key) => {
                        const value = extraWorkStats.by_status[key] ?? 0;
                        return (
                          <div key={key} className="bld-row-head">
                            <span className="bld-row-name">
                              {t(EXTRA_WORK_STATUS_KEY[key])}
                            </span>
                            <span className="bld-row-count">{value}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
