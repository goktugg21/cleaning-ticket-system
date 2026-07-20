// Shared Extra Work invoice-row component (P0-1 foundation).
//
// Single presentational <tr> consumed by the three downstream screens:
//   * Create / cart view (lineKind="cart")
//   * Extra Work detail pricing table (lineKind="pricing")
//   * Proposal builder / detail (lineKind="proposal")
//
// Column model (always renders in the same order, desktop = table row):
//   Service | Source | Qty | Unit | Unit price | VAT % | Subtotal | VAT | Total | Actions
//
// Source-column reconciliation rule (the entire reason this component
// exists — keeps the labelling logic in one place so the three screens
// cannot drift):
//
//   * "CONTRACT"        -> "Contract price"           (any line kind)
//   * "NEEDS_PROPOSAL"  -> "Custom / needs proposal"  (cart only — backend
//                          never emits NEEDS_PROPOSAL for proposal/pricing)
//   * "CUSTOM" + the line carries a non-null OWN unit_price
//                       -> "Agreed price"             (priced custom line)
//   * "CUSTOM" + no own unit_price
//                       -> "Custom / needs proposal"
//
// "Own unit_price" here means the line's own persisted amount, NOT
// `contract_unit_price`. For ProposalLine and ExtraWorkPricingLineItem
// the OWN unit_price is the operator-typed snapshot; for cart lines
// (ExtraWorkRequestItem) there is no own unit_price — the cart kind
// never produces "CUSTOM", so this branch is unreachable for cart lines
// and the per-kind narrowing below enforces it.
//
// The component is purely presentational: `editable` is a render hint,
// not a permission check. Backend per-record `actions` decide what the
// caller is ALLOWED to do; this prop only decides what the caller wants
// to RENDER. Do not bake role/permission logic into this file.
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type {
  ExtraWorkPricingLineItem,
  ExtraWorkRequestItem,
  ExtraWorkUnitType,
  PriceSource,
  ProposalLine,
  ServiceUnitType,
} from "../api/types";
import { formatMoney, formatNumber } from "../lib/intl";

// ExtraWorkUnitType and ServiceUnitType share storage values; one i18n
// map covers both (matches the inline map in ExtraWorkDetailPage that
// the next task will collapse onto this constant).
const UNIT_TYPE_I18N_KEY: Record<ExtraWorkUnitType | ServiceUnitType, string> =
  {
    HOURS: "unit_type.hours",
    SQUARE_METERS: "unit_type.square_meters",
    FIXED: "unit_type.fixed",
    ITEM: "unit_type.item",
    OTHER: "unit_type.other",
  };

// Shared presentational hints accepted by every variant. `rowTestId`
// overrides the default `<tr data-testid="invoice-line-row">` so a
// consumer with a legacy locked testid (e.g. the EW detail screen's
// `extra-work-detail-line-item-row`) can keep its Playwright contract.
// `subLabel` renders as additional content inside the Service cell,
// below the main label — used for per-line meta (cart: requested date
// + customer note; pricing: customer-visible / internal cost notes).
// Both are pure render hints; no role/permission logic lives here.
interface InvoiceLineRowSharedProps {
  editable?: boolean;
  onEdit?: () => void;
  onRemove?: () => void;
  rowTestId?: string;
  subLabel?: ReactNode;
}

export type InvoiceLineRowProps =
  | ({
      lineKind: "cart";
      line: ExtraWorkRequestItem;
    } & InvoiceLineRowSharedProps)
  | ({
      lineKind: "proposal";
      line: ProposalLine;
    } & InvoiceLineRowSharedProps)
  | ({
      lineKind: "pricing";
      line: ExtraWorkPricingLineItem;
    } & InvoiceLineRowSharedProps);

interface NormalizedLine {
  // Service / description column display.
  label: string;
  // Quantity + unit.
  quantity: string;
  unitType: ExtraWorkUnitType | ServiceUnitType;
  // #108 Part B — operator-supplied unit name (proposal lines entered
  // via "Custom…"); when set it replaces the enum unit label.
  customUnitLabel?: string;
  // Money columns. Each may be null when the line shape doesn't carry
  // that amount (e.g. cart lines have no own unit_price/totals).
  unitPrice: string | null;
  vatPct: string | null;
  subtotal: string | null;
  vatAmount: string | null;
  total: string | null;
  // Pricing source as emitted by the backend, plus the snapshot bit
  // the reconciliation rule needs: does the line carry an OWN amount?
  priceSource: PriceSource;
  hasOwnUnitPrice: boolean;
}

function normalize(props: InvoiceLineRowProps): NormalizedLine {
  switch (props.lineKind) {
    case "cart": {
      const line = props.line;
      // Cart lines have no own price snapshot. The Unit Price column
      // mirrors the live-resolved contract price when the backend
      // labels this line CONTRACT, else "—".
      return {
        label: line.service_name || "—",
        quantity: line.quantity,
        unitType: line.unit_type,
        unitPrice: line.contract_unit_price,
        vatPct: line.contract_vat_pct,
        subtotal: null,
        vatAmount: null,
        total: null,
        priceSource: line.price_source,
        // Cart lines never carry their OWN unit_price — pre-pricing by
        // construction. The reconciliation rule's "agreed price" branch
        // therefore never fires for cart kind (and price_source is
        // strictly CONTRACT | NEEDS_PROPOSAL for cart anyway).
        hasOwnUnitPrice: false,
      };
    }
    case "proposal": {
      const line = props.line;
      // Proposal lines: own unit_price is the operator-typed snapshot.
      // service_name is null for ad-hoc lines; fall back to description.
      const label = (line.service_name && line.service_name.trim())
        ? line.service_name
        : line.description || "—";
      return {
        label,
        quantity: line.quantity,
        unitType: line.unit_type,
        customUnitLabel: line.custom_unit_label?.trim() || undefined,
        unitPrice: line.unit_price,
        vatPct: line.vat_pct,
        subtotal: line.line_subtotal,
        vatAmount: line.line_vat,
        total: line.line_total,
        priceSource: line.price_source,
        hasOwnUnitPrice: isPositiveDecimalString(line.unit_price),
      };
    }
    case "pricing": {
      const line = props.line;
      return {
        label: line.description || "—",
        quantity: line.quantity,
        unitType: line.unit_type,
        unitPrice: line.unit_price,
        vatPct: line.vat_rate,
        subtotal: line.subtotal,
        vatAmount: line.vat_amount,
        total: line.total,
        priceSource: line.price_source,
        hasOwnUnitPrice: isPositiveDecimalString(line.unit_price),
      };
    }
  }
}

// "Has a real stored amount" — true when the decimal string parses to
// a strictly positive number. Zero or empty counts as no stored amount
// (the operator hasn't priced this line yet).
function isPositiveDecimalString(value: string | null | undefined): boolean {
  if (value == null) return false;
  const n = Number.parseFloat(value);
  return Number.isFinite(n) && n > 0;
}

function sourceLabelKey(
  priceSource: PriceSource,
  hasOwnUnitPrice: boolean,
): string {
  // CONTRACT always wins.
  if (priceSource === "CONTRACT") {
    return "invoice_row.source.contract_price";
  }
  // NEEDS_PROPOSAL — only emitted by cart lines; defend against backend
  // ever returning it for another kind by treating it uniformly.
  if (priceSource === "NEEDS_PROPOSAL") {
    return "invoice_row.source.needs_proposal";
  }
  // CUSTOM — branch on whether a real amount is stored.
  // Cart lines never reach this branch (backend doesn't emit CUSTOM
  // for cart kind); the per-kind narrowing in normalize() keeps
  // hasOwnUnitPrice=false for cart, so we'd fall through to
  // "needs proposal" if a future backend ever did. That's fine.
  // For proposal/pricing kinds the operator-typed snapshot decides:
  if (hasOwnUnitPrice) {
    return "invoice_row.source.agreed_price";
  }
  return "invoice_row.source.needs_proposal";
}

export function InvoiceLineRow(props: InvoiceLineRowProps) {
  const { t } = useTranslation("extra_work");
  const normalized = normalize(props);
  const editable = props.editable === true;

  const unitTypeLabel =
    normalized.customUnitLabel ??
    t(UNIT_TYPE_I18N_KEY[normalized.unitType] ?? "unit_type.other");
  const sourceLabel = t(
    sourceLabelKey(normalized.priceSource, normalized.hasOwnUnitPrice),
  );

  // VAT % is a number, not money. 21.00 must render as "21%", not
  // "€ 21,00". Keep two decimals (matches the backend's stored shape)
  // but trim trailing zeros where natural — formatNumber already does
  // that when min/max fraction digits are not set.
  const vatPctRender =
    normalized.vatPct == null
      ? "—"
      : `${formatNumber(normalized.vatPct, { maximumFractionDigits: 2 })}%`;

  return (
    <tr
      className="invoice-line-row"
      data-testid={props.rowTestId ?? "invoice-line-row"}
      data-line-kind={props.lineKind}
      data-price-source={normalized.priceSource}
    >
      <td className="invoice-line-row-service">
        <div className="invoice-line-row-service-label">{normalized.label}</div>
        {props.subLabel != null && (
          <div className="invoice-line-row-service-sub">{props.subLabel}</div>
        )}
      </td>
      <td className="invoice-line-row-source">
        <span
          className={`invoice-line-row-source-tag invoice-line-row-source-${normalized.priceSource.toLowerCase()}`}
          data-testid="invoice-line-row-source-tag"
        >
          {sourceLabel}
        </span>
      </td>
      <td className="invoice-line-row-num invoice-line-row-qty">
        {formatNumber(normalized.quantity, { maximumFractionDigits: 2 })}
      </td>
      <td className="invoice-line-row-unit">{unitTypeLabel}</td>
      <td className="invoice-line-row-num invoice-line-row-money">
        {formatMoney(normalized.unitPrice)}
      </td>
      <td className="invoice-line-row-num invoice-line-row-vat-pct">
        {vatPctRender}
      </td>
      <td className="invoice-line-row-num invoice-line-row-money">
        {formatMoney(normalized.subtotal)}
      </td>
      <td className="invoice-line-row-num invoice-line-row-money">
        {formatMoney(normalized.vatAmount)}
      </td>
      <td className="invoice-line-row-num invoice-line-row-money invoice-line-row-total">
        {formatMoney(normalized.total)}
      </td>
      <td className="invoice-line-row-actions">
        {editable && (
          <div className="invoice-line-row-actions-cluster">
            {props.onEdit && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={props.onEdit}
                data-testid="invoice-line-row-edit"
              >
                {t("invoice_row.action_edit")}
              </button>
            )}
            {props.onRemove && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={props.onRemove}
                data-testid="invoice-line-row-remove"
              >
                {t("invoice_row.action_remove")}
              </button>
            )}
          </div>
        )}
      </td>
    </tr>
  );
}

// Totals summary — a small companion component that renders ONE
// `<tr class="ew-pricing-totals-row">` matching the existing pricing
// table's totals styling. Kept presentational; the caller passes the
// already-rendered strings (or null for "—"). Mirrors the column
// layout above so it slots in under the line rows.
export interface InvoiceLineTotalsRowProps {
  subtotal: string | null;
  vatAmount: string | null;
  total: string | null;
  // True when the parent table renders an Actions column; the totals
  // row needs a matching empty <td> so the column count balances.
  hasActionsColumn?: boolean;
}

export function InvoiceLineTotalsRow({
  subtotal,
  vatAmount,
  total,
  hasActionsColumn = true,
}: InvoiceLineTotalsRowProps) {
  const { t } = useTranslation("extra_work");
  return (
    <tr
      className="invoice-line-totals-row ew-pricing-totals-row"
      data-testid="invoice-line-totals-row"
    >
      {/* Service / Source / Qty / Unit — empty cells spacing matches the
          column model of InvoiceLineRow above. */}
      <td colSpan={4} />
      <td className="invoice-line-row-num invoice-line-totals-label">
        {t("invoice_row.col_subtotal")}
      </td>
      <td className="invoice-line-row-num invoice-line-row-vat-pct" />
      <td className="invoice-line-row-num invoice-line-row-money">
        {formatMoney(subtotal)}
      </td>
      <td className="invoice-line-row-num invoice-line-row-money">
        {formatMoney(vatAmount)}
      </td>
      <td className="invoice-line-row-num invoice-line-row-money invoice-line-row-total">
        {formatMoney(total)}
      </td>
      {hasActionsColumn && <td />}
    </tr>
  );
}

// The canonical 10-column order parents render in <thead> lives in
// the sibling file `invoiceLineColumns.ts` (separated so the
// react-refresh/only-export-components rule stays clean — this file
// only exports React components).
