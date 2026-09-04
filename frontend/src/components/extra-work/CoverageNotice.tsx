/**
 * P-9 C4 — the coverage block inside the three money ceremonies (send
 * the price, start the work, approve on the customer's behalf). ONE
 * component; the comparison lives in `lib/extraWorkCoverage.ts`.
 *
 * Renders nothing when the price covers the request exactly — the calm
 * confirm P-8R built stays as it was. Otherwise an amber block that
 * says, in the reader's words, what is missing, what was added, and
 * which quantity differs; a missing line offers "Add a price for X"
 * when the caller can still add one (a DRAFT quote), which closes the
 * confirm and lands on that line's row.
 */
import { useTranslation } from "react-i18next";

import {
  coverageQuantity,
  type CoverageLine,
  type CoverageResult,
} from "../../lib/extraWorkCoverage";

export function CoverageNotice({
  coverage,
  onAddPrice,
}: {
  coverage: CoverageResult | null;
  /** When set, every missing line is a door onto its unpriced row. */
  onAddPrice?: (line: CoverageLine) => void;
}) {
  const { t } = useTranslation("extra_work");
  if (!coverage || coverage.exact) return null;
  const asked = coverage.covered.length + coverage.uncovered.length;
  const kinds = [
    coverage.uncovered.length > 0 ? "fewer" : null,
    coverage.extra.length > 0 ? "more" : null,
    coverage.quantityDiffs.length > 0 ? "quantity" : null,
  ].filter(Boolean);
  return (
    <div
      className="alert-warning"
      role="status"
      style={{ marginBottom: 12 }}
      data-testid="extra-work-coverage-notice"
      data-coverage={kinds.join(" ")}
    >
      {coverage.uncovered.length > 0 && (
        <div data-testid="extra-work-coverage-fewer">
          <p style={{ margin: 0, fontWeight: 600 }}>
            {t("detail.coverage_fewer", {
              count: asked,
              covered: coverage.covered.length,
            })}
          </p>
          <ul style={{ margin: "4px 0", paddingLeft: 18 }}>
            {coverage.uncovered.map((line) => (
              <li key={line.id} data-testid="extra-work-coverage-uncovered">
                {line.label}
              </li>
            ))}
          </ul>
          <p style={{ margin: 0 }}>
            {t(onAddPrice ? "detail.coverage_not_done_add" : "detail.coverage_not_done")}
          </p>
          {onAddPrice && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 6 }}>
              {coverage.uncovered.map((line) => (
                <button
                  key={line.id}
                  type="button"
                  className="link-button"
                  onClick={() => onAddPrice(line)}
                  data-testid={`extra-work-coverage-add-price-${line.id}`}
                >
                  {t("detail.coverage_add_price", { name: line.label })}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      {coverage.extra.length > 0 && (
        <p
          style={{ margin: coverage.uncovered.length > 0 ? "8px 0 0" : 0 }}
          data-testid="extra-work-coverage-more"
        >
          {t("detail.coverage_more", {
            count: coverage.extra.length,
            names: coverage.extra.map((line) => line.label).join(", "),
          })}
        </p>
      )}
      {coverage.quantityDiffs.length > 0 && (
        <ul
          style={{ margin: "8px 0 0", paddingLeft: 18 }}
          data-testid="extra-work-coverage-quantity"
        >
          {coverage.quantityDiffs.map((diff) => (
            <li key={diff.cart.id}>
              {t("detail.coverage_quantity", {
                name: diff.cart.label,
                asked: coverageQuantity(diff.asked),
                priced: coverageQuantity(diff.priced),
                unit: diff.cart.unit ?? "",
              }).replace(/\s+/g, " ").trim()}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
