/**
 * FE-6 (Addendum D §D.6 rule 3) — the overflow menu: ONE primary action
 * stays on the header, everything else folds behind "…".
 *
 * A button that opens a small list anchored to itself (rule 2: actions
 * appear where you clicked). Closes on a choice, on Escape, and on a
 * press outside. Items render in the order given; a `destructive`
 * item reads red.
 */
import { useEffect, useId, useRef, useState } from "react";
import { MoreHorizontal } from "lucide-react";

export interface OverflowMenuItem {
  key: string;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  destructive?: boolean;
  /** A11y state for a toggle item ("show archived"). */
  pressed?: boolean;
}

export function OverflowMenu({
  label,
  items,
  testIdPrefix,
}: {
  /** The button's accessible name ("More actions"). */
  label: string;
  items: OverflowMenuItem[];
  testIdPrefix: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (items.length === 0) return null;

  return (
    <div className="overflow-menu" ref={rootRef}>
      <button
        type="button"
        className="btn btn-secondary btn-sm overflow-menu-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={listId}
        aria-label={label}
        title={label}
        onClick={() => setOpen((current) => !current)}
        data-testid={`${testIdPrefix}-more`}
      >
        <MoreHorizontal size={16} strokeWidth={2.2} aria-hidden />
      </button>
      {open && (
        <div
          id={listId}
          role="menu"
          className="overflow-menu-list"
          data-testid={`${testIdPrefix}-more-menu`}
        >
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role="menuitem"
              className={`overflow-menu-item${item.destructive ? " destructive" : ""}`}
              aria-pressed={item.pressed}
              disabled={item.disabled}
              onClick={() => {
                setOpen(false);
                item.onClick();
              }}
              data-testid={`${testIdPrefix}-more-${item.key}`}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
