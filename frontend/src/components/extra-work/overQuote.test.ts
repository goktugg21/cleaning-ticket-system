import { describe, expect, it } from "vitest";

import { overQuoteFacts, overQuoteNeedsConfirm } from "./overQuote";

describe("overQuoteFacts — billed vs agreed hours (P-13 B)", () => {
  it("6.5 h worked against 6 h agreed at €42 is €21.00 more", () => {
    const facts = overQuoteFacts([
      { rate: 42, quantity: 6, worked: 6.5 },
    ]);
    expect(facts).toEqual({
      agreedHours: 6,
      workedHours: 6.5,
      deltaAmount: 21,
    });
  });
  it("no hours entered yet means no difference (worked falls back to agreed)", () => {
    const facts = overQuoteFacts([{ rate: 42, quantity: 6, worked: null }]);
    expect(facts?.deltaAmount).toBe(0);
  });
  it("a line without a rate makes the money delta unknowable", () => {
    expect(
      overQuoteFacts([
        { rate: 42, quantity: 6, worked: 6.5 },
        { rate: null, quantity: 2, worked: 3 },
      ]),
    ).toBeNull();
  });
});

describe("overQuoteNeedsConfirm — over 25% or over €100 MORE; warn only", () => {
  it("€21 more on a €286 job asks nothing (under both thresholds)", () => {
    expect(overQuoteNeedsConfirm(21, 286)).toBe(false);
  });
  it("over €100 more always asks", () => {
    expect(overQuoteNeedsConfirm(120, 5000)).toBe(true);
  });
  it("over 25% of the agreed total asks", () => {
    expect(overQuoteNeedsConfirm(80, 286)).toBe(true);
  });
  it("billing LESS never asks", () => {
    expect(overQuoteNeedsConfirm(-500, 286)).toBe(false);
  });
  it("with no agreed base only the €100 arm applies", () => {
    expect(overQuoteNeedsConfirm(60, null)).toBe(false);
    expect(overQuoteNeedsConfirm(101, null)).toBe(true);
  });
});
