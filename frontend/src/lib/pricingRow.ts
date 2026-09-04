/**
 * P-10 B4 — THE PRICING ROW EDITOR'S RULES, without React.
 *
 * "Edit" on a line of the Pricing table turns THAT row into inputs, and
 * nothing saves itself: a draft is typed, Save sends it, Cancel drops
 * it. This module is everything the row knows — the unit list, the
 * draft's shape, when Save is refused and why (§D.6 rule 14: a button
 * the server would refuse is disabled with its reason beside it), the
 * live money the row shows while typing, and the payload Save sends.
 * Pure data and pure functions; the component only renders them.
 */
import type { ProposalLineWritePayload } from "../api/extraWork";
import type { ExtraWorkUnitType, ProposalLine } from "../api/types";

/**
 * The units a line can be priced in: the catalogue's own list (the same
 * `unit_type` every Service carries) plus "other", which is the ONE
 * door to a unit word of the operator's own (`custom_unit_label`, the
 * backend's OTHER path). A `Record` over the union, so a sixth unit
 * fails the compiler here instead of missing from the select.
 */
const UNIT_RANK: Record<ExtraWorkUnitType, number> = {
  HOURS: 0,
  SQUARE_METERS: 1,
  FIXED: 2,
  ITEM: 3,
  OTHER: 4,
};
export const PRICING_UNIT_OPTIONS: readonly ExtraWorkUnitType[] = (
  Object.keys(UNIT_RANK) as ExtraWorkUnitType[]
).sort((a, b) => UNIT_RANK[a] - UNIT_RANK[b]);

/** The `extra_work` namespace key of each unit's label. */
export const PRICING_UNIT_LABEL_KEY: Record<ExtraWorkUnitType, string> = {
  HOURS: "unit_type.hours",
  SQUARE_METERS: "unit_type.square_meters",
  FIXED: "unit_type.fixed",
  ITEM: "unit_type.item",
  OTHER: "unit_type.other",
};

export const DEFAULT_VAT_PCT = "21.00";

export interface PricingRowDraft {
  description: string;
  quantity: string;
  unit_type: ExtraWorkUnitType;
  /** The operator's own unit word; meaningful only while `unit_type`
   *  is OTHER, blanked on the wire for every other unit. */
  custom_unit_label: string;
  unit_price: string;
  vat_pct: string;
  customer_explanation: string;
  internal_note: string;
}

/** A brand-new custom line: nothing typed yet, one of it, 21% VAT.
 *  The price is EMPTY, not "0.00" (W-FIX1 A3): zero is a price the
 *  operator types on purpose, never a default. */
export function emptyPricingRow(): PricingRowDraft {
  return {
    description: "",
    quantity: "1.00",
    unit_type: "FIXED",
    custom_unit_label: "",
    unit_price: "",
    vat_pct: DEFAULT_VAT_PCT,
    customer_explanation: "",
    internal_note: "",
  };
}

/** A SAVED line's values, back in the draft's shape. `unit_type` is
 *  OTHER on the wire whenever the operator typed a unit word, so the
 *  round trip keeps the word — otherwise reopening a "per pallet" line
 *  and pressing Save would rewrite it to a bare "Other". */
export function pricingRowFromLine(
  line: Pick<
    ProposalLine,
    | "description"
    | "quantity"
    | "unit_type"
    | "custom_unit_label"
    | "unit_price"
    | "vat_pct"
    | "customer_explanation"
  > & { internal_note?: string },
): PricingRowDraft {
  return {
    description: line.description ?? "",
    quantity: String(line.quantity),
    unit_type: line.unit_type,
    custom_unit_label: line.custom_unit_label ?? "",
    unit_price: String(line.unit_price),
    vat_pct: String(line.vat_pct),
    customer_explanation: line.customer_explanation ?? "",
    internal_note: line.internal_note ?? "",
  };
}

/** What the customer asked for, pre-filled so the operator sees what
 *  will change before it changes: quantity and unit from the request,
 *  the request's own words as the description of a custom line (a
 *  catalogue line keeps its service name), and no price yet. */
export function pricingRowFromRequest(seed: {
  label: string;
  quantity: string;
  unit_type: ExtraWorkUnitType;
  service: number | null;
}): PricingRowDraft {
  return {
    description: seed.service === null ? seed.label : "",
    quantity: String(seed.quantity),
    unit_type: seed.unit_type,
    custom_unit_label: "",
    unit_price: "",
    vat_pct: DEFAULT_VAT_PCT,
    customer_explanation: "",
    internal_note: "",
  };
}

const DRAFT_KEYS: readonly (keyof PricingRowDraft)[] = [
  "description",
  "quantity",
  "unit_type",
  "custom_unit_label",
  "unit_price",
  "vat_pct",
  "customer_explanation",
  "internal_note",
];

/** Has anything been typed? An unpriced row shows Save only once it has. */
export function pricingRowEquals(a: PricingRowDraft, b: PricingRowDraft): boolean {
  return DRAFT_KEYS.every((key) => a[key] === b[key]);
}

/** "12,50" and "12.50" are the same number; blank and junk are none. */
export function parseDecimal(raw: string): number | null {
  const text = raw.trim().replace(",", ".");
  if (text === "") return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

/** The first reason Save is refused, in the order the operator should
 *  hear them: the price first (rule 14's sentence — "Give it a price
 *  first"), then the rest. Null when the server would accept the row. */
export type PricingRowBlocker =
  | "price_missing"
  | "price_invalid"
  | "description_missing"
  | "quantity_invalid"
  | "vat_invalid";

export const PRICING_ROW_BLOCKER_KEY: Record<PricingRowBlocker, string> = {
  price_missing: "pricing_row.why_price",
  price_invalid: "pricing_row.why_price_invalid",
  description_missing: "pricing_row.why_description",
  quantity_invalid: "pricing_row.why_quantity",
  vat_invalid: "pricing_row.why_vat",
};

export function pricingRowBlocker(
  draft: PricingRowDraft,
  opts: { customLine: boolean },
): PricingRowBlocker | null {
  if (draft.unit_price.trim() === "") return "price_missing";
  const price = parseDecimal(draft.unit_price);
  if (price === null || price < 0) return "price_invalid";
  if (opts.customLine && draft.description.trim() === "") return "description_missing";
  const quantity = parseDecimal(draft.quantity);
  if (quantity === null || quantity <= 0) return "quantity_invalid";
  const vat = parseDecimal(draft.vat_pct);
  if (vat === null || vat < 0 || vat > 100) return "vat_invalid";
  return null;
}

/** Banker's rounding (ROUND_HALF_EVEN) to 2dp — the backend's Decimal
 *  quantisation, so the live boxes match the persisted totals. */
export function round2(n: number): number {
  const scaled = n * 100;
  const floor = Math.floor(scaled);
  const frac = scaled - floor;
  let rounded: number;
  if (Math.abs(frac - 0.5) < 1e-9) {
    rounded = floor % 2 === 0 ? floor : floor + 1;
  } else {
    rounded = Math.round(scaled);
  }
  return rounded / 100;
}

/** The row's own subtotal / VAT / total while typing, or null until
 *  there is a price and a quantity to multiply. The subtotal is rounded
 *  FIRST and VAT and total derive from it — the backend's staged
 *  quantisation. Display only: the totals line updates on Save. */
export function pricingRowMoney(
  draft: PricingRowDraft,
): { subtotal: number; vat: number; total: number } | null {
  const price = parseDecimal(draft.unit_price);
  const quantity = parseDecimal(draft.quantity);
  if (price === null || quantity === null) return null;
  const vatPct = parseDecimal(draft.vat_pct) ?? 0;
  const subtotal = round2(quantity * price);
  const vat = round2((subtotal * vatPct) / 100);
  return { subtotal, vat, total: round2(subtotal + vat) };
}

function decimalString(raw: string): string {
  const value = parseDecimal(raw);
  return value === null ? raw.trim() : value.toFixed(2);
}

/** What Save sends, on POST and on PATCH alike. `service` rides only
 *  when the caller names it (a request line's catalogue service on
 *  create); an edit omits it and the line keeps its own. The unit word
 *  travels only with OTHER — the backend blanks it for every concrete
 *  unit anyway (RF-2). */
export function pricingRowPayload(
  draft: PricingRowDraft,
  opts: { service?: number | null; includeInternal: boolean },
): ProposalLineWritePayload {
  const payload: ProposalLineWritePayload = {
    description: draft.description.trim(),
    quantity: decimalString(draft.quantity),
    unit_type: draft.unit_type,
    custom_unit_label:
      draft.unit_type === "OTHER" ? draft.custom_unit_label.trim() : "",
    unit_price: decimalString(draft.unit_price),
    vat_pct: decimalString(draft.vat_pct),
    customer_explanation: draft.customer_explanation,
  };
  if (opts.service !== undefined) payload.service = opts.service;
  if (opts.includeInternal) payload.internal_note = draft.internal_note;
  return payload;
}
