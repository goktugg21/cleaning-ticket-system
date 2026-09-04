import { describe, expect, it } from "vitest";

import { daysBetween, shortDay, shortDayTime, shortRange } from "./shortDate";

const TODAY = "2026-09-01";

describe("shortDate", () => {
  it("prints weekday, day and short month in one fixed order, without the year in the current year", () => {
    // en-US on its own says "Wed, Aug 26"; the house shape is day before month.
    expect(shortDay("2026-08-26", "en-US", TODAY)).toBe("Wed 26 Aug");
    // nl's short month carries a period ("aug."); the house shape drops it.
    expect(shortDay("2026-08-26", "nl-NL", TODAY)).toBe("wo 26 aug");
  });
  it("adds the year only when it differs from today's", () => {
    expect(shortDay("2025-12-30", "en-US", TODAY)).toBe("Tue 30 Dec 2025");
    expect(shortDay("2025-12-30", "nl-NL", TODAY)).toBe("di 30 dec 2025");
  });
  it("ranges with an en dash; a one-day window is one day", () => {
    expect(shortRange("2026-08-30", "2026-09-09", "en-US", TODAY)).toBe("Sun 30 Aug – Wed 9 Sep");
    expect(shortRange("2026-08-30", "2026-08-30", "en-US", TODAY)).toBe("Sun 30 Aug");
    expect(shortRange("2026-08-30", null, "en-US", TODAY)).toBe("Sun 30 Aug");
    expect(shortRange(null, null, "en-US", TODAY)).toBe("—");
  });
  it("prints a clock only when one is given", () => {
    expect(shortDayTime("2026-09-01", "09:00", "en-US", TODAY)).toBe("Tue 1 Sep 09:00");
    expect(shortDayTime("2026-09-01", null, "en-US", TODAY)).toBe("Tue 1 Sep");
  });
  it("never throws on junk", () => {
    expect(shortDay("not-a-day", "en-US", TODAY)).toBe("—");
    expect(shortDay(null, "en-US", TODAY)).toBe("—");
  });
  it("counts whole days, signed", () => {
    expect(daysBetween("2026-08-26", "2026-09-01")).toBe(6);
    expect(daysBetween("2026-09-01", "2026-08-26")).toBe(-6);
  });
});
