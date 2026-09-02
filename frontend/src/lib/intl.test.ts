import { describe, expect, it } from "vitest";

import { formatOrdinal } from "./intl";

describe("formatOrdinal", () => {
  it("speaks English ordinals through Intl.PluralRules", () => {
    expect(formatOrdinal(1, "en-US")).toBe("1st");
    expect(formatOrdinal(2, "en-US")).toBe("2nd");
    expect(formatOrdinal(3, "en-US")).toBe("3rd");
    expect(formatOrdinal(4, "en-US")).toBe("4th");
    expect(formatOrdinal(11, "en-US")).toBe("11th");
    expect(formatOrdinal(12, "en-US")).toBe("12th");
    expect(formatOrdinal(13, "en-US")).toBe("13th");
    expect(formatOrdinal(21, "en-US")).toBe("21st");
    expect(formatOrdinal(22, "en-US")).toBe("22nd");
    expect(formatOrdinal(31, "en-US")).toBe("31st");
  });
  it("speaks Dutch day-of-month ordinals (-ste for 1, 8 and 20 up; -de otherwise)", () => {
    expect(formatOrdinal(1, "nl-NL")).toBe("1ste");
    expect(formatOrdinal(2, "nl-NL")).toBe("2de");
    expect(formatOrdinal(8, "nl-NL")).toBe("8ste");
    expect(formatOrdinal(19, "nl-NL")).toBe("19de");
    expect(formatOrdinal(20, "nl-NL")).toBe("20ste");
    expect(formatOrdinal(28, "nl-NL")).toBe("28ste");
    expect(formatOrdinal(31, "nl-NL")).toBe("31ste");
  });
  it("never throws on junk", () => {
    expect(formatOrdinal(null, "en-US")).toBe("—");
    expect(formatOrdinal(undefined, "en-US")).toBe("—");
    expect(formatOrdinal(Number.NaN, "en-US")).toBe("—");
  });
});
