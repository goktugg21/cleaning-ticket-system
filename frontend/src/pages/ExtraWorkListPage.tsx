// Sprint 26C — Extra Work list page.
// Sprint 28 Batch 6 — translated through the `extra_work` i18n namespace.
// P-8R A1 — every row the server returns is on this page; the guard line.
// P-9 B — FOUR TABS. The list answers "where is my work?" the way the
//   People page does: a `.customer-tabs` strip backed by the address
//   (`/extra-work/<tab>`), one plain sentence per tab saying what the tab
//   is for and what happens next, ONE money line, at most six columns
//   with the row's one next step at the end, and the seven filter
//   dropdowns folded behind one Filter button. The tab table lives in
//   `lib/extraWorkTabs.ts` (exhaustive over `display_phase`), the next
//   step in `components/extra-work/nextStep.ts` (the detail page's own
//   source). Cancelled is not a tab: it is a link at the foot of
//   Finished, and the P-8 guard still adds up over it.
// P-10 B1/B2 — the chips say the ticket's own status words (the table
//   in `lib/extraWorkTabs.ts`), each tab opens on the chip with work to
//   do (`DEFAULT_CHIP`), and the chosen chip rides in the address
//   (`?chip=<key>`) so a reload lands where the person was.
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Link,
  Navigate,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import { PlusCircle, Search, SlidersHorizontal, Sparkles } from "lucide-react";
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
  ExtraWorkBulkPlanItem,
  ExtraWorkRequestIntent,
  ExtraWorkRequestList,
} from "../api/types";
import { getApiError } from "../api/client";
import { describeExtraWorkRefusal } from "../lib/extraWorkRefusal";
import { useAuth } from "../auth/AuthContext";
import { isProviderManagementRole } from "../auth/permissions";
import { ChoiceDialog } from "../components/ChoiceDialog";
import { EditModeToggle } from "../components/EditModeToggle";
import { BulkPlanDialog } from "../components/extra-work/BulkPlanDialog";
import { listNextStep } from "../components/extra-work/nextStep";
import { MultiSelectToolbar } from "../components/MultiSelectToolbar";
import { AssignPeopleDialog } from "../components/AssignPeopleDialog";
import { useEditMode } from "../lib/useEditMode";
import { ClickableRow } from "../components/ClickableRow";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { PhaseBadge } from "../components/customer/PhaseBadge";
import { SeriesHeaderRow } from "../components/extra-work/SeriesHeaderRow";
import { foldSeries } from "../lib/extraWorkSeries";
import { isPriced, rowAmounts } from "../lib/billing";
import { formatDate, formatMoney, formatNumber } from "../lib/intl";
import { customerLabelName } from "../lib/customerLabelName";
import {
  ALL_CHIP,
  CANCELLED_VIEW,
  DEFAULT_CHIP,
  EXTRA_WORK_TABS,
  SUB_CHIPS,
  TAB_LABEL_KEY,
  TAB_PURPOSE_KEY,
  bucketOf,
  chipFromParam,
  daysSince,
  deepLinkTarget,
  firstTabWithRows,
  isExtraWorkTab,
  startsWhenPriced,
  subChipMatches,
  todayIso,
} from "../lib/extraWorkTabs";
import type {
  DeepLinkTarget,
  ExtraWorkBucket,
  ExtraWorkTab,
} from "../lib/extraWorkTabs";

/** Sprint 180 §1(b) — a CUSTOMER_APPROVED request with zero operational
 *  tickets. The spawn is synchronous with approval, so zero tickets
 *  means the spawn FAILED. The detail page has the retry button;
 *  silence here is how that work gets lost. */
function isSpawnAnomaly(row: ExtraWorkRequestList): boolean {
  return row.status === "CUSTOMER_APPROVED" && !row.has_operational_ticket;
}

/** Asked more than this many days ago and still unpriced reads red. */
const AGE_WARN_DAYS = 5;

type CategoryFilter = string;

/** The columns of one tab, in render order. Page-local: nothing else
 *  renders these tables. The next step is always the last column. */
type ColumnKey =
  | "what"
  | "where"
  | "asked"
  | "after_pricing"
  | "estimate"
  | "sent"
  | "price"
  | "status"
  | "planned"
  | "people"
  | "finished"
  | "amount"
  | "invoice"
  | "next";

const COLUMNS: Readonly<Record<ExtraWorkBucket, ReadonlyArray<ColumnKey>>> = {
  "to-price": ["what", "where", "asked", "after_pricing", "estimate", "next"],
  "with-customer": ["what", "where", "sent", "price", "status", "next"],
  approved: ["what", "where", "planned", "people", "status", "next"],
  finished: ["what", "where", "finished", "amount", "invoice", "next"],
  cancelled: ["what", "where", "asked", "status", "next"],
};

const COLUMN_LABEL_KEY: Readonly<Record<ColumnKey, string>> = {
  what: "list.column_what",
  where: "list.column_where",
  asked: "list.column_asked",
  after_pricing: "list.column_after_pricing",
  estimate: "list.column_estimate",
  sent: "list.column_sent",
  price: "list.column_price",
  status: "list.column_status",
  planned: "list.column_planned",
  people: "list.column_people",
  finished: "list.column_finished",
  amount: "list.column_amount",
  invoice: "list.column_invoice",
  next: "list.column_next",
};

const RIGHT_ALIGNED: ReadonlySet<ColumnKey> = new Set(["estimate", "price", "amount"]);

/** Sprint 176 §3 — set the deadline and/or the planned end on a selection.
 *
 *  Every field starts blank meaning "leave unchanged", exactly like every
 *  other bulk field in the app, and a blank field is OMITTED from the
 *  payload rather than sent as null — the server reads key presence, so
 *  an omitted key leaves the stored date alone. This dialog can SET a
 *  date but not CLEAR one; clearing is per-request work on the detail
 *  page. */
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
    // Same overlay idiom as `AssignPeopleDialog` — an inline positioned
    // backdrop plus a `card`, NOT a native <dialog> (CLAUDE.md records
    // why the imperative ones are trouble when mounted conditionally).
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
 *   from the sidebar        no customer fixed, the customer filter is
 *                           offered, the tab is in the PATH
 *                           (`/extra-work/<tab>`);
 *   from inside a customer  the customer is fixed and its filter is not
 *                           offered; the tab lives in `?tab=`, because
 *                           the customer page owns the path.
 *
 * Fixing the customer is a UI convenience and nothing more: the SERVER
 * still decides what the actor may see.
 */
export function ExtraWorkList({
  customerId,
  hideHeader = false,
  tab,
}: {
  customerId?: number;
  /** The customer page draws its own header, so this one is suppressed
   *  rather than stacked under it. */
  hideHeader?: boolean;
  /** The tab the route names (`/extra-work/<tab>`). Undefined on the
   *  bare `/extra-work`, which lands on the first tab that has rows. */
  tab?: ExtraWorkTab;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const { me } = useAuth();
  // Read-only: every tab, chip-carrying redirect and view change is a
  // <Link>, so the address stays the one source and Back works.
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const isProvider = isProviderManagementRole(me?.role);
  const embedded = customerId !== undefined;
  const today = todayIso();

  // The deep links this address still honours, read once at mount:
  // `?status=<ExtraWorkStatus|phase>` (dashboard widgets, RF-18) lands
  // on the tab that holds it and preselects the matching chip;
  // `?filter=quote_requests` (the customer page's Quotes shortcut) is
  // the To price tab. P-10 B2 — the chip a deep link preselects is
  // WRITTEN to the address (`?chip=`) by the redirect below, so nothing
  // rides in `location.state` any more.
  const [deepLink] = useState<DeepLinkTarget | null>(() => {
    const byStatus = deepLinkTarget(searchParams.get("status"));
    if (byStatus) return byStatus;
    if (searchParams.get("filter") === "quote_requests") {
      return { bucket: "to-price", chip: null };
    }
    return null;
  });

  const viewCancelled = searchParams.get("view") === CANCELLED_VIEW;
  const urlTab = embedded ? searchParams.get("tab") : tab;
  const namedTab: ExtraWorkTab | null = isExtraWorkTab(urlTab) ? urlTab : null;

  // Sprint 155 §1b — the create button asks which of the three.
  const [chooserOpen, setChooserOpen] = useState(false);
  // Sprint 157 §2 / W3-F / Sprint 176 §3 — the three bulk actions,
  // behind the Sprint 155 §4 edit gate like every other list.
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignBusy, setAssignBusy] = useState(false);
  const [assignError, setAssignError] = useState("");
  const [planOpen, setPlanOpen] = useState(false);
  const [planBusy, setPlanBusy] = useState(false);
  const [planError, setPlanError] = useState("");
  const [datesOpen, setDatesOpen] = useState(false);
  const [datesBusy, setDatesBusy] = useState(false);
  const [datesError, setDatesError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [assignCandidates, setAssignCandidates] = useState<
    Record<ExtraWorkAssignmentRole, AssignmentCandidate[]>
  >({ WORKER: [], MANAGER: [] });
  const [rows, setRows] = useState<ExtraWorkRequestList[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Each tab remembers its own sub-chip, so switching tabs and back
  // does not lose a narrowing and a chip of one tab never narrows
  // another. The address (`?chip=`) is the source for the tab on
  // screen; this is the memory the tab links carry along. No entry
  // means the tab's default chip (P-10 B2).
  const [chipByTab, setChipByTab] = useState<Partial<Record<ExtraWorkBucket, string>>>(
    () => (deepLink?.chip ? { [deepLink.bucket]: deepLink.chip } : {}),
  );

  // The Filter fold. The four cascade filters and the category are
  // SERVER-side (they compose in `ExtraWorkRequestFilter`); planned and
  // search narrow the loaded rows on the client.
  const [searchInput, setSearchInput] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>("");
  const [categoryOptions, setCategoryOptions] =
    useState<ExtraWorkCategoryOptions>({ live: [], historical: [] });
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
  const [customerScoped, setCustomerScoped] = useState<{
    customerId: number;
    buildings: CustomerBuildingMembership[];
    departments: CustomerLabel[];
    workTypes: CustomerLabel[];
  } | null>(null);

  // M6.3 — the "my work" deep-link reads. Read as VALUES so a `?tab=`
  // or `?view=` change in embedded mode does not refetch the list.
  const mineParam = searchParams.get("mine") === "1";
  const intentParam =
    (searchParams.get("request_intent") as ExtraWorkRequestIntent | null) ??
    undefined;

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const allRows = await listAllExtraWork({
          created_by: mineParam && me?.id ? me.id : undefined,
          request_intent: intentParam,
          customer: customerFilter ? Number(customerFilter) : undefined,
          building: buildingFilter ? Number(buildingFilter) : undefined,
          department: departmentFilter ? Number(departmentFilter) : undefined,
          work_type: workTypeFilter ? Number(workTypeFilter) : undefined,
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
    mineParam,
    intentParam,
    me?.id,
    customerFilter,
    buildingFilter,
    departmentFilter,
    workTypeFilter,
    categoryFilter,
    reloadKey,
  ]);

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

  // Sprint 128 — LOAD-ONLY effect: the chosen customer's buildings and
  // labels. The dependent filters are cleared in the <select>'s
  // onChange, never here (CLAUDE.md: no setState in an effect body).
  useEffect(() => {
    const chosen = customerFilter ? Number(customerFilter) : null;
    if (!chosen) return;
    let cancelled = false;
    Promise.all([
      listCustomerBuildings(chosen),
      listLabels(chosen, "department", { is_active: true }),
      listLabels(chosen, "work_type", { is_active: true }),
    ])
      .then(([buildingsRes, departments, workTypes]) => {
        if (!cancelled) {
          setCustomerScoped({
            customerId: chosen,
            buildings: buildingsRes.results,
            departments,
            workTypes,
          });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setCustomerScoped({
            customerId: chosen,
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

  // ---- bucketing -------------------------------------------------------
  // Every row is bucketed ONCE by `display_phase` through the exhaustive
  // tab table. `unmatched` is only reachable when the server sends a
  // phase this build's union does not have; it is counted, never
  // dropped, and the guard under the table goes red over it.
  const { counts, unmatchedCount } = useMemo(() => {
    const tally: Record<ExtraWorkBucket, number> = {
      "to-price": 0,
      "with-customer": 0,
      approved: 0,
      finished: 0,
      cancelled: 0,
    };
    let unmatched = 0;
    for (const row of rows) {
      const bucket = bucketOf(row);
      if (bucket === null) unmatched += 1;
      else tally[bucket] += 1;
    }
    return { counts: tally, unmatchedCount: unmatched };
  }, [rows]);
  const countedTotal =
    EXTRA_WORK_TABS.reduce((sum, key) => sum + counts[key], 0) +
    counts.cancelled +
    unmatchedCount;

  // The tab on screen. Path mode without a tab is AUTO mode and redirects
  // below; embedded mode without `?tab=` simply shows the first tab that
  // has rows (the deep link wins when there is one).
  const autoTab: ExtraWorkTab = (() => {
    if (deepLink && deepLink.bucket !== CANCELLED_VIEW) return deepLink.bucket;
    return firstTabWithRows(counts);
  })();
  const activeTab: ExtraWorkTab = namedTab ?? autoTab;
  const activeBucket: ExtraWorkBucket = viewCancelled ? CANCELLED_VIEW : activeTab;
  // P-10 B2 — the address names the chip; a missing or unknown `?chip=`
  // falls back to what this tab remembers, then to the tab's default
  // (the chip with work to do). "All" is one click away on every tab.
  const urlChip = viewCancelled ? null : chipFromParam(activeTab, searchParams.get("chip"));
  const chipKey = urlChip ?? chipByTab[activeBucket] ?? DEFAULT_CHIP[activeTab];
  const chips = viewCancelled ? [] : SUB_CHIPS[activeTab];
  const activeChip = chips.find((chip) => chip.key === chipKey) ?? ALL_CHIP;

  // Plain derivations, deliberately not `useMemo`: the React-compiler
  // lint (`preserve-manual-memoization`) could not keep a manual memo
  // over `activeBucket` / `activeChip`, and a filter over a few hundred
  // rows costs nothing per render.
  const tabRows = rows.filter((row) => bucketOf(row) === activeBucket);

  const needle = searchInput.trim().toLowerCase();
  const visibleRows = tabRows.filter((row) => {
    if (!subChipMatches(activeChip, row)) return false;
    if (plannedFilter !== "ALL") {
      const planned = Boolean(row.provider_planned_date);
      if (plannedFilter === "PLANNED" ? !planned : planned) return false;
    }
    if (needle) {
      const hay = `${row.title} ${row.building_name ?? ""} ${
        row.customer_name ?? ""
      }`.toLowerCase();
      if (!hay.includes(needle)) return false;
    }
    return true;
  });

  // ---- money line ------------------------------------------------------
  // ONE line per tab, from the loaded rows of that tab, through
  // `rowAmounts` — the one billing-total rule. Nothing else about money
  // above the table.
  const moneyLine = ((): string | null => {
    const sum = (subset: ExtraWorkRequestList[]) =>
      subset.reduce((total, row) => total + rowAmounts(row).total, 0);
    switch (activeBucket) {
      case "to-price":
        return t("tabs.money_to_price", { count: tabRows.length });
      case "with-customer":
        return t("tabs.money_with_customer", {
          sent: formatMoney(sum(tabRows.filter((row) => row.display_phase !== "REJECTED"))),
          declined: formatMoney(sum(tabRows.filter((row) => row.display_phase === "REJECTED"))),
        });
      case "approved":
        return t("tabs.money_approved", { amount: formatMoney(sum(tabRows)) });
      case "finished":
        return t("tabs.money_finished", {
          amount: formatMoney(sum(tabRows)),
          open: formatMoney(sum(tabRows.filter((row) => row.display_phase === "DONE"))),
        });
      case "cancelled":
        return null;
    }
  })();

  // ---- edit gate + bulk actions ------------------------------------------
  const edit = useEditMode(visibleRows.map((row) => row.id));

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
      setReloadKey((key) => key + 1);
    } catch (err) {
      setAssignError(getApiError(err));
    } finally {
      setAssignBusy(false);
    }
  }

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

  async function runBulkPlan(items: ExtraWorkBulkPlanItem[]) {
    setPlanBusy(true);
    setPlanError("");
    try {
      await bulkPlanExtraWork({ items });
      setPlanOpen(false);
      edit.exit();
      setReloadKey((key) => key + 1);
    } catch (err) {
      // P-8R A3 — the coded sentence, at the dialog's own error line.
      setPlanError(describeExtraWorkRefusal(err, t).sentence);
    } finally {
      setPlanBusy(false);
    }
  }

  // ---- navigation helpers ------------------------------------------------
  /** The search string a tab link keeps: the "my work" reads survive,
   *  the one-shot deep-link params, the chip and the cancelled view do
   *  not (a tab link names its own chip through `linkTo`). */
  const keptSearch = (extra?: Record<string, string>): string => {
    const params = new URLSearchParams(searchParams);
    for (const key of ["status", "filter", "view", "tab", "chip"]) params.delete(key);
    if (extra) for (const [key, value] of Object.entries(extra)) params.set(key, value);
    const text = params.toString();
    return text ? `?${text}` : "";
  };
  /** P-10 B2 — `chip` undefined carries the chip `target` remembers (a
   *  deep link's, or one chosen earlier this visit); a key writes that
   *  chip; the cancelled view never carries one. No chip in the
   *  address means the tab's default. */
  const linkTo = (
    target: ExtraWorkTab,
    view?: typeof CANCELLED_VIEW,
    chip?: string,
  ): string => {
    const extra: Record<string, string> = {};
    if (embedded) extra.tab = target;
    if (view) extra.view = view;
    const carried = chip ?? chipByTab[target];
    if (carried && !view) extra.chip = carried;
    return embedded
      ? `${location.pathname}${keptSearch(extra)}`
      : `/extra-work/${target}${keptSearch(extra)}`;
  };

  const [expandedSeries, setExpandedSeries] = useState<number[]>([]);

  // AUTO MODE — the bare `/extra-work`: once the rows are in, go to the
  // first tab that has any (or the deep link's tab), else To price. The
  // deep link's chip is written to the address; its params are dropped.
  if (!embedded && namedTab === null && !loading && !error) {
    const target =
      deepLink?.bucket === CANCELLED_VIEW
        ? linkTo("finished", CANCELLED_VIEW)
        : linkTo(autoTab);
    return <Navigate to={target} replace />;
  }
  // A named tab reached with a one-shot deep-link param: rewrite the
  // address once so the chip it preselects is the one the address
  // says (P-10 B2), and the params do not survive into every tab link.
  if (!embedded && namedTab !== null && (searchParams.has("status") || searchParams.has("filter"))) {
    return <Navigate to={linkTo(namedTab, viewCancelled ? CANCELLED_VIEW : undefined)} replace />;
  }

  // ---- cells ---------------------------------------------------------------
  const dash = (title?: string) => (
    <span className="muted-empty" title={title}>
      &mdash;
    </span>
  );
  const money = (row: ExtraWorkRequestList) =>
    isPriced(row) ? formatMoney(rowAmounts(row).total) : dash(t("list.total_not_priced_hint"));

  const lineSummary = (row: ExtraWorkRequestList): string => {
    const lines = row.line_summary;
    if (!lines || lines.count === 0) return t("list.lines_none");
    const more = lines.count - lines.names.length;
    return more > 0
      ? `${lines.names.join(", ")} ${t("list.lines_more", { count: more })}`
      : lines.names.join(", ");
  };

  const cellWhat = (row: ExtraWorkRequestList, sub: ReactNode) => (
    <td className="td-subject" key="what">
      <Link to={`/extra-work/${row.id}`}>{row.title}</Link>
      <div className="muted small ew-cell-sub">{sub}</div>
    </td>
  );

  const cellAsked = (row: ExtraWorkRequestList) => {
    const age = daysSince(row.requested_at, today);
    const stale = age !== null && age > AGE_WARN_DAYS;
    return (
      <td key="asked" className="td-date">
        {formatDate(row.requested_at)}
        <div className={`small ew-cell-sub${stale ? " ew-late" : " muted"}`}>
          {age === null
            ? null
            : age <= 0
              ? t("list.age_today")
              : t("list.age_days", { count: age })}
        </div>
      </td>
    );
  };

  const cellPlanned = (row: ExtraWorkRequestList) => {
    const plannedDay =
      row.provider_planned_date ?? row.spawned_tickets[0]?.scheduled_start_at ?? null;
    if (plannedDay) {
      const passed = daysSince(plannedDay, today) ?? 0;
      const notStarted =
        row.display_phase === "WAITING_PLANNING" || row.display_phase === "SCHEDULED";
      const hours = row.budget_hours ? Number.parseFloat(row.budget_hours) : 0;
      return (
        <td key="planned" className="td-date">
          {formatDate(plannedDay)}
          {hours > 0 && (
            <span className="muted">
              {" · "}
              {t("list.planned_hours", {
                hours: formatNumber(hours, { maximumFractionDigits: 2 }),
              })}
            </span>
          )}
          {passed > 0 && notStarted && (
            <div className="small ew-cell-sub ew-late">
              {t("list.days_late", { count: passed })}
            </div>
          )}
        </td>
      );
    }
    if (row.deadline) {
      const left = -(daysSince(row.deadline, today) ?? 0);
      return (
        <td key="planned" className="td-date">
          <span className="muted">{t("list.not_planned")}</span>
          <div className={`small ew-cell-sub${row.is_overdue ? " ew-late" : " muted"}`}>
            {row.is_overdue
              ? t("list.days_late", { count: Math.max(1, -left) })
              : left <= 0
                ? t("list.deadline_today")
                : t("list.deadline_in", { count: left })}
          </div>
        </td>
      );
    }
    return (
      <td key="planned" className="td-date">
        <span className="muted">{t("list.not_planned")}</span>
      </td>
    );
  };

  const cellStatus = (row: ExtraWorkRequestList) => {
    if (row.display_phase === "REJECTED") {
      return (
        <td key="status">
          <PhaseBadge kind="ew" phase={row.display_phase} testId="extra-work-row-phase" />
          <div className="muted small ew-cell-sub ew-reason" title={row.rejection_note || undefined}>
            {row.rejection_note || t("list.declined_no_reason")}
          </div>
        </td>
      );
    }
    if (
      row.display_phase === "WAITING_CUSTOMER_APPROVAL" ||
      row.display_phase === "WAITING_YOUR_APPROVAL"
    ) {
      const waited = daysSince(row.pricing_proposed_at, today);
      return (
        <td key="status">
          {waited === null ? (
            <PhaseBadge kind="ew" phase={row.display_phase} testId="extra-work-row-phase" />
          ) : (
            <span className={waited >= 3 ? "ew-warn" : undefined} data-testid="extra-work-row-phase">
              {waited <= 0
                ? t("list.waiting_since_today")
                : t("list.waiting_days", { count: waited })}
            </span>
          )}
        </td>
      );
    }
    return (
      <td key="status">
        <PhaseBadge kind="ew" phase={row.display_phase} testId="extra-work-row-phase" />
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
    );
  };

  const cellInvoice = (row: ExtraWorkRequestList) => {
    if (row.is_invoiced) {
      const ref = row.invoice_ref ?? null;
      return (
        <td key="invoice">
          {ref?.number
            ? t("list.on_invoice", { number: ref.number })
            : t("list.on_invoice_concept")}
          {ref?.sent_at && (
            <div className="muted small ew-cell-sub">
              {t("list.invoice_sent_on", { date: formatDate(ref.sent_at) })}
            </div>
          )}
        </td>
      );
    }
    const day = row.customer_invoice_day;
    return (
      <td key="invoice">
        {t("list.not_invoiced_yet")}
        {day !== null && day !== undefined && (
          <div className="muted small ew-cell-sub">
            {day === "LAST_OF_MONTH"
              ? t("list.bills_month_end")
              : t("list.bills_on_day", { day })}
          </div>
        )}
      </td>
    );
  };

  const cellNext = (row: ExtraWorkRequestList) => {
    const step = listNextStep(row, { isProvider, today });
    return (
      <td key="next" className="td-next">
        {step.buttonKey && (
          <Link
            to={step.to}
            className={`btn btn-sm ${step.tone === "primary" ? "btn-primary" : "btn-secondary"}`}
            data-testid="extra-work-next-step"
          >
            {t(step.buttonKey)}
          </Link>
        )}
      </td>
    );
  };

  const cellFor = (column: ColumnKey, row: ExtraWorkRequestList): ReactNode => {
    switch (column) {
      case "what":
        return cellWhat(
          row,
          activeBucket === "approved" ? (
            <>
              {money(row)}
              {row.customer_decided_at && (
                <>
                  {" · "}
                  {t("list.approved_on", { date: formatDate(row.customer_decided_at) })}
                </>
              )}
            </>
          ) : (
            lineSummary(row)
          ),
        );
      case "where":
        return (
          <td key="where">
            {row.building_name}
            <div className="muted small ew-cell-sub">{row.customer_name}</div>
          </td>
        );
      case "asked":
        return cellAsked(row);
      case "after_pricing":
        return (
          <td key="after_pricing">
            {startsWhenPriced(row)
              ? t("list.after_pricing_starts")
              : t("list.after_pricing_to_customer")}
          </td>
        );
      case "estimate":
        return (
          <td key="estimate" style={{ textAlign: "right" }}>
            {row.contract_estimate_amount != null
              ? formatMoney(row.contract_estimate_amount)
              : dash(t("list.estimate_all_custom"))}
          </td>
        );
      case "sent":
        return (
          <td key="sent" className="td-date">
            {row.pricing_proposed_at ? formatDate(row.pricing_proposed_at) : dash()}
            <div className="muted small ew-cell-sub">{row.contact_name || "—"}</div>
          </td>
        );
      case "price":
      case "amount":
        return (
          <td key={column} style={{ textAlign: "right" }}>
            {money(row)}
          </td>
        );
      case "status":
        return cellStatus(row);
      case "planned":
        return cellPlanned(row);
      case "people":
        return (
          <td key="people">
            {row.people_names && row.people_names.length > 0 ? (
              row.people_names.join(", ")
            ) : (
              <span className="muted">{t("list.nobody_yet")}</span>
            )}
          </td>
        );
      case "finished":
        return (
          <td key="finished" className="td-date">
            {row.completed_at ? formatDate(row.completed_at) : dash()}
          </td>
        );
      case "invoice":
        return cellInvoice(row);
      case "next":
        return cellNext(row);
    }
  };

  const columns = COLUMNS[activeBucket];

  function renderRow(row: ExtraWorkRequestList, inSeries = false) {
    return (
      <ClickableRow
        key={row.id}
        className={inSeries ? "ew-series-member" : undefined}
        to={`/extra-work/${row.id}`}
        testId="extra-work-row"
      >
        {edit.editMode && (
          <td className="td-select" onClick={(event) => event.stopPropagation()}>
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
        {columns.map((column) => cellFor(column, row))}
      </ClickableRow>
    );
  }

  // ---- filter fold summary ---------------------------------------------------
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
  const activeFilterLabels: string[] = [];
  if (!embedded && customerChosen) {
    activeFilterLabels.push(
      customers.find((c) => String(c.id) === customerFilter)?.name ?? t("list.filter_customer"),
    );
  }
  if (buildingFilter) {
    activeFilterLabels.push(
      scopedBuildings.find((b) => String(b.building_id) === buildingFilter)?.building_name ??
        t("list.filter_building"),
    );
  }
  if (departmentFilter) {
    const label = scopedDepartments.find((d) => String(d.id) === departmentFilter);
    activeFilterLabels.push(label ? customerLabelName(label.name, t) : t("list.filter_department"));
  }
  if (workTypeFilter) {
    const label = scopedWorkTypes.find((w) => String(w.id) === workTypeFilter);
    activeFilterLabels.push(label ? customerLabelName(label.name, t) : t("list.filter_work_type"));
  }
  if (categoryFilter) activeFilterLabels.push(categoryFilter);
  if (plannedFilter !== "ALL") {
    activeFilterLabels.push(
      plannedFilter === "PLANNED" ? t("list.planned_only") : t("list.planned_none"),
    );
  }
  if (searchInput.trim()) activeFilterLabels.push(searchInput.trim());

  const showTable = !loading && !error && visibleRows.length > 0;

  return (
    <div data-testid="extra-work-list-page">
      {!hideHeader && (
        <PageHeader
          backLink={{ to: "/", label: t("back_to_dashboard") }}
          eyebrow={t("common:ops")}
          title={t("nav.meerwerk", { ns: "common" })}
          actions={
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
              key: "recurring",
              label: t("list.create_chooser_recurring"),
              description: t("list.create_chooser_recurring_desc"),
              onSelect: () => navigate("/planned-work/new"),
            },
          ]}
        />
      )}

      {/* The tab strip: the People page's `.customer-tabs`, one count
          per tab. In path mode the tab IS the address. */}
      <div
        className="customer-tabs ew-tabs"
        role="tablist"
        aria-label={t("nav.meerwerk", { ns: "common" })}
        data-testid="extra-work-tabs"
      >
        {EXTRA_WORK_TABS.map((key) => {
          const active = !viewCancelled && key === activeTab;
          return (
            <Link
              key={key}
              to={linkTo(key)}
              role="tab"
              aria-selected={active}
              className={`customer-tab${active ? " active" : ""}`}
              data-testid={`extra-work-tab-${key}`}
              data-count={counts[key]}
            >
              {t(TAB_LABEL_KEY[key])}
              <span className="ew-tab-count" data-testid={`extra-work-tab-count-${key}`}>
                {loading ? "…" : counts[key]}
              </span>
            </Link>
          );
        })}
      </div>

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

      {!loading && !error && (
        <>
          {/* What this tab is for, and the one money line. */}
          <div className="ew-tab-head" data-testid="extra-work-tab-head">
            {viewCancelled ? (
              <>
                <div className="ew-tab-title" data-testid="extra-work-cancelled-title">
                  {t("tabs.cancelled_title")}{" "}
                  <span className="muted">({counts.cancelled})</span>
                </div>
                <p className="section-head-sub ew-tab-purpose" data-testid="extra-work-tab-purpose">
                  {t("tabs.cancelled_purpose")}
                </p>
                <Link
                  to={linkTo("finished")}
                  className="btn btn-secondary btn-sm"
                  data-testid="extra-work-back-to-finished"
                >
                  {t("tabs.back_to_finished")}
                </Link>
              </>
            ) : (
              <>
                <p className="section-head-sub ew-tab-purpose" data-testid="extra-work-tab-purpose">
                  {t(TAB_PURPOSE_KEY[activeTab])}
                </p>
                {moneyLine && (
                  <p className="ew-tab-money" data-testid="extra-work-tab-money">
                    {moneyLine}
                  </p>
                )}
              </>
            )}
          </div>

          {/* Sub-chips, the Filter fold and the edit gate share one band. */}
          <div className="ew-tab-band">
            {chips.length > 0 && (
              <div
                className="composer-toggle ew-subtabs"
                role="tablist"
                aria-label={t(TAB_LABEL_KEY[activeTab])}
                data-testid="extra-work-subchips"
              >
                {chips.map((chip) => {
                  const count = tabRows.filter((row) => subChipMatches(chip, row)).length;
                  const active = chip.key === activeChip.key;
                  return (
                    <button
                      key={chip.key}
                      type="button"
                      role="tab"
                      aria-selected={active}
                      className={`composer-toggle-btn${active ? " active" : ""}`}
                      onClick={() => {
                        // P-10 B2 — remembered for the tab links, and
                        // written to the address (replace: a chip is a
                        // narrowing of this tab, not a place of its own)
                        // so a reload lands on the same chip.
                        setChipByTab((prev) => ({ ...prev, [activeBucket]: chip.key }));
                        navigate(linkTo(activeTab, undefined, chip.key), { replace: true });
                      }}
                      data-testid={`extra-work-chip-${chip.key}`}
                      data-count={count}
                    >
                      {t(chip.labelKey)}
                      <span className="ew-chip-count">{count}</span>
                    </button>
                  );
                })}
              </div>
            )}
            <div className="ew-tab-band-right">
              {isProvider && (
                <EditModeToggle
                  editMode={edit.editMode}
                  onToggle={edit.toggleMode}
                  disabled={assignBusy}
                  testId="extra-work-edit-mode-toggle"
                />
              )}
            </div>
          </div>

          <details
            className="filter-fold ew-filter-fold"
            open={activeFilterLabels.length > 0}
            data-testid="extra-work-filter-fold"
          >
            <summary className="filter-fold-summary" data-testid="extra-work-filter-toggle">
              <SlidersHorizontal size={14} strokeWidth={2.4} aria-hidden="true" />
              {t("list.filter_fold_label")}
              {activeFilterLabels.length > 0 && (
                <span className="filter-fold-count">
                  {t("list.filter_fold_active", { count: activeFilterLabels.length })}
                </span>
              )}
              {activeFilterLabels.map((label) => (
                <span className="filter-fold-chip" key={label}>
                  {label}
                </span>
              ))}
            </summary>
            <div className="filter-fold-body ew-list-filters" data-testid="extra-work-list-filters">
              {isProvider && !embedded && (
                <>
                  <div className="filter-field">
                    <span className="filter-label">{t("list.filter_customer")}</span>
                    <select
                      className="filter-control"
                      value={customerFilter}
                      onChange={(event) => {
                        // Clear the dependent filters here, in the handler.
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
                      title={customerChosen ? undefined : t("list.filter_pick_customer_hint")}
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
                    <span className="filter-label">{t("list.filter_department")}</span>
                    <select
                      className="filter-control"
                      value={departmentFilter}
                      onChange={(event) => setDepartmentFilter(event.target.value)}
                      disabled={!customerChosen}
                      title={customerChosen ? undefined : t("list.filter_pick_customer_hint")}
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
                    <span className="filter-label">{t("list.filter_work_type")}</span>
                    <select
                      className="filter-control"
                      value={workTypeFilter}
                      onChange={(event) => setWorkTypeFilter(event.target.value)}
                      disabled={!customerChosen}
                      title={customerChosen ? undefined : t("list.filter_pick_customer_hint")}
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
                </>
              )}
              <div className="filter-field">
                <span className="filter-label">{t("list.filter_catalog_category")}</span>
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
                    setPlannedFilter(event.target.value as "ALL" | "PLANNED" | "UNPLANNED")
                  }
                  data-testid="extra-work-list-filter-planned"
                >
                  <option value="ALL">{t("list.planned_all")}</option>
                  <option value="PLANNED">{t("list.planned_only")}</option>
                  <option value="UNPLANNED">{t("list.planned_none")}</option>
                </select>
              </div>
              <div className="filter-field search">
                <Search size={14} strokeWidth={2.2} />
                <input
                  className="filter-control"
                  type="search"
                  placeholder={t("list.search_placeholder")}
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                  data-testid="extra-work-list-search"
                />
              </div>
              {isProvider && !embedded && !customerChosen && (
                <div
                  className="ew-list-filters-hint muted small"
                  data-testid="extra-work-list-filter-hint"
                >
                  {t("list.filter_pick_customer_hint")}
                </div>
              )}
            </div>
          </details>

          {isProvider && edit.editMode && visibleRows.length > 0 && (
            <div className="ew-list-edit-bar">
              <MultiSelectToolbar
                selectedCount={edit.selection.length}
                onSelectAll={edit.selectAll}
                onClearAll={edit.clear}
                disabled={assignBusy}
                actions={[
                  { key: "assign", label: t("assign.button"), onClick: openAssign },
                  {
                    key: "dates",
                    label: t("list.bulk_dates_button"),
                    onClick: () => {
                      setDatesError("");
                      setDatesOpen(true);
                    },
                  },
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
            </div>
          )}

          {visibleRows.length === 0 && (
            <EmptyState
              icon={Sparkles}
              title={
                rows.length === 0
                  ? t("list.empty_state")
                  : tabRows.length === 0
                    ? t("tabs.empty_tab")
                    : t("list.empty_filtered_title")
              }
              description={
                rows.length === 0 || tabRows.length === 0
                  ? undefined
                  : t("list.empty_filtered_desc")
              }
              testId="extra-work-list-empty"
            />
          )}

          {showTable && (
            <div className="responsive-table-wrap">
              <div className="card" style={{ overflowX: "auto" }}>
                <table className="data-table data-table-dense data-table-fit ew-tab-table">
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
                      {columns.map((column) => (
                        <th
                          key={column}
                          style={RIGHT_ALIGNED.has(column) ? { textAlign: "right" } : undefined}
                          data-testid={`extra-work-column-${column}`}
                        >
                          {t(COLUMN_LABEL_KEY[column])}
                        </th>
                      ))}
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

              {/* Mobile card fallback: the row's what, where, phase and
                  its one next step. */}
              <ul
                className="admin-card-list"
                data-testid="admin-card-list"
                aria-label={t("nav.meerwerk", { ns: "common" })}
              >
                {visibleRows.map((row) => {
                  const step = listNextStep(row, { isProvider, today });
                  return (
                    <li key={row.id} className="admin-card">
                      <Link
                        to={`/extra-work/${row.id}`}
                        className="admin-card-link"
                        data-testid="extra-work-card"
                      >
                        <div className="admin-card-head">
                          <span className="admin-card-title">{row.title}</span>
                          <PhaseBadge
                            kind="ew"
                            phase={row.display_phase}
                            testId="extra-work-card-phase"
                          />
                        </div>
                        <dl className="admin-card-meta">
                          <div className="admin-card-meta-row">
                            <dt>{t("list.column_where")}</dt>
                            <dd>
                              {row.building_name} · {row.customer_name}
                            </dd>
                          </div>
                          <div className="admin-card-meta-row">
                            <dt>{t("list.column_amount")}</dt>
                            <dd>{money(row)}</dd>
                          </div>
                        </dl>
                      </Link>
                      {step.buttonKey && (
                        <Link to={step.to} className="btn btn-sm btn-secondary">
                          {t(step.buttonKey)}
                        </Link>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}

          {/* The foot: the cancelled door (Finished only) and the P-8
              guard — quiet when it adds up, red when it does not. */}
          <div className="ew-list-foot">
            {activeTab === "finished" && !viewCancelled && (
              <Link
                to={linkTo("finished", CANCELLED_VIEW)}
                className="ew-cancelled-link"
                data-testid="extra-work-cancelled-link"
                data-count={counts.cancelled}
              >
                {t("tabs.cancelled_link", { count: counts.cancelled })}
              </Link>
            )}
            <p
              className="muted small ew-list-guard-line"
              data-testid="extra-work-list-loaded-count"
              data-count={rows.length}
            >
              {t("list.loaded_count", { count: rows.length })}
            </p>
            {rows.length > 0 && countedTotal !== rows.length && (
              <div className="alert-error" role="alert" data-testid="extra-work-list-guard">
                {t("list.guard_mismatch", { loaded: rows.length, counted: countedTotal })}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/**
 * The sidebar route. `/extra-work` (no tab) lands on the first tab with
 * rows; `/extra-work/<tab>` opens that tab.
 */
export function ExtraWorkListPage({ tab }: { tab?: ExtraWorkTab }) {
  return <ExtraWorkList tab={tab} />;
}
