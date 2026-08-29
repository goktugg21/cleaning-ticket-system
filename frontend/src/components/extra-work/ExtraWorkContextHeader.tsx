/**
 * W8 §1 / FE-3 — the fact block of the meerwerk detail: four questions,
 * four blocks, always on screen whichever tab is open.
 *
 * What W8 replaced: a single wrapping row of small grey chips —
 * "B Amsterdam  B3 Amsterdam · Under review · Total: — · Deadline:
 * Aug 22 · Proposal · Other · Normal". Nine facts at one weight, in one
 * colour, on one line, is a decoration.
 *
 * What FE-3 (Addendum D §D.4) changes: the STATE block is gone from
 * here. Its badge soup — the request status, the spawned ticket's
 * status, the urgency, the labels — was every state dimension at equal
 * weight (§D.1 root cause 4). The one phase now opens the page in the
 * phase banner (the server's `display_phase`), and the raw values live
 * behind Geavanceerd. What stays here are FACTS, by the question each
 * answers, in the order a person forms them:
 *
 *   WIE / WAAR   the customer, and the building
 *   WAT          category, urgency, department / work type
 *   WANNEER      asked for, owed by (with the §D.11 chip), committed to
 *   GELD         the total, and whether it has been invoiced
 *
 * The title is NOT repeated here; it is the page's h1 above. The ONE
 * primary action is the banner's, not this block's.
 */
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Link } from "react-router-dom";
import { CalendarClock } from "lucide-react";

import type {
  ExtraWorkRequestDetail,
  ExtraWorkSpawnedTicket,
} from "../../api/types";
import { formatDate, formatMoney } from "../../lib/intl";
import { rowAmounts } from "../../lib/billing";

/**
 * W12 §2 — the ticket that kept a date of its own.
 *
 * Planning an extra work MOVES its tickets: writing
 * `provider_planned_date` calls `apply_planned_date_to_tickets`, which
 * sets each spawned ticket's `scheduled_start_at`. It deliberately
 * refuses to overwrite a ticket somebody rescheduled BY HAND, and
 * reports that on `planned_date_ticket_result` for the caller to
 * surface. Nothing surfaced it. A provider set a delivery date, a
 * ticket kept a different one, and the screen said nothing.
 *
 * Derived from the two rows themselves rather than from the plan
 * response, and that is the point: the response is a one-shot event that
 * a page reload loses, while the disagreement is a STATE that persists
 * until somebody resolves it. The ticket owns its date; this compares
 * the two and links to the row that can change it.
 */
function ticketsKeepingOwnDate(
  ew: ExtraWorkRequestDetail,
): ExtraWorkSpawnedTicket[] {
  const planned = ew.provider_planned_date;
  if (!planned) return [];
  return ew.spawned_tickets.filter(
    (ticket) =>
      ticket.schedule_status === "RESCHEDULED" &&
      ticket.scheduled_start_at !== null &&
      // Compare the DAY. The plan is a date, the ticket carries a
      // timestamp at local midnight, and an equal day is not a conflict.
      ticket.scheduled_start_at.slice(0, 10) !== planned.slice(0, 10),
  );
}

function Block({
  label,
  testId,
  action,
  children,
}: {
  label: string;
  testId: string;
  /** FE-3 — a quiet edit affordance on the block's own heading row. */
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="ew-ctx-block" data-testid={testId}>
      {action != null ? (
        <div className="ew-ctx-label-row">
          <div className="ew-ctx-label">{label}</div>
          {action}
        </div>
      ) : (
        <div className="ew-ctx-label">{label}</div>
      )}
      <div className="ew-ctx-body">{children}</div>
    </div>
  );
}

export function ExtraWorkContextHeader({
  ew,
  urgencyLabel,
  categoryLabel,
  departmentLabel,
  workTypeLabel,
  billedToLabel,
  proposedTotal = null,
  whatAction,
  whenAction,
  dueChip,
}: {
  ew: ExtraWorkRequestDetail;
  urgencyLabel: string;
  categoryLabel: string;
  departmentLabel: string | null;
  workTypeLabel: string | null;
  /** "Komt op" — who this is billed to, in words (`lib/billedTo`). */
  billedToLabel: string;
  /** W-FIX1 A3 (audit F3) — the total of the proposal the customer is
   *  looking at (SENT, not yet decided). Shown as "proposed" so MONEY
   *  and the banner read the same fact from the same record. */
  proposedTotal?: string | null;
  /** The classification editor's trigger (provider), in the WAT block. */
  whatAction?: ReactNode;
  /** The dates editor's trigger (provider), in the WANNEER block. */
  whenAction?: ReactNode;
  /** §D.11 G3 — the one chip for the deadline, built by the page. */
  dueChip?: ReactNode;
}) {
  const { t } = useTranslation(["extra_work", "common"]);
  const conflicts = ticketsKeepingOwnDate(ew);
  const plannedWindow = ew.provider_planned_date
    ? ew.provider_planned_end_date &&
      ew.provider_planned_end_date !== ew.provider_planned_date
      ? `${formatDate(ew.provider_planned_date)} – ${formatDate(
          ew.provider_planned_end_date,
        )}`
      : formatDate(ew.provider_planned_date)
    : null;

  return (
    <div className="ew-ctx" data-testid="extra-work-context-header">
      <Block label={t("detail.ctx_who_where")} testId="extra-work-ctx-who">
        <div className="ew-ctx-strong" data-testid="extra-work-header-customer">
          {ew.customer_name}
        </div>
        <div className="ew-ctx-sub" data-testid="extra-work-header-building">
          {ew.building_name}
        </div>
      </Block>

      <Block
        label={t("detail.ctx_what")}
        testId="extra-work-ctx-what"
        action={whatAction}
      >
        <div className="ew-ctx-strong" data-testid="extra-work-category">
          {categoryLabel}
        </div>
        {/* Urgency is a fact about THIS request, not a status. */}
        <div className="ew-ctx-sub" data-testid="extra-work-ctx-urgency">
          {urgencyLabel}
        </div>
        {(departmentLabel || workTypeLabel) && (
          <div className="ew-ctx-sub" data-testid="extra-work-ctx-labels">
            {[departmentLabel, workTypeLabel].filter(Boolean).join(" · ")}
          </div>
        )}
        <div className="ew-ctx-sub" data-testid="extra-work-billed-to">
          {t("detail.field_billed_to")}: {billedToLabel}
        </div>
      </Block>

      <Block
        label={t("detail.ctx_when")}
        testId="extra-work-ctx-when"
        action={whenAction}
      >
        {/* Each date says WHOSE it is (§D.2): the customer's wish, the
            promise we owe, the window we committed to. Never mixed. */}
        <div className="ew-ctx-sub" data-testid="extra-work-preferred-date">
          {t("detail.date_preferred")}:{" "}
          {ew.preferred_date ? formatDate(ew.preferred_date) : t("detail.empty_dash")}
        </div>
        <div
          className="ew-ctx-sub facts-line"
          data-testid="extra-work-deadline"
          style={{ display: "flex" }}
        >
          <span>
            {t("detail.date_deadline")}:{" "}
            {ew.deadline ? formatDate(ew.deadline) : t("detail.empty_dash")}
          </span>
          {dueChip}
        </div>
        <div className="ew-ctx-sub" data-testid="extra-work-planned-window">
          {t("detail.ctx_planned_window")}:{" "}
          {plannedWindow ?? t("detail.empty_dash")}
        </div>
        {/* The conflict, where the date is read. It names the ticket,
            names the date it kept, and links to the row that can change
            it. */}
        {conflicts.length > 0 && (
          <div
            className="ew-ctx-date-conflict"
            data-testid="extra-work-ctx-date-conflict"
          >
            <CalendarClock size={14} strokeWidth={2.4} aria-hidden="true" />
            <span>
              {conflicts.map((ticket, index) => (
                <span key={ticket.id}>
                  {index > 0 && " "}
                  {t("detail.ctx_ticket_kept_own_date", {
                    ticket: ticket.ticket_no ?? `#${ticket.id}`,
                    date: formatDate(
                      (ticket.scheduled_start_at as string).slice(0, 10),
                    ),
                  })}{" "}
                  <Link to={`/tickets/${ticket.id}`}>
                    {t("detail.ctx_ticket_kept_own_date_link")}
                  </Link>
                </span>
              ))}
            </span>
          </div>
        )}
      </Block>

      <Block label={t("detail.ctx_money")} testId="extra-work-ctx-money">
        {/* W9 §1 — an amount is coloured as an amount; a job with no
            price yet is coloured as WAITING, because that is what it is
            waiting for. */}
        <div
          className={
            ew.is_priced === false && proposedTotal === null
              ? "ew-ctx-strong ew-ctx-unpriced"
              : "ew-ctx-strong ew-ctx-money"
          }
          data-testid="extra-work-header-total"
        >
          {proposedTotal !== null
            ? formatMoney(Number(proposedTotal))
            : ew.is_priced === false
              ? t("detail.ctx_not_priced")
              : formatMoney(rowAmounts(ew).total)}
        </div>
        {proposedTotal !== null && (
          <div className="ew-ctx-sub" data-testid="extra-work-ctx-proposed">
            {t("detail.ctx_price_proposed")}
          </div>
        )}
        <div className="ew-ctx-sub" data-testid="extra-work-ctx-invoiced">
          {ew.is_invoiced
            ? t("detail.ctx_invoiced")
            : t("detail.ctx_not_invoiced")}
        </div>
      </Block>
    </div>
  );
}
