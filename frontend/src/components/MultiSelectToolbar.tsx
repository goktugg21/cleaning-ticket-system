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
  actionLabel,
  onAction,
  actionDestructive,
  testIdPrefix,
}: {
  selectedCount: number;
  onSelectAll: () => void;
  onClearAll: () => void;
  disabled?: boolean;
  // Both filter props present -> the filter input renders.
  filterValue?: string;
  onFilterChange?: (value: string) => void;
  // Sprint 137 item 7 — optional single action for the current
  // selection (the iOS-style list edit mode). Both props present ->
  // the action button renders, disabled while nothing is selected.
  // The LABEL is the caller's, deliberately: the same interaction
  // archives on the pricing lists and hard-deletes on the catalog
  // lists, and the button must say which one it actually does.
  actionLabel?: string;
  onAction?: () => void;
  actionDestructive?: boolean;
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
      {actionLabel !== undefined && onAction !== undefined && (
        <button
          type="button"
          className={
            actionDestructive
              ? "btn btn-danger btn-sm"
              : "btn btn-secondary btn-sm"
          }
          onClick={onAction}
          disabled={disabled || selectedCount === 0}
          data-testid={`${testIdPrefix}-action`}
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}
