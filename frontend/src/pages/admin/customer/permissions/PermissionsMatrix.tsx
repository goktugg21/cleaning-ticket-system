import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Pencil, X as XIcon } from "lucide-react";

import type {
  CustomerAccessRole,
  CustomerBuildingMembership,
  CustomerCompanyPolicyAdmin,
  CustomerUserBuildingAccess,
  CustomerUserMembership,
} from "../../../../api/types";
import { accessRoleLabelKey } from "../../../../lib/enumLabels";

import {
  PERMISSION_GROUP_LABEL_KEY,
  PERMISSION_GROUPS,
  PERMISSION_KEY_ROWS,
  type PermissionGroup,
  type PermissionKeyRow,
} from "./permissionKeyLabels";
import { PermissionGroupChip } from "./PermissionGroupChip";
import { Toggle } from "../../../../components/Toggle";

/**
 * Sprint 31 Phase 6 — introduced as an Excel-style permission matrix;
 * Sprint 130 replaced the 17 per-key ✓/✗ columns with one summary
 * chip per permission group (it no longer renders a matrix — the
 * name is kept so the row/testid history below still lines up).
 *
 * Primary view of the per-user permission surface; REPLACES the
 * `UserAccessCard` + `AccessPermissionsPanel` flow. One <tr> per
 * `CustomerUserBuildingAccess` row (user × building × access_role).
 *
 *   User | Actions | Role | Tickets chip | Extra Work chip | Users chip | Documents chip
 *
 * Each chip is a `PermissionGroupChip`, whose granted/total count is
 * derived from the SAME `resolvePanelValue` resolution the old cells
 * used — NEVER by client-side permission truth. The full per-key
 * inherit/allow/deny detail still lives one click away in
 * `PermissionEditorModal`; the chip is a summary, not a
 * re-implementation.
 *
 * Locked testids relocated from `UserAccessCard`:
 *   - `customer-access-role-select` + `data-user-id` + `data-building-id`
 *   - `customer-access-active-toggle` + `data-user-id` + `data-building-id`
 *   - `customer-access-overrides-button` + `data-user-id` + `data-building-id`
 *     (this button opens the modal directly; no intermediate panel
 *     step)
 *
 * New testids introduced:
 *   - `permissions-matrix` on the section root
 *   - `permissions-matrix-row` on each <tr>
 *   - `permission-group-chip` + `data-permission-group` +
 *     `data-granted-count` + `data-total-count` + `data-state`
 *     (rendered by PermissionGroupChip; Sprint 130 replaces the
 *     retired `permissions-matrix-cell` per-key testid)
 *
 * Retired:
 *   - `access-permissions-panel-<id>` / `access-permissions-edit-<id>`
 *     (the panel is gone — the matrix shows the same info at a
 *     glance and the modal opens directly from the row)
 *   - `customer-access-badge` (per-building chip — folded into the
 *     row itself)
 *   - `permissions-matrix-cell` (Sprint 130 — one bubble per key no
 *     longer exists; see `permission-group-chip` above)
 */
export interface PermissionsMatrixProps {
  members: CustomerUserMembership[];
  accessByUserId: Record<number, CustomerUserBuildingAccess[]>;
  linkedBuildings: CustomerBuildingMembership[];
  policy: CustomerCompanyPolicyAdmin | null;
  meId: number | undefined;
  /** True when an immediate-save round-trip is in flight for this user. */
  isUserBusy: (userId: number) => boolean;
  onRoleChange: (
    membership: CustomerUserMembership,
    access: CustomerUserBuildingAccess,
    newRole: CustomerAccessRole,
  ) => void;
  onActiveToggle: (
    membership: CustomerUserMembership,
    access: CustomerUserBuildingAccess,
    nextActive: boolean,
  ) => void;
  onEditPermissions: (
    membership: CustomerUserMembership,
    access: CustomerUserBuildingAccess,
  ) => void;
  onRemoveAccess: (
    membership: CustomerUserMembership,
    access: CustomerUserBuildingAccess,
  ) => void;
  onAddBuilding: (
    membership: CustomerUserMembership,
    buildingId: number,
  ) => void;
}

interface FlatRow {
  membership: CustomerUserMembership;
  access: CustomerUserBuildingAccess;
}

export function PermissionsMatrix(props: PermissionsMatrixProps) {
  const { t } = useTranslation("common");

  // Flatten (membership, access) into one row per access. The matrix
  // is intentionally access-row-grained so a user with N buildings
  // gets N rows — that matches the resolver's per-access semantics
  // and avoids hiding per-building override variation behind a
  // collapsed "user" row.
  const flatRows = useMemo<FlatRow[]>(() => {
    const out: FlatRow[] = [];
    for (const membership of props.members) {
      const accesses = props.accessByUserId[membership.user_id] ?? [];
      for (const access of accesses) {
        out.push({ membership, access });
      }
    }
    return out;
  }, [props.members, props.accessByUserId]);

  const groupedKeys = useMemo(() => {
    const grouped: Record<PermissionGroup, PermissionKeyRow[]> = {
      tickets: [],
      extra_work: [],
      users: [],
      documents: [],
    };
    for (const row of PERMISSION_KEY_ROWS) grouped[row.group].push(row);
    return grouped;
  }, []);

  return (
    <div
      className="permissions-matrix"
      data-testid="permissions-matrix"
    >
      <div className="permissions-matrix-scroll">
        <table className="permissions-matrix-table">
          <thead>
            {/* Column order: User | Actions | Role | one chip column
                per PERMISSION_GROUPS entry. The group's label is
                already printed on the chip itself (`Tickets 4/6`), so
                these header cells carry no visible text — an
                `aria-label` (same pattern as the Actions column)
                keeps `scope="col"` table semantics without doubling
                the label up on screen. */}
            <tr>
              <th className="permissions-matrix-cell-user">
                {t("customer_permissions.matrix.col_user")}
              </th>
              <th
                className="permissions-matrix-cell-actions"
                aria-label={t("customer_permissions.matrix.col_actions")}
              />
              <th className="permissions-matrix-cell-role">
                {t("customer_permissions.matrix.col_role")}
              </th>
              {PERMISSION_GROUPS.map((group) => (
                <th
                  key={group}
                  className="permissions-matrix-group-header"
                  scope="col"
                  aria-label={t(PERMISSION_GROUP_LABEL_KEY[group])}
                />
              ))}
            </tr>
          </thead>
          <tbody>
            {flatRows.length === 0 ? (
              <tr>
                <td
                  colSpan={3 + PERMISSION_GROUPS.length}
                  className="permissions-matrix-empty"
                  data-testid="permissions-matrix-empty"
                >
                  {t("customer_permissions.matrix.empty")}
                </td>
              </tr>
            ) : (
              flatRows.map(({ membership, access }) => (
                <MatrixRow
                  key={`${membership.user_id}-${access.building_id}`}
                  membership={membership}
                  access={access}
                  policy={props.policy}
                  groupedKeys={groupedKeys}
                  isSelf={props.meId === membership.user_id}
                  busy={props.isUserBusy(membership.user_id)}
                  onRoleChange={(newRole) =>
                    props.onRoleChange(membership, access, newRole)
                  }
                  onActiveToggle={(next) =>
                    props.onActiveToggle(membership, access, next)
                  }
                  onEditPermissions={() =>
                    props.onEditPermissions(membership, access)
                  }
                  onRemoveAccess={() =>
                    props.onRemoveAccess(membership, access)
                  }
                />
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface MatrixRowProps {
  membership: CustomerUserMembership;
  access: CustomerUserBuildingAccess;
  policy: CustomerCompanyPolicyAdmin | null;
  groupedKeys: Record<PermissionGroup, PermissionKeyRow[]>;
  isSelf: boolean;
  busy: boolean;
  onRoleChange: (newRole: CustomerAccessRole) => void;
  onActiveToggle: (next: boolean) => void;
  onEditPermissions: () => void;
  onRemoveAccess: () => void;
}

function MatrixRow(props: MatrixRowProps) {
  const { t } = useTranslation("common");
  const userName =
    props.membership.user_full_name?.trim() || props.membership.user_email;
  const overrides = props.access.permission_overrides ?? {};
  const isActive = props.access.is_active !== false;
  return (
    <tr
      className="permissions-matrix-row"
      data-testid="permissions-matrix-row"
      data-user-id={props.membership.user_id}
      data-building-id={props.access.building_id}
    >
      <th scope="row" className="permissions-matrix-cell-user">
        <div className="permissions-matrix-user-name">{userName}</div>
        <div className="permissions-matrix-user-building">
          {props.access.building_name}
        </div>
        {props.isSelf && (
          <span className="permissions-matrix-self-pill">
            {t("customer_permissions.you_chip")}
          </span>
        )}
        {!isActive && (
          <span className="permissions-matrix-inactive-pill">
            {t("customer_permissions.inactive_chip")}
          </span>
        )}
      </th>
      <td className="permissions-matrix-cell-actions">
        <div className="permissions-matrix-actions">
          <label
            className="permissions-matrix-active"
            title={t("customer_permissions.active_toggle_label")}
          >
            <Toggle
              data-testid="customer-access-active-toggle"
              data-user-id={props.membership.user_id}
              data-building-id={props.access.building_id}
              checked={isActive}
              disabled={props.busy || props.isSelf}
              onChange={(event) => props.onActiveToggle(event.target.checked)}
            />
            <span className="visually-hidden">
              {t("customer_permissions.active_toggle_label")}
            </span>
          </label>
          <button
            type="button"
            className="btn btn-ghost btn-sm permissions-matrix-edit-button"
            data-testid="customer-access-overrides-button"
            data-user-id={props.membership.user_id}
            data-building-id={props.access.building_id}
            onClick={props.onEditPermissions}
            aria-label={t("customer_permissions.matrix.edit_permissions")}
            title={t("customer_permissions.matrix.edit_permissions")}
          >
            <Pencil size={14} strokeWidth={2.2} aria-hidden="true" />
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm permissions-matrix-remove-button"
            data-testid="customer-access-remove-button"
            data-user-id={props.membership.user_id}
            data-building-id={props.access.building_id}
            onClick={props.onRemoveAccess}
            disabled={props.busy || props.isSelf}
            aria-label={t("customer_permissions.remove_access_label")}
            title={t("customer_permissions.remove_access_label")}
          >
            <XIcon size={14} strokeWidth={2.2} aria-hidden="true" />
          </button>
        </div>
      </td>
      <td className="permissions-matrix-cell-role">
        <label className="visually-hidden">
          {t("customer_permissions.role_select_label")}
        </label>
        <select
          className="permissions-matrix-role-select"
          data-testid="customer-access-role-select"
          data-user-id={props.membership.user_id}
          data-building-id={props.access.building_id}
          value={props.access.access_role}
          disabled={props.busy || props.isSelf}
          onChange={(event) =>
            props.onRoleChange(event.target.value as CustomerAccessRole)
          }
        >
          <option value="CUSTOMER_USER">
            {t(accessRoleLabelKey("CUSTOMER_USER"))}
          </option>
          <option value="CUSTOMER_LOCATION_MANAGER">
            {t(accessRoleLabelKey("CUSTOMER_LOCATION_MANAGER"))}
          </option>
          {/*
            CUSTOMER_COMPANY_ADMIN is company-wide and is NEVER offered as
            a per-building grant here — the only CCA control lives in the
            Users drill-in modal's "Make / Remove company admin" toggle
            (the backend 400s a per-building CCA grant with
            `cca_is_company_wide`). The option is rendered READ-BACK-ONLY:
            shown solely so a legacy CCA row still displays its current
            value in the select; it is never an option the operator can
            pick for a row that does not already hold it.
          */}
          {props.access.access_role === "CUSTOMER_COMPANY_ADMIN" && (
            <option value="CUSTOMER_COMPANY_ADMIN">
              {t(accessRoleLabelKey("CUSTOMER_COMPANY_ADMIN"))}
            </option>
          )}
        </select>
      </td>
      {PERMISSION_GROUPS.map((group) => (
        <td key={group} className="permissions-matrix-cell-group">
          <PermissionGroupChip
            group={group}
            rows={props.groupedKeys[group]}
            overrides={overrides}
            isActive={isActive}
            policy={props.policy}
            accessRole={props.access.access_role}
          />
        </td>
      ))}
    </tr>
  );
}
