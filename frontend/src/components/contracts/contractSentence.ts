import type { Contract } from "../../api/contracts.types";
import { formatMoney } from "../../pages/admin/contracts/contractTables";

/**
 * P-3 §C.1 — the SENTENCE a contract reads as, wherever it is listed:
 * "B Amsterdam — € 850 per maand voor B1 + B2 — sinds jan 2026 —
 * volgende periode: sep". Every fact is on the row the server already
 * sends. Its own module (not `ContractTerms.tsx`) because a file that
 * exports a component AND a function loses fast refresh — the same
 * split `workplan/entryHelpers.ts` makes.
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

/** The label of the calendar period AFTER the one containing today, in
 *  the contract's rhythm: "sep" / "Q4 2026" / "2027". Calendar-aligned,
 *  as Addendum C §C.5 states the periods are. Null when the contract is
 *  not active or that period starts after its end date. */
export function nextPeriodLabel(contract: Contract, locale: string): string | null {
  if (contract.status !== "ACTIVE") return null;
  const today = new Date();
  const months = MONTHS_PER_PERIOD[contract.billing_period];
  const startMonth = Math.floor(today.getMonth() / months) * months + months;
  const start = new Date(today.getFullYear(), startMonth, 1);
  const end = plainDate(contract.end_date);
  if (end && start > end) return null;
  if (contract.billing_period === "MONTHLY") {
    return start.toLocaleDateString(locale, { month: "short" });
  }
  if (contract.billing_period === "QUARTERLY") {
    return `Q${Math.floor(start.getMonth() / 3) + 1} ${start.getFullYear()}`;
  }
  return String(start.getFullYear());
}

/** "€ 850 per maand" — the amount of one billing period, in the
 *  contract's own rhythm: the revision's per-period amount where one is
 *  in force, else the normalised monthly figure. */
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

function locationsText(contract: Contract, t: Translate): string {
  const names = contract.buildings.map((b) => b.name);
  if (names.length === 0) return t("sentence.no_locations");
  if (names.length <= 3) return names.join(" + ");
  return `${names.slice(0, 2).join(" + ")} + ${t("sentence.more_locations", { count: names.length - 2 })}`;
}

/** The sentence a contract reads as, wherever it is listed. */
export function contractSentence(contract: Contract, t: Translate, locale: string): string {
  // P-4 (Part F) — a DRAFT reads as one (P-3's "still editable" honesty):
  // never "€ 0.00 per month since Aug until Aug" for a contract that is
  // not in force. Rules frozen; words only.
  if (contract.status === "DRAFT") {
    const amount = contract.active_revision?.amount ?? contract.monthly_amount;
    const draftParts = [
      contract.customer_name ?? "",
      t("sentence.draft_editable"),
      Number(amount) > 0
        ? `${amountPerPeriod(contract, t, locale)} ${t("sentence.for", { locations: locationsText(contract, t) })}`
        : t("sentence.for", { locations: locationsText(contract, t) }),
      contract.start_date
        ? t("sentence.planned_from", { since: monthYear(contract.start_date, locale) })
        : "",
    ];
    return draftParts.filter(Boolean).join(" — ");
  }
  const parts = [
    contract.customer_name ?? "",
    `${amountPerPeriod(contract, t, locale)} ${t("sentence.for", { locations: locationsText(contract, t) })}`,
    contract.end_date
      ? t("sentence.since_until", {
          since: monthYear(contract.start_date, locale),
          until: monthYear(contract.end_date, locale),
        })
      : t("sentence.since", { since: monthYear(contract.start_date, locale) }),
  ];
  const next = nextPeriodLabel(contract, locale);
  if (next) parts.push(t("sentence.next_period", { period: next }));
  return parts.filter(Boolean).join(" — ");
}

