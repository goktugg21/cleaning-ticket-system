/** P-15 4.3 — the compressed pattern words, pinned. */
import { describe, expect, it } from "vitest";

import { patternGroups, patternLabel } from "./patternLabel";
import type { PatternDay } from "./patternLabel";

const LABELS: Record<PatternDay, string> = {
  monday: "Mon",
  tuesday: "Tue",
  wednesday: "Wed",
  thursday: "Thu",
  friday: "Fri",
  saturday: "Sat",
  sunday: "Sun",
};

const label = (days: Partial<Record<PatternDay, string>>) =>
  patternLabel(
    {
      monday: "0",
      tuesday: "0",
      wednesday: "0",
      thursday: "0",
      friday: "0",
      saturday: "0",
      sunday: "0",
      ...days,
    },
    (day) => LABELS[day],
    (hours) => `${hours} h`,
  );

describe("patternLabel", () => {
  it("compresses a working week into one run", () => {
    expect(
      label({
        monday: "8.00",
        tuesday: "8.00",
        wednesday: "8.00",
        thursday: "8.00",
        friday: "8.00",
      }),
    ).toBe("Mon–Fri · 8 h");
  });

  it("splits where the hours differ", () => {
    expect(
      label({
        monday: "8.00",
        tuesday: "8.00",
        wednesday: "8.00",
        thursday: "8.00",
        friday: "6.00",
      }),
    ).toBe("Mon–Thu · 8 h, Fri · 6 h");
  });

  it("skips zero days — a gap breaks the run", () => {
    expect(
      label({ monday: "4.00", wednesday: "4.00" }),
    ).toBe("Mon · 4 h, Wed · 4 h");
  });

  it("an all-zero pattern answers null, never a fabricated run", () => {
    expect(label({})).toBeNull();
    expect(patternGroups({
      monday: "0",
      tuesday: "0",
      wednesday: "0",
      thursday: "0",
      friday: "0",
      saturday: "0",
      sunday: "0",
    })).toEqual([]);
  });

  it("a single day names itself once", () => {
    expect(label({ saturday: "5.50" })).toBe("Sat · 5.5 h");
  });
});
