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
