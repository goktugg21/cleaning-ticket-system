/**
 * W18 — ONE "Extra work" card on the operational ticket.
 *
 * One work, one page: a chargeable row opens the TICKET, so the ticket
 * carries the Extra-Work facts. W17 split them over two cards (money +
 * a separate hours panel whose 160px table column clipped the input out
 * of the narrow rail); this is the merge. Per hourly line a stacked
 * label-over-input row, the amounts under them, billing month and
 * invoice state read-only, and ONE button: Save hours. Fixed-price work
 * has no hours affordance at all — absent, not disabled.
 *
 * PROVIDER-ONLY, and the CALLER gates the mount: STAFF get a hard 404
 * on `GET /api/extra-work/<id>/` (`scope_extra_work_for` returns
 * `.none()` for them — measured, not assumed), so the fetch must never
 * fire for a role that cannot pass it, and customers keep their
 * existing surfaces. A provider whose scope still refuses the record
 * (a BUILDING_MANAGER outside the building) collapses to nothing
 * rather than to an error card.
 *
 * Money comes from `rowAmounts()` — the ONE billing-total rule
 * (final-with-quoted-fallback) — never a hand-sum. `isPriced` keeps
 * "unpriced" (an em dash) from ever rendering like "costs nothing"
 * (a real EUR 0,00). On top of that, W18: while the active priced set
 * has hourly lines and no final amount exists yet, the amounts are a
 * projection, not a bill — they render as an em dash with an
 * "awaiting worked hours" state instead of a EUR 0,00 that reads as
 * "costs nothing". Scoped HERE; `isPriced`/`rowAmounts` serve the
 * lists unchanged.
 */
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  fetchProposalPdf,
  getExtraWork,
  getProposalDetail,
  listProposalsForEw,
  transitionExtraWork,
  updateExtraWorkBilling,
} from "../../api/extraWork";
import type {
  ExtraWorkRequestDetail,
  Proposal,
  ProposalDetail,
} from "../../api/types";
import { isPriced, rowAmounts } from "../../lib/billing";
import { formatDate, formatMoney, formatNumber } from "../../lib/intl";
import { CollapsibleCard } from "../CollapsibleCard";
import { PdfPreviewDialog } from "../PdfPreviewDialog";
import type { PdfPreviewDialogHandle } from "../PdfPreviewDialog";
import { StatusBadge } from "../StatusBadge";
import { useToast } from "../ToastProvider";
import { ActualHoursPanel } from "./ActualHoursPanel";
import {
  actualHoursPanelKey,
  deriveActiveHourlyLines,
  finiteOrNull,
  selectApprovedProposal,
} from "./activeHourlyLines";

// W25 — ONE column geometry for the Agreement card's tables, shared by
// the header row and the data rows so the words sit over the numbers
// they name. The name cell takes the slack and wraps; the two number
// cells keep a fixed basis, which is what makes a header meaningful at
// all (a header over an elastic column names nothing). Sized for the
// ~340px ticket rail at 1366 — measured, not guessed.
const CELL_NAME = {
  flex: "1 1 auto",
  minWidth: 0,
  overflowWrap: "anywhere",
} as const;
const CELL_QTY = {
  flex: "0 0 54px",
  textAlign: "right",
  whiteSpace: "nowrap",
} as const;
const CELL_AMOUNT = {
  flex: "0 0 86px",
  textAlign: "right",
  whiteSpace: "nowrap",
} as const;
const ROW_STYLE = {
  display: "flex",
  alignItems: "baseline",
  gap: 8,
  padding: "4px 0",
} as const;

export function TicketExtraWorkCards({
  extraWorkId,
  currentTicketId,
  onChanged,
}: {
  extraWorkId: number;
  /** W21 — the job page this card group is mounted on, so the series
   *  day list can render THIS day as text instead of a self-link. */
  currentTicketId?: number;
  /** W22 — called after a write that the ticket page may want to
   *  re-read for (the cancel; the ticket itself is NOT auto-cancelled,
   *  but its convert/origin affordances read the EW state). */
  onChanged?: () => void;
}) {
  const { t } = useTranslation(["ticket_detail", "extra_work"]);
  const { push: pushToast } = useToast();
  const [ew, setEw] = useState<ExtraWorkRequestDetail | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [approvedProposalDetail, setApprovedProposalDetail] =
    useState<ProposalDetail | null>(null);
  const [pdfBusy, setPdfBusy] = useState(false);
  /** W-HOURS4 Task 4 — the in-app preview of the same document the
   *  Download button fetches. Native `<dialog>`, rendered
   *  unconditionally below and driven through the ref (CLAUDE.md). */
  const pdfPreviewRef = useRef<PdfPreviewDialogHandle>(null);
  // W22 §1 — the billing-month editor, rebuilt from the request page
  // (the redirect closed that page for providers, and the month was
  // one of the three facts that lived only there). `null` draft means
  // "showing the stored value"; "" means the operator cleared it, which
  // PATCHes invoice_date null = follows the completion month.
  const [billingDraft, setBillingDraft] = useState<string | null>(null);
  const [billingBusy, setBillingBusy] = useState(false);
  // W22 §2 — cancel modal state. The server refuses IN_PROGRESS ->
  // CANCELLED without an override_reason (400 override_reason_required),
  // so the modal collects it and shows the server's refusal in place.
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [cancelBusy, setCancelBusy] = useState(false);
  const [cancelError, setCancelError] = useState("");

  useEffect(() => {
    let cancelled = false;
    getExtraWork(extraWorkId)
      .then((detail) => {
        if (!cancelled) setEw(detail);
      })
      .catch(() => {
        // Out-of-scope or gone: the ticket page stands on its own.
        if (!cancelled) setEw(null);
      });
    listProposalsForEw(extraWorkId)
      .then((list) => {
        if (!cancelled) setProposals(list);
      })
      .catch(() => {
        if (!cancelled) setProposals([]);
      });
    return () => {
      cancelled = true;
    };
  }, [extraWorkId]);

  // The approved proposal's lines (with `actual_hours`) are NOT on the
  // EW detail payload — same second fetch the Extra Work page does.
  const approvedProposal = selectApprovedProposal(proposals);
  const approvedProposalId = approvedProposal?.id ?? null;
  useEffect(() => {
    let cancelled = false;
    if (approvedProposalId === null) {
      queueMicrotask(() => {
        if (!cancelled) setApprovedProposalDetail(null);
      });
      return () => {
        cancelled = true;
      };
    }
    getProposalDetail(extraWorkId, approvedProposalId)
      .then((detail) => {
        if (!cancelled) setApprovedProposalDetail(detail);
      })
      .catch(() => {
        if (!cancelled) setApprovedProposalDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [extraWorkId, approvedProposalId]);

  if (!ew) return null;

  const amounts = rowAmounts(ew);
  const priced = isPriced(ew);
  const activeHourlyLines = deriveActiveHourlyLines(
    ew,
    approvedProposal,
    approvedProposalDetail,
  );
  // W18 — hourly lines with no final amount yet: the quoted numbers are
  // a projection. Em dash + state label, never a EUR 0,00 that reads
  // as "costs nothing".
  const awaitingHours =
    activeHourlyLines.length > 0 && ew.final_total_amount === null;
  // W21 — the THIRD money state. Same active-set precedence the backend
  // `is_priced_expression` walks (approved proposal > INSTANT cart >
  // legacy pricing rows), WITHOUT the hourly filter: zero lines in the
  // whole active set means nothing was ever agreed, which is a
  // different fact from "the agreed lines sum to zero" (a legal price)
  // and from "hourly lines await their hours". `null` while the
  // approved proposal's lines are still loading, so the state cannot
  // flash on before the data that decides it.
  const activePricedCount = approvedProposal
    ? approvedProposalDetail
      ? approvedProposalDetail.lines.filter((l) => l.is_approved_for_spawn)
          .length
      : null
    : ew.routing_decision === "INSTANT"
      ? ew.line_items.length
      : ew.pricing_line_items.length;
  const noPriceAgreed = activePricedCount === 0;
  const money = (value: number) =>
    priced && !awaitingHours && !noPriceAgreed ? formatMoney(value) : "—";
  // Same lock the Extra Work page derives: the backend freezes the final
  // amount once any spawned operational ticket is APPROVED or CLOSED.
  const finalAmountLocked = ew.spawned_tickets.some(
    (spawned) => spawned.status === "APPROVED" || spawned.status === "CLOSED",
  );
  // PDF read is action-driven, same as the Extra Work page: absent
  // `actions` (older response) falls back to offering it — the caller
  // already gates this card to provider management.
  const canViewProposalPdf = ew.actions
    ? ew.actions.can_view_proposal_pdf
    : true;
  const isSeries = ew.spawned_tickets.length > 1;
  // W21 — the Agreement card's three tables, from data this component
  // ALREADY holds (no new fetches): the cart the customer asked for,
  // the approved proposal's agreed lines, and the day-by-day spawned
  // tickets ordered the way the redirect orders them (scheduled date,
  // undated last, id as tiebreak).
  // W22 §3a — the Agreed table follows the SAME precedence walk the
  // money totals follow (approved proposal > INSTANT cart > legacy
  // pricing rows), so "Agreed" can never name a different set than the
  // amounts under it. Proposal and legacy lines carry their own
  // computed totals; a cart line's agreed amount is its contract unit
  // price × quantity, and a NEEDS_PROPOSAL cart line has no price yet
  // — an em dash, never a zero (zero is a legal price).
  // W22.2 — a parsed amount is a finite number or null: a missing/
  // blank/unparseable source value becomes null and the cell renders
  // the em dash explicitly. The formatters are never handed null and
  // asked to be graceful. W25 moved `finiteOrNull` into
  // `activeHourlyLines` so the hours panel's arithmetic and these
  // tables read a source string exactly one way.
  const agreedRows: {
    id: number;
    label: string;
    quantity: string | null;
    amount: number | null;
  }[] = approvedProposal
    ? (approvedProposalDetail?.lines ?? [])
        .filter((line) => line.is_approved_for_spawn)
        .map((line) => ({
          id: line.id,
          label: line.service_name ?? line.description,
          quantity: line.quantity ?? null,
          amount: finiteOrNull(line.line_total),
        }))
    : ew.routing_decision === "INSTANT"
      ? ew.line_items.map((line) => ({
          id: line.id,
          label: line.service_name || line.custom_description,
          quantity: line.quantity ?? null,
          amount:
            finiteOrNull(line.contract_unit_price) !== null &&
            finiteOrNull(line.quantity) !== null
              ? (finiteOrNull(line.contract_unit_price) as number) *
                (finiteOrNull(line.quantity) as number)
              : null,
        }))
      : ew.pricing_line_items.map((line) => ({
          id: line.id,
          label: line.description,
          quantity: line.quantity ?? null,
          amount: finiteOrNull(line.total),
        }));
  // W22 §3b — nothing asks twice: the Requested table exists to show
  // what the customer asked BEFORE a proposal re-priced it. With no
  // approved proposal, Agreed IS the requested cart — one table.
  const showRequested = approvedProposal !== null && ew.line_items.length > 0;
  const sortedSpawned = [...ew.spawned_tickets].sort((a, b) => {
    const ad = a.scheduled_start_at ?? "9999-12-31T23:59:59Z";
    const bd = b.scheduled_start_at ?? "9999-12-31T23:59:59Z";
    if (ad !== bd) return ad < bd ? -1 : 1;
    return a.id - b.id;
  });
  const hasAgreement =
    showRequested ||
    agreedRows.length > 0 ||
    (approvedProposalId !== null && canViewProposalPdf) ||
    isSeries;
  // W22 §2 — rule 6: the action renders only when the server's own list
  // says this viewer may drive it. `allowed_next_statuses` is computed
  // per-user through `_user_can_drive_transition`, so status, role and
  // scope are one server-derived fact, not three client guesses.
  const canCancel = ew.allowed_next_statuses.includes("CANCELLED");

  async function handleDownloadPdf() {
    if (approvedProposalId === null) return;
    setPdfBusy(true);
    try {
      const blob = await fetchProposalPdf(extraWorkId, approvedProposalId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `proposal-${approvedProposalId}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      pushToast({ variant: "error", title: getApiError(err) });
    } finally {
      setPdfBusy(false);
    }
  }

  /** W-HOURS4 Task 4 — Preview beside Download. The dialog fetches the
   *  SAME route `fetchProposalPdf` (`api/extraWork.ts`) downloads, as
   *  an authenticated blob, and keeps its own Download button: a
   *  proposal is preview + download (only credentials are preview-only). */
  function openPdfPreview() {
    if (approvedProposalId === null) return;
    pdfPreviewRef.current?.open({
      url: `/extra-work/${extraWorkId}/proposals/${approvedProposalId}/pdf/`,
      filename: `proposal-${approvedProposalId}.pdf`,
    });
  }

  const storedBillingMonth = ew.invoice_date ? ew.invoice_date.slice(0, 7) : "";
  const billingValue = billingDraft ?? storedBillingMonth;

  async function saveBillingMonth() {
    if (!ew || billingBusy) return;
    setBillingBusy(true);
    try {
      const updated = await updateExtraWorkBilling(ew.id, {
        invoice_date: billingValue === "" ? null : `${billingValue}-01`,
      });
      setEw(updated);
      setBillingDraft(null);
      // Rule 4 — the answer states the month the SERVER stored, not the
      // one that was typed; a server that stored something else must
      // not be reported as success.
      pushToast({
        variant: "success",
        title: updated.invoice_date
          ? t("ew_billing_saved", { month: updated.invoice_date.slice(0, 7) })
          : t("ew_billing_cleared"),
      });
    } catch (err) {
      pushToast({ variant: "error", title: getApiError(err) });
    } finally {
      setBillingBusy(false);
    }
  }

  async function handleConfirmCancel() {
    if (!ew || cancelBusy) return;
    const reason = cancelReason.trim();
    if (reason === "") return;
    setCancelBusy(true);
    setCancelError("");
    try {
      // `override_reason` satisfies the IN_PROGRESS gate (the server
      // coerces is_override there); `note` lands the same words on the
      // history row for the pre-spawn statuses where no override is in
      // play — the reason is recorded whichever pair this is.
      const updated = await transitionExtraWork(ew.id, {
        to_status: "CANCELLED",
        override_reason: reason,
        note: reason,
      });
      setEw(updated);
      setCancelOpen(false);
      setCancelReason("");
      pushToast({ variant: "success", title: t("ew_cancel_done") });
      onChanged?.();
    } catch (err) {
      setCancelError(getApiError(err));
    } finally {
      setCancelBusy(false);
    }
  }

  return (
    <>
    <div className="card" data-testid="ticket-extra-work-money">
      <div className="form-section">
        <div className="form-section-title">{t("ew_card_title")}</div>
        {activeHourlyLines.length > 0 && (
          <ActualHoursPanel
            variant="embedded"
            key={actualHoursPanelKey(
              approvedProposal,
              activeHourlyLines,
              ew.updated_at,
            )}
            ewId={ew.id}
            hourlyLines={activeHourlyLines}
            finalTotalAmount={ew.final_total_amount}
            // W22 §4 — the save answers with the card's own facts: the
            // hours just written, the total they produced (rowAmounts,
            // the ONE rule, over the refreshed detail) and the month it
            // bills in. No new fetch — everything is in the response.
            successMessage={(detail, hoursSaved) =>
              detail.invoice_date
                ? t("ew_hours_saved", {
                    hours: formatNumber(hoursSaved),
                    total: formatMoney(rowAmounts(detail).total),
                    month: detail.invoice_date.slice(0, 7),
                  })
                : t("ew_hours_saved_no_month", {
                    hours: formatNumber(hoursSaved),
                    total: formatMoney(rowAmounts(detail).total),
                  })
            }
            locked={finalAmountLocked}
            // W25 — the client-side math per line is a PREVIEW. The
            // saved subtotal comparison is only offered when these
            // hourly lines ARE the whole active priced set, because the
            // PATCH response carries no per-line amounts and a partial
            // sum cannot be compared to a whole one.
            previewCoversTotal={
              activePricedCount !== null &&
              activeHourlyLines.length === activePricedCount
            }
            finalSubtotalAmount={ew.final_subtotal_amount}
            onUpdated={(detail) => {
              setEw(detail);
              if (approvedProposalId !== null) {
                getProposalDetail(extraWorkId, approvedProposalId)
                  .then(setApprovedProposalDetail)
                  .catch(() => {
                    // Keep the prior detail; a transient refresh failure
                    // must not blank the fields mid-edit.
                  });
              }
            }}
          />
        )}
        <div className="detail-kv-list">
          <div className="detail-kv-row">
            <span className="detail-kv-label">{t("ew_card_subtotal")}</span>
            <span className="detail-kv-val" data-testid="ticket-ew-subtotal">
              {money(amounts.subtotal)}
            </span>
          </div>
          <div className="detail-kv-row">
            <span className="detail-kv-label">{t("ew_card_vat")}</span>
            <span className="detail-kv-val">{money(amounts.vat)}</span>
          </div>
          <div className="detail-kv-row">
            <span className="detail-kv-label">{t("ew_card_total")}</span>
            <span className="detail-kv-val" data-testid="ticket-ew-total">
              <strong>{money(amounts.total)}</strong>
              {/* Three states, never conflated: an agreed zero renders
                  as EUR 0,00 with no label; an empty active set says
                  nothing was agreed; hourly lines say what they wait
                  for. `noPriceAgreed` wins — an empty set has no hours
                  to await. */}
              {noPriceAgreed ? (
                <span
                  className="muted small"
                  style={{ marginLeft: 8 }}
                  data-testid="ticket-ew-no-price"
                >
                  {t("ew_card_no_price")}
                </span>
              ) : (
                awaitingHours && (
                  <span
                    className="muted small"
                    style={{ marginLeft: 8 }}
                    data-testid="ticket-ew-awaiting-hours"
                  >
                    {t("ew_card_awaiting_hours")}
                  </span>
                )
              )}
            </span>
          </div>
          <div className="detail-kv-row">
            <span className="detail-kv-label">
              {t("ew_card_billing_month")}
            </span>
            {/* W22 §1 — the value IS the control (the request page's
                editor, rebuilt here since the redirect closed that page
                for providers). Empty + save = follows the completion
                month again (invoice_date null). */}
            <span
              className="detail-kv-val"
              data-testid="ticket-ew-billing-month"
              style={{ display: "flex", gap: 8, alignItems: "center" }}
            >
              <input
                type="month"
                className="field-input"
                style={{ minWidth: 0, flex: 1 }}
                value={billingValue}
                onChange={(event) => setBillingDraft(event.target.value)}
                aria-label={t("extra_work:detail.billing_month_input_label")}
                data-testid="ticket-ew-billing-month-input"
              />
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={billingBusy || billingValue === storedBillingMonth}
                onClick={() => void saveBillingMonth()}
                data-testid="ticket-ew-billing-save"
              >
                {t("extra_work:detail.billing_save")}
              </button>
            </span>
          </div>
          <div className="detail-kv-row">
            <span className="detail-kv-label">{t("ew_card_invoiced")}</span>
            <span className="detail-kv-val" data-testid="ticket-ew-invoiced">
              {ew.is_invoiced
                ? t("extra_work:detail.billing_invoiced_on", {
                    date: ew.invoiced_at ? formatDate(ew.invoiced_at) : "—",
                  })
                : t("extra_work:detail.billing_not_invoiced")}
            </span>
          </div>
        </div>
        {/* W22 §2 — the cancel, home from the closed request page. A
            secondary action, rendered only when `allowed_next_statuses`
            offers CANCELLED to THIS viewer (rule 6). */}
        {canCancel && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            style={{ alignSelf: "flex-start" }}
            onClick={() => {
              setCancelError("");
              setCancelOpen(true);
            }}
            data-testid="ticket-ew-cancel-button"
          >
            {t("ew_cancel_action")}
          </button>
        )}
      </div>
    </div>
    {/* W21 — THE AGREEMENT CARD. What was asked, what was agreed, the
        paper it was agreed on, and (for a series) the days it became.
        This card replaced the "Request & proposal" origin link and the
        "Series overview" escape: the request page no longer exists for
        a provider once work is spawned, so everything it was opened for
        lives here. Collapsed by default — it is reference, not the
        job's live state. Names, tables and row links only. */}
    {hasAgreement && (
      <CollapsibleCard
        title={t("ew_agreement_title")}
        // W-PLAN2 Task 2 — open by default (Details + Activity are
        // the only cards that stay collapsed). One token; declared as
        // out-of-owned-list in the wave report.
        defaultOpen
        testId="side-card-agreement"
      >
        <div style={{ padding: "14px 18px 16px" }}>
          {/* W22 §3b — Requested renders only when a proposal re-priced
              the ask; with no proposal, Agreed IS the requested cart
              and nothing asks twice (rule 8). */}
          {/* W22.2 — NOT `.data-table`: that class carries a min-width
              of 860px (index.css) for the wide list pages, and inside
              this ~340px rail card it pushed the quantity and money
              cells past the viewport's right edge, where `.workspace`
              clipped them — the owner saw only the line's name (the
              same clipping mode W18 fixed for the hours input). Fluid
              flex rows: the name wraps, the numbers keep their spot. */}
          {showRequested && (
            <>
              <div className="detail-kv-label">
                {t("ew_agreement_requested")}
              </div>
              <div data-testid="ticket-ew-requested-lines">
                {/* W25 — the column words. Without them a number in the
                    rail is just a number; the owner could not tell an
                    amount from a count. The requested cart has NO money
                    column (it is what was asked, before anything was
                    priced), so it gets the two headers it actually has
                    — an "Amount" over an absent column would be the
                    lie the header exists to prevent. */}
                <div
                  style={ROW_STYLE}
                  data-testid="ticket-ew-requested-head"
                >
                  <span className="detail-kv-label" style={CELL_NAME}>
                    {t("extra_work:detail.agreement_col_service")}
                  </span>
                  <span className="detail-kv-label" style={CELL_QTY}>
                    {t("extra_work:detail.agreement_col_qty")}
                  </span>
                </div>
                {ew.line_items.map((line) => (
                  <div key={line.id} style={ROW_STYLE}>
                    <span style={CELL_NAME}>
                      {line.service_name || line.custom_description}
                    </span>
                    <span style={CELL_QTY}>
                      {line.quantity != null && line.quantity !== ""
                        ? formatNumber(line.quantity)
                        : "—"}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
          {agreedRows.length > 0 && (
            <>
              <div
                className="detail-kv-label"
                style={showRequested ? { marginTop: 12 } : undefined}
              >
                {t("ew_agreement_agreed")}
              </div>
              <div data-testid="ticket-ew-agreed-lines">
                <div style={ROW_STYLE} data-testid="ticket-ew-agreed-head">
                  <span className="detail-kv-label" style={CELL_NAME}>
                    {t("extra_work:detail.agreement_col_service")}
                  </span>
                  <span className="detail-kv-label" style={CELL_QTY}>
                    {t("extra_work:detail.agreement_col_qty")}
                  </span>
                  <span className="detail-kv-label" style={CELL_AMOUNT}>
                    {t("extra_work:detail.agreement_col_amount")}
                  </span>
                </div>
                {agreedRows.map((row) => (
                  <div key={row.id} style={ROW_STYLE}>
                    <span style={CELL_NAME}>{row.label}</span>
                    <span style={CELL_QTY}>
                      {row.quantity !== null && row.quantity !== ""
                        ? formatNumber(row.quantity)
                        : "—"}
                    </span>
                    <span style={{ ...CELL_AMOUNT, fontWeight: 500 }}>
                      {row.amount !== null ? formatMoney(row.amount) : "—"}
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
          {approvedProposalId !== null && canViewProposalPdf && (
            <div
              style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 12 }}
              data-testid="ticket-ew-proposal-pdf-actions"
            >
              {/* W-HOURS4 Task 4 — Preview opens the same document in
                  the in-app viewer, download kept. */}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={openPdfPreview}
                data-testid="ticket-ew-proposal-preview"
              >
                {t("extra_work:detail.pdf_preview_button")}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  void handleDownloadPdf();
                }}
                disabled={pdfBusy}
                data-testid="ticket-ew-proposal-pdf"
              >
                {pdfBusy
                  ? t("extra_work:detail.pdf_download_busy")
                  : t("extra_work:detail.pdf_download_button")}
              </button>
            </div>
          )}
          {isSeries && (
            <>
              <div className="detail-kv-label" style={{ marginTop: 12 }}>
                {t("ew_agreement_days")}
              </div>
              <ul
                className="ew-spawned-tickets-list"
                data-testid="ticket-ew-series-days"
              >
                {sortedSpawned.map((day) => (
                  <li
                    key={day.id}
                    className="ew-spawned-ticket-row"
                    data-testid={`ticket-ew-series-day-${day.id}`}
                  >
                    {day.id === currentTicketId ? (
                      <span style={{ fontSize: 14, fontWeight: 500 }}>
                        {day.scheduled_start_at
                          ? formatDate(day.scheduled_start_at)
                          : "—"}
                      </span>
                    ) : (
                      <Link
                        to={`/tickets/${day.id}`}
                        className="ew-spawned-ticket-link"
                      >
                        {day.scheduled_start_at
                          ? formatDate(day.scheduled_start_at)
                          : "—"}
                      </Link>
                    )}
                    <StatusBadge
                      status={{ kind: "ticket", value: day.status }}
                      variant="cell"
                    />
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </CollapsibleCard>
    )}
    {/* W22 §2 — the cancel modal. The reason is the server's own
        requirement (400 override_reason_required on in-flight work), so
        the confirm stays disabled until one is written and the server's
        refusal renders inside the modal. The warning states the one
        thing the press does NOT do: this ticket is not auto-cancelled.
        Same overlay classes as RejectReasonDialog — no new CSS. */}
    {cancelOpen && (
      <div
        className="reject-modal-backdrop"
        role="dialog"
        aria-modal="true"
        data-testid="ticket-ew-cancel-modal"
      >
        <div className="reject-modal">
          <h3 className="reject-modal-title">
            {t("extra_work:detail.cancel_dialog_title")}
          </h3>
          <p className="reject-modal-desc">
            {t("extra_work:detail.cancel_dialog_spawned_warning_desc")}
          </p>
          {cancelError && (
            <div
              className="alert-error"
              role="alert"
              data-testid="ticket-ew-cancel-error"
            >
              {cancelError}
            </div>
          )}
          <label
            className="field-label"
            htmlFor="ticket-ew-cancel-reason"
          >
            {t("ew_cancel_reason_label")}
          </label>
          <textarea
            id="ticket-ew-cancel-reason"
            className="field-textarea reject-modal-textarea"
            rows={4}
            value={cancelReason}
            onChange={(event) => setCancelReason(event.target.value)}
            data-testid="ticket-ew-cancel-reason"
            autoFocus
          />
          <div className="reject-modal-actions">
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setCancelOpen(false);
                setCancelReason("");
                setCancelError("");
              }}
              disabled={cancelBusy}
              data-testid="ticket-ew-cancel-keep"
            >
              {t("extra_work:detail.cancel_dialog_keep")}
            </button>
            <button
              type="button"
              className="btn btn-danger btn-sm"
              onClick={() => void handleConfirmCancel()}
              disabled={cancelBusy || cancelReason.trim() === ""}
              data-testid="ticket-ew-cancel-confirm"
            >
              {t("extra_work:detail.cancel_dialog_confirm")}
            </button>
          </div>
        </div>
      </div>
    )}
    {/* W-HOURS4 Task 4 — rendered UNCONDITIONALLY and driven through the
        ref (CLAUDE.md's rule for a native <dialog>). `withDownload`
        stays on: a proposal is a document you keep. */}
    <PdfPreviewDialog ref={pdfPreviewRef} />
    </>
  );
}
