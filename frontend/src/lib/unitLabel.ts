/**
 * P-4 (Part A) — UNITS EVERYWHERE THEY ARE TRUE.
 *
 * A service is priced per hour, per m², per item, as a fixed price, or
 * per an operator's own unit ("pallet"). The cart used to show a bare
 * number beside a price; a person who does not know the catalog could
 * not tell 50 of what. Two words, from EXISTING `unit_type` data only:
 * the "per …" phrase for a chip and the short suffix for a quantity
 * box ("50 m²").
 */
import type { TFunction } from "i18next";

import type { ServiceUnitType } from "../api/types";

export interface LineUnit {
  type: ServiceUnitType;
  /** The operator's own unit word for OTHER; blank otherwise. */
  label: string;
}

/** "per hour" / "per m²" / "fixed price" / "per item" / "per pallet". */
export function unitPhrase(unit: LineUnit | undefined, t: TFunction): string {
  if (!unit) return "";
  switch (unit.type) {
    case "HOURS":
      return t("unit.per_hour");
    case "SQUARE_METERS":
      return t("unit.per_m2");
    case "FIXED":
      return t("unit.fixed");
    case "ITEM":
      return t("unit.per_item");
    case "OTHER":
      return unit.label.trim() ? t("unit.per_custom", { label: unit.label.trim() }) : "";
    default:
      return "";
  }
}

/** The short word after a quantity: "hours", "m²", "pcs", "pallet", or
 *  "×" for a fixed price (2 × a fixed job). */
export function unitSuffix(unit: LineUnit | undefined, t: TFunction): string {
  if (!unit) return "×";
  switch (unit.type) {
    case "HOURS":
      return t("unit.suffix_hours");
    case "SQUARE_METERS":
      return "m²";
    case "ITEM":
      return t("unit.suffix_items");
    case "OTHER":
      return unit.label.trim() || "×";
    default:
      return "×";
  }
}
