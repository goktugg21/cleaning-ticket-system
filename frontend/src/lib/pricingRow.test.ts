import { describe, expect, it } from "vitest";

import {
  DEFAULT_VAT_PCT,
  PRICING_ROW_BLOCKER_KEY,
  PRICING_UNIT_LABEL_KEY,
  PRICING_UNIT_OPTIONS,
  emptyPricingRow,
  parseDecimal,
  pricingRowBlocker,
  pricingRowEquals,
  pricingRowFromLine,
  pricingRowFromRequest,
  pricingRowMoney,
  pricingRowPayload,
  round2,
  type PricingRowDraft,
} from "./pricingRow";

const priced = (over: Partial<PricingRowDraft> = {}): PricingRowDraft => ({
  ...emptyPricingRow(),
  description: "Crew time on Saturday",
  unit_price: "50.00",
  ...over,
});

describe("PRICING_UNIT_OPTIONS", () => {
  it("is the catalogue's list plus other, in catalogue order, other last", () => {
    expect(PRICING_UNIT_OPTIONS).toEqual(["HOURS", "SQUARE_METERS", "FIXED", "ITEM", "OTHER"]);
    for (const unit of PRICING_UNIT_OPTIONS) {
      expect(PRICING_UNIT_LABEL_KEY[unit]).toMatch(/^unit_type\./);
    }
  });
});

describe("drafts", () => {
  it("opens a new custom line with no price, one of it and 21% VAT", () => {
    const draft = emptyPricingRow();
    expect(draft.unit_price).toBe("");
    expect(draft.quantity).toBe("1.00");
    expect(draft.vat_pct).toBe(DEFAULT_VAT_PCT);
    expect(draft.unit_type).toBe("FIXED");
  });

  it("round-trips a saved line, keeping the operator's own unit word", () => {
    const draft = pricingRowFromLine({
      description: "",
      quantity: "3.00",
      unit_type: "OTHER",
      custom_unit_label: "pallet",
      unit_price: "12.50",
      vat_pct: "9.00",
      customer_explanation: "visible",
      internal_note: "hidden",
    });
    expect(draft).toEqual({
      description: "",
      quantity: "3.00",
      unit_type: "OTHER",
      custom_unit_label: "pallet",
      unit_price: "12.50",
      vat_pct: "9.00",
      customer_explanation: "visible",
      internal_note: "hidden",
    });
    // A customer read omits internal_note; the draft still has a string.
    expect(
      pricingRowFromLine({
        description: "x",
        quantity: "1.00",
        unit_type: "HOURS",
        custom_unit_label: "",
        unit_price: "1.00",
        vat_pct: "21.00",
        customer_explanation: "",
      }).internal_note,
    ).toBe("");
  });

  it("pre-fills what the customer asked for, and no price", () => {
    const custom = pricingRowFromRequest({
      label: "Graffiti removal",
      quantity: "2.00",
      unit_type: "SQUARE_METERS",
      service: null,
    });
    expect(custom.description).toBe("Graffiti removal");
    expect(custom.quantity).toBe("2.00");
    expect(custom.unit_type).toBe("SQUARE_METERS");
    expect(custom.unit_price).toBe("");
    // A catalogue line keeps its service name; the description stays empty.
    const catalog = pricingRowFromRequest({
      label: "Window cleaning",
      quantity: "4.00",
      unit_type: "HOURS",
      service: 15,
    });
    expect(catalog.description).toBe("");
  });

  it("knows when something was typed", () => {
    const seed = pricingRowFromRequest({
      label: "ff",
      quantity: "1.00",
      unit_type: "FIXED",
      service: null,
    });
    expect(pricingRowEquals(seed, { ...seed })).toBe(true);
    expect(pricingRowEquals(seed, { ...seed, unit_price: "1" })).toBe(false);
    expect(pricingRowEquals(seed, { ...seed, quantity: "2.00" })).toBe(false);
    expect(pricingRowEquals(seed, { ...seed, unit_type: "HOURS" })).toBe(false);
  });
});

describe("parseDecimal", () => {
  it("reads a comma or a dot, and nothing from blank or junk", () => {
    expect(parseDecimal("12,50")).toBe(12.5);
    expect(parseDecimal(" 12.50 ")).toBe(12.5);
    expect(parseDecimal("0")).toBe(0);
    expect(parseDecimal("")).toBeNull();
    expect(parseDecimal("   ")).toBeNull();
    expect(parseDecimal("abc")).toBeNull();
  });
});

describe("pricingRowBlocker (rule 14)", () => {
  it("refuses Save with 'give it a price first' while the price is empty", () => {
    expect(pricingRowBlocker(priced({ unit_price: "" }), { customLine: true })).toBe(
      "price_missing",
    );
    expect(pricingRowBlocker(priced({ unit_price: "  " }), { customLine: false })).toBe(
      "price_missing",
    );
    expect(PRICING_ROW_BLOCKER_KEY.price_missing).toBe("pricing_row.why_price");
  });

  it("takes 0.00 as a price, on purpose", () => {
    expect(pricingRowBlocker(priced({ unit_price: "0" }), { customLine: true })).toBeNull();
    expect(pricingRowBlocker(priced({ unit_price: "0,00" }), { customLine: true })).toBeNull();
  });

  it("refuses a negative or unreadable price", () => {
    expect(pricingRowBlocker(priced({ unit_price: "-1" }), { customLine: true })).toBe(
      "price_invalid",
    );
    expect(pricingRowBlocker(priced({ unit_price: "abc" }), { customLine: true })).toBe(
      "price_invalid",
    );
  });

  it("wants a description on a custom line only", () => {
    expect(pricingRowBlocker(priced({ description: " " }), { customLine: true })).toBe(
      "description_missing",
    );
    expect(pricingRowBlocker(priced({ description: "" }), { customLine: false })).toBeNull();
  });

  it("wants a quantity above zero and a VAT between 0 and 100", () => {
    expect(pricingRowBlocker(priced({ quantity: "0" }), { customLine: true })).toBe(
      "quantity_invalid",
    );
    expect(pricingRowBlocker(priced({ quantity: "" }), { customLine: true })).toBe(
      "quantity_invalid",
    );
    expect(pricingRowBlocker(priced({ vat_pct: "101" }), { customLine: true })).toBe(
      "vat_invalid",
    );
    expect(pricingRowBlocker(priced({ vat_pct: "-1" }), { customLine: true })).toBe(
      "vat_invalid",
    );
    expect(pricingRowBlocker(priced({ vat_pct: "0" }), { customLine: true })).toBeNull();
  });

  it("names the price before anything else", () => {
    expect(
      pricingRowBlocker(priced({ unit_price: "", description: "", quantity: "0" }), {
        customLine: true,
      }),
    ).toBe("price_missing");
  });
});

describe("pricingRowMoney", () => {
  it("shows nothing until there is a price", () => {
    expect(pricingRowMoney(priced({ unit_price: "" }))).toBeNull();
    expect(pricingRowMoney(priced({ quantity: "" }))).toBeNull();
  });

  it("rounds the subtotal first and derives VAT and total from it", () => {
    expect(pricingRowMoney(priced({ quantity: "3", unit_price: "12.5", vat_pct: "21" }))).toEqual(
      { subtotal: 37.5, vat: 7.88, total: 45.38 },
    );
    expect(pricingRowMoney(priced({ quantity: "2", unit_price: "0", vat_pct: "21" }))).toEqual({
      subtotal: 0,
      vat: 0,
      total: 0,
    });
  });

  it("rounds halves to even like the backend", () => {
    expect(round2(0.125)).toBe(0.12);
    expect(round2(0.135)).toBe(0.14);
    expect(round2(2.675)).toBe(2.68);
  });
});

describe("pricingRowPayload", () => {
  it("sends two-decimal numbers and blanks the unit word off a concrete unit", () => {
    const payload = pricingRowPayload(
      priced({
        quantity: "2,5",
        unit_price: "12,5",
        vat_pct: "21",
        unit_type: "HOURS",
        custom_unit_label: "stale",
        description: "  Crew time  ",
        internal_note: "cost 40",
      }),
      { includeInternal: true },
    );
    expect(payload).toEqual({
      description: "Crew time",
      quantity: "2.50",
      unit_type: "HOURS",
      custom_unit_label: "",
      unit_price: "12.50",
      vat_pct: "21.00",
      customer_explanation: "",
      internal_note: "cost 40",
    });
    expect("service" in payload).toBe(false);
  });

  it("keeps the unit word only behind other, and the service only when named", () => {
    const payload = pricingRowPayload(
      priced({ unit_type: "OTHER", custom_unit_label: " pallet " }),
      { service: null, includeInternal: false },
    );
    expect(payload.unit_type).toBe("OTHER");
    expect(payload.custom_unit_label).toBe("pallet");
    expect(payload.service).toBeNull();
    expect("internal_note" in payload).toBe(false);
    expect(
      pricingRowPayload(priced(), { service: 15, includeInternal: false }).service,
    ).toBe(15);
  });
});
