// Invoicing Phase 4b — the provider "Facturen" page.
//
// Replaces the old RF-13 InvoicesPage (which grouped the month's billable
// Extra Work). This page is driven by the Phase-4a invoice REST surface:
//
//   * a "Due now / upcoming" panel on top  (GET /api/invoices/due/), with a
//     per-row "Genereer" control that generates draft invoice(s) for that
//     customer + period, using the customer's granularity default with a
//     per-generation OVERRIDE toggle (one invoice / per building);
//   * the full invoice list below           (GET /api/invoices/ with the
//     customer / building / status / period filters), each row linking to
//     the dedicated invoice-detail page.
//
// Reusable: with `customerId` set the page is customer-scoped, and
// `embedded` drops the standalone header (the customer sub-page header
// renders instead). Used by CustomerInvoicesPage.
//
// Sprint 186 §2 — "customer-scoped" used to mean a LESSER page: no due
// panel, no preview, no generate, and a card whose only content was a
// link to the real one. Three of the four customer work sub-pages mount
// the main component with the customer pinned; this was the one that
// mounted a reduced copy, so an operator standing on a customer had to
// leave, find that customer again in a provider-wide list, and generate
// from there. It is now the SAME page with one pin.
//
// What "pinned" means, precisely — and what the `customerScoped` guards
// below are protecting:
//   * `customer` is passed to the list endpoint, server-side;
//   * the customer FILTER dropdown is not rendered, so the pin cannot be
//     widened from inside the page;
//   * the customer COLUMN is not rendered, because every row is that one
//     customer;
//   * the Due panel is narrowed to that customer client-side (see the
//     effect). Leaving it provider-wide would list OTHER customers on
//     this customer's page, which is the cross-tenant surprise the
//     customer chips shipped last week.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { BadgeEuro } from "lucide-react";

import { getApiError } from "../api/client";
import {
  generateInvoices,
  getInvoiceDueList,
  getInvoicePreview,
  granularityFor,
  listAllInvoices,
  pairForGranularity,
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
// Sprint 183 §1 — the shared billing controls, used identically by
// customer settings so the two screens cannot word this differently.
import { BillingTargetFields } from "../components/BillingTargetFields";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import {
  PdfPreviewDialog,
  type PdfPreviewDialogHandle,
} from "../components/PdfPreviewDialog";
import { useToast } from "../components/ToastProvider";
import { customerLabelName } from "../lib/customerLabelName";
import {
  formatDateTime,
  formatInvoiceGroupLabel,
  formatMoney,
} from "../lib/intl";

type StatusFilter = InvoiceStatus | "ALL";

/** Sprint 183 — the /due/ row carries three fields `api/types.ts` does
 *  not describe yet: the saved billing pair (Sprint 182 §3) and the
 *  Sprint 183 §2 "why is there nothing" diagnosis. `api/types.ts`
 *  belongs to another agent this round, so the shape is narrowed here.
 *  Optional throughout, so a server that predates either still renders. */
// Sprint 184 §5 — the local narrowings that stood here are gone.
// `InvoiceDueRow` in `api/types.ts` now describes the billing pair and
// the nothing-reason, and `Invoice` describes `created_by_label`. They
// were narrowed here only because that file belonged to another agent.

/** The one sentence, from the one diagnosis. Sprint 183 §2 — the same
 *  function answers for the Due panel and the preview, so this renderer
 *  is shared between them too rather than written twice. */
function nothingSentence(
  t: (key: string, opts?: Record<string, unknown>) => string,
  nothing: InvoiceNothingReason | undefined,
): string | null {
  if (!nothing || nothing.reason === "NOTHING_TO_EXPLAIN") return null;
  if (nothing.reason === "NO_EXTRA_WORK") {
    return t("invoices:nothing.no_extra_work");
  }
  if (nothing.reason === "NONE_FINISHED") {
    return t("invoices:nothing.none_finished", {
      count: nothing.unbilled_count,
    });
  }
  if (nothing.reason === "NOT_IN_PERIOD") {
    return t("invoices:nothing.not_in_period", {
      count: nothing.finished_count,
    });
  }
  return t("invoices:nothing.all_invoiced", {
    count: nothing.invoiced_count,
  });
}

const STATUS_LABEL_KEY: Record<InvoiceStatus, string> = {
  DRAFT: "facturen.status_draft",
  ISSUED: "facturen.status_issued",
  SENT: "facturen.status_sent",
};

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
  if (!year || !month) return "—";
  return `${String(month).padStart(2, "0")}-${year}`;
}

/* ====================================================================
   W5 fix 4 — WHICH PERIOD the unbilled work belongs to.

   THE BUG THE OWNER HIT. The due panel and the Generate button answer
   two different questions and neither says which one it is answering.
   `unbilled_extra_work_through` (backend/invoicing/selectors.py:227)
   matches work billable in the current period OR ANY EARLIER one;
   `unbilled_extra_work` (:207) matches ONE EXACT period and is what
   `generate` runs. So work whose billing month is June shows as "1
   unbilled" in the August panel and generates nothing in August, and
   the screen explains none of that. Both selectors are correct and
   neither is touched here — what was missing is the period, said out
   loud, in three places: on the row, on the button, and in the answer
   when a run produces nothing.

   HOW THE PERIODS ARE FOUND, WITHOUT A NEW ENDPOINT. `/invoices/preview/`
   already takes a year and a month and already runs the THROUGH query,
   so `linesThrough(M) - linesThrough(M-1)` is the count that sits in
   exactly M. Walking back from the current period until the through
   count reaches zero yields every period that holds unbilled work,
   oldest last. Two facts make this cheap: the walk stops at the oldest
   period with work (typically one or two steps), and it is capped at
   `MAX_PERIOD_LOOKBACK` steps so a pathological customer cannot spend
   the panel's afternoon on it.

   The differencing is a count of ROWS, never money. Every amount on
   this page still comes from the server through `formatMoney`. */
const MAX_PERIOD_LOOKBACK = 13;

interface UnbilledPeriod {
  year: number;
  month: number;
  count: number;
}

interface UnbilledPeriods {
  /** Oldest first. Empty when the probe found nothing to attribute. */
  periods: UnbilledPeriod[];
  /** The walk hit its cap with work still older than the last period. */
  truncated: boolean;
}

function monthBefore(
  year: number,
  month: number,
): { year: number; month: number } {
  return month === 1
    ? { year: year - 1, month: 12 }
    : { year, month: month - 1 };
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
  let through = previewLineCount(
    await getInvoicePreview({ customer, year, month }),
  );
  let steps = 0;
  while (through > 0 && steps < MAX_PERIOD_LOOKBACK) {
    const earlier = monthBefore(cursor.year, cursor.month);
    const earlierThrough = previewLineCount(
      await getInvoicePreview({
        customer,
        year: earlier.year,
        month: earlier.month,
      }),
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

/** The row sentence. One period is named; several are given as a span. */
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

export function FacturenPage({
  customerId,
  embedded = false,
}: {
  customerId?: number;
  embedded?: boolean;
} = {}) {
  const { t } = useTranslation(["common", "invoices"]);
  const { push: pushToast } = useToast();
  const navigate = useNavigate();
  const customerScoped = customerId !== undefined;

  const [dueRows, setDueRows] = useState<InvoiceDueRow[]>([]);
  const [dueLoading, setDueLoading] = useState(true);
  // W5 fix 4 — resolved lazily per customer, keyed by customer id. An
  // absent entry means "not resolved yet or the probe failed", and a row
  // in that state simply says nothing rather than guessing a period.
  const [duePeriods, setDuePeriods] = useState<
    Record<number, UnbilledPeriods>
  >({});
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  // List filters. status + period narrow server-side; customer / building are
  // derived dropdowns applied client-side over the loaded set.
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");
  const [periodMonth, setPeriodMonth] = useState("");
  const [customerFilter, setCustomerFilter] = useState("ALL");
  const [buildingFilter, setBuildingFilter] = useState("ALL");

  // Generate control — opened from a due row; a single inline panel.
  const [genRow, setGenRow] = useState<InvoiceDueRow | null>(null);
  const [genMonth, setGenMonth] = useState("");
  // Sprint 183 §1 — the dialog speaks the SAME two controls as customer
  // settings. It used to offer the old three-value granularity list,
  // because Sprint 182 split the customer setting and never came back
  // here — so the two screens described one decision in two
  // vocabularies. Seeded from the customer's saved pair below; changing
  // it here overrides THIS RUN only and never writes the setting back.
  const [genTarget, setGenTarget] =
    useState<InvoiceBillingTarget>("CUSTOMER");
  const [genSplit, setGenSplit] = useState<InvoiceSplit>("NONE");
  const [genBusy, setGenBusy] = useState(false);

  // Sprint 182 §2 — the preview. NOTHING IS STORED server-side, so this
  // state is the only copy and it is thrown away when the panel closes;
  // reopening recomputes. That is the point: a stored preview is a draft
  // in all but name, and two kinds of draft is how you invoice twice.
  const [previewRow, setPreviewRow] = useState<InvoiceDueRow | null>(null);
  const [preview, setPreview] = useState<InvoicePreview | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  // W17 — the preview DOCUMENT opens in this in-app dialog, download-
  // less. Rendered unconditionally and driven through the ref (the
  // Sprint 118/128 native-<dialog> rule).
  const previewPdfRef = useRef<PdfPreviewDialogHandle>(null);

  // Due panel. Sprint 186 §2 — loaded in BOTH modes and narrowed to the
  // pinned customer when there is one.
  //
  // The narrowing is client-side because `/invoices/due/` takes no
  // customer parameter — it answers "who is due" over the caller's whole
  // scope, one row per scheduled customer, unpaginated. Adding the
  // parameter is a backend change and this is a frontend-only branch, so
  // the page filters the response instead. That is a display narrowing
  // over a response the server already tenant-scoped
  // (`scope_customers_for`), not a substitute for one; and the guard on
  // `/due/` is the SAME `_forbid_non_operator` that already gates the
  // invoice list this page loads either way, so no caller reaches this
  // fetch that was not already reaching that one.
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

  // W5 fix 4 — resolve WHICH periods each due row's unbilled work sits
  // in. Runs after the rows land, one row at a time rather than a burst,
  // and every state write happens in an async callback (never in the
  // effect body). A row whose probe throws keeps its silence: a missing
  // sentence is recoverable, a wrong period is not.
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

  // Invoice list. Sprint 120 — listAllInvoices pages exhaustively (the
  // plain listInvoices requests page_size=100 and never follows `next`,
  // so this list, its status/period filtering, and its totals used to
  // silently see only the first 100 matching invoices).
  const period = useMemo(() => parseMonth(periodMonth), [periodMonth]);
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const allInvoices = await listAllInvoices({
          customer: customerId,
          status: statusFilter === "ALL" ? undefined : statusFilter,
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
  }, [customerId, statusFilter, period, refreshKey]);

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

  const visibleInvoices = useMemo(() => {
    return invoices.filter((inv) => {
      if (
        !customerScoped &&
        customerFilter !== "ALL" &&
        String(inv.customer) !== customerFilter
      ) {
        return false;
      }
      if (buildingFilter !== "ALL" && String(inv.building) !== buildingFilter) {
        return false;
      }
      return true;
    });
  }, [invoices, customerScoped, customerFilter, buildingFilter]);

  function openGenerate(row: InvoiceDueRow) {
    setGenRow(row);
    // W5 fix 4 — open on the OLDEST period that actually holds unbilled
    // work, not on the current calendar month. `generate` targets one
    // exact period, so seeding it with "now" is what produced "0 drafts
    // generated" against a panel that had just said there was work. The
    // row's own period is the fallback for a customer whose probe has
    // not landed yet, which is the behaviour this replaces.
    const resolved = duePeriods[row.customer];
    const target = resolved?.periods[0];
    setGenMonth(
      target
        ? `${target.year}-${String(target.month).padStart(2, "0")}`
        : row.period_year && row.period_month
          ? `${row.period_year}-${String(row.period_month).padStart(2, "0")}`
          : currentMonthValue(),
    );
    // Seed from the customer's SAVED pair. The /due/ row carries both
    // (Sprint 182), with the legacy granularity as the fallback for a
    // server that predates them.
    if (row.invoice_billing_target) {
      setGenTarget(row.invoice_billing_target);
      setGenSplit(row.invoice_split ?? "NONE");
    } else {
      const pair = pairForGranularity(row.invoice_granularity_default);
      setGenTarget(pair.target);
      setGenSplit(pair.split);
    }
  }

  // Sprint 182 §2 — recomputed on every open, never cached across opens.
  async function openPreview(row: InvoiceDueRow) {
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
    // W17 — the owner's spec: the preview is something you LOOK AT, in
    // the app, at that moment, and nothing else. It used to open in a
    // new browser tab (a tab is a thing you keep) next to a download
    // button (a file is a thing you file). Now it renders inside the
    // in-app dialog with no download affordance; the dialog fetches
    // the blob itself and revokes it on close, so leaving the page
    // discards the document. Nothing is stored server-side either —
    // the endpoint plans and renders, never saves.
    if (!previewRow) return;
    previewPdfRef.current?.open({
      url:
        `/invoices/preview/?customer=${previewRow.customer}` +
        `&year=${previewRow.period_year}&month=${previewRow.period_month}` +
        `&download=pdf`,
      filename: t("facturen.preview_doc_name", {
        name: previewRow.customer_name,
      }),
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
        // legacy `granularity` field. Cheaper and lower-risk than a new
        // request shape: the endpoint already accepts it and the
        // customer serializer already translates a legacy write.
        granularity: granularityFor(genTarget, genSplit),
      });
      if (created.length > 0) {
        pushToast({
          variant: "success",
          title: t("facturen.gen_toast", { count: created.length }),
        });
      } else {
        // W5 fix 4 — "0 drafts generated" is a count, not an answer. Say
        // which period the run targeted and, when the probe knows,
        // where this customer's unbilled work actually is.
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
              {customerScoped
                ? t("facturen.due_sub_customer")
                : t("facturen.due_sub")}
            </div>
          </div>
        </div>
        {dueLoading ? (
          <div className="loading-bar">
            <div className="loading-bar-fill" />
          </div>
        ) : dueRows.length === 0 ? (
          <p className="muted small" data-testid="facturen-due-empty">
            {/* Sprint 186 §2 — an empty panel means two different
                things. Provider-wide it means nobody is due. On ONE
                customer it almost always means that customer has no
                billing schedule at all, because `/due/` only reports
                scheduled customers — so the page says which it is and
                where the schedule is set, instead of a "nothing due"
                that reads as a broken screen. */}
            {customerScoped
              ? t("facturen.due_empty_customer")
              : t("facturen.due_empty")}
          </p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table" data-testid="facturen-due-table">
              <thead>
                <tr>
                  <th>{t("facturen.col_customer")}</th>
                  <th>{t("facturen.due_col_schedule")}</th>
                  <th style={{ textAlign: "right" }}>
                    {t("facturen.due_col_unbilled")}
                  </th>
                  <th style={{ textAlign: "right" }}>
                    {t("facturen.col_total")}
                  </th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {dueRows.map((row) => (
                  <tr key={row.customer} data-testid="facturen-due-row">
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
                    <td className="muted small">
                      {row.invoice_day_rule === "FIRST_OF_MONTH"
                        ? t("facturatie.day_first")
                        : row.invoice_day_rule === "LAST_OF_MONTH"
                          ? t("facturatie.day_last")
                          : "—"}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {row.unbilled_count}
                      {/* Sprint 183 §2 — "I cannot generate anything
                          in Due now" was correct behaviour with no
                          explanation. The count alone says 0; this
                          says WHY it is 0 and what to go and look
                          at. */}
                      {nothingSentence(t, row.nothing_reason) && (
                        <span
                          className="muted small"
                          style={{ display: "block", textAlign: "left" }}
                          data-testid="facturen-due-nothing"
                        >
                          {nothingSentence(t, row.nothing_reason)}
                        </span>
                      )}
                      {/* W5 fix 4 — WHICH period this count is about.
                          The count comes from the THROUGH query, so a
                          "1" here can be June's work read in August;
                          without this line the panel and the Generate
                          button silently disagree. */}
                      {periodsSentence(t, duePeriods[row.customer]) && (
                        <span
                          className="muted small"
                          style={{ display: "block", textAlign: "left" }}
                          data-testid="facturen-due-periods"
                        >
                          {periodsSentence(t, duePeriods[row.customer])}
                        </span>
                      )}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {formatMoney(row.unbilled_total)}
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {/* Sprint 182 §2 — look before you cut. The
                          preview shows what a run WOULD produce, from
                          the same calculation that produces it. */}
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => openPreview(row)}
                        disabled={row.unbilled_count === 0}
                        data-testid="facturen-preview-open"
                        style={{ marginRight: 8 }}
                      >
                        {t("facturen.preview_open")}
                      </button>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={() => openGenerate(row)}
                        disabled={row.unbilled_count === 0}
                        data-testid="facturen-generate-open"
                      >
                        {t("facturen.generate")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Sprint 182 §2 — the preview panel. Read-only: it creates
            nothing and claims nothing, so it is safe to open at any
            time and safe to close without deciding anything. */}
        {previewRow && (
          <div
            className="card"
            style={{ padding: 14, marginTop: 12 }}
            data-testid="facturen-preview-panel"
          >
            <div className="section-head-title" style={{ marginBottom: 4 }}>
              {t("facturen.preview_title", {
                name: previewRow.customer_name,
              })}
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
                {/* Sprint 187 §7.2 — the heading this empty state was
                    always supposed to have. It has been translated in
                    BOTH bundles since Sprint 183 and rendered by
                    nothing, so the panel showed a lone diagnostic
                    sentence with no title above it and read like a
                    stray line rather than an answer. */}
                <div
                  className="section-head-title"
                  data-testid="facturen-preview-empty-heading"
                >
                  {t("invoices:nothing.heading")}
                </div>
                <p className="muted small" data-testid="facturen-preview-empty">
                  {/* Sprint 183 §2 — the SAME sentence the Due panel
                      shows, from the same server-side diagnosis. The old
                      "no unbilled extra work" line was true and told an
                      operator nothing they could act on. */}
                  {nothingSentence(t, preview.nothing_reason) ??
                    t("facturen.preview_empty")}
                </p>
              </>
            )}

            {!previewBusy && preview && preview.invoice_count > 0 && (
              <>
                <div className="table-wrap">
                  <table
                    className="data-table"
                    data-testid="facturen-preview-table"
                  >
                    <thead>
                      <tr>
                        <th>{t("facturen.preview_col_addressed_to")}</th>
                        <th style={{ textAlign: "right" }}>
                          {t("facturen.preview_col_lines")}
                        </th>
                        <th style={{ textAlign: "right" }}>
                          {t("facturen.preview_col_total")}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.invoices.map((planned, index) => (
                        <tr
                          key={`${planned.building ?? "customer"}-${planned.department ?? "d"}-${planned.work_type ?? "w"}-${index}`}
                          data-testid="facturen-preview-row"
                        >
                          <td>
                            {planned.building_name ??
                              t("facturen.preview_customer_level")}
                          </td>
                          <td style={{ textAlign: "right" }}>
                            {planned.line_count}
                          </td>
                          <td style={{ textAlign: "right" }}>
                            {formatMoney(planned.total_amount)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p
                  className="muted small"
                  data-testid="facturen-preview-computed-at"
                >
                  {t("facturen.preview_computed_at", {
                    when: formatDateTime(preview.computed_at),
                  })}
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
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={handleViewPreviewPdf}
                disabled={previewBusy || !preview?.invoice_count}
                data-testid="facturen-preview-view"
              >
                {t("facturen.preview_view_pdf")}
              </button>
            </div>
          </div>
        )}

        {genRow && (
          <div
            className="card"
            style={{ padding: 14, marginTop: 12 }}
            data-testid="facturen-generate-panel"
          >
            <div className="section-head-title" style={{ marginBottom: 8 }}>
              {t("facturen.gen_title", { name: genRow.customer_name })}
            </div>
            {/* W5 fix 4 — the same sentence the row carries, repeated
                where the month is chosen, because this is the field the
                operator is about to get wrong. */}
            {periodsSentence(t, duePeriods[genRow.customer]) && (
              <p
                className="muted small"
                style={{ marginTop: 0 }}
                data-testid="facturen-generate-periods"
              >
                {periodsSentence(t, duePeriods[genRow.customer])}
              </p>
            )}
            <div
              className="invoices-toolbar"
              style={{ display: "flex", gap: 16, flexWrap: "wrap" }}
            >
              <label className="field">
                <span className="field-label">{t("facturen.gen_month")}</span>
                <input
                  className="field-input"
                  type="month"
                  value={genMonth}
                  onChange={(e) => setGenMonth(e.target.value)}
                  data-testid="facturen-generate-month"
                />
              </label>
              <div style={{ flexBasis: "100%" }}>
                {/* Sprint 183 §1 — the SAME component customer
                    settings uses, so both screens describe this
                    decision in identical words. */}
                <BillingTargetFields
                  idPrefix="facturen-gen"
                  target={genTarget}
                  split={genSplit}
                  onTargetChange={setGenTarget}
                  onSplitChange={setGenSplit}
                  disabled={genBusy}
                />
                <p className="muted small" style={{ marginBottom: 0 }}>
                  {t("invoices:billing.this_run_only")}
                </p>
              </div>
            </div>
            <div className="form-actions" style={{ marginTop: 12 }}>
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
                disabled={genBusy || !parseMonth(genMonth)}
                data-testid="facturen-generate-confirm"
              >
                {/* W5 fix 4 — the button names the ONE period it is
                    about to generate. `generate` has always targeted an
                    exact period; only the button was silent about it. */}
                {(() => {
                  const parsed = parseMonth(genMonth);
                  return parsed
                    ? t("facturen.gen_confirm_for", {
                        period: formatPeriod(parsed.year, parsed.month),
                      })
                    : t("facturen.generate");
                })()}
              </button>
            </div>
          </div>
        )}
      </section>

      {/* ---- Invoice list ---- */}
      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        <div className="invoices-toolbar" style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
          <label className="field">
            <span className="field-label">{t("facturen.filter_period")}</span>
            <input
              className="field-input"
              type="month"
              value={periodMonth}
              onChange={(e) => setPeriodMonth(e.target.value)}
              data-testid="facturen-filter-period"
            />
          </label>
          {!customerScoped && (
            <label className="field">
              <span className="field-label">{t("facturen.filter_customer")}</span>
              <select
                className="field-select"
                value={customerFilter}
                onChange={(e) => setCustomerFilter(e.target.value)}
                data-testid="facturen-filter-customer"
              >
                <option value="ALL">{t("facturen.filter_all")}</option>
                {customerOptions.map(([cid, name]) => (
                  <option key={cid} value={String(cid)}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="field">
            <span className="field-label">{t("facturen.filter_building")}</span>
            <select
              className="field-select"
              value={buildingFilter}
              onChange={(e) => setBuildingFilter(e.target.value)}
              data-testid="facturen-filter-building"
            >
              <option value="ALL">{t("facturen.filter_all")}</option>
              {buildingOptions.map(([bid, name]) => (
                <option key={bid} value={String(bid)}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">{t("facturen.filter_status")}</span>
            <select
              className="field-select"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
              data-testid="facturen-filter-status"
            >
              <option value="ALL">{t("facturen.filter_all")}</option>
              <option value="DRAFT">{t("facturen.status_draft")}</option>
              <option value="ISSUED">{t("facturen.status_issued")}</option>
              <option value="SENT">{t("facturen.status_sent")}</option>
            </select>
          </label>
        </div>
      </div>

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : visibleInvoices.length === 0 ? (
        <EmptyState
          icon={BadgeEuro}
          title={t("facturen.list_empty_title")}
          description={t("facturen.list_empty_desc")}
        />
      ) : (
        <div className="card" style={{ overflowX: "auto" }}>
          <table className="data-table" data-testid="facturen-list-table">
            <thead>
              <tr>
                <th>{t("facturen.col_number")}</th>
                {/* W24-FX1 §3 — the money sits SECOND, not last.
                    Nine columns need more than the 1110px this page gets
                    at 1366, so the card scrolls sideways; the last column
                    is the one that falls off the end, and the last column
                    was Totaal. Measured at 1366: the Totaal header
                    truncated to "TO…" and its cells sat past the
                    container edge, reachable only by a scrollbar nobody
                    looks for on a list they came to read amounts off.
                    Position is the fix, not width: whatever the viewport,
                    the number a reader opened this page for is on screen
                    without scrolling, and the descriptive columns — which
                    tolerate being scrolled to — take the overflow. Kept
                    right-aligned, with its header, so it still reads as a
                    money column. */}
                <th style={{ textAlign: "right" }}>{t("facturen.col_total")}</th>
                {/* Sprint 187 §6a — WHICH company issued it. Numbering
                    is gapless per company per YEAR, so two rows in this
                    list legitimately both read `2026-0001` and nothing
                    told them apart. Shown on every deployment, including
                    a single-company one where the column repeats: the
                    alternative is a column that appears and disappears
                    depending on data, which is harder to trust than one
                    that is always there. */}
                <th>{t("facturen.col_company")}</th>
                {!customerScoped && <th>{t("facturen.col_customer")}</th>}
                <th>{t("facturen.col_building")}</th>
                <th>{t("facturen.col_department_work_type")}</th>
                <th>{t("facturen.col_period")}</th>
                <th>{t("invoices:created_by.label")}</th>
                <th>{t("facturen.col_status")}</th>
              </tr>
            </thead>
            <tbody>
              {visibleInvoices.map((inv) => (
                <tr
                  key={inv.id}
                  data-testid="facturen-list-row"
                  style={{ cursor: "pointer" }}
                  tabIndex={0}
                  onClick={(e) => {
                    // The number cell is a real <Link> (keyboard focus,
                    // open-in-new-tab, middle-click). If the click originated
                    // on it, let the anchor navigate — don't double-fire.
                    if ((e.target as HTMLElement).closest("a")) return;
                    navigate(`/invoices/${inv.id}`);
                  }}
                  onKeyDown={(e) => {
                    // Enter on the focused row (not the inner anchor) navigates.
                    if (e.key === "Enter" && e.target === e.currentTarget) {
                      navigate(`/invoices/${inv.id}`);
                    }
                  }}
                >
                  <td>
                    <Link to={`/invoices/${inv.id}`} className="link">
                      {inv.number ?? t("facturen.concept")}
                      {inv.is_reversal && (
                        <span className="muted small" style={{ marginLeft: 6 }}>
                          ({t("facturen.credit_note")})
                        </span>
                      )}
                      {/* Sprint 122 (B2) — a reversed original stays SENT on
                          the books, so flag it here too or it silently reads
                          as a normal open invoice in the list. */}
                      {inv.credited_by_number && (
                        <span className="muted small" style={{ marginLeft: 6 }}>
                          (
                          {t("facturen.credited_by", {
                            number: inv.credited_by_number,
                          })}
                          )
                        </span>
                      )}
                    </Link>
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <strong>{formatMoney(inv.total_amount)}</strong>
                  </td>
                  <td className="muted small">{inv.company_name}</td>
                  {!customerScoped && <td>{inv.customer_name}</td>}
                  <td className="muted small">
                    {inv.building_name ?? t("facturen.all_buildings")}
                  </td>
                  <td className="muted small">
                    {/* Sprint 187 §4 — the LIST said "Algemeen" while
                        the invoice DETAIL, one click away, said
                        "General" for the same invoice. Both go through
                        `customerLabelName` now: it translates ONLY the
                        auto-seeded name and passes an operator-typed one
                        through untouched. */}
                    {formatInvoiceGroupLabel(
                      customerLabelName(inv.department_name, t),
                      customerLabelName(inv.work_type_name, t),
                    ) || "—"}
                  </td>
                  <td className="muted small">
                    {formatPeriod(inv.period_year, inv.period_month)}
                  </td>
                  {/* Sprint 183 §3 — WHO created it. The nightly run's
                      invoices used to borrow a COMPANY_ADMIN's name
                      because `created_by` was NOT NULL; they say System
                      now. The server resolves the label so "System" is
                      never a frontend guess, and never renders blank or
                      "Unassigned". */}
                  <td className="muted small" data-testid="facturen-created-by">
                    {inv.created_by_label || t("invoices:created_by.system")}
                  </td>
                  <td>
                    {/* Sprint 122 (B1) — an ISSUED-but-unsent credit note
                        gets its own amber tag instead of blending into the
                        plain gray "Issued" used for every other non-SENT
                        invoice, so it can't get lost in a long list. */}
                    <span
                      className={
                        inv.is_reversal && inv.status === "ISSUED"
                          ? "cell-tag cell-tag-warn"
                          : inv.status === "SENT"
                            ? "cell-tag cell-tag-open"
                            : "cell-tag cell-tag-closed"
                      }
                      data-testid="facturen-list-status"
                    >
                      <i />
                      {inv.is_reversal && inv.status === "ISSUED"
                        ? t("facturen.credit_note_unsent")
                        : t(STATUS_LABEL_KEY[inv.status])}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* W17 — always mounted, opened through the ref only. A native
          <dialog> wrapped in a condition is an invisible dialog and a
          dead trigger button (Sprint 128). No download: the preview is
          deliberately a document you can only look at. */}
      <PdfPreviewDialog ref={previewPdfRef} withDownload={false} />
    </div>
  );
}
