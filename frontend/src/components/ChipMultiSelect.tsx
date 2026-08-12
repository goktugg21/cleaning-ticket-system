import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

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
  onOpenChange,
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
  /** Sprint 169 §1 — reports the open list's REAL bottom edge in
   *  viewport coordinates, so a containing dialog can grow to hold it.
   *  Called with `null` when the list closes.
   *
   *  Sprint 168 stopped the list being CLIPPED by portalling it out of
   *  the modal. That was a correct fix for clipping and the wrong
   *  answer to the question: the owner is looking at a short modal with
   *  a long list hanging out of its bottom over the page. The list has
   *  to be INSIDE the modal's box, which only the modal can arrange —
   *  so the picker reports where its list ends and lets it. */
  onOpenChange?: (listBottom: number | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const wrapRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  /** Where the portalled list is drawn. Null until it has been
   *  measured, which is why the list renders nothing before then. */
  const [rect, setRect] = useState<{
    left: number;
    top: number;
    width: number;
    flipped: boolean;
  } | null>(null);

  /**
   * Sprint 168 §4 — the list is PORTALLED to `document.body`.
   *
   * Inside the week/bulk modal it used to be cut off after about three
   * names. Measured, the clipping ancestor is
   * `.week-entry-modal { overflow-x: hidden }` — and a box with
   * `overflow-x: hidden` and `overflow-y: visible` computes its
   * overflow-y to `auto`, so the rule that stopped sideways scroll
   * quietly started clipping vertically too.
   *
   * Two ways out: make the modal tall enough that the open list fits,
   * or let the list escape. The second is what a native `<select>`
   * does, and it does not make an EMPTY modal tall — which is the
   * whole point of the Sprint 167 sizing. So the list is drawn at the
   * control's viewport rect, outside every ancestor's overflow, and
   * flips above the control when there is not room below.
   */
  useLayoutEffect(() => {
    // Deliberately does NOT clear `rect` on close: a synchronous
    // setState in an effect body is banned (CLAUDE.md), and a stale
    // rect costs nothing because the list renders only while `open`.
    // Re-opening re-measures in a LAYOUT effect, so the new position is
    // in place before the browser paints — no flash at the old spot.
    if (!open) return;
    const measure = () => {
      const control = wrapRef.current?.querySelector(
        ".chip-multiselect-control",
      );
      if (!control) return;
      const box = control.getBoundingClientRect();
      const below = window.innerHeight - box.bottom;
      // 232 = the list's own 220 max-height plus its border and the
      // 4px it sits off the control.
      const flipped = below < 232 && box.top > below;
      setRect({
        left: box.left,
        top: flipped ? box.top - 4 : box.bottom + 4,
        width: box.width,
        flipped,
      });
    };
    measure();
    // `true` for the capture phase: the modal body is itself a
    // scrolling box, and a scroll inside it does not bubble.
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [open]);

  /** Report the list's real bottom once it has been laid out. A second
   *  effect rather than folding it into the measure above: that one
   *  computes where the list WILL go, this one reads where it landed,
   *  and the difference matters when the list is shorter than its
   *  max-height. */
  useEffect(() => {
    if (!onOpenChange) return;
    if (!open || !rect) {
      onOpenChange(null);
      return;
    }
    const node = listRef.current;
    onOpenChange(node ? node.getBoundingClientRect().bottom : null);
    return () => onOpenChange(null);
  }, [open, rect, onOpenChange]);

  // Close on a click outside. Bound only while open, so the document
  // carries no listener for a control nobody is using. The LIST is
  // checked separately now that it is portalled — it is no longer a
  // descendant of the wrapper, so `wrapRef.contains` says false for a
  // click on an option and the list would close before the click
  // landed.
  useEffect(() => {
    if (!open) return;
    const onDocDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (wrapRef.current?.contains(target)) return;
      if (listRef.current?.contains(target)) return;
      setOpen(false);
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

      {open &&
        rect &&
        createPortal(
        <ul
          ref={listRef}
          className="chip-multiselect-list chip-multiselect-list-floating"
          role="listbox"
          aria-multiselectable="true"
          aria-label={placeholder}
          // Keyboard handling still belongs to the wrapper, and a
          // portalled node keeps React's tree for events — but a real
          // DOM keydown here would escape to the modal's window
          // listener, so Escape is handled on the list as well.
          onKeyDown={onKeyDown}
          style={{
            left: rect.left,
            width: rect.width,
            ...(rect.flipped
              ? { bottom: window.innerHeight - rect.top }
              : { top: rect.top }),
          }}
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
        </ul>,
          document.body,
        )}
    </div>
  );
}
