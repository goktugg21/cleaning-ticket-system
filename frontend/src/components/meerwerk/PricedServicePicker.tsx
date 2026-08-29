/**
 * FE-5 — the priced-service picker, shared by the customer's guided
 * flow and the provider's create page.
 *
 * What it offers is the customer's OWN agreed prices and custom prices
 * (SoT §5.7 — the two endpoints only ever answer customer-specific
 * rows); a tick puts a line in the cart, a quantity sits beside a
 * ticked line, the price stands at the end of the row. The list is
 * bounded (a real customer has hundreds of rows), searchable once it
 * is long enough to need it, and — when the customer files prices in
 * folders — filterable by folder with one row of chips. The folder is
 * a FILTER here, never a question the form asks.
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type {
  CustomerCustomPrice,
  CustomerPriceFolder,
  CustomerServicePrice,
} from "../../api/types";
import { formatMoney } from "../../lib/intl";
import { BoundedList } from "../BoundedList";
import {
  customPriceLine,
  lineAmounts,
  serviceLine,
  type MeerwerkCartLine,
} from "./cart";

/** Rows above which the search box appears. */
const SEARCH_THRESHOLD = 8;

interface PickerRow {
  line: MeerwerkCartLine;
  folder: number | null;
  testId: string;
}

export function PricedServicePicker({
  prices,
  customPrices,
  folders = [],
  cart,
  onToggle,
  onQuantity,
  showAmounts = false,
  emptyLabel,
  testIdPrefix,
}: {
  prices: CustomerServicePrice[];
  customPrices: CustomerCustomPrice[];
  /** The customer's active folders; chips render only for folders
   *  that actually hold an offered row. */
  folders?: CustomerPriceFolder[];
  cart: MeerwerkCartLine[];
  onToggle: (line: MeerwerkCartLine) => void;
  onQuantity: (key: string, quantity: number) => void;
  /** Provider surfaces show the line total beside the unit price. */
  showAmounts?: boolean;
  /** Shown when the customer has no priced rows at all. */
  emptyLabel: string;
  testIdPrefix: string;
}) {
  const { t } = useTranslation("common");
  const [query, setQuery] = useState("");
  const [folderFilter, setFolderFilter] = useState<number | "all">("all");

  const rows = useMemo((): PickerRow[] => {
    const out: PickerRow[] = prices.map((price) => ({
      line: serviceLine(price),
      folder: price.folder,
      testId: `${testIdPrefix}-service-${price.service}`,
    }));
    for (const price of customPrices) {
      out.push({
        line: customPriceLine(price),
        folder: price.folder,
        testId: `${testIdPrefix}-custom-price-${price.id}`,
      });
    }
    return out;
  }, [prices, customPrices, testIdPrefix]);

  const folderChips = useMemo(
    () =>
      folders.filter((folder) => rows.some((row) => row.folder === folder.id)),
    [folders, rows],
  );
  // A filter pointing at a folder that no longer has rows (customer
  // switched) collapses to "all" at the point of use, never in an
  // effect.
  const activeFolder =
    folderFilter !== "all" && folderChips.some((f) => f.id === folderFilter)
      ? folderFilter
      : "all";

  const needle = query.trim().toLowerCase();
  const visible = rows.filter(
    (row) =>
      (activeFolder === "all" || row.folder === activeFolder) &&
      (!needle || row.line.label.toLowerCase().includes(needle)),
  );

  if (rows.length === 0) {
    return (
      <p className="muted small" data-testid={`${testIdPrefix}-picker-empty`}>
        {emptyLabel}
      </p>
    );
  }

  return (
    <div data-testid={`${testIdPrefix}-picker`}>
      {folderChips.length > 0 && (
        <div
          className="meerwerk-filter-chips"
          role="group"
          aria-label={t("meerwerk_cart.filter_label")}
          data-testid={`${testIdPrefix}-folder-chips`}
        >
          <button
            type="button"
            className={
              activeFolder === "all" ? "btn btn-primary btn-sm" : "btn btn-secondary btn-sm"
            }
            aria-pressed={activeFolder === "all"}
            onClick={() => setFolderFilter("all")}
          >
            {t("meerwerk_cart.filter_all")}
          </button>
          {folderChips.map((folder) => (
            <button
              key={folder.id}
              type="button"
              className={
                activeFolder === folder.id
                  ? "btn btn-primary btn-sm"
                  : "btn btn-secondary btn-sm"
              }
              aria-pressed={activeFolder === folder.id}
              onClick={() => setFolderFilter(folder.id)}
              data-testid={`${testIdPrefix}-folder-chip-${folder.id}`}
            >
              {folder.name}
            </button>
          ))}
        </div>
      )}
      {rows.length > SEARCH_THRESHOLD && (
        <input
          type="search"
          className="field-input meerwerk-picker-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t("meerwerk_cart.search_placeholder")}
          aria-label={t("meerwerk_cart.search_placeholder")}
          data-testid={`${testIdPrefix}-picker-search`}
        />
      )}
      <BoundedList
        size="lg"
        count={visible.length}
        ariaLabel={t("meerwerk_flow.q_what")}
        testIdPrefix={`${testIdPrefix}-picker-list`}
        emptyState={
          <p className="muted small">{t("meerwerk_cart.no_match")}</p>
        }
      >
        <ul
          style={{ listStyle: "none", margin: 0, padding: 0 }}
          data-testid={`${testIdPrefix}-services`}
        >
          {visible.map((row) => {
            const inCart = cart.find((line) => line.key === row.line.key);
            const amounts =
              showAmounts && inCart ? lineAmounts(inCart) : null;
            return (
              <li key={row.line.key} className="wp-undated-row">
                <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={Boolean(inCart)}
                    onChange={() => onToggle(row.line)}
                    data-testid={row.testId}
                  />
                  <span>{row.line.label}</span>
                </label>
                <span style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  {inCart && (
                    <input
                      type="number"
                      min={1}
                      value={inCart.quantity}
                      onChange={(event) =>
                        onQuantity(inCart.key, Number(event.target.value) || 1)
                      }
                      style={{ width: 64 }}
                      className="field-input"
                      aria-label={t("meerwerk_flow.quantity")}
                    />
                  )}
                  <span className="muted small">
                    {formatMoney(row.line.unitPrice ?? "0")}
                  </span>
                  {amounts && inCart && inCart.quantity > 1 && (
                    <span className="meerwerk-line-amount">
                      {formatMoney(amounts.subtotal)}
                    </span>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      </BoundedList>
    </div>
  );
}
