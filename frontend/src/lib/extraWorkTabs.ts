/**
 * P-9 B — THE ONE TAB TABLE of the Extra work list.
 *
 * The list is four tabs, each holding a set of `display_phase` values
 * (FE-2's one server-computed phase, Addendum D §D.4). This file is the
 * only place that says which phase sits on which tab, which sub-chips a
 * tab offers, which chip a tab OPENS on, and where a `?status=` deep
 * link lands. The page iterates these exported constants and never
 * keeps a second copy — CLAUDE.md's exhaustiveness rule: `TAB_OF_PHASE`
 * is a `Record` over the FULL phase union, so a phase the union gains
 * and this table does not place fails to compile, instead of landing in
 * no tab and going uncounted.
 *
 * P-10 B1 — THE CHIP WORDS ARE THE TICKET'S OWN WORDS. The owner: "Don't
 * tickets have their own statuses? Why aren't you using them?" The
 * Approved tab's chips (and the Finished tab's DONE chip) point at the
 * `common:ticket_status.*` keys the ticket itself shows; the
 * `common:phase.ew.*` values every badge and banner reads are set to
 * the same words, so no surface shows a parallel word. The one state
 * that had no phase — the crew reported done, the manager has not
 * checked — is `WAITING_MANAGER_CHECK` (provider viewer only).
 *
 * P-10 B2 — EACH TAB OPENS ON THE CHIP WITH WORK TO DO (`DEFAULT_CHIP`);
 * "All" is always one click away. The page carries the chosen chip in
 * the address (`?chip=<key>`); a missing or unknown value means the
 * tab's default.
 *
 * CANCELLED is not a tab. It is a view reached from the foot of Finished
 * ("Cancelled requests (32)"), and the P-8 guard still holds over it:
 * server count = the four tab counts + cancelled.
 *
 * Pure data and pure functions only. No React, no i18n — labels are
 * KEYS (the `extra_work` namespace unless prefixed), resolved by the
 * page.
 */
import type {
  ExtraWorkDisplayPhase,
  ExtraWorkRequestList,
  ExtraWorkStatus,
} from "../api/types";

export type ExtraWorkTab = "to-price" | "with-customer" | "approved" | "finished";

/** The view that is not a tab. */
export const CANCELLED_VIEW = "cancelled";
export type ExtraWorkBucket = ExtraWorkTab | typeof CANCELLED_VIEW;

/** Render order of the tab strip. Derived type-first: a tab missing
 *  here fails `TAB_LABEL_KEY` below, not the other way round. */
export const EXTRA_WORK_TABS: ReadonlyArray<ExtraWorkTab> = [
  "to-price",
  "with-customer",
  "approved",
  "finished",
];

/**
 * Every `ExtraWorkDisplayPhase`, exhaustively, to exactly one bucket.
 * The customer-voiced twin (`WAITING_YOUR_APPROVAL`) sits with the
 * provider's reading of the same state: a provider list never receives
 * it, but the union has it and it must not be uncounted.
 */
export const TAB_OF_PHASE: Readonly<Record<ExtraWorkDisplayPhase, ExtraWorkBucket>> = {
  WAITING_PRICE: "to-price",
  WAITING_YOUR_APPROVAL: "with-customer",
  WAITING_CUSTOMER_APPROVAL: "with-customer",
  REJECTED: "with-customer",
  WAITING_PLANNING: "approved",
  SCHEDULED: "approved",
  IN_EXECUTION: "approved",
  WAITING_MANAGER_CHECK: "approved",
  WAITING_COMPLETION_APPROVAL: "approved",
  DONE: "finished",
  INVOICED: "finished",
  CANCELLED: CANCELLED_VIEW,
};

export const TAB_LABEL_KEY: Readonly<Record<ExtraWorkTab, string>> = {
  "to-price": "tabs.to_price",
  "with-customer": "tabs.with_customer",
  approved: "tabs.approved",
  finished: "tabs.finished",
};

/** One plain sentence per tab: what the tab is for, what happens next. */
export const TAB_PURPOSE_KEY: Readonly<Record<ExtraWorkTab, string>> = {
  "to-price": "tabs.purpose_to_price",
  "with-customer": "tabs.purpose_with_customer",
  approved: "tabs.purpose_approved",
  finished: "tabs.purpose_finished",
};

/**
 * A second-level pill under the tab strip. `phases` narrows by phase;
 * `startsWhenPriced` splits To price by what happens AFTER pricing
 * (the request's intent — `AUTO_START_AFTER_PRICING` never returns to
 * the customer, exactly the branch `display_phase.py` takes). A chip
 * with neither is "All".
 */
export interface ExtraWorkSubChip {
  key: string;
  labelKey: string;
  phases?: ReadonlyArray<ExtraWorkDisplayPhase>;
  startsWhenPriced?: boolean;
}

export const ALL_CHIP: ExtraWorkSubChip = { key: "all", labelKey: "tabs.chip_all" };

export const SUB_CHIPS: Readonly<Record<ExtraWorkTab, ReadonlyArray<ExtraWorkSubChip>>> = {
  "to-price": [
    ALL_CHIP,
    { key: "to_customer", labelKey: "tabs.chip_to_customer", startsWhenPriced: false },
    { key: "starts_when_priced", labelKey: "tabs.chip_starts_when_priced", startsWhenPriced: true },
  ],
  "with-customer": [
    ALL_CHIP,
    {
      key: "waiting",
      labelKey: "tabs.chip_waiting",
      phases: ["WAITING_CUSTOMER_APPROVAL", "WAITING_YOUR_APPROVAL"],
    },
    { key: "declined", labelKey: "tabs.chip_declined", phases: ["REJECTED"] },
  ],
  // P-10 B1 — the ticket's own words, in the order the work moves.
  // "Not planned yet" is the schedule's zone word (My schedule's
  // P-11 F — ONE key: `common:phase.ew.WAITING_PLANNING` is the only
  // home of the words; the strip title, the list cell and this chip
  // all read it.
  approved: [
    ALL_CHIP,
    { key: "not_planned", labelKey: "common:phase.ew.WAITING_PLANNING", phases: ["WAITING_PLANNING"] },
    { key: "scheduled", labelKey: "common:ticket_status.acknowledged", phases: ["SCHEDULED"] },
    { key: "in_progress", labelKey: "common:ticket_status.in_progress", phases: ["IN_EXECUTION"] },
    {
      key: "manager_check",
      labelKey: "common:ticket_status.waiting_manager_review",
      phases: ["WAITING_MANAGER_CHECK"],
    },
    {
      key: "customer_check",
      labelKey: "common:ticket_status.waiting_customer_approval",
      phases: ["WAITING_COMPLETION_APPROVAL"],
    },
  ],
  finished: [
    ALL_CHIP,
    // B2 — the Finished tab opens on the operator's question ("To
    // invoice"); the row badge beside it says the ticket's own word
    // ("Work approved", B1). A question is not a status.
    { key: "to_invoice", labelKey: "tabs.chip_to_invoice", phases: ["DONE"] },
    { key: "invoiced", labelKey: "common:phase.ew.INVOICED", phases: ["INVOICED"] },
  ],
};

/**
 * P-10 B2 — the chip a tab opens on: the first thing to do there. The
 * owner on Approved: "these are the first things to do" — the rows
 * nobody has planned. Exhaustive over the tabs; every value names a
 * chip of its own tab (pinned by `extraWorkTabs.test.ts`).
 */
export const DEFAULT_CHIP: Readonly<Record<ExtraWorkTab, string>> = {
  "to-price": ALL_CHIP.key,
  "with-customer": "waiting",
  approved: "not_planned",
  finished: "to_invoice",
};

/** The chip `raw` names on `tab`, or null when it names none (a
 *  missing or unknown `?chip=` means the tab's default). */
export function chipFromParam(tab: ExtraWorkTab, raw: string | null | undefined): string | null {
  if (!raw) return null;
  return SUB_CHIPS[tab].some((chip) => chip.key === raw) ? raw : null;
}

/** Does the work start by itself once it is priced? Mirrors the
 *  `AUTO_START_AFTER_PRICING` branch of `display_phase.py`. */
export function startsWhenPriced(row: ExtraWorkRequestList): boolean {
  return row.request_intent === "AUTO_START_AFTER_PRICING";
}

export function subChipMatches(chip: ExtraWorkSubChip, row: ExtraWorkRequestList): boolean {
  if (chip.phases && !chip.phases.includes(row.display_phase)) return false;
  if (chip.startsWhenPriced !== undefined && startsWhenPriced(row) !== chip.startsWhenPriced) {
    return false;
  }
  return true;
}

/** The bucket a row belongs to, or null for a phase this build does not
 *  know (a server string outside the union). Null is COUNTED by the
 *  page's guard, never dropped. */
export function bucketOf(row: ExtraWorkRequestList): ExtraWorkBucket | null {
  return (TAB_OF_PHASE as Record<string, ExtraWorkBucket | undefined>)[row.display_phase] ?? null;
}

/** P-11 A5 — the bucket's name for the cross-tab search line: a tab's
 *  own label, the cancelled view's title for the view that is not a
 *  tab. */
export const BUCKET_LABEL_KEY: Readonly<Record<ExtraWorkBucket, string>> = {
  ...TAB_LABEL_KEY,
  [CANCELLED_VIEW]: "tabs.cancelled_title",
};

/**
 * P-11 A5 — search searches the tab you are in: the tab is the
 * question, and a search inside it stays inside it. This is the ONE
 * search predicate (title, building, customer — the hay the page
 * always used), shared by the in-tab filter and the cross-tab line so
 * the two can never disagree about what "matches" means.
 */
export function searchMatches(row: ExtraWorkRequestList, needle: string): boolean {
  const trimmed = needle.trim().toLowerCase();
  if (!trimmed) return true;
  const hay = `${row.title} ${row.building_name ?? ""} ${row.customer_name ?? ""}`.toLowerCase();
  return hay.includes(trimmed);
}

export interface OtherTabMatch {
  bucket: ExtraWorkBucket;
  row: ExtraWorkRequestList;
}

/** The rows the needle matches OUTSIDE the active bucket, each named
 *  with its own bucket — the "Also N matches in other tabs" line.
 *  Pinned by `extraWorkTabs.test.ts` with a title that exists in two
 *  phases. Rows with a phase this build does not know are dropped here
 *  (they have no tab to point at); the page's guard counts them. */
export function otherTabMatches(
  rows: ReadonlyArray<ExtraWorkRequestList>,
  activeBucket: ExtraWorkBucket,
  needle: string,
): OtherTabMatch[] {
  if (!needle.trim()) return [];
  const out: OtherTabMatch[] = [];
  for (const row of rows) {
    const bucket = bucketOf(row);
    if (bucket === null || bucket === activeBucket) continue;
    if (searchMatches(row, needle)) out.push({ bucket, row });
  }
  return out;
}

export function isExtraWorkTab(value: string | null | undefined): value is ExtraWorkTab {
  return EXTRA_WORK_TABS.includes(value as ExtraWorkTab);
}

/** Where a deep link lands: the bucket, and the sub-chip when one
 *  stands for exactly that state. */
export interface DeepLinkTarget {
  bucket: ExtraWorkBucket;
  chip: string | null;
}

/**
 * Dashboard widgets still deep-link with `?status=<ExtraWorkStatus>`
 * (RF-18). A status lands on the tab its phase normally sits in;
 * exhaustive so a new status cannot silently open on "everything".
 */
const STATUS_DEEP_LINK: Readonly<Record<ExtraWorkStatus, DeepLinkTarget>> = {
  REQUESTED: { bucket: "to-price", chip: null },
  UNDER_REVIEW: { bucket: "to-price", chip: null },
  PRICING_PROPOSED: { bucket: "with-customer", chip: "waiting" },
  CUSTOMER_APPROVED: { bucket: "approved", chip: "not_planned" },
  IN_PROGRESS: { bucket: "approved", chip: "in_progress" },
  COMPLETED: { bucket: "finished", chip: null },
  CUSTOMER_REJECTED: { bucket: "with-customer", chip: "declined" },
  CANCELLED: { bucket: CANCELLED_VIEW, chip: null },
};

/** `?status=` accepts a phase name (P-8R) or a raw status. Unknown
 *  values resolve to null and the page opens normally. */
export function deepLinkTarget(raw: string | null): DeepLinkTarget | null {
  if (!raw || raw === "ALL") return null;
  const byPhase = (TAB_OF_PHASE as Record<string, ExtraWorkBucket | undefined>)[raw];
  if (byPhase) {
    if (byPhase === CANCELLED_VIEW) return { bucket: byPhase, chip: null };
    const chip = SUB_CHIPS[byPhase].find(
      (c) => c.phases && c.phases.length >= 1 && c.phases.includes(raw as ExtraWorkDisplayPhase),
    );
    return { bucket: byPhase, chip: chip?.key ?? null };
  }
  return (STATUS_DEEP_LINK as Record<string, DeepLinkTarget | undefined>)[raw] ?? null;
}

/** The first tab that has rows, else To price — where `/extra-work`
 *  lands when nobody asked for a tab. */
export function firstTabWithRows(counts: Readonly<Record<ExtraWorkBucket, number>>): ExtraWorkTab {
  return EXTRA_WORK_TABS.find((tab) => counts[tab] > 0) ?? "to-price";
}

/** Whole days from `fromIso` (a date or datetime string) to `todayIso`
 *  (YYYY-MM-DD). Negative when `fromIso` is in the future. Null when
 *  either is missing or unparseable. Date-only arithmetic on purpose:
 *  "waiting 3 days" counts calendar days, not 72 hours. */
export function daysSince(fromIso: string | null | undefined, todayIso: string): number | null {
  if (!fromIso) return null;
  const from = new Date(fromIso);
  const today = new Date(`${todayIso}T00:00:00`);
  if (Number.isNaN(from.getTime()) || Number.isNaN(today.getTime())) return null;
  const fromDay = new Date(from.getFullYear(), from.getMonth(), from.getDate());
  return Math.round((today.getTime() - fromDay.getTime()) / 86_400_000);
}

/** Today as YYYY-MM-DD in the browser's own calendar. */
export function todayIso(now: Date = new Date()): string {
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}
