// #108 Part D — shared toolbar for long multi-select checkbox lists:
// Select all / Clear all actions + an "N geselecteerd" count, with an
// optional filter input for lists that can realistically exceed ~15
// rows (buildings, services). Selection state stays with the caller —
// this component is presentation only, and the filter must never
// change what is submitted (hidden-but-selected rows stay selected).
// Pair with the .multi-select-list scroll container class.
import { useTranslation } from "react-i18next";

/**
 * Sprint 137 item 7 / Sprint 138 §1–§2 — one or more actions for the
 * current selection (the iOS-style list edit mode).
 *
 * The LABEL is always the caller's, deliberately: the same interaction
 * archives on the customer pricing lists, hard-deletes on the Units
 * list, and deactivates-or-deletes on the Services list depending on
 * whether the row is referenced. The button has to say which one it
 * actually does.
 *
 * Sprint 138 turned the single action into a list because the Services
 * list genuinely needs several (deactivate / activate / move to
 * category / delete) — rather than growing a second selection
 * primitive alongside this one.
 */
export interface MultiSelectAction {
  key: string;
  label: string;
  onClick: () => void;
  destructive?: boolean;
  /** Disabled for a reason the caller can explain in `title`. */
  disabled?: boolean;
  title?: string;
}

export function MultiSelectToolbar({
  selectedCount,
  onSelectAll,
  onClearAll,
  disabled,
  filterValue,
  onFilterChange,
  actions,
  countLabel,
  testIdPrefix,
}: {
  selectedCount: number;
  onSelectAll: () => void;
  onClearAll: () => void;
  disabled?: boolean;
  // Both filter props present -> the filter input renders.
  filterValue?: string;
  onFilterChange?: (value: string) => void;
  actions?: MultiSelectAction[];
  // Sprint 138 §3 — overrides the default "N geselecteerd" when the
  // caller needs to say what the count covers (e.g. "N of M active
  // rows", because archived price rows are not selectable at all).
  countLabel?: string;
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
        {countLabel ?? t("multi_select.selected_count", { count: selectedCount })}
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
      {(actions ?? []).map((action) => (
        <button
          key={action.key}
          type="button"
          className={
            action.destructive
              ? "btn btn-danger btn-sm"
              : "btn btn-secondary btn-sm"
          }
          onClick={action.onClick}
          disabled={
            disabled || selectedCount === 0 || Boolean(action.disabled)
          }
          title={action.title}
          data-testid={`${testIdPrefix}-action-${action.key}`}
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}
