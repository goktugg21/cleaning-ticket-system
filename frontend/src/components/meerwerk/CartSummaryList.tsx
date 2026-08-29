/**
 * FE-2/FE-5 — the cart as the reader confirms it: one row per line,
 * "quantity × label", the note under it, the customer's own price or
 * "prijs volgt" at the end. Shared by the customer's confirm step and
 * the provider's create page.
 */
import { useTranslation } from "react-i18next";

import { formatMoney } from "../../lib/intl";
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
              <span>{`${line.quantity} × ${line.label}`}</span>
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
