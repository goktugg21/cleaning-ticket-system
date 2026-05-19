import { useMemo } from "react";
import { Building2, ChevronRight, Plus, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  CustomerAccessRole,
  CustomerBuildingMembership,
  CustomerUserBuildingAccess,
  CustomerUserMembership,
} from "../../../../api/types";
import { getInitials } from "../../../../lib/initials";
import { accessRoleLabelKey } from "../../../../lib/enumLabels";
import { EmptyState } from "../../../../components/EmptyState";

/**
 * Sprint 28 Batch 15.2 — replaces the dense "one user per row in a
 * data-table cell stuffed with chips" affordance with a real card
 * per CustomerUserMembership. The card body lists each building
 * the user has access to, with the sub-role + active toggle + a
 * "Custom permissions: N" pill that opens the override drawer.
 *
 * The locked testids `customer-access-badge`, `customer-access-role-select`
 * (real <select>), `customer-access-active-toggle` (real <input
 * type="checkbox">), and `customer-access-overrides-button` are
 * preserved with their existing `data-user-id` / `data-building-id`
 * attributes.
 */
export interface UserAccessCardProps {
  membership: CustomerUserMembership;
  accesses: CustomerUserBuildingAccess[];
  linkedBuildings: CustomerBuildingMembership[];
  /** True only for the current authenticated user. */
  meId: number | undefined;
  /** Whether the active actor can grant CUSTOMER_COMPANY_ADMIN (SUPER_ADMIN only). */
  canGrantCustomerCompanyAdmin: boolean;
  busy: boolean;
  onRoleChange: (
    access: CustomerUserBuildingAccess,
    newRole: CustomerAccessRole,
  ) => void;
  onActiveToggle: (
    access: CustomerUserBuildingAccess,
    nextActive: boolean,
  ) => void;
  onOpenOverrides: (access: CustomerUserBuildingAccess) => void;
  onRemoveAccess: (access: CustomerUserBuildingAccess) => void;
  onAddBuilding: (buildingId: number) => void;
}

function countOverrides(access: CustomerUserBuildingAccess): number {
  return Object.keys(access.permission_overrides ?? {}).length;
}

export function UserAccessCard({
  membership,
  accesses,
  linkedBuildings,
  meId,
  canGrantCustomerCompanyAdmin,
  busy,
  onRoleChange,
  onActiveToggle,
  onOpenOverrides,
  onRemoveAccess,
  onAddBuilding,
}: UserAccessCardProps) {
  const { t } = useTranslation("common");

  const accessBuildingIds = useMemo(
    () => new Set(accesses.map((a) => a.building_id)),
    [accesses],
  );
  const grantableBuildings = useMemo(
    () => linkedBuildings.filter((l) => !accessBuildingIds.has(l.building_id)),
    [linkedBuildings, accessBuildingIds],
  );

  const fullName = membership.user_full_name?.trim() || "";
  const initials = getInitials(fullName || membership.user_email);

  return (
    <article
      className="user-access-card"
      data-testid="customer-user-access-summary"
      data-user-access-card-id={membership.user_id}
      id={`user-access-card-${membership.user_id}`}
    >
      <header className="user-access-card-header">
        <span className="user-access-card-avatar" aria-hidden="true">
          {initials}
        </span>
        <div className="user-access-card-identity">
          <div className="user-access-card-name">
            {fullName || membership.user_email}
          </div>
          {fullName && (
            <div className="user-access-card-email">{membership.user_email}</div>
          )}
        </div>
      </header>

      {accesses.length === 0 ? (
        <div className="user-access-card-body">
          <EmptyState
            compact
            icon={Building2}
            title={t("customer_form.access_no_buildings")}
            description={t(
              "customer_permissions.access_no_buildings_helper",
            )}
          />
        </div>
      ) : (
        <ul className="user-access-card-body access-chip-list">
          {accesses.map((access) => {
            const isSelf = meId === access.user_id;
            const overridesCount = countOverrides(access);
            const customPermissionsLabel =
              overridesCount === 0
                ? t("customer_permissions.custom_permissions_label_zero")
                : overridesCount === 1
                  ? t(
                      "customer_permissions.custom_permissions_label_some_one",
                      { count: overridesCount },
                    )
                  : t(
                      "customer_permissions.custom_permissions_label_some_other",
                      { count: overridesCount },
                    );

            return (
              <li
                key={access.id}
                className={`access-chip${
                  access.is_active === false ? " access-chip-inactive" : ""
                }`}
                data-testid="customer-access-badge"
              >
                <div className="access-chip-building">
                  <span className="access-chip-building-name">
                    {access.building_name}
                  </span>
                  {isSelf && (
                    <span
                      className="access-chip-you"
                      title={t("customer_permissions.you_chip_hint")}
                    >
                      {t("customer_permissions.you_chip")}
                    </span>
                  )}
                  {access.is_active === false && (
                    <span className="access-chip-inactive-tag">
                      {t("customer_permissions.inactive_chip")}
                    </span>
                  )}
                </div>

                <div className="access-chip-controls">
                  <label
                    className="access-chip-role"
                    title={t("customer_permissions.role_select_label")}
                  >
                    <span className="visually-hidden">
                      {t("customer_permissions.role_select_label")}
                    </span>
                    <select
                      className="access-chip-role-select"
                      data-testid="customer-access-role-select"
                      data-user-id={membership.user_id}
                      data-building-id={access.building_id}
                      value={access.access_role}
                      disabled={busy || isSelf}
                      onChange={(event) =>
                        onRoleChange(
                          access,
                          event.target.value as CustomerAccessRole,
                        )
                      }
                    >
                      <option value="CUSTOMER_USER">
                        {t(accessRoleLabelKey("CUSTOMER_USER"))}
                      </option>
                      <option value="CUSTOMER_LOCATION_MANAGER">
                        {t(accessRoleLabelKey("CUSTOMER_LOCATION_MANAGER"))}
                      </option>
                      {/*
                        Sprint 28 Batch 15.2 — H-6/H-7 invariant: only
                        SUPER_ADMIN may grant CUSTOMER_COMPANY_ADMIN.
                        Show the option to SUPER_ADMIN OR when the
                        access row already holds the role (so the
                        select can still display the current value
                        for COMPANY_ADMIN, who simply can't switch a
                        non-admin TO it).
                      */}
                      {(canGrantCustomerCompanyAdmin ||
                        access.access_role === "CUSTOMER_COMPANY_ADMIN") && (
                        <option value="CUSTOMER_COMPANY_ADMIN">
                          {t(accessRoleLabelKey("CUSTOMER_COMPANY_ADMIN"))}
                        </option>
                      )}
                    </select>
                  </label>

                  <label className="access-chip-active">
                    <input
                      type="checkbox"
                      data-testid="customer-access-active-toggle"
                      data-user-id={membership.user_id}
                      data-building-id={access.building_id}
                      checked={access.is_active !== false}
                      disabled={busy || isSelf}
                      onChange={(event) =>
                        onActiveToggle(access, event.target.checked)
                      }
                    />
                    <span>{t("customer_permissions.active_toggle_label")}</span>
                  </label>

                  <button
                    type="button"
                    className={`custom-permissions-pill${
                      overridesCount > 0 ? " custom-permissions-pill-some" : ""
                    }`}
                    data-testid="customer-access-overrides-button"
                    data-user-id={membership.user_id}
                    data-building-id={access.building_id}
                    onClick={() => onOpenOverrides(access)}
                    disabled={busy}
                  >
                    <span
                      className="custom-permissions-pill-dot"
                      aria-hidden="true"
                    />
                    <span>{customPermissionsLabel}</span>
                    <ChevronRight size={14} strokeWidth={2.2} aria-hidden="true" />
                  </button>

                  <button
                    type="button"
                    className="access-chip-remove"
                    aria-label={t("customer_permissions.remove_access_label")}
                    title={t("customer_permissions.remove_access_label")}
                    onClick={() => onRemoveAccess(access)}
                    disabled={busy || isSelf}
                  >
                    <X size={14} strokeWidth={2.4} />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <footer className="user-access-card-footer">
        <div className="add-building-access-row">
          <Plus size={14} strokeWidth={2.2} aria-hidden="true" />
          <label className="add-building-access-label">
            <span>{t("customer_permissions.add_building_access")}</span>
            <select
              className="field-select add-building-access-select"
              value=""
              disabled={busy || grantableBuildings.length === 0}
              onChange={(event) => {
                const v = event.target.value;
                if (v === "") return;
                onAddBuilding(Number(v));
                event.target.value = "";
              }}
            >
              <option value="">
                {grantableBuildings.length === 0
                  ? t("customer_permissions.add_building_no_more")
                  : t("customer_permissions.add_building_placeholder")}
              </option>
              {grantableBuildings.map((l) => (
                <option key={l.id} value={l.building_id}>
                  {l.building_name}
                </option>
              ))}
            </select>
          </label>
        </div>
      </footer>
    </article>
  );
}


