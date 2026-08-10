// Sprint 160 §3 — the pure helpers behind the contracts table.
//
// Deliberately separate from the page component and free of React: the
// three views, the two toggles and the bounded project columns are all
// derivations of one fetched page, and a derivation with no rendering
// in it is one that can be reasoned about (and, when the Frontend
// Testing Sprint lands a runner, tested) on its own.

import type { Contract } from "../../../api/contracts.types";

/** List / Customer Summary / Building Summary — three GROUPINGS of the
 *  same data, never three fetches. */
export type GroupBy = "none" | "customer" | "building";
/** The Prices / Hours toggle. */
export type Measure = "prices" | "hours";
/** The Monthly / Yearly toggle. Applies to money only — hours are a
 *  per-billing-period budget and are not multiplied by twelve here. */
export type Timeframe = "monthly" | "yearly";

/**
 * How many per-project columns the table will show before folding the
 * rest into "Other".
 *
 * The Sprint 152.2 rule: a table that grows a column per project looks
 * fine on the four projects in a seed database and is unusable on the
 * forty a real tenant has. Six is what fits beside the fixed columns at
 * a normal desktop width; the folded count is always reported so the
 * operator knows the "Other" column is not empty by accident.
 */
export const MAX_PROJECT_COLUMNS = 6;

function toNumber(value: string | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 * The value one contract contributes, for the current toggles.
 *
 * Money comes from the server's already-normalised `monthly_amount` /
 * `yearly_amount` rather than being recomputed here from the line
 * amounts and the billing period — that arithmetic (a quarterly
 * contract's line amount is a QUARTER's money) belongs in one place,
 * and the backend is that place. Hours are the revision's per-period
 * budget and are NOT scaled by the timeframe: an hours budget answers
 * "how much work per billing period", and multiplying it by twelve
 * would invent a yearly figure the contract never states.
 */
export function perPeriodValue(
  contract: Contract,
  measure: Measure,
  timeframe: Timeframe,
): number {
  if (measure === "hours") return toNumber(contract.total_hours);
  return toNumber(
    timeframe === "monthly" ? contract.monthly_amount : contract.yearly_amount,
  );
}

function lineValue(
  contract: Contract,
  line: { amount: string; hours: string },
  measure: Measure,
  timeframe: Timeframe,
): number {
  if (measure === "hours") return toNumber(line.hours);
  // A line's `amount` is one BILLING PERIOD's money. Scale it the same
  // way the backend scales the contract total, so a project column and
  // the row total are the same number expressed twice, not two
  // different rules that agree on monthly contracts only.
  const perPeriod = toNumber(line.amount);
  const monthsPerPeriod =
    contract.billing_period === "YEARLY"
      ? 12
      : contract.billing_period === "QUARTERLY"
        ? 3
        : 1;
  const monthly = perPeriod / monthsPerPeriod;
  return timeframe === "monthly" ? monthly : monthly * 12;
}

export interface ProjectColumn {
  key: string;
  label: string;
  valueFor: (contract: Contract) => number;
}

export interface ProjectColumns {
  columns: ProjectColumn[];
  /** How many distinct project names were folded into "Other". Shown
   *  to the operator — a silent truncation reads as "that is all of
   *  them". */
  folded: number;
  otherFor: (contract: Contract) => number;
}

/**
 * The per-project columns for the CURRENT result set.
 *
 * Only the project names that actually occur on the fetched page get a
 * column, so the table is per tenant without anything being
 * configured. They are ranked by total value across the page (the
 * biggest projects earn the columns), the top `MAX_PROJECT_COLUMNS`
 * are shown, and everything else folds into one "Other" column whose
 * count is reported.
 */
export function buildProjectColumns(
  contracts: Contract[],
  measure: Measure,
  timeframe: Timeframe,
): ProjectColumns {
  const totals = new Map<string, number>();
  for (const contract of contracts) {
    for (const line of contract.projects) {
      const name = line.name.trim();
      if (!name) continue;
      totals.set(
        name,
        (totals.get(name) ?? 0) + lineValue(contract, line, measure, timeframe),
      );
    }
  }

  const ranked = [...totals.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([name]) => name);
  const shown = ranked.slice(0, MAX_PROJECT_COLUMNS);
  const shownSet = new Set(shown);

  const valueOf = (contract: Contract, predicate: (name: string) => boolean) =>
    contract.projects
      .filter((line) => predicate(line.name.trim()))
      .reduce(
        (sum, line) => sum + lineValue(contract, line, measure, timeframe),
        0,
      );

  return {
    columns: shown.map((name) => ({
      key: name,
      label: name,
      valueFor: (contract) => valueOf(contract, (candidate) => candidate === name),
    })),
    folded: ranked.length - shown.length,
    otherFor: (contract) => valueOf(contract, (name) => !shownSet.has(name)),
  };
}

export interface ContractGroupRow {
  key: string;
  label: string;
  rows: Contract[];
  total: number;
}

/**
 * The three views, from one fetched page.
 *
 * `none` is a single unlabelled group so the table body renders through
 * ONE code path in every view — the alternative, a conditional that
 * renders grouped rows or flat rows, is two layouts to keep in step and
 * is how the summary views end up disagreeing with the list.
 *
 * A contract covering three buildings appears under EACH of them in the
 * building view. That is a deliberate answer rather than an oversight:
 * the question the view answers is "what is contracted at this
 * location", and hiding a contract from two of its own locations to
 * keep a page total tidy would answer it wrongly. The per-group totals
 * therefore sum to more than the tenant total in that view, which is
 * correct for a per-location reading.
 */
export function groupContracts(
  contracts: Contract[],
  groupBy: GroupBy,
): ContractGroupRow[] {
  if (groupBy === "none") {
    return [
      {
        key: "all",
        label: "",
        rows: contracts,
        total: 0,
      },
    ];
  }

  const groups = new Map<string, ContractGroupRow>();
  const push = (key: string, label: string, contract: Contract) => {
    const existing = groups.get(key);
    if (existing) {
      existing.rows.push(contract);
      return;
    }
    groups.set(key, { key, label, rows: [contract], total: 0 });
  };

  for (const contract of contracts) {
    if (groupBy === "customer") {
      push(
        `c${contract.customer}`,
        contract.customer_name ?? "—",
        contract,
      );
      continue;
    }
    if (contract.buildings.length === 0) {
      push("b-none", "—", contract);
      continue;
    }
    for (const building of contract.buildings) {
      push(`b${building.id}`, building.name, contract);
    }
  }

  return [...groups.values()].sort((a, b) => a.label.localeCompare(b.label));
}

/**
 * Fill in each group's total for the current toggles. Kept out of
 * `groupContracts` so the grouping does not have to know what is being
 * measured.
 */
export function withGroupTotals(
  groups: ContractGroupRow[],
  measure: Measure,
  timeframe: Timeframe,
): ContractGroupRow[] {
  return groups.map((group) => ({
    ...group,
    total: group.rows.reduce(
      (sum, contract) => sum + perPeriodValue(contract, measure, timeframe),
      0,
    ),
  }));
}

export function formatMoney(
  value: string | number,
  locale: string,
): string {
  const amount = typeof value === "number" ? value : toNumber(value);
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency: "EUR",
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return amount.toFixed(2);
  }
}

export function formatNumber(
  value: string | number,
  locale: string,
): string {
  const amount = typeof value === "number" ? value : toNumber(value);
  try {
    return new Intl.NumberFormat(locale, {
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return amount.toFixed(2);
  }
}

export function formatDate(value: string | null, locale: string): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleDateString(locale, {
      year: "numeric",
      month: "short",
      day: "2-digit",
    });
  } catch {
    return value;
  }
}

/** The Period column of the Invoice Preview — "februari 2026". */
export function formatPeriod(value: string, locale: string): string {
  try {
    return new Date(value).toLocaleDateString(locale, {
      year: "numeric",
      month: "long",
    });
  } catch {
    return value;
  }
}
