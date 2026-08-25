import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Link,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
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
  TicketCategory,
} from "../api/types";
import {
  bulkAssignTickets,
  bulkConfirmTickets,
  listTicketAssignmentCandidates,
  listTicketCategories,
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
import { FinancialStrip } from "../components/extra-work/FinancialStrip";
import { SLABadge } from "../components/sla/SLABadge";
import { StatusTiles } from "../components/StatusTiles";
import { listScope } from "../lib/listScope";
import { PeriodFilter } from "../components/PeriodFilter";
import { periodParams, periodState } from "../lib/period";
import type { PeriodState } from "../lib/period";
import { useToast } from "../components/ToastProvider";
import { useEditMode } from "../lib/useEditMode";
import { currentMonth, splitOpenInvoiced, sumRows } from "../lib/billing";
import { ticketStatusLabelKey } from "../lib/enumLabels";
import {
  TICKET_ARCHIVE_STATUSES,
  TICKET_LIST_STATUSES,
  archivedTicketTotal,
  ticketArchiveStatusParam,
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

/**
 * W9 BUG 1 + BUG 4 — the dashboard had TWO answers to "what needs
 * doing", and the one with a person's name on it was always zero.
 *
 * "Waiting for you" counted `my_managed` — the tickets this person is
 * the named manager of. W8 chose it over `created_by` and it is the
 * better predicate, but for the two roles that mostly look at this
 * screen it is empty by construction: a SUPER_ADMIN and a COMPANY_ADMIN
 * hand work out, they are not the named manager on it. So all three
 * chips read 0 for ever, under a heading claiming they were the owner's
 * work, while the sidebar said B1 Amsterdam had 50 active. "Why are
 * these 0? What exactly determines these numbers? When do they change?"
 * — the honest answers were "you are on nothing", "an assignment nobody
 * makes to you" and "never".
 *
 * The block is gone rather than re-predicated, because the dashboard was
 * already carrying the right answer six inches above it. "Needs
 * attention" lists the work that will not move until somebody on the
 * provider side acts, and it is role-correct without a single per-role
 * branch: every count behind it runs through `scope_tickets_for`, so a
 * SUPER_ADMIN sees the company's, a COMPANY_ADMIN sees their company's
 * and a BUILDING_MANAGER sees their buildings'. That IS "waiting for
 * you", per role, and unlike the chips it is never structurally zero.
 *
 * What "waiting for you" means, then, by role and by row:
 *
 *   Reported done, needs your check   the cleaner has finished; until
 *                                     you check it the customer never
 *                                     sees it and it cannot be invoiced
 *   Unassigned                        nobody is on it, so nothing at
 *                                     all happens until you put someone
 *   Approval overdue                  the customer has gone quiet on
 *                                     finished work, and chasing them
 *                                     is the provider's move
 *
 * Two blocks became one. Nothing was added.
 */

/**
 * W9 BUG 2 — the dashboard row and the page it opens, from ONE table.
 *
 * The owner's requirement for a dashboard number, verbatim: clicking it
 * should make clear why he clicked, what he is looking at, which filter
 * is on, why these tickets belong there and what to do next. A selected
 * chip over an empty table answers none of those, and the answer cannot
 * live on the dashboard because by then he has left it.
 *
 * So each queue owns its link AND its destination heading, side by side
 * in one entry: the row he clicked and the page he lands on say the same
 * words because they read the same key. `matches` is the same predicate
 * spelled as a question, so a link and its heading cannot drift — the
 * defect this file has now produced three times, once per surface that
 * counted tickets its own way.
 *
 * This generalises the review queue, which has had exactly this
 * treatment since Sprint 158 and was the only queue to get it.
 */
/**
 * The two narrowings the ticket list turns on by ITSELF, switched off.
 *
 * Every count behind these queues is over all work in scope: the
 * unassigned query asks for `status=OPEN&assigned_to__isnull`, and
 * nothing in it says "ordinary tickets only, and hide finished
 * chargeable work". The list says both, by default, from an absent
 * parameter — so a link carrying only the status would land on strictly
 * fewer rows than the number that was clicked. An absent parameter is a
 * default, never an opinion, so a queue link states the whole predicate.
 * This is the same lesson W7 learned on the "My work" links; those links
 * are gone and the rule outlived them.
 */
const QUEUE_WIDE = "work=all&finished_extra_work=1";

/** The one place a queue's URL is written. Both the dashboard row and
 *  the page's own heading resolve through this key. */
function queueSearch(key: string): string {
  return TICKET_QUEUES.find((queue) => queue.key === key)?.search ?? "";
}

interface TicketQueueState {
  status: string;
  unassigned: boolean;
  stalled: boolean;
}

const TICKET_QUEUES: {
  key: string;
  search: string;
  matches: (state: TicketQueueState) => boolean;
  /** The queue whose next step is putting somebody on the work. */
  assigns?: boolean;
}[] = [
  {
    key: "review",
    search: `status=WAITING_MANAGER_REVIEW&${QUEUE_WIDE}`,
    matches: (s) =>
      s.status === "WAITING_MANAGER_REVIEW" && !s.unassigned && !s.stalled,
  },
  {
    key: "unassigned",
    search: `status=OPEN&unassigned=1&${QUEUE_WIDE}`,
    matches: (s) => s.status === "OPEN" && s.unassigned,
    assigns: true,
  },
  {
    key: "approval_overdue",
    search: `status=WAITING_CUSTOMER_APPROVAL&stalled=1&${QUEUE_WIDE}`,
    matches: (s) => s.status === "WAITING_CUSTOMER_APPROVAL" && s.stalled,
  },
];

/**
 * The parameters `/tickets/stats/` understands.
 *
 * Everything the LIST can send that is not in this set is invisible to
 * the count endpoint, so a page carrying one of those has tiles that
 * cannot describe their own rows. `statsAreBlind` below turns that into
 * an em dash instead of into a confident wrong number — the rule
 * `StatusTiles` was built around, applied to the four narrowings that
 * were quietly exempt from it.
 *
 * `status` / `status__in` / `page` are deliberately absent: the tiles ARE
 * the status axis (a tile counts one status, so the request must not
 * pre-filter by status) and `visibleTicketTotal` already subtracts
 * exactly the statuses `status__in` hides.
 */
const STATS_KNOWN_PARAMS = new Set([
  "page",
  "status",
  "status__in",
  "customer",
  "category",
  "category__isnull",
  "is_extra_work",
  "hide_finished_extra_work",
  // W-H §2/§3 — `/tickets/stats/` learned all three in the same commit
  // that added them to the list, which is the only way the tiles can go
  // on counting the rows they sit above. The Tickets page always sends
  // a period, so leaving these out would have made the tiles blind on
  // every load rather than in the rare case this set exists for.
  "archived",
  "date_from",
  "date_to",
]);

/**
 * W14 §2 — carry a status chip across the working-list / archive toggle
 * only when the pile being opened actually has that chip.
 *
 * Both directions drop something: the tickets page opens on `OPEN`,
 * which the archive cannot hold (`archive_not_finished`), and the
 * archive can be sitting on `CONVERTED_TO_EXTRA_WORK`, which the
 * working list deliberately does not show. Either survivor leaves an
 * empty list with no chip lit to explain why, so the filter is dropped
 * to "all" rather than kept as a narrowing nobody can see.
 */
function keepStatusFilter(
  current: TicketStatus | "",
  axis: readonly TicketStatus[],
): TicketStatus | "" {
  if (current === "") return "";
  return axis.includes(current) ? current : "";
}

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

/**
 * W7 DESIGN 3 — priority as TEXT in the table, not as a fourth pill.
 *
 * Every row carried a priority chip, a status chip, a deadline chip and
 * (on chargeable rows) an origin chip. Four pills across one line is the
 * "paragraph wearing chips" the owner is describing: the eye reads a
 * stripe of coloured lozenges and has to decode each one to find out
 * which of them is the thing it came for.
 *
 * A table column has a heading, so the pill was never carrying the
 * label — only the colour. The colour stays (urgent and high still read
 * red and amber at a glance); the lozenge goes. NORMAL, which is most
 * rows, drops to muted text, because "this one is ordinary" does not
 * deserve to be shouted on every line.
 *
 * The phone card keeps the pill: there is no column heading on a card,
 * so the surface is what says "this is the priority".
 */
function priorityTextClass(priority: string): string {
  return `cell-prio cell-prio-${priority.toLowerCase()}`;
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
  // The ROUTER's location, not the global one: this component is mounted
  // on two different chargeable routes and the back link has to name the
  // one the reader is actually on.
  const routeLocation = useLocation();
  const { me } = useAuth();
  const { push } = useToast();
  const { t } = useTranslation(["dashboard", "common"]);
  const userRole = me?.role ?? null;

  /* W17 §1 — A CHARGEABLE ROW OPENS THE TICKET, for every role.
   *
   * W15 sent chargeable clicks to the extra work because the ticket was
   * "the half of the job WITHOUT the money". That premise is gone: an
   * EW-origin ticket now carries the Extra Work card group (money,
   * actual hours, billing month — TicketDetailPage, W17 §2), so the
   * ticket is the ONE page for the job and every list row opens it —
   * this one exactly like the ordinary ticket list.
   *
   * The W15 STAFF exception dissolves with the redirect: STAFF land on
   * the ticket like everyone else, and the ticket page never fetches
   * the EW for them (`scope_extra_work_for` returns `.none()` — the
   * card group's mount is gated on the same `canAccessExtraWork`
   * predicate the nav uses). */
  /* The route this page is mounted on travels with the navigation —
   * `/tickets/chargeable` and `/admin/customers/<id>/chargeable` both
   * land on this component, so the ticket page's back link can name the
   * list the reader actually came from instead of guessing. Absent for
   * every non-chargeable row, which leaves that link exactly as it was. */
  const chargeableBackState = isChargeableWork
    ? { chargeableFrom: `${routeLocation.pathname}${routeLocation.search}` }
    : undefined;

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
  /** Sprint 185 E §1 — narrow the meldingen list to one KIND OF WORK.
   *  The filter is the whole point of the catalog: a taxonomy whose
   *  values never reach the filters is a dropdown. */
  // Sprint 187 §5 — `""` is no filter, a number is one category, and
  // "none" is the backend's `category__isnull` (offered by
  // `TicketFilter` since Sprint 185 with nothing in the UI emitting
  // it). A sentinel rather than a second piece of state: one value
  // decides the list params, the stats params and the "filters are
  // active" test, so the three cannot disagree.
  const [categoryFilter, setCategoryFilter] = useState<number | "" | "none">("");
  const [categories, setCategories] = useState<TicketCategory[]>([]);

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
  /* W-H §3/§4 — THE PERIOD, and THIS MONTH is what the page opens on.
   *
   * The owner: "I need to be able to see this month's jobs." The
   * default matters more than the filter: a Tickets page that opens on
   * every ticket ever raised is the pile his father was looking at.
   * This month is what somebody has to act on today; everything older
   * is one dropdown away and the archive is one toggle away. */
  const [period, setPeriod] = useState<PeriodState>(() =>
    periodState("this_month"),
  );
  /* W-H §2 — the working list or the archive. Never both: an archive
   * that still turns up among live work is a flag, not an archive. */
  const [showArchive, setShowArchive] = useState(false);
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
  /**
   * W7 BUG 2 — "Showing only your items" is a FILTER, so it turns on as
   * well as off.
   *
   * It used to be a fact-chip whose only control was a `<Link to="/tickets">`.
   * That is a one-way door twice over: nothing on the page could switch it
   * back on, and because the link threw the whole query string away it also
   * silently dropped whatever else was set — the type narrowing, the
   * deadline filter, the page. Now it is URL-backed state with a labelled
   * control in the filter bar, and toggling it rewrites one parameter and
   * leaves the rest alone.
   */
  const mineOnly = searchParams.get("mine") === "1";

  /**
   * W8 BUG 1 + BUG 3 — WHO IS ON THIS, as one control with three
   * answers.
   *
   * There were two dropdowns here: "Created by: anyone / only me" and
   * "Assigned to: anyone / nobody yet". The first is the whole of BUG 1
   * — for a SUPER_ADMIN "the ones I happened to open" is not a slice of
   * work anybody would ask for, and it was the predicate behind the
   * dashboard's "My work: 7" beside a page reading 78. The second
   * answered half of the real question.
   *
   * The real question is one question, so it is one control: who is on
   * this ticket — anyone, me, or nobody yet. "Me" is `my_managed`, the
   * union of the primary-manager FK and the responsible-manager M:N,
   * i.e. the tickets this person is actually on the hook for. Nothing on
   * this page filters by author any more.
   */
  const assignedFilter: "" | "me" | "nobody" = unassignedFilter
    ? "nobody"
    : mineOnly
      ? "me"
      : "";
  const setAssignedFilter = useCallback(
    (value: "" | "me" | "nobody") => {
      setPage(1);
      setSelectedIds(new Set<number>());
      setUnassignedFilter(value === "nobody");
      const nextSearch = new URLSearchParams(searchParams);
      if (value === "me") nextSearch.set("mine", "1");
      else nextSearch.delete("mine");
      setSearchParams(nextSearch, { replace: true });
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

  // W13 — the catalog behind the filter above. Loaded once on the
  // tickets page; non-fatal, and the filter is simply not rendered when
  // the company has no categories yet.
  //
  // Deliberately UNFILTERED: an archived category still has last
  // month's meldingen on it, and a filter that could not ask for them
  // would make those rows unfindable. The create forms narrow instead
  // (`is_active` + `available_at_intake`), which is the opposite job.
  //
  // W13-FIX §3 — the seven categories are seeded PER COMPANY, so an
  // unfiltered read returns seven per tenant. An operator who belongs to
  // exactly one company can only ever file against that company's
  // seven, so ask for those and the dropdown holds seven rather than
  // twenty-one.
  //
  // A SUPER_ADMIN spanning several companies is the one case where the
  // list genuinely IS cross-company -- narrowing it would hide other
  // tenants' meldingen from their own filter. That case keeps every row
  // and groups them by company below, so the repeated names read as
  // "Melden, at each of three companies" instead of the same word three
  // times with no way to tell which is which.
  const scopeCompanyId =
    me?.company_ids?.length === 1 ? me.company_ids[0] : undefined;

  useEffect(() => {
    if (!isTicketsPage) return;
    let cancelled = false;
    listTicketCategories(scopeCompanyId ? { company: scopeCompanyId } : undefined)
      .then((rows) => {
        if (!cancelled) setCategories(rows);
      })
      .catch(() => {
        /* non-fatal: the list still reads without its filter */
      });
    return () => {
      cancelled = true;
    };
  }, [isTicketsPage, scopeCompanyId]);

  /** The dropdown's rows grouped by owning company, in a stable order.
   *  One group means one tenant, and the render falls back to a flat
   *  list -- an <optgroup> around the only company on screen would be
   *  a label nobody needs. */
  const categoryOptionGroups = useMemo(() => {
    const byCompany = new Map<string, typeof categories>();
    for (const row of categories) {
      const key = row.company_name || String(row.company);
      const bucket = byCompany.get(key);
      if (bucket) bucket.push(row);
      else byCompany.set(key, [row]);
    }
    return [...byCompany.entries()]
      .map(([company, rows]) => ({ company, rows }))
      .sort((a, b) => a.company.localeCompare(b.company));
  }, [categories]);

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
    // W14 §2 — and the ROWS follow the same axis the chips do. In the
    // archive that is the archivable set: sending the working list's
    // `status__in` would hide an archived CONVERTED_TO_EXTRA_WORK
    // ticket from the only place it is meant to be findable.
    else if (isTicketsPage) {
      params.status__in = showArchive
        ? ticketArchiveStatusParam()
        : ticketListStatusParam();
    }
    if (priorityFilter) params.priority = priorityFilter;
    // Sprint 185 E §1 — server-side, so it survives pagination instead
    // of filtering one page while `count` describes another set.
    if (categoryFilter === "none") params.category__isnull = "true";
    else if (categoryFilter !== "") params.category = categoryFilter;
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
    /* W-H §2/§3 — both only on the Tickets page. The dashboard widgets
     * share this fetch helper and count totals; narrowing those to a
     * month would silently change what every KPI on the landing page
     * means. */
    if (isTicketsPage) {
      if (showArchive) params.archived = "true";
      Object.assign(params, periodParams(period));
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
      // W8 BUG 1 — "mine" is the work this person is RESPONSIBLE for
      // (`my_managed` = the primary-manager FK ∪ the responsible-manager
      // M:N), not the work they happened to create. `created_by` is what
      // produced the dashboard's 7-beside-78 and nothing asks for it now.
      if (mineOnly) params.my_managed = "true";
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
    categoryFilter,
    searchActive,
    slaFilter,
    unassignedFilter,
    stalledApprovalFilter,
    hideFinishedExtraWork,
    period,
    showArchive,
    searchParams,
    mineOnly,
    isTicketsPage,
    workTypeFilter,
  ]);

  /**
   * W7 BUG 1 — the SAME object, split in two: what the count endpoint can
   * be told, and what it cannot.
   *
   * Derived from `queryParams` rather than re-listed beside it, so a
   * filter added to the list in future is blind by default. That is the
   * safe direction to fail: a new filter that nobody remembered to teach
   * the stats endpoint makes the tiles say "I cannot know", which is
   * true, instead of leaving them confidently counting the whole company.
   */
  // A STRING, not an object: `useCallback` compares dependencies with
  // Object.is, so a freshly-built object would give `loadStats` a new
  // identity on every page turn and fire a redundant count request each
  // time. Sorted, so key order cannot manufacture a change either.
  const statsParamsKey = useMemo(() => {
    const known: Record<string, string> = {};
    for (const [key, value] of Object.entries(queryParams)) {
      // `status` is the tile axis and `page` is not a narrowing at all.
      if (key === "page" || key === "status") continue;
      if (STATS_KNOWN_PARAMS.has(key)) known[key] = String(value);
    }
    return JSON.stringify(
      Object.fromEntries(Object.entries(known).sort(([a], [b]) => (a < b ? -1 : 1))),
    );
  }, [queryParams]);

  /* W10 — see `lib/listScope`. Built from the SAME three inputs the
     query uses, never from the route name, so a page that changes its
     defaults cannot start lying about them. */
  const scope = useMemo(
    () =>
      listScope({
        work: workTypeFilter,
        status: statusFilter,
        hidesFinished: hideFinishedExtraWork,
      }),
    [workTypeFilter, statusFilter, hideFinishedExtraWork],
  );

  const statsAreBlind = useMemo(
    () =>
      Object.keys(queryParams).some(
        (key) => key !== "page" && !STATS_KNOWN_PARAMS.has(key),
      ),
    [queryParams],
  );

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
      // W7 BUG 1 — the tiles are asked for exactly the set the rows are
      // asked for, minus the status axis they themselves select on.
      //
      // The four hand-rolled `if` blocks that used to live here
      // (hide-finished, work type, customer, category) were four separate
      // memories of what the list sends, added one sprint at a time, each
      // one after the tiles had already been caught describing a
      // different set than the rows beneath them. `statsParams` is
      // derived from the list's own `queryParams`, so there is nothing
      // left to remember.
      const parsed = JSON.parse(statsParamsKey) as Record<string, string>;
      const response = await api.get<TicketStats>("/tickets/stats/", {
        params: Object.keys(parsed).length ? parsed : undefined,
      });
      setStats(response.data);
    } catch {
      // KPI cards fall back to "—" placeholders if the endpoint fails.
    }
  }, [statsParamsKey]);

  // M6.3 — "my work" summary counts (provider-management only). Each
  // count is the PaginatedResponse.count for a created_by=me query;
  // page_size:1 keeps the payload minimal (count is the full total).
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
    loadAttention();
    loadWidgets();
  }, [
    loadStats,
    loadStatsByBuilding,
    loadExtraWorkStats,
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

  /**
   * W7 DESIGN 3 — one control that puts the list back to showing
   * everything.
   *
   * It used to reset five of the eight narrowings and leave the other
   * three — "only mine", the approval-overdue preset and the
   * finished-extra-work hide — still on, with the list still short and
   * the button gone, which is the worst possible state to leave a
   * non-developer in. Everything that narrows this list is cleared here,
   * and the summary line above the table says in words what is still on
   * until you press it.
   */
  function clearFilters() {
    setPage(1);
    setStatusFilter("");
    setCategoryFilter("");
    setPriorityFilter("");
    setSearchInput("");
    setSearchActive("");
    setUnassignedFilter(false);
    setStalledApprovalFilter(false);
    setHideFinishedExtraWork(false);
    // The Chargeable work page IS this list pinned to chargeable work by
    // its route. "Show everything" clears the filters a person chose; it
    // does not turn the page into a different page.
    if (!isChargeableWork) setWorkTypeFilter("all");
    // Sprint 7 — clearing filters also leaves the bulk-confirm queue.
    setSelectedIds(new Set<number>());

    // ONE write to the query string.
    //
    // `setSlaFilter` and `setMineOnly` each build their next URL from
    // the same `searchParams` snapshot, so calling both from here would
    // apply the second and silently discard the first — the reader
    // would press "Show everything" and watch one filter survive.
    //
    // The three narrowings that are ON BY DEFAULT have to be written
    // POSITIVELY rather than deleted: an absent `status` means OPEN, an
    // absent `work` means ordinary tickets only, and an absent
    // `finished_extra_work` means finished work is hidden. Deleting them
    // would put the page back exactly where it started, and a refresh
    // would undo the click. This is the same lesson as the "My work"
    // link at the top of this file: a URL has to state the whole
    // predicate, because an absent parameter is a default and not an
    // opinion.
    const next = new URLSearchParams(searchParams);
    for (const key of ["sla", "mine", "stalled", "unassigned", "type", "exclude_type"]) {
      next.delete(key);
    }
    next.set("status", "ALL");
    if (!isChargeableWork) next.set("work", "all");
    next.set("finished_extra_work", "1");
    setSearchParams(next, { replace: true });
  }

  // Narrowings the reader chose. `hideFinishedExtraWork` and the
  // work-type default are ON when the page opens, so they are described
  // in the summary line but do not by themselves claim the list is
  // filtered — otherwise "Show everything" would be lit on arrival and
  // pressing it would change what the page means by default.
  const hasActiveFilters = Boolean(
    statusFilter || priorityFilter || categoryFilter !== "" ||
      searchActive || slaFilter ||
      unassignedFilter || stalledApprovalFilter || mineOnly,
  );

  // W8 BUG 3 — the narrowing SENTENCES are gone with the line that
  // rendered them; every control that sets one now says what it does.


  /**
   * W7 DESIGN 7 — the manager-review queue explains itself on arrival.
   *
   * "Manager review queue" names the queue after the role that owns it,
   * which tells the reader nothing about what is in it or why it is
   * costing them anything. What is in it: work a cleaner has reported
   * finished. Why it matters: until somebody checks it the customer
   * never sees it and it cannot be invoiced.
   */
  /**
   * W9 BUG 2 — which named queue this page is currently showing, if any.
   *
   * Read from the page's own filter state rather than from the URL, so a
   * queue reached by working the filters by hand explains itself exactly
   * as one reached from the dashboard. The heading, the reason and the
   * empty message all key off this, which is why a link and its
   * destination cannot say different things.
   */
  const activeQueue = useMemo(
    () =>
      TICKET_QUEUES.find((queue) =>
        queue.matches({
          status: statusFilter,
          unassigned: unassignedFilter,
          stalled: stalledApprovalFilter,
        }),
      ) ?? null,
    [statusFilter, unassignedFilter, stalledApprovalFilter],
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
          {/* W-NAV1.5 — no New ticket button on Chargeable work.
              A chargeable ticket is not something you create here: it
              is SPAWNED when a customer approves an Extra Work quote.
              The button offered a blank melding form, which produces a
              ticket that would never appear on this list — an action
              whose result vanishes. The Tickets page keeps it. */}
          {!isChargeableWork && (
            <Link className="btn btn-primary btn-sm" to="/tickets/new">
              <Plus size={14} strokeWidth={2.5} />
              {t("new_ticket")}
            </Link>
          )}
          {/* W-UX1 §1 — One-off work gets its own create button back.
              The note above explains why "New ticket" does NOT belong
              here (a chargeable ticket is SPAWNED, never typed), and
              that argument leaves this page with no way to start the
              thing it lists. "New extra work" is that way.

              Provider management only. `canAccessExtraWork` is the
              WRONG gate here — it admits CUSTOMER_USER, who reaches
              extra work through the quote-request page and would land
              on a provider create form. STAFF are excluded by both. */}
          {isChargeableWork && isProviderManagementRole(userRole) && (
            <Link
              className="btn btn-primary btn-sm"
              to="/extra-work/new"
              data-testid="chargeable-new-extra-work"
            >
              <Plus size={14} strokeWidth={2.5} />
              {t("new_extra_work")}
            </Link>
          )}
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
                      to={`/tickets?${queueSearch("review")}`}
                      className="attn-row"
                      data-testid="attention-review"
                    >
                      <span className="attn-row-label">
                        {t("queue.review.title")}
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
                      to={`/tickets?${queueSearch("unassigned")}`}
                      className="attn-row"
                      data-testid="attention-unassigned"
                    >
                      <span className="attn-row-label">
                        {t("queue.unassigned.title")}
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
                      to={`/tickets?${queueSearch("approval_overdue")}`}
                      className="attn-row"
                      data-testid="attention-approval-overdue"
                    >
                      <span className="attn-row-label">
                        {t("queue.approval_overdue.title", {
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

            {/* #109 Part G — bottom density band (management view only):
                a Facturatie mini per-building panel + a compact
                Laatste-tickets/extra-werk list. Both reuse
                already-loaded data / the existing parallel loaders. */}
            <section
              className="dashboard-bottom-band"
              data-testid="dashboard-bottom-band"
            >
              {/* W-HK1 §3 — the billing panel sizes to ITS OWN content.
                  `.dashboard-bottom-band` sets `align-items: stretch` so
                  the two cards end on one line (W7 DESIGN 4); with a
                  handful of buildings on the left and a long activity
                  list on the right, that rule was spending the bottom
                  two-thirds of this card on nothing. `align-self: start`
                  opts THIS card out and leaves the band rule — and the
                  card beside it — untouched. Content is unchanged. */}
              <div
                className="card attention-card dashboard-billing-card"
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
                {t("queue.review.title")}
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
                {t("queue.unassigned.title")}
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
              to={`/tickets?${queueSearch("unassigned")}`}
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

        {/* W1-C §2.4 — the money strip, on the Chargeable work page.

            Only there, and not on the ordinary Tickets page: the
            figures are Extra Work money, and a page about meldingen has
            no money on it to explain. `isChargeableWork` rather than
            `isTicketsPage` is the whole difference. Provider management
            only — the component returns null for anybody else, and the
            endpoint refuses them as well.

            W-NAV1.2b — the THREE execution figures, not four. Work has
            started on everything this page lists, so "Quoted, not yet
            started" is about rows that are NOT here; it belongs to the
            Extra Work Quote list and renders there. Selection only —
            none of the three is computed differently. */}
        {isChargeableWork && (
          <FinancialStrip variant="execution" customerId={customerId} />
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
        {/* W7 DESIGN 3 — the work-type control moved into the filter bar.

            It was a lone pressed/unpressed button floating in its own
            strip above the tiles, which reads as a chip stating a fact
            rather than as the filter it is. It is a labelled dropdown
            beside the other filters now: same parameter, same URL, same
            testids, but a person looking for "how do I change what this
            list shows" finds it where every other answer to that
            question already lives. */}

        {/* W7 BUG 1 — the counts describe the rows beneath them, or they
            say they cannot know. There is no third option, and there is
            certainly no option where they describe a different set in the
            same type size as the number the reader came here for.

            `statsAreBlind` is true when the list carries a narrowing the
            count endpoint has never been taught — "only mine" is the one
            that produced the owner's 21 above two rows, but a search
            term, a priority and the two attention-card presets were all
            equally invisible to it. When it is true the per-status tiles
            show no number at all, and the "All" tile falls back to the
            list's OWN `count`, which is the one number on the page that
            is exact by construction: it is what the server said when it
            returned these rows. That fallback only holds with no status
            chosen, because with one chosen `count` describes that status
            rather than the whole list. */}
        {/* W8 BUG 2 — the counts follow the filter, or the row does
            not claim to count.

            The old third option was the worst of the two: "All" kept a
            number (from the list's own `count`, a different source) and
            the eight status tiles beside it each showed an em dash, with
            a paragraph in the side column apologising for it. Eight
            dashes read as eight empty buckets, and no wording rescues
            that — a reader who has to be told what a control means is
            looking at a broken control.

            So when `/tickets/stats/` cannot describe these rows, the
            whole row drops its numbers and goes on being what it also
            always was: the status filter. Nothing to explain. */}
        {/* W-H §2/§3 — the period, and which pile you are looking at.
            Above the status tiles because they narrow WHICH ROWS the
            tiles count, and the tiles already follow this filter (the
            stats call carries `archived` and the period the same way
            the list does).

            Two controls, no prose. "Working list / Archive" is a pair
            of states, not a verb, so it reads as a place you are rather
            than a thing you do. */}
        <div className="list-scope-row" data-testid="tickets-scope-row">
          <PeriodFilter
            idPrefix="tickets"
            value={period}
            onChange={(next) => {
              setPeriod(next);
              setPage(1);
            }}
          />
          <div className="composer-toggle" role="tablist" aria-label={t("period.label")}>
            <button
              type="button"
              role="tab"
              aria-selected={!showArchive}
              className={`composer-toggle-btn ${!showArchive ? "active" : ""}`}
              onClick={() => {
                setShowArchive(false);
                setPage(1);
                // W14 §2 — the two piles do not share a status axis, so
                // a chip selected in one must not survive into the
                // other. Carrying `CLOSED` back into the working list is
                // harmless; carrying `OPEN` into the archive is not — it
                // narrows the rows to a status the archive cannot hold
                // and leaves an empty list with no chip lit to explain
                // it. Cleared in BOTH directions so the rule is one rule.
                setStatusFilter((current) =>
                  keepStatusFilter(current, TICKET_LIST_STATUSES),
                );
              }}
              data-testid="tickets-show-working"
            >
              {t("archive.show_working")}
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={showArchive}
              className={`composer-toggle-btn ${showArchive ? "active" : ""}`}
              onClick={() => {
                setShowArchive(true);
                setPage(1);
                // See the sibling above. The tickets page opens on
                // `OPEN`, so without this every first press of Archive
                // showed an empty archive.
                setStatusFilter((current) =>
                  keepStatusFilter(current, TICKET_ARCHIVE_STATUSES),
                );
              }}
              data-testid="tickets-show-archive"
            >
              {t("archive.show")}
            </button>
          </div>
        </div>
        {/* W14 §2 — THE CHIPS BELONG TO THE PILE THAT IS OPEN.
            The archive gate (`filters.apply_archived`) was clean and the
            counts followed it, but the row above the list went on
            drawing the WORKING LIST's ten statuses over it. The owner:
            "why am I seeing normal ticket status chips while the archive
            chip is selected?" — and he was right to ask: the server
            refuses to archive anything that is not terminal
            (`archive_not_finished`), so seven of those ten chips could
            only ever read 0. Measured on crmtest with `?archived=true`:
            `by_status` came back `{}` for all ten.
            One axis, chosen by which pile is open. */}
        <StatusTiles
          tiles={(showArchive
            ? TICKET_ARCHIVE_STATUSES
            : TICKET_LIST_STATUSES
          ).map((value) => ({
            value,
            label: tStatus(value),
            count: stats ? (stats.by_status[value] ?? 0) : -1,
          }))}
          active={statusFilter}
          onChange={(value: string) => {
            setStatusFilter(value as TicketStatus | "");
            setPage(1);
            setSelectedIds(new Set<number>());
          }}
          totalCount={
            showArchive ? archivedTicketTotal(stats) : visibleTicketTotal(stats)
          }
          showCounts={!statsAreBlind}
          testIdPrefix="tickets-status"
        />

          <section
            className="work-layout"
            data-testid="dashboard-tickets-section"
          >
            <div className="dash-main">
              <div className="card" style={{ overflow: "hidden" }}>
                {/* W7 DESIGN 3 + DESIGN 7 — the head says what this list
                    is, and nothing else. The five fact-chips that used to
                    stack here (only yours / only unassigned / awaiting
                    approval 14+ days / finished extra work hidden /
                    finished extra work shown) are one sentence below the
                    filters, and each of them now has a labelled control
                    among the filters instead of a pill with an × on it. */}
                {/* W9 BUG 2 — what you are looking at, why these
                    tickets are here, and the next step, in the words of
                    the dashboard row you clicked to get here. */}
                <div className="section-head">
                  <div>
                    <div
                      className="section-head-title"
                      data-testid="tickets-queue-title"
                    >
                      {activeQueue
                        ? t(`queue.${activeQueue.key}.title`)
                        : t("section_recent_title")}
                    </div>
                    {/* W10 — WHY THESE ROWS. Tickets, Chargeable work
                        and this page's own defaults are three filters
                        over one set of records, and the line here used
                        to read "Everything you are allowed to see" on a
                        page showing open ordinary tickets with
                        chargeable work excluded. Derived from the same
                        state the query is built from, so it cannot
                        describe a different list than the one below.
                        A dashboard queue keeps its own wording: it is
                        more specific than anything derivable here. */}
                    <div
                      className="section-head-sub"
                      data-testid="tickets-scope-sentence"
                    >
                      {activeQueue ? (
                        t(`queue.${activeQueue.key}.why`)
                      ) : (
                        <>
                          {t(scope.key)}
                          {scope.hiddenKey ? ` ${t(scope.hiddenKey)}` : ""}
                        </>
                      )}
                    </div>
                  </div>
                  {isProviderManagementRole(userRole) &&
                    (activeQueue?.assigns && !edit.editMode ? (
                      /* W9 — BRING THE ACTION TO WHERE THE USER IS. The
                         next step in the unassigned queue is putting
                         somebody on the work, and it was behind a button
                         called "Edit". Same control, named for the job
                         it does here. The house rule still holds: the
                         screen edits nothing until this is pressed. */
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={edit.start}
                        disabled={bulkSubmitting || assignBusy}
                        data-testid="tickets-queue-action"
                      >
                        {t("queue.unassigned.action")}
                      </button>
                    ) : (
                      <EditModeToggle
                        editMode={edit.editMode}
                        onToggle={edit.toggleMode}
                        disabled={bulkSubmitting || assignBusy}
                        testId="dashboard-tickets-edit-toggle"
                      />
                    ))}
                </div>

                <form className="filter-bar" onSubmit={handleSearchSubmit}>
                  {/* Sprint 185 E §1 — WHICH KIND OF WORK. Rendered only
                      when the company has a catalog: an empty dropdown is
                      a control that looks broken, and the Catalogs tab's
                      empty state is what explains where it comes from
                      (the Sprint 178 rule for the building-type filter,
                      restated here rather than re-decided). */}
                  {categories.length > 0 && (
                    <div className="filter-field">
                      <span className="filter-label">
                        {t("common:ticket_categories.field_label")}
                      </span>
                      <select
                        className="filter-control"
                        value={String(categoryFilter)}
                        data-testid="tickets-filter-category"
                        onChange={(event) => {
                          const value = event.target.value;
                          setPage(1);
                          setSelectedIds(new Set<number>());
                          setCategoryFilter(
                            value === ""
                              ? ""
                              : value === "none"
                                ? "none"
                                : Number(value),
                          );
                        }}
                      >
                        <option value="">
                          {t("common:ticket_categories.filter_all")}
                        </option>
                        {/* Sprint 187 §5 — the backend has been able to
                            list "not yet categorised" since the catalog
                            shipped (`category__isnull`); the dropdown
                            offered no way to ask for it, so the one
                            state an operator most needs to work through
                            was the one they could only find by reading
                            every row. */}
                        <option value="none">
                          {t("common:ticket_categories.filter_uncategorised")}
                        </option>
                        {categoryOptionGroups.length > 1
                          ? categoryOptionGroups.map((group) => (
                              <optgroup key={group.company} label={group.company}>
                                {group.rows.map((row) => (
                                  <option key={row.id} value={row.id}>
                                    {row.label}
                                  </option>
                                ))}
                              </optgroup>
                            ))
                          : categories.map((row) => (
                              <option key={row.id} value={row.id}>
                                {row.label}
                              </option>
                            ))}
                      </select>
                    </div>
                  )}
                  {/* W8 BUG 3 — the Status dropdown is gone. The tile
                      row above the list is the status control: it
                      already selects, already clears, and already shows
                      which status is on. Two controls for one question
                      is how a person ends up unable to say what either
                      of them does. */}
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
                  {/* W8 BUG 1 + BUG 3 — WHO IS ON THIS, once.

                      Was two dropdowns: "Created by: anyone / only me"
                      and "Assigned to: anyone / nobody yet". Author is
                      not a slice of work anybody asks for — it is the
                      predicate that made the dashboard say 7 over a page
                      of 78 — and the other half of the real question was
                      already here. One control, three answers. */}
                  <div className="filter-field">
                    <span className="filter-label">
                      {t("filters.assigned")}
                    </span>
                    <select
                      className="filter-control"
                      value={assignedFilter}
                      data-testid="tickets-filter-assigned"
                      onChange={(event) =>
                        setAssignedFilter(
                          event.target.value as "" | "me" | "nobody",
                        )
                      }
                    >
                      <option value="">{t("filters.assigned_anyone")}</option>
                      <option value="me">{t("filters.assigned_me")}</option>
                      <option value="nobody">
                        {t("filters.assigned_nobody")}
                      </option>
                    </select>
                  </div>
                  {/* W8 BUG 3 — WHAT IS ON THIS LIST, once.

                      Was two dropdowns sitting side by side, both
                      answering it and neither saying so: "Show: tickets
                      only / tickets and chargeable work" and "Finished
                      chargeable work: hidden / shown". Three of the four
                      combinations are one sentence each, and the fourth
                      (tickets only, finished chargeable shown) narrows
                      chargeable work out and then un-hides it — a state
                      with no meaning. One control, three answers, in the
                      order that widens the list. The Chargeable work
                      page pins its own work type, so it offers the
                      finished/hidden choice alone. */}
                  <div className="filter-field">
                    <span className="filter-label">
                      {t("work_scope.label")}
                    </span>
                    <select
                      className="filter-control"
                      value={
                        isChargeableWork
                          ? hideFinishedExtraWork
                            ? "tickets"
                            : "everything"
                          : workTypeFilter === "tickets"
                            ? "tickets"
                            : hideFinishedExtraWork
                              ? "with_chargeable"
                              : "everything"
                      }
                      data-testid="tickets-work-scope"
                      onChange={(event) => {
                        const value = event.target.value;
                        setPage(1);
                        setSelectedIds(new Set<number>());
                        setHideFinishedExtraWork(value !== "everything");
                        if (!isChargeableWork) {
                          const next = new URLSearchParams(searchParams);
                          if (value === "tickets") {
                            setWorkTypeFilter("tickets");
                            next.delete("work");
                          } else {
                            setWorkTypeFilter("all");
                            next.set("work", "all");
                          }
                          setSearchParams(next, { replace: true });
                        }
                      }}
                    >
                      {!isChargeableWork && (
                        <option value="tickets">
                          {t("work_scope.tickets_only")}
                        </option>
                      )}
                      {!isChargeableWork && (
                        <option value="with_chargeable">
                          {t("work_scope.with_chargeable")}
                        </option>
                      )}
                      {isChargeableWork && (
                        <option value="tickets">
                          {t("work_scope.unfinished_only")}
                        </option>
                      )}
                      <option value="everything">
                        {t("work_scope.everything")}
                      </option>
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
                    {/* W8 BUG 3 — "Reported done, needs a check" is
                        gone. It set one status, which is what the tile
                        of that name above the list does in one click,
                        and a button that duplicates a filter is the
                        third thing on this bar a person could not name.
                        The tile keeps the wording. */}
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

                {/* W7 DESIGN 3 — the facts, as one line of text.
                    A count the reader can trust, then what is being held
                    back and why, then the single control that undoes all
                    of it. No pills: every one of these is a statement,
                    and the things that FILTER are the dropdowns above. */}
                {/* W8 BUG 3 — the count, and nothing else.

                    This line used to carry up to five sentences naming
                    the narrowings that were on ("only the ones you
                    created", "chargeable work left out", ...) plus a
                    second reset button beside the Clear button six
                    inches above it. Every one of those sentences existed
                    because the control that set it did not say what it
                    did; each of those controls now does, so there is
                    nothing left for the sentence to explain. */}
                <p
                  className="list-summary"
                  data-testid="tickets-list-summary"
                  aria-live="polite"
                >
                  <span className="list-summary-count">
                    {loading
                      ? t("loading")
                      : t("filter_summary.count", {
                          visible: tickets.length,
                          count,
                        })}
                  </span>
                </p>

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
                  {/* Sprint 188 — Chargeable work carries two columns the
                      tickets page does not (Extra work + Route, in place of
                      its single Priority), so at the same cell padding the
                      table was wider than its track and the list scrolled
                      sideways. `data-table-dense` is the repo's existing
                      density modifier (Sprint 153 §3.6): same layout, same
                      columns, tighter cells. */}
                  <table
                    className={`data-table${
                      isChargeableWork
                        ? " data-table-dense data-table-fit"
                        : ""
                    }`}
                  >
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
                          <>
                            {/* W13 — "you have to show all of it: is it
                                a complaint, a request, a compliment?"
                                The list could FILTER by category since
                                Sprint 185 and never printed it, so the
                                answer was reachable only by opening
                                every row. Not on Chargeable work, which
                                spends these two columns on the extra
                                work a row came from. */}
                            <th>{t("common:ticket_categories.field_label")}</th>
                            <th>{t("common:priority")}</th>
                          </>
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
                          /* W14 §3 — ONE CLICK, ONE HISTORY ENTRY.
                             The row is clickable AND contains `<Link>`s
                             to the same ticket. Clicking a link
                             navigated, the click then bubbled to here,
                             and this navigated again. Instrumenting
                             `history.pushState` on crmtest, one click
                             on ticket 343 logged `PUSH /tickets/343`
                             TWICE and `history.state.idx` went 1 -> 3 —
                             so one press of the browser's Back landed
                             back on the ticket it was pressed from, and
                             only for the cells that happen to be links.
                             The anchor is left to be an anchor
                             (open-in-new-tab, middle click, the status
                             bar showing where it goes); the row handles
                             only the cells that are not one. */
                          onClick={(event) => {
                            if (
                              (event.target as HTMLElement).closest("a,button")
                            ) {
                              return;
                            }
                            navigate(`/tickets/${ticket.id}`, {
                              state: chargeableBackState,
                            });
                          }}
                          onKeyDown={(event) => {
                            if (event.key === "Enter" || event.key === " ") {
                              event.preventDefault();
                              navigate(`/tickets/${ticket.id}`, {
                                state: chargeableBackState,
                              });
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
                              state={chargeableBackState}
                              className="td-id"
                            >
                              {ticket.ticket_no}
                            </Link>
                            {/* W15 §1 — NOT on Chargeable work, and for
                                two reasons that point the same way.

                                It SAYS NOTHING there: every row on that
                                page is chargeable work by construction
                                (`?is_extra_work=true` is pinned by the
                                route), so a chip repeating it on all of
                                them is a label with no contrast.

                                And it is now a SECOND DOOR to where the
                                row already goes — the exact duplication
                                the owner's rule 3 forbids, and the shape
                                that logged `PUSH /tickets/343` twice in
                                W14 §3. On the ordinary ticket list, where
                                the row opens the ticket and these rows
                                are the minority, it stays: there it is
                                the only way through to the extra work and
                                it is genuinely telling you something. */}
                            {!isChargeableWork && ticket.extra_work_origin && (
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
                            {/* W15 §1 — the subject goes WHERE THE ROW
                                GOES. An anchor inside a clickable row
                                that lands somewhere else is the row
                                lying about itself: the pointer says one
                                destination and the rest of the row does
                                another. The ticket number beside it is
                                the labelled door to the ticket. */}
                            <Link
                              to={`/tickets/${ticket.id}`}
                              state={chargeableBackState}
                            >
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
                          {!isChargeableWork && (
                            <td>
              {/* W13-FIX §4 — REVERTED to the row's own chip.
                                  The owner: "who told you to change them,
                                  revert them, they look terrible."

                                  W13 gave this one cell an outlined pill
                                  with the catalog colour painted onto its
                                  border AND its text, which no other tag
                                  in this table does. It is `.cell-tag`
                                  again, exactly like the cells beside it,
                                  and the category's colour rides on the
                                  `<i>` dot that `.cell-tag` has always
                                  used for precisely this -- so nothing is
                                  restyled and no colour is lost. */}
                              {ticket.category_name ? (
                                <span
                                  className="cell-tag"
                                  data-testid="ticket-row-category"
                                >
                                  <i
                                    style={
                                      ticket.category_color
                                        ? { background: ticket.category_color }
                                        : undefined
                                    }
                                  />
                                  {ticket.category_name}
                                </span>
                              ) : (
                                /* Shown, not hidden. "Not classified
                                   yet" is the state an operator works
                                   through, and a blank cell reads as a
                                   rendering fault rather than a job. */
                                <span
                                  className="muted-empty"
                                  data-testid="ticket-row-category-none"
                                >
                                  {t("common:ticket_categories.none")}
                                </span>
                              )}
                            </td>
                          )}
                          {isChargeableWork ? (
                            <>
                              {/* W15 §1 (surviving W17 §1) — the extra
                                  work is NAMED here, not linked, and
                                  both halves of that are deliberate.

                                  The row opens the ticket, which now
                                  CARRIES the extra work's money and
                                  keeps its own door to the EW page — so
                                  an anchor in this cell is a duplicate
                                  route to what the row already reaches
                                  — and this table has already been bitten
                                  by that exact shape (W14 §3: a link
                                  inside a clickable row logged
                                  `PUSH /tickets/343` twice, so one press
                                  of Back went nowhere).

                                  AND IT WAS A DOOR TO A 404 FOR STAFF.
                                  Measured on the dev API: STAFF are
                                  served all 5 chargeable rows, each
                                  carrying `extra_work_origin`, while
                                  `GET /api/extra-work/6/` answers them
                                  `404 {"detail":"No ExtraWorkRequest
                                  matches the given query."}` — because
                                  `scope_extra_work_for` returns `.none()`
                                  for STAFF. Rule 6 says a role that
                                  cannot use it does not see it; a link
                                  that always breaks is worse than no
                                  link. The title stays, because "which
                                  extra work did this come from" is a
                                  fact they still need, and it is already
                                  in the payload they already receive. */}
                              <td>
                                {ticket.extra_work_origin ? (
                                  <span
                                    data-testid={`chargeable-ew-${ticket.id}`}
                                  >
                                    {ticket.extra_work_origin
                                      .extra_work_request_title ||
                                      `#${ticket.extra_work_origin.extra_work_request_id}`}
                                  </span>
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
                              <span className={priorityTextClass(ticket.priority)}>
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
                          {/* W7 BUG 3 + DESIGN 1/2 — ONE sentence about
                              the deadline, as text. It reads "On time —
                              6h left", "Almost late — 1h left", "Late by
                              1h 37m", "Waiting on customer", "Finished"
                              or "No deadline"; the last of those is the
                              row that used to render an empty cell. */}
                          <td className="td-sla">
                            <SLABadge
                              state={ticket.sla_display_state}
                              remainingSeconds={
                                ticket.sla_remaining_business_seconds
                              }
                              variant="plain"
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
                      {/* W15 §1 — same rule as the table above, and this
                          mirror is "kept in DOM regardless of viewport",
                          so leaving it unguarded would put the duplicate
                          door back on the page invisibly. */}
                      {!isChargeableWork && ticket.extra_work_origin && (
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
                    {/* W9 BUG 2 — an empty queue is GOOD NEWS and says
                        so in its own words. "No tickets match these
                        filters" is what a filter accident looks like,
                        and it read identically to one. */}
                    <div className="empty-title">
                      {activeQueue
                        ? t(`queue.${activeQueue.key}.empty`)
                        : hasActiveFilters
                          ? t("empty_no_match_title")
                          : t("empty_no_tickets_title")}
                    </div>
                    <p className="empty-sub">
                      {activeQueue
                        ? t("queue.empty_sub")
                        : hasActiveFilters
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

              {/* W8 BUG 2 + BUG 3 — the "Status breakdown" card is
                  gone. It listed the same eight numbers from the same
                  `/tickets/stats/` response as the tile row directly
                  above the list, so the page counted its statuses twice
                  and had two places to be wrong; and it was the only
                  home of the paragraph that apologised for the em
                  dashes. The tiles are the status count and the status
                  filter, and there is one of them. */}
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
