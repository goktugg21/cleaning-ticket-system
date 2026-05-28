import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import type {
  CustomerCompanyPolicyAdmin,
  CustomerUserBuildingAccess,
} from "../api/types";

/**
 * Sprint 29 Batch 29.7 — permissions transparency chip.
 *
 * Surfaces, in a single text pill, whether a given (user, customer)
 * pair uses the customer-default permission set or one or more
 * per-access overrides.
 *
 * Sprint 29 Batch 29.8.5 — the chip now supports two modes:
 *   1. Toggle mode (preferred) — when `onToggle` is provided, the
 *      chip renders as a <button> that opens an inline
 *      <PermissionsRollupSummary> panel next to it. This lets dad
 *      glance at WHO can do WHAT without leaving the page.
 *   2. Legacy link mode — when `onToggle` is NOT provided, the chip
 *      falls back to the original 29.2 deep-link behaviour so any
 *      call site not yet upgraded to the inline pattern keeps
 *      working.
 *
 * The locked 29.6 / 29.7 testid `permissions-rollup-chip-<userId>`
 * (or whatever override `testId` is passed) is preserved regardless
 * of mode.
 *
 * Counting rule: sum the keys of `permission_overrides` across every
 * access row for the (user, customer) pair. A user with three
 * building accesses, each with two overrides, shows "Custom (6)".
 * Same override key on different buildings is NOT deduped — they're
 * separate concrete deviations from the customer default.
 */
export interface PermissionsRollupChipProps {
  customerId: number;
  userId: number;
  accesses: CustomerUserBuildingAccess[];
  testId?: string;
  className?: string;
  /**
   * Sprint 29 Batch 29.8.5 — when present, the chip renders as a
   * toggle button instead of a deep-link <Link>. The parent owns the
   * expanded state and renders <PermissionsRollupSummary> alongside.
   */
  onToggle?: () => void;
  expanded?: boolean;
  /**
   * Optional — only used by the new toggle mode. Not consumed
   * directly by the chip itself; passing it here keeps the prop
   * surface consistent for callers that thread the same policy into
   * both the chip AND the summary panel.
   */
  policy?: CustomerCompanyPolicyAdmin;
}

export function PermissionsRollupChip({
  customerId,
  userId,
  accesses,
  testId,
  className,
  onToggle,
  expanded,
}: PermissionsRollupChipProps) {
  const { t } = useTranslation("common");

  const count = accesses.reduce(
    (sum, a) => sum + Object.keys(a.permission_overrides ?? {}).length,
    0,
  );

  const isCustom = count > 0;
  const label = isCustom
    ? t("permissions_rollup.custom", { count })
    : t("permissions_rollup.default");
  const ariaLabel = isCustom
    ? t("permissions_rollup.aria_custom", { count })
    : t("permissions_rollup.aria_default");

  const classes = [
    "permissions-rollup-chip",
    isCustom
      ? "permissions-rollup-chip-custom"
      : "permissions-rollup-chip-default",
    expanded ? "permissions-rollup-chip-expanded" : null,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const resolvedTestId = testId ?? `permissions-rollup-chip-${userId}`;

  if (onToggle) {
    return (
      <button
        type="button"
        onClick={onToggle}
        className={classes}
        data-testid={resolvedTestId}
        aria-label={ariaLabel}
        aria-expanded={expanded ?? false}
      >
        {label}
      </button>
    );
  }

  return (
    <Link
      to={`/admin/customers/${customerId}/permissions?focus_user=${userId}`}
      className={classes}
      data-testid={resolvedTestId}
      aria-label={ariaLabel}
    >
      {label}
    </Link>
  );
}

