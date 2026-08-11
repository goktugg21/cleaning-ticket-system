import { useEffect, useRef, useState } from "react";

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
 *
 * ## Sprint 164 §4 — what it does now
 *
 * Sprint 163 shipped it opening only on the caret and closing after one
 * pick, which is wrong for a control whose whole purpose is choosing
 * SEVERAL things:
 *
 *  * clicking anywhere in the control opens the list, not just the arrow
 *  * it STAYS open after a selection, so chips accumulate pick by pick
 *  * Escape closes it, and so does a click outside
 *  * the list marks what is already chosen rather than hiding it, so the
 *    operator can see and un-pick without hunting for the chip
 *  * it is keyboard-reachable end to end: the control is focusable,
 *    arrows move through the list, Enter toggles, Escape closes
 *
 * A native `<select multiple>` was the obvious alternative and is not
 * used: it cannot show chips, its multi-select gesture (ctrl-click) is
 * the one users get wrong most often, and it looks nothing like the
 * reference. The listbox below is the accessible pattern for this.
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
  const [activeIndex, setActiveIndex] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Close on a click outside. Bound only while open, so the document
  // carries no listener for a control nobody is using.
  useEffect(() => {
    if (!open) return;
    const onDocDown = (event: MouseEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocDown);
    return () => document.removeEventListener("mousedown", onDocDown);
  }, [open]);

  const chosen = options.filter((option) => selectedIds.includes(option.id));

  if (options.length === 0) {
    return <p className="muted small">{emptyText}</p>;
  }

  const toggle = (id: number) =>
    onChange(
      selectedIds.includes(id)
        ? selectedIds.filter((value) => value !== id)
        : [...selectedIds, id],
    );

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      // Escape closes the INNERMOST thing. Without stopping propagation
      // it reached the dialog's own handler and closed the whole modal,
      // losing the grid — found by driving it, not by reading it.
      if (open) {
        event.stopPropagation();
        event.preventDefault();
      }
      setOpen(false);
      return;
    }
    if (!open && (event.key === "Enter" || event.key === " " || event.key === "ArrowDown")) {
      event.preventDefault();
      setOpen(true);
      return;
    }
    if (!open) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((i) => Math.min(options.length - 1, i + 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((i) => Math.max(0, i - 1));
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      const option = options[activeIndex];
      if (option) toggle(option.id);
    }
  };

  return (
    <div
      className="chip-multiselect"
      ref={wrapRef}
      onKeyDown={onKeyDown}
      data-testid={testIdPrefix}
    >
      {/* The whole control opens the list, not only the caret. */}
      <div
        className="chip-multiselect-control"
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={placeholder}
        tabIndex={disabled ? -1 : 0}
        onClick={() => !disabled && setOpen(true)}
        data-testid={`${testIdPrefix}-open`}
      >
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
              onClick={(event) => {
                // Without this the click bubbles to the control and
                // re-opens the list the operator just closed.
                event.stopPropagation();
                onChange(selectedIds.filter((id) => id !== option.id));
              }}
              data-testid={`${testIdPrefix}-remove-${option.id}`}
            >
              &times;
            </button>
          </span>
        ))}
        <span className="chip-multiselect-caret" aria-hidden="true">
          &#9662;
        </span>
      </div>

      {open && (
        <ul
          className="chip-multiselect-list"
          role="listbox"
          aria-multiselectable="true"
          aria-label={placeholder}
          data-testid={`${testIdPrefix}-list`}
        >
          {/* Chosen entries stay IN the list, marked. Hiding them would
              mean the only way to un-pick is to find the chip, and the
              list is where the operator is already looking. */}
          {options.map((option, index) => {
            const isSelected = selectedIds.includes(option.id);
            return (
              <li key={option.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  className={`chip-multiselect-option${
                    index === activeIndex ? " is-active" : ""
                  }${isSelected ? " is-selected" : ""}`}
                  disabled={disabled}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => toggle(option.id)}
                  data-testid={`${testIdPrefix}-option-${option.id}`}
                >
                  <span className="chip-multiselect-check" aria-hidden="true">
                    {isSelected ? "\u2713" : ""}
                  </span>
                  <span>{option.label}</span>
                  {option.sublabel && (
                    <span className="muted small">{option.sublabel}</span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
