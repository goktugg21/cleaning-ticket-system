import { CalendarClock } from "lucide-react";
import { useTranslation } from "react-i18next";

/**
 * Sprint W1-B item 14 — the customer-facing explanation of the billing
 * cutoff.
 *
 * WHY THIS EXISTS
 * ---------------
 * `extra_work.billing.is_earned` gained a second arm this sprint: work
 * that is finished and waiting on the customer's approval is billable
 * once the customer's billing cutoff arrives, approval or no approval.
 * That is the right rule — it is what stops August's work landing on
 * September's invoice — but a rule about somebody's money that they were
 * never told about is a rule they will find out about from an invoice
 * they did not expect. So it is stated, in their own words, on the
 * surfaces where they meet the work and where they meet the bill.
 *
 * The same three sentences go out in the approval-request e-mail
 * (`notifications/services.py::_BILLING_CUTOFF_PARAGRAPH_NL`), because
 * plenty of customers act on the mail and never open the app.
 *
 * DELIBERATELY NOT
 * ----------------
 * Not a dismissible toast, and not a settings-page paragraph. A notice
 * the reader can make disappear is a notice they can un-see before the
 * invoice arrives; a notice behind Settings is one they will never find.
 * It is small, permanent and quiet.
 *
 * `variant` picks WHICH of the two questions is being answered:
 *   "before"  — you have work waiting; here is what happens if you do
 *               not answer before your billing date.
 *   "invoice" — you are looking at a bill; here is why something you had
 *               not approved is on it, and what to do about it.
 * Both carry the same rule and the same reversal promise; only the
 * opening sentence differs, because a person reading an invoice has a
 * different question from a person reading a work list.
 */
export function BillingCutoffNotice({
  variant = "before",
}: {
  variant?: "before" | "invoice";
}) {
  const { t } = useTranslation("common");

  return (
    <aside
      className="billing-cutoff-notice"
      data-testid="billing-cutoff-notice"
      data-variant={variant}
    >
      <CalendarClock size={18} aria-hidden="true" />
      <div className="billing-cutoff-notice-body">
        <p className="billing-cutoff-notice-title">
          {t("billing_cutoff_notice.title")}
        </p>
        <p>
          {variant === "invoice"
            ? t("billing_cutoff_notice.lead_invoice")
            : t("billing_cutoff_notice.lead_before")}
        </p>
        <p>{t("billing_cutoff_notice.rule")}</p>
        <p>{t("billing_cutoff_notice.reversal")}</p>
      </div>
    </aside>
  );
}
