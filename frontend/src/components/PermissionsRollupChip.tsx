import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import type { CustomerUserBuildingAccess } from "../api/types";

/**
 * Sprint 29 Batch 29.7 — permissions transparency chip.
 *
 * Surfaces, in a single text pill, whether a given (user, customer)
 * pair uses the customer-default permission set or one or more
 * per-access overrides. Click → 29.2 deep-link onto the Permissions
 * page with `?focus_user=<userId>` so the user-access card is
 * scrolled into view.
 *
 * The chip is intentionally display-only — the override-management UX
 * (the drawer + per-key tri-state radios + sticky save bar) stays on
 * the Permissions page; this is a glance-level rollup that ships
 * everywhere a user appears in admin context (Permissions page card
 * header, Customer Users tab row, User detail Customer access row).
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
}

export function PermissionsRollupChip({
  customerId,
  userId,
  accesses,
  testId,
  className,
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
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <Link
      to={`/admin/customers/${customerId}/permissions?focus_user=${userId}`}
      className={classes}
      data-testid={testId ?? `permissions-rollup-chip-${userId}`}
      aria-label={ariaLabel}
    >
      {label}
    </Link>
  );
}

