// Invoicing Phase 5 — the customer invoice DETAIL page (READ-ONLY).
//
// A CUSTOMER_USER's own SENT invoice: header + the two-page PDF preview
// (blob -> object URL -> iframe, revoked on unmount) + download + the totals
// + the lines (read-only) + the summary. NO edit controls, NO lifecycle
// buttons — the backend serves only SENT, redacted, in-scope invoices.
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ChevronLeft, Download } from "lucide-react";

import { getApiError } from "../api/client";
import { fetchMyInvoicePdf, getMyInvoice } from "../api/invoices";
import type { CustomerInvoice } from "../api/types";
import { formatDate, formatMoney } from "../lib/intl";

function formatPeriod(year: number | null, month: number | null): string {
  if (!year || !month) return "—";
  return `${String(month).padStart(2, "0")}-${year}`;
}

export function MyInvoiceDetailPage() {
  const { id } = useParams();
  const { t } = useTranslation("common");

  const [invoice, setInvoice] = useState<CustomerInvoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(true);
  const [pdfError, setPdfError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const fresh = await getMyInvoice(id ?? "");
        if (!cancelled) setInvoice(fresh);
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
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    let created: string | null = null;
    async function loadPdf() {
      setPdfError("");
      try {
        const blob = await fetchMyInvoicePdf(id ?? "");
        if (cancelled) return;
        created = URL.createObjectURL(blob);
        setPdfUrl(created);
      } catch (err) {
        if (!cancelled) setPdfError(getApiError(err));
      } finally {
        if (!cancelled) setPdfLoading(false);
      }
    }
    loadPdf();
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [id]);

  async function handleDownload() {
    if (!invoice) return;
    try {
      const blob = await fetchMyInvoicePdf(invoice.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `factuur-${invoice.number ?? invoice.id}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(getApiError(err));
    }
  }

  if (loading) {
    return (
      <div className="loading-bar">
        <div className="loading-bar-fill" />
      </div>
    );
  }

  if (!invoice) {
    return (
      <div className="alert-error" role="alert">
        {error || t("customer_facturen.load_error")}
      </div>
    );
  }

  return (
    <div data-testid="my-invoice-detail-page">
      <Link to="/my/facturen" className="link-back" data-testid="my-invoice-back">
        <ChevronLeft size={14} strokeWidth={2.5} />
        {t("customer_facturen.detail_back")}
      </Link>

      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {invoice.is_reversal
              ? t("facturen.credit_note")
              : t("customer_facturen.detail_eyebrow")}
          </div>
          <h2 className="page-title" data-testid="my-invoice-number">
            {invoice.number ?? `#${invoice.id}`}
            <span style={{ marginLeft: 12 }}>
              <span className="cell-tag cell-tag-open" data-testid="my-invoice-status">
                <i />
                {t("facturen.status_sent")}
              </span>
            </span>
          </h2>
        </div>
      </div>

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* Meta. */}
      <section className="card" style={{ padding: "18px 20px", marginBottom: 16 }}>
        <div className="detail-field-row">
          <div className="detail-field-label">
            {t("customer_facturen.field_building")}
          </div>
          <div className="detail-field-value">
            {invoice.building_name ?? t("facturen.all_buildings")}
          </div>
        </div>
        <div className="detail-field-row">
          <div className="detail-field-label">
            {t("customer_facturen.field_period")}
          </div>
          <div className="detail-field-value">
            {formatPeriod(invoice.period_year, invoice.period_month)}
          </div>
        </div>
        <div className="detail-field-row">
          <div className="detail-field-label">
            {t("customer_facturen.field_sent")}
          </div>
          <div className="detail-field-value">
            {invoice.sent_at ? formatDate(invoice.sent_at) : "—"}
          </div>
        </div>
      </section>

      {/* PDF preview. */}
      <section className="card" style={{ marginBottom: 16 }}>
        <div className="section-head">
          <div className="section-head-title">
            {t("invoice_detail.pdf_title")}
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={handleDownload}
            data-testid="my-invoice-pdf-download"
          >
            <Download size={14} strokeWidth={2} />
            {t("invoice_detail.pdf_download")}
          </button>
        </div>
        <div style={{ padding: 16 }}>
          {pdfError ? (
            <div className="alert-error" role="alert">
              {pdfError}
            </div>
          ) : pdfUrl ? (
            <iframe
              title={t("invoice_detail.pdf_title")}
              src={pdfUrl}
              data-testid="my-invoice-pdf-frame"
              style={{
                width: "100%",
                height: 760,
                border: "1px solid var(--border, #e2e2e2)",
                borderRadius: 6,
              }}
            />
          ) : (
            pdfLoading && (
              <div className="loading-bar">
                <div className="loading-bar-fill" />
              </div>
            )
          )}
        </div>
      </section>

      {/* Totals. */}
      <section className="card" style={{ padding: "16px 20px", marginBottom: 16 }}>
        <div className="detail-field-row">
          <div className="detail-field-label">
            {t("invoice_detail.totals_subtotal")}
          </div>
          <div className="detail-field-value" data-testid="my-invoice-subtotal">
            {formatMoney(invoice.subtotal_amount)}
          </div>
        </div>
        <div className="detail-field-row">
          <div className="detail-field-label">
            {t("invoice_detail.totals_vat")}
          </div>
          <div className="detail-field-value">
            {formatMoney(invoice.vat_amount)}
          </div>
        </div>
        <div className="detail-field-row">
          <div className="detail-field-label">
            <strong>{t("invoice_detail.totals_total")}</strong>
          </div>
          <div className="detail-field-value" data-testid="my-invoice-total">
            <strong>{formatMoney(invoice.total_amount)}</strong>
          </div>
        </div>
      </section>

      {/* Lines (read-only). */}
      <section className="card" style={{ marginBottom: 16 }}>
        <div className="section-head">
          <div className="section-head-title">
            {t("customer_facturen.lines_title")}
          </div>
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table" data-testid="my-invoice-lines-table">
            <thead>
              <tr>
                <th>{t("invoice_detail.line_desc")}</th>
                <th style={{ textAlign: "right" }}>
                  {t("invoice_detail.line_qty")}
                </th>
                <th style={{ textAlign: "right" }}>
                  {t("invoice_detail.line_unit")}
                </th>
                <th style={{ textAlign: "right" }}>
                  {t("invoice_detail.line_vat")}
                </th>
                <th style={{ textAlign: "right" }}>
                  {t("invoice_detail.line_total")}
                </th>
              </tr>
            </thead>
            <tbody>
              {invoice.lines.map((line, index) => (
                <tr key={index} data-testid="my-invoice-line-row">
                  <td>{line.description || "—"}</td>
                  <td style={{ textAlign: "right" }}>{line.quantity}</td>
                  <td style={{ textAlign: "right" }}>
                    {formatMoney(line.unit_price)}
                  </td>
                  <td style={{ textAlign: "right" }}>{line.vat_pct}</td>
                  <td style={{ textAlign: "right" }}>
                    {formatMoney(line.line_total)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Fee (if any). */}
      {invoice.optional_fee_amount && (
        <section
          className="card"
          style={{ padding: "16px 20px", marginBottom: 16 }}
        >
          <div className="section-head-title">
            {t("customer_facturen.fee_title")}
          </div>
          <p style={{ marginTop: 8 }}>
            {invoice.optional_fee_label || "—"} ·{" "}
            {formatMoney(invoice.optional_fee_amount)}
          </p>
        </section>
      )}

      {/* Summary (if set). */}
      {invoice.summary_text && (
        <section
          className="card"
          style={{ padding: "16px 20px", marginBottom: 16 }}
        >
          <div className="section-head-title">
            {t("customer_facturen.summary_title")}
          </div>
          <p style={{ marginTop: 8 }}>{invoice.summary_text}</p>
        </section>
      )}
    </div>
  );
}
