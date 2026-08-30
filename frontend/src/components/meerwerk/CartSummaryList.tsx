/**
 * FE-2/FE-5 — the cart as the reader confirms it: one row per line,
 * "quantity × label", the note under it, the customer's own price or
 * "prijs volgt" at the end. Shared by the customer's confirm step and
 * the provider's create page.
 */
import { useTranslation } from "react-i18next";

import { formatMoney } from "../../lib/intl";
import { unitPhrase, unitSuffix } from "../../lib/unitLabel";
import { lineAmounts, type MeerwerkCartLine } from "./cart";

export function CartSummaryList({
  lines,
  showAmounts = false,
  testIdPrefix,
}: {
  lines: MeerwerkCartLine[];
  /** Provider surfaces show the line total, not only the unit price. */
  showAmounts?: boolean;
  testIdPrefix: string;
}) {
  const { t } = useTranslation("common");
  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {lines.map((line) => {
        const amounts = showAmounts ? lineAmounts(line) : null;
        return (
          <li
            key={line.key}
            className="wp-undated-row"
            data-testid={`${testIdPrefix}-confirm-line`}
            data-kind={line.kind}
          >
            <div className="wp-undated-row-main">
              {/* P-4 (Part A) — "50 m² × Ramen wassen", the unit repeated
                  where the reader confirms. A fixed price stays "2 ×". */}
              <span>
                {line.unit && line.unit.type !== "FIXED"
                  ? `${line.quantity} ${unitSuffix(line.unit, t)} × ${line.label}`
                  : `${line.quantity} × ${line.label}`}
                {line.unit && (
                  <span className="meerwerk-unit-chip" data-testid={`${testIdPrefix}-confirm-unit`}>
                    {unitPhrase(line.unit, t)}
                  </span>
                )}
              </span>
              {line.note && <span className="muted small">{line.note}</span>}
            </div>
            {line.unitPrice ? (
              amounts && line.quantity > 1 ? (
                <span style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
                  <span className="muted small">{formatMoney(line.unitPrice)}</span>
                  <span className="meerwerk-line-amount">
                    {formatMoney(amounts.subtotal)}
                  </span>
                </span>
              ) : (
                <span className="muted small">{formatMoney(line.unitPrice)}</span>
              )
            ) : (
              <span className="phase-badge phase-badge-action">
                {t("meerwerk_flow.price_follows")}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
