import { describe, expect, it } from "vitest";

import type {
  ExtraWorkRequestDetail,
  Proposal,
  ProposalDetail,
} from "../../api/types";

import { agreedLines } from "./agreedLines";

/** Minimal shapes — only the fields the derivation reads. */
function ewWith(partial: Record<string, unknown>): ExtraWorkRequestDetail {
  return {
    routing_decision: null,
    line_items: [],
    pricing_line_items: [],
    ...partial,
  } as unknown as ExtraWorkRequestDetail;
}

const APPROVED = { id: 7, status: "CUSTOMER_APPROVED" } as unknown as Proposal;

describe("agreedLines — ONE VAT basis (P-13 W3)", () => {
  it("proposal path: the Amount is the EX-VAT subtotal, never line_total — €31.48 stays €31.48", () => {
    const detail = {
      lines: [
        {
          id: 1,
          is_approved_for_spawn: true,
          service_name: "Extra werk regie uren",
          description: "",
          quantity: "1.00",
          line_subtotal: "31.48",
          line_vat: "6.61",
          line_total: "38.09",
        },
      ],
    } as unknown as ProposalDetail;
    const { rows, totals } = agreedLines(ewWith({}), APPROVED, detail);
    expect(rows).toHaveLength(1);
    expect(rows[0].amount).toBe(31.48);
    expect(totals).toEqual({ ex: 31.48, incl: 38.09 });
  });

  it("legacy path: the Amount is the stored EX-VAT subtotal, never total", () => {
    const ew = ewWith({
      pricing_line_items: [
        {
          id: 2,
          description: "Deep cleaning",
          quantity: "6.00",
          subtotal: "252.00",
          vat_amount: "52.92",
          total: "304.92",
        },
      ],
    });
    const { rows, totals } = agreedLines(ew, null, null);
    expect(rows[0].amount).toBe(252);
    expect(totals).toEqual({ ex: 252, incl: 304.92 });
  });

  it("instant path: price × qty stays ex VAT and the incl total derives per line", () => {
    const ew = ewWith({
      routing_decision: "INSTANT",
      line_items: [
        {
          id: 3,
          service_name: "Deep cleaning",
          custom_description: "",
          quantity: "6.00",
          contract_unit_price: "42.00",
          contract_vat_pct: "21.00",
        },
      ],
    });
    const { rows, totals } = agreedLines(ew, null, null);
    expect(rows[0].amount).toBe(252);
    expect(totals).toEqual({ ex: 252, incl: 304.92 });
  });

  it("an unpriced instant line keeps its em dash and makes the totals unknowable", () => {
    const ew = ewWith({
      routing_decision: "INSTANT",
      line_items: [
        {
          id: 4,
          service_name: "Needs a quote",
          custom_description: "",
          quantity: "2.00",
          contract_unit_price: null,
          contract_vat_pct: null,
        },
      ],
    });
    const { rows, totals } = agreedLines(ew, null, null);
    expect(rows[0].amount).toBeNull();
    expect(totals).toBeNull();
  });

  it("no lines: no rows, no totals", () => {
    expect(agreedLines(ewWith({}), null, null)).toEqual({
      rows: [],
      totals: null,
    });
  });
});
