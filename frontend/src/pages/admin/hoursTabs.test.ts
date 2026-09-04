import { describe, expect, it } from "vitest";

import { HOURS_TABS, hoursTabOf } from "./hoursTabs";

describe("hoursTabs — the Hours page's two tabs (P-14 A1)", () => {
  it("is exactly Worked then Agreed, each with its own path", () => {
    expect(HOURS_TABS.map((t) => t.key)).toEqual(["worked", "agreed"]);
    expect(HOURS_TABS.map((t) => t.path)).toEqual([
      "/admin/hours",
      "/admin/hours/agreed",
    ]);
  });
  it("every tab has a distinct label key", () => {
    const labels = HOURS_TABS.map((t) => t.labelKey);
    expect(new Set(labels).size).toBe(labels.length);
  });
  it("the bare page is the Worked tab", () => {
    expect(hoursTabOf("/admin/hours", null)).toBe("worked");
    expect(hoursTabOf("/admin/hours/", undefined)).toBe("worked");
  });
  it("/admin/hours/agreed is the Agreed tab", () => {
    expect(hoursTabOf("/admin/hours/agreed", null)).toBe("agreed");
    expect(hoursTabOf("/admin/hours/agreed/", null)).toBe("agreed");
  });
  it("the P-13 ?tab=schedule deep link still lands on Agreed", () => {
    expect(hoursTabOf("/admin/hours", "schedule")).toBe("agreed");
  });
  it("an unknown ?tab= means Worked", () => {
    expect(hoursTabOf("/admin/hours", "garbage")).toBe("worked");
    expect(hoursTabOf("/admin/hours", "")).toBe("worked");
  });
});
