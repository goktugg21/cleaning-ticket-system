// P-11 B2/B4 — the grid's sum and fill behaviour, pinned pure.
import { describe, expect, it } from "vitest";

import {
  acceptsHoursInput,
  fillTargetCount,
  isFillTarget,
  parseHours,
  sumHours,
} from "./gridRules";

describe("hours input and sums", () => {
  it("accepts what a person types while typing hours, both separators", () => {
    for (const good of ["", "8", "7.5", "7,5", "12", "0.25", "23,75"]) {
      expect(acceptsHoursInput(good), good).toBe(true);
    }
    for (const bad of ["g", "8h", "1.2.3", "123", "-1", "8,555"]) {
      expect(acceptsHoursInput(bad), bad).toBe(false);
    }
  });

  it("parses the comma and the dot to the same number; junk counts zero", () => {
    expect(parseHours("7,5")).toBe(7.5);
    expect(parseHours("7.5")).toBe(7.5);
    expect(parseHours("  8 ")).toBe(8);
    expect(parseHours("")).toBe(0);
    expect(parseHours("g")).toBe(0);
    expect(parseHours("-2")).toBe(0);
  });

  it("sums a line the way the Week column prints it", () => {
    expect(sumHours(["3", "4,5", "", "0", "1.25"])).toBe(8.75);
  });
});

describe("the fill row lands on the standard lines only (P-11 B2)", () => {
  const standard = { sourceType: "" };
  const jobLine = { sourceType: "TICKET" };
  const extraWorkLine = { sourceType: "EXTRA_WORK" };
  const addedByHand = { sourceType: "", manual: true };

  it("a standard line is filled; a job line and an added line are not", () => {
    expect(isFillTarget(standard)).toBe(true);
    expect(isFillTarget(jobLine)).toBe(false);
    expect(isFillTarget(extraWorkLine)).toBe(false);
    expect(isFillTarget(addedByHand)).toBe(false);
  });

  it("the sentence's count is the same predicate — it cannot disagree with the behaviour", () => {
    expect(
      fillTargetCount([standard, standard, jobLine, extraWorkLine, addedByHand]),
    ).toBe(2);
  });
});
