/**
 * Sprint 28 Batch 15.1 — shared role badge.
 *
 * The single most-requested visual fix from the screenshots: the
 * Users page rendered every role identically, so an operator couldn't
 * see at a glance that "Company admin" (provider) and "Customer
 * user" (customer side) belong to different worlds. This component
 * splits the visual on side:
 *
 *   PROVIDER side (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER / STAFF)
 *     → shell-green badge with a small "PROVIDER" caption
 *   CUSTOMER side (CUSTOMER_USER)
 *     → teal-mint badge with a small "CUSTOMER" caption
 *
 * The component also exists in a `compact` form for table cells (no
 * side caption, just colored chip).
 *
 * Tests:
 *   - The Users page Playwright spec only asserts on rendered text,
 *     not on classes, so the visual change is safe.
 */
import { useTranslation } from "react-i18next";
import type { Role } from "../api/types";
import { isCustomerRole, isProviderRole, roleLabelKey } from "../lib/enumLabels";

export interface RoleBadgeProps {
  role: Role | null | undefined;
  /** Compact form (chip only, no caption). Default false. */
  compact?: boolean;
  testId?: string;
}

export function RoleBadge({ role, compact = false, testId }: RoleBadgeProps) {
  const { t } = useTranslation("common");

  if (!role) {
    return (
      <span className="role-badge role-badge-fallback" data-testid={testId}>
        {t("roles.fallback")}
      </span>
    );
  }

  const isProvider = isProviderRole(role);
  const isCustomer = isCustomerRole(role);
  const sideClass = isProvider
    ? "role-badge-provider"
    : isCustomer
    ? "role-badge-customer"
    : "role-badge-fallback";
  const sideCaptionKey = isProvider
    ? "role_side.provider"
    : isCustomer
    ? "role_side.customer"
    : "role_side.fallback";

  return (
    <span
      className={`role-badge ${sideClass}${compact ? " role-badge-compact" : ""}`}
      data-testid={testId}
    >
      <span className="role-badge-label">{t(roleLabelKey(role))}</span>
      {!compact && (
        <span className="role-badge-side">{t(sideCaptionKey)}</span>
      )}
    </span>
  );
}

