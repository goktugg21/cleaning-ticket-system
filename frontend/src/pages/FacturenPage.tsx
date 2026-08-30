// Invoicing Phase 4b — the provider "Facturen" page.
//
// P-6 V1 (Addendum D §D.6 rule 12, rules 13–15) — the page reads top to
// bottom as one story: where you stand (four facts), what is due now
// (one primary action per row), what will not reach the invoice (the
// billing-month guard, folded with its count), and every invoice made
// so far, grouped by month so the "Invoices → customer → month"
// sentence from the meerwerk pages lands somewhere literal.
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
import { BadgeEuro, CheckCircle2, Search, SlidersHorizontal } from "lucide-react";

import { getApiError } from "../api/client";
import {
  generateInvoices,
  getBillingMonthAtRisk,
  getInvoiceDueList,
  getInvoicePreview,
  granularityFor,
  listAllInvoices,
  pairForGranularity,
  type AtRiskGroup,
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
import { BoundedList } from "../components/BoundedList";
import { ClickableRow } from "../components/ClickableRow";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import {
  PdfPreviewDialog,
  type PdfPreviewDialogHandle,
} from "../components/PdfPreviewDialog";
import { StatusTiles } from "../components/StatusTiles";
import { useToast } from "../components/ToastProvider";
import { monthName } from "../lib/billingSentence";
import { customerLabelName } from "../lib/customerLabelName";
import {
  formatDate,
  formatDateTime,
  formatInvoiceGroupLabel,
  formatMoney,
} from "../lib/intl";

type StatusFilter = InvoiceStatus | "";

// WP-1 G4 — human words for the guard's machine stages.
const AT_RISK_STAGE_KEYS: Record<AtRiskStage, string> = {
  WAITING_REVIEW: "facturen.at_risk_stage_waiting_review",
  SLOT_DONE: "facturen.at_risk_stage_slot_done",
  BLOCKED: "facturen.at_risk_stage_blocked",
  PAST_DEADLINE: "facturen.at_risk_stage_past_deadline",
};

const STATUS_LABEL_KEY: Record<InvoiceStatus, string> = {
  DRAFT: "facturen.status_draft",
  ISSUED: "facturen.status_issued",
  SENT: "facturen.status_sent",
};

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

function formatPeriod(year: number | null, month: number | null): string {
  if (!year || !month) return "";
  return `${String(month).padStart(2, "0")}-${year}`;
}

/** "Augustus 2026" — the month as a word, capitalised for a heading. */
function periodHeading(year: number, month: number): string {
  const words = monthName(`${year}-${String(month).padStart(2, "0")}`);
  return words.charAt(0).toUpperCase() + words.slice(1);
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

interface InvoiceGroup {
  key: string;
  label: string;
  rows: Invoice[];
  total: string;
}

export function FacturenPage({
  customerId,
  embedded = false,
}: {
  customerId?: number;
  embedded?: boolean;
} = {}) {
  const { t } = useTranslation(["common", "invoices"]);
  const { push: pushToast } = useToast();
  const customerScoped = customerId !== undefined;
  // P-6 V1 — the "Invoices → customer → month" sentence on the meerwerk
  // pages links here with `?customer=<id>&period=YYYY-MM`; the page opens
  // on exactly that customer and month.
  const [searchParams] = useSearchParams();

  const [dueRows, setDueRows] = useState<InvoiceDueRow[]>([]);
  const [dueLoading, setDueLoading] = useState(true);
  const [atRiskGroups, setAtRiskGroups] = useState<AtRiskGroup[]>([]);
  const [atRiskTruncated, setAtRiskTruncated] = useState(false);
  const [duePeriods, setDuePeriods] = useState<Record<number, UnbilledPeriods>>({});
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  // List filters. customer (pinned) + period narrow server-side; status,
  // building and the search narrow client-side over the loaded set.
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("");
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

  // Generate control — opened from a due row; a single inline panel.
  const [genRow, setGenRow] = useState<InvoiceDueRow | null>(null);
  const [genMonth, setGenMonth] = useState("");
  const [genTarget, setGenTarget] = useState<InvoiceBillingTarget>("CUSTOMER");
  const [genSplit, setGenSplit] = useState<InvoiceSplit>("NONE");
  const [genBusy, setGenBusy] = useState(false);

  // Sprint 182 §2 — the preview. NOTHING IS STORED server-side.
  const [previewRow, setPreviewRow] = useState<InvoiceDueRow | null>(null);
  const [preview, setPreview] = useState<InvoicePreview | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const previewPdfRef = useRef<PdfPreviewDialogHandle>(null);

  // Due panel — loaded in BOTH modes, narrowed to the pinned customer.
  useEffect(() => {
    let cancelled = false;
    async function loadDue() {
      try {
        const rows = await getInvoiceDueList();
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
  }, [customerId, refreshKey]);

  // WP-1 G4 — the at-risk rows. A failed fetch keeps its silence.
  useEffect(() => {
    let cancelled = false;
    async function loadAtRisk() {
      try {
        const data = await getBillingMonthAtRisk();
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
  }, [customerId, refreshKey]);

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
  }, [customerId, period, refreshKey]);

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

  // Everything but the status tile — the tiles count within this set.
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

  const visibleInvoices = useMemo(
    () => (statusFilter === "" ? baseVisible : baseVisible.filter((inv) => inv.status === statusFilter)),
    [baseVisible, statusFilter],
  );

  // Grouped by billing month, newest first; invoices without a period
  // close the list under their own heading.
  const groups = useMemo<InvoiceGroup[]>(() => {
    const byKey = new Map<string, Invoice[]>();
    for (const inv of visibleInvoices) {
      const key = inv.period_year && inv.period_month
        ? `${inv.period_year}-${String(inv.period_month).padStart(2, "0")}`
        : "none";
      const bucket = byKey.get(key);
      if (bucket) bucket.push(inv);
      else byKey.set(key, [inv]);
    }
    const keys = [...byKey.keys()].sort((a, b) => {
      if (a === "none") return 1;
      if (b === "none") return -1;
      return b.localeCompare(a);
    });
    return keys.map((key) => {
      const rows = [...(byKey.get(key) ?? [])].sort(
        (a, b) => a.customer_name.localeCompare(b.customer_name) || b.id - a.id,
      );
      const parsed = key === "none" ? null : parseMonth(key);
      return {
        key,
        label: parsed ? periodHeading(parsed.year, parsed.month) : t("facturen.group_no_period"),
        rows,
        total: sumAmounts(rows.map((row) => row.total_amount)),
      };
    });
  }, [visibleInvoices, t]);

  // Rule 13 — a column whose every value would be empty is absent.
  const showGroupLabelColumn = visibleInvoices.some(
    (inv) => inv.department_name || inv.work_type_name,
  );
  const showBuildingColumn = visibleInvoices.some((inv) => inv.building !== null);

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

  const anyFilter = activeFilterChips.length > 0 || search.trim() !== "" || statusFilter !== "";

  function clearFilters() {
    setPeriodMonth("");
    setCustomerFilter("ALL");
    setBuildingFilter("ALL");
    setSearch("");
    setStatusFilter("");
  }

  // The four facts.
  const dueNowRows = dueRows.filter((row) => row.unbilled_count > 0);
  const dueNowTotal = sumAmounts(dueNowRows.map((row) => row.unbilled_total));
  const draftRows = invoices.filter((inv) => inv.status === "DRAFT");
  const issuedRows = invoices.filter((inv) => inv.status === "ISSUED");
  const atRiskCount = atRiskGroups.reduce((total, group) => total + group.rows.length, 0);

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
        pushToast({
          variant: "success",
          title: t("facturen.gen_toast", { count: created.length }),
        });
      } else {
        const attempted = formatPeriod(parsed.year, parsed.month);
        const elsewhere = periodListLabel(duePeriods[genRow.customer]);
        pushToast({
          variant: "info",
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
  const columnCount =
    2 + (customerScoped ? 0 : 1) + (showBuildingColumn ? 1 : 0) + (showGroupLabelColumn ? 1 : 0) + 1;

  return (
    <div data-testid="facturen-page">
      {!embedded && (
        <PageHeader
          eyebrow={t("facturen.eyebrow")}
          title={t("facturen.title")}
          subtitle={t("facturen.subtitle")}
        />
      )}

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* ---- Where you stand: four facts ---- */}
      <div className="facts" data-testid="facturen-facts">
        <div className="ew-ctx-block" data-testid="facturen-fact-due">
          <div className="ew-ctx-label">{t("facturen.fact_due_label")}</div>
          <div className="ew-ctx-body">
            <div className={dueNowRows.length > 0 ? "ew-ctx-strong ew-ctx-money" : "ew-ctx-strong"}>
              {dueLoading
                ? "…"
                : dueNowRows.length > 0
                  ? t("facturen.fact_due_value", { count: dueNowRows.length })
                  : t("facturen.fact_due_none")}
            </div>
            <div className="ew-ctx-sub">
              {dueLoading
                ? ""
                : dueNowRows.length > 0
                  ? t("facturen.fact_due_sub", { amount: formatMoney(dueNowTotal) })
                  : t("facturen.fact_due_sub_none")}
            </div>
          </div>
        </div>
        <div className="ew-ctx-block" data-testid="facturen-fact-drafts">
          <div className="ew-ctx-label">{t("facturen.fact_drafts_label")}</div>
          <div className="ew-ctx-body">
            <div className="ew-ctx-strong">
              {loading
                ? "…"
                : draftRows.length > 0
                  ? t("facturen.fact_drafts_value", { count: draftRows.length })
                  : t("facturen.fact_drafts_none")}
            </div>
            <div className="ew-ctx-sub">
              {!loading && draftRows.length > 0
                ? `${formatMoney(sumAmounts(draftRows.map((row) => row.total_amount)))} · ${t("facturen.fact_drafts_sub")}`
                : ""}
            </div>
          </div>
        </div>
        <div className="ew-ctx-block" data-testid="facturen-fact-issued">
          <div className="ew-ctx-label">{t("facturen.fact_issued_label")}</div>
          <div className="ew-ctx-body">
            <div className="ew-ctx-strong">
              {loading
                ? "…"
                : issuedRows.length > 0
                  ? t("facturen.fact_issued_value", { count: issuedRows.length })
                  : t("facturen.fact_issued_none")}
            </div>
            <div className="ew-ctx-sub">
              {!loading && issuedRows.length > 0 ? t("facturen.fact_issued_sub") : ""}
            </div>
          </div>
        </div>
        <div className="ew-ctx-block" data-testid="facturen-fact-risk">
          <div className="ew-ctx-label">{t("facturen.fact_risk_label")}</div>
          <div className="ew-ctx-body">
            <div className={atRiskCount > 0 ? "ew-ctx-strong ew-ctx-unpriced" : "ew-ctx-strong"}>
              {atRiskCount > 0
                ? t("facturen.fact_risk_value", { count: atRiskCount })
                : t("facturen.fact_risk_none")}
            </div>
            <div className="ew-ctx-sub">{atRiskCount > 0 ? t("facturen.fact_risk_sub") : ""}</div>
          </div>
        </div>
      </div>

      {/* ---- Due panel ---- */}
      <section
        className="card"
        style={{ padding: 16, marginBottom: 16 }}
        data-testid="facturen-due-panel"
      >
        <div className="section-head" style={{ marginBottom: 10 }}>
          <div>
            <div className="section-head-title">{t("facturen.due_title")}</div>
            <div className="section-head-sub">
              {customerScoped ? t("facturen.due_sub_customer") : t("facturen.due_sub")}
            </div>
          </div>
        </div>
        {dueLoading ? (
          <div className="loading-bar">
            <div className="loading-bar-fill" />
          </div>
        ) : dueRows.length === 0 ? (
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
          <div style={{ overflowX: "auto" }}>
            <table className="data-table" data-testid="facturen-due-table">
              <thead>
                <tr>
                  <th>{t("facturen.col_customer")}</th>
                  <th>{t("facturen.due_col_schedule")}</th>
                  <th>{t("facturen.due_col_unbilled")}</th>
                  <th style={{ textAlign: "right" }}>{t("facturen.col_total")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {dueRows.map((row) => {
                  const ready = row.unbilled_count > 0;
                  return (
                    <tr key={row.customer} data-testid="facturen-due-row" data-ready={ready}>
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
                      </td>
                      {/* W-HK1 §2 — the backend's order: a fixed day wins
                          over the FIRST/LAST rule. */}
                      <td className="muted small">
                        {row.invoice_day_of_month != null
                          ? t("facturatie.day_of_month", { day: row.invoice_day_of_month })
                          : row.invoice_day_rule === "FIRST_OF_MONTH"
                            ? t("facturatie.day_first")
                            : row.invoice_day_rule === "LAST_OF_MONTH"
                              ? t("facturatie.day_last")
                              : t("facturen.no_schedule")}
                      </td>
                      <td>
                        <strong>{row.unbilled_count}</strong>
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
                        {ready ? <strong>{formatMoney(row.unbilled_total)}</strong> : ""}
                      </td>
                      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        {/* One primary per row; a row with nothing to
                            generate carries its reason in words instead
                            of two dead buttons (rules 3 and 14). */}
                        {ready ? (
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
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
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
            </div>
          </div>
        )}
      </section>

      {/* ---- WP-1 G4: the billing-month guard, folded with its count ---- */}
      {atRiskGroups.length === 0 ? (
        <p className="facturen-clear" data-testid="facturen-at-risk-clear">
          <CheckCircle2 size={16} strokeWidth={2.4} aria-hidden="true" />
          <span>
            <strong>{t("facturen.at_risk_clear_title")}</strong>{" "}
            <span className="muted">{t("facturen.at_risk_clear_sub")}</span>
          </span>
        </p>
      ) : (
        <details className="form-fold" data-testid="facturen-at-risk-panel">
          <summary className="form-fold-summary">
            {t("facturen.at_risk_title")}
            <span className="form-fold-summary-value">
              {t("facturen.fact_risk_value", { count: atRiskCount })}
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
                      <tr key={`${group.customer}-${row.extra_work_id}`} data-testid="facturen-at-risk-row">
                        {!customerScoped && <td>{group.customer_name}</td>}
                        <td>
                          <Link
                            to={row.ticket_id !== null ? `/tickets/${row.ticket_id}` : `/extra-work/${row.extra_work_id}`}
                          >
                            {row.ticket_no ? `${row.ticket_no} · ` : ""}
                            {row.title}
                          </Link>
                          {row.building_name && <div className="muted small">{row.building_name}</div>}
                        </td>
                        <td>{t(AT_RISK_STAGE_KEYS[row.stage])}</td>
                        <td>{t("facturen.at_risk_age", { count: row.age_days })}</td>
                        <td>{formatDate(`${row.date}T00:00:00`)}</td>
                      </tr>
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

      {/* ---- Invoice list ---- */}
      <section className="card" style={{ padding: 16 }} data-testid="facturen-list-card">
        <div className="section-head" style={{ marginBottom: 10 }}>
          <div>
            <div className="section-head-title">{t("facturen.list_title")}</div>
            <div className="section-head-sub">
              {loading ? "" : t("facturen.list_count", { count: visibleInvoices.length })}
            </div>
          </div>
        </div>

        <StatusTiles
          tiles={(["DRAFT", "ISSUED", "SENT"] as InvoiceStatus[]).map((status) => ({
            value: status,
            label: t(STATUS_LABEL_KEY[status]),
            count: statusCounts[status],
          }))}
          active={statusFilter}
          onChange={(value) => setStatusFilter(value as StatusFilter)}
          totalCount={baseVisible.length}
          testIdPrefix="facturen-status"
        />

        <div className="ew-list-filters" style={{ marginTop: 12 }} data-testid="facturen-filters">
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
        ) : invoices.length === 0 && !anyFilter ? (
          <EmptyState
            icon={BadgeEuro}
            title={t("facturen.list_empty_title")}
            description={t("facturen.list_empty_desc")}
            testId="facturen-list-empty"
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
                  <th>{t("facturen.col_number")}</th>
                  <th style={{ textAlign: "right" }}>{t("facturen.col_total")}</th>
                  {!customerScoped && <th>{t("facturen.col_customer")}</th>}
                  {showBuildingColumn && <th>{t("facturen.col_building")}</th>}
                  {showGroupLabelColumn && <th>{t("facturen.col_department_work_type")}</th>}
                  <th>{t("facturen.col_status")}</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => (
                  <GroupRows
                    key={group.key}
                    group={group}
                    columnCount={columnCount}
                    customerScoped={customerScoped}
                    showBuildingColumn={showBuildingColumn}
                    showGroupLabelColumn={showGroupLabelColumn}
                    t={t}
                  />
                ))}
              </tbody>
            </table>
          </BoundedList>
        )}
      </section>

      {/* W17 — always mounted, opened through the ref only. */}
      <PdfPreviewDialog ref={previewPdfRef} withDownload={false} />
    </div>
  );
}

function GroupRows({
  group,
  columnCount,
  customerScoped,
  showBuildingColumn,
  showGroupLabelColumn,
  t,
}: {
  group: InvoiceGroup;
  columnCount: number;
  customerScoped: boolean;
  showBuildingColumn: boolean;
  showGroupLabelColumn: boolean;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  return (
    <>
      <tr className="invoice-group-row" data-testid="facturen-group-row" data-group={group.key}>
        <td colSpan={columnCount}>
          <span className="invoice-group-label">{group.label}</span>
          <span className="invoice-group-meta">
            {t("facturen.list_count", { count: group.rows.length })} · {formatMoney(group.total)}
          </span>
        </td>
      </tr>
      {group.rows.map((inv) => {
        const unsentCredit = inv.is_reversal && inv.status === "ISSUED";
        return (
          <ClickableRow key={inv.id} to={`/invoices/${inv.id}`} testId="facturen-list-row">
            <td>
              <Link to={`/invoices/${inv.id}`} className="link" onClick={(e) => e.stopPropagation()}>
                {inv.number ?? t("facturen.concept")}
              </Link>
              {inv.is_reversal && (
                <span className="muted small" style={{ marginLeft: 6 }}>({t("facturen.credit_note")})</span>
              )}
              {inv.credited_by_number && (
                <span className="muted small" style={{ marginLeft: 6 }}>
                  ({t("facturen.credited_by", { number: inv.credited_by_number })})
                </span>
              )}
              <div className="muted small">
                {inv.number === null ? `${t("facturen.concept_number_hint")} · ` : ""}
                {inv.company_name} · {inv.created_by_label || t("invoices:created_by.system")}
              </div>
            </td>
            <td style={{ textAlign: "right" }}>
              <strong>{formatMoney(inv.total_amount)}</strong>
            </td>
            {!customerScoped && <td>{inv.customer_name}</td>}
            {showBuildingColumn && (
              <td className="muted small">{inv.building_name ?? t("facturen.all_buildings")}</td>
            )}
            {showGroupLabelColumn && (
              <td className="muted small">
                {formatInvoiceGroupLabel(
                  customerLabelName(inv.department_name, t),
                  customerLabelName(inv.work_type_name, t),
                )}
              </td>
            )}
            <td>
              <span
                className={
                  unsentCredit
                    ? "cell-tag cell-tag-warn"
                    : inv.status === "SENT"
                      ? "cell-tag cell-tag-open"
                      : "cell-tag cell-tag-closed"
                }
                data-testid="facturen-list-status"
              >
                <i />
                {unsentCredit ? t("facturen.credit_note_unsent") : t(STATUS_LABEL_KEY[inv.status])}
              </span>
            </td>
          </ClickableRow>
        );
      })}
    </>
  );
}
