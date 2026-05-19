/**
 * Sprint 28 Batch 15.1 — unified clickable table row.
 *
 * Today four patterns coexist:
 *   1. Whole-row clickable    (BuildingsAdmin, CustomersAdmin, …)
 *   2. Title-cell clickable   (ExtraWorkList, StaffRequests)
 *   3. Plain non-interactive  (CustomerBuildings, CustomerUsers, …)
 *   4. Bespoke onClick on tr  (Dashboard tickets)
 *
 * Going forward, pages use this component for #1 and pass
 * `inert=true` for #3. The `clickable-row` class is the successor
 * to `admin-row-clickable`; both are applied during the
 * transition so legacy tables still get pointer + focus styling.
 *
 * `to` and `onActivate` are mutually independent: prefer `to` for
 * navigation; use `onActivate` for in-place actions (modal open,
 * sheet expansion). When both are missing the row renders as
 * non-interactive, matching `inert=true`.
 */
import type { KeyboardEvent, MouseEvent, ReactNode } from "react";
import { useNavigate } from "react-router-dom";

export interface ClickableRowProps {
  to?: string;
  onActivate?: () => void;
  /** Render as a plain non-interactive row. Default false. */
  inert?: boolean;
  /** Additional CSS classes to merge with the base row classes. */
  className?: string;
  /** Pass-through aria-label for screen readers. */
  ariaLabel?: string;
  testId?: string;
  children: ReactNode;
}

export function ClickableRow({
  to,
  onActivate,
  inert = false,
  className,
  ariaLabel,
  testId,
  children,
}: ClickableRowProps) {
  const navigate = useNavigate();

  const interactive = !inert && (Boolean(to) || Boolean(onActivate));

  const handleActivate = () => {
    if (onActivate) {
      onActivate();
    } else if (to) {
      navigate(to);
    }
  };

  const handleClick = (event: MouseEvent<HTMLTableRowElement>) => {
    if (!interactive) return;
    // Allow nested links/buttons to keep their own behaviour by
    // checking whether the click came from one of them. Without
    // this, clicking an inline action button inside the row would
    // also trigger the row navigation.
    if (event.target instanceof HTMLElement) {
      const inner = event.target.closest("a,button,input,select,textarea,label");
      if (inner && inner !== event.currentTarget) {
        return;
      }
    }
    handleActivate();
  };

  const handleKey = (event: KeyboardEvent<HTMLTableRowElement>) => {
    if (!interactive) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      handleActivate();
    }
  };

  const classes = ["", className]
    .concat(interactive ? ["clickable-row", "admin-row-clickable"] : [])
    .filter(Boolean)
    .join(" ")
    .trim();

  return (
    <tr
      className={classes || undefined}
      role={interactive ? "link" : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-label={interactive ? ariaLabel : undefined}
      onClick={interactive ? handleClick : undefined}
      onKeyDown={interactive ? handleKey : undefined}
      data-testid={testId}
    >
      {children}
    </tr>
  );
}

