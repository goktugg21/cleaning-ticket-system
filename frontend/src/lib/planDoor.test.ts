// P-11 A7 — the banner's "Plan it" door was dead on a fresh spawned
// ticket: it pointed at the schedule anchor without switching to the
// tab that mounts it. These pins keep the door's landing honest.
import { describe, expect, it } from "vitest";

import { planDoorAction } from "./planDoor";

describe("planDoorAction", () => {
  it("opens the plan modal for a spawned ticket the viewer may plan", () => {
    expect(
      planDoorAction({ hasExtraWorkOrigin: true, canOpenEwPlan: true }),
    ).toEqual({ kind: "ew-plan-modal" });
  });

  it("names the tab that hosts the schedule anchor for an ordinary ticket — pointing without switching is the P-10 dead door", () => {
    expect(
      planDoorAction({ hasExtraWorkOrigin: false, canOpenEwPlan: true }),
    ).toEqual({ kind: "schedule-anchor", tab: "plan" });
  });

  it("falls back to the schedule anchor when the viewer may not open the extra-work plan (STAFF is hard-404'd on extra work)", () => {
    expect(
      planDoorAction({ hasExtraWorkOrigin: true, canOpenEwPlan: false }),
    ).toEqual({ kind: "schedule-anchor", tab: "plan" });
  });
});
