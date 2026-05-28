import { Link } from "react-router-dom";
import { ChevronUp, Pencil } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { CustomerUserBuildingAccess } from "../api/types";
import { accessRoleLabelKey } from "../lib/enumLabels";

/**
 * Sprint 29 Batch 29.8.5 — inline summary that the
 * <PermissionsRollupChip> toggles in place of its old deep-link
 * navigation behaviour.
 *
 * One row per (user, customer, building) access. Each row exposes:
 *   - building name
 *   - effective sub-role (CUSTOMER_USER / LOCATION_MANAGER / COMPANY_ADMIN)
 *   - override count
 *   - an "Edit" link that opens the override drawer for that
 *     access via the parent-owned `onOpenOverrides` callback
 *
 * Footer carries:
 *   - "Open full editor" — 29.2 deep-link onto the Permissions page
 *     with ?focus_user=<userId>, preserving the existing 29.6 link
 *     contract on User Detail.
 *   - "Collapse" — closes the summary.
 *
 * Parent owns the data fetch (accesses + customer-name + per-row
 * drawer open). This component is pure presentation.
 */
export interface PermissionsRollupSummaryProps {
  userId: number;
  customerId: number;
  userLabel: string;
  customerLabel: string;
  accesses: CustomerUserBuildingAccess[];
  loading?: boolean;
  onOpenOverrides: (access: CustomerUserBuildingAccess) => void;
  onCollapse: () => void;
}

function overridesCountLabelKey(count: number): string {
  if (count === 0) return "permissions_rollup.summary_overrides_zero";
  if (count === 1) return "permissions_rollup.summary_overrides_one";
  return "permissions_rollup.summary_overrides_other";
}

export function PermissionsRollupSummary({
  userId,
  customerId,
  userLabel,
  customerLabel,
  accesses,
  loading,
  onOpenOverrides,
  onCollapse,
}: PermissionsRollupSummaryProps) {
  const { t } = useTranslation("common");

  return (
    <section
      className="permissions-rollup-summary"
      data-testid={`permissions-rollup-summary-${userId}-${customerId}`}
    >
      <header className="permissions-rollup-summary-header">
        <div className="permissions-rollup-summary-title">
          {t("permissions_rollup.summary_title", {
            user: userLabel,
            customer: customerLabel,
          })}
        </div>
      </header>

      {loading ? (
        <div className="permissions-rollup-summary-loading">
          {t("permissions_rollup.summary_loading")}
        </div>
      ) : accesses.length === 0 ? (
        <div className="permissions-rollup-summary-empty">
          {t("permissions_rollup.summary_empty")}
        </div>
      ) : (
        <ul className="permissions-rollup-summary-list">
          {accesses.map((access) => {
            const overrides = Object.keys(
              access.permission_overrides ?? {},
            ).length;
            return (
              <li
                key={access.id}
                className="permissions-rollup-summary-row"
                data-testid={`permissions-rollup-summary-row-${access.id}`}
              >
                <span className="permissions-rollup-summary-row-building">
                  {access.building_name}
                </span>
                <span className="permissions-rollup-summary-row-role">
                  {t(accessRoleLabelKey(access.access_role))}
                  {" · "}
                  {t(overridesCountLabelKey(overrides), { count: overrides })}
                </span>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm permissions-rollup-summary-row-edit"
                  onClick={() => onOpenOverrides(access)}
                  data-testid={`permissions-rollup-summary-edit-${access.id}`}
                >
                  <Pencil size={12} strokeWidth={2.2} aria-hidden="true" />
                  <span style={{ marginLeft: 4 }}>
                    {t("permissions_rollup.summary_edit_row")}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <footer className="permissions-rollup-summary-footer">
        <Link
          to={`/admin/customers/${customerId}/permissions?focus_user=${userId}`}
          className="link"
          data-testid={`permissions-rollup-summary-open-full-${userId}-${customerId}`}
        >
          {t("permissions_rollup.summary_open_full")}
        </Link>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onCollapse}
          data-testid={`permissions-rollup-summary-collapse-${userId}-${customerId}`}
        >
          <ChevronUp size={14} strokeWidth={2.2} aria-hidden="true" />
          <span style={{ marginLeft: 4 }}>
            {t("permissions_rollup.summary_collapse")}
          </span>
        </button>
      </footer>
    </section>
  );
}

