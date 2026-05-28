import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Pencil, X as XIcon } from "lucide-react";

import type {
  CustomerAccessRole,
  CustomerBuildingMembership,
  CustomerCompanyPolicyAdmin,
  CustomerPermissionKey,
  CustomerUserBuildingAccess,
  CustomerUserMembership,
} from "../../../../api/types";
import { accessRoleLabelKey } from "../../../../lib/enumLabels";

import { resolvePanelValue } from "./effectiveResolver";
import {
  PERMISSION_GROUP_LABEL_KEY,
  PERMISSION_KEY_ROWS,
  type PermissionGroup,
  type PermissionKeyRow,
} from "./permissionKeyLabels";
import { PermissionBubble } from "./PermissionBubble";

/**
 * Sprint 31 Phase 6 — Excel-style permission matrix.
 *
 * Primary view of the per-user permission surface; REPLACES the
 * `UserAccessCard` + `AccessPermissionsPanel` flow. One <tr> per
 * `CustomerUserBuildingAccess` row (user × building × access_role).
 *
 *   User | Role | Tickets (6) | Extra Work (6) | Users (4) | Actions
 *
 * Each permission cell renders a `PermissionBubble` whose state is
 * driven by `resolvePanelValue` — NEVER by client-side permission
 * truth. The matrix shows the EFFECTIVE outcome, collapsing
 * inherit-allow + override-allow into "granted" and bringing
 * policy-blocked out as a distinct visual variant so the operator
 * can tell "user doesn't have it" apart from "company policy
 * forbids it" without opening the modal.
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
 *   - `permission-bubble` (rendered by PermissionBubble)
 *
 * Retired:
 *   - `access-permissions-panel-<id>` / `access-permissions-edit-<id>`
 *     (the panel is gone — the matrix shows the same info at a
 *     glance and the modal opens directly from the row)
 *   - `customer-access-badge` (per-building chip — folded into the
 *     row itself)
 */
export interface PermissionsMatrixProps {
  members: CustomerUserMembership[];
  accessByUserId: Record<number, CustomerUserBuildingAccess[]>;
  linkedBuildings: CustomerBuildingMembership[];
  policy: CustomerCompanyPolicyAdmin | null;
  meId: number | undefined;
  canGrantCustomerCompanyAdmin: boolean;
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
            {/* Group-span header row. Column order:
                  User | Actions | Role | Tickets(6) | Extra Work(6) | Users(4)
                The first three are sticky-left so identity + controls
                stay visible while the 16 vertical permission columns
                scroll under them on narrow viewports. */}
            <tr className="permissions-matrix-head-groups">
              <th
                className="permissions-matrix-cell-user permissions-matrix-sticky-user"
                rowSpan={2}
              >
                {t("customer_permissions.matrix.col_user")}
              </th>
              <th
                className="permissions-matrix-cell-actions permissions-matrix-sticky-actions"
                rowSpan={2}
                aria-label={t("customer_permissions.matrix.col_actions")}
              />
              <th
                className="permissions-matrix-cell-role permissions-matrix-sticky-role"
                rowSpan={2}
              >
                {t("customer_permissions.matrix.col_role")}
              </th>
              {(["tickets", "extra_work", "users"] as const).map((group) => (
                <th
                  key={group}
                  colSpan={groupedKeys[group].length}
                  className={`permissions-matrix-group-header permissions-matrix-group-${group}`}
                >
                  {t(PERMISSION_GROUP_LABEL_KEY[group])}
                </th>
              ))}
            </tr>
            {/* Per-key short-label row. Labels are rotated -45° so
                each permission column narrows to ~34px while staying
                fully readable. Adjacent labels lean up-and-right out
                of their own columns on parallel diagonals and don't
                overlap each other. The grid still scrolls under the
                frozen User | Actions | Role columns when needed —
                the angle just shrinks how wide it has to be. */}
            <tr className="permissions-matrix-head-keys">
              {(["tickets", "extra_work", "users"] as const).flatMap((group) =>
                groupedKeys[group].map((row) => (
                  <th
                    key={row.key}
                    className="permissions-matrix-key-header permissions-matrix-key-header-angled"
                    title={t(
                      `customer_permissions.permission_keys.${row.key}.label`,
                    )}
                    scope="col"
                  >
                    <span className="permissions-matrix-key-short">
                      {t(
                        `customer_permissions.matrix.key_short.${row.key}`,
                      )}
                    </span>
                  </th>
                )),
              )}
            </tr>
          </thead>
          <tbody>
            {flatRows.length === 0 ? (
              <tr>
                <td
                  colSpan={3 + PERMISSION_KEY_ROWS.length}
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
                  isSelf={props.meId === membership.user_id}
                  busy={props.isUserBusy(membership.user_id)}
                  canGrantCustomerCompanyAdmin={
                    props.canGrantCustomerCompanyAdmin
                  }
                  policyBlockedLabel={t(
                    "customer_permissions.matrix.policy_blocked",
                  )}
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
  isSelf: boolean;
  busy: boolean;
  canGrantCustomerCompanyAdmin: boolean;
  policyBlockedLabel: string;
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
      <th
        scope="row"
        className="permissions-matrix-cell-user permissions-matrix-sticky-user"
      >
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
      <td className="permissions-matrix-cell-actions permissions-matrix-sticky-actions">
        <div className="permissions-matrix-actions">
          <label
            className="permissions-matrix-active"
            title={t("customer_permissions.active_toggle_label")}
          >
            <input
              type="checkbox"
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
      <td className="permissions-matrix-cell-role permissions-matrix-sticky-role">
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
            H-6 / H-7 invariant: only SUPER_ADMIN may grant
            CUSTOMER_COMPANY_ADMIN. Show the option if the viewer can
            grant it OR if the row already holds it (so the select
            displays the current value for a CA who cannot promote
            other users to CCA but must still see this user's role).
          */}
          {(props.canGrantCustomerCompanyAdmin ||
            props.access.access_role === "CUSTOMER_COMPANY_ADMIN") && (
            <option value="CUSTOMER_COMPANY_ADMIN">
              {t(accessRoleLabelKey("CUSTOMER_COMPANY_ADMIN"))}
            </option>
          )}
        </select>
      </td>
      {PERMISSION_KEY_ROWS.map((row) => (
        <PermissionMatrixCell
          key={row.key}
          permissionKey={row.key}
          overrides={overrides}
          isActive={isActive}
          policy={props.policy}
          accessRole={props.access.access_role}
          policyBlockedLabel={props.policyBlockedLabel}
        />
      ))}
    </tr>
  );
}

interface PermissionMatrixCellProps {
  permissionKey: CustomerPermissionKey;
  overrides: Record<string, boolean>;
  isActive: boolean;
  policy: CustomerCompanyPolicyAdmin | null;
  accessRole: CustomerAccessRole;
  policyBlockedLabel: string;
}

function PermissionMatrixCell({
  permissionKey,
  overrides,
  isActive,
  policy,
  accessRole,
  policyBlockedLabel,
}: PermissionMatrixCellProps) {
  const { t } = useTranslation("common");
  const resolution = resolvePanelValue({
    key: permissionKey,
    overrides,
    isActive,
    policy,
    accessRole,
  });
  const keyLabel = t(
    `customer_permissions.permission_keys.${permissionKey}.label`,
  );
  const ariaLabel = resolution.granted
    ? t("customer_permissions.matrix.cell_granted_aria", { key: keyLabel })
    : resolution.reason === "policy_denied"
      ? t("customer_permissions.matrix.cell_policy_blocked_aria", {
          key: keyLabel,
        })
      : t("customer_permissions.matrix.cell_denied_aria", { key: keyLabel });
  return (
    <td
      className="permissions-matrix-cell-perm"
      data-testid="permissions-matrix-cell"
      data-permission-key={permissionKey}
      data-effective={resolution.granted ? "granted" : "denied"}
      data-policy-blocked={
        resolution.reason === "policy_denied" ? "true" : "false"
      }
    >
      <PermissionBubble
        resolution={resolution}
        policyBlockedLabel={policyBlockedLabel}
        ariaLabel={ariaLabel}
      />
    </td>
  );
}
