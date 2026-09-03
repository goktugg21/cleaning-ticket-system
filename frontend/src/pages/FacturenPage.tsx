// Invoicing Phase 4b — the provider "Facturen" page.
//
// P-6 V1 (Addendum D §D.6 rule 12, rules 13–15) — the page reads top to
// bottom as one story: where you stand, what is due now (one primary
// action per row), what will not reach the invoice (the billing-month
// guard, folded with its count), and every invoice made so far,
// grouped by month so the "Invoices → customer → month" sentence from
// the meerwerk pages lands somewhere literal.
//
// P-11 D (§D.22 items 1-3, 6-7) — the four fact tiles and the status
// tile row became ONE tab strip with counts (Due now · Drafts ·
// Issued · Sent · All), the tab in the address (?tab=) like the Extra
// work page, one purpose sentence per tab. Due now shows the due
// table; every other tab shows the invoice list narrowed to that
// status (a reversal is a flag on a row, not a status — no Reversed
// tab). One next-step button per row, sharing the detail banner's
// words; the list never sends — every button opens the detail.
//
// Driven by the Phase-4a invoice REST surface:
//   * GET /api/invoices/due/      the due rows (one per scheduled customer)
//   * GET /api/invoices/at-risk/  the WP-1 G4 billing-month guard
//   * GET /api/invoices/preview/  what a run WOULD produce (nothing stored)
//   * POST /api/invoices/generate/
//   * GET /api/invoices/          the list (customer / period server-side;
//                                 status, building and search client-side
//                                 over the exhaustively-loaded set so the
//                                 status tiles carry real counts)
//
// Reusable: with `customerId` set the page is customer-scoped, and
// `embedded` drops the standalone header (the customer sub-page header
// renders instead). Used by CustomerInvoicesPage. "Pinned" means: the
// customer goes to the list endpoint server-side, the customer filter
// and column are not rendered, and the due / at-risk rows are narrowed
// to that customer client-side (the endpoints answer the caller's whole
// scope; see Sprint 186 §2).
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { BadgeEuro, Search, SlidersHorizontal } from "lucide-react";

import { getApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { canReadCustomerArea, isProviderAdmin } from "../auth/permissions";
import {
  generateInvoices,
  getBillingMonthAtRisk,
  getInvoiceDueList,
  getInvoicePreview,
  granularityFor,
  listAllInvoices,
  pairForGranularity,
  type AtRiskGroup,
  type AtRiskRow,
  type AtRiskStage,
  type InvoiceBillingTarget,
  type InvoicePreview,
  type InvoiceSplit,
} from "../api/invoices";
import type {
  Invoice,
  InvoiceDueRow,
  InvoiceNothingReason,
  InvoiceStatus,
} from "../api/types";
import { BillingTargetFields } from "../components/BillingTargetFields";
import { RoadTabs, TeachHead } from "../components/guide/RoadTabs";
import { StartHere } from "../components/guide/StartHere";
import { TeachEmpty } from "../components/guide/TeachEmpty";
import { DoneBanner } from "../components/guide/DoneBanner";
import { useDoneBanner } from "../components/guide/useDoneBanner";
import { HIGHLIGHT_CLASS, HIGHLIGHT_MS } from "../components/guide/highlight";
import { CompanyScopeSelect } from "../components/guide/CompanyScopeSelect";
import { BillingDayDialog } from "../components/invoices/BillingDayDialog";
import { HowThisWorks } from "../components/guide/HowThisWorks";
import { WhatHappens } from "../components/guide/WhatHappens";
import { pickSeedCompany, useCompanyScope } from "../lib/useCompanyScope";
import { atRiskRowHref, dueRowHref } from "../lib/rowLink";
import { BoundedList } from "../components/BoundedList";
import { ClickableRow } from "../components/ClickableRow";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import {
  PdfPreviewDialog,
  type PdfPreviewDialogHandle,
} from "../components/PdfPreviewDialog";
import { monthName } from "../lib/billingSentence";
import { formatDate, formatDateTime, formatMoney, formatOrdinal } from "../lib/intl";

// P-12 D1 (§D.24 rule 3) — the tabs ARE the steps of the road, in
// the order things happen, numbered: finished work becomes a draft,
// you check it, you issue it, you send it. The "All" tab is gone — it
// was not a step. ONE ordered constant; every consumer iterates it
// (the Sprint 126/130 lesson).
const FACTUREN_TABS = ["due", "drafts", "issued", "sent"] as const;
type FacturenTab = (typeof FACTUREN_TABS)[number];

const TAB_LABEL_KEY: Record<FacturenTab, string> = {
  due: "invoices:tabs.due",
  drafts: "invoices:tabs.drafts",
  issued: "invoices:tabs.issued",
  sent: "invoices:tabs.sent",
};

/** The numbered eyebrow word per step ("1 · Afgerond werk"). */
const TAB_STEP_KEY: Record<FacturenTab, string> = {
  due: "invoices:road.due_step",
  drafts: "invoices:road.drafts_step",
  issued: "invoices:road.issued_step",
  sent: "invoices:road.sent_step",
};

/** The invoice status one tab narrows the list to; the Due tab shows
 *  the per-customer due table instead of the list. */
const TAB_STATUS: Record<FacturenTab, InvoiceStatus | null> = {
  due: null,
  drafts: "DRAFT",
  issued: "ISSUED",
  sent: "SENT",
};

// P-11 D (§D.22 item 7) — ONE next-step button per row, the invoice's
// own next move, sharing the detail banner's words. The list never
// sends: every button opens the detail, where the real action lives.
const NEXT_STEP_KEY: Record<InvoiceStatus, string> = {
  DRAFT: "invoice_detail.action_issue",
  ISSUED: "invoice_detail.action_send",
  SENT: "invoices:list.open",
};

function parseFacturenTab(value: string | null): FacturenTab | null {
  return value !== null && (FACTUREN_TABS as readonly string[]).includes(value)
    ? (value as FacturenTab)
    : null;
}

// WP-1 G4 — human words for the guard's machine stages. Since P-13 A
// these are the FALLBACK for a payload without `reason` — the cell
// renders `atRiskSentence` below.
const AT_RISK_STAGE_KEYS: Record<AtRiskStage, string> = {
  WAITING_REVIEW: "facturen.at_risk_stage_waiting_review",
  SLOT_DONE: "facturen.at_risk_stage_slot_done",
  BLOCKED: "facturen.at_risk_stage_blocked",
  PAST_DEADLINE: "facturen.at_risk_stage_past_deadline",
  ON_HOLD: "facturen.at_risk_stage_on_hold",
  NOT_PLANNED: "facturen.at_risk_stage_not_planned",
};

/** P-13 A (O1) — the reason cell is a sentence from the job's REAL
 *  state, never a category word (the owner met "Stuck at: stuck").
 *  Falls back to the stage words for an older payload. */
function atRiskSentence(
  t: (key: string, opts?: Record<string, unknown>) => string,
  row: AtRiskRow,
): string {
  const since = row.since ? formatDate(`${row.since}T00:00:00`) : "";
  switch (row.reason) {
    case "REVIEW_WAIT":
      return row.manager_names && row.manager_names.length > 0
        ? t("invoices:road.at_risk_review_named", {
            names: row.manager_names.join(", "),
            count: row.age_days,
          })
        : t("invoices:road.at_risk_review", { count: row.age_days });
    case "DONE_UNMOVED":
      return t("invoices:road.at_risk_done_unmoved", { count: row.age_days });
    case "REJECTED":
      return t("invoices:road.at_risk_rejected", { date: since });
    case "CONVERTED":
      return t("invoices:road.at_risk_converted", { date: since });
    case "CREW_UNABLE":
      return t("invoices:road.at_risk_crew_unable", { date: since });
    case "ON_HOLD":
      return t("invoices:road.at_risk_on_hold", { date: since });
    case "PAST_DEADLINE":
      return t("invoices:road.at_risk_past_deadline", { count: row.age_days });
    case "NOT_PLANNED":
      return t("invoices:road.at_risk_not_planned", {
        date: formatDate(`${row.date}T00:00:00`),
      });
    default:
      return t(AT_RISK_STAGE_KEYS[row.stage]);
  }
}

/** The one sentence, from the one diagnosis (Sprint 183 §2). Shared by
 *  the Due panel and the preview so they cannot word it differently. */
function nothingSentence(
  t: (key: string, opts?: Record<string, unknown>) => string,
  nothing: InvoiceNothingReason | undefined,
): string | null {
  if (!nothing || nothing.reason === "NOTHING_TO_EXPLAIN") return null;
  if (nothing.reason === "NO_EXTRA_WORK") {
    return t("invoices:nothing.no_extra_work");
  }
  if (nothing.reason === "NONE_FINISHED") {
    return t("invoices:nothing.none_finished", { count: nothing.unbilled_count });
  }
  if (nothing.reason === "NOT_IN_PERIOD") {
    return t("invoices:nothing.not_in_period", { count: nothing.finished_count });
  }
  return t("invoices:nothing.all_invoiced", { count: nothing.invoiced_count });
}

function currentMonthValue(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function parseMonth(value: string): { year: number; month: number } | null {
  const [y, m] = value.split("-").map(Number);
  if (!Number.isFinite(y) || !Number.isFinite(m) || m < 1 || m > 12) {
    return null;
  }
  return { year: y, month: m };
}

/** P-7 S4.1 — a billing month is WORDS everywhere: "augustus 2026",
 *  never "08-2026". */
function formatPeriod(year: number | null, month: number | null): string {
  if (!year || !month) return "";
  return monthName(`${year}-${String(month).padStart(2, "0")}`);
}

function sumAmounts(values: string[]): string {
  return values
    .reduce((total, value) => total + (Number.parseFloat(value) || 0), 0)
    .toFixed(2);
}

/* ====================================================================
   W5 fix 4 — WHICH PERIOD the unbilled work belongs to.

   `unbilled_extra_work_through` (the /due/ count) matches work billable
   in the current period OR ANY EARLIER one; `generate` runs ONE exact
   period. So work whose billing month is June shows as "1 unbilled" in
   August and generates nothing in August. Both selectors are correct;
   what was missing is the period, said out loud: on the row, on the
   button, and in the answer when a run produces nothing.

   `/invoices/preview/` takes a year and a month and runs the THROUGH
   query, so `linesThrough(M) - linesThrough(M-1)` is the count that sits
   in exactly M. Walking back until the through count reaches zero
   yields every period that holds unbilled work, oldest last; capped at
   `MAX_PERIOD_LOOKBACK`. The differencing is a count of ROWS, never
   money. */
const MAX_PERIOD_LOOKBACK = 13;

interface UnbilledPeriod {
  year: number;
  month: number;
  count: number;
}

interface UnbilledPeriods {
  periods: UnbilledPeriod[];
  truncated: boolean;
}

function monthBefore(year: number, month: number): { year: number; month: number } {
  return month === 1 ? { year: year - 1, month: 12 } : { year, month: month - 1 };
}

function previewLineCount(preview: InvoicePreview): number {
  return preview.invoices.reduce((total, inv) => total + inv.line_count, 0);
}

async function resolveUnbilledPeriods(
  customer: number,
  year: number,
  month: number,
): Promise<UnbilledPeriods> {
  const periods: UnbilledPeriod[] = [];
  let cursor = { year, month };
  let through = previewLineCount(await getInvoicePreview({ customer, year, month }));
  let steps = 0;
  while (through > 0 && steps < MAX_PERIOD_LOOKBACK) {
    const earlier = monthBefore(cursor.year, cursor.month);
    const earlierThrough = previewLineCount(
      await getInvoicePreview({ customer, year: earlier.year, month: earlier.month }),
    );
    if (through > earlierThrough) {
      periods.push({ ...cursor, count: through - earlierThrough });
    }
    cursor = earlier;
    through = earlierThrough;
    steps += 1;
  }
  periods.reverse();
  return { periods, truncated: through > 0 };
}

function periodsSentence(
  t: (key: string, opts?: Record<string, unknown>) => string,
  resolved: UnbilledPeriods | undefined,
): string | null {
  if (!resolved || resolved.periods.length === 0) return null;
  const first = resolved.periods[0];
  if (resolved.periods.length === 1) {
    return t("facturen.due_period_one", {
      period: formatPeriod(first.year, first.month),
    });
  }
  const last = resolved.periods[resolved.periods.length - 1];
  return t("facturen.due_period_many", {
    count: resolved.periods.length,
    first: formatPeriod(first.year, first.month),
    last: formatPeriod(last.year, last.month),
  });
}

function periodListLabel(resolved: UnbilledPeriods | undefined): string | null {
  if (!resolved || resolved.periods.length === 0) return null;
  return resolved.periods
    .map((period) => formatPeriod(period.year, period.month))
    .join(", ");
}

/** P-12 D5 (§D.24 rule 6) — the draft row says what its lines came
 *  from: "Contract CNT-2026-0002 · augustus + 2 meerwerkregels". A
 *  contract-generated draft's non-EW lines belong to the contract;
 *  a hand-made draft's are hand lines. */
function draftLinesSummary(
  inv: Invoice,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  const ewCount = inv.lines.filter((line) => line.extra_work !== null).length;
  const parts: string[] = [];
  if (inv.contract) {
    parts.push(
      t("invoices:road.lines_contract", {
        no: inv.contract.contract_no,
        period: monthName(inv.contract.period_start.slice(0, 7)),
      }),
    );
  }
  if (ewCount > 0) {
    parts.push(t("invoices:road.lines_ew", { count: ewCount }));
  }
  const rest = inv.lines.length - ewCount;
  if (!inv.contract && rest > 0) {
    parts.push(t("invoices:road.lines_hand", { count: rest }));
  }
  return parts.length > 0 ? parts.join(" + ") : t("invoices:road.lines_none");
}

export function FacturenPage({
  customerId,
  embedded = false,
}: {
  customerId?: number;
  embedded?: boolean;
} = {}) {
  const { t } = useTranslation(["common", "invoices"]);
  const { me } = useAuth();
  const customerScoped = customerId !== undefined;
  // P-8R F — the row's customer link goes to the customer detail, whose
  // own guard (`CustomerReadRoute`) decides who may open it. Every
  // billing role passes today; the gate is stated so a plain name, not a
  // dead door, is what a narrower role would get.
  const canOpenCustomer = canReadCustomerArea(me?.role);
  /** P-14 (findings) — "Set a billing day" PATCHes the customer, which
   *  is SA/CA-only server-side; a BUILDING_MANAGER (a full invoice
   *  operator otherwise, Addendum B) got a door that could only 403.
   *  The money sentence stays for BM; the schedule-fixing door hides. */
  const canSetBillingDay = isProviderAdmin(me?.role);
  /** P-15 §0.1 / H-12 — issue/send/un-issue/reverse are CA/SA-only.
   *  The Start-here must not order a BM to send. */
  const canCommitInvoices = isProviderAdmin(me?.role);
  // P-6 V1 — the "Invoices → customer → month" sentence on the meerwerk
  // pages links here with `?customer=<id>&period=YYYY-MM`; the page opens
  // on exactly that customer and month.
  const [searchParams, setSearchParams] = useSearchParams();

  const [dueRows, setDueRows] = useState<InvoiceDueRow[]>([]);
  const [dueLoading, setDueLoading] = useState(true);
  const [atRiskGroups, setAtRiskGroups] = useState<AtRiskGroup[]>([]);
  const [atRiskTruncated, setAtRiskTruncated] = useState(false);
  const [duePeriods, setDuePeriods] = useState<Record<number, UnbilledPeriods>>({});
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  // List filters. customer (pinned) + period narrow server-side;
  // building and the search narrow client-side over the loaded set.
  const [periodMonth, setPeriodMonth] = useState(() => {
    const fromUrl = embedded ? null : searchParams.get("period");
    return fromUrl && parseMonth(fromUrl) ? fromUrl : "";
  });
  const [customerFilter, setCustomerFilter] = useState(() => {
    const fromUrl = embedded ? null : searchParams.get("customer");
    return fromUrl && /^\d+$/.test(fromUrl) ? fromUrl : "ALL";
  });
  const [buildingFilter, setBuildingFilter] = useState("ALL");
  const [search, setSearch] = useState("");

  // P-12 D1 — the tab, in the address (?tab=). Without one the page
  // opens on the road's first step; a meerwerk deep link (?customer= /
  // ?period=) lands there too — the customer's unbilled work IS the
  // To-invoice tab, and the filters narrow every tab including it.
  const urlTab = parseFacturenTab(searchParams.get("tab"));
  const activeTab: FacturenTab = urlTab ?? "due";

  function selectTab(next: FacturenTab) {
    const params = new URLSearchParams(searchParams);
    params.set("tab", next);
    setSearchParams(params);
  }

  // Generate control — opened from a due row; a single inline panel.
  const [genRow, setGenRow] = useState<InvoiceDueRow | null>(null);
  const [genMonth, setGenMonth] = useState("");
  const [genTarget, setGenTarget] = useState<InvoiceBillingTarget>("CUSTOMER");
  const [genSplit, setGenSplit] = useState<InvoiceSplit>("NONE");
  const [genBusy, setGenBusy] = useState(false);

  // P-13 A (W1) — "Set a billing day", from the row that shows the gap.
  const [dayRow, setDayRow] = useState<InvoiceDueRow | null>(null);

  // Sprint 182 §2 — the preview. NOTHING IS STORED server-side.
  const [previewRow, setPreviewRow] = useState<InvoiceDueRow | null>(null);
  const [preview, setPreview] = useState<InvoicePreview | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const previewPdfRef = useRef<PdfPreviewDialogHandle>(null);

  // P-12 D3 (§D.24 rule 4) — the after-action banner and the fresh
  // drafts' ten-second tint on the Drafts tab.
  const facDone = useDoneBanner("invoices");
  const [newDraftIds, setNewDraftIds] = useState<number[]>([]);
  useEffect(() => {
    if (newDraftIds.length === 0) return;
    const timer = window.setTimeout(() => setNewDraftIds([]), HIGHLIGHT_MS);
    return () => window.clearTimeout(timer);
  }, [newDraftIds]);

  // P-12 §D.24.2 — one company at a time (SUPER_ADMIN, standalone
  // page only). The session's shared choice wins; else the company
  // with something waiting seeds it once the due rows arrive.
  const companyScope = useCompanyScope(
    !embedded && !customerScoped && me?.role === "SUPER_ADMIN",
  );
  const scopedCompany =
    companyScope.companyId === "" ? undefined : companyScope.companyId;

  // Due panel — loaded in BOTH modes, narrowed to the pinned customer.
  useEffect(() => {
    let cancelled = false;
    async function loadDue() {
      try {
        const rows = await getInvoiceDueList(
          scopedCompany === undefined ? {} : { company: scopedCompany },
        );
        if (!cancelled) {
          setDueRows(
            customerId === undefined
              ? rows
              : rows.filter((row) => row.customer === customerId),
          );
        }
      } catch (err) {
        if (!cancelled) setError(getApiError(err));
      } finally {
        if (!cancelled) setDueLoading(false);
      }
    }
    loadDue();
    return () => {
      cancelled = true;
    };
  }, [customerId, refreshKey, scopedCompany]);

  // §D.24.2 + P-13 A (W2) — the seed chain, explicit and pinned
  // (`pickSeedCompany`): session choice (the hook applies it) → the
  // company with something waiting → the first company by name. The
  // last arm is the W2 fix: with nothing due anywhere the selector
  // read "…" forever. Waits for the due rows so an empty first render
  // cannot jump the queue.
  useEffect(() => {
    if (!companyScope.ready || companyScope.companyId !== "") return;
    if (companyScope.companies.length <= 1) return;
    if (dueLoading) return;
    const seed = pickSeedCompany(dueRows, companyScope.companies);
    if (seed !== null) companyScope.seedCompany(seed);
  }, [companyScope, dueRows, dueLoading]);

  // WP-1 G4 — the at-risk rows. A failed fetch keeps its silence.
  useEffect(() => {
    let cancelled = false;
    async function loadAtRisk() {
      try {
        const data = await getBillingMonthAtRisk(
          scopedCompany === undefined ? {} : { company: scopedCompany },
        );
        if (cancelled) return;
        setAtRiskGroups(
          customerId === undefined
            ? data.groups
            : data.groups.filter((group) => group.customer === customerId),
        );
        setAtRiskTruncated(data.truncated);
      } catch {
        if (!cancelled) setAtRiskGroups([]);
      }
    }
    loadAtRisk();
    return () => {
      cancelled = true;
    };
  }, [customerId, refreshKey, scopedCompany]);

  // W5 fix 4 — resolve WHICH periods each due row's unbilled work sits in.
  useEffect(() => {
    let cancelled = false;
    const rows = dueRows.filter((row) => row.unbilled_count > 0);
    if (rows.length === 0) return;
    async function resolveAll() {
      for (const row of rows) {
        try {
          const resolved = await resolveUnbilledPeriods(
            row.customer,
            row.period_year,
            row.period_month,
          );
          if (cancelled) return;
          setDuePeriods((prev) => ({ ...prev, [row.customer]: resolved }));
        } catch {
          if (cancelled) return;
        }
      }
    }
    resolveAll();
    return () => {
      cancelled = true;
    };
  }, [dueRows]);

  // Invoice list — exhaustive (Sprint 120), status filtered client-side
  // so the status tiles carry real counts.
  const period = useMemo(() => parseMonth(periodMonth), [periodMonth]);
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const allInvoices = await listAllInvoices({
          customer: customerId,
          company: scopedCompany,
          period_year: period?.year,
          period_month: period?.month,
        });
        if (!cancelled) setInvoices(allInvoices);
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
  }, [customerId, period, refreshKey, scopedCompany]);

  const customerOptions = useMemo(() => {
    const map = new Map<number, string>();
    for (const inv of invoices) map.set(inv.customer, inv.customer_name);
    return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [invoices]);
  const buildingOptions = useMemo(() => {
    const map = new Map<number, string>();
    for (const inv of invoices) {
      if (inv.building !== null) {
        map.set(inv.building, inv.building_name ?? String(inv.building));
      }
    }
    return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [invoices]);

  // Everything but the status tab — the tabs count within this set.
  const baseVisible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return invoices.filter((inv) => {
      if (!customerScoped && customerFilter !== "ALL" && String(inv.customer) !== customerFilter) {
        return false;
      }
      if (buildingFilter !== "ALL" && String(inv.building) !== buildingFilter) {
        return false;
      }
      if (needle) {
        const haystack = [
          inv.number ?? "",
          inv.customer_name,
          inv.building_name ?? "",
          inv.credited_by_number ?? "",
        ]
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    });
  }, [invoices, customerScoped, customerFilter, buildingFilter, search]);

  const statusCounts = useMemo(() => {
    const counts: Record<InvoiceStatus, number> = { DRAFT: 0, ISSUED: 0, SENT: 0 };
    for (const inv of baseVisible) counts[inv.status] += 1;
    return counts;
  }, [baseVisible]);

  // P-11 D — the tab IS the status narrowing (the All and Due now tabs
  // narrow nothing; Due now renders the due table, not this list).
  const tabStatus = TAB_STATUS[activeTab];
  const visibleInvoices = useMemo(
    () => (tabStatus === null ? baseVisible : baseVisible.filter((inv) => inv.status === tabStatus)),
    [baseVisible, tabStatus],
  );


  const activeFilterChips = useMemo(() => {
    const chips: string[] = [];
    if (period) chips.push(formatPeriod(period.year, period.month));
    if (!customerScoped && customerFilter !== "ALL") {
      const name = customerOptions.find(([id]) => String(id) === customerFilter)?.[1];
      chips.push(name ?? t("facturen.filter_customer"));
    }
    if (buildingFilter !== "ALL") {
      const name = buildingOptions.find(([id]) => String(id) === buildingFilter)?.[1];
      chips.push(name ?? t("facturen.filter_building"));
    }
    return chips;
  }, [period, customerScoped, customerFilter, customerOptions, buildingFilter, buildingOptions, t]);

  const anyFilter = activeFilterChips.length > 0 || search.trim() !== "";

  function clearFilters() {
    setPeriodMonth("");
    setCustomerFilter("ALL");
    setBuildingFilter("ALL");
    setSearch("");
  }

  // P-11 D — the tab counts, client-side over the loaded sets: the
  // list is exhaustive (Sprint 120), and the due count is today's
  // "ready for a draft" fact from the due rows.
  // The due table narrows with the customer filter too, so a meerwerk
  // deep link (?customer=) lands on To invoice showing THAT customer.
  const visibleDueRows = useMemo(
    () =>
      customerFilter === "ALL"
        ? dueRows
        : dueRows.filter((row) => String(row.customer) === customerFilter),
    [dueRows, customerFilter],
  );
  const dueNowRows = visibleDueRows.filter((row) => row.unbilled_count > 0);
  const atRiskCount = atRiskGroups.reduce((total, group) => total + group.rows.length, 0);
  const tabCounts: Record<FacturenTab, number> = {
    due: dueNowRows.length,
    drafts: statusCounts.DRAFT,
    issued: statusCounts.ISSUED,
    sent: statusCounts.SENT,
  };

  // §D.22 rule 4 — one money line per step, over the loaded rows.
  const thisYear = String(new Date().getFullYear());
  const tabMoney: Record<FacturenTab, string> = {
    due: sumAmounts(dueNowRows.map((row) => row.unbilled_total)),
    drafts: sumAmounts(
      baseVisible.filter((inv) => inv.status === "DRAFT").map((inv) => inv.total_amount),
    ),
    issued: sumAmounts(
      baseVisible.filter((inv) => inv.status === "ISSUED").map((inv) => inv.total_amount),
    ),
    sent: sumAmounts(
      baseVisible
        .filter((inv) => inv.status === "SENT" && (inv.sent_at ?? "").startsWith(thisYear))
        .map((inv) => inv.total_amount),
    ),
  };

  // §D.24 rule 2 — the ONE thing waiting, first step first: a due-now
  // customer, else drafts to check, else issued waiting to be sent.
  // P-13 A (W1) — a customer with finished money and NO billing day
  // comes before all of those: nothing will ever pick their work up
  // until somebody sets the day (or makes the draft by hand).
  const startNoDayRow =
    dueNowRows.find(
      (row) => row.invoice_day_of_month == null && !row.invoice_day_rule,
    ) ?? null;
  const startDueRow = dueNowRows.find((row) => row.is_due) ?? null;
  const oldestDraft =
    [...baseVisible].filter((inv) => inv.status === "DRAFT").sort((a, b) => a.id - b.id)[0] ??
    null;
  const oldestIssued =
    [...baseVisible].filter((inv) => inv.status === "ISSUED").sort((a, b) => a.id - b.id)[0] ??
    null;

  function openGenerate(row: InvoiceDueRow) {
    setGenRow(row);
    setPreviewRow(null);
    setPreview(null);
    // W5 fix 4 — open on the OLDEST period that actually holds unbilled work.
    const resolved = duePeriods[row.customer];
    const target = resolved?.periods[0];
    setGenMonth(
      target
        ? `${target.year}-${String(target.month).padStart(2, "0")}`
        : row.period_year && row.period_month
          ? `${row.period_year}-${String(row.period_month).padStart(2, "0")}`
          : currentMonthValue(),
    );
    if (row.invoice_billing_target) {
      setGenTarget(row.invoice_billing_target);
      setGenSplit(row.invoice_split ?? "NONE");
    } else {
      const pair = pairForGranularity(row.invoice_granularity_default);
      setGenTarget(pair.target);
      setGenSplit(pair.split);
    }
  }

  async function openPreview(row: InvoiceDueRow) {
    setGenRow(null);
    setPreviewRow(row);
    setPreview(null);
    setPreviewBusy(true);
    setError("");
    try {
      setPreview(
        await getInvoicePreview({
          customer: row.customer,
          year: row.period_year,
          month: row.period_month,
        }),
      );
    } catch (err) {
      setError(getApiError(err));
      setPreviewRow(null);
    } finally {
      setPreviewBusy(false);
    }
  }

  function handleViewPreviewPdf() {
    // W17 — the preview is something you LOOK AT, in the app, and nothing
    // else: in-app dialog, no download, nothing stored server-side.
    if (!previewRow) return;
    previewPdfRef.current?.open({
      url:
        `/invoices/preview/?customer=${previewRow.customer}` +
        `&year=${previewRow.period_year}&month=${previewRow.period_month}` +
        `&download=pdf`,
      filename: t("facturen.preview_doc_name", { name: previewRow.customer_name }),
    });
  }

  async function handleGenerate() {
    if (!genRow) return;
    const parsed = parseMonth(genMonth);
    if (!parsed) return;
    setGenBusy(true);
    setError("");
    try {
      const created = await generateInvoices({
        customer: genRow.customer,
        year: parsed.year,
        month: parsed.month,
        // Sprint 183 §1 — the UI speaks the pair; the WIRE keeps the
        // legacy `granularity` field.
        granularity: granularityFor(genTarget, genSplit),
      });
      if (created.length > 0) {
        // P-12 D3 (§D.24 rule 4) — the page MOVES you to where the
        // thing went: the Drafts tab, the new drafts tinted, and the
        // banner says what happened, what did NOT, and the next step.
        const ewLineCount = created.reduce(
          (total, inv) => total + inv.lines.filter((line) => line.extra_work !== null).length,
          0,
        );
        facDone.announce({
          title: t("invoices:road.made_title", {
            count: created.length,
            name: genRow.customer_name,
            amount: formatMoney(sumAmounts(created.map((inv) => inv.total_amount))),
            period: formatPeriod(parsed.year, parsed.month),
            lines: ewLineCount,
          }),
          body: t("invoices:road.made_body"),
          actionLabel: t("invoices:road.made_action", { count: created.length }),
          actionTo: `/invoices/${created[0].id}`,
        });
        setNewDraftIds(created.map((inv) => inv.id));
        selectTab("drafts");
      } else {
        const attempted = formatPeriod(parsed.year, parsed.month);
        const elsewhere = periodListLabel(duePeriods[genRow.customer]);
        // Zero created: the same surface, the P-11 sentence — a banner
        // on the tab the person is on, never only a toast.
        facDone.announce({
          title: elsewhere
            ? t("facturen.gen_zero_elsewhere", { attempted, actual: elsewhere })
            : t("facturen.gen_zero", { attempted }),
        });
      }
      setGenRow(null);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setGenBusy(false);
    }
  }

  const genParsed = parseMonth(genMonth);

  return (
    <div data-testid="facturen-page">
      {!embedded && (
        <PageHeader
          eyebrow={t("facturen.eyebrow")}
          title={t("facturen.title")}
          subtitle={t("facturen.subtitle")}
          testId="facturen-header"
          actions={
            <CompanyScopeSelect
              companies={companyScope.companies}
              companyId={companyScope.companyId}
              onChange={(id) => companyScope.chooseCompany(id)}
              testId="facturen-company-scope"
            />
          }
        />
      )}

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* P-13 §D.24 rule 8 — what this page CAN do, before what to do. */}
      {!embedded && !customerScoped && (
        <HowThisWorks
          pageKey="invoices"
          testId="facturen-how"
          lines={[
            t("invoices:how.1"),
            t("invoices:how.2"),
            t("invoices:how.3"),
            t("invoices:how.4"),
            t("invoices:how.5"),
          ]}
        />
      )}

      {/* P-12 §D.24 rule 4 — what just happened, in place. */}
      {facDone.done && (
        <DoneBanner
          done={facDone.done}
          onDismiss={facDone.dismiss}
          testId="facturen-done"
        />
      )}

      {/* P-12 §D.24 rule 2 — the ONE thing waiting, first step first.
          P-13 J — while a Done banner is up, Start here stands down:
          one voice at a time. */}
      {!dueLoading && !loading && !genRow && !facDone.done && (
        canSetBillingDay && startNoDayRow ? (
          <StartHere
            testId="facturen-start-here"
            action={{
              label: t("invoices:road.start_no_day_action", {
                name: startNoDayRow.customer_name,
              }),
              onClick: () => {
                selectTab("due");
                setDayRow(startNoDayRow);
              },
            }}
          >
            {t("invoices:road.start_no_day", {
              name: startNoDayRow.customer_name,
              total: formatMoney(startNoDayRow.unbilled_total),
            })}
          </StartHere>
        ) : startDueRow ? (
          <StartHere
            testId="facturen-start-here"
            action={{
              label: t("invoices:road.start_due_action", {
                name: startDueRow.customer_name,
              }),
              onClick: () => {
                selectTab("due");
                openGenerate(startDueRow);
              },
            }}
          >
            {t("invoices:road.start_due", {
              count: dueNowRows.length,
              total: formatMoney(tabMoney.due),
              name: startDueRow.customer_name,
              day:
                startDueRow.invoice_day_of_month != null
                  ? t("facturatie.day_of_month", { day: startDueRow.invoice_day_of_month })
                  : startDueRow.invoice_day_rule === "LAST_OF_MONTH"
                    ? t("facturatie.day_last")
                    : t("facturatie.day_first"),
            })}
          </StartHere>
        ) : oldestDraft ? (
          <StartHere
            testId="facturen-start-here"
            action={{
              label: t("invoices:road.start_drafts_action"),
              to: `/invoices/${oldestDraft.id}`,
            }}
          >
            {t("invoices:road.start_drafts", {
              count: tabCounts.drafts,
              total: formatMoney(tabMoney.drafts),
            })}
          </StartHere>
        ) : oldestIssued ? (
          <StartHere
            testId="facturen-start-here"
            action={{
              label: t("invoices:road.start_issued_action"),
              to: `/invoices/${oldestIssued.id}`,
            }}
          >
            {/* P-15 §0.1 — a BM may not send; the sentence must not
                suggest it. The read variant states who does. */}
            {canCommitInvoices
              ? t("invoices:road.start_issued", { count: tabCounts.issued })
              : t("invoices:road.start_issued_read", { count: tabCounts.issued })}
          </StartHere>
        ) : null
      )}

      {/* P-12 D1 (§D.24 rule 3) — the road: numbered steps, in the
          order things happen, each with its count. */}
      <RoadTabs
        steps={FACTUREN_TABS.map((key) => ({
          key,
          step: t(TAB_STEP_KEY[key]),
          label: t(TAB_LABEL_KEY[key]),
          count:
            (key === "due" ? dueLoading : loading) ? null : tabCounts[key],
        }))}
        activeKey={activeTab}
        onSelect={(key) => selectTab(key)}
        ariaLabel={t("facturen.title")}
        testIdPrefix="facturen-tab"
      />

      {/* Rule 3's second half — the step teaches itself, with the one
          money line (§D.22 rule 4). */}
      <TeachHead
        testId="facturen-teach"
        title={t(`invoices:road.${activeTab}_title`)}
        body={t(`invoices:road.${activeTab}_body`)}
        money={
          (activeTab === "due" ? dueLoading : loading)
            ? undefined
            : {
                value:
                  activeTab === "due" || activeTab === "drafts" || activeTab === "issued" || activeTab === "sent"
                    ? formatMoney(tabMoney[activeTab])
                    : "",
                label: t(`invoices:road.${activeTab}_money_label`),
              }
        }
      />

      {/* ---- Due panel — the Due now tab ---- */}
      {activeTab === "due" && (
      <section
        className="card"
        style={{ padding: 16, marginBottom: 16 }}
        data-testid="facturen-due-panel"
      >
        {dueLoading ? (
          <div className="loading-bar">
            <div className="loading-bar-fill" />
          </div>
        ) : visibleDueRows.length === 0 ? (
          <p className="muted small" data-testid="facturen-due-empty">
            {customerScoped ? (
              t("facturen.due_empty_customer")
            ) : (
              <>
                {t("facturen.due_empty")}{" "}
                <Link to="/admin/customers" className="page-sub-link">
                  {t("facturen.due_empty_link")}
                </Link>
              </>
            )}
          </p>
        ) : (
          <>
          <div style={{ overflowX: "auto" }}>
            <table className="data-table" data-testid="facturen-due-table">
              <thead>
                <tr>
                  <th>{t("facturen.col_customer")}</th>
                  <th>{t("facturen.due_col_schedule")}</th>
                  <th>{t("invoices:road.due_col_waiting")}</th>
                  <th style={{ textAlign: "right" }}>{t("facturen.col_total")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {visibleDueRows.map((row) => {
                  const ready = row.unbilled_count > 0;
                  // P-13 A (W1) — no day AND no rule: the row that used
                  // to be invisible. Its schedule cell says the fact and
                  // its actions offer the two ways out.
                  const noDay =
                    row.invoice_day_of_month == null && !row.invoice_day_rule;
                  const dayWords =
                    row.invoice_day_of_month != null
                      ? t("facturatie.day_of_month", { day: row.invoice_day_of_month })
                      : row.invoice_day_rule === "FIRST_OF_MONTH"
                        ? t("facturatie.day_first")
                        : row.invoice_day_rule === "LAST_OF_MONTH"
                          ? t("facturatie.day_last")
                          : t("invoices:road.no_day_set");
                  return (
                    <ClickableRow
                      key={row.customer}
                      to={dueRowHref(row)}
                      inert={embedded || customerScoped}
                      testId="facturen-due-row"
                      dataAttrs={{ ready }}
                      ariaLabel={row.customer_name}
                    >
                      <td>
                        {row.customer_name}
                        {row.is_due && (
                          <span
                            className="cell-tag cell-tag-open"
                            style={{ marginLeft: 8 }}
                            data-testid="facturen-due-badge"
                          >
                            <i />
                            {t("facturen.due_now")}
                          </span>
                        )}
                        {/* Rule 1's "today is the 2nd" sub — why Due
                            now is (or is not) on this row. */}
                        {row.is_due && (
                          <span className="muted small" style={{ display: "block" }}>
                            {t("invoices:road.due_today_sub", {
                              day: dayWords,
                              today: formatOrdinal(new Date().getDate()),
                            })}
                          </span>
                        )}
                      </td>
                      {/* W-HK1 §2 — the backend's order: a fixed day wins
                          over the FIRST/LAST rule. */}
                      <td className="muted small">{dayWords}</td>
                      <td>
                        {ready ? (
                          <strong>
                            {t("invoices:road.due_waiting_jobs", {
                              count: row.unbilled_count,
                            })}
                          </strong>
                        ) : (
                          <span className="cell-tag cell-tag-closed">
                            <i />
                            {t("invoices:road.due_nothing_yet")}
                          </span>
                        )}
                        {nothingSentence(t, row.nothing_reason) && (
                          <span
                            className="muted small"
                            style={{ display: "block" }}
                            data-testid="facturen-due-nothing"
                          >
                            {nothingSentence(t, row.nothing_reason)}
                          </span>
                        )}
                        {periodsSentence(t, duePeriods[row.customer]) && (
                          <span
                            className="muted small"
                            style={{ display: "block" }}
                            data-testid="facturen-due-periods"
                          >
                            {periodsSentence(t, duePeriods[row.customer])}
                          </span>
                        )}
                      </td>
                      <td style={{ textAlign: "right" }}>
                        {ready ? <strong>{formatMoney(row.unbilled_total)}</strong> : "\u2014"}
                      </td>
                      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        {/* D5 — the due row keeps its pair (Preview +
                            Make a draft): the one-button rule is the
                            LIST tabs'. A row with nothing carries its
                            reason in words instead of dead buttons.
                            P-13 A (W1) — a no-day row's pair is "Set a
                            billing day" + "Make a draft now": fix the
                            schedule, or bill by hand right here. */}
                        {ready && noDay ? (
                          <>
                            {canSetBillingDay && (
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                onClick={() => setDayRow(row)}
                                data-testid="facturen-set-day-open"
                                style={{ marginRight: 8 }}
                              >
                                {t("invoices:road.set_day")}
                              </button>
                            )}
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              onClick={() => openGenerate(row)}
                              data-testid="facturen-generate-open"
                            >
                              {t("invoices:road.make_draft_now")}
                            </button>
                          </>
                        ) : ready ? (
                          <>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              onClick={() => openPreview(row)}
                              data-testid="facturen-preview-open"
                              style={{ marginRight: 8 }}
                            >
                              {t("facturen.preview_open")}
                            </button>
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              onClick={() => openGenerate(row)}
                              data-testid="facturen-generate-open"
                            >
                              {t("facturen.generate")}
                            </button>
                          </>
                        ) : (
                          <span className="muted small" data-testid="facturen-due-nothing-now">
                            {t("facturen.due_nothing_now")}
                          </span>
                        )}
                      </td>
                    </ClickableRow>
                  );
                })}
              </tbody>
            </table>
          </div>
          {/* P-11 D item 3 — what a draft is, said once under the table. */}
          <p className="muted small" style={{ margin: "8px 0 0" }} data-testid="facturen-draft-hint">
            {t("invoices:due.draft_hint")}
          </p>
          </>
        )}

        {/* P-12 D1 — the at-risk guard is the To-invoice tab's FOOTER
            line: "N running jobs will not reach this month's
            invoices — see which". Nothing renders when it is clear
            (a card celebrating zero is what §D.24 rule 2 bans). */}
        {atRiskGroups.length > 0 && (
          <details className="form-fold" style={{ marginTop: 12 }} data-testid="facturen-at-risk-panel">
            <summary className="form-fold-summary">
              {t("invoices:road.at_risk_foot", { count: atRiskCount })}
              <span className="form-fold-summary-value">
                {t("facturen.at_risk_see_which")}
              </span>
            </summary>
            <div className="form-fold-body">
              <p className="muted small" style={{ marginTop: 4 }}>{t("facturen.at_risk_sub")}</p>
              <div style={{ overflowX: "auto" }}>
                <table className="data-table data-table-dense" data-testid="facturen-at-risk-table">
                  <thead>
                    <tr>
                      {!customerScoped && <th>{t("facturen.col_customer")}</th>}
                      <th>{t("facturen.at_risk_col_item")}</th>
                      <th>{t("facturen.at_risk_col_stage")}</th>
                      <th>{t("facturen.at_risk_col_age")}</th>
                      <th>{t("facturen.at_risk_col_date")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {atRiskGroups.flatMap((group) =>
                      group.rows.map((row) => (
                        // P-13 A (O1a) / \u00a7D.22 rule 9 \u2014 the WHOLE row
                        // opens the job; the name stays a real link for
                        // middle-click.
                        <ClickableRow
                          key={`${group.customer}-${row.extra_work_id}`}
                          to={atRiskRowHref(row)}
                          testId="facturen-at-risk-row"
                          ariaLabel={row.title}
                        >
                          {!customerScoped && <td>{group.customer_name}</td>}
                          <td>
                            <Link to={atRiskRowHref(row)}>
                              {row.ticket_no ? `${row.ticket_no} \u00b7 ` : ""}
                              {row.title}
                            </Link>
                            {row.building_name && <div className="muted small">{row.building_name}</div>}
                          </td>
                          <td>{atRiskSentence(t, row)}</td>
                          <td>{t("facturen.at_risk_age", { count: row.age_days })}</td>
                          <td>{formatDate(`${row.date}T00:00:00`)}</td>
                        </ClickableRow>
                      )),
                    )}
                  </tbody>
                </table>
              </div>
              {atRiskTruncated && (
                <p className="muted small" role="status">{t("facturen.at_risk_truncated")}</p>
              )}
            </div>
          </details>
        )}


        {/* Sprint 182 §2 — the preview panel. Creates nothing. */}
        {previewRow && (
          <div className="card" style={{ padding: 14, marginTop: 12 }} data-testid="facturen-preview-panel">
            <div className="section-head-title" style={{ marginBottom: 4 }}>
              {t("facturen.preview_title", { name: previewRow.customer_name })}
            </div>
            <p className="muted small" style={{ marginTop: 0 }}>
              {t("facturen.preview_disclaimer")}
            </p>
            {previewBusy && (
              <div className="loading-bar">
                <div className="loading-bar-fill" />
              </div>
            )}
            {!previewBusy && preview && preview.invoice_count === 0 && (
              <>
                <div className="section-head-title" data-testid="facturen-preview-empty-heading">
                  {t("invoices:nothing.heading")}
                </div>
                <p className="muted small" data-testid="facturen-preview-empty">
                  {nothingSentence(t, preview.nothing_reason) ?? t("facturen.preview_empty")}
                </p>
              </>
            )}
            {!previewBusy && preview && preview.invoice_count > 0 && (
              <>
                <div className="table-wrap">
                  <table className="data-table" data-testid="facturen-preview-table">
                    <thead>
                      <tr>
                        <th>{t("facturen.preview_col_addressed_to")}</th>
                        <th style={{ textAlign: "right" }}>{t("facturen.preview_col_lines")}</th>
                        <th style={{ textAlign: "right" }}>{t("facturen.preview_col_total")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.invoices.map((planned, index) => (
                        <tr
                          key={`${planned.building ?? "customer"}-${planned.department ?? "d"}-${planned.work_type ?? "w"}-${index}`}
                          data-testid="facturen-preview-row"
                        >
                          <td>{planned.building_name ?? t("facturen.preview_customer_level")}</td>
                          <td style={{ textAlign: "right" }}>{planned.line_count}</td>
                          <td style={{ textAlign: "right" }}>{formatMoney(planned.total_amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="muted small" data-testid="facturen-preview-computed-at">
                  {t("facturen.preview_computed_at", { when: formatDateTime(preview.computed_at) })}
                </p>
              </>
            )}
            <div className="form-actions" style={{ marginTop: 12 }}>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setPreviewRow(null);
                  setPreview(null);
                }}
              >
                {t("facturen.preview_close")}
              </button>
              {!previewBusy && preview && preview.invoice_count > 0 && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={handleViewPreviewPdf}
                  data-testid="facturen-preview-view"
                >
                  {t("facturen.preview_view_pdf")}
                </button>
              )}
            </div>
          </div>
        )}

        {/* The generate panel — two questions, one consequence, one button. */}
        {genRow && (
          <div className="card" style={{ marginTop: 12 }} data-testid="facturen-generate-panel">
            <div className="form-section" style={{ padding: "16px 18px" }}>
              <div className="section-head-title">
                {t("facturen.gen_title", { name: genRow.customer_name })}
              </div>
              <div className="form-section-title">
                <span className="ew-plan-step">1</span>
                {t("facturen.gen_step_month")}
              </div>
              {periodsSentence(t, duePeriods[genRow.customer]) && (
                <p className="muted small" style={{ margin: "-8px 0 0" }} data-testid="facturen-generate-periods">
                  {periodsSentence(t, duePeriods[genRow.customer])}
                </p>
              )}
              <label className="field" style={{ maxWidth: 220 }}>
                <span className="field-label">{t("facturen.gen_month")}</span>
                <input
                  className="field-input"
                  type="month"
                  value={genMonth}
                  onChange={(e) => setGenMonth(e.target.value)}
                  data-testid="facturen-generate-month"
                />
              </label>
            </div>
            <div className="form-section" style={{ padding: "16px 18px" }}>
              <div className="form-section-title">
                <span className="ew-plan-step">2</span>
                {t("facturen.gen_step_target")}
              </div>
              {/* Sprint 183 §1 — the SAME component customer settings uses. */}
              <BillingTargetFields
                idPrefix="facturen-gen"
                target={genTarget}
                split={genSplit}
                onTargetChange={setGenTarget}
                onSplitChange={setGenSplit}
                disabled={genBusy}
              />
              <p className="muted small" style={{ margin: 0 }}>
                {t("invoices:billing.this_run_only")}
              </p>
            </div>
            <div className="form-section" style={{ padding: "14px 18px" }}>
              <p className="muted small" style={{ margin: 0 }} data-testid="facturen-generate-consequence">
                {genParsed
                  ? t("facturen.gen_consequence", {
                      name: genRow.customer_name,
                      period: formatPeriod(genParsed.year, genParsed.month),
                    })
                  : t("facturen.gen_confirm_no_month")}
              </p>
              <div className="form-actions" style={{ marginTop: 4 }}>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setGenRow(null)}
                  disabled={genBusy}
                >
                  {t("facturen.gen_cancel")}
                </button>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  onClick={handleGenerate}
                  disabled={genBusy || !genParsed}
                  title={genParsed ? undefined : t("facturen.gen_confirm_no_month")}
                  data-testid="facturen-generate-confirm"
                >
                  {genParsed
                    ? t("facturen.gen_confirm_for", { period: formatPeriod(genParsed.year, genParsed.month) })
                    : t("facturen.gen_confirm_no_month")}
                </button>
              </div>
              {/* P-13 §D.24 rule 8 — the pre-read under the button. */}
              <WhatHappens testId="facturen-generate-what">
                {t("invoices:road.what_generate")}
              </WhatHappens>
            </div>
          </div>
        )}
      </section>
      )}

      {/* ---- The three list steps: Drafts, Issued, Sent ---- */}
      {activeTab !== "due" && (
      <section className="card" style={{ padding: 16 }} data-testid="facturen-list-card">
        <div className="ew-list-filters" data-testid="facturen-filters">
          <div className="filter-field search">
            <Search size={14} strokeWidth={2.2} aria-hidden="true" />
            <input
              className="filter-control"
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t("facturen.search_placeholder")}
              aria-label={t("facturen.search_placeholder")}
              data-testid="facturen-search"
            />
          </div>
          <details className="filter-fold" open={activeFilterChips.length > 0} data-testid="facturen-filter-fold">
            <summary className="filter-fold-summary" data-testid="facturen-filter-toggle">
              <SlidersHorizontal size={14} strokeWidth={2.4} aria-hidden="true" />
              {t("facturen.filter_fold")}
              {activeFilterChips.length > 0 && (
                <span className="filter-fold-count">
                  {t("facturen.filter_active", { count: activeFilterChips.length })}
                </span>
              )}
              {activeFilterChips.map((label) => (
                <span className="filter-fold-chip" key={label}>{label}</span>
              ))}
            </summary>
            <div className="filter-fold-body">
              <div className="filter-field">
                <span className="filter-label">{t("facturen.filter_period")}</span>
                <input
                  className="filter-control"
                  type="month"
                  value={periodMonth}
                  onChange={(e) => setPeriodMonth(e.target.value)}
                  data-testid="facturen-filter-period"
                />
              </div>
              {!customerScoped && (
                <div className="filter-field">
                  <span className="filter-label">{t("facturen.filter_customer")}</span>
                  <select
                    className="filter-control"
                    value={customerFilter}
                    onChange={(e) => setCustomerFilter(e.target.value)}
                    data-testid="facturen-filter-customer"
                  >
                    <option value="ALL">{t("facturen.filter_all")}</option>
                    {customerOptions.map(([cid, name]) => (
                      <option key={cid} value={String(cid)}>{name}</option>
                    ))}
                  </select>
                </div>
              )}
              <div className="filter-field">
                <span className="filter-label">{t("facturen.filter_building")}</span>
                <select
                  className="filter-control"
                  value={buildingFilter}
                  onChange={(e) => setBuildingFilter(e.target.value)}
                  data-testid="facturen-filter-building"
                >
                  <option value="ALL">{t("facturen.filter_all")}</option>
                  {buildingOptions.map(([bid, name]) => (
                    <option key={bid} value={String(bid)}>{name}</option>
                  ))}
                </select>
              </div>
              {anyFilter && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={clearFilters} data-testid="facturen-filter-clear">
                  {t("facturen.filter_clear")}
                </button>
              )}
            </div>
          </details>
        </div>

        {loading ? (
          <div className="loading-bar" style={{ marginTop: 12 }}>
            <div className="loading-bar-fill" />
          </div>
        ) : visibleInvoices.length === 0 && !anyFilter ? (
          /* §D.24 rule 5 — the empty step teaches how a row gets here. */
          <TeachEmpty
            testId={`facturen-road-empty-${activeTab}`}
            title={t(`invoices:road.${activeTab}_empty_title`)}
            body={t(`invoices:road.${activeTab}_empty_body`)}
          />
        ) : visibleInvoices.length === 0 ? (
          <EmptyState
            icon={BadgeEuro}
            title={t("facturen.list_empty_filtered_title")}
            description={t("facturen.list_empty_filtered_desc")}
            compact
            action={
              <button type="button" className="btn btn-secondary btn-sm" onClick={clearFilters}>
                {t("facturen.filter_clear")}
              </button>
            }
            testId="facturen-list-empty-filtered"
          />
        ) : (
          <BoundedList
            size="lg"
            count={visibleInvoices.length}
            ariaLabel={t("facturen.list_title")}
            testIdPrefix="facturen-list"
            className="table-wrap"
          >
            <table className="data-table" data-testid="facturen-list-table" style={{ marginTop: 12 }}>
              <thead>
                <tr>
                  <th>
                    {activeTab === "drafts"
                      ? t("invoices:road.col_draft")
                      : t("facturen.col_number")}
                  </th>
                  {!customerScoped && <th>{t("facturen.col_customer")}</th>}
                  {activeTab === "drafts" && <th>{t("invoices:road.col_lines")}</th>}
                  {activeTab === "issued" && <th>{t("invoices:road.col_issued")}</th>}
                  {activeTab === "sent" && <th>{t("invoices:road.col_sent")}</th>}
                  <th style={{ textAlign: "right" }}>{t("facturen.col_total")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {[...visibleInvoices]
                  .sort((a, b) => b.id - a.id)
                  .map((inv) => {
                    const unsentCredit = inv.is_reversal && inv.status === "ISSUED";
                    const isNew = newDraftIds.includes(inv.id);
                    return (
                      <ClickableRow
                        key={inv.id}
                        to={`/invoices/${inv.id}`}
                        testId="facturen-list-row"
                        className={isNew ? HIGHLIGHT_CLASS : undefined}
                      >
                        <td>
                          <Link to={`/invoices/${inv.id}`} className="link" onClick={(e) => e.stopPropagation()}>
                            {activeTab === "drafts"
                              ? formatPeriod(inv.period_year, inv.period_month) ||
                                t("facturen.concept")
                              : (inv.number ?? t("facturen.concept"))}
                          </Link>
                          {isNew && (
                            <span className="cell-tag cell-tag-open" style={{ marginLeft: 8 }} data-testid="facturen-row-new">
                              <i />
                              {t("invoices:road.row_new")}
                            </span>
                          )}
                          {unsentCredit && (
                            <span className="cell-tag cell-tag-warn" style={{ marginLeft: 8 }}>
                              <i />
                              {t("facturen.credit_note_unsent")}
                            </span>
                          )}
                          {inv.is_reversal && !unsentCredit && (
                            <span className="muted small" style={{ marginLeft: 6 }}>({t("facturen.credit_note")})</span>
                          )}
                          {inv.credited_by_number && (
                            <span className="muted small" style={{ marginLeft: 6 }}>
                              ({t("facturen.credited_by", { number: inv.credited_by_number })})
                            </span>
                          )}
                          <div className="muted small">
                            {activeTab === "drafts"
                              ? t("invoices:road.made_when", {
                                  when: formatDate(inv.created_at),
                                })
                              : activeTab === "issued"
                                ? `${t("facturen.concept_number_hint")} \u00b7 ${formatPeriod(inv.period_year, inv.period_month)}`
                                : formatPeriod(inv.period_year, inv.period_month)}
                            {" \u00b7 "}
                            {inv.company_name}
                          </div>
                        </td>
                        {!customerScoped && (
                          <td>
                            {canOpenCustomer ? (
                              <Link
                                to={`/admin/customers/${inv.customer}`}
                                className="row-fact-link"
                                data-testid="facturen-row-customer"
                                onClick={(e) => e.stopPropagation()}
                              >
                                {inv.customer_name}
                              </Link>
                            ) : (
                              inv.customer_name
                            )}
                          </td>
                        )}
                        {activeTab === "drafts" && (
                          <td className="muted small" data-testid="facturen-row-lines">
                            {draftLinesSummary(inv, t)}
                          </td>
                        )}
                        {activeTab === "issued" && (
                          <td className="muted small">
                            {inv.issued_at ? formatDate(inv.issued_at) : "\u2014"}
                          </td>
                        )}
                        {activeTab === "sent" && (
                          <td className="muted small">
                            {inv.sent_at ? formatDate(inv.sent_at) : "\u2014"}
                          </td>
                        )}
                        <td style={{ textAlign: "right" }}>
                          <strong>{formatMoney(inv.total_amount)}</strong>
                        </td>
                        {/* §D.22 item 7 — ONE next-step button, the
                            detail banner's words; it opens the detail,
                            where the real action (issue, send) lives. */}
                        <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                          <Link
                            to={`/invoices/${inv.id}`}
                            className="btn btn-secondary btn-sm"
                            onClick={(e) => e.stopPropagation()}
                            data-testid="facturen-row-next"
                          >
                            {t(NEXT_STEP_KEY[inv.status])}
                          </Link>
                        </td>
                      </ClickableRow>
                    );
                  })}
              </tbody>
            </table>
          </BoundedList>
        )}
      </section>
      )}

      {/* W17 — always mounted, opened through the ref only. */}
      <PdfPreviewDialog ref={previewPdfRef} withDownload={false} />

      {/* P-13 A (W1) — the billing-day dialog, from the no-day row and
          its Start-here card. A non-native overlay (ChoiceDialog's
          pattern), so conditional mounting is safe. */}
      {dayRow && (
        <BillingDayDialog
          customerId={dayRow.customer}
          customerName={dayRow.customer_name}
          current={{
            invoice_day_of_month: dayRow.invoice_day_of_month,
            invoice_day_rule: dayRow.invoice_day_rule,
          }}
          onCancel={() => setDayRow(null)}
          onSaved={() => {
            const name = dayRow.customer_name;
            setDayRow(null);
            setRefreshKey((k) => k + 1);
            facDone.announce({
              title: t("invoices:road.day_set_title", { name }),
              body: t("invoices:road.day_set_body"),
            });
          }}
        />
      )}
    </div>
  );
}
