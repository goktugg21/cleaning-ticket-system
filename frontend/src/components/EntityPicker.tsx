/**
 * Sprint 154 — the ONE multi-select picker.
 *
 * Five surfaces in this sprint need the same interaction: "pick M things
 * out of a server collection that may have hundreds of rows". Assign
 * customers to buildings (§F, both directions), add customers/managers/
 * staff/contacts on the building detail page (§G.2), bulk-add buildings
 * on the customer buildings page (§G.1), and link at creation time on
 * both forms (§H). Writing that picker five times is how five copies
 * drift; this is the one.
 *
 * Presentation only — the caller owns the data and the selection, exactly
 * like `MultiSelectToolbar`, which this pairs with rather than replaces.
 *
 * Two rules it enforces on every caller for free:
 *
 *   * The list is BOUNDED (`BoundedList`), because it renders a SERVER
 *     collection and CLAUDE.md §8 forbids an unbounded one. A provider
 *     with three hundred buildings must not get three hundred rows.
 *   * The filter NEVER changes what is submitted. A row that is selected
 *     and then filtered out of view stays selected, and the count says
 *     so — the same contract `MultiSelectToolbar` documents. Hiding a
 *     selected row and silently dropping it would be the worst of both.
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { BoundedList } from "./BoundedList";

export interface EntityPickerOption {
  id: number;
  label: string;
  /** Optional second line — a city, an e-mail, a role. */
  sublabel?: string;
}

export function EntityPicker({
  options,
  selectedIds,
  onChange,
  disabled,
  emptyText,
  testIdPrefix,
  size = "md",
}: {
  options: EntityPickerOption[];
  selectedIds: number[];
  onChange: (next: number[]) => void;
  disabled?: boolean;
  emptyText: string;
  testIdPrefix: string;
  size?: "sm" | "md" | "lg";
}) {
  const { t } = useTranslation("common");
  const [filter, setFilter] = useState("");

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return options;
    return options.filter(
      (o) =>
        o.label.toLowerCase().includes(needle) ||
        (o.sublabel ?? "").toLowerCase().includes(needle),
    );
  }, [options, filter]);

  const toggle = (id: number) =>
    onChange(
      selectedIds.includes(id)
        ? selectedIds.filter((existing) => existing !== id)
        : [...selectedIds, id],
    );

  return (
    <div data-testid={`${testIdPrefix}-picker`}>
      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "center",
          marginBottom: 8,
          flexWrap: "wrap",
        }}
      >
        <input
          className="field-input"
          type="search"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder={t("multi_select.filter_placeholder")}
          disabled={disabled}
          data-testid={`${testIdPrefix}-filter`}
          style={{ flex: "1 1 200px", minWidth: 0 }}
        />
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={disabled || visible.length === 0}
          // Select-all covers the VISIBLE rows only, and the count below
          // says how many are selected in total — so "select all" picking
          // fewer than the whole collection never looks broken.
          onClick={() =>
            onChange([...new Set([...selectedIds, ...visible.map((o) => o.id)])])
          }
          data-testid={`${testIdPrefix}-select-all`}
        >
          {t("multi_select.select_all")}
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={disabled || selectedIds.length === 0}
          onClick={() => onChange([])}
          data-testid={`${testIdPrefix}-clear-all`}
        >
          {t("multi_select.clear_all")}
        </button>
        <span className="muted small" data-testid={`${testIdPrefix}-count`}>
          {t("multi_select.selected_count", { count: selectedIds.length })}
        </span>
      </div>

      <BoundedList
        size={size}
        count={visible.length}
        ariaLabel={emptyText}
        testIdPrefix={testIdPrefix}
        emptyState={
          <p className="muted small" style={{ padding: "10px 0", margin: 0 }}>
            {filter.trim() ? t("entity_picker.no_matches") : emptyText}
          </p>
        }
      >
        <ul className="entity-picker-list">
          {visible.map((option) => (
            <li key={option.id}>
              <label className="entity-picker-row">
                <input
                  type="checkbox"
                  checked={selectedIds.includes(option.id)}
                  onChange={() => toggle(option.id)}
                  disabled={disabled}
                  data-testid={`${testIdPrefix}-option-${option.id}`}
                />
                <span className="entity-picker-text">
                  <span className="entity-picker-label">{option.label}</span>
                  {option.sublabel && (
                    <span className="entity-picker-sublabel">
                      {option.sublabel}
                    </span>
                  )}
                </span>
              </label>
            </li>
          ))}
        </ul>
      </BoundedList>
    </div>
  );
}
