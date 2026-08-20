/**
 * W8 §1 — the four blocks of context that never move.
 *
 * What this replaces: a single wrapping row of small grey chips —
 * "B Amsterdam  B3 Amsterdam · Under review · Total: — · Deadline:
 * Aug 22 · Proposal · Other · Normal". Every one of those is a real
 * fact, and the row read as a breadcrumb, so the eye skipped it. Nine
 * facts at one weight, in one colour, on one line, is a decoration.
 *
 * The fix is not more chips or bigger chips. It is that facts which
 * answer DIFFERENT questions stop sharing a line. Four blocks, four
 * questions, always on screen whichever tab is open:
 *
 *   WHO AND WHERE    the customer, and the building
 *   WHAT AND STATE   the status, how urgent, how it is classified
 *   MONEY            the total, and whether it has been invoiced
 *   WHAT NEXT        one sentence and one button (see `nextStep.ts`)
 *
 * The title is NOT repeated here. It is the page's h1 four pixels
 * above, and printing it twice is the clutter this sprint is removing,
 * not a fifth fact.
 *
 * WHAT NEXT is deliberately the last block and the only one with a
 * button. Reading order runs identity -> state -> money -> action,
 * which is the order a person forms the question in.
 */
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ExtraWorkRequestDetail } from "../../api/types";
import { StatusBadge } from "../StatusBadge";
import { SpawnedTicketLinks } from "./SpawnedTicketLinks";
import { formatMoney } from "../../lib/intl";
import { rowAmounts } from "../../lib/billing";

function Block({
  label,
  testId,
  children,
}: {
  label: string;
  testId: string;
  children: ReactNode;
}) {
  return (
    <div className="ew-ctx-block" data-testid={testId}>
      <div className="ew-ctx-label">{label}</div>
      <div className="ew-ctx-body">{children}</div>
    </div>
  );
}

export function ExtraWorkContextHeader({
  ew,
  urgencyLabel,
  departmentLabel,
  workTypeLabel,
  nextStep,
}: {
  ew: ExtraWorkRequestDetail;
  urgencyLabel: string;
  departmentLabel: string | null;
  workTypeLabel: string | null;
  /** The WHAT NEXT block, built by the page (it owns the handlers). */
  nextStep: ReactNode;
}) {
  const { t } = useTranslation(["extra_work", "common"]);

  // The status a person means when they ask "where is this?". Once an
  // operational ticket exists the ticket IS what is happening, which is
  // the rule the list settled on in Sprint 181 and the reason the two
  // screens stopped disagreeing. Unchanged here, only relocated.
  const status =
    ew.spawned_tickets.length > 0
      ? ({ kind: "ticket", value: ew.spawned_tickets[0].status } as const)
      : ({ kind: "extra-work", value: ew.status } as const);

  return (
    <div className="ew-ctx" data-testid="extra-work-context-header">
      <Block
        label={t("detail.ctx_who_where")}
        testId="extra-work-ctx-who"
      >
        <div className="ew-ctx-strong" data-testid="extra-work-header-customer">
          {ew.customer_name}
        </div>
        <div className="ew-ctx-sub" data-testid="extra-work-header-building">
          {ew.building_name}
        </div>
      </Block>

      <Block
        label={t("detail.ctx_what_state")}
        testId="extra-work-ctx-state"
      >
        <div className="ew-ctx-badges">
          <StatusBadge status={status} testId="extra-work-header-status" />
          {/* Urgency is a fact about THIS request, not a status, so it
              renders as plain text beside the badge rather than as a
              second badge competing with it. */}
          <span className="ew-ctx-sub">{urgencyLabel}</span>
        </div>
        {/* The ticket number belongs with the status it is now the
            source of. It used to be a separate cell in the Details
            grid, one tab away from the badge that came from it. */}
        {ew.spawned_tickets.length > 0 && (
          <div className="ew-ctx-sub" data-testid="extra-work-ctx-ticket">
            <SpawnedTicketLinks tickets={ew.spawned_tickets} max={3} />
          </div>
        )}
        {(departmentLabel || workTypeLabel) && (
          <div className="ew-ctx-sub" data-testid="extra-work-ctx-labels">
            {[departmentLabel, workTypeLabel].filter(Boolean).join(" · ")}
          </div>
        )}
      </Block>

      <Block label={t("detail.ctx_money")} testId="extra-work-ctx-money">
        <div className="ew-ctx-strong" data-testid="extra-work-header-total">
          {ew.is_priced === false
            ? t("detail.ctx_not_priced")
            : formatMoney(rowAmounts(ew).total)}
        </div>
        {/* Invoiced or not, in words. An absent invoice date used to be
            the only signal, which is a fact you have to already know how
            to read. */}
        <div className="ew-ctx-sub" data-testid="extra-work-ctx-invoiced">
          {ew.is_invoiced
            ? t("detail.ctx_invoiced")
            : t("detail.ctx_not_invoiced")}
        </div>
      </Block>

      <Block label={t("detail.ctx_what_next")} testId="extra-work-ctx-next">
        {nextStep}
      </Block>
    </div>
  );
}
