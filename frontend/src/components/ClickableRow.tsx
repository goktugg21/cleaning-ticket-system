/**
 * Sprint 28 Batch 15.1 — unified clickable table row.
 *
 * P-13 D (O3, §D.22 rule 9) — the row semantics moved into
 * `lib/useRowLink.ts` (the ONE hook: inner-control guard, Enter/Space,
 * link role); this component is its `<tr>` packaging. Rows are links
 * everywhere: every list/table row whose object has a page uses this
 * (or, where a `<tr>` is impossible, the hook directly), the name
 * stays a real link inside for middle-click, and the row's buttons
 * stop the click via the shared inner-control selector.
 *
 * `to` and `onActivate` are mutually independent: prefer `to` for
 * navigation; use `onActivate` for in-place actions (modal open,
 * sheet expansion). When both are missing the row renders as
 * non-interactive, matching `inert=true`.
 */
import type { ReactNode } from "react";

import { useRowLink } from "../lib/useRowLink";

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
  /** Optional `data-role` attribute on the row (some listings/e2e key on it). */
  dataRole?: string;
  /** Extra `data-*` attributes (P-13 — the due row's `data-ready`,
   *  highlight markers). Keys WITHOUT the `data-` prefix. */
  dataAttrs?: Record<string, string | number | boolean | undefined>;
  children: ReactNode;
}

export function ClickableRow({
  to,
  onActivate,
  inert = false,
  className,
  ariaLabel,
  testId,
  dataRole,
  dataAttrs,
  children,
}: ClickableRowProps) {
  const { interactive, rowProps } = useRowLink({
    to,
    onActivate,
    inert,
    ariaLabel,
  });

  const classes = ["", className]
    .concat(interactive ? ["clickable-row", "admin-row-clickable"] : [])
    .filter(Boolean)
    .join(" ")
    .trim();

  const extra: Record<string, string | number | boolean> = {};
  if (dataAttrs) {
    for (const [key, value] of Object.entries(dataAttrs)) {
      if (value !== undefined) extra[`data-${key}`] = value;
    }
  }

  return (
    <tr
      className={classes || undefined}
      data-testid={testId}
      data-role={dataRole}
      {...extra}
      {...rowProps}
    >
      {children}
    </tr>
  );
}
