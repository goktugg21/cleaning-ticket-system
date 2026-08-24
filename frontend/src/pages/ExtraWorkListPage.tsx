// Sprint 26C — Extra Work list page.
// Sprint 28 Batch 6 — translated through the `extra_work` i18n namespace.
// Sprint 28 Batch 15.3 — rebuilt with KPI strip, filter bar, StatusBadge,
//   formatMoney/formatDate, ClickableRow, mobile card list, EmptyState.
//   Functional contract is unchanged; only the presentation layer moves.
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { PlusCircle, Search, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import { listAllCustomers, listCustomerBuildings } from "../api/admin";
import { listLabels } from "../api/customerLabels";
import {
  bulkAssignExtraWork,
  bulkPlanExtraWork,
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
  ExtraWorkCategory,
  ExtraWorkBulkPlanItem,
  ExtraWorkRequestIntent,
  ExtraWorkRequestList,
  ExtraWorkStatus,
} from "../api/types";
import { getApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { isProviderManagementRole } from "../auth/permissions";
import { ChoiceDialog } from "../components/ChoiceDialog";
import { StatusTiles } from "../components/StatusTiles";
import { FinancialStrip } from "../components/extra-work/FinancialStrip";
import { EditModeToggle } from "../components/EditModeToggle";
import { BulkPlanDialog } from "../components/extra-work/BulkPlanDialog";
import { MultiSelectToolbar } from "../components/MultiSelectToolbar";
import { AssignPeopleDialog } from "../components/AssignPeopleDialog";
import { useEditMode } from "../lib/useEditMode";
import { ClickableRow } from "../components/ClickableRow";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { RouteBadge } from "../components/RouteBadge";
import { StatusBadge } from "../components/StatusBadge";
import { SeriesHeaderRow } from "../components/extra-work/SeriesHeaderRow";
import { foldSeries } from "../lib/extraWorkSeries";
import { isPriced, rowAmounts } from "../lib/billing";
import { formatDate, formatMoney } from "../lib/intl";
import { extraWorkCategoryName } from "../lib/extraWorkCategoryLabel";
import { customerLabelName } from "../lib/customerLabelName";

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

// Sprint 182 §2 — this page's private status-label map is gone.
//
// It pointed at `extra_work:status.*`, where CUSTOMER_APPROVED reads
// "Customer approved", while the badge two lines below rendered
// `common:extra_work_status.*`, where the same status reads "Price
// approved" — the crisp name, because what the customer approved is the
// QUOTE. One row could therefore say one thing on screen and another in
// the CSV taken from it. `extraWorkStatusLabelKey` is the one source now.

/**
 * Sprint 181 §2 — nine chips became four, twice.  W24-FX1 §2a — and
 * four silently dropped rows, twice.
 *
 * The list used to show all nine Extra Work statuses as chips on both
 * tracks. The tracks already answer the biggest question, so the chips
 * were repeating it. Each track was cut down to "only what can be
 * non-zero within it", on this reasoning:
 *
 *   "`IN_PROGRESS` and `COMPLETED` cannot occur in a track defined as
 *    `has no ticket`."
 *
 * That is not true, and the function twenty lines below this one is the
 * proof: `isSpawnAnomaly` exists precisely because a `CUSTOMER_APPROVED`
 * request with no operational ticket is a thing that happens — the spawn
 * is synchronous with approval, so zero tickets means the spawn FAILED.
 * A request stranded that way can still be walked forward by hand into
 * `IN_PROGRESS` and `COMPLETED`, and it is still on the Quote & price
 * track, because nothing operational ever started.
 *
 * `QUOTE_TRACK_CHIPS` named five of the eight Extra Work statuses, so
 * those three rows matched no chip at all: the owner measured ALLE 34
 * against a chip sum of 33. The Work started track had the same hole
 * four times over — it named seven of eleven ticket statuses, missing
 * `ACKNOWLEDGED`, `ON_HOLD`, `REJECTED` and `CONVERTED_TO_EXTRA_WORK`,
 * all four added since. A row that matches no chip is not filtered out;
 * it is simply uncounted, which is the one failure a count must not
 * have.
 *
 * So the chips are no longer WRITTEN as a list. Each track declares a
 * `Record` over its FULL status union, mapping every status to a chip,
 * and the chip list is derived from it. The union is the compiler's, so
 * the next status added to `ExtraWorkStatus` or `TicketStatus` fails the
 * build here until somebody says which chip it belongs in — which is the
 * check that was missing when `ACKNOWLEDGED` and `ON_HOLD` arrived.
 * Chips sum to ALLE by construction, not by inspection.
 *
 * Groupings kept from Sprint 181, and the reasoning is still its own:
 * `REQUESTED` + `UNDER_REVIEW` are two spellings of "nobody has priced
 * this yet"; `WAITING_MANAGER_REVIEW` + `REOPENED_BY_ADMIN` are internal
 * hops inside "in progress"; the terminal ticket states fold into one
 * "Finished", because an operator scanning the list wants to know
 * whether it is done, not which door it left by — which is also why
 * `CONVERTED_TO_EXTRA_WORK`, a third such door, joins them.
 * `ACKNOWLEDGED` ("seen and scheduled, work not begun") folds into Open
 * for the same reason: on this list the question is whether the work has
 * started, and it has not.
 *
 * Every label is an EXISTING key. The three Extra Work statuses and the
 * two ticket statuses that had no chip reuse the StatusBadge vocabulary
 * out of `common.json` (`extra_work_status.*` / `ticket_status.*`, the
 * same strings `enumLabels.ts` resolves for the badges in the table
 * below), so nothing new was added to any bundle.
 */
interface ChipSpec<TStatus extends string> {
  /** Group key. A chip can stand for several statuses, so this is not
   *  necessarily an enum member. */
  value: string;
  statuses: ReadonlyArray<TStatus>;
  labelKey: string;
}

/** Derives the rendered chip list from the two Records.
 *
 *  Order comes from `order`, which is also what `TChip` is derived FROM,
 *  so `chipOf` cannot name a chip the list does not render and `labelOf`
 *  cannot leave one unlabelled. Both directions are the compiler's, which
 *  is the point: a hand-written array is checked by nobody. */
function chipsFromMap<TStatus extends string, TChip extends string>(
  order: ReadonlyArray<TChip>,
  chipOf: Readonly<Record<TStatus, TChip>>,
  labelOf: Readonly<Record<TChip, string>>,
): ReadonlyArray<ChipSpec<TStatus>> {
  const buckets = new Map<TChip, TStatus[]>();
  for (const chip of order) buckets.set(chip, []);
  for (const status of Object.keys(chipOf) as TStatus[]) {
    buckets.get(chipOf[status])?.push(status);
  }
  return order.map((value) => ({
    value,
    statuses: buckets.get(value) ?? [],
    labelKey: labelOf[value],
  }));
}

const QUOTE_CHIP_ORDER = [
  "AWAITING_PRICING",
  "PRICING_PROPOSED",
  "CUSTOMER_APPROVED",
  "IN_PROGRESS",
  "COMPLETED",
  "CUSTOMER_REJECTED",
  "CANCELLED",
] as const;
type QuoteChipValue = (typeof QUOTE_CHIP_ORDER)[number];

/** Every `ExtraWorkStatus`, exhaustively. Adding one to the union breaks
 *  this line until it is placed. */
const QUOTE_CHIP_OF: Readonly<Record<ExtraWorkStatus, QuoteChipValue>> = {
  REQUESTED: "AWAITING_PRICING",
  UNDER_REVIEW: "AWAITING_PRICING",
  PRICING_PROPOSED: "PRICING_PROPOSED",
  // The three that used to fall through. On a track defined as "no
  // operational ticket" these are the stranded-spawn rows, and each
  // keeps its own label rather than being lumped together: "approved",
  // "underway" and "done" are different problems for whoever has to go
  // and fix them.
  CUSTOMER_APPROVED: "CUSTOMER_APPROVED",
  IN_PROGRESS: "IN_PROGRESS",
  COMPLETED: "COMPLETED",
  CUSTOMER_REJECTED: "CUSTOMER_REJECTED",
  CANCELLED: "CANCELLED",
};

const QUOTE_CHIP_LABEL: Readonly<Record<QuoteChipValue, string>> = {
  AWAITING_PRICING: "list.chip_awaiting_pricing",
  PRICING_PROPOSED: "list.chip_with_customer",
  CUSTOMER_APPROVED: "common:extra_work_status.customer_approved",
  IN_PROGRESS: "common:extra_work_status.in_progress",
  COMPLETED: "common:extra_work_status.completed",
  CUSTOMER_REJECTED: "list.chip_rejected",
  CANCELLED: "list.chip_cancelled",
};

const QUOTE_TRACK_CHIPS: ReadonlyArray<ChipSpec<ExtraWorkStatus>> =
  chipsFromMap(QUOTE_CHIP_ORDER, QUOTE_CHIP_OF, QUOTE_CHIP_LABEL);

/** "" = no chip selected (the All tile). A chip value is a GROUP key,
 *  not necessarily a raw enum member. */
type StatusFilter = string;

/** W24-FX1 §2a — the residual chip's value. Deliberately not a status
 *  and not a chip key, so it can never collide with one. */
const UNMATCHED_CHIP = "__UNMATCHED__";

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

/**
 * W2-C — the four KPI counter cards are gone, and `ExtraWorkKpis` with
 * them. Three of the four numbers they carried were already on screen
 * twice:
 *
 *   Open requests    == the "Awaiting pricing" chip, which also FILTERS
 *   Awaiting customer== the "With the customer" chip, same
 *   Price approved   == split across the two tracks BY DESIGN since
 *                       Sprint 180: the "No ticket" badge on Quote &
 *                       price counts the half with no operational
 *                       ticket, and the ticket chips on Chargeable work
 *                       show the other half. This one is a real
 *                       removal, recorded in the sprint checklist.
 *
 * The fourth, the total value, is NOT removed — it moved to the list's
 * own toolbar (`listTotalValue` below), where "the total of these
 * requests" cannot be mistaken for one of the money strip's four
 * carefully-scoped figures. Its ARITHMETIC is untouched, deliberately:
 * relocating a number must not change it.
 */

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
  // W3-F — bulk plan, behind the same edit gate as the two bulk actions
  // beside it. ONE payload applied to the whole selection, which is what
  // the endpoint does; per-work hours are planned on the detail page,
  // because the server refuses hours for anybody not assigned to EACH
  // selected work and one shared distribution is only ever valid when
  // the same crew is on every job.
  const [planOpen, setPlanOpen] = useState(false);
  const [planBusy, setPlanBusy] = useState(false);
  const [planError, setPlanError] = useState("");

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
  // W-NAV1.2 — the Work started track (and its toggle) is gone from this
  // page: started work lives on the Chargeable work list
  // (/tickets/chargeable) now. This list only ever shows the Quote &
  // price track, so there is no view state to hold here any more.
  // RF-18 (#107) — dashboard widgets deep-link with ?status=<EW status>;
  // read once at mount (validated), the chips own the state after.
  //
  // Sprint 181 §2 — the chips are GROUPS now, so a deep link naming a
  // raw status is matched against the groups rather than compared to
  // one. A link to `?status=REQUESTED` lands on the "Awaiting pricing"
  // chip, which is where that row now lives; an unrecognised value
  // falls through to no filter rather than to an empty screen.
  //
  // Sprint 158's "open on what has not been actioned" default is GONE,
  // and deliberately: it only ever made sense for one of the two
  // tracks, and since Sprint 180 the track already answers "what should
  // I look at". Opening pre-filtered on a chip the operator did not
  // pick is the same confusion §2 is removing, one level up.
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() => {
    const raw = new URLSearchParams(window.location.search).get("status");
    if (!raw || raw === "ALL") return "";
    const match = QUOTE_TRACK_CHIPS.find((chip) =>
      (chip.statuses as readonly string[]).includes(raw),
    );
    return match ? match.value : "";
  });
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("");
  const [categoryOptions, setCategoryOptions] =
    useState<ExtraWorkCategoryOptions>({ live: [], historical: [] });

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

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const allRows = await listAllExtraWork({
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

  // W-NAV1.2 — this list only shows the Quote & price side any more:
  // requests with no operational ticket yet. The answer comes from the
  // server (`has_operational_ticket`, resolved through the canonical
  // `Ticket.extra_work_request` FK — the same definition the invoice run
  // uses), so it cannot drift from the money. Started work (an
  // operational ticket exists) lives on the Chargeable work list
  // (/tickets/chargeable) instead.
  const quoteRows = useMemo(
    () => rows.filter((row) => !row.has_operational_ticket),
    [rows],
  );

  /** How many of the loaded requests are NOT on this page because work
   *  has started on them. Only used to offer the Chargeable work link
   *  from the empty state — see the EmptyState `action` below. */
  const startedElsewhereCount = rows.length - quoteRows.length;

  // §1(b) — approved-but-never-spawned rows, counted for the marker
  // beside the list. They stay on this track (nothing operational has
  // started) but they are a failure, not a state.
  const spawnAnomalyCount = useMemo(
    () => quoteRows.filter(isSpawnAnomaly).length,
    [quoteRows],
  );

  const chipMatches = useCallback(
    (row: ExtraWorkRequestList, chipValue: string): boolean => {
      const spec = QUOTE_TRACK_CHIPS.find((c) => c.value === chipValue);
      if (!spec) return false;
      return (spec.statuses as readonly string[]).includes(row.status);
    },
    [],
  );

  // W24-FX1 §2a — counted by BUCKETING each row once, not by running a
  // filter per chip. Same numbers when every row matches, but this shape
  // can also answer "how many matched nothing", and the Record above
  // guarantees that answer is zero for every status the compiler knows
  // about. `unmatched` covers only what the compiler cannot see: a
  // status string the server invented that is not in the union yet. It
  // is surfaced rather than absorbed — an uncounted row is the defect
  // this whole block exists to remove, and hiding the residual would
  // reintroduce it one level down.
  /** The one chip a row belongs to, or `null` when it belongs to none.
   *  With the Record exhaustive over its union, `null` is only reachable
   *  if the server sends a status string the client's union does not
   *  have yet. */
  const rowChipValue = useCallback(
    (row: ExtraWorkRequestList): string | null =>
      QUOTE_TRACK_CHIPS.find((chip) => chipMatches(row, chip.value))
        ?.value ?? null,
    [chipMatches],
  );

  const { statusCounts, unmatchedCount } = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const chip of QUOTE_TRACK_CHIPS) counts[chip.value] = 0;
    let unmatched = 0;
    for (const row of quoteRows) {
      const value = rowChipValue(row);
      if (value === null) unmatched += 1;
      else counts[value] += 1;
    }
    return { statusCounts: counts, unmatchedCount: unmatched };
  }, [quoteRows, rowChipValue]);

  // The list's own money total — computed from the full loaded set (not
  // the filtered view, and not the active track), which is what the
  // label under it says. `rows` is the COMPLETE matching set (Sprint 120
  // — listAllExtraWork exhausts every page), so it does not silently
  // undercount past 100 rows.
  //
  // W2-C moved this out of a KPI card and into the list toolbar and left
  // the arithmetic ALONE. Re-scoping it to `visibleRows` would read
  // better beside the row count and is arguably the bug fix this page
  // wants, but it would also change a number the owner reads while a
  // sprint about layout was in flight. Named as a follow-up in the
  // sprint checklist instead.
  const listTotalValue = useMemo(() => {
    let totalNum = 0;
    for (const r of rows) {
      // Earned = final actual-hours amount when present, else the quoted
      // estimate (rowAmounts — the shared billing rule the /invoices widget
      // uses), so this agrees with the per-row Total column below.
      if (r.status !== "CANCELLED") {
        totalNum += rowAmounts(r).total;
      }
    }
    return totalNum.toFixed(2);
  }, [rows]);

  const visibleRows = useMemo(() => {
    const needle = searchInput.trim().toLowerCase();
    const filtered = quoteRows.filter((r) => {
      // Sprint 181 §2 — a chip stands for a GROUP of statuses.
      // W24-FX1 §2a — the residual chip selects exactly the rows no chip
      // claimed, so clicking it shows them instead of emptying the table.
      if (statusFilter === UNMATCHED_CHIP) {
        if (rowChipValue(r) !== null) return false;
      } else if (statusFilter && !chipMatches(r, statusFilter)) return false;
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
    quoteRows,
    chipMatches,
    rowChipValue,
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

  /** W3-F / W4-O — a plan PER WORK across a selection, in one call.
   *
   *  Same OMIT-what-was-not-touched discipline as `runBulkDates` above,
   *  and for a sharper reason: the two completion flags are booleans the
   *  server reads by KEY PRESENCE, so spreading a dialog's state would
   *  write `false` for a switch nobody looked at and silently clear the
   *  flag on every selected work. The dialog therefore builds each row's
   *  item from what actually changed on that row, and the ids ride
   *  INSIDE the items — this function no longer decides which works the
   *  payload lands on, because with per-work values that is the same
   *  decision as which values land.
   *
   *  All-or-nothing at the far end: one unresolvable id rejects the
   *  batch with zero writes, so there is no partial state to reconcile
   *  and the list is simply reloaded on success. */
  async function runBulkPlan(items: ExtraWorkBulkPlanItem[]) {
    setPlanBusy(true);
    setPlanError("");
    try {
      await bulkPlanExtraWork({ items });
      setPlanOpen(false);
      edit.exit();
      setReloadKey((key) => key + 1);
    } catch (err) {
      setPlanError(getApiError(err));
    } finally {
      setPlanBusy(false);
    }
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

  // W5-B — which series are expanded. Collapsed by default: a series is
  // one agreed job and showing it as twelve identical-looking rows is
  // what this replaces. State lives here rather than in the header row
  // so expansion survives a re-render of the table.
  const [expandedSeries, setExpandedSeries] = useState<number[]>([]);
  // NOTE: the series header spans the table with a deliberately
  // over-large colSpan rather than a counted one. Four of this table's
  // columns are conditional (the select box, the ticket column, the
  // billing column, the billed-to column), so a hand-counted span would
  // be a second list that has to be kept in step with the first — the
  // exact shape of the bug CLAUDE.md records about render-order arrays.
  // HTML clamps an over-large colSpan to the real row width, so 99 is
  // always right and cannot drift.

  /** ONE row — series member or standalone, the SAME markup either way.
   *
   *  Extracted rather than duplicated on purpose: a member of a series
   *  must not quietly render a poorer row than the one an operator is
   *  used to, and two copies of a 150-line row is how that happens. The
   *  only difference is an indent class. */
  function renderRow(row: ExtraWorkRequestList, inSeries = false) {
    return (
                  <ClickableRow
                    key={row.id}
                    className={inSeries ? "ew-series-member" : undefined}
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
                      {/* W-NAV1.2 — ONE status per row, the Extra Work's
                          own. This list is the quote track only now, so
                          there is no ticket to read a status off: a row
                          with an operational ticket is not on this page
                          at all, it is on Chargeable work. */}
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
                      {isPriced(row) ? (
                        formatMoney(rowAmounts(row).total)
                      ) : (
                        <span
                          className="muted-empty"
                          title={t("list.total_not_priced_hint")}
                        >
                          &mdash;
                        </span>
                      )}
                    </td>
                    {/* W-NAV1.2 — the ticket / billing / billed-to
                        columns are gone with the Work started track that
                        was the only place they rendered. A row on this
                        page has no operational ticket by definition, so
                        none of the three has anything to say here. */}
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
    );
  }

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

      {/* W3-F — bulk plan. Conditionally mounted like its two
          neighbours; a plain overlay, not a native `<dialog>`. */}
      {planOpen && (
        <BulkPlanDialog
          rows={rows.filter((row) => edit.selection.includes(row.id))}
          busy={planBusy}
          error={planError}
          onCancel={() => setPlanOpen(false)}
          onConfirm={(items) => void runBulkPlan(items)}
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

      {/* W1-C §2.4 — the money strip. Provider management only; the
          component returns null for anybody else. */}
      <FinancialStrip customerId={customerId} />

      {/* W2-C — ONE band, not three stacked rows.
          W-NAV1.2 — and now one band with ONE control in it. The track
          toggle is gone: this page is the quote track, full stop, and
          started work is the Chargeable work list's job. The sentence
          that explained which track you were on stays, because it still
          says what this list holds; it is no longer a choice, so it is
          no longer beside a control.

          The spawn-anomaly count rode on the removed QUOTE tab as a
          marker. It is NOT dropped with the tab — an approved request
          whose ticket never spawned is a failure somebody has to go and
          fix, and per-row markers alone mean scrolling to find them. It
          sits beside the sentence now, same styling, same title, same
          two existing keys.

          Sprint 159 §3 / 180 / 181 §2 — the chips: the chip IS the
          filter, it carries its own count, the active one is visibly
          selected. */}
      <div className="ew-list-scope" data-testid="extra-work-scope-band">
        <div className="ew-list-scope-top">
          <p className="ew-list-scope-hint muted small">
            {t("list.track_quote_hint")}
            {spawnAnomalyCount > 0 && (
              <span
                className="cell-tag cell-tag-rejected"
                style={{ marginLeft: 6 }}
                title={t("list.track_anomaly_title")}
                data-testid="extra-work-spawn-anomaly-count"
              >
                {t("list.track_anomaly_marker")} {spawnAnomalyCount}
              </span>
            )}
          </p>
        </div>

        <div className="ew-list-scope-chips">
          <StatusTiles
            tiles={[
              ...QUOTE_TRACK_CHIPS.map((chip) => ({
                value: chip.value,
                label: t(chip.labelKey),
                count: statusCounts[chip.value] ?? 0,
              })),
              // W24-FX1 §2a — only ever rendered when the server sent a
              // status this build has no chip for. It is a real filter,
              // not a footnote: a count nobody can open is the same dead
              // end as a row nobody counts.
              ...(unmatchedCount > 0
                ? [
                    {
                      value: UNMATCHED_CHIP,
                      label: t("common:extra_work_status.fallback"),
                      count: unmatchedCount,
                    },
                  ]
                : []),
            ]}
            active={statusFilter}
            onChange={setStatusFilter}
            totalCount={quoteRows.length}
            testIdPrefix="extra-work-status"
          />
        </div>
      </div>

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
        {/* Sprint 181 §2 — the status <select> that stood here is gone.
            It was a SECOND control over the same state as the tiles
            above, offering the same nine options in the less readable
            of the two shapes. A control earns its place by changing
            what somebody does next; this one only offered a second way
            to do what the tiles already do. */}
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
                    {customerLabelName(d.name, t)}
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
                    {customerLabelName(w.name, t)}
                  </option>
                ))}
              </select>
            </div>
            {/* W-NAV1.2 — the two INVOICE filters are gone with the
                Work started track that was the only place they
                rendered. A request with no operational ticket cannot be
                invoiceable yet, so on this page they could only ever
                ask a question the data cannot answer. They live on the
                Chargeable work list and on /invoices. */}
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

      {/* W-NAV1.2 — the M4 invoice-run toolbar is gone. It only ever
          rendered while a billing-month filter was set, and that filter
          left with the Work started track; the CSV export it carried
          went with it, since it exported the invoice columns this page
          no longer has. The Facturen page (/invoices) owns that run. */}

      {/* Empty / list.
          W-NAV1.2 — the rescue the old track-switch button provided is
          kept, pointed at its new home. A dashboard deep link
          (?status=COMPLETED) still lands here, where by definition
          almost nothing with that status lives, so rather than read as
          "there is nothing" the page says how many requests have
          started work and offers the one click to Chargeable work.
          Existing keys only: `list.track_switch_to` with the sidebar's
          own `nav.chargeable_work` as the destination name. */}
      {!loading && visibleRows.length === 0 && !error && (
        <EmptyState
          icon={Sparkles}
          title={
            quoteRows.length === 0
              ? t("list.empty_state")
              : t("list.empty_filtered_title")
          }
          description={
            quoteRows.length === 0 ? undefined : t("list.empty_filtered_desc")
          }
          action={
            startedElsewhereCount > 0 ? (
              <Link
                to="/tickets/chargeable"
                className="btn btn-secondary btn-sm"
                data-testid="extra-work-track-switch"
              >
                {t("list.track_switch_to", {
                  count: startedElsewhereCount,
                  track: t("nav.chargeable_work", { ns: "common" }),
                })}
              </Link>
            ) : undefined
          }
          testId="extra-work-list-empty"
        />
      )}

      {visibleRows.length > 0 && (
        <div className="ew-list-edit-bar">
          {/* W2-C — where the "Totale waarde" KPI card went.
              It is the same arithmetic it always was (every loaded
              request except the cancelled ones, through `rowAmounts`),
              moved off the card row and onto the list it describes, and
              said in words rather than in a box: beside the money strip
              it read as a fifth figure of the same kind, and it is not
              one — the strip's four are server aggregates over precise
              populations, this is the sum of what this page loaded.

              The row it now shares was provider-only because the edit
              toggle inside it is. The row is rendered for everyone now
              and the toggle keeps its own gate, so a customer does not
              lose a number they could read before. */}
          <p
            className="ew-list-total muted small"
            data-testid="extra-work-list-total"
          >
            {t("list.total_value_label")}{" "}
            <strong>{formatMoney(listTotalValue)}</strong>{" "}
            <span className="ew-list-total-meta">
              {t("list.total_value_meta")}
            </span>
          </p>
          {isProvider && edit.editMode && (
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
                // W3-F — the bulk half of the planning layer.
                {
                  key: "plan",
                  label: t("plan.bulk_button"),
                  onClick: () => {
                    setPlanError("");
                    setPlanOpen(true);
                  },
                },
              ]}
              testIdPrefix="extra-work-bulk"
            />
          )}
          {isProvider && (
            <EditModeToggle
              editMode={edit.editMode}
              onToggle={edit.toggleMode}
              disabled={assignBusy}
              testId="extra-work-edit-mode-toggle"
            />
          )}
        </div>
      )}

      {visibleRows.length > 0 && (
        <div className="responsive-table-wrap">
          {/* W24-FX1 §1d — was `overflow: "hidden"`. Nine columns do not
              fit the 1110px this page gets at 1366, and `.responsive-
              table-wrap` declares no overflow of its own, so this card
              was the only thing deciding what happened to the rest — and
              it decided to cut it off. Measured: the table ran 64px past
              the card, taking the Deadline column with it, with no
              scrollbar and nothing on screen to say so. `overflowX:
              "auto"` is what the Facturen list card already does. */}
          <div className="card" style={{ overflowX: "auto" }}>
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
                  {/* W-NAV1.2 — the ticket / billing / billed-to columns
                      are gone with the Work started track. They only
                      make sense once work has actually started, and a
                      row with started work is not on this page. */}
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
                {foldSeries(visibleRows).map((entry) => {
                  if (entry.kind === "row") return renderRow(entry.row);
                  const open = expandedSeries.includes(entry.group.id);
                  return (
                    <Fragment key={`series-${entry.group.id}`}>
                      <SeriesHeaderRow
                        group={entry.group}
                        onThisPage={entry.rows.length}
                        columns={99}
                        open={open}
                        onToggle={() =>
                          setExpandedSeries((prev) =>
                            prev.includes(entry.group.id)
                              ? prev.filter((id) => id !== entry.group.id)
                              : [...prev, entry.group.id],
                          )
                        }
                      />
                      {open && entry.rows.map((row) => renderRow(row, true))}
                    </Fragment>
                  );
                })}
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
                      {/* Sprint 181 §1 — the card carries the same one
                          status the table row does, from the same
                          authority. */}
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
                      <dd>
                        {isPriced(row) ? (
                          formatMoney(rowAmounts(row).total)
                        ) : (
                          <span className="muted-empty">&mdash;</span>
                        )}
                      </dd>
                    </div>
                    {/* W-NAV1.2 — the mobile card carries exactly the
                        columns the table carries; the ticket / billed-to
                        / billing rows left with the Work started track. */}
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
