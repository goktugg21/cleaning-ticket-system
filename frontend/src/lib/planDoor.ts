/**
 * P-11 A7 — where the banner's "Plan it" door lands.
 *
 * The rule-14 gate's sentence ends in a door. P-10 wired that door to
 * `pointAtMissingPiece("schedule")` alone — but the schedule anchor
 * mounts only on the Plan tab, and the missing-piece pointer is
 * deliberately decoupled (lib/missingPiece.ts): pointing at an
 * unmounted anchor parks the target silently. On every other tab the
 * click did nothing — the owner's dead door.
 *
 * The decision is pure and lives here so vitest can pin it:
 *  - a ticket born from extra work, viewed by someone who may open the
 *    plan modal, gets the modal itself — the same one the Actions
 *    card's "Plan the work" opens (the plan's one home);
 *  - every other case switches to the Plan tab FIRST and only then
 *    points at the schedule anchor. The order is the fix: the anchor
 *    must be mounted before the pointer fires.
 */

export type PlanDoorAction =
  | { kind: "ew-plan-modal" }
  | { kind: "schedule-anchor"; tab: "plan" };

export function planDoorAction(opts: {
  hasExtraWorkOrigin: boolean;
  canOpenEwPlan: boolean;
}): PlanDoorAction {
  if (opts.hasExtraWorkOrigin && opts.canOpenEwPlan) {
    return { kind: "ew-plan-modal" };
  }
  return { kind: "schedule-anchor", tab: "plan" };
}
