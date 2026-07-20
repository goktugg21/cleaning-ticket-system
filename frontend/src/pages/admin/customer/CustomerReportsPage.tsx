import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import { getCustomer } from "../../../api/admin";
import { listExtraWork } from "../../../api/extraWork";
import type { ReportFilters } from "../../../api/reports";
import type { CustomerAdmin, ExtraWorkRequestList } from "../../../api/types";
import { currentMonth, splitOpenInvoiced, sumRows } from "../../../lib/billing";
import { formatMoney } from "../../../lib/intl";
import { ExtraWorkRevenueChart } from "../../reports/charts/ExtraWorkRevenueChart";
import { StatusDistributionChart } from "../../reports/charts/StatusDistributionChart";
import { TicketsOverTimeChart } from "../../reports/charts/TicketsOverTimeChart";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

type StatusFilter = "ALL" | "OPEN" | "INVOICED";

/**
 * Customer-detail Reports tab.
 *
 * #108 Part E shipped the billing KPI grid (EW list + lib/billing math)
 * because the report endpoints had no customer filter. #109 Part H
 * added an additive `customer` param to the extra-work-revenue,
 * tickets-over-time and status-distribution endpoints, so this tab now
 * also renders the REAL charts locked to this customer:
 *   - ExtraWorkRevenueChart (billing_period = the selected month, to
 *     match the KPI grid's bucketing) + its CSV/PDF export buttons;
 *   - TicketsOverTimeChart (the month's date range);
 *   - StatusDistributionChart (current snapshot).
 * The month/status controls + KPI grid are unchanged.
 */
export function CustomerReportsPage() {
  const { id } = useParams();
  const { t } = useTranslation("common");

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [rows, setRows] = useState<ExtraWorkRequestList[]>([]);
  const [month, setMonth] = useState(currentMonth);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (numericId === null) return;
    let cancelled = false;
    getCustomer(numericId)
      .then((data) => {
        if (!cancelled) setCustomer(data);
      })
      .catch(() => {
        // Header falls back to the empty name; the revenue fetch below
        // carries the user-facing error.
      });
    return () => {
      cancelled = true;
    };
  }, [numericId]);

  // Part J — `loading` starts true so the first render shows the bar
  // without a synchronous setLoading(true) in the effect body (the
  // CustomerTicketsPage idiom that keeps this file clear of
  // react-hooks/set-state-in-effect). On a month change the KPIs
  // refresh in place when the fetch resolves — no loading flash.
  useEffect(() => {
    if (numericId === null) return;
    let cancelled = false;
    // No synchronous setState in the effect body (Part J): error is
    // cleared on success and set on failure, both inside the settled
    // promise, matching the CustomerTicketsPage idiom.
    listExtraWork({
      customer: numericId,
      billing_period: month,
      page_size: 500,
    })
      .then((resp) => {
        if (cancelled) return;
        setRows(resp.results);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [numericId, month]);

  // #109 Part H — filters locking every chart to this customer. The
  // revenue chart uses billing-month mode (same bucket as the KPIs);
  // the ticket charts use the selected month's date range / a current
  // snapshot. Memoized so useReport's filtersKey is stable per month.
  const monthRange = useMemo(() => {
    const [y, m] = month.split("-").map(Number);
    const lastDay = new Date(y, m, 0).getDate();
    return {
      from: `${month}-01`,
      to: `${month}-${String(lastDay).padStart(2, "0")}`,
    };
  }, [month]);
  const revenueFilters: ReportFilters = useMemo(
    () => ({ customer: numericId ?? undefined, billing_period: month }),
    [numericId, month],
  );
  const overTimeFilters: ReportFilters = useMemo(
    () => ({
      customer: numericId ?? undefined,
      from: monthRange.from,
      to: monthRange.to,
    }),
    [numericId, monthRange],
  );
  const statusFilters: ReportFilters = useMemo(
    () => ({ customer: numericId ?? undefined }),
    [numericId],
  );

  const visibleRows = useMemo(
    () =>
      rows.filter((r) => {
        if (statusFilter === "OPEN" && r.is_invoiced === true) return false;
        if (statusFilter === "INVOICED" && r.is_invoiced !== true)
          return false;
        return true;
      }),
    [rows, statusFilter],
  );
  const totals = useMemo(() => sumRows(visibleRows), [visibleRows]);
  const split = useMemo(() => splitOpenInvoiced(visibleRows), [visibleRows]);

  if (numericId === null) {
    return (
      <div className="alert-error" role="alert">
        {t("admin.load_error")}
      </div>
    );
  }

  return (
    <div data-testid="customer-reports-page">
      <CustomerSubPageHeader
        customerName={customer?.name ?? ""}
        isActive={customer?.is_active ?? true}
        eyebrow={t("nav.customer_submenu.reports")}
      />

      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        <div className="invoices-toolbar">
          <label className="field invoices-toolbar-field">
            <span className="field-label">{t("billing.month_label")}</span>
            <input
              className="field-input"
              type="month"
              value={month}
              onChange={(e) => e.target.value && setMonth(e.target.value)}
              data-testid="customer-reports-month"
            />
          </label>
          <label className="field invoices-toolbar-field">
            <span className="field-label">{t("billing.filter_status")}</span>
            <select
              className="field-select"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
              data-testid="customer-reports-status"
            >
              <option value="ALL">{t("billing.filter_all")}</option>
              <option value="OPEN">{t("billing.status_open")}</option>
              <option value="INVOICED">{t("billing.status_invoiced")}</option>
            </select>
          </label>
        </div>
        <p className="muted small" style={{ margin: 0 }}>
          {t("customer_reports.helper")}
        </p>
      </div>

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {loading ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : (
        <div
          className="operations-kpi-grid option-a-hero"
          data-testid="customer-reports-kpis"
        >
          <div className="kpi-card">
            <div className="kpi-label">{t("customer_reports.kpi_earned")}</div>
            <div className="kpi-row-2">
              <div className="kpi-value">{formatMoney(totals.total)}</div>
            </div>
            <div className="kpi-meta">
              {t("customer_reports.kpi_earned_meta", { count: totals.count })}
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">{t("billing.status_open")}</div>
            <div className="kpi-row-2">
              <div className="kpi-value">{formatMoney(split.openTotal)}</div>
            </div>
            <div className="kpi-meta">
              {t("customer_reports.kpi_open_meta", { count: totals.open })}
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">{t("billing.status_invoiced")}</div>
            <div className="kpi-row-2">
              <div className="kpi-value">
                {formatMoney(split.invoicedTotal)}
              </div>
            </div>
            <div className="kpi-meta">
              {t("customer_reports.kpi_invoiced_meta", {
                count: totals.invoiced,
              })}
            </div>
          </div>
          <div className="kpi-card">
            <div className="kpi-label">{t("customer_reports.kpi_vat")}</div>
            <div className="kpi-row-2">
              <div className="kpi-value">{formatMoney(totals.vat)}</div>
            </div>
            <div className="kpi-meta">
              {t("customer_reports.kpi_vat_meta", {
                subtotal: formatMoney(totals.subtotal),
              })}
            </div>
          </div>
        </div>
      )}

      {/* #109 Part H — real charts locked to this customer. */}
      <div style={{ marginTop: 16 }} data-testid="customer-reports-charts">
        <ExtraWorkRevenueChart filters={revenueFilters} refreshKey={0} />
        <TicketsOverTimeChart filters={overTimeFilters} refreshKey={0} />
        <StatusDistributionChart filters={statusFilters} refreshKey={0} />
      </div>

      <p className="muted small" style={{ marginTop: 16 }}>
        <Link to="/reports" className="link">
          {t("customer_reports.full_reports_link")}
        </Link>
      </p>
    </div>
  );
}
