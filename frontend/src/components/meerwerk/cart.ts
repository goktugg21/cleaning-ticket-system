/**
 * FE-5 — the meerwerk cart, shared by the customer's guided flow
 * (`pages/customer/MeerwerkFlowPage`) and the provider's create page
 * (`pages/CreateExtraWorkPage`).
 *
 * One line shape, one payload mapping, one title/description
 * derivation: the two surfaces submit to the SAME create endpoint and
 * must describe a cart in the same words, so the pieces they share
 * live here rather than as two copies that drift.
 */
import type { CustomerCustomPrice, CustomerServicePrice } from "../../api/types";

export interface MeerwerkCartLine {
  key: string;
  kind: "service" | "custom_price" | "other";
  id: number | null;
  label: string;
  /** The customer's OWN agreed / custom price, as the server sends it. */
  unitPrice: string | null;
  vatPct: string | null;
  quantity: number;
  otherText: string;
  /** The optional note on a line. */
  note?: string;
}

/** FE-4 — one "iets anders" row while it is being typed. */
export interface OtherLineDraft {
  key: string;
  text: string;
  note: string;
}

export function emptyOtherLine(index: number): OtherLineDraft {
  return { key: `other-${index}`, text: "", note: "" };
}

export function serviceLine(price: CustomerServicePrice): MeerwerkCartLine {
  return {
    key: `svc-${price.service}`,
    kind: "service",
    id: price.service,
    label: price.service_name,
    unitPrice: price.unit_price,
    vatPct: price.vat_pct,
    quantity: 1,
    otherText: "",
  };
}

export function customPriceLine(price: CustomerCustomPrice): MeerwerkCartLine {
  return {
    key: `cp-${price.id}`,
    kind: "custom_price",
    id: price.id,
    label: price.custom_name,
    unitPrice: price.unit_price,
    vatPct: price.vat_pct,
    quantity: 1,
    otherText: "",
  };
}

/** The typed "iets anders" rows that hold text, as cart lines. */
export function otherLinesToCart(others: OtherLineDraft[]): MeerwerkCartLine[] {
  return others
    .filter((row) => row.text.trim())
    .map((row) => ({
      key: row.key,
      kind: "other" as const,
      id: null,
      label: row.text.trim(),
      unitPrice: null,
      vatPct: null,
      quantity: 1,
      otherText: row.text.trim(),
      note: row.note.trim(),
    }));
}

/** The `line_items` the create AND preview endpoints take. Exactly one
 *  of service / custom_price / custom_description per line. */
export function cartLineItemsPayload(lines: MeerwerkCartLine[]) {
  return lines.map((line) => {
    const note = line.note?.trim();
    const noteField = note ? { customer_note: note } : {};
    if (line.kind === "service") {
      return {
        service: Number(line.id),
        quantity: String(line.quantity),
        ...noteField,
      };
    }
    if (line.kind === "custom_price") {
      return {
        custom_price: Number(line.id),
        quantity: String(line.quantity),
        ...noteField,
      };
    }
    return {
      custom_description: line.otherText,
      quantity: "1",
      ...noteField,
    };
  });
}

/** The request title when nobody typed one: the first line, plus a
 *  count of the rest. */
export function derivedTitle(lines: MeerwerkCartLine[]): string {
  const names = lines.map((line) => line.label);
  if (names.length === 0) return "";
  const title = names.length === 1 ? names[0] : `${names[0]} +${names.length - 1}`;
  return title.slice(0, 255);
}

/** The request description when nobody typed one: one line per cart
 *  line, in the words the confirm list shows. */
export function derivedDescription(
  lines: MeerwerkCartLine[],
  otherPrefix: string,
): string {
  return lines
    .map((line) =>
      line.kind === "other"
        ? `${otherPrefix}: ${line.otherText}`
        : `${line.quantity} × ${line.label}`,
    )
    .join("\n");
}

/** Cent-exact line amounts from the customer's own price. `null` when
 *  the line has no price to multiply. */
export function lineAmounts(
  line: Pick<MeerwerkCartLine, "unitPrice" | "vatPct" | "quantity">,
): { subtotal: number; vat: number; total: number } | null {
  if (line.unitPrice === null) return null;
  const unit = Number(line.unitPrice);
  if (!Number.isFinite(unit)) return null;
  const vatPct = line.vatPct !== null ? Number(line.vatPct) : 0;
  const cents = (n: number) => Math.round(n * 100) / 100;
  const subtotal = cents(line.quantity * unit);
  const vat = cents(subtotal * ((Number.isFinite(vatPct) ? vatPct : 0) / 100));
  return { subtotal, vat, total: cents(subtotal + vat) };
}

/** The outcome sentence's three shapes (§D.5.2): everything agreed →
 *  straight to planning; a price first; or auto-start once priced. */
export type MeerwerkOutcomeKind = "instant" | "quote" | "auto_start";

/** The `common` key for an outcome sentence. The customer's and the
 *  provider's wording differ by who does what. */
export function outcomeKey(
  kind: MeerwerkOutcomeKind,
  audience: "customer" | "provider",
): string {
  const base = `meerwerk_flow.outcome_${kind}`;
  return audience === "provider" ? `${base}_provider` : base;
}
