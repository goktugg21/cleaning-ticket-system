import { useMemo } from "react";
import { Check, ChevronUp, Pencil, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  CustomerCompanyPolicyAdmin,
  CustomerUserBuildingAccess,
} from "../../../../api/types";

import {
  panelReasonLabelKey,
  resolvePanelValue,
  type PanelResolution,
} from "./effectiveResolver";
import {
  PERMISSION_GROUP_LABEL_KEY,
  PERMISSION_KEY_ROWS,
  permissionKeyDescriptionKey,
  permissionKeyLabelKey,
  type PermissionGroup,
} from "./permissionKeyLabels";

/**
 * Sprint 29 Batch 29.8.5 — read-only inline panel that surfaces the
 * 16 effective customer permissions for a single
 * (user, building) access row.
 *
 * Toggled open from the "N custom permissions" pill on
 * `UserAccessCard`. The pill's onClick used to open the override
 * drawer directly; in 29.8.5 it toggles this panel, and the panel
 * carries an explicit "Edit overrides" button that opens the drawer.
 * This way the operator can see WHO can do WHAT at a glance without
 * dropping into the editor.
 *
 * Resolution is delegated to `resolvePanelValue` (defined in
 * `effectiveResolver.ts`) so the precedence tree stays single-source
 * with the drawer; the panel only owns the visual presentation.
 */
export interface AccessPermissionsPanelProps {
  access: CustomerUserBuildingAccess;
  policy: CustomerCompanyPolicyAdmin | null;
  onEditClick: () => void;
  onCollapse: () => void;
}

export function AccessPermissionsPanel({
  access,
  policy,
  onEditClick,
  onCollapse,
}: AccessPermissionsPanelProps) {
  const { t } = useTranslation("common");

  const groupedRows = useMemo(() => {
    const grouped: Record<PermissionGroup, typeof PERMISSION_KEY_ROWS> = {
      tickets: [],
      extra_work: [],
      users: [],
    } as unknown as Record<PermissionGroup, typeof PERMISSION_KEY_ROWS>;
    // The unknown-cast above is a workaround for TS not letting us
    // initialise the record value as a mutable array of the readonly
    // tuple type. We immediately overwrite each entry below.
    (Object.keys(grouped) as PermissionGroup[]).forEach((g) => {
      grouped[g] = PERMISSION_KEY_ROWS.filter((r) => r.group === g);
    });
    return grouped;
  }, []);

  return (
    <section
      className="access-permissions-panel"
      data-testid={`access-permissions-panel-${access.id}`}
      aria-label={t("customer_permissions.access_panel.aria_label", {
        building: access.building_name,
      })}
    >
      <header className="access-permissions-panel-header">
        <div className="access-permissions-panel-title">
          {t("customer_permissions.access_panel.title", {
            building: access.building_name,
          })}
        </div>
        <div className="access-permissions-panel-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onEditClick}
            data-testid={`access-permissions-edit-${access.id}`}
          >
            <Pencil size={13} strokeWidth={2.2} aria-hidden="true" />
            <span style={{ marginLeft: 6 }}>
              {t("customer_permissions.access_panel.edit_button")}
            </span>
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={onCollapse}
            aria-label={t("customer_permissions.access_panel.collapse")}
          >
            <ChevronUp size={14} strokeWidth={2.2} aria-hidden="true" />
            <span style={{ marginLeft: 6 }}>
              {t("customer_permissions.access_panel.collapse")}
            </span>
          </button>
        </div>
      </header>

      {(["tickets", "extra_work", "users"] as const).map((group) => (
        <div key={group} className="access-permissions-group">
          <div className="access-permissions-group-title">
            {t(PERMISSION_GROUP_LABEL_KEY[group])}
          </div>
          <ul className="access-permissions-list">
            {groupedRows[group].map((row) => {
              const resolution: PanelResolution = resolvePanelValue({
                key: row.key,
                overrides: access.permission_overrides ?? {},
                isActive: access.is_active !== false,
                policy,
                accessRole: access.access_role,
              });
              return (
                <li
                  key={row.key}
                  className={`access-permission-row ${
                    resolution.granted ? "granted" : "denied"
                  }`}
                  data-testid={`access-permission-row-${access.id}-${row.key}`}
                  data-permission-key={row.key}
                  data-granted={resolution.granted ? "true" : "false"}
                  data-reason={resolution.reason}
                >
                  <span
                    className="access-permission-row-indicator"
                    aria-hidden="true"
                  >
                    {resolution.granted ? (
                      <Check size={14} strokeWidth={2.4} />
                    ) : (
                      <X size={14} strokeWidth={2.4} />
                    )}
                  </span>
                  <div className="access-permission-row-text">
                    <div className="access-permission-row-label">
                      {t(permissionKeyLabelKey(row.key))}
                    </div>
                    <div className="access-permission-row-description muted small">
                      {t(permissionKeyDescriptionKey(row.key))}
                    </div>
                  </div>
                  <span className="access-permission-row-reason muted small">
                    {t(panelReasonLabelKey(resolution.reason))}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </section>
  );
}

