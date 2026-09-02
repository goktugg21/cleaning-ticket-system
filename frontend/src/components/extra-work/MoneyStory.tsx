/**
 * P-13 B (O2/W4) — the Money tab tells ONE story, top to bottom:
 *
 *   1. Agreed with the customer — every quote line, qty × unit price
 *      = amount (ex VAT), the total ex and incl VAT, and who agreed
 *      to it when. Read-only.
 *   2. Worked — the hourly lines with the timesheet prefill and "Save
 *      hours to bill" (ActualHoursPanel), the fixed lines read-only
 *      with "fixed price". Every line the customer approved appears
 *      here, none missing (the owner's "ff €34" was in the Agreement
 *      and absent from the card — nothing connected them).
 *   3. Goes on the invoice — the sum of block 2 (final-with-quoted-
 *      fallback, the ONE rule), the customer's billing fact, and
 *      where the money IS ("Not yet on an invoice" / "On draft #17" /
 *      "Sent on invoice 2026-0003"). When block 3 differs from block
 *      1, an amber line says by how much — always.
 *
 * ONE component, mounted on the extra-work request page AND the
 * spawned ticket's Money tab, so the two can never tell the story
 * differently. The ticket passes its billing-month editor through the
 * `billingEditor` slot; testids from the old ticket card
 * (ticket-ew-subtotal/-total/-invoiced/…) are kept so the walks and
 * probes keep finding the same facts.
 */
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import type {
  ExtraWorkRequestDetail,
  Proposal,
  ProposalDetail,
} from "../../api/types";
import { isPriced, rowAmounts } from "../../lib/billing";
import {
  billingMonthWords,
  hoursSavedMessage,
  invoicesDestination,
} from "../../lib/billingSentence";
import { formatDate, formatMoney, formatNumber } from "../../lib/intl";

import { ActualHoursPanel } from "./ActualHoursPanel";
import {
  actualHoursPanelKey,
  deriveActiveHourlyLines,
  finiteOrNull,
} from "./activeHourlyLines";
import { agreedLines } from "./agreedLines";
import { HOURS_PANEL_MODE } from "./hoursPanelMode";
import { overQuoteFacts } from "./overQuote";

/** P-11 B3's number-for-a-sentence: "4", "2.5". */
function fmtHours(value: number): string {
  return String(Number(value.toFixed(2)));
}

export function MoneyStory({
  ew,
  approvedProposal,
  approvedProposalDetail,
  locked,
  onUpdated,
  onAddLine,
  billingEditor,
}: {
  ew: ExtraWorkRequestDetail;
  approvedProposal: Proposal | null;
  approvedProposalDetail: ProposalDetail | null;
  /** True once a spawned ticket is APPROVED/CLOSED (final amount frozen). */
  locked: boolean;
  onUpdated: (detail: ExtraWorkRequestDetail) => void;
  onAddLine?: () => void;
  /** The mount's own billing-month control, rendered inside block 3. */
  billingEditor?: ReactNode;
}) {
  const { t } = useTranslation(["extra_work", "ticket_detail", "common"]);
  const mode = HOURS_PANEL_MODE[ew.display_phase];
  const hourlyLines = deriveActiveHourlyLines(
    ew,
    approvedProposal,
    approvedProposalDetail,
  );
  const { rows: agreedRows, totals: agreedTotals } = agreedLines(
    ew,
    approvedProposal,
    approvedProposalDetail,
  );
  const fixedLines = agreedRows
    .filter((row) => row.unitType !== "HOURS")
    .map((row) => ({ id: row.id, label: row.label, amount: row.amount }));

  // The same three-way count TicketExtraWorkCards derived: null while
  // the approved proposal's detail is still loading, so nothing can
  // flash a wrong state.
  const activePricedCount = approvedProposal
    ? approvedProposalDetail
      ? approvedProposalDetail.lines.filter((l) => l.is_approved_for_spawn)
          .length
      : null
    : ew.routing_decision === "INSTANT"
      ? ew.line_items.length
      : ew.pricing_line_items.length;
  const noPriceAgreed = activePricedCount === 0;
  const awaitingHours =
    hourlyLines.length > 0 && ew.final_total_amount === null;
  const amounts = rowAmounts(ew);
  const priced = isPriced(ew);
  // P-5 (§D.2 dash ban) — an amount that cannot be stated yet is said
  // in a word: what it is waiting for. The SAME words the old ticket
  // card used (ticket_detail:ew_card_*) — one name per concept.
  const money = (value: number): string =>
    priced && !awaitingHours && !noPriceAgreed
      ? formatMoney(value)
      : awaitingHours
        ? t("ticket_detail:ew_card_awaiting_hours_short")
        : noPriceAgreed
          ? t("ticket_detail:ew_card_no_price")
          : t("ticket_detail:ew_card_not_priced_yet");

  // The amber difference — block 3 against block 1, from the SAVED
  // hours (before any save, worked == agreed and the line is silent).
  const savedFacts = overQuoteFacts(
    hourlyLines.map((line) => ({
      rate: line.rate,
      quantity: line.quantity,
      worked: finiteOrNull(line.actual_hours),
    })),
  );
  const diff =
    savedFacts !== null && Math.abs(savedFacts.deltaAmount) >= 0.005
      ? savedFacts
      : null;

  // Block 1's provenance sentence: who agreed, when — or that no
  // approval was needed.
  const approvedOn =
    approvedProposal?.customer_decided_at ?? ew.customer_decided_at ?? null;
  const provenance =
    ew.routing_decision === "INSTANT" && !approvedProposal
      ? t("money.started_no_approval", {
          who: ew.created_by_name || ew.created_by_email,
          date: formatDate(ew.requested_at),
        })
      : approvedOn
        ? t("money.approved_by", {
            who: ew.customer_name,
            date: formatDate(approvedOn),
          })
        : null;

  const ref = ew.invoice_ref;

  return (
    <div
      style={{ display: "flex", flexDirection: "column", gap: 16 }}
      data-testid="money-story"
    >
      {/* ---- 1 · Agreed with the customer ---- */}
      {agreedRows.length > 0 && (
        <section data-testid="money-agreed">
          <div className="form-section-title">{t("money.agreed_title")}</div>
          <table className="ew-agreement-table">
            <colgroup>
              <col />
              <col className="ew-agreement-col-qty" />
              <col className="ew-agreement-col-amount" />
            </colgroup>
            <thead>
              <tr>
                <th className="detail-kv-label">
                  {t("detail.agreement_col_service")}
                </th>
                <th className="detail-kv-label ew-agreement-num">
                  {t("money.col_qty_price")}
                </th>
                <th className="detail-kv-label ew-agreement-num">
                  {t("detail.agreement_col_amount")}
                </th>
              </tr>
            </thead>
            <tbody>
              {agreedRows.map((row) => (
                <tr key={row.id} data-testid="money-agreed-row">
                  <td className="ew-agreement-name">{row.label}</td>
                  <td className="ew-agreement-num muted small">
                    {row.quantity !== null && row.quantity !== ""
                      ? formatNumber(row.quantity)
                      : "—"}
                    {" × "}
                    {row.unitPrice !== null
                      ? formatMoney(row.unitPrice)
                      : "—"}
                  </td>
                  <td className="ew-agreement-num ew-agreement-amount">
                    {row.amount !== null ? formatMoney(row.amount) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {agreedTotals && (
            <p
              className="muted small ew-agreement-num"
              style={{ margin: "4px 0 0", textAlign: "right" }}
              data-testid="money-agreed-total"
            >
              {t("money.total_pair", {
                ex: formatMoney(agreedTotals.ex),
                incl: formatMoney(agreedTotals.incl),
              })}
            </p>
          )}
          {provenance && (
            <p
              className="muted small"
              style={{ margin: "4px 0 0" }}
              data-testid="money-agreed-provenance"
            >
              {provenance}
            </p>
          )}
        </section>
      )}

      {/* ---- 2 · Worked ---- */}
      {mode !== "none" && agreedRows.length > 0 && (
        <section data-testid="money-worked">
          <div className="form-section-title">{t("money.worked_title")}</div>
          {mode === "before" ? (
            <>
              {Number(ew.budget_hours ?? 0) > 0 && (
                <p
                  style={{ margin: "0 0 4px" }}
                  data-testid="extra-work-hours-planned"
                >
                  {t("detail.hours_planned_line", {
                    hours: Number(ew.budget_hours ?? 0),
                  })}
                </p>
              )}
              <p className="muted small" style={{ margin: 0 }}>
                {t("detail.hours_before_start")}
              </p>
              {fixedLines.length > 0 && (
                <div
                  className="detail-kv-list"
                  data-testid="extra-work-fixed-lines"
                >
                  {fixedLines.map((line) => (
                    <div key={line.id} className="detail-kv-row">
                      <span className="detail-kv-label">{line.label}</span>
                      <span className="detail-kv-val">
                        <span className="muted small" style={{ marginRight: 6 }}>
                          {t("detail.fixed_price_tag")}
                        </span>
                        {line.amount !== null
                          ? formatMoney(line.amount)
                          : "—"}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : hourlyLines.length > 0 ? (
            <ActualHoursPanel
              variant="embedded"
              readOnly={mode === "read_only"}
              key={actualHoursPanelKey(
                approvedProposal,
                hourlyLines,
                ew.updated_at,
              )}
              ewId={ew.id}
              hourlyLines={hourlyLines}
              fixedLines={fixedLines}
              agreedExTotal={agreedTotals?.ex ?? null}
              finalTotalAmount={ew.final_total_amount}
              locked={locked}
              previewCoversTotal={
                activePricedCount !== null &&
                hourlyLines.length + fixedLines.length === activePricedCount &&
                fixedLines.length === 0
              }
              finalSubtotalAmount={ew.final_subtotal_amount}
              successMessage={(detail) =>
                hoursSavedMessage(
                  detail,
                  formatMoney(rowAmounts(detail).total),
                  t,
                )
              }
              successPath={(detail) => invoicesDestination(detail)}
              onUpdated={onUpdated}
              onAddLine={onAddLine}
            />
          ) : (
            /* An all-fixed job: nothing to enter, everything listed. */
            <div className="detail-kv-list" data-testid="extra-work-fixed-lines">
              {fixedLines.map((line) => (
                <div key={line.id} className="detail-kv-row">
                  <span className="detail-kv-label">{line.label}</span>
                  <span className="detail-kv-val">
                    <span className="muted small" style={{ marginRight: 6 }}>
                      {t("detail.fixed_price_tag")}
                    </span>
                    {line.amount !== null ? formatMoney(line.amount) : "—"}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* ---- 3 · Goes on the invoice ---- */}
      <section data-testid="money-invoice">
        <div className="form-section-title">{t("money.invoice_title")}</div>
        <div className="detail-kv-list">
          <div className="detail-kv-row">
            <span className="detail-kv-label">
              {t("ticket_detail:ew_card_subtotal")}
            </span>
            <span className="detail-kv-val" data-testid="ticket-ew-subtotal">
              {money(amounts.subtotal)}
            </span>
          </div>
          <div className="detail-kv-row">
            <span className="detail-kv-label">
              {t("ticket_detail:ew_card_vat")}
            </span>
            <span className="detail-kv-val">{money(amounts.vat)}</span>
          </div>
          <div className="detail-kv-row">
            <span className="detail-kv-label">
              {t("ticket_detail:ew_card_total")}
            </span>
            <span className="detail-kv-val" data-testid="ticket-ew-total">
              {!noPriceAgreed && awaitingHours ? (
                <strong className="muted" data-testid="ticket-ew-awaiting-hours">
                  {t("ticket_detail:ew_card_awaiting_hours")}
                </strong>
              ) : (
                <strong>{money(amounts.total)}</strong>
              )}
              {noPriceAgreed && (
                <span
                  className="muted small"
                  style={{ marginLeft: 8 }}
                  data-testid="ticket-ew-no-price"
                >
                  {t("ticket_detail:ew_card_no_price")}
                </span>
              )}
            </span>
          </div>
        </div>
        {/* The amber difference — always, when the bill left the quote. */}
        {diff && (
          <div
            className="alert-warning"
            style={{ marginTop: 8 }}
            data-testid="money-over-quote"
          >
            {t(
              diff.deltaAmount > 0
                ? "money.over_quote_more"
                : "money.over_quote_less",
              {
                worked: fmtHours(diff.workedHours),
                agreed: fmtHours(diff.agreedHours),
                diff: formatMoney(Math.abs(diff.deltaAmount)),
              },
            )}
          </div>
        )}
        {/* The customer's billing fact — the month in words, and their
            own invoice day when one is set. */}
        <p
          className="muted small ticket-ew-billing-sentence"
          data-testid="ticket-ew-billing-sentence"
        >
          {t(
            ew.invoice_date
              ? "billing.consequence_month"
              : "billing.consequence_completion",
            { customer: ew.customer_name, month: billingMonthWords(ew, t) },
          )}
          {ew.customer_invoice_day != null && (
            <span data-testid="ticket-ew-invoice-day">
              {" "}
              {t("billing.customer_invoice_day", {
                customer: ew.customer_name,
                day:
                  ew.customer_invoice_day === "LAST_OF_MONTH"
                    ? t("common:facturatie.day_last")
                    : t("common:facturatie.day_of_month", {
                        day: ew.customer_invoice_day,
                      }),
              })}
            </span>
          )}
        </p>
        {billingEditor}
        {/* Where the money IS. `invoice_ref` is provider-only; a
            payload without it falls back to the old flag words. */}
        <p
          className="muted small"
          style={{ margin: "6px 0 0" }}
          data-testid="ticket-ew-invoiced"
        >
          {ref === undefined ? (
            ew.is_invoiced
              ? t("detail.billing_invoiced_on", {
                  date: ew.invoiced_at ? formatDate(ew.invoiced_at) : "—",
                })
              : t("detail.billing_not_invoiced")
          ) : ref === null ? (
            t("money.not_on_invoice")
          ) : ref.status === "DRAFT" ? (
            <>
              {t("money.on_draft", { id: ref.id })}{" "}
              <Link to={`/invoices/${ref.id}`}>{t("money.open_draft")}</Link>
            </>
          ) : ref.status === "ISSUED" ? (
            <>
              {t("money.on_issued")}{" "}
              <Link to={`/invoices/${ref.id}`}>{t("money.open_invoice")}</Link>
            </>
          ) : (
            <>
              {t("money.sent_on", { number: ref.number ?? "" })}{" "}
              <Link to={`/invoices/${ref.id}`}>{t("money.open_invoice")}</Link>
            </>
          )}
        </p>
      </section>
    </div>
  );
}
