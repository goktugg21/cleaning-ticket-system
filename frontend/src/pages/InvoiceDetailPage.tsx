// Invoicing Phase 4b — the dedicated invoice-detail page.
//
// P-6 V1 (Addendum D §D.6 rule 12, rules 13–15) — the ticket detail's
// rhythm on the system's bone: a header that holds no buttons, ONE
// strip that says where the invoice stands and what happens next with
// the one primary action beside it, four facts, the lines, the text on
// the invoice behind a fold, the document, and every correction behind
// "Geavanceerd" with its existing confirm + audit surfaces.
//
// Lifecycle (Addendum B): DRAFT → ISSUED → SENT; un-issue (ISSUED →
// DRAFT); reversal (a terminal negative credit note). Numbering is
// assigned at SEND. A SENT invoice is immutable; the backend enforces
// it and a failed edit surfaces the backend message.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Download } from "lucide-react";

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
  unissueInvoice,
  updateInvoiceLine,
  updateInvoiceMeta,
} from "../api/invoices";
import type { Invoice, InvoiceLine, InvoiceStatus } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../components/ConfirmDialog";
import { PageHeader } from "../components/PageHeader";
import { RoadTabs } from "../components/guide/RoadTabs";
import { useToast } from "../components/ToastProvider";
import { formatDate, formatInvoiceGroupLabel, formatMoney } from "../lib/intl";
import { monthName } from "../lib/billingSentence";
import { customerLabelName } from "../lib/customerLabelName";

const STATUS_LABEL_KEY: Record<InvoiceStatus, string> = {
  DRAFT: "facturen.status_draft",
  ISSUED: "facturen.status_issued",
  SENT: "facturen.status_sent",
};

type LifecycleAction = "issue" | "send" | "unissue" | "reverse" | "delete";

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

/** P-7 S4.1 — the period as words ("augustus 2026"). */
function formatPeriod(year: number | null, month: number | null): string | null {
  if (!year || !month) return null;
  return monthName(`${year}-${String(month).padStart(2, "0")}`);
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
  const [pendingLifecycle, setPendingLifecycle] = useState<LifecycleAction | null>(null);
  const removeLineDialogRef = useRef<ConfirmDialogHandle>(null);
  const [pendingRemoveLine, setPendingRemoveLine] = useState<InvoiceLine | null>(null);

  const isDraft = invoice?.status === "DRAFT";
  // Sprint 122 (B1) — a reversal born ISSUED is a live credit note the
  // customer cannot see until it is sent.
  const unsentCreditNote = invoice?.is_reversal === true && invoice?.status === "ISSUED";

  function applyInvoice(fresh: Invoice) {
    setInvoice(fresh);
    setSummaryDraft(fresh.summary_text ?? "");
    setFeeLabel(fresh.optional_fee_label ?? "");
    setFeeAmount(fresh.optional_fee_amount ?? "");
  }

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
        applyInvoice(await issueInvoice(invoice.id));
        setPdfRefresh((k) => k + 1);
        pushToast({ variant: "success", title: t("invoice_detail.issued_toast") });
      } else if (pendingLifecycle === "send") {
        applyInvoice(await sendInvoice(invoice.id));
        setPdfRefresh((k) => k + 1);
        pushToast({ variant: "success", title: t("invoice_detail.sent_toast") });
      } else if (pendingLifecycle === "unissue") {
        applyInvoice(await unissueInvoice(invoice.id));
        setPdfRefresh((k) => k + 1);
        pushToast({ variant: "success", title: t("invoice_detail.unissued_toast") });
      } else if (pendingLifecycle === "reverse") {
        const reversal = await reverseInvoice(invoice.id);
        pushToast({ variant: "success", title: t("invoice_detail.reversed_toast") });
        lifecycleDialogRef.current?.close();
        setPendingLifecycle(null);
        navigate(`/invoices/${reversal.id}`);
        return;
      } else if (pendingLifecycle === "delete") {
        await deleteDraftInvoice(invoice.id);
        pushToast({ variant: "success", title: t("invoice_detail.deleted_toast") });
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
      case "unissue":
        return {
          title: t("invoice_detail.confirm_unissue_title"),
          body: t("invoice_detail.confirm_unissue_body"),
          confirm: t("invoice_detail.action_unissue"),
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
    // Never a void: the page says it cannot show the invoice, with the way back.
    return (
      <div data-testid="invoice-detail-page">
        <PageHeader
          backLink={{ to: "/invoices", label: t("invoice_detail.back") }}
          eyebrow={t("invoice_detail.eyebrow")}
          title={t("invoice_detail.unavailable_title")}
        />
        <section className="card" role="alert" style={{ padding: 22 }} data-testid="invoice-detail-unavailable">
          <p className="muted" style={{ margin: 0 }}>{error || t("invoice_detail.load_error")}</p>
        </section>
      </div>
    );
  }

  const numberText = invoice.number ?? t("facturen.concept");
  const periodText = formatPeriod(invoice.period_year, invoice.period_month);

  // ONE strip: where it stands, what happens next, the one action.
  const phase = (() => {
    if (invoice.status === "DRAFT") {
      return {
        tone: "action",
        label: t("facturen.status_draft"),
        sub: t("invoice_detail.phase_draft_sub"),
        action: (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => requestLifecycle("issue")}
            disabled={busy}
            data-testid="invoice-issue-button"
          >
            {t("invoice_detail.action_issue")}
          </button>
        ),
      };
    }
    if (invoice.status === "ISSUED") {
      return {
        tone: "action",
        label: unsentCreditNote ? t("facturen.credit_note_unsent") : t("invoice_detail.phase_issued_label"),
        sub: unsentCreditNote ? t("invoice_detail.credit_note_unsent_note") : t("invoice_detail.phase_issued_sub"),
        action: (
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => requestLifecycle("send")}
            disabled={busy}
            data-testid="invoice-send-button"
          >
            {t("invoice_detail.action_send")}
          </button>
        ),
      };
    }
    const sentOn = invoice.sent_at ? formatDate(invoice.sent_at) : "";
    return {
      tone: "done",
      label: invoice.is_reversal
        ? t("invoice_detail.phase_credit_sent_label", { date: sentOn })
        : t("invoice_detail.phase_sent_label", { date: sentOn }),
      sub: invoice.is_reversal
        ? t("invoice_detail.phase_credit_sent_sub")
        : invoice.credited_by_number
          ? t("invoice_detail.credited_note", { number: invoice.credited_by_number })
          : t("invoice_detail.phase_sent_sub"),
      action: (
        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={handleDownloadPdf}
          data-testid="invoice-pdf-download"
        >
          <Download size={14} strokeWidth={2} />
          {t("invoice_detail.pdf_download")}
        </button>
      ),
    };
  })();

  const extrasSummary = [
    invoice.summary_text ? t("invoice_detail.extras_summary_set") : null,
    invoice.optional_fee_amount
      ? t("invoice_detail.extras_fee_set", { amount: formatMoney(invoice.optional_fee_amount) })
      : null,
  ].filter(Boolean);
  const advancedItems = (
    isDraft ? ["delete"] : invoice.status === "ISSUED" && !invoice.is_reversal ? ["unissue"] : invoice.status === "SENT" && !invoice.is_reversal ? ["reverse"] : []
  ) as LifecycleAction[];

  return (
    <div data-testid="invoice-detail-page">
      <PageHeader
        backLink={{ to: "/invoices", label: t("invoice_detail.back") }}
        eyebrow={invoice.is_reversal ? t("facturen.credit_note") : t("invoice_detail.eyebrow")}
        title={<span data-testid="invoice-detail-number">{numberText}</span>}
        statusPill={
          <span
            className={
              unsentCreditNote
                ? "cell-tag cell-tag-warn"
                : invoice.status === "SENT"
                  ? "cell-tag cell-tag-open"
                  : "cell-tag cell-tag-closed"
            }
            data-testid="invoice-detail-status"
          >
            <i />
            {unsentCreditNote ? t("facturen.credit_note_unsent") : t(STATUS_LABEL_KEY[invoice.status])}
          </span>
        }
        subtitle={
          invoice.number === null
            ? `${invoice.customer_name} · ${t("facturen.concept_number_hint")}`
            : invoice.customer_name
        }
      />

      {error && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {/* P-12 D4 (§D.24 rule 3) — the same road the list shows, the
          current step marked. A credit note is born issued WITH its
          number, so the road's sentences would lie on it — no road. */}
      {!invoice.is_reversal && (
        <RoadTabs
          variant="progress"
          steps={[
            { key: "due", step: t("invoices:road.due_step"), label: t("invoices:tabs.due") },
            { key: "drafts", step: t("invoices:road.drafts_step"), label: t("invoices:tabs.drafts") },
            { key: "issued", step: t("invoices:road.issued_step"), label: t("invoices:tabs.issued") },
            { key: "sent", step: t("invoices:road.sent_step"), label: t("invoices:tabs.sent") },
          ]}
          activeKey={
            invoice.status === "DRAFT"
              ? "drafts"
              : invoice.status === "ISSUED"
                ? "issued"
                : "sent"
          }
          ariaLabel={t("facturen.title")}
          testIdPrefix="invoice-road"
        />
      )}

      <div
        className={`phase-banner phase-banner-${phase.tone}`}
        role="status"
        data-testid="invoice-phase-banner"
        data-status={invoice.status}
      >
        <div className="phase-banner-text">
          <span className="phase-banner-label">{phase.label}</span>
          <span className="phase-banner-sub">{phase.sub}</span>
        </div>
        <div className="phase-banner-action">{phase.action}</div>
      </div>

      {/* Sprint 122 (B2) — a reversed original stays SENT on the books. */}
      {invoice.credited_by_number && invoice.status !== "SENT" && (
        <div className="alert-info" role="status" style={{ marginBottom: 16 }} data-testid="invoice-credited-note">
          {t("invoice_detail.credited_note", { number: invoice.credited_by_number })}
        </div>
      )}

      {/* Facts: who, when, how much, where it stands. */}
      <div className="facts" data-testid="invoice-facts">
        <div className="ew-ctx-block" data-testid="invoice-fact-customer">
          <div className="ew-ctx-label">{t("invoice_detail.field_customer")}</div>
          <div className="ew-ctx-body">
            <div className="ew-ctx-strong">
              <Link to={`/admin/customers/${invoice.customer}`}>{invoice.customer_name}</Link>
            </div>
            <div className="ew-ctx-sub">
              {invoice.building && invoice.building_name ? (
                <Link to={`/admin/buildings/${invoice.building}`}>{invoice.building_name}</Link>
              ) : (
                t("invoice_detail.all_buildings")
              )}
            </div>
            {(invoice.department_name || invoice.work_type_name) && (
              <div className="ew-ctx-sub" data-testid="invoice-detail-group-label-row">
                {formatInvoiceGroupLabel(
                  customerLabelName(invoice.department_name, t),
                  customerLabelName(invoice.work_type_name, t),
                )}
              </div>
            )}
          </div>
        </div>
        <div className="ew-ctx-block" data-testid="invoice-fact-period">
          <div className="ew-ctx-label">{t("invoice_detail.field_period")}</div>
          <div className="ew-ctx-body">
            <div className="ew-ctx-strong">{periodText ?? t("facturen.no_period")}</div>
            {/* P-5 S7 — the contract this invoice was generated for. */}
            {invoice.contract && (
              <div className="ew-ctx-sub" data-testid="invoice-contract-row">
                <Link to={`/admin/customers/${invoice.customer}/contracts/${invoice.contract.id}`}>
                  {invoice.contract.contract_type_name
                    ? `${invoice.contract.contract_type_name} · ${invoice.contract.contract_no}`
                    : invoice.contract.contract_no}
                </Link>{" "}
                {t("invoice_detail.contract_period", {
                  from: formatDate(`${invoice.contract.period_start}T00:00:00`),
                  to: formatDate(`${invoice.contract.period_end}T00:00:00`),
                })}
              </div>
            )}
          </div>
        </div>
        <div className="ew-ctx-block" data-testid="invoice-fact-amount">
          <div className="ew-ctx-label">{t("invoice_detail.fact_amount")}</div>
          <div className="ew-ctx-body">
            <div className="ew-ctx-strong ew-ctx-money" data-testid="invoice-total">
              {formatMoney(invoice.total_amount)}
            </div>
            <div className="ew-ctx-sub" data-testid="invoice-subtotal">
              {t("invoice_detail.amount_breakdown", {
                subtotal: formatMoney(invoice.subtotal_amount),
                vat: formatMoney(invoice.vat_amount),
              })}
            </div>
          </div>
        </div>
        <div className="ew-ctx-block" data-testid="invoice-fact-dates">
          <div className="ew-ctx-label">{t("invoice_detail.fact_dates")}</div>
          <div className="ew-ctx-body">
            {/* Rule 15 — an unset date reads as words, never as a value. */}
            <div className={invoice.issued_at ? "ew-ctx-strong" : "ew-ctx-strong muted-empty"}>
              {invoice.issued_at
                ? t("invoice_detail.issued_on", { date: formatDate(invoice.issued_at) })
                : t("invoice_detail.not_issued_yet")}
            </div>
            <div className={invoice.sent_at ? "ew-ctx-sub" : "ew-ctx-sub muted-empty"}>
              {invoice.sent_at
                ? t("invoice_detail.sent_on", { date: formatDate(invoice.sent_at) })
                : t("invoice_detail.not_sent_yet")}
            </div>
            <div className="ew-ctx-sub">
              {t("invoice_detail.created_by_line", {
                who: invoice.created_by_label || t("invoices:created_by.system"),
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Lines — the bone. */}
      <section className="card" style={{ marginBottom: 16 }} data-testid="invoice-lines-card">
        <div className="section-head">
          <div>
            <div className="section-head-title">{t("invoice_detail.lines_title")}</div>
            <div className="section-head-sub">
              {isDraft ? t("invoice_detail.lines_sub_draft") : t("invoice_detail.lines_sub_final")}
            </div>
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
        {invoice.lines.length === 0 && !addOpen ? (
          <p className="muted small" style={{ padding: "0 20px 16px" }} data-testid="invoice-lines-empty">
            {t("invoice_detail.lines_empty")}
          </p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="data-table" data-testid="invoice-lines-table">
              <thead>
                <tr>
                  <th>{t("invoice_detail.line_desc")}</th>
                  <th style={{ textAlign: "right" }}>{t("invoice_detail.line_qty")}</th>
                  <th style={{ textAlign: "right" }}>{t("invoice_detail.line_unit")}</th>
                  <th style={{ textAlign: "right" }}>{t("invoice_detail.line_vat")}</th>
                  <th style={{ textAlign: "right" }}>{t("invoice_detail.line_total")}</th>
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
                          onChange={(e) => setEditDraft({ ...editDraft, description: e.target.value })}
                          data-testid="invoice-line-edit-desc"
                        />
                      </td>
                      <td>
                        <input
                          className="field-input"
                          value={editDraft.quantity}
                          onChange={(e) => setEditDraft({ ...editDraft, quantity: e.target.value })}
                          style={{ textAlign: "right", width: "100%" }}
                        />
                      </td>
                      <td>
                        <input
                          className="field-input"
                          value={editDraft.unit_price}
                          onChange={(e) => setEditDraft({ ...editDraft, unit_price: e.target.value })}
                          style={{ textAlign: "right", width: "100%" }}
                        />
                      </td>
                      <td>
                        <input
                          className="field-input"
                          value={editDraft.vat_pct}
                          onChange={(e) => setEditDraft({ ...editDraft, vat_pct: e.target.value })}
                          style={{ textAlign: "right", width: "100%" }}
                        />
                      </td>
                      <td style={{ textAlign: "right" }}>{formatMoney(line.line_total)}</td>
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
                      <td>
                        {line.description || t("invoice_detail.line_no_description")}
                        {/* P-5 S7 — the meerwerk and the building behind
                            this amount, as links; a hand line says so. */}
                        <div className="muted small" data-testid="invoice-line-source">
                          {line.extra_work !== null ? (
                            <>
                              <Link to={`/extra-work/${line.extra_work}`}>{t("invoice_detail.line_source_ew")}</Link>
                              {line.building && line.building_name ? (
                                <>
                                  {" · "}
                                  <Link to={`/admin/buildings/${line.building}`}>{line.building_name}</Link>
                                </>
                              ) : null}
                            </>
                          ) : (
                            t("invoice_detail.line_hand")
                          )}
                        </div>
                      </td>
                      <td style={{ textAlign: "right" }}>{line.quantity}</td>
                      <td style={{ textAlign: "right" }}>{formatMoney(line.unit_price)}</td>
                      <td style={{ textAlign: "right" }}>{line.vat_pct}</td>
                      <td style={{ textAlign: "right" }}>{formatMoney(line.line_total)}</td>
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
                        onChange={(e) => setAddDraft({ ...addDraft, description: e.target.value })}
                        data-testid="invoice-add-line-desc"
                      />
                    </td>
                    <td>
                      <input
                        className="field-input"
                        value={addDraft.quantity}
                        onChange={(e) => setAddDraft({ ...addDraft, quantity: e.target.value })}
                        style={{ textAlign: "right", width: "100%" }}
                        data-testid="invoice-add-line-qty"
                      />
                    </td>
                    <td>
                      <input
                        className="field-input"
                        value={addDraft.unit_price}
                        onChange={(e) => setAddDraft({ ...addDraft, unit_price: e.target.value })}
                        style={{ textAlign: "right", width: "100%" }}
                        data-testid="invoice-add-line-unit"
                      />
                    </td>
                    <td>
                      <input
                        className="field-input"
                        value={addDraft.vat_pct}
                        onChange={(e) => setAddDraft({ ...addDraft, vat_pct: e.target.value })}
                        style={{ textAlign: "right", width: "100%" }}
                      />
                    </td>
                    <td />
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
              <tfoot>
                <tr>
                  <td colSpan={4} style={{ textAlign: "right" }} className="muted small">
                    {t("invoice_detail.totals_subtotal")} {formatMoney(invoice.subtotal_amount)} ·{" "}
                    {t("invoice_detail.totals_vat")} {formatMoney(invoice.vat_amount)}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <strong>{formatMoney(invoice.total_amount)}</strong>
                  </td>
                  {isDraft && <td />}
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </section>

      {/* Text on the invoice: the page-1 summary and the optional fee. */}
      <details className="form-fold" open={isDraft && extrasSummary.length > 0} data-testid="invoice-extras-fold">
        <summary className="form-fold-summary">
          {t("invoice_detail.extras_title")}
          <span className="form-fold-summary-value">
            {extrasSummary.length > 0 ? extrasSummary.join(" · ") : t("invoice_detail.extras_none")}
          </span>
        </summary>
        <div className="form-fold-body">
          <div className="field" style={{ marginTop: 8 }}>
            <span className="field-label">{t("invoice_detail.summary_title")}</span>
            {isDraft ? (
              <>
                <span className="muted small">{t("invoice_detail.summary_hint")}</span>
                <textarea
                  className="field-input"
                  rows={3}
                  value={summaryDraft}
                  onChange={(e) => setSummaryDraft(e.target.value)}
                  style={{ width: "100%", marginTop: 6 }}
                  data-testid="invoice-summary-input"
                />
                <div className="form-actions" style={{ marginTop: 8 }}>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={handleSaveSummary}
                    disabled={busy}
                    data-testid="invoice-summary-save"
                  >
                    {t("invoice_detail.summary_save")}
                  </button>
                </div>
              </>
            ) : (
              <p style={{ margin: "4px 0 0" }} className={invoice.summary_text ? undefined : "muted small"}>
                {invoice.summary_text || t("invoice_detail.summary_empty")}
              </p>
            )}
          </div>
          <div className="field" style={{ marginTop: 14 }}>
            <span className="field-label">{t("invoice_detail.fee_title")}</span>
            {isDraft ? (
              <>
                <span className="muted small">{t("invoice_detail.fee_hint")}</span>
                <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 6 }}>
                  <label className="field" style={{ flex: "1 1 240px" }}>
                    <span className="field-label">{t("invoice_detail.fee_label")}</span>
                    <input
                      className="field-input"
                      value={feeLabel}
                      onChange={(e) => setFeeLabel(e.target.value)}
                      data-testid="invoice-fee-label"
                    />
                  </label>
                  <label className="field" style={{ flex: "0 0 160px" }}>
                    <span className="field-label">{t("invoice_detail.fee_amount")}</span>
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
                    className="btn btn-secondary btn-sm"
                    onClick={handleSaveFee}
                    disabled={busy}
                    data-testid="invoice-fee-save"
                  >
                    {t("invoice_detail.fee_save")}
                  </button>
                </div>
              </>
            ) : invoice.optional_fee_amount ? (
              <p style={{ margin: "4px 0 0" }}>
                {invoice.optional_fee_label ? `${invoice.optional_fee_label} · ` : ""}
                {formatMoney(invoice.optional_fee_amount)}
              </p>
            ) : (
              <p className="muted small" style={{ margin: "4px 0 0" }}>{t("invoice_detail.fee_none")}</p>
            )}
          </div>
        </div>
      </details>

      {/* The document. */}
      <section className="card" style={{ marginBottom: 16 }} data-testid="invoice-pdf-card">
        <div className="section-head">
          <div className="section-head-title">{t("invoice_detail.pdf_title")}</div>
          {invoice.status !== "SENT" && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={handleDownloadPdf}
              data-testid="invoice-pdf-download"
            >
              <Download size={14} strokeWidth={2} />
              {t("invoice_detail.pdf_download")}
            </button>
          )}
        </div>
        <div style={{ padding: 16 }}>
          {pdfError ? (
            <div className="alert-error" role="alert">{pdfError}</div>
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

      {/* Geavanceerd: every correction, each with its confirm + audit surface. */}
      <details className="action-fold" data-testid="invoice-advanced">
        <summary className="form-fold-summary">{t("invoice_detail.advanced")}</summary>
        {advancedItems.length > 0 && (
          <>
            <p className="muted small" style={{ margin: "8px 0 0" }}>{t("invoice_detail.advanced_intro")}</p>
            <div className="action-fold-list">
              {advancedItems.includes("delete") && (
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
              )}
              {advancedItems.includes("unissue") && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => requestLifecycle("unissue")}
                  disabled={busy}
                  data-testid="invoice-unissue-button"
                >
                  {t("invoice_detail.action_unissue")}
                </button>
              )}
              {advancedItems.includes("reverse") && (
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => requestLifecycle("reverse")}
                  disabled={busy}
                  data-testid="invoice-reverse-button"
                >
                  {t("invoice_detail.action_reverse")}
                </button>
              )}
            </div>
          </>
        )}
        <dl className="action-fold-raw">
          <dt>{t("invoice_detail.raw_id")}</dt>
          <dd><code>{invoice.id}</code></dd>
          <dt>{t("facturen.col_company")}</dt>
          <dd>{invoice.company_name}</dd>
        </dl>
      </details>

      <ConfirmDialog
        ref={lifecycleDialogRef}
        title={lifecycleCopy.title}
        body={lifecycleCopy.body}
        confirmLabel={lifecycleCopy.confirm}
        onConfirm={handleConfirmLifecycle}
        onCancel={() => setPendingLifecycle(null)}
        busy={busy}
        destructive={pendingLifecycle === "delete" || pendingLifecycle === "reverse"}
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
