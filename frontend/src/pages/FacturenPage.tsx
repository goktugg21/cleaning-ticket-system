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
// Reusable, mirroring the old InvoicesPage contract: with `customerId` set
// the page is customer-scoped (list only, no due panel / generate, a pointer
// to the standalone Facturen page) and `embedded` drops the standalone header
// (the customer sub-page header renders instead). Used by CustomerInvoicesPage.
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { BadgeEuro } from "lucide-react";

import { getApiError } from "../api/client";
import {
  fetchInvoicePreviewPdf,
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
import { useToast } from "../components/ToastProvider";
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
  const [dueLoading, setDueLoading] = useState(!customerScoped);
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

  // Due panel (skipped when customer-scoped / embedded).
  useEffect(() => {
    if (customerScoped) return;
    let cancelled = false;
    async function loadDue() {
      try {
        const rows = await getInvoiceDueList();
        if (!cancelled) setDueRows(rows);
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
  }, [customerScoped, refreshKey]);

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
    setGenMonth(
      row.period_year && row.period_month
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

  async function handleDownloadPreview() {
    if (!previewRow) return;
    try {
      const blob = await fetchInvoicePreviewPdf({
        customer: previewRow.customer,
        year: previewRow.period_year,
        month: previewRow.period_month,
      });
      // Opened in a tab rather than force-downloaded: the operator is
      // checking numbers, not filing a document, and the PDF is stamped
      // PREVIEW on every page so a stray tab cannot be mistaken for an
      // invoice.
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener");
      // Revoked on the next tick so the opened tab has taken the blob.
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setError(getApiError(err));
    }
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
      pushToast({
        variant: created.length > 0 ? "success" : "info",
        title: t("facturen.gen_toast", { count: created.length }),
      });
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

      {customerScoped ? (
        <div className="card" style={{ padding: 16, marginBottom: 16 }}>
          <Link to="/invoices" className="link" data-testid="facturen-manage-link">
            {t("facturen.manage_link")}
          </Link>
        </div>
      ) : (
        // ---- Due panel ----
        <section
          className="card"
          style={{ padding: 16, marginBottom: 16 }}
          data-testid="facturen-due-panel"
        >
          <div className="section-head" style={{ marginBottom: 10 }}>
            <div>
              <div className="section-head-title">{t("facturen.due_title")}</div>
              <div className="section-head-sub">{t("facturen.due_sub")}</div>
            </div>
          </div>
          {dueLoading ? (
            <div className="loading-bar">
              <div className="loading-bar-fill" />
            </div>
          ) : dueRows.length === 0 ? (
            <p className="muted small" data-testid="facturen-due-empty">
              {t("facturen.due_empty")}
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
                <p className="muted small" data-testid="facturen-preview-empty">
                  {/* Sprint 183 §2 — the SAME sentence the Due panel
                      shows, from the same server-side diagnosis. The old
                      "no unbilled extra work" line was true and told an
                      operator nothing they could act on. */}
                  {nothingSentence(t, preview.nothing_reason) ??
                    t("facturen.preview_empty")}
                </p>
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
                  onClick={handleDownloadPreview}
                  disabled={previewBusy || !preview?.invoice_count}
                  data-testid="facturen-preview-download"
                >
                  {t("facturen.preview_download")}
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
                  {t("facturen.generate")}
                </button>
              </div>
            </div>
          )}
        </section>
      )}

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
                {!customerScoped && <th>{t("facturen.col_customer")}</th>}
                <th>{t("facturen.col_building")}</th>
                <th>{t("facturen.col_department_work_type")}</th>
                <th>{t("facturen.col_period")}</th>
                <th>{t("invoices:created_by.label")}</th>
                <th>{t("facturen.col_status")}</th>
                <th style={{ textAlign: "right" }}>{t("facturen.col_total")}</th>
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
                  {!customerScoped && <td>{inv.customer_name}</td>}
                  <td className="muted small">
                    {inv.building_name ?? t("facturen.all_buildings")}
                  </td>
                  <td className="muted small">
                    {formatInvoiceGroupLabel(
                      inv.department_name,
                      inv.work_type_name,
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
                  <td style={{ textAlign: "right" }}>
                    <strong>{formatMoney(inv.total_amount)}</strong>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
