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
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  fetchProposalPdf,
  getExtraWork,
  getProposalDetail,
  listProposalsForEw,
} from "../../api/extraWork";
import type {
  ExtraWorkRequestDetail,
  Proposal,
  ProposalDetail,
} from "../../api/types";
import { isPriced, rowAmounts } from "../../lib/billing";
import { formatDate, formatMoney } from "../../lib/intl";
import { useToast } from "../ToastProvider";
import { ActualHoursPanel } from "./ActualHoursPanel";
import {
  actualHoursPanelKey,
  deriveActiveHourlyLines,
  selectApprovedProposal,
} from "./activeHourlyLines";

export function TicketExtraWorkCards({
  extraWorkId,
}: {
  extraWorkId: number;
}) {
  const { t } = useTranslation(["ticket_detail", "extra_work"]);
  const { push: pushToast } = useToast();
  const [ew, setEw] = useState<ExtraWorkRequestDetail | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [approvedProposalDetail, setApprovedProposalDetail] =
    useState<ProposalDetail | null>(null);
  const [pdfBusy, setPdfBusy] = useState(false);

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
  const money = (value: number) =>
    priced && !awaitingHours ? formatMoney(value) : "—";
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

  return (
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
            locked={finalAmountLocked}
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
              {awaitingHours && (
                <span
                  className="muted small"
                  style={{ marginLeft: 8 }}
                  data-testid="ticket-ew-awaiting-hours"
                >
                  {t("ew_card_awaiting_hours")}
                </span>
              )}
            </span>
          </div>
          <div className="detail-kv-row">
            <span className="detail-kv-label">
              {t("ew_card_billing_month")}
            </span>
            <span
              className="detail-kv-val"
              data-testid="ticket-ew-billing-month"
            >
              {ew.invoice_date
                ? ew.invoice_date.slice(0, 7)
                : t("extra_work:detail.billing_follows_completion")}
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
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          {approvedProposalId !== null && canViewProposalPdf && (
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
          )}
          {isSeries && (
            <Link
              to={`/extra-work/${extraWorkId}?full=1`}
              className="btn btn-ghost btn-sm"
              data-testid="ticket-ew-series-link"
            >
              {t("ew_card_series_link")}
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
