import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import { getCustomer } from "../../../api/admin";
import { listExtraWork } from "../../../api/extraWork";
import type { CustomerAdmin, ExtraWorkRequestList } from "../../../api/types";
import { currentMonth, splitOpenInvoiced, sumRows } from "../../../lib/billing";
import { formatMoney } from "../../../lib/intl";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

type StatusFilter = "ALL" | "OPEN" | "INVOICED";

/**
 * #108 Part E — the customer-detail Reports tab: the Extra Work
 * revenue report with the customer preset FIXED.
 *
 * Recon finding: /reports/extra-work-revenue/ has no customer filter
 * (scope is company/building only), and Part E is frontend-only. The
 * EW LIST endpoint, however, both accepts ?customer= and applies the
 * SAME server-side earned/billing-month classification the revenue
 * report's billing-month mode uses (extra_work.billing via the
 * billing_period filter). This tab therefore reuses that endpoint plus
 * the shared lib/billing math (the sanctioned client-side mirror the
 * Facturen page and the dashboard widget already use) — same numbers,
 * no duplicated business logic. The full multi-state chart per
 * customer would need a small additive backend param (follow-up).
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

  useEffect(() => {
    if (numericId === null) return;
    let cancelled = false;
    setLoading(true); // eslint-disable-line react-hooks/set-state-in-effect
    setError("");
    listExtraWork({
      customer: numericId,
      billing_period: month,
      page_size: 500,
    })
      .then((resp) => {
        if (!cancelled) setRows(resp.results);
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

      <p className="muted small" style={{ marginTop: 16 }}>
        <Link to="/reports" className="link">
          {t("customer_reports.full_reports_link")}
        </Link>
      </p>
    </div>
  );
}
