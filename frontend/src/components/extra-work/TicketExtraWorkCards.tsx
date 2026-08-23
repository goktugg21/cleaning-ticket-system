/**
 * W17 §2 — the Extra Work facts, on the operational ticket.
 *
 * One work, one page: a chargeable row now opens the TICKET, so the
 * ticket must carry the Extra-Work-specific facts (money, hours,
 * billing) instead of degrading into a bare ticket page. This group
 * SHOWS and LINKS; it does not grow second editors — the billing month
 * and invoice run stay edited on the Extra Work's Money tab, which is
 * where the one button goes.
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
 * (a real EUR 0,00).
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import {
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
  const [ew, setEw] = useState<ExtraWorkRequestDetail | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [approvedProposalDetail, setApprovedProposalDetail] =
    useState<ProposalDetail | null>(null);

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
  const money = (value: number) => (priced ? formatMoney(value) : "—");
  const activeHourlyLines = deriveActiveHourlyLines(
    ew,
    approvedProposal,
    approvedProposalDetail,
  );
  // Same lock the Extra Work page derives: the backend freezes the final
  // amount once any spawned operational ticket is APPROVED or CLOSED.
  const finalAmountLocked = ew.spawned_tickets.some(
    (spawned) => spawned.status === "APPROVED" || spawned.status === "CLOSED",
  );

  return (
    <>
      <div className="card" data-testid="ticket-extra-work-money">
        <div className="form-section">
          <div className="form-section-title">{t("ew_card_title")}</div>
          <div className="detail-kv-list">
            <div className="detail-kv-row">
              <span className="detail-kv-label">{t("ew_card_subtotal")}</span>
              <span
                className="detail-kv-val"
                data-testid="ticket-ew-subtotal"
              >
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
              <span
                className="detail-kv-val"
                data-testid="ticket-ew-invoiced"
              >
                {ew.is_invoiced
                  ? t("extra_work:detail.billing_invoiced_on", {
                      date: ew.invoiced_at ? formatDate(ew.invoiced_at) : "—",
                    })
                  : t("extra_work:detail.billing_not_invoiced")}
              </span>
            </div>
          </div>
          <Link
            to={`/extra-work/${extraWorkId}?tab=money`}
            className="btn btn-secondary btn-sm"
            // `.form-section` is a stretch-aligned flex column; unpinned,
            // the button renders full-width like a submit bar.
            style={{ alignSelf: "flex-start" }}
            data-testid="ticket-ew-open-money"
          >
            {t("ew_card_open")}
          </Link>
        </div>
      </div>
      {activeHourlyLines.length > 0 && (
        <ActualHoursPanel
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
                  // must not blank the panel mid-edit.
                });
            }
          }}
        />
      )}
    </>
  );
}
