import { describe, expect, it } from "vitest";
import type { TFunction } from "i18next";

import {
  compareCoverage,
  coverageConfirmLabel,
  coverageQuantity,
  foldLabel,
  type CoverageLine,
} from "./extraWorkCoverage";

const cart = (
  id: number,
  label: string,
  quantity: string,
  service: number | null = null,
): CoverageLine => ({ id, label, quantity, service });

const quote = cart;

describe("compareCoverage", () => {
  it("is exact when every cart line has a quote line with the same quantity", () => {
    const result = compareCoverage(
      [cart(1, "Window cleaning", "2.00", 15), cart(2, "ff", "1.00")],
      [quote(10, "Window cleaning", "2.00", 15), quote(11, "ff", "1.00")],
    );
    expect(result.exact).toBe(true);
    expect(result.covered.map((p) => [p.cart.id, p.quote.id])).toEqual([
      [1, 10],
      [2, 11],
    ]);
    expect(result.uncovered).toEqual([]);
    expect(result.extra).toEqual([]);
    expect(result.quantityDiffs).toEqual([]);
  });

  it("names the cart lines the quote does not cover (fewer)", () => {
    const result = compareCoverage(
      [
        cart(1, "Window cleaning", "2.00", 15),
        cart(2, "ff", "1.00"),
        cart(3, "Graffiti removal", "1.00"),
      ],
      [quote(10, "Window cleaning", "2.00", 15), quote(11, "ff", "1.00")],
    );
    expect(result.exact).toBe(false);
    expect(result.covered).toHaveLength(2);
    expect(result.uncovered.map((l) => l.label)).toEqual(["Graffiti removal"]);
    expect(result.extra).toEqual([]);
  });

  it("names the quote lines the customer did not ask for (more)", () => {
    const result = compareCoverage(
      [cart(1, "Window cleaning", "2.00", 15)],
      [
        quote(10, "Window cleaning", "2.00", 15),
        quote(11, "Travel", "1.00"),
      ],
    );
    expect(result.exact).toBe(false);
    expect(result.uncovered).toEqual([]);
    expect(result.extra.map((l) => l.label)).toEqual(["Travel"]);
  });

  it("reports a quantity that differs on a matched line", () => {
    const result = compareCoverage(
      [cart(1, "Regie uren", "2.00", 15)],
      [quote(10, "Regie uren", "4.00", 15)],
    );
    expect(result.exact).toBe(false);
    expect(result.covered).toHaveLength(1);
    expect(result.quantityDiffs).toHaveLength(1);
    expect(result.quantityDiffs[0].asked).toBe(2);
    expect(result.quantityDiffs[0].priced).toBe(4);
  });

  it("matches free-text lines by trimmed, case-folded name", () => {
    const result = compareCoverage(
      [cart(1, "  Graffiti   removal ", "1.00")],
      [quote(10, "graffiti removal", "1.00")],
    );
    expect(result.exact).toBe(true);
  });

  it("matches a service cart line by service id even when the names differ", () => {
    const result = compareCoverage(
      [cart(1, "Extra werk regie uren", "3.00", 15)],
      [quote(10, "Regie", "3.00", 15)],
    );
    expect(result.exact).toBe(true);
  });

  it("matches a service cart line by name when the quote line was typed without the service", () => {
    const result = compareCoverage(
      [cart(1, "Window cleaning", "1.00", 15)],
      [quote(10, "window cleaning", "1.00")],
    );
    expect(result.exact).toBe(true);
    expect(result.covered[0].quote.id).toBe(10);
  });

  it("lets a quote line cover at most one cart line", () => {
    const result = compareCoverage(
      [cart(1, "ff", "1.00"), cart(2, "ff", "1.00")],
      [quote(10, "ff", "1.00")],
    );
    expect(result.covered).toHaveLength(1);
    expect(result.uncovered.map((l) => l.id)).toEqual([2]);
    expect(result.extra).toEqual([]);
  });

  it("treats an empty quote as covering nothing", () => {
    const result = compareCoverage([cart(1, "ff", "1.00")], []);
    expect(result.exact).toBe(false);
    expect(result.uncovered).toHaveLength(1);
  });

  it("is exact for an empty cart and an empty quote", () => {
    expect(compareCoverage([], []).exact).toBe(true);
  });
});

describe("coverageConfirmLabel", () => {
  const t = ((key: string, options?: Record<string, unknown>) =>
    `${key}${options ? " " + JSON.stringify(options) : ""}`) as unknown as TFunction;

  it("keeps the exact label when the price covers the request", () => {
    const exact = compareCoverage([cart(1, "ff", "1.00")], [quote(10, "ff", "1.00")]);
    expect(coverageConfirmLabel(t, exact, "send", "Send the price")).toBe("Send the price");
    expect(coverageConfirmLabel(t, null, "start", "Yes, start")).toBe("Yes, start");
  });

  it("says the covered count when lines are missing", () => {
    const fewer = compareCoverage(
      [cart(1, "a", "1"), cart(2, "b", "1"), cart(3, "c", "1")],
      [quote(10, "a", "1"), quote(11, "b", "1")],
    );
    expect(coverageConfirmLabel(t, fewer, "start", "x")).toBe(
      'detail.coverage_start_partial {"covered":2,"asked":3}',
    );
  });

  it("says the line count and the extras when lines were added", () => {
    const more = compareCoverage(
      [cart(1, "a", "1"), cart(2, "b", "1"), cart(3, "c", "1")],
      [quote(10, "a", "1"), quote(11, "b", "1"), quote(12, "c", "1"), quote(13, "d", "1")],
    );
    expect(coverageConfirmLabel(t, more, "send", "x")).toBe(
      'detail.coverage_send_extra {"count":4,"extra":1}',
    );
  });

  it("keeps the exact label for a quantity-only difference", () => {
    const qty = compareCoverage([cart(1, "a", "2")], [quote(10, "a", "4")]);
    expect(coverageConfirmLabel(t, qty, "approve", "Confirm")).toBe("Confirm");
  });
});

describe("helpers", () => {
  it("folds labels", () => {
    expect(foldLabel("  Ramen   Wassen ")).toBe("ramen wassen");
  });
  it("prints quantities without trailing zeros", () => {
    expect(coverageQuantity(2)).toBe("2");
    expect(coverageQuantity(2.5)).toBe("2.5");
    expect(coverageQuantity(2.004)).toBe("2");
  });
});
