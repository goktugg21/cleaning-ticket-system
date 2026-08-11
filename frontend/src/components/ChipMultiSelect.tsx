import { useRef, useState } from "react";

/**
 * Sprint 163 §1 — a one-line multi-select: the chosen items sit in the
 * control as removable chips, and a dropdown adds more.
 *
 * Replaces `EntityPicker` at the top of the week-entry modal, where two
 * tall scrolling checkbox lists ate the upper half of the dialog and
 * pushed the grid — the thing the operator came for — below the fold.
 * The reference system uses this shape for both Workers and Buildings,
 * and it is the reason its modal fits four assignments and every
 * control without the page scrolling.
 *
 * `EntityPicker` is deliberately NOT changed: it is the right control
 * where a list is the point and there is room for it (the bulk-assign
 * dialogs, the permission editors). This is a second control for a
 * different constraint, not a replacement for that one.
 */
export function ChipMultiSelect({
  options,
  selectedIds,
  onChange,
  placeholder,
  removeLabel,
  emptyText,
  disabled,
  testIdPrefix,
}: {
  options: { id: number; label: string; sublabel?: string }[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  placeholder: string;
  /** Accessible name for a chip's remove control, given the label. */
  removeLabel: (label: string) => string;
  emptyText: string;
  disabled?: boolean;
  testIdPrefix: string;
}) {
  const [open, setOpen] = useState(false);
  const selectRef = useRef<HTMLSelectElement>(null);

  const chosen = options.filter((option) => selectedIds.includes(option.id));
  const available = options.filter(
    (option) => !selectedIds.includes(option.id),
  );

  if (options.length === 0) {
    return <p className="muted small">{emptyText}</p>;
  }

  return (
    <div className="chip-multiselect" data-testid={testIdPrefix}>
      <div className="chip-multiselect-control">
        {chosen.length === 0 && (
          <span className="chip-multiselect-placeholder">{placeholder}</span>
        )}
        {chosen.map((option) => (
          <span
            key={option.id}
            className="chip-multiselect-chip"
            data-testid={`${testIdPrefix}-chip-${option.id}`}
          >
            {option.label}
            <button
              type="button"
              className="chip-multiselect-remove"
              aria-label={removeLabel(option.label)}
              disabled={disabled}
              onClick={() =>
                onChange(selectedIds.filter((id) => id !== option.id))
              }
              data-testid={`${testIdPrefix}-remove-${option.id}`}
            >
              &times;
            </button>
          </span>
        ))}

        {/* The caret is the affordance; the select itself only appears
            once it is pressed. A select sitting permanently beside the
            chips reads as a second, competing control. */}
        {available.length > 0 && !open && (
          <button
            type="button"
            className="chip-multiselect-caret"
            aria-label={placeholder}
            disabled={disabled}
            onClick={() => {
              setOpen(true);
              // Focus lands on the select once React has rendered it.
              queueMicrotask(() => selectRef.current?.focus());
            }}
            data-testid={`${testIdPrefix}-open`}
          >
            &#9662;
          </button>
        )}

        {open && (
          <select
            ref={selectRef}
            className="chip-multiselect-select"
            defaultValue=""
            disabled={disabled}
            aria-label={placeholder}
            onChange={(event) => {
              if (event.target.value === "") return;
              onChange([...selectedIds, Number(event.target.value)]);
              setOpen(false);
            }}
            onBlur={() => setOpen(false)}
            data-testid={`${testIdPrefix}-select`}
          >
            <option value="">{placeholder}</option>
            {available.map((option) => (
              <option key={option.id} value={option.id}>
                {option.sublabel
                  ? `${option.label} — ${option.sublabel}`
                  : option.label}
              </option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}
