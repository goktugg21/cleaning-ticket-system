// Invoicing Phase 4b — the dedicated invoice-detail page.
//
// A read-only-by-default detail surface with, WHILE DRAFT ONLY, the full
// editable surfaces the owner insisted on (a key Ramazan requirement):
//   * the two-page PDF preview (fetched as a blob -> object URL -> iframe;
//     revoked on unmount; refetched after every successful edit);
//   * lifecycle buttons (Issue when DRAFT, Send when ISSUED, Reverse when
//     SENT — each confirm-gated, each refetches after);
//   * the editable page-1 summary (summary_text);
//   * the optional fee box (label + amount);
//   * full line editing — add a hand line / edit any line / remove a line
//     (remove releases the linked EW server-side; the confirm spells it out).
// Once ISSUED/SENT the edit controls are hidden (the backend enforces the
// immutability; a failed edit surfaces the backend message).
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ChevronLeft, Download } from "lucide-react";

import { getApiError } from "../api/client";
import {
  addInvoiceLine,
  deleteDraftInvoice,
  fetchInvoicePdf,
  getInvoice,
  issueInvoice,
  removeInvoiceLine,
  reverseInvoice,
  sendInvoice,
  updateInvoiceLine,
  updateInvoiceMeta,
} from "../api/invoices";
import type { Invoice, InvoiceLine, InvoiceStatus } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../components/ConfirmDialog";
import { useToast } from "../components/ToastProvider";
import { formatDate, formatMoney } from "../lib/intl";

const STATUS_LABEL_KEY: Record<InvoiceStatus, string> = {
  DRAFT: "facturen.status_draft",
  ISSUED: "facturen.status_issued",
  SENT: "facturen.status_sent",
};

type LifecycleAction = "issue" | "send" | "reverse" | "delete";

interface LineDraft {
  description: string;
  quantity: string;
  unit_price: string;
  vat_pct: string;
}

const EMPTY_LINE_DRAFT: LineDraft = {
  description: "",
  quantity: "1",
  unit_price: "0",
  vat_pct: "21",
};

function formatPeriod(year: number | null, month: number | null): string {
  if (!year || !month) return "—";
  return `${String(month).padStart(2, "0")}-${year}`;
}

export function InvoiceDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation("common");
  const { push: pushToast } = useToast();

  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // PDF preview (object URL + a refresh counter bumped after each edit).
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(true);
  const [pdfError, setPdfError] = useState("");
  const [pdfRefresh, setPdfRefresh] = useState(0);

  // Draft editors.
  const [summaryDraft, setSummaryDraft] = useState("");
  const [feeLabel, setFeeLabel] = useState("");
  const [feeAmount, setFeeAmount] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [addDraft, setAddDraft] = useState<LineDraft>(EMPTY_LINE_DRAFT);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<LineDraft>(EMPTY_LINE_DRAFT);

  const lifecycleDialogRef = useRef<ConfirmDialogHandle>(null);
  const [pendingLifecycle, setPendingLifecycle] =
    useState<LifecycleAction | null>(null);
  const removeLineDialogRef = useRef<ConfirmDialogHandle>(null);
  const [pendingRemoveLine, setPendingRemoveLine] = useState<InvoiceLine | null>(
    null,
  );

  const isDraft = invoice?.status === "DRAFT";

  function applyInvoice(fresh: Invoice) {
    setInvoice(fresh);
    setSummaryDraft(fresh.summary_text ?? "");
    setFeeLabel(fresh.optional_fee_label ?? "");
    setFeeAmount(fresh.optional_fee_amount ?? "");
  }

  // Initial load.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError("");
      try {
        const fresh = await getInvoice(id ?? "");
        if (!cancelled) applyInvoice(fresh);
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

  // PDF preview — refetched whenever the invoice id or pdfRefresh changes.
  useEffect(() => {
    let cancelled = false;
    let created: string | null = null;
    async function loadPdf() {
      setPdfError("");
      try {
        const blob = await fetchInvoicePdf(id ?? "");
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
  }, [id, pdfRefresh]);

  async function reloadInvoice() {
    const fresh = await getInvoice(id ?? "");
    applyInvoice(fresh);
    setPdfRefresh((k) => k + 1);
  }

  // ---- edit handlers (DRAFT-only; the backend re-enforces) ----
  async function handleSaveSummary() {
    if (!invoice) return;
    setBusy(true);
    setError("");
    try {
      await updateInvoiceMeta(invoice.id, { summary_text: summaryDraft });
      await reloadInvoice();
      pushToast({ variant: "success", title: t("invoice_detail.saved_toast") });
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveFee() {
    if (!invoice) return;
    setBusy(true);
    setError("");
    try {
      await updateInvoiceMeta(invoice.id, {
        optional_fee_label: feeLabel,
        optional_fee_amount: feeAmount.trim() === "" ? null : feeAmount.trim(),
      });
      await reloadInvoice();
      pushToast({ variant: "success", title: t("invoice_detail.saved_toast") });
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleAddLine() {
    if (!invoice) return;
    setBusy(true);
    setError("");
    try {
      await addInvoiceLine(invoice.id, {
        description: addDraft.description,
        quantity: addDraft.quantity,
        unit_price: addDraft.unit_price,
        vat_pct: addDraft.vat_pct,
      });
      setAddOpen(false);
      setAddDraft(EMPTY_LINE_DRAFT);
      await reloadInvoice();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  function startEdit(line: InvoiceLine) {
    setEditingId(line.id);
    setEditDraft({
      description: line.description,
      quantity: line.quantity,
      unit_price: line.unit_price,
      vat_pct: line.vat_pct,
    });
  }

  async function handleSaveLine(lineId: number) {
    if (!invoice) return;
    setBusy(true);
    setError("");
    try {
      await updateInvoiceLine(invoice.id, lineId, {
        description: editDraft.description,
        quantity: editDraft.quantity,
        unit_price: editDraft.unit_price,
        vat_pct: editDraft.vat_pct,
      });
      setEditingId(null);
      await reloadInvoice();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirmRemoveLine() {
    if (!invoice || !pendingRemoveLine) return;
    setBusy(true);
    setError("");
    try {
      await removeInvoiceLine(invoice.id, pendingRemoveLine.id);
      removeLineDialogRef.current?.close();
      setPendingRemoveLine(null);
      await reloadInvoice();
    } catch (err) {
      setError(getApiError(err));
      removeLineDialogRef.current?.close();
    } finally {
      setBusy(false);
    }
  }

  // ---- lifecycle ----
  function requestLifecycle(action: LifecycleAction) {
    setPendingLifecycle(action);
    lifecycleDialogRef.current?.open();
  }

  async function handleConfirmLifecycle() {
    if (!invoice || pendingLifecycle === null) return;
    setBusy(true);
    setError("");
    try {
      if (pendingLifecycle === "issue") {
        const updated = await issueInvoice(invoice.id);
        applyInvoice(updated);
        setPdfRefresh((k) => k + 1);
        pushToast({
          variant: "success",
          title: t("invoice_detail.issued_toast"),
        });
      } else if (pendingLifecycle === "send") {
        const updated = await sendInvoice(invoice.id);
        applyInvoice(updated);
        setPdfRefresh((k) => k + 1);
        pushToast({
          variant: "success",
          title: t("invoice_detail.sent_toast"),
        });
      } else if (pendingLifecycle === "reverse") {
        const reversal = await reverseInvoice(invoice.id);
        pushToast({
          variant: "success",
          title: t("invoice_detail.reversed_toast"),
        });
        lifecycleDialogRef.current?.close();
        setPendingLifecycle(null);
        navigate(`/invoices/${reversal.id}`);
        return;
      } else if (pendingLifecycle === "delete") {
        await deleteDraftInvoice(invoice.id);
        pushToast({
          variant: "success",
          title: t("invoice_detail.deleted_toast"),
        });
        navigate("/invoices");
        return;
      }
      lifecycleDialogRef.current?.close();
      setPendingLifecycle(null);
    } catch (err) {
      setError(getApiError(err));
      lifecycleDialogRef.current?.close();
    } finally {
      setBusy(false);
    }
  }

  async function handleDownloadPdf() {
    if (!invoice) return;
    try {
      const blob = await fetchInvoicePdf(invoice.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `factuur-${invoice.number ?? `concept-${invoice.id}`}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(getApiError(err));
    }
  }

  const lifecycleCopy = useMemo(() => {
    switch (pendingLifecycle) {
      case "issue":
        return {
          title: t("invoice_detail.confirm_issue_title"),
          body: t("invoice_detail.confirm_issue_body"),
          confirm: t("invoice_detail.action_issue"),
        };
      case "send":
        return {
          title: t("invoice_detail.confirm_send_title"),
          body: t("invoice_detail.confirm_send_body"),
          confirm: t("invoice_detail.action_send"),
        };
      case "reverse":
        return {
          title: t("invoice_detail.confirm_reverse_title"),
          body: t("invoice_detail.confirm_reverse_body"),
          confirm: t("invoice_detail.action_reverse"),
        };
      case "delete":
        return {
          title: t("invoice_detail.confirm_delete_title"),
          body: t("invoice_detail.confirm_delete_body"),
          confirm: t("invoice_detail.action_delete"),
        };
      default:
        return { title: "", body: "", confirm: "" };
    }
  }, [pendingLifecycle, t]);

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
        {error || t("invoice_detail.load_error")}
      </div>
    );
  }

  const numberText = invoice.number ?? t("facturen.concept");

  return (
    <div data-testid="invoice-detail-page">
      <Link to="/invoices" className="link-back" data-testid="invoice-detail-back">
        <ChevronLeft size={14} strokeWidth={2.5} />
        {t("invoice_detail.back")}
      </Link>

      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {invoice.is_reversal
              ? t("facturen.credit_note")
              : t("invoice_detail.eyebrow")}
          </div>
          <h2 className="page-title" data-testid="invoice-detail-number">
            {numberText}
            <span style={{ marginLeft: 12 }}>
              <span
                className={
                  invoice.status === "SENT"
                    ? "cell-tag cell-tag-open"
                    : "cell-tag cell-tag-closed"
                }
                data-testid="invoice-detail-status"
              >
                <i />
                {t(STATUS_LABEL_KEY[invoice.status])}
              </span>
            </span>
          </h2>
        </div>
        <div className="page-header-actions">
          {isDraft && (
            <>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => requestLifecycle("issue")}
                disabled={busy}
                data-testid="invoice-issue-button"
              >
                {t("invoice_detail.action_issue")}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                style={{ color: "var(--red)" }}
                onClick={() => requestLifecycle("delete")}
                disabled={busy}
                data-testid="invoice-delete-button"
              >
                {t("invoice_detail.action_delete")}
              </button>
            </>
          )}
          {invoice.status === "ISSUED" && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => requestLifecycle("send")}
              disabled={busy}
              data-testid="invoice-send-button"
            >
              {t("invoice_detail.action_send")}
            </button>
          )}
          {invoice.status === "SENT" && !invoice.is_reversal && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => requestLifecycle("reverse")}
              disabled={busy}
              data-testid="invoice-reverse-button"
            >
              {t("invoice_detail.action_reverse")}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {!isDraft && (
        <div
          className="alert-info"
          role="status"
          style={{ marginBottom: 16 }}
          data-testid="invoice-readonly-note"
        >
          {t("invoice_detail.readonly_note")}
        </div>
      )}

      {/* Meta card. */}
      <section className="card" style={{ padding: "18px 20px", marginBottom: 16 }}>
        <div className="detail-field-row">
          <div className="detail-field-label">
            {t("invoice_detail.field_customer")}
          </div>
          <div className="detail-field-value">{invoice.customer_name}</div>
        </div>
        <div className="detail-field-row">
          <div className="detail-field-label">
            {t("invoice_detail.field_building")}
          </div>
          <div className="detail-field-value">
            {invoice.building_name ?? t("invoice_detail.all_buildings")}
          </div>
        </div>
        <div className="detail-field-row">
          <div className="detail-field-label">
            {t("invoice_detail.field_period")}
          </div>
          <div className="detail-field-value">
            {formatPeriod(invoice.period_year, invoice.period_month)}
          </div>
        </div>
        <div className="detail-field-row">
          <div className="detail-field-label">
            {t("invoice_detail.field_issued")}
          </div>
          <div className="detail-field-value">
            {invoice.issued_at ? formatDate(invoice.issued_at) : "—"}
          </div>
        </div>
        <div className="detail-field-row">
          <div className="detail-field-label">
            {t("invoice_detail.field_sent")}
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
            onClick={handleDownloadPdf}
            data-testid="invoice-pdf-download"
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
              data-testid="invoice-pdf-frame"
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
          <div className="detail-field-value" data-testid="invoice-subtotal">
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
          <div className="detail-field-value" data-testid="invoice-total">
            <strong>{formatMoney(invoice.total_amount)}</strong>
          </div>
        </div>
      </section>

      {/* Lines. */}
      <section className="card" style={{ marginBottom: 16 }}>
        <div className="section-head">
          <div className="section-head-title">
            {t("invoice_detail.lines_title")}
          </div>
          {isDraft && !addOpen && (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                setAddDraft(EMPTY_LINE_DRAFT);
                setAddOpen(true);
              }}
              disabled={busy}
              data-testid="invoice-add-line-open"
            >
              {t("invoice_detail.line_add")}
            </button>
          )}
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table" data-testid="invoice-lines-table">
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
                <th>{t("facturen.col_status")}</th>
                {isDraft && <th />}
              </tr>
            </thead>
            <tbody>
              {invoice.lines.map((line) =>
                editingId === line.id ? (
                  <tr key={line.id} data-testid="invoice-line-edit-row">
                    <td>
                      <input
                        className="field-input"
                        value={editDraft.description}
                        onChange={(e) =>
                          setEditDraft({
                            ...editDraft,
                            description: e.target.value,
                          })
                        }
                        data-testid="invoice-line-edit-desc"
                      />
                    </td>
                    <td>
                      <input
                        className="field-input"
                        value={editDraft.quantity}
                        onChange={(e) =>
                          setEditDraft({ ...editDraft, quantity: e.target.value })
                        }
                        style={{ textAlign: "right", maxWidth: 80 }}
                      />
                    </td>
                    <td>
                      <input
                        className="field-input"
                        value={editDraft.unit_price}
                        onChange={(e) =>
                          setEditDraft({
                            ...editDraft,
                            unit_price: e.target.value,
                          })
                        }
                        style={{ textAlign: "right", maxWidth: 90 }}
                      />
                    </td>
                    <td>
                      <input
                        className="field-input"
                        value={editDraft.vat_pct}
                        onChange={(e) =>
                          setEditDraft({ ...editDraft, vat_pct: e.target.value })
                        }
                        style={{ textAlign: "right", maxWidth: 70 }}
                      />
                    </td>
                    <td style={{ textAlign: "right" }}>
                      {formatMoney(line.line_total)}
                    </td>
                    <td className="muted small">
                      {line.extra_work !== null
                        ? t("invoice_detail.line_ew")
                        : t("invoice_detail.line_hand")}
                    </td>
                    <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={() => handleSaveLine(line.id)}
                        disabled={busy}
                        data-testid="invoice-line-save"
                      >
                        {t("invoice_detail.line_save")}
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => setEditingId(null)}
                        disabled={busy}
                      >
                        {t("invoice_detail.line_cancel")}
                      </button>
                    </td>
                  </tr>
                ) : (
                  <tr key={line.id} data-testid="invoice-line-row">
                    <td>{line.description || "—"}</td>
                    <td style={{ textAlign: "right" }}>{line.quantity}</td>
                    <td style={{ textAlign: "right" }}>
                      {formatMoney(line.unit_price)}
                    </td>
                    <td style={{ textAlign: "right" }}>{line.vat_pct}</td>
                    <td style={{ textAlign: "right" }}>
                      {formatMoney(line.line_total)}
                    </td>
                    <td className="muted small">
                      {line.extra_work !== null
                        ? t("invoice_detail.line_ew")
                        : t("invoice_detail.line_hand")}
                    </td>
                    {isDraft && (
                      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          onClick={() => startEdit(line)}
                          disabled={busy}
                          data-testid="invoice-line-edit"
                        >
                          {t("invoice_detail.line_edit")}
                        </button>
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm"
                          style={{ color: "var(--red)" }}
                          onClick={() => {
                            setPendingRemoveLine(line);
                            removeLineDialogRef.current?.open();
                          }}
                          disabled={busy}
                          data-testid="invoice-line-remove"
                        >
                          {t("invoice_detail.line_remove")}
                        </button>
                      </td>
                    )}
                  </tr>
                ),
              )}
              {isDraft && addOpen && (
                <tr data-testid="invoice-add-line-row">
                  <td>
                    <input
                      className="field-input"
                      value={addDraft.description}
                      placeholder={t("invoice_detail.line_desc")}
                      onChange={(e) =>
                        setAddDraft({ ...addDraft, description: e.target.value })
                      }
                      data-testid="invoice-add-line-desc"
                    />
                  </td>
                  <td>
                    <input
                      className="field-input"
                      value={addDraft.quantity}
                      onChange={(e) =>
                        setAddDraft({ ...addDraft, quantity: e.target.value })
                      }
                      style={{ textAlign: "right", maxWidth: 80 }}
                      data-testid="invoice-add-line-qty"
                    />
                  </td>
                  <td>
                    <input
                      className="field-input"
                      value={addDraft.unit_price}
                      onChange={(e) =>
                        setAddDraft({ ...addDraft, unit_price: e.target.value })
                      }
                      style={{ textAlign: "right", maxWidth: 90 }}
                      data-testid="invoice-add-line-unit"
                    />
                  </td>
                  <td>
                    <input
                      className="field-input"
                      value={addDraft.vat_pct}
                      onChange={(e) =>
                        setAddDraft({ ...addDraft, vat_pct: e.target.value })
                      }
                      style={{ textAlign: "right", maxWidth: 70 }}
                    />
                  </td>
                  <td />
                  <td className="muted small">
                    {t("invoice_detail.line_hand")}
                  </td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      onClick={handleAddLine}
                      disabled={busy}
                      data-testid="invoice-add-line-save"
                    >
                      {t("invoice_detail.line_save")}
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      onClick={() => setAddOpen(false)}
                      disabled={busy}
                    >
                      {t("invoice_detail.line_cancel")}
                    </button>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Summary (page 1). */}
      <section className="card" style={{ padding: "16px 20px", marginBottom: 16 }}>
        <div className="section-head-title">
          {t("invoice_detail.summary_title")}
        </div>
        {isDraft ? (
          <>
            <p className="muted small" style={{ marginTop: 4 }}>
              {t("invoice_detail.summary_hint")}
            </p>
            <textarea
              className="field-input"
              rows={3}
              value={summaryDraft}
              onChange={(e) => setSummaryDraft(e.target.value)}
              style={{ width: "100%", marginTop: 8 }}
              data-testid="invoice-summary-input"
            />
            <div className="form-actions" style={{ marginTop: 8 }}>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleSaveSummary}
                disabled={busy}
                data-testid="invoice-summary-save"
              >
                {t("invoice_detail.summary_save")}
              </button>
            </div>
          </>
        ) : (
          <p style={{ marginTop: 8 }}>{invoice.summary_text || "—"}</p>
        )}
      </section>

      {/* Fee box. */}
      <section className="card" style={{ padding: "16px 20px", marginBottom: 16 }}>
        <div className="section-head-title">{t("invoice_detail.fee_title")}</div>
        {isDraft ? (
          <>
            <p className="muted small" style={{ marginTop: 4 }}>
              {t("invoice_detail.fee_hint")}
            </p>
            <div
              style={{
                display: "flex",
                gap: 16,
                flexWrap: "wrap",
                marginTop: 8,
              }}
            >
              <label className="field" style={{ flex: "1 1 240px" }}>
                <span className="field-label">
                  {t("invoice_detail.fee_label")}
                </span>
                <input
                  className="field-input"
                  value={feeLabel}
                  onChange={(e) => setFeeLabel(e.target.value)}
                  data-testid="invoice-fee-label"
                />
              </label>
              <label className="field" style={{ flex: "0 0 160px" }}>
                <span className="field-label">
                  {t("invoice_detail.fee_amount")}
                </span>
                <input
                  className="field-input"
                  value={feeAmount}
                  onChange={(e) => setFeeAmount(e.target.value)}
                  inputMode="decimal"
                  style={{ textAlign: "right" }}
                  data-testid="invoice-fee-amount"
                />
              </label>
            </div>
            <div className="form-actions" style={{ marginTop: 8 }}>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleSaveFee}
                disabled={busy}
                data-testid="invoice-fee-save"
              >
                {t("invoice_detail.fee_save")}
              </button>
            </div>
          </>
        ) : invoice.optional_fee_amount ? (
          <p style={{ marginTop: 8 }}>
            {invoice.optional_fee_label || "—"} ·{" "}
            {formatMoney(invoice.optional_fee_amount)}
          </p>
        ) : (
          <p className="muted" style={{ marginTop: 8 }}>
            —
          </p>
        )}
      </section>

      <ConfirmDialog
        ref={lifecycleDialogRef}
        title={lifecycleCopy.title}
        body={lifecycleCopy.body}
        confirmLabel={lifecycleCopy.confirm}
        onConfirm={handleConfirmLifecycle}
        onCancel={() => setPendingLifecycle(null)}
        busy={busy}
        destructive={
          pendingLifecycle === "delete" || pendingLifecycle === "reverse"
        }
      />
      <ConfirmDialog
        ref={removeLineDialogRef}
        title={t("invoice_detail.confirm_remove_line_title")}
        body={
          pendingRemoveLine && pendingRemoveLine.extra_work !== null
            ? t("invoice_detail.confirm_remove_line_body_ew")
            : t("invoice_detail.confirm_remove_line_body_hand")
        }
        confirmLabel={t("invoice_detail.line_remove")}
        onConfirm={handleConfirmRemoveLine}
        onCancel={() => setPendingRemoveLine(null)}
        busy={busy}
        destructive
      />
    </div>
  );
}
