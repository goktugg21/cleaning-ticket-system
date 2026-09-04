/**
 * P-4 (Part C) — MONEY THAT CALMS INSTEAD OF STRESSES.
 *
 * Addendum B's rules are unchanged; these are the SENTENCES that state
 * their consequence where a person acts: which month the work bills
 * in and where it will be found. One helper so the billing-month field,
 * its save, and "Save hours to bill" all say the same destination.
 */
import type { TFunction } from "i18next";

import type { ExtraWorkRequestDetail } from "../api/types";
import { localeCode } from "./intl";

/** "December 2026" from "2026-12" / "2026-12-01", in the UI's locale. */
export function monthName(value: string | null | undefined): string {
  if (!value) return "";
  const [y, m] = value.slice(0, 7).split("-").map(Number);
  if (!y || !m) return value;
  return new Date(y, m - 1, 1).toLocaleDateString(localeCode(), {
    month: "long",
    year: "numeric",
  });
}

/** The month this work bills in as words: the overridden month, or
 *  "the month it is completed in". */
export function billingMonthWords(
  detail: Pick<ExtraWorkRequestDetail, "invoice_date">,
  t: TFunction,
): string {
  return detail.invoice_date
    ? monthName(detail.invoice_date)
    : t("extra_work:billing.completion_month_words");
}

/** P-6 V1 — the Invoices page opened on this work's customer and, when
 *  the billing month is fixed, on that month. The "completed-in" month
 *  is not known until completion, so the link then opens on the
 *  customer alone. */
export function invoicesDestination(
  detail: Pick<ExtraWorkRequestDetail, "invoice_date" | "customer">,
): string {
  // P-12 D6 — the landing is the road's FIRST step: To invoice, where
  // unbilled work sits, narrowed to this customer (the due table reads
  // the filter too).
  const period = detail.invoice_date ? detail.invoice_date.slice(0, 7) : "";
  return period
    ? `/invoices?tab=due&customer=${detail.customer}&period=${period}`
    : `/invoices?tab=due&customer=${detail.customer}`;
}

/** P-12 D6 — days until the customer's next billing day. 0 = today. */
export function daysUntilBillingDay(
  day: number | "LAST_OF_MONTH",
  today: Date = new Date(),
): number {
  const base = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const lastOfThisMonth = new Date(
    base.getFullYear(),
    base.getMonth() + 1,
    0,
  ).getDate();
  let target: Date;
  if (day === "LAST_OF_MONTH") {
    target =
      base.getDate() <= lastOfThisMonth
        ? new Date(base.getFullYear(), base.getMonth(), lastOfThisMonth)
        : new Date(base.getFullYear(), base.getMonth() + 2, 0);
  } else {
    target =
      base.getDate() <= day
        ? new Date(base.getFullYear(), base.getMonth(), day)
        : new Date(base.getFullYear(), base.getMonth() + 1, day);
  }
  return Math.round((target.getTime() - base.getTime()) / 86400000);
}

/** P-12 D6 (§D.24 rules 4+6) — what "Save hours to bill" ANSWERS: the
 *  amount, whose next invoice it feeds and on which day (with how far
 *  away that is), and where to see it. One owner for both mounts of
 *  the panel. Falls back to the P-4 sentence when the customer has no
 *  billing day. */
export function hoursSavedMessage(
  detail: Pick<
    ExtraWorkRequestDetail,
    "invoice_date" | "customer" | "customer_name" | "customer_invoice_day"
  >,
  amount: string,
  t: TFunction,
): string {
  const day = detail.customer_invoice_day;
  if (day == null) {
    return t("extra_work:billing.hours_saved_where", {
      amount,
      customer: detail.customer_name,
      month: billingMonthWords(detail, t),
    });
  }
  const dayWords =
    day === "LAST_OF_MONTH"
      ? t("common:facturatie.day_last")
      : t("common:facturatie.day_of_month", { day });
  const inDays = daysUntilBillingDay(day);
  return t("extra_work:billing.hours_saved_invoice_day", {
    amount,
    customer: detail.customer_name,
    day: dayWords,
    when:
      inDays === 0
        ? t("extra_work:billing.hours_saved_today")
        : t("extra_work:billing.hours_saved_in_days", { count: inDays }),
  });
}
