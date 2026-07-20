// #108 Part D — shared toolbar for long multi-select checkbox lists:
// Select all / Clear all actions + an "N geselecteerd" count, with an
// optional filter input for lists that can realistically exceed ~15
// rows (buildings, services). Selection state stays with the caller —
// this component is presentation only, and the filter must never
// change what is submitted (hidden-but-selected rows stay selected).
// Pair with the .multi-select-list scroll container class.
import { useTranslation } from "react-i18next";

export function MultiSelectToolbar({
  selectedCount,
  onSelectAll,
  onClearAll,
  disabled,
  filterValue,
  onFilterChange,
  testIdPrefix,
}: {
  selectedCount: number;
  onSelectAll: () => void;
  onClearAll: () => void;
  disabled?: boolean;
  // Both filter props present -> the filter input renders.
  filterValue?: string;
  onFilterChange?: (value: string) => void;
  testIdPrefix: string;
}) {
  const { t } = useTranslation("common");
  return (
    <div
      className="multi-select-toolbar"
      data-testid={`${testIdPrefix}-toolbar`}
    >
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        onClick={onSelectAll}
        disabled={disabled}
        data-testid={`${testIdPrefix}-select-all`}
      >
        {t("multi_select.select_all")}
      </button>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        onClick={onClearAll}
        disabled={disabled}
        data-testid={`${testIdPrefix}-clear-all`}
      >
        {t("multi_select.clear_all")}
      </button>
      <span
        className="multi-select-count"
        data-testid={`${testIdPrefix}-count`}
      >
        {t("multi_select.selected_count", { count: selectedCount })}
      </span>
      {onFilterChange !== undefined && (
        <input
          className="field-input multi-select-filter"
          type="search"
          value={filterValue ?? ""}
          onChange={(event) => onFilterChange(event.target.value)}
          placeholder={t("multi_select.filter_placeholder")}
          disabled={disabled}
          data-testid={`${testIdPrefix}-filter`}
        />
      )}
    </div>
  );
}
