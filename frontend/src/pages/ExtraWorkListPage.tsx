// Sprint 26C — Extra Work list page.
// Sprint 28 Batch 6 — translated through the `extra_work` i18n namespace.
// Sprint 28 Batch 15.3 — rebuilt with KPI strip, filter bar, StatusBadge,
//   formatMoney/formatDate, ClickableRow, mobile card list, EmptyState.
//   Functional contract is unchanged; only the presentation layer moves.
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  CheckCircle2,
  Clock,
  Inbox,
  PlusCircle,
  Search,
  Sparkles,
  Wallet,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { listAllCustomers, listCustomerBuildings } from "../api/admin";
import { listLabels } from "../api/customerLabels";
import {
  bulkAssignExtraWork,
  bulkSetExtraWorkDates,
  listAllExtraWork,
  listExtraWorkAssignmentCandidates,
  listExtraWorkCategoryOptions,
} from "../api/extraWork";
import type { ExtraWorkCategoryOptions } from "../api/extraWork";
import type {
  AssignmentCandidate,
  CustomerAdmin,
  ExtraWorkAssignmentRole,
  CustomerBuildingMembership,
  CustomerLabel,
  ExtraWorkBilledTo,
  ExtraWorkCategory,
  ExtraWorkRequestIntent,
  ExtraWorkRequestList,
  ExtraWorkStatus,
} from "../api/types";
import { getApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { isProviderManagementRole } from "../auth/permissions";
import { ChoiceDialog } from "../components/ChoiceDialog";
import { StatusTiles } from "../components/StatusTiles";
import { TrackTabs } from "../components/extra-work/TrackTabs";
import type { ExtraWorkTrack } from "../components/extra-work/TrackTabs";
import { EditModeToggle } from "../components/EditModeToggle";
import { MultiSelectToolbar } from "../components/MultiSelectToolbar";
import { AssignPeopleDialog } from "../components/AssignPeopleDialog";
import { useEditMode } from "../lib/useEditMode";
import { ClickableRow } from "../components/ClickableRow";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { RouteBadge } from "../components/RouteBadge";
import { StatusBadge } from "../components/StatusBadge";
import { rowAmounts } from "../lib/billing";
import { formatDate, formatMoney } from "../lib/intl";
import { extraWorkCategoryName } from "../lib/extraWorkCategoryLabel";

const CATEGORY_I18N_KEY: Record<ExtraWorkCategory, string> = {
  DEEP_CLEANING: "category.deep_cleaning",
  WINDOW_CLEANING: "category.window_cleaning",
  FLOOR_MAINTENANCE: "category.floor_maintenance",
  SANITARY_SERVICE: "category.sanitary_service",
  WASTE_REMOVAL: "category.waste_removal",
  FURNITURE_MOVING: "category.furniture_moving",
  EVENT_CLEANING: "category.event_cleaning",
  EMERGENCY_CLEANING: "category.emergency_cleaning",
  OTHER: "category.other",
};

const STATUS_I18N_KEY: Record<ExtraWorkStatus, string> = {
  REQUESTED: "status.requested",
  UNDER_REVIEW: "status.under_review",
  PRICING_PROPOSED: "status.pricing_proposed",
  CUSTOMER_APPROVED: "status.customer_approved",
  // Sprint 29 Batch 29.8 — operational segment.
  IN_PROGRESS: "status.in_progress",
  COMPLETED: "status.completed",
  CUSTOMER_REJECTED: "status.customer_rejected",
  CANCELLED: "status.cancelled",
};

/** Sprint 180 §3 — the two billing targets. A `Record` over the union
 *  rather than a second array literal: adding a third value to
 *  `ExtraWorkBilledTo` then fails the compiler here instead of rendering
 *  a blank cell (CLAUDE.md — a hardcoded array defeats exhaustiveness
 *  checking, which is how Sprint 126's headerless column shipped). */
const BILLED_TO_I18N_KEY: Record<ExtraWorkBilledTo, string> = {
  BUILDING: "billed_to.building",
  CUSTOMER: "billed_to.customer",
};

const STATUS_FILTER_OPTIONS: ReadonlyArray<ExtraWorkStatus> = [
  "REQUESTED",
  "UNDER_REVIEW",
  "PRICING_PROPOSED",
  "CUSTOMER_APPROVED",
  // Sprint 29 Batch 29.8 — surface the operational segment in the
  // list filter so operators can narrow to in-progress / completed
  // execution rows.
  "IN_PROGRESS",
  "COMPLETED",
  "CUSTOMER_REJECTED",
  "CANCELLED",
];

type StatusFilter = ExtraWorkStatus | "ALL";

/** Sprint 180 §1(b) — a CUSTOMER_APPROVED request with zero operational
 *  tickets. It stays on the Quote & price track (operationally nothing
 *  has started, which is what the track means) but it is NOT normal: the
 *  spawn is synchronous with approval, so zero tickets means the spawn
 *  FAILED. A recovery button already exists on the detail page
 *  (POST /api/extra-work/<id>/spawn/); silence here is how that work
 *  gets lost. */
function isSpawnAnomaly(row: ExtraWorkRequestList): boolean {
  return row.status === "CUSTOMER_APPROVED" && !row.has_operational_ticket;
}
// Sprint 143 §6 — the filter is a catalog category NAME now, not an
// `ExtraWorkCategory` enum member. "" = no filter. The enum still drives
// the table's own "Categorie" COLUMN (a different field on the request,
// left alone this sprint — see `## NEXT`), which is exactly why the two
// were confusable and why this filter had to stop using it.
type CategoryFilter = string;

interface ExtraWorkKpis {
  open: number; // REQUESTED + UNDER_REVIEW
  awaiting: number; // PRICING_PROPOSED
  approved: number; // CUSTOMER_APPROVED
  totalValue: string; // decimal-string sum of earned amounts (excludes CANCELLED)
}

/** Sprint 176 §3 — set the deadline and/or the planned end on a selection.
 *
 *  The whole point of this dialog is what it does NOT send. Every field
 *  starts blank meaning "leave unchanged", exactly like every other bulk
 *  field in the app, and a blank field is OMITTED from the payload rather
 *  than sent as null — the server reads key presence, so an omitted key
 *  leaves the stored date alone. Without that, bulk-setting a deadline
 *  across ten rows would silently wipe the planned end date on the one row
 *  that had one.
 *
 *  Which means this dialog can SET a date but not CLEAR one: a blank
 *  field is already spoken for by "leave unchanged", and two different
 *  intentions cannot share one blank input. Clearing is deliberate,
 *  per-request work — the Details card's date editor does it. Offering a
 *  bulk clear would need a third state (a checkbox per field), and the
 *  operation it enables, wiping a date across a selection, is not one
 *  worth making easy to reach by accident. */
function BulkDatesDialog({
  count,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  count: number;
  busy: boolean;
  error: string;
  onCancel: () => void;
  onConfirm: (payload: {
    deadline?: string;
    planned_end_date?: string;
  }) => void;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const [deadline, setDeadline] = useState("");
  const [plannedEnd, setPlannedEnd] = useState("");

  const nothingToDo = !deadline && !plannedEnd;

  function confirm() {
    const payload: { deadline?: string; planned_end_date?: string } = {};
    if (deadline) payload.deadline = deadline;
    if (plannedEnd) payload.planned_end_date = plannedEnd;
    onConfirm(payload);
  }

  return (
    // Same overlay idiom as `AssignPeopleDialog` next door — an inline
    // positioned backdrop plus a `card`, NOT a native <dialog>. CLAUDE.md
    // records why the imperative ones are trouble when mounted
    // conditionally; this one is plain markup and mounts safely.
    <div
      role="presentation"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
        padding: 16,
      }}
    >
      <div
        className="card"
        role="dialog"
        aria-modal="true"
        style={{ maxWidth: 520, width: "100%", padding: 24 }}
        data-testid="extra-work-bulk-dates-dialog"
      >
        <h2 className="form-section-title">{t("list.bulk_dates_title")}</h2>
        <p className="muted small">
          {t("list.bulk_dates_summary", { count })}
        </p>
        <div className="field">
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span className="muted small">{t("detail.deadline")}</span>
            <input
              type="date"
              className="field-input"
              value={deadline}
              onChange={(event) => setDeadline(event.target.value)}
              data-testid="extra-work-bulk-dates-deadline"
            />
          </label>
          <label
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 4,
              marginTop: 8,
            }}
          >
            <span className="muted small">
              {t("detail.field_planned_end_date")}
            </span>
            <input
              type="date"
              className="field-input"
              value={plannedEnd}
              onChange={(event) => setPlannedEnd(event.target.value)}
              data-testid="extra-work-bulk-dates-planned-end"
            />
          </label>
          <div className="muted small" style={{ marginTop: 8 }}>
            {t("list.bulk_dates_unchanged_hint")}
          </div>
        </div>
        {error && (
          <div className="alert-error" style={{ marginTop: 8 }}>
            {error}
          </div>
        )}
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
            marginTop: 16,
          }}
        >
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onCancel}
            disabled={busy}
          >
            {t("common:cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={confirm}
            disabled={busy || nothingToDo}
            data-testid="extra-work-bulk-dates-confirm"
          >
            {busy ? t("detail.dates_saving") : t("common:save")}
          </button>
        </div>
      </div>
    </div>
  );
}

function KpiCard({
  icon: Icon,
  label,
  value,
  meta,
  testId,
}: {
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  meta: string;
  testId: string;
}) {
  return (
    <div className="ew-kpi-card" data-testid={testId}>
      <div className="ew-kpi-card-icon" aria-hidden="true">
        <Icon size={18} strokeWidth={1.9} />
      </div>
      <div className="ew-kpi-card-body">
        <div className="ew-kpi-card-label">{label}</div>
        <div className="ew-kpi-card-value">{value}</div>
        <div className="ew-kpi-card-meta">{meta}</div>
      </div>
    </div>
  );
}

/**
 * Sprint 169 §8 — ONE extra-work list, mounted twice.
 *
 * `CustomerExtraWorkPage` was a 296-line read-only re-implementation of
 * this 1202-line page: no checkbox column, no `MultiSelectToolbar`, no
 * `useEditMode`, no bulk assignment, no bulk status action. Everything
 * Sprints 158-164 built here was missing there, because they were two
 * independently-maintained copies of the same list — the failure mode
 * CLAUDE.md names explicitly.
 *
 * Copying the features across would have produced two copies that drift
 * again. So the list is this component, and the difference between the
 * two entry points is ONE prop:
 *
 *   from the sidebar        no customer fixed, the customer filter is
 *                           offered;
 *   from inside a customer  the customer is fixed and its filter is not
 *                           offered. Everything else is identical.
 *
 * Fixing the customer is a UI convenience and nothing more. The request
 * carries `customer=<id>` exactly as the picker would have set it, and
 * the SERVER still decides what the actor may see — a customer id the
 * actor has no access to returns their own rows, not that customer's.
 */
export function ExtraWorkList({
  customerId,
  hideHeader = false,
}: {
  customerId?: number;
  /** The customer page draws its own header, so this one is suppressed
   *  rather than stacked under it. */
  hideHeader?: boolean;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const { me } = useAuth();
  // M6.3 — additive "my work" deep-link reads. With both params absent
  // these resolve to undefined below, so the fetch is unchanged.
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  // Provider-only: the billing-month picker, invoice-status filter, and the
  // invoiced column. The backend redacts the billing fields for CUSTOMER_USER
  // anyway; this also hides the controls from them.
  const isProvider = isProviderManagementRole(me?.role);
  // Sprint 155 §1b — the create button asks which of the three.
  const [chooserOpen, setChooserOpen] = useState(false);
  // Sprint 157 §2 — assign people to several requests at once, behind
  // the Sprint 155 §4 edit gate like every other list.
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignBusy, setAssignBusy] = useState(false);
  const [assignError, setAssignError] = useState("");
  // Sprint 176 §3 — bulk deadline / planned end, behind the same edit gate.
  const [datesOpen, setDatesOpen] = useState(false);
  const [datesBusy, setDatesBusy] = useState(false);
  const [datesError, setDatesError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  // Sprint 159 §2 — BOTH roles at once, so both candidate lists are
  // held. Keyed by role because eligibility differs between them and one
  // shared list would offer a worker as a manager.
  const [assignCandidates, setAssignCandidates] = useState<
    Record<ExtraWorkAssignmentRole, AssignmentCandidate[]>
  >({ WORKER: [], MANAGER: [] });
  const [rows, setRows] = useState<ExtraWorkRequestList[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Filter state (client-side; the backend list endpoint IS paginated, but
  // Sprint 120 switched this page to `listAllExtraWork`, which pages
  // through every `next` until exhausted (capped, see api/extraWork.ts) —
  // so `rows` below is the FULL matching set regardless of how many pages
  // that takes, and filtering happens over the complete set, not one page.
  const [searchInput, setSearchInput] = useState("");
  // Sprint 180 §1 — which of the two tracks is on screen. A VIEW, not a
  // filter: one of the two is always selected, and each carries its own
  // columns. Quote & price opens first because that is where work
  // arrives and where somebody has to act on it. A deep link that lands
  // on the wrong track is not left stranded — the empty state names the
  // other one and offers the click (see the EmptyState `action` below).
  const [track, setTrack] = useState<ExtraWorkTrack>("QUOTE");
  // RF-18 (#107) — dashboard widgets deep-link with ?status=<EW status>;
  // read once at mount (validated), the dropdown owns the state after.
  // Sprint 158 §2 — the list opens on what has not been actioned.
  // `REQUESTED` is the genuinely-untouched status in
  // `ExtraWorkStatus` (the customer has asked, nobody has picked it up),
  // and the owner named it. A `?status=` deep link still wins, and
  // `?status=ALL` is how a link asks for everything.
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() => {
    const raw = new URLSearchParams(window.location.search).get("status");
    if (raw === "ALL") return "ALL";
    return raw && (STATUS_FILTER_OPTIONS as readonly string[]).includes(raw)
      ? (raw as StatusFilter)
      : "REQUESTED";
  });
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("");
  const [categoryOptions, setCategoryOptions] =
    useState<ExtraWorkCategoryOptions>({ live: [], historical: [] });

  // Server-side filters (M4): these drive the 2d list endpoint
  // (?billing_period / ?invoice_status). Search / status / category stay
  // client-side. "" = no billing-month filter.
  const [billingMonth, setBillingMonth] = useState("");
  const [invoiceStatus, setInvoiceStatus] = useState<
    "ALL" | "completed" | "invoiced"
  >("ALL");

  // Sprint 128 — provider label-cascade filters (Customer -> Building ->
  // Department -> Work Type), all four server-side (they compose in the
  // backend ExtraWorkRequestFilter). Building / Department / Work Type are
  // per-customer, so they are disabled until a customer is chosen and cleared
  // when it changes. Provider-only: a CUSTOMER_USER is already scoped to one
  // customer, so a customer picker is meaningless for them.
  // Seeded from the fixed customer when there is one. A plain initial
  // value, not an effect: syncing a prop into state through an effect is
  // the pattern CLAUDE.md bans, and the component is keyed by customer
  // id at the mount site so a change remounts it.
  const [deadlineSort, setDeadlineSort] = useState<"" | "asc" | "desc">("");
  // Sprint 174 §4d — a FILTER, never a mode. Default ALL, and it is
  // visible and clearable: the owner was explicit that planned extra
  // work must still be findable if he changes his mind about planning
  // it, so nothing may hide rows with no way back.
  const [plannedFilter, setPlannedFilter] = useState<
    "ALL" | "PLANNED" | "UNPLANNED"
  >("ALL");
  const [customerFilter, setCustomerFilter] = useState(
    customerId === undefined ? "" : String(customerId),
  );
  const [buildingFilter, setBuildingFilter] = useState("");
  const [departmentFilter, setDepartmentFilter] = useState("");
  const [workTypeFilter, setWorkTypeFilter] = useState("");
  const [customers, setCustomers] = useState<CustomerAdmin[]>([]);
  // The chosen customer's buildings + label lists, tagged with the customer
  // id so a stale set from the previously chosen customer is never offered.
  const [customerScoped, setCustomerScoped] = useState<{
    customerId: number;
    buildings: CustomerBuildingMembership[];
    departments: CustomerLabel[];
    workTypes: CustomerLabel[];
  } | null>(null);

  // #108 Part F — the mark/clear-invoiced run moved to the Facturen
  // page (owner decision); this list keeps the billing-month +
  // invoice-status FILTERS and a pointer link to /invoices.

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const allRows = await listAllExtraWork({
          billing_period: billingMonth || undefined,
          invoice_status: invoiceStatus === "ALL" ? undefined : invoiceStatus,
          created_by:
            searchParams.get("mine") === "1" && me?.id ? me.id : undefined,
          request_intent:
            (searchParams.get("request_intent") as
              | ExtraWorkRequestIntent
              | null) ?? undefined,
          // Sprint 128 — the label cascade (all server-side). A foreign /
          // stale child filter simply narrows to zero rows (scope-safe).
          customer: customerFilter ? Number(customerFilter) : undefined,
          building: buildingFilter ? Number(buildingFilter) : undefined,
          department: departmentFilter ? Number(departmentFilter) : undefined,
          work_type: workTypeFilter ? Number(workTypeFilter) : undefined,
          // Sprint 143 §6 — server-side now (was a client-side enum
          // compare over rows that had already been fetched).
          category: categoryFilter || undefined,
        });
        if (!cancelled) setRows(allRows);
      } catch (err) {
        if (!cancelled) setError(getApiError(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [
    billingMonth,
    invoiceStatus,
    searchParams,
    me?.id,
    customerFilter,
    buildingFilter,
    departmentFilter,
    workTypeFilter,
    categoryFilter,
    // Sprint 176 §3 — a bulk date write changes rows this list is
    // showing, so it bumps this counter to re-run the load. A counter
    // rather than a hoisted `load()`: the fetch is guarded by the
    // effect's own `cancelled` flag, and calling it from outside would
    // escape that guard.
    reloadKey,
  ]);

  // Sprint 143 §6 — the category dropdown's two groups. Own effect
  // because it does not depend on any filter; a failure leaves the
  // dropdown with just "all", which still lists everything.
  useEffect(() => {
    let cancelled = false;
    listExtraWorkCategoryOptions()
      .then((res) => {
        if (!cancelled) setCategoryOptions(res);
      })
      .catch(() => {
        /* non-fatal: the list itself is unaffected */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Sprint 128 — load the customer list once (provider only; a CUSTOMER_USER
  // has no customer picker).
  useEffect(() => {
    if (!isProvider) return;
    let cancelled = false;
    listAllCustomers()
      .then((res) => {
        if (!cancelled) setCustomers(res);
      })
      .catch(() => {
        // A load failure just leaves the customer picker empty.
      });
    return () => {
      cancelled = true;
    };
  }, [isProvider]);

  // Sprint 128 — LOAD-ONLY effect (no synchronous setState — CLAUDE.md §3):
  // when the customer filter changes, load the chosen customer's buildings +
  // active label lists. The three dependent filters are CLEARED in the
  // customer <select> onChange (an event handler, not here), so a stale child
  // id never reaches the fetch; `customerScoped` is guarded by customer id
  // below so a stale option set is never shown either.
  useEffect(() => {
    const customerId = customerFilter ? Number(customerFilter) : null;
    if (!customerId) return;
    let cancelled = false;
    Promise.all([
      listCustomerBuildings(customerId),
      listLabels(customerId, "department", { is_active: true }),
      listLabels(customerId, "work_type", { is_active: true }),
    ])
      .then(([buildingsRes, departments, workTypes]) => {
        if (!cancelled) {
          setCustomerScoped({
            customerId,
            buildings: buildingsRes.results,
            departments,
            workTypes,
          });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCustomerScoped({
            customerId,
            buildings: [],
            departments: [],
            workTypes: [],
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [customerFilter]);

  // Sprint 180 §1 — the two tracks, split on the ONE question: has an
  // operational ticket been born from this extra work? The answer comes
  // from the server (`has_operational_ticket`, resolved through the
  // canonical `Ticket.extra_work_request` FK — the same definition the
  // invoice run uses), so this list cannot drift from the money.
  const trackRows = useMemo(() => {
    const quote: ExtraWorkRequestList[] = [];
    const started: ExtraWorkRequestList[] = [];
    for (const row of rows) {
      (row.has_operational_ticket ? started : quote).push(row);
    }
    return { QUOTE: quote, STARTED: started };
  }, [rows]);

  const activeTrackRows = trackRows[track];
  const isWorkStarted = track === "STARTED";
  const otherTrack: ExtraWorkTrack = isWorkStarted ? "QUOTE" : "STARTED";

  // Switching track is a VIEW change with two pieces of clean-up, and
  // both belong in the event handler rather than an effect (syncing
  // state through an effect body is the pattern CLAUDE.md bans).
  const switchTrack = useCallback((value: ExtraWorkTrack) => {
    setTrack(value);
    // The two tracks hold different statuses almost by definition, so
    // carrying "REQUESTED" onto Work started would show an empty table
    // and read as "there is nothing here" rather than "you are still
    // filtered".
    setStatusFilter("ALL");
    if (value === "QUOTE") {
      // The two invoice filters have no control on this track, so they
      // must not stay applied behind its back.
      setBillingMonth("");
      setInvoiceStatus("ALL");
    }
  }, []);

  // §1(b) — approved-but-never-spawned rows, counted for the Quote &
  // price tab's marker. They stay on this track (nothing operational has
  // started) but they are a failure, not a state.
  const spawnAnomalyCount = useMemo(
    () => trackRows.QUOTE.filter(isSpawnAnomaly).length,
    [trackRows],
  );

  // Sprint 158 §2 — counts per status, computed from loaded rows and
  // not from `visibleRows`, or every chip but the active one would read
  // zero.
  // Sprint 180 §1 — over the ACTIVE TRACK rather than over everything:
  // a tile that promises nine rows and then shows none because they are
  // all on the other track is worse than no number.
  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const row of activeTrackRows) {
      counts[row.status] = (counts[row.status] ?? 0) + 1;
    }
    return counts;
  }, [activeTrackRows]);

  // KPI strip — computed from the full loaded set (not the filtered
  // view, and not the active track) so the operator always sees the same
  // headline numbers regardless of which filter is active. `rows` is the
  // COMPLETE matching set (Sprint 120 — listAllExtraWork exhausts every
  // page), so these totals no longer silently undercount past 100 rows.
  // A backend aggregation endpoint remains a future option if request
  // volume on very large tenants becomes a real cost; not needed for
  // correctness.
  const kpis = useMemo<ExtraWorkKpis>(() => {
    let open = 0;
    let awaiting = 0;
    let approved = 0;
    let totalNum = 0;
    for (const r of rows) {
      if (r.status === "REQUESTED" || r.status === "UNDER_REVIEW") open += 1;
      else if (r.status === "PRICING_PROPOSED") awaiting += 1;
      else if (r.status === "CUSTOMER_APPROVED") approved += 1;
      // Earned = final actual-hours amount when present, else the quoted
      // estimate (rowAmounts — the shared billing rule the /invoices widget
      // uses), so this KPI agrees with the per-row Total column below.
      if (r.status !== "CANCELLED") {
        totalNum += rowAmounts(r).total;
      }
    }
    return {
      open,
      awaiting,
      approved,
      totalValue: totalNum.toFixed(2),
    };
  }, [rows]);

  const visibleRows = useMemo(() => {
    const needle = searchInput.trim().toLowerCase();
    const filtered = activeTrackRows.filter((r) => {
      if (statusFilter !== "ALL" && r.status !== statusFilter) return false;
      if (needle) {
        const hay = `${r.title} ${r.building_name ?? ""} ${
          r.customer_name ?? ""
        }`.toLowerCase();
        if (!hay.includes(needle)) return false;
      }
      return true;
    });
    // Sprint 174 §1/§4d — the deadline sort and the planned filter.
    // Both are CLIENT-side over rows the server already scoped: the
    // list is a page of rows the operator can see, and a second server
    // round-trip to reorder what is already on screen would be slower
    // and no more correct.
    const narrowed =
      plannedFilter === "ALL"
        ? filtered
        : filtered.filter((r) =>
            plannedFilter === "PLANNED"
              ? Boolean(r.preferred_date)
              : !r.preferred_date,
          );
    if (!deadlineSort) return narrowed;
    return [...narrowed].sort((a, b) => {
      // A row with NO deadline sorts last in both directions: "nobody
      // said when" is not earlier or later than a date, and putting it
      // first would bury the rows the sort exists to surface.
      if (!a.deadline && !b.deadline) return 0;
      if (!a.deadline) return 1;
      if (!b.deadline) return -1;
      const order = a.deadline.localeCompare(b.deadline);
      return deadlineSort === "asc" ? order : -order;
    });
  }, [
    activeTrackRows,
    searchInput,
    statusFilter,
    deadlineSort,
    plannedFilter,
  ]);


  // Sprint 157 §2 — the Edit gate + the bulk assign handlers. The
  // controller is keyed on the CURRENTLY VISIBLE rows, so a selection
  // cannot outlive a filter change (lib/useEditMode.ts derives both the
  // mode and the selection for exactly this reason).
  const edit = useEditMode(visibleRows.map((row) => row.id));

  // Sprint 158 §1 — eligibility is per (request, role) and comes from
  // the SERVER. With several requests selected the offer is the
  // INTERSECTION: somebody eligible at one building but not another
  // would be rejected for the whole batch (the endpoint is
  // all-or-nothing), so offering them would be offering a guaranteed
  // failure.
  const loadAssignCandidates = useCallback(async (requestIds: number[]) => {
    if (requestIds.length === 0) {
      setAssignCandidates({ WORKER: [], MANAGER: [] });
      return;
    }
    const forRole = async (role: ExtraWorkAssignmentRole) => {
      const lists = await Promise.all(
        requestIds.map((id) => listExtraWorkAssignmentCandidates(id, role)),
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

  async function openAssign() {
    setAssignError("");
    setAssignOpen(true);
    await loadAssignCandidates(edit.selection);
  }

  /** ONE request for both roles — see `AssignPeopleDialog`. */
  async function runAssign(managerIds: number[], workerIds: number[]) {
    setAssignBusy(true);
    setAssignError("");
    try {
      await bulkAssignExtraWork({
        requests: edit.selection,
        managers: managerIds,
        workers: workerIds,
        mode: "assign",
      });
      setAssignOpen(false);
      edit.exit();
    } catch (err) {
      setAssignError(getApiError(err));
    } finally {
      setAssignBusy(false);
    }
  }

  /** Sprint 176 §3 — one date across a selection.
   *
   *  The payload is built by OMITTING what the operator left alone, never
   *  by spreading the dialog's state: a blank field must mean "leave
   *  unchanged", and sending it as `null` would clear that date on every
   *  selected row — a data-loss bug that looks like a successful save.
   *  The dialog therefore hands back only the fields it was actually
   *  given. */
  async function runBulkDates(payload: {
    deadline?: string;
    planned_end_date?: string;
  }) {
    setDatesBusy(true);
    setDatesError("");
    try {
      await bulkSetExtraWorkDates({
        requests: edit.selection,
        ...payload,
      });
      setDatesOpen(false);
      edit.exit();
      setReloadKey((key) => key + 1);
    } catch (err) {
      setDatesError(getApiError(err));
    } finally {
      setDatesBusy(false);
    }
  }

  // M4 (3c) — client-side itemized CSV of the in-view rows. Mirrors the
  // proposal-PDF Blob + object-URL + synthetic <a download> pattern. UTF-8
  // BOM so Excel reads Dutch characters, CRLF line endings, quoted fields.
  function exportCsv() {
    const esc = (v: string | null | undefined) =>
      `"${String(v ?? "").replace(/"/g, '""')}"`;
    const headers = [
      t("list.column_title"),
      t("list.column_customer"),
      t("list.column_building"),
      t("list.column_status"),
      t("list.export_col_subtotal"),
      t("list.export_col_vat"),
      t("list.column_total"),
      t("list.column_billing"),
      t("list.export_col_invoice_date"),
      t("list.column_requested"),
    ];
    const lines = [headers.map(esc).join(",")];
    for (const row of visibleRows) {
      // Earned (final-with-quoted-fallback) so the export matches the on-screen
      // Total; the three columns stay coherent (subtotal + vat == total).
      const amounts = rowAmounts(row);
      lines.push(
        [
          row.title,
          row.customer_name,
          row.building_name,
          t(STATUS_I18N_KEY[row.status] ?? row.status),
          amounts.subtotal.toFixed(2),
          amounts.vat.toFixed(2),
          amounts.total.toFixed(2),
          row.is_invoiced
            ? t("list.billing_invoiced")
            : t("list.billing_to_invoice"),
          row.invoice_date ? formatDate(row.invoice_date) : "",
          formatDate(row.requested_at),
        ]
          .map(esc)
          .join(","),
      );
    }
    const csv = "\uFEFF" + lines.join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `extra-work_${billingMonth}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  // Sprint 128 — the child options to OFFER right now, guarded inline so a set
  // fetched for a previously chosen customer is never shown against the
  // current one (and TS narrows `customerScoped`).
  const scopedBuildings =
    customerScoped && String(customerScoped.customerId) === customerFilter
      ? customerScoped.buildings
      : [];
  const scopedDepartments =
    customerScoped && String(customerScoped.customerId) === customerFilter
      ? customerScoped.departments
      : [];
  const scopedWorkTypes =
    customerScoped && String(customerScoped.customerId) === customerFilter
      ? customerScoped.workTypes
      : [];
  const customerChosen = customerFilter !== "";

  return (
    <div data-testid="extra-work-list-page">
      {!hideHeader && (
      <PageHeader
        backLink={{ to: "/", label: t("back_to_dashboard") }}
        eyebrow={t("common:ops")}
        title={t("list.page_title")}
        subtitle={t("list.page_subtitle")}
        actions={
          /* Sprint 155 §1b — this button used to go straight to the
             direct-order form, which is only ONE of the three things
             "new extra work" can mean here. It now asks. */
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => setChooserOpen(true)}
            data-testid="extra-work-list-create-link"
          >
            <PlusCircle size={14} strokeWidth={2.2} />
            <span style={{ marginLeft: 6 }}>{t("list.create_button")}</span>
          </button>
        }
      />
      )}

      {assignOpen && (
        <AssignPeopleDialog
          summary={t("assign.summary_requests", {
            count: edit.selection.length,
          })}
          managerCandidates={assignCandidates.MANAGER.map((person) => ({
            id: person.id,
            label: person.full_name || person.email,
            sublabel: person.email,
          }))}
          workerCandidates={assignCandidates.WORKER.map((person) => ({
            id: person.id,
            label: person.full_name || person.email,
            sublabel: person.email,
          }))}
          busy={assignBusy}
          error={assignError}
          onCancel={() => setAssignOpen(false)}
          onConfirm={runAssign}
        />
      )}

      {datesOpen && (
        <BulkDatesDialog
          count={edit.selection.length}
          busy={datesBusy}
          error={datesError}
          onCancel={() => setDatesOpen(false)}
          onConfirm={runBulkDates}
        />
      )}

      {chooserOpen && (
        <ChoiceDialog
          title={t("list.create_chooser_title")}
          subtitle={t("list.create_chooser_subtitle")}
          onCancel={() => setChooserOpen(false)}
          testIdPrefix="extra-work-create-chooser"
          choices={[
            {
              key: "request",
              label: t("list.create_chooser_request"),
              description: t("list.create_chooser_request_desc"),
              onSelect: () => navigate("/extra-work/new"),
            },
            {
              key: "quote",
              label: t("list.create_chooser_quote"),
              description: t("list.create_chooser_quote_desc"),
              onSelect: () => navigate("/extra-work/request-quote"),
            },
            {
              key: "recurring",
              label: t("list.create_chooser_recurring"),
              description: t("list.create_chooser_recurring_desc"),
              // Sprint 156 §2 — the recurring option was the odd one
              // out: the other two open a FORM and this one opened the
              // LIST, so "create" landed the operator on a page with
              // nothing created. /planned-work/new is the existing
              // create route (App.tsx) — no new route, no new page.
              onSelect: () => navigate("/planned-work/new"),
            },
          ]}
        />
      )}

      {loading && (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      )}

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* KPI strip */}
      <div className="ew-list-kpi-row" data-testid="extra-work-list-kpi-row">
        <KpiCard
          icon={Inbox}
          label={t("kpi.open_label")}
          value={kpis.open}
          meta={t("kpi.open_meta")}
          testId="extra-work-list-kpi-open"
        />
        <KpiCard
          icon={Clock}
          label={t("kpi.awaiting_label")}
          value={kpis.awaiting}
          meta={t("kpi.awaiting_meta")}
          testId="extra-work-list-kpi-awaiting"
        />
        <KpiCard
          icon={CheckCircle2}
          label={t("kpi.approved_label")}
          value={kpis.approved}
          meta={t("kpi.approved_meta")}
          testId="extra-work-list-kpi-approved"
        />
        <KpiCard
          icon={Wallet}
          label={t("kpi.value_label")}
          value={formatMoney(kpis.totalValue)}
          meta={t("kpi.value_meta")}
          testId="extra-work-list-kpi-value"
        />
      </div>

      {/* Sprint 180 §1 — the two tracks. An extra work has a commercial
          life and an operational one; this is which of the two you are
          looking at, and it decides the columns below. Above the status
          tiles because it is the coarser question: first WHICH life,
          then which step within it. */}
      <TrackTabs
        tabs={[
          {
            value: "QUOTE",
            label: t("list.track_quote"),
            count: trackRows.QUOTE.length,
            anomalyCount: spawnAnomalyCount,
            anomalyTitle: t("list.track_anomaly_title"),
          },
          {
            value: "STARTED",
            label: t("list.track_started"),
            count: trackRows.STARTED.length,
          },
        ]}
        active={track}
        onChange={switchTrack}
        testIdPrefix="extra-work-track"
      />

      <p className="ew-list-filters-hint muted small">
        {track === "QUOTE"
          ? t("list.track_quote_hint")
          : t("list.track_started_hint")}
      </p>

      {/* Sprint 159 §3 — the statuses as TILES, the design the owner
          picked for both work lists. Every one visible with its count
          (real ones: Sprint 120 made this page fetch the full set), the
          active one visibly selected, and clearing is the All tile or
          the × on the active one rather than a sentence of prose. The
          status dropdown below stays: it is the same state, and removing
          a control an operator may already be using would be hiding a
          feature.
          Sprint 180 — counts and total are per TRACK now, so a tile
          never promises rows that live on the other one. */}
      <StatusTiles
        tiles={STATUS_FILTER_OPTIONS.map((value) => ({
          value,
          label: t(STATUS_I18N_KEY[value]),
          count: statusCounts[value] ?? 0,
        }))}
        active={statusFilter === "ALL" ? "" : statusFilter}
        onChange={(value) =>
          setStatusFilter((value === "" ? "ALL" : value) as StatusFilter)
        }
        totalCount={activeTrackRows.length}
        testIdPrefix="extra-work-status"
      />

      {/* Filter bar */}
      <div
        className="card ew-list-filters"
        data-testid="extra-work-list-filters"
      >
        <div className="filter-field search">
          <Search size={14} strokeWidth={2.2} />
          <input
            className="filter-control"
            type="search"
            placeholder={t("list.search_placeholder")}
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </div>
        <div className="filter-field">
          <span className="filter-label">{t("list.column_status")}</span>
          <select
            className="filter-control"
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.target.value as StatusFilter)
            }
          >
            <option value="ALL">{t("list.filter_all_statuses")}</option>
            {STATUS_FILTER_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {t(STATUS_I18N_KEY[s])}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <span className="filter-label">
            {t("list.filter_catalog_category")}
          </span>
          {/* Sprint 143 §6 — real catalog categories, filtered
              SERVER-side (`?category=`, matched on the order-time
              snapshot). Two groups: what the catalog still offers, and
              names that only survive in history because the category was
              renamed, archived or deleted after the order. The second
              group is why the backend matches the snapshot rather than
              the live FK — a join would silently drop exactly those
              requests. */}
          <select
            className="filter-control"
            value={categoryFilter}
            onChange={(event) => setCategoryFilter(event.target.value)}
            data-testid="extra-work-category-filter"
          >
            <option value="">{t("list.filter_all_categories")}</option>
            {categoryOptions.live.length > 0 && (
              <optgroup label={t("list.filter_category_group_live")}>
                {categoryOptions.live.map((name) => (
                  <option key={`live-${name}`} value={name}>
                    {name}
                  </option>
                ))}
              </optgroup>
            )}
            {categoryOptions.historical.length > 0 && (
              <optgroup label={t("list.filter_category_group_historical")}>
                {categoryOptions.historical.map((name) => (
                  <option key={`hist-${name}`} value={name}>
                    {name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </div>
        <div className="filter-field">
          <span className="filter-label">{t("list.filter_planned")}</span>
          <select
            className="filter-control"
            value={plannedFilter}
            onChange={(event) =>
              setPlannedFilter(
                event.target.value as "ALL" | "PLANNED" | "UNPLANNED",
              )
            }
            data-testid="extra-work-list-filter-planned"
          >
            <option value="ALL">{t("list.planned_all")}</option>
            <option value="PLANNED">{t("list.planned_only")}</option>
            <option value="UNPLANNED">{t("list.planned_none")}</option>
          </select>
        </div>

        {isProvider && customerId === undefined && (
          <>
            {/* Sprint 128 — the label cascade: Customer -> Building ->
                Department -> Work Type. The last three are per-customer, so
                they are disabled (with a hint) until a customer is chosen and
                clear when it changes. */}
            <div className="filter-field">
              <span className="filter-label">{t("list.filter_customer")}</span>
              <select
                className="filter-control"
                value={customerFilter}
                onChange={(event) => {
                  // Clear the dependent (per-customer) filters here in the
                  // event handler — never in the load effect (CLAUDE.md §3).
                  setCustomerFilter(event.target.value);
                  setBuildingFilter("");
                  setDepartmentFilter("");
                  setWorkTypeFilter("");
                }}
                data-testid="extra-work-list-filter-customer"
              >
                <option value="">{t("list.filter_all_customers")}</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="filter-field">
              <span className="filter-label">{t("list.filter_building")}</span>
              <select
                className="filter-control"
                value={buildingFilter}
                onChange={(event) => setBuildingFilter(event.target.value)}
                disabled={!customerChosen}
                title={
                  customerChosen
                    ? undefined
                    : t("list.filter_pick_customer_hint")
                }
                data-testid="extra-work-list-filter-building"
              >
                <option value="">{t("list.filter_all_buildings")}</option>
                {scopedBuildings.map((b) => (
                  <option key={b.building_id} value={b.building_id}>
                    {b.building_name}
                  </option>
                ))}
              </select>
            </div>
            <div className="filter-field">
              <span className="filter-label">
                {t("list.filter_department")}
              </span>
              <select
                className="filter-control"
                value={departmentFilter}
                onChange={(event) => setDepartmentFilter(event.target.value)}
                disabled={!customerChosen}
                title={
                  customerChosen
                    ? undefined
                    : t("list.filter_pick_customer_hint")
                }
                data-testid="extra-work-list-filter-department"
              >
                <option value="">{t("list.filter_all_departments")}</option>
                {scopedDepartments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="filter-field">
              <span className="filter-label">
                {t("list.filter_work_type")}
              </span>
              <select
                className="filter-control"
                value={workTypeFilter}
                onChange={(event) => setWorkTypeFilter(event.target.value)}
                disabled={!customerChosen}
                title={
                  customerChosen
                    ? undefined
                    : t("list.filter_pick_customer_hint")
                }
                data-testid="extra-work-list-filter-work-type"
              >
                <option value="">{t("list.filter_all_work_types")}</option>
                {scopedWorkTypes.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </select>
            </div>
            {/* Sprint 180 §1 — the two INVOICE filters belong to the
                Work started track for the same reason the invoice
                column does: a request with no operational ticket cannot
                be invoiceable yet, so offering to filter it by billing
                month invites a question the data cannot answer. Both
                are CLEARED when the operator switches back (see the
                TrackTabs handler) — a hidden filter that is still
                applied is worse than no filter. */}
            {isWorkStarted && (
            <div className="filter-field">
              <span className="filter-label">
                {t("list.filter_billing_month")}
              </span>
              <span
                style={{
                  display: "inline-flex",
                  gap: 6,
                  alignItems: "center",
                }}
              >
                <input
                  className="filter-control"
                  type="month"
                  value={billingMonth}
                  onChange={(event) => setBillingMonth(event.target.value)}
                  data-testid="extra-work-list-billing-month"
                />
                {billingMonth && (
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => setBillingMonth("")}
                  >
                    {t("list.filter_billing_month_clear")}
                  </button>
                )}
              </span>
            </div>
            )}
            {isWorkStarted && (
            <div className="filter-field">
              <span className="filter-label">
                {t("list.filter_invoice_status")}
              </span>
              <select
                className="filter-control"
                value={invoiceStatus}
                onChange={(event) =>
                  setInvoiceStatus(
                    event.target.value as "ALL" | "completed" | "invoiced",
                  )
                }
                data-testid="extra-work-list-invoice-status"
              >
                <option value="ALL">{t("list.invoice_status_all")}</option>
                <option value="completed">
                  {t("list.invoice_status_completed")}
                </option>
                <option value="invoiced">
                  {t("list.invoice_status_invoiced")}
                </option>
              </select>
            </div>
            )}
          </>
        )}
        {/* Sprint 138 §6 — the cascade hint used to be its own
            `.filter-field`, so it floated between the controls and made
            the bar look ragged. It now sits on ONE line beneath the
            controls it describes (and as a `title` on each disabled
            control), spanning the full row. */}
        {isProvider && !customerChosen && (
          <div
            className="ew-list-filters-hint muted small"
            data-testid="extra-work-list-filter-hint"
          >
            {t("list.filter_pick_customer_hint")}
          </div>
        )}
      </div>

      {/* M4 toolbar, reduced by #108 Part F — the mark/clear-invoiced
          run lives on the Facturen page now; a muted pointer replaces
          the buttons. The month label + CSV export stay. */}
      {isProvider && billingMonth && (
        <div
          className="card"
          data-testid="extra-work-list-invoice-run"
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            gap: 12,
            marginBottom: 16,
          }}
        >
          <span style={{ fontWeight: 600 }}>
            {t("list.invoice_run_label", { month: billingMonth })}
          </span>
          <span className="muted small">
            {t("list.invoice_run_pointer_prefix")}{" "}
            <Link to="/invoices" className="link">
              {t("list.invoice_run_pointer_link")}
            </Link>
          </span>
          <div style={{ marginLeft: "auto" }}>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={visibleRows.length === 0}
              onClick={exportCsv}
              data-testid="extra-work-list-export-csv"
            >
              {t("list.export_csv")}
            </button>
          </div>
        </div>
      )}

      {/* Empty / list.
          Sprint 180 §1 — the TRACK is a narrowing an operator did not
          necessarily choose: a dashboard deep link (?status=COMPLETED)
          lands on Quote & price, where by definition almost nothing
          with that status lives. Rather than let the page read as
          "there is nothing", the action below says how many rows are on
          the other track and offers the one click. */}
      {!loading && visibleRows.length === 0 && !error && (
        <EmptyState
          icon={Sparkles}
          title={
            billingMonth
              ? t("list.empty_billing_month")
              : rows.length === 0
                ? t("list.empty_state")
                : t("list.empty_filtered_title")
          }
          description={
            billingMonth || rows.length === 0
              ? undefined
              : t("list.empty_filtered_desc")
          }
          action={
            trackRows[otherTrack].length > 0 ? (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => switchTrack(otherTrack)}
                data-testid="extra-work-track-switch"
              >
                {t("list.track_switch_to", {
                  count: trackRows[otherTrack].length,
                  track: t(
                    otherTrack === "QUOTE"
                      ? "list.track_quote"
                      : "list.track_started",
                  ),
                })}
              </button>
            ) : undefined
          }
          testId="extra-work-list-empty"
        />
      )}

      {isProvider && visibleRows.length > 0 && (
        <div className="ew-list-edit-bar">
          {edit.editMode && (
            <MultiSelectToolbar
              selectedCount={edit.selection.length}
              onSelectAll={edit.selectAll}
              onClearAll={edit.clear}
              disabled={assignBusy}
              actions={[
                {
                  key: "assign",
                  label: t("assign.button"),
                  onClick: openAssign,
                },
                // Sprint 176 §3 — a batch of jobs agreed for the same
                // week is the normal case, not an edge one.
                {
                  key: "dates",
                  label: t("list.bulk_dates_button"),
                  onClick: () => {
                    setDatesError("");
                    setDatesOpen(true);
                  },
                },
              ]}
              testIdPrefix="extra-work-bulk"
            />
          )}
          <EditModeToggle
            editMode={edit.editMode}
            onToggle={edit.toggleMode}
            disabled={assignBusy}
            testId="extra-work-edit-mode-toggle"
          />
        </div>
      )}

      {visibleRows.length > 0 && (
        <div className="responsive-table-wrap">
          <div className="card" style={{ overflow: "hidden" }}>
            <table className="data-table">
              <thead>
                <tr>
                  {edit.editMode && (
                    <th className="th-select">
                      <input
                        type="checkbox"
                        checked={edit.allSelected}
                        onChange={() =>
                          edit.allSelected ? edit.clear() : edit.selectAll()
                        }
                        disabled={assignBusy}
                        aria-label={t("assign.button")}
                        data-testid="extra-work-select-all"
                      />
                    </th>
                  )}
                  <th>{t("list.column_title")}</th>
                  <th>{t("list.column_status")}</th>
                  <th>{t("list.column_route")}</th>
                  <th>{t("list.column_category")}</th>
                  <th>{t("list.column_building")}</th>
                  <th>{t("list.column_customer")}</th>
                  <th style={{ textAlign: "right" }}>
                    {t("list.column_total")}
                  </th>
                  {/* Sprint 180 §1/§2/§3 — the three columns that only
                      make sense once work has actually started. The
                      invoice column in particular: a row with no ticket
                      CANNOT be invoiceable yet, so showing invoice state
                      on the Quote & price track is exactly what confused
                      people. It is not hidden there, it does not apply
                      there. */}
                  {isWorkStarted && <th>{t("list.column_ticket")}</th>}
                  {isWorkStarted && isProvider && (
                    <th>{t("list.column_billing")}</th>
                  )}
                  {isWorkStarted && <th>{t("list.column_billed_to")}</th>}
                  <th>{t("list.column_requested")}</th>
                  {/* Sprint 174 §1 — the DEADLINE, sortable. Sprint 173
                      added the field and the API filter; nothing on any
                      screen showed it, which is where the owner looked
                      for it. */}
                  <th>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() =>
                        setDeadlineSort((current) =>
                          current === "asc"
                            ? "desc"
                            : current === "desc"
                              ? ""
                              : "asc",
                        )
                      }
                      data-testid="ew-sort-deadline"
                    >
                      {t("list.column_deadline")}
                      {deadlineSort === "asc"
                        ? " ▲"
                        : deadlineSort === "desc"
                          ? " ▼"
                          : ""}
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => (
                  <ClickableRow
                    key={row.id}
                    to={`/extra-work/${row.id}`}
                    testId="extra-work-row"
                  >
                    {edit.editMode && (
                      <td
                        className="td-select"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <input
                          type="checkbox"
                          checked={edit.isSelected(row.id)}
                          onChange={() => edit.toggle(row.id)}
                          disabled={assignBusy}
                          aria-label={row.title}
                          data-testid={`extra-work-select-${row.id}`}
                        />
                      </td>
                    )}
                    <td className="td-subject">
                      <Link to={`/extra-work/${row.id}`}>{row.title}</Link>
                    </td>
                    <td>
                      <StatusBadge
                        status={{ kind: "extra-work", value: row.status }}
                      />
                      {/* Sprint 180 §1(b) — approved, but the spawn that
                          is supposed to be synchronous with approval
                          produced no ticket. The row belongs on this
                          track, but saying nothing about it is how the
                          work gets lost. The detail page has the retry
                          button. */}
                      {isSpawnAnomaly(row) && (
                        <span
                          className="cell-tag cell-tag-rejected"
                          style={{ marginLeft: 6 }}
                          title={t("list.track_anomaly_title")}
                          data-testid="ew-no-ticket-marker"
                        >
                          {t("list.track_anomaly_marker")}
                        </span>
                      )}
                    </td>
                    <td>
                      <RouteBadge value={row.routing_decision} />
                    </td>
                    <td>
                      {/* Sprint 144 §1 — new shape first, enum fallback. */}
                      {extraWorkCategoryName(row) ??
                        t(CATEGORY_I18N_KEY[row.category] ?? row.category)}
                    </td>
                    <td>{row.building_name}</td>
                    <td>{row.customer_name}</td>
                    <td style={{ textAlign: "right" }}>
                      {formatMoney(rowAmounts(row).total)}
                    </td>
                    {isWorkStarted && (
                      <td data-testid={`ew-ticket-cell-${row.id}`}>
                        {/* The reverse of the ticket page's "came from
                            Extra Work" block, which has existed for
                            sprints. One row, one link per spawned
                            ticket — one is the normal case (Sprint 6A
                            spawns exactly one). */}
                        {row.spawned_tickets.length === 0 ? (
                          <span className="muted-empty">—</span>
                        ) : (
                          row.spawned_tickets.map((ticket) => (
                            <Link
                              key={ticket.id}
                              to={`/tickets/${ticket.id}`}
                              onClick={(event) => event.stopPropagation()}
                              style={{ marginRight: 8 }}
                            >
                              {ticket.ticket_no ?? `#${ticket.id}`}
                            </Link>
                          ))
                        )}
                      </td>
                    )}
                    {isWorkStarted && isProvider && (
                      <td>
                        {row.is_invoiced ? (
                          <span className="badge badge-approved">
                            {t("list.billing_invoiced")}
                          </span>
                        ) : (
                          <span className="badge badge-normal">
                            {t("list.billing_to_invoice")}
                          </span>
                        )}
                        {row.invoice_date && (
                          <div
                            style={{
                              fontSize: "0.8em",
                              marginTop: 2,
                              color: "var(--text-muted)",
                            }}
                          >
                            {formatDate(row.invoice_date)}
                          </div>
                        )}
                      </td>
                    )}
                    {isWorkStarted && (
                      <td data-testid={`ew-billed-to-cell-${row.id}`}>
                        {t(BILLED_TO_I18N_KEY[row.billed_to])}
                      </td>
                    )}
                    <td>{formatDate(row.requested_at)}</td>
                    <td className="td-date">
                      {row.deadline ? formatDate(row.deadline) : (
                        <span className="muted-empty">—</span>
                      )}
                      {/* The markers, in the status colours this app
                          already has — a new pair would mean two
                          vocabularies for "something is wrong". */}
                      {row.is_overdue && (
                        <span
                          className="cell-tag cell-tag-rejected"
                          style={{ marginLeft: 6 }}
                          data-testid="ew-overdue-marker"
                        >
                          {t("list.overdue")}
                        </span>
                      )}
                      {row.started_before_plan && (
                        <span
                          className="cell-tag cell-tag-open"
                          style={{ marginLeft: 6 }}
                          title={t("list.startedEarlyWhy")}
                          data-testid="ew-started-early-marker"
                        >
                          {t("list.startedEarly")}
                        </span>
                      )}
                    </td>
                  </ClickableRow>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile card fallback */}
          <ul
            className="admin-card-list"
            data-testid="admin-card-list"
            aria-label={t("list.page_title")}
          >
            {visibleRows.map((row) => (
              <li key={row.id} className="admin-card">
                <Link
                  to={`/extra-work/${row.id}`}
                  className="admin-card-link"
                  data-testid="extra-work-card"
                >
                  <div className="admin-card-head">
                    <span className="admin-card-title">{row.title}</span>
                    <span
                      style={{
                        display: "inline-flex",
                        gap: 6,
                        alignItems: "center",
                        flexWrap: "wrap",
                      }}
                    >
                      <StatusBadge
                        status={{ kind: "extra-work", value: row.status }}
                      />
                      <RouteBadge value={row.routing_decision} />
                      {isSpawnAnomaly(row) && (
                        <span
                          className="cell-tag cell-tag-rejected"
                          title={t("list.track_anomaly_title")}
                        >
                          {t("list.track_anomaly_marker")}
                        </span>
                      )}
                    </span>
                  </div>
                  <dl className="admin-card-meta">
                    <div className="admin-card-meta-row">
                      <dt>{t("list.column_route")}</dt>
                      <dd>
                        {row.routing_decision === "INSTANT"
                          ? t("route_badge.instant", { ns: "common" })
                          : t("route_badge.proposal", { ns: "common" })}
                      </dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("list.column_category")}</dt>
                      <dd>
                        {extraWorkCategoryName(row) ??
                          t(CATEGORY_I18N_KEY[row.category] ?? row.category)}
                      </dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("list.column_building")}</dt>
                      <dd>{row.building_name}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("list.column_customer")}</dt>
                      <dd>{row.customer_name}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("list.column_total")}</dt>
                      <dd>{formatMoney(rowAmounts(row).total)}</dd>
                    </div>
                    {/* Sprint 180 — the mobile card carries exactly the
                        columns the table on this track carries. */}
                    {isWorkStarted && (
                      <div className="admin-card-meta-row">
                        <dt>{t("list.column_ticket")}</dt>
                        <dd>
                          {row.spawned_tickets.length === 0
                            ? "—"
                            : row.spawned_tickets
                                .map((tk) => tk.ticket_no ?? `#${tk.id}`)
                                .join(", ")}
                        </dd>
                      </div>
                    )}
                    {isWorkStarted && (
                      <div className="admin-card-meta-row">
                        <dt>{t("list.column_billed_to")}</dt>
                        <dd>{t(BILLED_TO_I18N_KEY[row.billed_to])}</dd>
                      </div>
                    )}
                    {isWorkStarted && isProvider && (
                      <div className="admin-card-meta-row">
                        <dt>{t("list.column_billing")}</dt>
                        <dd>
                          {row.is_invoiced ? (
                            <span className="badge badge-approved">
                              {t("list.billing_invoiced")}
                            </span>
                          ) : (
                            <span className="badge badge-normal">
                              {t("list.billing_to_invoice")}
                            </span>
                          )}
                          {row.invoice_date
                            ? ` · ${formatDate(row.invoice_date)}`
                            : ""}
                        </dd>
                      </div>
                    )}
                    <div className="admin-card-meta-row">
                      <dt>{t("list.column_requested")}</dt>
                      <dd>{formatDate(row.requested_at)}</dd>
                    </div>
                  </dl>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

    </div>
  );
}

/**
 * The sidebar route. A wrapper, so the route keeps its own name while
 * the list itself is the shared component above.
 */
export function ExtraWorkListPage() {
  return <ExtraWorkList />;
}
