import { useTranslation } from "react-i18next";

import type {
  CustomerAccessRole,
  CustomerCompanyPolicyAdmin,
} from "../../../../api/types";

import { resolvePanelValue } from "./effectiveResolver";
import {
  PERMISSION_GROUP_LABEL_KEY,
  permissionKeyLabelKey,
  type PermissionGroup,
  type PermissionKeyRow,
} from "./permissionKeyLabels";

/**
 * Sprint 130 — one summary chip per permission group, replacing the
 * per-key columns `PermissionsMatrix` used to render. Counts are
 * derived from the SAME `resolvePanelValue` resolution the removed
 * cells used (never reimplemented) — this component only tallies
 * `PanelResolution.granted` across a group's keys, it does not decide
 * grant/deny itself.
 *
 * Visual state carries a non-color signal alongside the color so the
 * summary reads without relying on hue:
 *   - "all"     -> filled solid chip, bold white text  (every key granted)
 *   - "partial" -> outlined amber chip, bold text      (some granted)
 *   - "none"    -> outlined faint chip, regular weight  (none granted)
 */
export type PermissionGroupChipState = "all" | "partial" | "none";

export interface PermissionGroupChipProps {
  group: PermissionGroup;
  rows: ReadonlyArray<PermissionKeyRow>;
  overrides: Record<string, boolean>;
  isActive: boolean;
  policy: CustomerCompanyPolicyAdmin | null;
  accessRole: CustomerAccessRole;
}

export function PermissionGroupChip({
  group,
  rows,
  overrides,
  isActive,
  policy,
  accessRole,
}: PermissionGroupChipProps) {
  const { t } = useTranslation("common");
  const groupLabel = t(PERMISSION_GROUP_LABEL_KEY[group]);

  const grantedLabels: string[] = [];
  for (const row of rows) {
    const resolution = resolvePanelValue({
      key: row.key,
      overrides,
      isActive,
      policy,
      accessRole,
    });
    if (resolution.granted) {
      grantedLabels.push(t(permissionKeyLabelKey(row.key)));
    }
  }

  const grantedCount = grantedLabels.length;
  const totalCount = rows.length;
  const state: PermissionGroupChipState =
    grantedCount === 0
      ? "none"
      : grantedCount === totalCount
        ? "all"
        : "partial";

  const title =
    grantedCount > 0
      ? grantedLabels.join(", ")
      : t("customer_permissions.matrix.group_chip_none_title");

  const ariaLabel = t("customer_permissions.matrix.group_chip_aria", {
    group: groupLabel,
    granted: grantedCount,
    total: totalCount,
  });

  return (
    <span
      className={`permission-group-chip permission-group-chip-${state}`}
      data-testid="permission-group-chip"
      data-permission-group={group}
      data-granted-count={grantedCount}
      data-total-count={totalCount}
      data-state={state}
      title={title}
      aria-label={ariaLabel}
    >
      <span className="permission-group-chip-label">{groupLabel}</span>
      <span className="permission-group-chip-count">
        {grantedCount}/{totalCount}
      </span>
    </span>
  );
}
