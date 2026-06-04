/**
 * UI-polish — shared customer access-role chip (CCA / CLM / CU).
 *
 * Reuses the RoleBadge calm-chip language (a small teal dot + the label
 * on a faint teal tint) so the Users list and both Employees directories
 * render the customer access role identically — instead of the old
 * `badge badge-normal` block. Customer access roles are always
 * customer-side, so the chip always uses the teal accent.
 *
 * The `data-access-role` attribute is preserved (CSS / e2e hook). A null
 * role renders the muted em-dash, matching the previous AccessRoleCell.
 */
import { useTranslation } from "react-i18next";

import type { CustomerAccessRole } from "../api/types";
import { accessRoleLabelKey } from "../lib/enumLabels";

export interface AccessRoleBadgeProps {
  accessRole: CustomerAccessRole | null | undefined;
  testId?: string;
}

export function AccessRoleBadge({ accessRole, testId }: AccessRoleBadgeProps) {
  const { t } = useTranslation("common");

  if (!accessRole) {
    return <span className="muted">—</span>;
  }

  return (
    <span
      className="role-badge role-badge-customer role-badge-compact"
      data-access-role={accessRole}
      data-testid={testId}
    >
      <span className="role-badge-dot" aria-hidden="true" />
      <span className="role-badge-text">
        <span className="role-badge-label">
          {t(accessRoleLabelKey(accessRole))}
        </span>
      </span>
    </span>
  );
}
