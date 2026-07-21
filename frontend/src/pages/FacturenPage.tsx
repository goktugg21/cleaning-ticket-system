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
  generateInvoices,
  getInvoiceDueList,
  listInvoices,
} from "../api/invoices";
import type {
  Invoice,
  InvoiceDueRow,
  InvoiceGranularity,
  InvoiceStatus,
} from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { useToast } from "../components/ToastProvider";
import { formatMoney } from "../lib/intl";

type StatusFilter = InvoiceStatus | "ALL";

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
  const { t } = useTranslation("common");
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
  const [genGranularity, setGenGranularity] =
    useState<InvoiceGranularity>("CUSTOMER");
  const [genBusy, setGenBusy] = useState(false);

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

  // Invoice list.
  const period = useMemo(() => parseMonth(periodMonth), [periodMonth]);
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const resp = await listInvoices({
          customer: customerId,
          status: statusFilter === "ALL" ? undefined : statusFilter,
          period_year: period?.year,
          period_month: period?.month,
        });
        if (!cancelled) setInvoices(resp.results);
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
    setGenGranularity(row.invoice_granularity_default);
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
        granularity: genGranularity,
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
                      <td style={{ textAlign: "right" }}>{row.unbilled_count}</td>
                      <td style={{ textAlign: "right" }}>
                        {formatMoney(row.unbilled_total)}
                      </td>
                      <td style={{ textAlign: "right" }}>
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
                <fieldset
                  className="field"
                  style={{ border: 0, padding: 0, margin: 0 }}
                >
                  <span className="field-label">
                    {t("facturen.gen_granularity")}
                  </span>
                  <div style={{ display: "flex", gap: 14, marginTop: 4 }}>
                    <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <input
                        type="radio"
                        name="gen-granularity"
                        checked={genGranularity === "CUSTOMER"}
                        onChange={() => setGenGranularity("CUSTOMER")}
                        data-testid="facturen-granularity-customer"
                      />
                      {t("facturatie.granularity_customer")}
                    </label>
                    <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
                      <input
                        type="radio"
                        name="gen-granularity"
                        checked={genGranularity === "PER_BUILDING"}
                        onChange={() => setGenGranularity("PER_BUILDING")}
                        data-testid="facturen-granularity-building"
                      />
                      {t("facturatie.granularity_building")}
                    </label>
                  </div>
                </fieldset>
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
                <th>{t("facturen.col_period")}</th>
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
                    </Link>
                  </td>
                  {!customerScoped && <td>{inv.customer_name}</td>}
                  <td className="muted small">
                    {inv.building_name ?? t("facturen.all_buildings")}
                  </td>
                  <td className="muted small">
                    {formatPeriod(inv.period_year, inv.period_month)}
                  </td>
                  <td>
                    <span
                      className={
                        inv.status === "SENT"
                          ? "cell-tag cell-tag-open"
                          : "cell-tag cell-tag-closed"
                      }
                      data-testid="facturen-list-status"
                    >
                      <i />
                      {t(STATUS_LABEL_KEY[inv.status])}
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
