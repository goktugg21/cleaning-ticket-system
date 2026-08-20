/**
 * W-E §2 — ONE reading of `ExtraWorkRequest.billed_to`, for every screen
 * that shows it.
 *
 * The field has THREE states and the app was rendering two. Sprint 182
 * §6 made the column nullable and migration 0032 set every existing row
 * to NULL, meaning "this job has no opinion — follow the customer's
 * `invoice_billing_target`". After that:
 *
 *   - the Extra Work detail page printed "Building" for a null, which is
 *     a claim about a decision nobody made;
 *   - the list looked the value up in a `Record` over the two-value
 *     union, so a null produced `undefined` and the cell rendered the
 *     key it could not find.
 *
 * Both read the same helper now, so the third state cannot be forgotten
 * on one screen and handled on the other. The `Record` is still keyed by
 * a union rather than written as an array, so a future fourth state
 * fails the compiler here (CLAUDE.md — a hardcoded literal defeats
 * exhaustiveness checking).
 */
import type { ExtraWorkBilledTo } from "../api/types";

const KEYS: Record<ExtraWorkBilledTo | "FOLLOW_CUSTOMER", string> = {
  FOLLOW_CUSTOMER: "billed_to.follow_customer",
  BUILDING: "billed_to.building",
  CUSTOMER: "billed_to.customer",
};

/** The `extra_work` translation key naming the invoice this work lands
 *  on. Null in — the normal state — reads as "follow the customer". */
export function billedToKey(value: ExtraWorkBilledTo | null): string {
  return KEYS[value ?? "FOLLOW_CUSTOMER"];
}
