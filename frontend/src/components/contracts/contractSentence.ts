import type { Contract } from "../../api/contracts.types";
import { formatMoney } from "../../pages/admin/contracts/contractTables";

/**
 * P-3 §C.1 / P-13 F (E1) — the SENTENCE a contract reads as, wherever
 * it is listed and on its own detail header:
 * "B Amsterdam betaalt € 850 per maand voor 3 regels bij B1 + B2, van
 * jan 2026 tot dec 2026, vooraf gefactureerd op dag 1." Every fact is
 * on the row the server already sends. A contract with no lines names
 * the one missing thing instead; a DRAFT ends with the clause that
 * nothing is invoiced until it is activated. Its own module (not
 * `ContractTerms.tsx`) because a file that exports a component AND a
 * function loses fast refresh — the same split
 * `workplan/entryHelpers.ts` makes.
 */

/** The narrow `t` the list page's row component already passes around. */
export type Translate = (key: string, options?: Record<string, unknown>) => string;

export const MONTHS_PER_PERIOD = { MONTHLY: 1, QUARTERLY: 3, YEARLY: 12 } as const;

export function plainDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const d = new Date(`${value}T00:00:00`);
  return Number.isNaN(d.getTime()) ? null : d;
}
/** "jan 2026" */
export function monthYear(value: string | null | undefined, locale: string): string {
  const d = plainDate(value);
  if (!d) return "";
  return d.toLocaleDateString(locale, { month: "short", year: "numeric" });
}

/** "€ 850 per maand" — the amount of one billing period, in the
 *  contract's own rhythm: the revision's per-period amount where one is
 *  in force, else the normalised monthly figure. A QUARTERLY or YEARLY
 *  contract says its own period truthfully. */
export function amountPerPeriod(contract: Contract, t: Translate, locale: string): string {
  const period = contract.billing_period;
  const amount =
    contract.active_revision?.amount ??
    (period === "MONTHLY"
      ? contract.monthly_amount
      : period === "YEARLY"
        ? contract.yearly_amount
        : String(Number(contract.monthly_amount) * 3));
  return t(`sentence.amount_${period}`, { amount: formatMoney(amount, locale) });
}

/** "B1 + B2", at most three named, then "+ N more". Exported so the
 *  test can pin the fold without going through the whole sentence. */
export function locationsText(contract: Contract, t: Translate): string {
  const names = contract.buildings.map((b) => b.name);
  if (names.length === 0) return t("sentence.no_locations");
  if (names.length <= 3) return names.join(" + ");
  return `${names.slice(0, 2).join(" + ")} + ${t("sentence.more_locations", { count: names.length - 2 })}`;
}

/** The sentence a contract reads as, wherever it is listed. */
export function contractSentence(contract: Contract, t: Translate, locale: string): string {
  // P-13 F (E1) — ZERO LINES WINS OVER EVERYTHING: with no lines there
  // is no amount and no billing to describe, so the sentence names the
  // one missing thing instead of dressing zeros up as facts.
  if (contract.line_count === 0) {
    return t("sentence.no_lines", { customer: contract.customer_name ?? "" });
  }
  const isDraft = contract.status === "DRAFT";
  // P-4 honesty, kept: a DRAFT whose lines carry no money never claims
  // the customer "pays € 0.00" — it states the lines and locations and
  // lets the trailing clause say why nothing moves.
  const draftAmount = contract.active_revision?.amount ?? contract.monthly_amount;
  const saysMoney = !isDraft || Number(draftAmount) > 0;
  const who = {
    customer: contract.customer_name ?? "",
    lines: t("sentence.line_count", { count: contract.line_count }),
    locations: locationsText(contract, t),
  };
  const facts = [
    saysMoney
      ? t("sentence.pays", { ...who, amount: amountPerPeriod(contract, t, locale) })
      : t("sentence.has_lines", who),
    // An open-ended contract must not claim an end: "to {end}" only
    // when the server serves one.
    contract.end_date
      ? t("sentence.from_to", {
          start: monthYear(contract.start_date, locale),
          end: monthYear(contract.end_date, locale),
        })
      : t("sentence.from", { start: monthYear(contract.start_date, locale) }),
    t(`sentence.invoiced_${contract.billing_type}`, { day: contract.billing_day }),
  ].join(", ");
  return isDraft ? `${facts} — ${t("sentence.draft_clause")}.` : `${facts}.`;
}
