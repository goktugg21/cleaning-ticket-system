import type { CSSProperties, FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Layers, Plus, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, getApiError } from "../api/client";
import { getMySlots } from "../api/admin";
import { getExtraWorkStats, listExtraWork } from "../api/extraWork";
import { getInboxUnreadCount } from "../api/inbox";
import { listNotifications, notificationHref } from "../api/notifications";
import type {
  ExtraWorkStats,
  Notification,
  PaginatedResponse,
  TicketList,
  TicketStats,
  TicketStatsByBuildingResponse,
  TicketStatsByBuildingRow,
  TicketStatus,
} from "../api/types";
import { bulkConfirmTickets } from "../api/tickets";
import { useAuth } from "../auth/AuthContext";
import {
  canAccessBilling,
  canAccessExtraWork,
  isProviderManagementRole,
  isStaffRole,
} from "../auth/permissions";
import { SLABadge } from "../components/sla/SLABadge";
import { useToast } from "../components/ToastProvider";
import { currentMonth, splitOpenInvoiced } from "../lib/billing";
import { formatDate, formatDateTime, formatMoney } from "../lib/intl";

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
  // Sprint 7 — surface the manager-review queue so provider management
  // can preset the list to the bulk-confirm view ("te bevestigen").
  "WAITING_MANAGER_REVIEW",
  "WAITING_CUSTOMER_APPROVAL",
  "APPROVED",
  "REJECTED",
  "CLOSED",
  "REOPENED_BY_ADMIN",
];

// (RF-16 removed the dashboard Extra Work status breakdown — the EW
// status vocabulary now lives with the list on ExtraWorkListPage.)

const PRIORITY_OPTIONS: Priority[] = ["NORMAL", "HIGH", "URGENT"];

const SLA_FILTER_VALUES: Exclude<SLAFilterValue, "">[] = [
  "on_track",
  "at_risk",
  "breached",
  "paused",
  "completed",
  "historical",
];

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
 *
 * RF-3 (Ramazan 2026-06-23) — the same component powers a focused
 * top-level Tickets LIST page. `variant="tickets-page"` locks the view
 * to `tickets` and hides the dashboard-level chrome (KPI hero, "my
 * work", work-strip toggle), reusing the existing ticket surface
 * (filters / presets / bulk-confirm / pagination) instead of a
 * duplicated second implementation. Default `"dashboard"` is unchanged.
 */
export function DashboardPage({
  variant = "dashboard",
}: {
  variant?: "dashboard" | "tickets-page";
} = {}) {
  const isTicketsPage = variant === "tickets-page";
  const navigate = useNavigate();
  const { me } = useAuth();
  const { push } = useToast();
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
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [now, setNow] = useState<Date>(() => new Date());

  // RF-16 (#106) — the Tickets page accepts ?status= and ?unassigned=1
  // presets so the dashboard's attention cards can deep-link into the
  // full list with the right filter applied (read once at mount; the
  // dropdowns own the state afterwards).
  const [statusFilter, setStatusFilter] = useState<TicketStatus | "">(() => {
    const raw = new URLSearchParams(window.location.search).get("status");
    return raw && (STATUS_OPTIONS as string[]).includes(raw)
      ? (raw as TicketStatus)
      : "";
  });
  const [unassignedFilter, setUnassignedFilter] = useState(
    () => new URLSearchParams(window.location.search).get("unassigned") === "1",
  );
  const [priorityFilter, setPriorityFilter] = useState<Priority | "">("");
  const [searchInput, setSearchInput] = useState("");
  const [searchActive, setSearchActive] = useState("");

  // Sprint 7 — bulk manager-confirm selection. Only ever surfaced when
  // `bulkMode` is true (provider management viewing the
  // WAITING_MANAGER_REVIEW queue). The set may legitimately hold ids no
  // longer in the current page; everything downstream derives the
  // submittable set from the VISIBLE rows, so stale ids are inert.
  const [selectedIds, setSelectedIds] = useState<Set<number>>(
    () => new Set<number>(),
  );
  const [bulkSubmitting, setBulkSubmitting] = useState(false);

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

  // RF-16 (#106) — the work-view segmented control is gone: the full
  // list views are exclusive to the Tickets / Extra Work pages, and
  // the dashboard renders attention cards instead. The old ?view=
  // deep links simply land on the overview now (no route changes).
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
    // RF-16 — unassigned preset (attention-card deep link). Uses the
    // backend filterset's assigned_to isnull lookup.
    if (unassignedFilter) params.assigned_to__isnull = "true";
    // M6.3 — "my work" deep-links. Only applied on the Tickets page
    // (where the clear chip is shown).
    if (isTicketsPage) {
      if (searchParams.get("mine") === "1" && me?.id) params.created_by = me.id;
      const typeParam = searchParams.get("type");
      if (typeParam) params.type = typeParam;
      const exclTypeParam = searchParams.get("exclude_type");
      if (exclTypeParam) params.exclude_type = exclTypeParam;
    }
    return params;
  }, [
    page,
    statusFilter,
    priorityFilter,
    searchActive,
    slaFilter,
    unassignedFilter,
    searchParams,
    me,
    isTicketsPage,
  ]);

  const loadTickets = useCallback(async () => {
    // RF-16 — the ticket LIST only renders on the Tickets page now.
    if (!isTicketsPage) return;
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
  }, [queryParams, isTicketsPage]);

  useEffect(() => {
    loadTickets();
  }, [loadTickets]);

  // Sprint 7 — bulk manager-confirm. The affordance only appears for
  // provider management while the list is filtered to the
  // WAITING_MANAGER_REVIEW queue. The submittable set is always derived
  // from the currently-visible rows, so changing filters/pages can
  // never bulk-confirm a ticket that is no longer on screen.
  const bulkMode =
    isProviderManagementRole(userRole) &&
    statusFilter === "WAITING_MANAGER_REVIEW";
  const selectedVisibleIds = useMemo(
    () =>
      tickets
        .filter((ticket) => selectedIds.has(ticket.id))
        .map((ticket) => ticket.id),
    [tickets, selectedIds],
  );
  const allVisibleSelected =
    tickets.length > 0 && selectedVisibleIds.length === tickets.length;

  const toggleRowSelection = useCallback((id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const toggleAllVisible = useCallback(() => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      const everyVisibleSelected =
        tickets.length > 0 && tickets.every((ticket) => next.has(ticket.id));
      if (everyVisibleSelected) {
        tickets.forEach((ticket) => next.delete(ticket.id));
      } else {
        tickets.forEach((ticket) => next.add(ticket.id));
      }
      return next;
    });
  }, [tickets]);

  const handleBulkConfirm = useCallback(async () => {
    const ids = tickets
      .filter((ticket) => selectedIds.has(ticket.id))
      .map((ticket) => ticket.id);
    if (ids.length === 0) return;
    setBulkSubmitting(true);
    try {
      const result = await bulkConfirmTickets(ids);
      if (result.failed === 0) {
        push({
          variant: "success",
          title: t("bulk_confirm.toast_success_title"),
          description: t("bulk_confirm.toast_success_desc", {
            count: result.succeeded,
          }),
        });
      } else {
        push({
          variant: "warning",
          title: t("bulk_confirm.toast_partial_title"),
          description: t("bulk_confirm.toast_partial_desc", {
            succeeded: result.succeeded,
            failed: result.failed,
          }),
        });
      }
      setSelectedIds(new Set<number>());
      await loadTickets();
    } catch (err) {
      push({
        variant: "error",
        title: t("bulk_confirm.toast_error_title"),
        description: getApiError(err),
      });
    } finally {
      setBulkSubmitting(false);
    }
  }, [tickets, selectedIds, push, t, loadTickets]);

  const loadStats = useCallback(async () => {
    try {
      const response = await api.get<TicketStats>("/tickets/stats/");
      setStats(response.data);
    } catch {
      // KPI cards fall back to "—" placeholders if the endpoint fails.
    }
  }, []);

  // M6.3 — "my work" summary counts (provider-management only). Each
  // count is the PaginatedResponse.count for a created_by=me query;
  // page_size:1 keeps the payload minimal (count is the full total).
  const [myCounts, setMyCounts] = useState<{
    tickets: number | null;
    meldingen: number | null;
    extraWork: number | null;
    quoteRequests: number | null;
  }>({
    tickets: null,
    meldingen: null,
    extraWork: null,
    quoteRequests: null,
  });

  const loadMyCounts = useCallback(async () => {
    const meId = me?.id;
    if (!meId || !isProviderManagementRole(userRole)) return;
    try {
      const [tk, ml, ew, qr] = await Promise.all([
        api.get<PaginatedResponse<TicketList>>("/tickets/", {
          params: { created_by: meId, exclude_type: "REPORT", page_size: 1 },
        }),
        api.get<PaginatedResponse<TicketList>>("/tickets/", {
          params: { created_by: meId, type: "REPORT", page_size: 1 },
        }),
        listExtraWork({ created_by: meId, page_size: 1 }),
        listExtraWork({
          created_by: meId,
          request_intent: "REQUEST_QUOTE",
          page_size: 1,
        }),
      ]);
      setMyCounts({
        tickets: tk.data.count,
        meldingen: ml.data.count,
        extraWork: ew.count,
        quoteRequests: qr.count,
      });
    } catch {
      // Leave "—" placeholders on failure (mirrors loadStats).
    }
  }, [me?.id, userRole]);

  const loadStatsByBuilding = useCallback(async () => {
    // The by-building side panel renders on the Tickets page only.
    if (!isTicketsPage) return;
    try {
      const response = await api.get<TicketStatsByBuildingResponse>(
        "/tickets/stats/by-building/",
      );
      setByBuilding(response.data);
    } catch {
      // Card empties out if the endpoint fails.
    }
  }, [isTicketsPage]);

  const loadExtraWorkStats = useCallback(async () => {
    try {
      const data = await getExtraWorkStats();
      setExtraWorkStats(data);
    } catch {
      // KPI cards fall back to placeholders.
    }
  }, []);

  // RF-16 (#106) — attention-card data: the manager-review queue, the
  // unassigned-open queue (count + top rows each, via the established
  // count-query pattern) and the recent-activity feed. Dashboard only.
  const [attnReview, setAttnReview] = useState<{
    count: number;
    rows: TicketList[];
  } | null>(null);
  const [attnUnassigned, setAttnUnassigned] = useState<{
    count: number;
    rows: TicketList[];
  } | null>(null);
  const [attnActivity, setAttnActivity] = useState<Notification[] | null>(
    null,
  );

  // RF-18 (#107) — info-widget data (dashboard variant only). One fetch
  // per widget on mount (+ the shared auto-refresh); role-ineligible
  // widgets never fetch; failures keep the "—" placeholder.
  const [inboxUnread, setInboxUnread] = useState<number | null>(null);
  const [billingMonthTotals, setBillingMonthTotals] = useState<{
    openTotal: number;
    invoicedTotal: number;
  } | null>(null);
  const [todaySlotCount, setTodaySlotCount] = useState<number | null>(null);

  const loadWidgets = useCallback(async () => {
    if (isTicketsPage) return;
    const localDateKey = (iso: string | null): string | null => {
      if (!iso) return null;
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return null;
      const pad = (n: number) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    };
    const [inbox, billing, slots] = await Promise.allSettled([
      getInboxUnreadCount(),
      canAccessBilling(userRole)
        ? listExtraWork({ billing_period: currentMonth(), page_size: 500 })
        : Promise.resolve(null),
      isStaffRole(userRole) ? getMySlots() : Promise.resolve(null),
    ]);
    if (inbox.status === "fulfilled") setInboxUnread(inbox.value);
    if (billing.status === "fulfilled" && billing.value !== null) {
      setBillingMonthTotals(splitOpenInvoiced(billing.value.results));
    }
    if (slots.status === "fulfilled" && slots.value !== null) {
      const today = localDateKey(new Date().toISOString());
      setTodaySlotCount(
        slots.value.filter(
          (s) => localDateKey(s.scheduled_start_at) === today,
        ).length,
      );
    }
  }, [isTicketsPage, userRole]);

  const loadAttention = useCallback(async () => {
    if (isTicketsPage) return;
    try {
      const [rev, una, act] = await Promise.all([
        api.get<PaginatedResponse<TicketList>>("/tickets/", {
          params: { status: "WAITING_MANAGER_REVIEW", page_size: 3 },
        }),
        api.get<PaginatedResponse<TicketList>>("/tickets/", {
          params: {
            status: "OPEN",
            assigned_to__isnull: "true",
            page_size: 3,
          },
        }),
        listNotifications({ page: 1 }),
      ]);
      setAttnReview({ count: rev.data.count, rows: rev.data.results });
      setAttnUnassigned({ count: una.data.count, rows: una.data.results });
      setAttnActivity(act.results.slice(0, 3));
    } catch {
      // Cards keep their "—" placeholders on failure (mirrors loadStats).
    }
  }, [isTicketsPage]);

  useEffect(() => {
    // Top KPI row needs BOTH ticket and extra-work stats (it is a
    // 5-card unified row), so the stats loaders run unconditionally.
    // The by-building loader is Tickets-page-gated; the attention
    // loader is dashboard-gated.
    loadStats();
    loadStatsByBuilding();
    loadExtraWorkStats();
    loadMyCounts();
    loadAttention();
    loadWidgets();
  }, [
    loadStats,
    loadStatsByBuilding,
    loadExtraWorkStats,
    loadMyCounts,
    loadAttention,
    loadWidgets,
  ]);

  useEffect(() => {
    const handle = window.setInterval(() => {
      loadTickets();
      loadStats();
      loadStatsByBuilding();
      loadExtraWorkStats();
      loadAttention();
      loadWidgets();
    }, AUTO_REFRESH_INTERVAL_MS);
    return () => {
      window.clearInterval(handle);
    };
  }, [
    loadTickets,
    loadStats,
    loadStatsByBuilding,
    loadExtraWorkStats,
    loadAttention,
    loadWidgets,
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
    setUnassignedFilter(false);
    // Sprint 7 — clearing filters also leaves the bulk-confirm queue.
    setSelectedIds(new Set<number>());
  }

  const hasActiveFilters = Boolean(
    statusFilter || priorityFilter || searchActive || slaFilter ||
      unassignedFilter,
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
            <span className="breadcrumb-current">
              {isTicketsPage
                ? t("tickets_page.breadcrumb_current")
                : t("breadcrumb_current")}
            </span>
          </nav>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {isTicketsPage ? t("tickets_page.eyebrow") : t("eyebrow")}
          </div>
          <h2 className="page-title">
            {isTicketsPage ? t("tickets_page.title") : t("title")}
          </h2>
          <p className="page-sub">
            {/* RF-16 — the dashboard loads no list, so the list-count
                subtitle only makes sense on the Tickets page. */}
            {!isTicketsPage
              ? t("subtitle_overview")
              : loading
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
              title={lastUpdated ? formatDateTime(lastUpdated) : undefined}
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
        {/* RF-3 — the Tickets page hides the dashboard-level chrome (KPI
            hero, "my work", work-strip toggle) and leads straight with the
            ticket surface below. The dashboard at "/" is unchanged. */}
        {!isTicketsPage && (
          <>
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

        {/* RF-18 (#107) — compact info widgets: count/euro + label +
            deep link with the right preset. Role-aware (a widget the
            role cannot act on never renders or fetches); complements
            the KPI hero and attention cards. */}
        <section
          className="widget-row"
          data-testid="dashboard-widget-row"
          style={{ marginTop: 12 }}
        >
          <Link to="/inbox" className="info-widget" data-testid="widget-inbox">
            <span className="info-widget-value">{fmt(inboxUnread)}</span>
            <span className="info-widget-label">{t("widgets.inbox")}</span>
          </Link>
          {canAccessExtraWork(userRole) && (
            <Link
              to="/extra-work?status=UNDER_REVIEW"
              className="info-widget"
              data-testid="widget-awaiting-pricing"
            >
              <span className="info-widget-value">
                {fmt(extraWorkStats?.awaiting_pricing ?? null)}
              </span>
              <span className="info-widget-label">
                {t("widgets.awaiting_pricing")}
              </span>
            </Link>
          )}
          {canAccessExtraWork(userRole) && (
            <Link
              to="/extra-work?status=PRICING_PROPOSED"
              className="info-widget"
              data-testid="widget-awaiting-customer"
            >
              <span className="info-widget-value">
                {fmt(extraWorkStats?.awaiting_customer_approval ?? null)}
              </span>
              <span className="info-widget-label">
                {t("widgets.awaiting_customer")}
              </span>
            </Link>
          )}
          {canAccessBilling(userRole) && (
            <Link
              to="/invoices"
              className="info-widget"
              data-testid="widget-billing"
            >
              <span className="info-widget-value">
                {billingMonthTotals
                  ? formatMoney(billingMonthTotals.openTotal)
                  : "—"}
              </span>
              <span className="info-widget-label">
                {billingMonthTotals
                  ? t("widgets.billing_month", {
                      invoiced: formatMoney(billingMonthTotals.invoicedTotal),
                    })
                  : t("widgets.billing_month_loading")}
              </span>
            </Link>
          )}
          {isStaffRole(userRole) && (
            <Link
              to="/agenda"
              className="info-widget"
              data-testid="widget-today-slots"
            >
              <span className="info-widget-value">{fmt(todaySlotCount)}</span>
              <span className="info-widget-label">
                {t("widgets.today_slots")}
              </span>
            </Link>
          )}
        </section>

        {/* M6.3 — "My work" summary. Provider-management only ("my
            created items" is a provider-admin concept). Each card links
            into a created_by=me-filtered list view. */}
        {isProviderManagementRole(userRole) && me?.id && (
          <section
            className="my-work-section"
            data-testid="dashboard-my-work"
            style={{ marginTop: 12 }}
          >
            <div className="section-head" style={{ marginBottom: 10 }}>
              <div className="section-head-title">{t("my_work.title")}</div>
            </div>
            <div className="operations-kpi-grid">
              <Link
                to="/tickets?mine=1&exclude_type=REPORT"
                className="kpi-card"
                data-testid="dashboard-my-tickets"
              >
                <div className="kpi-label">{t("my_work.tickets")}</div>
                <div className="kpi-row-2">
                  <div className="kpi-value">{fmt(myCounts.tickets)}</div>
                </div>
              </Link>
              <Link
                to="/tickets?mine=1&type=REPORT"
                className="kpi-card"
                data-testid="dashboard-my-meldingen"
              >
                <div className="kpi-label">{t("my_work.meldingen")}</div>
                <div className="kpi-row-2">
                  <div className="kpi-value">{fmt(myCounts.meldingen)}</div>
                </div>
              </Link>
              <Link
                to="/extra-work?mine=1"
                className="kpi-card"
                data-testid="dashboard-my-extra-work"
              >
                <div className="kpi-label">{t("my_work.extra_work")}</div>
                <div className="kpi-row-2">
                  <div className="kpi-value">{fmt(myCounts.extraWork)}</div>
                </div>
              </Link>
              <Link
                to="/extra-work?mine=1&request_intent=REQUEST_QUOTE"
                className="kpi-card"
                data-testid="dashboard-my-quote-requests"
              >
                <div className="kpi-label">{t("my_work.quote_requests")}</div>
                <div className="kpi-row-2">
                  <div className="kpi-value">{fmt(myCounts.quoteRequests)}</div>
                </div>
              </Link>
            </div>
          </section>
        )}

        {/* RF-16 (#106) — attention cards replace the dashboard's big
            lists (which now live exclusively on the Tickets / Extra
            Work pages). Each card: count + top rows + a deep link into
            the full page with the right preset applied. */}
        <section
          className="attention-grid"
          data-testid="dashboard-attention"
          style={{ marginTop: 12 }}
        >
          <div className="card attention-card" data-testid="attention-review">
            <div className="attention-card-head">
              <span className="attention-card-title">
                {t("attention.review_title")}
              </span>
              <span className="attention-card-count">
                {fmt(stats?.by_status?.WAITING_MANAGER_REVIEW ?? null)}
              </span>
            </div>
            <ul className="attention-card-list">
              {(attnReview?.rows ?? []).map((ticket) => (
                <li key={ticket.id}>
                  <Link to={`/tickets/${ticket.id}`} className="attention-row">
                    <span className="attention-row-title">{ticket.title}</span>
                    <span className="muted small">
                      {formatDate(ticket.created_at)}
                    </span>
                  </Link>
                </li>
              ))}
              {attnReview !== null && attnReview.rows.length === 0 && (
                <li className="muted small">{t("attention.empty")}</li>
              )}
            </ul>
            <Link
              to="/tickets?status=WAITING_MANAGER_REVIEW"
              className="attention-card-link"
              data-testid="attention-review-link"
            >
              {t("attention.view_all")}
            </Link>
          </div>

          <div
            className="card attention-card"
            data-testid="attention-unassigned"
          >
            <div className="attention-card-head">
              <span className="attention-card-title">
                {t("attention.unassigned_title")}
              </span>
              <span className="attention-card-count">
                {attnUnassigned === null ? "—" : attnUnassigned.count}
              </span>
            </div>
            <ul className="attention-card-list">
              {(attnUnassigned?.rows ?? []).map((ticket) => (
                <li key={ticket.id}>
                  <Link to={`/tickets/${ticket.id}`} className="attention-row">
                    <span className="attention-row-title">{ticket.title}</span>
                    <span className="muted small">
                      {formatDate(ticket.created_at)}
                    </span>
                  </Link>
                </li>
              ))}
              {attnUnassigned !== null && attnUnassigned.rows.length === 0 && (
                <li className="muted small">{t("attention.empty")}</li>
              )}
            </ul>
            <Link
              to="/tickets?status=OPEN&unassigned=1"
              className="attention-card-link"
              data-testid="attention-unassigned-link"
            >
              {t("attention.view_all")}
            </Link>
          </div>

          <div className="card attention-card" data-testid="attention-activity">
            <div className="attention-card-head">
              <span className="attention-card-title">
                {t("attention.activity_title")}
              </span>
            </div>
            <ul className="attention-card-list">
              {(attnActivity ?? []).map((item) => {
                const href = notificationHref(item);
                const body = (
                  <>
                    <span className="attention-row-title">{item.summary}</span>
                    <span className="muted small">
                      {formatDate(item.created_at)}
                    </span>
                  </>
                );
                return (
                  <li key={item.id}>
                    {href ? (
                      <Link to={href} className="attention-row">
                        {body}
                      </Link>
                    ) : (
                      <span className="attention-row">{body}</span>
                    )}
                  </li>
                );
              })}
              {attnActivity !== null && attnActivity.length === 0 && (
                <li className="muted small">{t("attention.empty")}</li>
              )}
            </ul>
            <Link
              to="/notifications"
              className="attention-card-link"
              data-testid="attention-activity-link"
            >
              {t("attention.view_all")}
            </Link>
          </div>
        </section>
          </>
        )}

        {isTicketsPage && (
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
                  {searchParams.get("mine") === "1" && (
                    <div
                      className="active-filter-chip"
                      data-testid="dashboard-mine-filter-chip"
                    >
                      <span>{t("my_work.filter_chip")}</span>
                      <Link to="/tickets" className="active-filter-clear">
                        {t("my_work.filter_clear")}
                      </Link>
                    </div>
                  )}
                  {unassignedFilter && (
                    <div
                      className="active-filter-chip"
                      data-testid="dashboard-unassigned-filter-chip"
                    >
                      <span>{t("attention.unassigned_chip")}</span>
                      <button
                        type="button"
                        className="active-filter-clear"
                        onClick={() => {
                          setPage(1);
                          setUnassignedFilter(false);
                        }}
                      >
                        {t("my_work.filter_clear")}
                      </button>
                    </div>
                  )}
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
                        // Sprint 7 — a status change leaves the
                        // bulk-confirm queue; drop any selection so it
                        // can't carry across filters.
                        setSelectedIds(new Set<number>());
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
                    {isProviderManagementRole(userRole) &&
                      statusFilter !== "WAITING_MANAGER_REVIEW" && (
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          data-testid="dashboard-manager-review-preset"
                          onClick={() => {
                            setPage(1);
                            setSelectedIds(new Set<number>());
                            setStatusFilter("WAITING_MANAGER_REVIEW");
                          }}
                        >
                          {t("bulk_confirm.queue_preset")}
                        </button>
                      )}
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

                {bulkMode && selectedVisibleIds.length > 0 && (
                  <div
                    className="bulk-action-bar"
                    data-testid="dashboard-bulk-action-bar"
                  >
                    <span className="bulk-action-bar-count">
                      {t("bulk_confirm.selected_count", {
                        count: selectedVisibleIds.length,
                      })}
                    </span>
                    <div className="bulk-action-bar-actions">
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => setSelectedIds(new Set<number>())}
                        disabled={bulkSubmitting}
                      >
                        {t("bulk_confirm.clear_selection")}
                      </button>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        data-testid="dashboard-bulk-confirm-button"
                        onClick={handleBulkConfirm}
                        disabled={bulkSubmitting}
                      >
                        {bulkSubmitting
                          ? t("bulk_confirm.confirming")
                          : t("bulk_confirm.confirm_action", {
                              count: selectedVisibleIds.length,
                            })}
                      </button>
                    </div>
                  </div>
                )}

                {loading && (
                  <div className="loading-bar" style={{ margin: 0 }}>
                    <div className="loading-bar-fill" />
                  </div>
                )}

                <div className="table-wrap ticket-list-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        {bulkMode && (
                          <th style={{ width: 36 }}>
                            <input
                              type="checkbox"
                              aria-label={t("bulk_confirm.select_all")}
                              data-testid="dashboard-bulk-select-all"
                              checked={allVisibleSelected}
                              onChange={toggleAllVisible}
                            />
                          </th>
                        )}
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
                          {bulkMode && (
                            <td
                              onClick={(event) => event.stopPropagation()}
                              onKeyDown={(event) => event.stopPropagation()}
                            >
                              <input
                                type="checkbox"
                                aria-label={t("bulk_confirm.select_row", {
                                  ticket: ticket.ticket_no,
                                })}
                                checked={selectedIds.has(ticket.id)}
                                onChange={() => toggleRowSelection(ticket.id)}
                              />
                            </td>
                          )}
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

      </div>
    </div>
  );
}
