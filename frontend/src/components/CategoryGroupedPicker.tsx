// Sprint 139 §3 — the ONE category-grouped multi-select list.
//
// Sprint 138 §5 grouped the copy-from-defaults picker by
// ServiceCategory with a per-category select-all. The two bulk
// price-adjust modals (catalog defaults on ServicesAdminPage, contract
// prices on CustomerPricingPage) were still flat scrolling lists, so
// the same catalog was presented three different ways depending on
// which modal you opened. This component is that shape, extracted, so
// there is one implementation rather than three copies to keep in
// sync.
//
// The selection rule it enforces, consistently with every other
// multi-select list in this codebase: **a per-category select-all
// covers every row in that category, including rows the text filter is
// currently hiding.** The filter is display-only — "hidden-but-selected
// rows stay selected" — and a filter-narrowed select-all would quietly
// fail the owner's "select this whole category at once" ask. The group
// header always states the real total so that is never a surprise.
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { PickerGroup } from "../lib/pickerGroups";

export function CategoryGroupedPicker<T>({
  groups,
  getId,
  renderItem,
  selectedIds,
  onToggleItem,
  onToggleGroup,
  disabled,
  testIdPrefix,
}: {
  groups: PickerGroup<T>[];
  getId: (item: T) => number;
  renderItem: (item: T) => ReactNode;
  selectedIds: number[];
  onToggleItem: (id: number, checked: boolean) => void;
  onToggleGroup: (group: PickerGroup<T>, checked: boolean) => void;
  disabled?: boolean;
  testIdPrefix: string;
}) {
  const { t } = useTranslation("common");
  return (
    <div className="multi-select-list">
      {groups.map((group) => (
        <div key={group.key} className="copy-default-group">
          <div className="copy-default-group-header">
            <span className="copy-default-group-name">{group.name}</span>
            <span className="muted small">
              {group.visible.length === group.items.length
                ? t("customer_pricing.copy_group_count", {
                    count: group.items.length,
                  })
                : t("customer_pricing.copy_group_count_filtered", {
                    shown: group.visible.length,
                    count: group.items.length,
                  })}
            </span>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              data-testid={`${testIdPrefix}-group-select-all`}
              data-category-key={group.key}
              onClick={() => onToggleGroup(group, true)}
              disabled={disabled}
            >
              {t("customer_pricing.copy_group_select_all", {
                count: group.items.length,
              })}
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              data-testid={`${testIdPrefix}-group-clear`}
              data-category-key={group.key}
              onClick={() => onToggleGroup(group, false)}
              disabled={disabled}
            >
              {t("multi_select.clear_all")}
            </button>
          </div>
          {group.visible.map((item) => (
            <label key={getId(item)}>
              <input
                type="checkbox"
                className="checkbox-input"
                data-testid={`${testIdPrefix}-row`}
                data-row-id={getId(item)}
                checked={selectedIds.includes(getId(item))}
                onChange={(event) =>
                  onToggleItem(getId(item), event.target.checked)
                }
                disabled={disabled}
              />
              <span>{renderItem(item)}</span>
            </label>
          ))}
          {group.visible.length === 0 && (
            <div
              className="muted small"
              style={{ padding: "4px 0 8px 8px" }}
            >
              {t("customer_pricing.copy_group_all_filtered")}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
