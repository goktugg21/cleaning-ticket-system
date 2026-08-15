import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
// Sprint 180 §3 — `CSSProperties` and `Layers` left with
// `ExtraWorkOriginPill`; they were only ever used by it.
import { Plus, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { api, getApiError } from "../api/client";
import { getMySlots } from "../api/admin";
import {
  getExtraWorkStats,
  listAllExtraWork,
  listExtraWork,
} from "../api/extraWork";
import { getInboxUnreadCount } from "../api/inbox";
import { listNotifications, notificationHref } from "../api/notifications";
import type {
  AssignmentCandidate,
  ExtraWorkRequestList,
  ExtraWorkStats,
  Notification,
  PaginatedResponse,
  TicketList,
  TicketStats,
  TicketStatsByBuildingResponse,
  TicketStatsByBuildingRow,
  TicketStatus,
} from "../api/types";
import {
  bulkAssignTickets,
  bulkConfirmTickets,
  listTicketAssignmentCandidates,
} from "../api/tickets";
import { useAuth } from "../auth/AuthContext";
import {
  canAccessBilling,
  canAccessExtraWork,
  isProviderManagementRole,
  isStaffRole,
} from "../auth/permissions";
import { AssignPeopleDialog } from "../components/AssignPeopleDialog";
import { EditModeToggle } from "../components/EditModeToggle";
import { ExtraWorkOriginPill } from "../components/ExtraWorkOriginPill";
import { SLABadge } from "../components/sla/SLABadge";
import { StatusTiles } from "../components/StatusTiles";
import { useToast } from "../components/ToastProvider";
import { useEditMode } from "../lib/useEditMode";
import { currentMonth, splitOpenInvoiced, sumRows } from "../lib/billing";
import { ticketStatusLabelKey } from "../lib/enumLabels";
import {
  TICKET_LIST_STATUSES,
  ticketListStatusParam,
  visibleTicketTotal,
} from "../lib/ticketStatus";
import { formatDate, formatDateTime, formatMoney } from "../lib/intl";
import { StatusBadge } from "../components/StatusBadge";

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

// Sprint 182 §1 — the hand-written eight-status array that used to sit
// here is gone. It listed eight of the nine `TicketStatus` members, and
// nothing warned anyone: the chips omitted `CONVERTED_TO_EXTRA_WORK`
// while the "All" tile counted it, which is the owner's "ALL says 142
// but the chips add up to 138". `lib/ticketStatus.ts` derives the list
// from a `Record` over the union, so a ninth status now fails the
// compiler instead of quietly vanishing from a screen.

/**
 * Sprint 183 §1 — ONE chip, not three segments and a sub-page.
 *
 * The owner: "there is no need for both a chargeable-work filter on the
 * tickets page AND a chargeable-work sub-page. Just a chip on tickets to
 * show regular tickets only."
 *
 * So the sub-page, its route and its nav entry are gone, and what is
 * left is exactly what he asked for: the list shows everything by
 * default, and one labelled chip narrows it to ordinary tickets. Off is
 * always one click away, which is the house rule — nothing hidden with
 * no way back.
 *
 * `chargeable` survives as a PARSED value with no control that sets it,
 * so a bookmarked `?work=chargeable` still resolves rather than throwing;
 * it renders as "everything", which is the least surprising fallback for
 * a link to a view that no longer exists.
 */
type WorkTypeFilter = "all" | "tickets" | "chargeable";

// (RF-16 removed the dashboard Extra Work status breakdown — the EW
// status vocabulary now lives with the list on ExtraWorkListPage.)

const PRIORITY_OPTIONS: Priority[] = ["NORMAL", "HIGH", "URGENT"];

// Sprint 180 §1 — how long a ticket may sit in WAITING_CUSTOMER_APPROVAL
// before the dashboard calls it overdue. Mirrors
// `backend/tickets/auto_close.py::STALLED_CUSTOMER_APPROVAL_DAYS`; the
// backend filter takes any number of days, this is only what the UI
// asks for. Such work is DONE and unbillable — `is_earned` needs
// CLOSED, and CLOSED is downstream of the customer's answer — so a
// silent queue here is lost revenue, not just a stale list.
const STALLED_APPROVAL_DAYS = 14;

/**
 * Sprint 181 §4 — `historical` is gone from the UI.
 *
 * It meant "this ticket predates the SLA engine": a migration artefact,
 * not something an operator should ever have to read or reason about.
 * The owner has confirmed the SLA engine is here to stay, and on
 * crmtest all 79 historical tickets are already soft-deleted, so the
 * option now matches nothing at all — a filter that can only return an
 * empty list is worse than no filter.
 *
 * A UI removal only. `HISTORICAL` stays in the backend constant and in
 * `sla_backfill`, which still writes it, and stays in `SLADisplayState`
 * so a legacy row that does surface renders as something rather than
 * breaking the badge.
 */
const SLA_FILTER_VALUES: Exclude<SLAFilterValue, "" | "historical">[] = [
  "on_track",
  "at_risk",
  "breached",
  "paused",
  "completed",
];

function priorityCellClass(priority: string): string {
  return `cell-tag cell-tag-${priority.toLowerCase()}`;
}

// Sprint 182 §2 — `statusCellClass` is gone with the two cells that
// called it. It derived a CSS class by lowercasing the enum, which is a
// second colour vocabulary beside `StatusBadge`'s tone map: the two
// agreed for six statuses and quietly disagreed for the rest.

// Sprint 180 §3 — `ExtraWorkOriginPill` moved to
// `components/ExtraWorkOriginPill.tsx`. It lived here as a local
// component, which is why the dashboard's ticket table showed a
// ticket's Extra Work origin and the agenda and meldingen lists showed
// nothing. Same markup, same testids, same translation keys — one
// definition, three consumers.

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
  customerId,
  hideHeader = false,
}: {
  /** Sprint 183 §1 — the `"chargeable-work"` variant is gone with its
   *  sub-page. The narrowing it stood for is the list's own chip now. */
  /** Sprint 181 §5 / restored at the Sprint 183 integration —
   *  `"chargeable-work"` is this same page narrowed to tickets born from
   *  an Extra Work. A variant rather than a second implementation, so the
   *  two can never drift. Sprint 183 deleted it on a misread instruction:
   *  the owner asked for the redundant CHIP to go, not the page. */
  variant?: "dashboard" | "tickets-page" | "chargeable-work";
  /** Sprint 169 §8 — mounted INSIDE a customer: the list is narrowed to
   *  that customer and everything else is identical.
   *
   *  `CustomerTicketsPage` was a 295-line read-only re-implementation of
   *  this list with no selection, no `MultiSelectToolbar` and no bulk
   *  actions, because the two were independently maintained copies. The
   *  owner's rule is that a list behaves the same whether you reach it
   *  from the sidebar or from inside a customer, so the customer page
   *  now mounts THIS list rather than keeping a second one.
   *
   *  Narrowing is a UI convenience: the request carries `customer=<id>`
   *  and the SERVER still decides what the actor may see. */
  customerId?: number;
  /** The customer page draws its own header. */
  hideHeader?: boolean;
} = {}) {
  const isChargeableWork = variant === "chargeable-work";
  const isTicketsPage = variant === "tickets-page" || isChargeableWork;
  const navigate = useNavigate();
  const { me } = useAuth();
  const { push } = useToast();
  const { t } = useTranslation(["dashboard", "common"]);
  const userRole = me?.role ?? null;
  // Sprint 182 §2 — ONE word per status, from the source every other
  // screen reads.
  //
  // This page built its own i18n key by lowercasing the enum, which
  // reached the OLDER `common:status.*` block — where APPROVED is the
  // bare word "Approved". That bare word labels at least five different
  // things in this product, and on a ticket it means one specific thing:
  // the customer accepted the finished WORK. `ticket_status.approved`
  // already says exactly that ("Work approved" / "Werk akkoord") and is
  // what `StatusBadge` has rendered on the Extra Work list for a sprint.
  // Two screens showing one fact now show one string.
  const tStatus = (status: TicketStatus) =>
    t(ticketStatusLabelKey(status), { ns: "common" });
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
  // Sprint 158 §2 — the TICKETS page opens on what has not been
  // actioned. `OPEN` is the genuinely-untouched status in
  // `TicketStatus`: every spawn path creates a ticket OPEN and writes
  // the initial history row at that status, so nothing has happened to
  // an OPEN ticket yet.
  //
  // The DASHBOARD variant keeps "" — it is a summary of everything by
  // definition, and defaulting it would make the dashboard disagree with
  // its own attention cards.
  //
  // `?status=` still wins, and `?status=ALL` is how a link asks for
  // everything, so the existing deep links from the dashboard widgets
  // are unaffected.
  const [statusFilter, setStatusFilter] = useState<TicketStatus | "">(() => {
    const raw = new URLSearchParams(window.location.search).get("status");
    if (raw === "ALL") return "";
    if (raw && (TICKET_LIST_STATUSES as readonly string[]).includes(raw)) {
      return raw as TicketStatus;
    }
    return variant === "tickets-page" ? "OPEN" : "";
  });
  /**
   * Sprint 183 §1 — `?work=tickets`, URL-backed so the view survives a
   * refresh and can be linked to. `?work=chargeable` from an old
   * bookmark parses to "all": the view it named no longer exists, and
   * showing everything is friendlier than showing nothing.
   */
  const [workTypeFilter, setWorkTypeFilter] = useState<WorkTypeFilter>(() => {
    // The Chargeable work sub-page IS this page pinned to chargeable
    // work, so the route decides the filter and the chip below never
    // offers "chargeable" as a third state -- that redundancy is the
    // thing the owner asked to remove.
    if (variant === "chargeable-work") return "chargeable";
    const raw = new URLSearchParams(window.location.search).get("work");
    if (raw === "all" || raw === "tickets") return raw;
    // The Tickets page is the ORDINARY tickets page. "Tickets only" was
    // a confusing name for a chip on a page where everything is already
    // a ticket -- and chargeable work has its own page, so showing it in
    // both was the duplication the owner objected to. Default: ordinary
    // tickets. The chip ADDS chargeable work back for the rare view of
    // everything at once.
    return variant === "tickets-page" ? "tickets" : "all";
  });
  const [unassignedFilter, setUnassignedFilter] = useState(
    () => new URLSearchParams(window.location.search).get("unassigned") === "1",
  );
  // Sprint 180 §1 — the "customer never answered" preset. Deep-linked
  // from the dashboard's approval-overdue attention row; shows a
  // clearable chip like every other preset on this page.
  const [stalledApprovalFilter, setStalledApprovalFilter] = useState(
    () => new URLSearchParams(window.location.search).get("stalled") === "1",
  );
  // Sprint 180 §2 — "completed extra works should not show inside
  // tickets."
  //
  // ON by default because that is what was asked, and because a
  // provider looking at the ticket list is looking for work to do.
  // Clearable because the house rule is that nothing is hidden with no
  // way back (the Sprint 158 escape-hatch shape): the chip below states
  // that rows are hidden and turns it off in one click.
  //
  // A URL opt-out (`?finished_extra_work=1`) exists so a link can point
  // straight at the unhidden list.
  const [hideFinishedExtraWork, setHideFinishedExtraWork] = useState(
    () =>
      new URLSearchParams(window.location.search).get(
        "finished_extra_work",
      ) !== "1",
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

  // Sprint 159 §2 — assign managers AND workers to the selected tickets
  // in one dialog and one request, the same surface the Extra Work list
  // has had since Sprint 157.
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignBusy, setAssignBusy] = useState(false);
  const [assignError, setAssignError] = useState("");
  const [assignCandidates, setAssignCandidates] = useState<{
    WORKER: AssignmentCandidate[];
    MANAGER: AssignmentCandidate[];
  }>({ WORKER: [], MANAGER: [] });

  const [searchParams, setSearchParams] = useSearchParams();
  const slaFilter: SLAFilterValue = (() => {
    const raw = searchParams.get("sla") || "";
    // Sprint 181 §4 — validated against the OFFERED set, so a stale
    // `?sla=historical` bookmark resolves to "no filter" (the full list)
    // rather than to a state with no control to clear it. Derived from
    // `SLA_FILTER_VALUES` rather than re-listed, so removing an option
    // there cannot leave a reachable value here.
    return (SLA_FILTER_VALUES as string[]).includes(raw)
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
    // Sprint 182 §1 — the ROWS agree with the chips above them.
    //
    // A converted ticket is not on this list (the owner's decision: its
    // work did not finish, it became an Extra Work), so with no status
    // chosen the query asks for exactly the statuses the chips count.
    // Server-side via `status__in`, because filtering the current page
    // in the client would leave `count` — and therefore the pager and
    // the "All" tile — describing a different set than the rows.
    else if (isTicketsPage) params.status__in = ticketListStatusParam();
    if (priorityFilter) params.priority = priorityFilter;
    if (searchActive.trim()) params.search = searchActive.trim();
    if (slaFilter) params.sla = slaFilter;
    // RF-16 — unassigned preset (attention-card deep link). Uses the
    // backend filterset's assigned_to isnull lookup.
    if (unassignedFilter) params.assigned_to__isnull = "true";
    // Sprint 180 §1 — approval-overdue preset. The backend filter is
    // the authority on what "overdue" means (it ages
    // `sent_for_approval_at`, the column the transition stamps); the
    // page only supplies the threshold.
    if (stalledApprovalFilter) {
      params.awaiting_customer_approval_days = STALLED_APPROVAL_DAYS;
    }
    // Sprint 180 §2 — hide finished Extra Work. Sent only on the
    // Tickets page: it is a list-reading preference, and the dashboard
    // widgets that share this component's fetch helpers count totals.
    if (isTicketsPage && hideFinishedExtraWork) {
      params.hide_finished_extra_work = "true";
    }
    // M6.3 — "my work" deep-links. Only applied on the Tickets page
    // (where the clear chip is shown).
    // The fixed customer, when this list is mounted inside one.
    if (customerId !== undefined) params.customer = customerId;
    // Sprint 183 §1 — the work-type narrowing, server-side
    // (`TicketFilter.is_extra_work`) so it survives pagination instead
    // of filtering one page. Sprint 183 §2 sends the SAME parameter to
    // `/tickets/stats/`, which is what stopped the chips showing dashes.
    if (isTicketsPage) {
      if (workTypeFilter === "chargeable") params.is_extra_work = "true";
      else if (workTypeFilter === "tickets") params.is_extra_work = "false";
    }
    if (isTicketsPage) {
      if (searchParams.get("mine") === "1" && me?.id) params.created_by = me.id;
      const typeParam = searchParams.get("type");
      if (typeParam) params.type = typeParam;
      const exclTypeParam = searchParams.get("exclude_type");
      if (exclTypeParam) params.exclude_type = exclTypeParam;
    }
    return params;
  }, [
    customerId,
    page,
    statusFilter,
    priorityFilter,
    searchActive,
    slaFilter,
    unassignedFilter,
    stalledApprovalFilter,
    hideFinishedExtraWork,
    searchParams,
    me,
    isTicketsPage,
    workTypeFilter,
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

  // Sprint 7 — bulk manager-confirm, for provider management. The
  // submittable set is always derived from the currently-visible rows,
  // so changing filters or pages can never bulk-confirm a ticket that is
  // no longer on screen.
  //
  // Sprint 159 §2 — the selection is behind the Sprint 155 §4 Edit gate
  // now, like every other list. The hook supplies only the MODE: this
  // page owns `selectedIds` because the set may legitimately span pages,
  // and adopting the hook's own selection (filtered to the visible rows)
  // would silently drop the off-screen half.
  //
  // The gate also widens what selection is FOR. It used to exist only in
  // the WAITING_MANAGER_REVIEW queue, because bulk-confirm was the only
  // thing it fed; assigning people is not queue-specific, so the mode is
  // now available wherever a provider manager is looking and the
  // CONFIRM button is what stays queue-specific.
  const edit = useEditMode(
    isProviderManagementRole(userRole) ? tickets.map((t) => t.id) : [],
    { onExit: () => setSelectedIds(new Set<number>()) },
  );
  const bulkMode = edit.editMode;
  const canBulkConfirm = statusFilter === "WAITING_MANAGER_REVIEW";
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

  /** Sprint 159 §2 — the candidates for BOTH roles, from the server.
   *
   *  With several tickets selected the offer is the INTERSECTION:
   *  somebody eligible at one building but not another would be
   *  rejected for the whole batch (the endpoint is all-or-nothing), so
   *  offering them would be offering a guaranteed failure. Same rule the
   *  Extra Work list applies. */
  const loadAssignCandidates = useCallback(async (ticketIds: number[]) => {
    if (ticketIds.length === 0) {
      setAssignCandidates({ WORKER: [], MANAGER: [] });
      return;
    }
    const forRole = async (role: "WORKER" | "MANAGER") => {
      const lists = await Promise.all(
        ticketIds.map((id) => listTicketAssignmentCandidates(id, role)),
      );
      const [first, ...rest] = lists;
      return first.filter((person) =>
        rest.every((list) => list.some((other) => other.id === person.id)),
      );
    };
    try {
      const [workers, managers] = await Promise.all([
        forRole("WORKER"),
        forRole("MANAGER"),
      ]);
      setAssignCandidates({ WORKER: workers, MANAGER: managers });
    } catch (err) {
      setAssignError(getApiError(err));
      setAssignCandidates({ WORKER: [], MANAGER: [] });
    }
  }, []);

  const openAssign = useCallback(async () => {
    setAssignError("");
    setAssignOpen(true);
    await loadAssignCandidates(selectedVisibleIds);
  }, [loadAssignCandidates, selectedVisibleIds]);

  const runAssign = useCallback(
    async (managerIds: number[], workerIds: number[]) => {
      setAssignBusy(true);
      setAssignError("");
      try {
        const result = await bulkAssignTickets({
          tickets: selectedVisibleIds,
          managers: managerIds,
          workers: workerIds,
          mode: "assign",
        });
        setAssignOpen(false);
        edit.exit();
        push({
          variant: "success",
          title: t("common:assign_people.assigned", { count: result.created }),
        });
      } catch (err) {
        setAssignError(getApiError(err));
      } finally {
        setAssignBusy(false);
      }
    },
    [selectedVisibleIds, edit, push, t],
  );

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
      // Sprint 180 §2 — the status tiles sit directly above the rows
      // they count, so they must be counting the same rows. When the
      // Tickets page is hiding finished Extra Work, the stats request
      // carries the same flag and the endpoint applies the same
      // exclusion. The DASHBOARD is a summary of everything and sends
      // nothing, so its KPI strip is unchanged.
      // Sprint 183 integration — the chips also carry the WORK-TYPE
      // narrowing now. Sprint 183 gave `/tickets/stats/` the same
      // `is_extra_work` the list takes, but the page never sent it and
      // the tiles kept the old "we cannot know" em-dash fallback. Once
      // the Tickets page started defaulting to ordinary tickets, that
      // fallback fired on the DEFAULT view and every chip read as a dash.
      const statsParams: Record<string, string> = {};
      if (isTicketsPage && hideFinishedExtraWork)
        statsParams.hide_finished_extra_work = "true";
      if (isTicketsPage && workTypeFilter === "chargeable")
        statsParams.is_extra_work = "true";
      else if (isTicketsPage && workTypeFilter === "tickets")
        statsParams.is_extra_work = "false";
      const response = await api.get<TicketStats>("/tickets/stats/", {
        params: Object.keys(statsParams).length ? statsParams : undefined,
      });
      setStats(response.data);
    } catch {
      // KPI cards fall back to "—" placeholders if the endpoint fails.
    }
  }, [isTicketsPage, hideFinishedExtraWork, workTypeFilter]);

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
  // Sprint 180 §1 — finished work the customer has not answered on.
  // This is the edge case auto-close CANNOT fix: nobody approves, so
  // nothing closes, so `is_earned` never turns true and the work is
  // never invoiced. We do not manufacture the approval on a timer —
  // approving on the customer's behalf is a money decision and the
  // system already has a reasoned, audited route for it. We make the
  // queue visible instead, so somebody chases it.
  const [attnStalledApproval, setAttnStalledApproval] = useState<{
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
  // #109 Part G — the full billing-month rows (already fetched for the
  // split above) power the "Facturatie <maand>" mini per-building panel;
  // storing them adds ZERO extra requests.
  const [billingRows, setBillingRows] = useState<
    ExtraWorkRequestList[] | null
  >(null);
  const [todaySlotCount, setTodaySlotCount] = useState<number | null>(null);
  // #109 Part G — most-recent tickets + extra work for the "Laatste
  // tickets / extra werk" panel (fetched in parallel inside the
  // existing attention loader — no new waterfall).
  const [recentTickets, setRecentTickets] = useState<TicketList[] | null>(
    null,
  );
  const [recentExtraWork, setRecentExtraWork] = useState<
    ExtraWorkRequestList[] | null
  >(null);

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
      // Sprint 120 — this used to request page_size=500, but DRF's
      // max_page_size (config/pagination.py) silently clamps that to 200,
      // so any month with more than 200 matching EW rows was undercounted
      // with no error. listAllExtraWork pages exhaustively instead.
      canAccessBilling(userRole)
        ? listAllExtraWork({ billing_period: currentMonth() })
        : Promise.resolve(null),
      isStaffRole(userRole) ? getMySlots() : Promise.resolve(null),
    ]);
    if (inbox.status === "fulfilled") setInboxUnread(inbox.value);
    if (billing.status === "fulfilled" && billing.value !== null) {
      setBillingMonthTotals(splitOpenInvoiced(billing.value));
      setBillingRows(billing.value);
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
      const [rev, una, stalled, act, recentTk, recentEw] = await Promise.all([
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
        // Sprint 180 §1 — the approval-overdue queue. The backend
        // filter already narrows to WAITING_CUSTOMER_APPROVAL, so no
        // status param is needed here.
        api.get<PaginatedResponse<TicketList>>("/tickets/", {
          params: {
            awaiting_customer_approval_days: STALLED_APPROVAL_DAYS,
            page_size: 3,
          },
        }),
        listNotifications({ page: 1 }),
        // #109 Part G — most-recent 5 across the caller's scope (the
        // backend scopes /tickets/ + /extra-work/ already; default
        // ordering is newest-first). Parallel with the batch above.
        api.get<PaginatedResponse<TicketList>>("/tickets/", {
          params: { page_size: 5 },
        }),
        listExtraWork({ page_size: 5 }),
      ]);
      setAttnReview({ count: rev.data.count, rows: rev.data.results });
      setAttnUnassigned({ count: una.data.count, rows: una.data.results });
      setAttnStalledApproval({
        count: stalled.data.count,
        rows: stalled.data.results,
      });
      setAttnActivity(act.results.slice(0, 3));
      setRecentTickets(recentTk.data.results.slice(0, 5));
      setRecentExtraWork(recentEw.results.slice(0, 5));
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

  // #109 Part G — per-building billing breakdown for the "Facturatie"
  // mini panel, from the already-fetched billing rows (top 4 by total).
  const billingByBuilding = useMemo(() => {
    if (billingRows === null) return null;
    const byBuilding = new Map<number, ExtraWorkRequestList[]>();
    for (const r of billingRows) {
      const list = byBuilding.get(r.building) ?? [];
      list.push(r);
      byBuilding.set(r.building, list);
    }
    return [...byBuilding.entries()]
      .map(([buildingId, rows]) => ({
        buildingId,
        buildingName: rows[0].building_name,
        totals: sumRows(rows),
      }))
      .sort((a, b) => b.totals.total - a.totals.total)
      .slice(0, 4);
  }, [billingRows]);

  // #108 Option A — count badge for the "Aandacht nodig" rows. Rows the
  // provider must act on get the warning tint as soon as the count is
  // positive; rows waiting on someone else stay neutral.
  const attnBadge = (value: number | null, actionable: boolean): string =>
    actionable && value !== null && value > 0
      ? "attn-count attn-count-warn"
      : "attn-count";

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
      {!hideHeader && (
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
            {isChargeableWork
              ? t("common:chargeable_work.title")
              : isTicketsPage
                ? t("tickets_page.title")
                : t("title")}
          </h2>
          <p className="page-sub">
            {/* RF-16 — the dashboard loads no list, so the list-count
                subtitle only makes sense on the Tickets page. The
                dashboard shows the muted full-lists pointer instead
                (#108 Option A). */}
            {!isTicketsPage ? (
              <>
                {t("pointer.full_lists")}{" "}
                <Link to="/tickets" className="page-sub-link">
                  {t("pointer.tickets")}
                </Link>
                {" · "}
                <Link to="/extra-work" className="page-sub-link">
                  {t("pointer.extra_work")}
                </Link>
              </>
            ) : loading ? (
              t("loading_data")
            ) : (
              t("subtitle_counts", {
                count,
                visible: tickets.length,
                page,
                pages: pageCount,
              })
            )}
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
      )}

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
        {/* #108 Option A — the provider-management dashboard: a 4-KPI
            hero, an "Aandacht nodig" priority list beside a compact
            "Vandaag" column, and a "Mijn werk" chip row. All values come
            from the existing #106/#107 loaders — no new fetches. */}
        {!isTicketsPage && isProviderManagementRole(userRole) && (
          <>
            <div
              className="operations-kpi-grid option-a-hero"
              data-testid="dashboard-ops-kpi-row"
            >
              <div className="kpi-card" data-testid="hero-open-work">
                <div className="kpi-label">{t("hero.open_label")}</div>
                <div className="kpi-row-2">
                  <div className="kpi-value">{fmt(opsKpis.totalOpen)}</div>
                </div>
                <div className="kpi-meta">{t("hero.open_meta")}</div>
              </div>
              <div
                className="kpi-card kpi-urgent"
                data-testid="hero-urgent"
              >
                <div className="kpi-label">{t("hero.urgent_label")}</div>
                <div className="kpi-row-2">
                  <div className="kpi-value">{fmt(opsKpis.urgent)}</div>
                </div>
                <div className="kpi-meta">{t("hero.urgent_meta")}</div>
              </div>
              <div className="kpi-card" data-testid="hero-awaiting">
                <div className="kpi-label">{t("hero.awaiting_label")}</div>
                <div className="kpi-row-2">
                  <div className="kpi-value">{fmt(opsKpis.awaiting)}</div>
                </div>
                <div className="kpi-meta">{t("hero.awaiting_meta")}</div>
              </div>
              <Link
                to="/invoices"
                className="kpi-card"
                data-testid="hero-month"
              >
                <div className="kpi-label">{t("hero.month_label")}</div>
                <div className="kpi-row-2">
                  <div className="kpi-value">
                    {billingMonthTotals
                      ? formatMoney(billingMonthTotals.openTotal)
                      : "—"}
                  </div>
                </div>
                <div className="kpi-meta">
                  {billingMonthTotals
                    ? t("hero.month_meta", {
                        invoiced: formatMoney(
                          billingMonthTotals.invoicedTotal,
                        ),
                      })
                    : t("hero.month_loading")}
                </div>
                {/* #109 Part G — explicit open-vs-invoiced split under
                    the amount (data already fetched for the widget). */}
                {billingMonthTotals && (
                  <div
                    className="kpi-split"
                    data-testid="hero-month-split"
                  >
                    <span className="kpi-split-open">
                      {t("hero.split_open", {
                        amount: formatMoney(billingMonthTotals.openTotal),
                      })}
                    </span>
                    <span className="kpi-split-invoiced">
                      {t("hero.split_invoiced", {
                        amount: formatMoney(
                          billingMonthTotals.invoicedTotal,
                        ),
                      })}
                    </span>
                  </div>
                )}
              </Link>
            </div>

            <section
              className="attention-layout"
              data-testid="dashboard-attention"
            >
              <div
                className="card attention-card"
                data-testid="attention-needed"
              >
                <div className="attention-card-head">
                  <span className="attention-card-title">
                    {t("attention_panel.title")}
                  </span>
                </div>
                <ul className="attn-list">
                  <li className="attn-item">
                    <Link
                      to="/tickets?status=WAITING_MANAGER_REVIEW"
                      className="attn-row"
                      data-testid="attention-review"
                    >
                      <span className="attn-row-label">
                        {t("attention.review_title")}
                      </span>
                      <span
                        className={attnBadge(
                          stats?.by_status?.WAITING_MANAGER_REVIEW ?? null,
                          true,
                        )}
                      >
                        {fmt(stats?.by_status?.WAITING_MANAGER_REVIEW ?? null)}
                      </span>
                    </Link>
                  </li>
                  <li className="attn-item">
                    <Link
                      to="/tickets?status=OPEN&unassigned=1"
                      className="attn-row"
                      data-testid="attention-unassigned"
                    >
                      <span className="attn-row-label">
                        {t("attention.unassigned_title")}
                      </span>
                      <span
                        className={attnBadge(
                          attnUnassigned?.count ?? null,
                          true,
                        )}
                      >
                        {fmt(attnUnassigned?.count ?? null)}
                      </span>
                    </Link>
                    {(attnUnassigned?.rows ?? []).length > 0 && (
                      <ul className="attn-sublist">
                        {(attnUnassigned?.rows ?? []).slice(0, 3).map(
                          (ticket) => (
                            <li key={ticket.id}>
                              <Link
                                to={`/tickets/${ticket.id}`}
                                className="attention-row"
                              >
                                <span className="attention-row-title">
                                  {ticket.title}
                                </span>
                                <span className="muted small">
                                  {formatDate(ticket.created_at)}
                                </span>
                              </Link>
                            </li>
                          ),
                        )}
                      </ul>
                    )}
                  </li>
                  {/* Sprint 180 §1 — finished work the customer never
                      answered on. Unlike the row below it, this one IS
                      provider-actionable (chase the customer, or record
                      the approval on their behalf through the existing
                      reasoned override), and unlike the rest of the
                      list it is money: none of it can be invoiced until
                      it closes. So it gets the warning tint. */}
                  <li className="attn-item">
                    <Link
                      to={`/tickets?status=WAITING_CUSTOMER_APPROVAL&stalled=1`}
                      className="attn-row"
                      data-testid="attention-approval-overdue"
                    >
                      <span className="attn-row-label">
                        {t("attention.approval_overdue_title", {
                          days: STALLED_APPROVAL_DAYS,
                        })}
                      </span>
                      <span
                        className={attnBadge(
                          attnStalledApproval?.count ?? null,
                          true,
                        )}
                      >
                        {fmt(attnStalledApproval?.count ?? null)}
                      </span>
                    </Link>
                    {(attnStalledApproval?.rows ?? []).length > 0 && (
                      <ul className="attn-sublist">
                        {(attnStalledApproval?.rows ?? [])
                          .slice(0, 3)
                          .map((ticket) => (
                            <li key={ticket.id}>
                              <Link
                                to={`/tickets/${ticket.id}`}
                                className="attention-row"
                              >
                                <span className="attention-row-title">
                                  {ticket.title}
                                </span>
                                <span className="muted small">
                                  {formatDate(ticket.created_at)}
                                </span>
                              </Link>
                            </li>
                          ))}
                      </ul>
                    )}
                  </li>
                  <li className="attn-item">
                    <Link
                      to="/extra-work?status=UNDER_REVIEW"
                      className="attn-row"
                      data-testid="attention-awaiting-pricing"
                    >
                      <span className="attn-row-label">
                        {t("attention.awaiting_pricing_title")}
                      </span>
                      <span
                        className={attnBadge(
                          extraWorkStats?.awaiting_pricing ?? null,
                          true,
                        )}
                      >
                        {fmt(extraWorkStats?.awaiting_pricing ?? null)}
                      </span>
                    </Link>
                  </li>
                  <li className="attn-item">
                    <Link
                      to="/extra-work?status=PRICING_PROPOSED"
                      className="attn-row"
                      data-testid="attention-awaiting-customer"
                    >
                      <span className="attn-row-label">
                        {t("attention.awaiting_customer_title")}
                      </span>
                      {/* Waiting on the CUSTOMER — not provider-actionable,
                          so this row never gets the warning tint. */}
                      <span className="attn-count">
                        {fmt(
                          extraWorkStats?.awaiting_customer_approval ?? null,
                        )}
                      </span>
                    </Link>
                  </li>
                </ul>
              </div>

              <div
                className="card attention-card"
                data-testid="dashboard-today"
              >
                <div className="attention-card-head">
                  <span className="attention-card-title">
                    {t("today.title")}
                  </span>
                </div>
                <ul className="attn-list">
                  <li className="attn-item">
                    <Link
                      to="/agenda"
                      className="attn-row"
                      data-testid="today-slots"
                    >
                      <span className="attn-row-label">{t("today.slots")}</span>
                      <span className="attn-count">{fmt(todaySlotCount)}</span>
                    </Link>
                  </li>
                  <li className="attn-item">
                    <Link
                      to="/inbox"
                      className="attn-row"
                      data-testid="today-inbox"
                    >
                      <span className="attn-row-label">
                        {t("widgets.inbox")}
                      </span>
                      <span className="attn-count">{fmt(inboxUnread)}</span>
                    </Link>
                  </li>
                </ul>
                <div className="attention-card-head">
                  <span className="attention-card-title">
                    {t("attention.activity_title")}
                  </span>
                </div>
                <ul
                  className="attention-card-list"
                  data-testid="attention-activity"
                >
                  {(attnActivity ?? []).map((item) => {
                    const href = notificationHref(item);
                    const body = (
                      <>
                        <span className="attention-row-title">
                          {item.summary}
                        </span>
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

            {me?.id && (
              <section
                className="mywork-section"
                data-testid="dashboard-my-work"
              >
                <div className="section-head" style={{ marginBottom: 10 }}>
                  <div className="section-head-title">{t("my_work.title")}</div>
                </div>
                <div className="mywork-chips">
                  <Link
                    to="/tickets?mine=1&exclude_type=REPORT"
                    className="mywork-chip"
                    data-testid="dashboard-my-tickets"
                  >
                    <span>{t("my_work.chip_tickets")}</span>
                    <span className="mywork-chip-count">
                      {fmt(myCounts.tickets)}
                    </span>
                  </Link>
                  <Link
                    to="/tickets?mine=1&type=REPORT"
                    className="mywork-chip"
                    data-testid="dashboard-my-meldingen"
                  >
                    <span>{t("my_work.chip_meldingen")}</span>
                    <span className="mywork-chip-count">
                      {fmt(myCounts.meldingen)}
                    </span>
                  </Link>
                  <Link
                    to="/extra-work?mine=1"
                    className="mywork-chip"
                    data-testid="dashboard-my-extra-work"
                  >
                    <span>{t("my_work.chip_extra_work")}</span>
                    <span className="mywork-chip-count">
                      {fmt(myCounts.extraWork)}
                    </span>
                  </Link>
                  <Link
                    to="/extra-work?mine=1&request_intent=REQUEST_QUOTE"
                    className="mywork-chip"
                    data-testid="dashboard-my-quote-requests"
                  >
                    <span>{t("my_work.chip_quotes")}</span>
                    <span className="mywork-chip-count">
                      {fmt(myCounts.quoteRequests)}
                    </span>
                  </Link>
                </div>
              </section>
            )}

            {/* #109 Part G — bottom density band (management view only):
                a Facturatie mini per-building panel + a compact
                Laatste-tickets/extra-werk list. Both reuse
                already-loaded data / the existing parallel loaders. */}
            <section
              className="dashboard-bottom-band"
              data-testid="dashboard-bottom-band"
            >
              <div
                className="card attention-card"
                data-testid="dashboard-billing-panel"
              >
                <div className="attention-card-head">
                  <span className="attention-card-title">
                    {t("bottom.billing_title", { month: currentMonth() })}
                  </span>
                  <Link
                    to="/invoices"
                    className="attention-card-link"
                    data-testid="dashboard-billing-link"
                  >
                    {t("attention.view_all")}
                  </Link>
                </div>
                {billingByBuilding === null ? (
                  <p className="muted small">{t("loading")}</p>
                ) : billingByBuilding.length === 0 ? (
                  <p className="muted small">{t("bottom.billing_empty")}</p>
                ) : (
                  <table className="data-table dashboard-mini-table">
                    <tbody>
                      {billingByBuilding.map((row) => (
                        <tr key={row.buildingId}>
                          <td>{row.buildingName}</td>
                          <td className="mini-num muted small">
                            {t("bottom.billing_open_count", {
                              count: row.totals.open,
                            })}
                          </td>
                          <td className="mini-num">
                            <strong>{formatMoney(row.totals.total)}</strong>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              <div
                className="card attention-card"
                data-testid="dashboard-recent-panel"
              >
                <div className="attention-card-head">
                  <span className="attention-card-title">
                    {t("bottom.recent_title")}
                  </span>
                </div>
                <ul className="attention-card-list">
                  {(recentTickets ?? []).map((tk) => (
                    <li key={`t-${tk.id}`}>
                      <Link
                        to={`/tickets/${tk.id}`}
                        className="attention-row"
                      >
                        <span className="attention-row-title">
                          {tk.ticket_no} · {tk.title}
                        </span>
                        <span className="muted small">
                          {formatDate(tk.created_at)}
                        </span>
                      </Link>
                    </li>
                  ))}
                  {(recentExtraWork ?? []).map((ew) => (
                    <li key={`e-${ew.id}`}>
                      <Link
                        to={`/extra-work/${ew.id}`}
                        className="attention-row"
                      >
                        <span className="attention-row-title">
                          {t("ops_type_extra_work")} · {ew.title}
                        </span>
                        <span className="muted small">
                          {ew.building_name}
                        </span>
                      </Link>
                    </li>
                  ))}
                  {recentTickets !== null &&
                    recentExtraWork !== null &&
                    recentTickets.length === 0 &&
                    recentExtraWork.length === 0 && (
                      <li className="muted small">{t("attention.empty")}</li>
                    )}
                </ul>
              </div>
            </section>
          </>
        )}

        {/* The STAFF + customer dashboard at "/" is preserved as-is —
            #108 rebuilt only the provider-management view above. (The
            management-only billing widget and "Mijn werk" cards never
            rendered for these roles, so they are absent here.) */}
        {!isTicketsPage && !isProviderManagementRole(userRole) && (
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
          <>
        {/* Sprint 163 §2 — the status strip sits ABOVE the two-column
            work-layout, not inside its narrow left column.

            It used to live in `.dash-main`, which `work-layout`
            sizes at 610px against a 340px side panel. Nine readable
            tiles do not fit 610px at any padding, so the strip could
            only ever wrap or scroll there however the tiles were
            styled — Sprint 161 made it scroll, Sprint 163's grid
            made it wrap, and both were treating the symptom. Full
            content width was the actual instruction. */}
        {/* Sprint 159 §3 — the same tiles the Extra Work list
            uses. The owner asked for the pair to match and named
            which way round.

            The counts come from the SERVER: `/tickets/stats/`
            already returns `by_status`, and the "Status
            breakdown" panel in the side column has rendered
            exactly these numbers since long before this sprint.
            Reusing its source rather than inventing a second one
            costs no extra request. Sprint 158's reasoning for
            leaving the chips countless was right for the numbers
            it had — the client holds one page — and that is
            precisely why these come from the stats endpoint and
            not from `tickets`. Until it resolves, `-1` renders
            an em dash rather than a wrong number. */}
        {/* Sprint 183 — ONE chip: "Tickets only". Pressed = ordinary
            tickets; unpressed = everything, the default, always one click
            away. The owner asked for the redundant CHARGEABLE chip to go,
            not the Chargeable work sub-page — that page is the only way to
            see chargeable work as a group and it stays. Sprint 183 read
            the instruction the other way round and deleted the page; the
            integration restored it. */}
        {!isChargeableWork && (
        <div className="work-strip" style={{ marginBottom: 12 }}>
          <div className="work-strip-toggle" data-testid="tickets-work-type">
            <button
              type="button"
              className={`btn btn-sm ${
                workTypeFilter === "all" ? "btn-primary" : "btn-secondary"
              }`}
              aria-pressed={workTypeFilter === "all"}
              data-testid="tickets-work-type-tickets"
              onClick={() => {
                const next_value =
                  workTypeFilter === "all" ? "tickets" : "all";
                setPage(1);
                setSelectedIds(new Set<number>());
                setWorkTypeFilter(next_value);
                const next = new URLSearchParams(searchParams);
                if (next_value === "tickets") next.delete("work");
                else next.set("work", next_value);
                setSearchParams(next, { replace: true });
              }}
            >
              {t("work_type.include_chargeable")}
            </button>
          </div>
        </div>
        )}

        {/* Sprint 182 §1/§4 — the counts and the rows describe the same
            set, or the counts say they cannot know.

            The stats request carries the SAME work-type and
            hide-finished flags as the list, so the tiles count exactly
            the rows beneath them. The em dash is now reserved for its
            real meaning: the stats call itself failed. */}
        <StatusTiles
          tiles={TICKET_LIST_STATUSES.map((value) => ({
            value,
            // The page's OWN status label helper, the same one
            // the dropdown below uses — a second labelling path
            // here rendered raw enum names.
            label: tStatus(value),
            count: stats ? (stats.by_status[value] ?? 0) : -1,
          }))}
          active={statusFilter}
          onChange={(value: string) => {
            setStatusFilter(value as TicketStatus | "");
            setPage(1);
            setSelectedIds(new Set<number>());
          }}
          // "All" counts what the chips count: the same stats response,
          // minus exactly the statuses this list does not show.
          //
          // It used to fall back to the list's own `count` under a
          // work-type narrowing, and to an em dash when a status chip was
          // also active — because the stats endpoint could not then be
          // asked for a narrowed total. It can now (the request carries
          // the same `is_extra_work`), so the fallbacks are gone: once the
          // Tickets page began defaulting to ordinary tickets, "All" was
          // reading a dash on the default view with a status selected.
          totalCount={visibleTicketTotal(stats)}
          testIdPrefix="tickets-status"
        />

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
                  {/* Sprint 180 §1 — approval-overdue preset chip. */}
                  {stalledApprovalFilter && (
                    <div
                      className="active-filter-chip"
                      data-testid="dashboard-stalled-approval-chip"
                    >
                      <span>
                        {t("attention.approval_overdue_chip", {
                          days: STALLED_APPROVAL_DAYS,
                        })}
                      </span>
                      <button
                        type="button"
                        className="active-filter-clear"
                        onClick={() => {
                          setPage(1);
                          setStalledApprovalFilter(false);
                        }}
                      >
                        {t("my_work.filter_clear")}
                      </button>
                    </div>
                  )}
                  {/* Sprint 180 §2 — the escape hatch for the hide.
                      Rendered whenever the hide is ON, so the list
                      never quietly omits rows: it says what it is
                      holding back and undoes it in one click. */}
                  {hideFinishedExtraWork && (
                    <div
                      className="active-filter-chip"
                      data-testid="dashboard-hide-finished-ew-chip"
                    >
                      <span>{t("finished_extra_work.hidden_chip")}</span>
                      <button
                        type="button"
                        className="active-filter-clear"
                        onClick={() => {
                          setPage(1);
                          setHideFinishedExtraWork(false);
                        }}
                        data-testid="dashboard-hide-finished-ew-show"
                      >
                        {t("finished_extra_work.show_all")}
                      </button>
                    </div>
                  )}
                  {/* ...and the way back to hiding, so the control is
                      a toggle rather than a one-way door. */}
                  {!hideFinishedExtraWork && (
                    <div
                      className="active-filter-chip"
                      data-testid="dashboard-show-finished-ew-chip"
                    >
                      <span>{t("finished_extra_work.shown_chip")}</span>
                      <button
                        type="button"
                        className="active-filter-clear"
                        onClick={() => {
                          setPage(1);
                          setHideFinishedExtraWork(true);
                        }}
                        data-testid="dashboard-hide-finished-ew-hide"
                      >
                        {t("finished_extra_work.hide_again")}
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
                  {isProviderManagementRole(userRole) && (
                    <EditModeToggle
                      editMode={edit.editMode}
                      onToggle={edit.toggleMode}
                      disabled={bulkSubmitting || assignBusy}
                      testId="dashboard-tickets-edit-toggle"
                    />
                  )}
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
                      {TICKET_LIST_STATUSES.map((status) => (
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

                {assignOpen && (
                  <AssignPeopleDialog
                    summary={t("common:assign_people.summary_tickets", {
                      count: selectedVisibleIds.length,
                    })}
                    managerCandidates={assignCandidates.MANAGER.map((p) => ({
                      id: p.id,
                      label: p.full_name || p.email,
                      sublabel: p.email,
                    }))}
                    workerCandidates={assignCandidates.WORKER.map((p) => ({
                      id: p.id,
                      label: p.full_name || p.email,
                      sublabel: p.email,
                    }))}
                    busy={assignBusy}
                    error={assignError}
                    onCancel={() => setAssignOpen(false)}
                    onConfirm={(managerIds, workerIds) =>
                      void runAssign(managerIds, workerIds)
                    }
                  />
                )}

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
                      {/* Sprint 159 §2 — one dialog, both roles, one
                          request. See `AssignPeopleDialog`. */}
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        data-testid="dashboard-bulk-assign-button"
                        onClick={() => void openAssign()}
                        disabled={bulkSubmitting || assignBusy}
                      >
                        {t("common:assign_people.title")}
                      </button>
                      {canBulkConfirm && (
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
                      )}
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
                              className="checkbox-input"
                              aria-label={t("bulk_confirm.select_all")}
                              data-testid="dashboard-bulk-select-all"
                              checked={allVisibleSelected}
                              onChange={toggleAllVisible}
                            />
                          </th>
                        )}
                        <th>{t("common:ticket_no")}</th>
                        <th>{t("common:subject")}</th>
                        {/* Chargeable work exists to TRACK the extra works that
                            went operational, so it shows the extra work and how
                            it got here. On the ordinary tickets page neither
                            column means anything, so it shows priority instead.
                            Two pages, two jobs -- which is the point of having
                            two pages. */}
                        {isChargeableWork ? (
                          <>
                            <th>{t("chargeable.col_extra_work")}</th>
                            <th>{t("chargeable.col_route")}</th>
                          </>
                        ) : (
                          <th>{t("common:priority")}</th>
                        )}
                        <th>{t("common:status")}</th>
                        <th className="td-sla">{t("common:sla")}</th>
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
                                className="checkbox-input"
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
                          {isChargeableWork ? (
                            <>
                              <td>
                                {ticket.extra_work_origin ? (
                                  <a
                                    href={`/extra-work/${ticket.extra_work_origin.extra_work_request_id}`}
                                    onClick={(event) => event.stopPropagation()}
                                    data-testid={`chargeable-ew-${ticket.id}`}
                                  >
                                    {ticket.extra_work_origin
                                      .extra_work_request_title ||
                                      `#${ticket.extra_work_origin.extra_work_request_id}`}
                                  </a>
                                ) : (
                                  <span className="muted-empty">—</span>
                                )}
                              </td>
                              <td>
                                {ticket.extra_work_origin?.origin ? (
                                  <span className="badge badge-muted">
                                    {ticket.extra_work_origin.origin ===
                                    "INSTANT"
                                      ? t("common:route_badge.instant")
                                      : t("common:route_badge.proposal")}
                                  </span>
                                ) : (
                                  <span className="muted-empty">—</span>
                                )}
                              </td>
                            </>
                          ) : (
                            <td>
                              <span className={priorityCellClass(ticket.priority)}>
                                <i />
                                {tPriority(ticket.priority)}
                              </span>
                            </td>
                          )}
                          <td>
                            {/* Sprint 182 §2 — the shared badge, so a
                                ticket's status is the same word and the
                                same colour here as on the Extra Work
                                list showing the same ticket. This cell
                                built its own class and looked up its own
                                label, which is how "Approved" here and
                                "Work approved" there became two
                                spellings of one fact. */}
                            <StatusBadge
                              status={{ kind: "ticket", value: ticket.status }}
                              variant="cell"
                              testId={`ticket-row-status-${ticket.id}`}
                            />
                          </td>
                          {/* Sprint 181 §4 — the SLA is a DIFFERENT
                              question from the workflow status beside
                              it, and adjacent columns of small coloured
                              pills read as one string. The rule marks
                              where "how is this job going" ends and
                              "are we late" begins. */}
                          <td className="td-sla">
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
                          {/* The mobile card is the same row; it renders
                              the same badge. Two renderers for one status
                              is how the desktop table and the phone card
                              start disagreeing. */}
                          <StatusBadge
                            status={{ kind: "ticket", value: ticket.status }}
                            variant="cell"
                            testId={`ticket-card-status-${ticket.id}`}
                          />
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
                      {TICKET_LIST_STATUSES.map((key) => {
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
          </>
        )}

      </div>
    </div>
  );
}
