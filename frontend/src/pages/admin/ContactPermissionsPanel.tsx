// Sprint 2 + perm-panel completion (frontend) — in-place permission
// editor for a contact's linked user. Opens DOWNWARD under the contact's
// "Manage permissions" toggle (no navigation away). MIRRORS the matrix's
// per-user controls — per-building access-role <select>, active/inactive
// toggle, remove-building, and an add-building picker — plus the reused
// PermissionEditorModal (tri-state inherit/allow/deny groups tickets ->
// extra_work -> users) + effectiveResolver helpers. It REUSES the same api
// fns and gating (grantable-target-role policy + self-edit guard); it does
// NOT fork PermissionsMatrix / CustomerPermissionsPage / the leaf
// components, so their locked testids stay green. The panel carries its
// own contact-permissions-* testids.
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ExternalLink, Pencil, Plus, Trash2 } from "lucide-react";

import { getApiError } from "../../api/client";
import {
  addCustomerUserAccess,
  getCustomer,
  getCustomerPolicy,
  listCustomerBuildings,
  listCustomerUserAccess,
  listCustomerUsers,
  removeCustomerUserAccess,
  updateCustomerUserAccess,
  updateCustomerUserAccessRole,
} from "../../api/admin";
import type {
  CustomerAccessRole,
  CustomerAdmin,
  CustomerBuildingMembership,
  CustomerCompanyPolicyAdmin,
  CustomerPermissionKey,
  CustomerUserBuildingAccess,
  CustomerUserMembership,
} from "../../api/types";
import { CUSTOMER_PERMISSION_KEYS } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { accessRoleLabelKey } from "../../lib/enumLabels";

import { PermissionEditorModal } from "./customer/permissions/PermissionEditorModal";
import type { OverrideDraft } from "./customer/permissions/PermissionEditorModal";
import {
  buildOverridesPayload,
  draftValueFromOverride,
} from "./customer/permissions/effectiveResolver";

export function ContactPermissionsPanel({
  customerId,
  userId,
}: {
  customerId: number;
  userId: number;
}) {
  const { t } = useTranslation("common");
  const { me } = useAuth();

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [membership, setMembership] = useState<CustomerUserMembership | null>(
    null,
  );
  const [accessRows, setAccessRows] = useState<CustomerUserBuildingAccess[]>([]);
  const [buildings, setBuildings] = useState<CustomerBuildingMembership[]>([]);
  const [policy, setPolicy] = useState<CustomerCompanyPolicyAdmin | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Single immediate-save flag for the per-building access mutations
  // (role / active / add / remove). Disables the controls while a
  // round-trip is in flight — mirrors the matrix's per-user busy gate.
  const [accessBusy, setAccessBusy] = useState(false);
  const [addBuildingId, setAddBuildingId] = useState("");

  // Override modal state — mirrors CustomerPermissionsPage exactly so the
  // reused PermissionEditorModal behaves identically here.
  const emptyOverrideDraft = useMemo<OverrideDraft>(() => {
    const d = {} as OverrideDraft;
    for (const key of CUSTOMER_PERMISSION_KEYS) d[key] = "inherit";
    return d;
  }, []);
  const [editingAccess, setEditingAccess] =
    useState<CustomerUserBuildingAccess | null>(null);
  const [overrideDraft, setOverrideDraft] =
    useState<OverrideDraft>(emptyOverrideDraft);
  const [overrideSaving, setOverrideSaving] = useState(false);

  // Remove-building confirm dialog.
  const removeRef = useRef<ConfirmDialogHandle>(null);
  const [removeTarget, setRemoveTarget] =
    useState<CustomerUserBuildingAccess | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);

  // Load the customer (for the grantable-role policy), the membership (for
  // the modal user label + self gate), this user's per-building access
  // rows, the company policy, and the customer's buildings (for the
  // add-building picker) — once per (customer, user). All setState happens
  // inside the async closure AFTER an await, never synchronously in the
  // effect body, so there is no set-state-in-effect.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [customerData, usersResp, accessResp, policyData, buildingsResp] =
          await Promise.all([
            getCustomer(customerId),
            listCustomerUsers(customerId),
            listCustomerUserAccess(customerId, userId),
            getCustomerPolicy(customerId),
            listCustomerBuildings(customerId),
          ]);
        if (cancelled) return;
        setCustomer(customerData);
        setMembership(
          usersResp.results.find((m) => m.user_id === userId) ?? null,
        );
        setAccessRows(accessResp.results);
        setPolicy(policyData);
        setBuildings(buildingsResp.results);
        setError("");
        setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError(getApiError(err));
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [customerId, userId]);

  async function reloadAccess() {
    try {
      const resp = await listCustomerUserAccess(customerId, userId);
      setAccessRows(resp.results);
      setError("");
    } catch (err) {
      setError(getApiError(err));
    }
  }

  // ---- Override modal (unchanged from Sprint 2) ----
  function openEditor(access: CustomerUserBuildingAccess) {
    const draft = {} as OverrideDraft;
    for (const key of CUSTOMER_PERMISSION_KEYS) {
      draft[key as CustomerPermissionKey] = draftValueFromOverride(
        access.permission_overrides ?? {},
        key as CustomerPermissionKey,
      );
    }
    setOverrideDraft(draft);
    setEditingAccess(access);
  }

  function closeEditor() {
    setEditingAccess(null);
    setOverrideDraft(emptyOverrideDraft);
  }

  async function handleSaveOverrides() {
    if (!editingAccess) return;
    setOverrideSaving(true);
    setError("");
    try {
      await updateCustomerUserAccess(customerId, userId, editingAccess.building_id, {
        permission_overrides: buildOverridesPayload(overrideDraft),
      });
      await reloadAccess();
      closeEditor();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setOverrideSaving(false);
    }
  }

  // ---- Per-building access mutations (immediate-save, mirrors matrix) ----
  async function handleRoleChange(
    access: CustomerUserBuildingAccess,
    newRole: CustomerAccessRole,
  ) {
    if (newRole === access.access_role) return;
    setAccessBusy(true);
    setError("");
    try {
      await updateCustomerUserAccessRole(
        customerId,
        userId,
        access.building_id,
        newRole,
      );
      await reloadAccess();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setAccessBusy(false);
    }
  }

  async function handleToggleActive(
    access: CustomerUserBuildingAccess,
    nextActive: boolean,
  ) {
    setAccessBusy(true);
    setError("");
    try {
      await updateCustomerUserAccess(customerId, userId, access.building_id, {
        is_active: nextActive,
      });
      await reloadAccess();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setAccessBusy(false);
    }
  }

  async function handleAddBuilding() {
    const buildingId = Number(addBuildingId);
    if (!buildingId) return;
    setAccessBusy(true);
    setError("");
    try {
      await addCustomerUserAccess(customerId, userId, buildingId);
      setAddBuildingId("");
      await reloadAccess();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setAccessBusy(false);
    }
  }

  function openRemoveDialog(access: CustomerUserBuildingAccess) {
    setRemoveTarget(access);
    setError("");
    removeRef.current?.open();
  }

  async function handleConfirmRemove() {
    if (!removeTarget) return;
    setRemoveBusy(true);
    setError("");
    try {
      await removeCustomerUserAccess(customerId, userId, removeTarget.building_id);
      removeRef.current?.close();
      setRemoveTarget(null);
      await reloadAccess();
    } catch (err) {
      setError(getApiError(err));
      removeRef.current?.close();
    } finally {
      setRemoveBusy(false);
    }
  }

  // ---- Derived gating (mirrors CustomerPermissionsPage) ----
  // Self-edit guard: an actor cannot edit their OWN access row.
  const isSelf = me?.id === userId;
  // H-6/H-7: only viewers whose customer.actions allow it may grant CCA;
  // absent actions falls back to SUPER_ADMIN-only (safest pre-fetch).
  const allowedTargetAccessRoles =
    customer?.actions?.allowed_target_customer_access_roles ?? null;
  const canGrantCustomerCompanyAdmin = allowedTargetAccessRoles
    ? allowedTargetAccessRoles.includes("CUSTOMER_COMPANY_ADMIN")
    : me?.role === "SUPER_ADMIN";

  // Buildings the user does not yet have access to (for the add picker).
  const availableBuildings = buildings.filter(
    (b) => !accessRows.some((a) => a.building_id === b.building_id),
  );

  const editingIsSelf = editingAccess ? me?.id === editingAccess.user_id : false;
  const matrixHref = `/admin/customers/${customerId}/permissions?focus_user=${userId}`;

  return (
    <div
      className="card"
      data-testid="contact-permissions-panel"
      style={{ marginTop: 12, padding: "14px 16px 16px" }}
    >
      <div
        style={{
          fontSize: 11,
          fontWeight: 800,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
          color: "var(--text-faint)",
          marginBottom: 10,
        }}
      >
        {t("customer_contacts.permissions_panel_title")}
      </div>

      {error && (
        <div
          className="alert-error"
          role="alert"
          data-testid="contact-permissions-error"
          style={{ marginBottom: 10 }}
        >
          {error}
        </div>
      )}

      {/* Add-building picker — the customer's buildings the user lacks.
          Hidden while loading, for the actor's own row (self-edit guard),
          and when there is nothing left to add. */}
      {!loading && !isSelf && availableBuildings.length > 0 && (
        <div
          data-testid="contact-permissions-add-building"
          style={{
            display: "flex",
            gap: 8,
            alignItems: "flex-end",
            flexWrap: "wrap",
            marginBottom: 12,
          }}
        >
          <div className="field" style={{ margin: 0 }}>
            <label className="field-label" htmlFor="contact-perm-add-building">
              {t("customer_contacts.permissions_panel_add_building_label")}
            </label>
            <select
              id="contact-perm-add-building"
              className="field-input"
              data-testid="contact-permissions-add-building-select"
              value={addBuildingId}
              disabled={accessBusy}
              onChange={(event) => setAddBuildingId(event.target.value)}
              style={{ minWidth: 180, height: 34 }}
            >
              <option value="">
                {t(
                  "customer_contacts.permissions_panel_add_building_placeholder",
                )}
              </option>
              {availableBuildings.map((b) => (
                <option key={b.building_id} value={b.building_id}>
                  {b.building_name}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            data-testid="contact-permissions-add-building-button"
            onClick={handleAddBuilding}
            disabled={accessBusy || addBuildingId === ""}
          >
            <Plus size={14} strokeWidth={2.2} />
            {t("customer_contacts.permissions_panel_add_building_button")}
          </button>
        </div>
      )}

      {loading ? (
        <p className="muted small" data-testid="contact-permissions-loading">
          {t("customer_contacts.permissions_panel_loading")}
        </p>
      ) : accessRows.length === 0 ? (
        <div data-testid="contact-permissions-empty">
          <p className="muted small" style={{ margin: 0 }}>
            {t("customer_contacts.permissions_panel_empty")}
          </p>
          <p className="muted small" style={{ margin: "4px 0 0" }}>
            {t("customer_contacts.permissions_panel_empty_hint")}
          </p>
        </div>
      ) : (
        <ul
          data-testid="contact-permissions-building-list"
          style={{
            listStyle: "none",
            margin: 0,
            padding: 0,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          {accessRows.map((access) => {
            const overrideCount = Object.keys(
              access.permission_overrides ?? {},
            ).length;
            const isActive = access.is_active !== false;
            return (
              <li
                key={access.building_id}
                data-testid="contact-permissions-building-row"
                data-building-id={access.building_id}
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  padding: "8px 10px",
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                    flexWrap: "wrap",
                  }}
                >
                  <span style={{ fontWeight: 600 }}>{access.building_name}</span>
                  <span
                    style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}
                  >
                    {!isActive && (
                      <span
                        className="muted small"
                        data-testid="contact-permissions-inactive"
                      >
                        {t("customer_permissions.inactive_chip")}
                      </span>
                    )}
                    {overrideCount > 0 && (
                      <span
                        className="badge badge-waiting_customer_approval"
                        data-testid="contact-permissions-custom-badge"
                      >
                        {t("customer_contacts.permissions_panel_custom_badge")}
                      </span>
                    )}
                  </span>
                </div>

                <div
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    flexWrap: "wrap",
                  }}
                >
                  <select
                    className="field-input"
                    data-testid="contact-permissions-role-select"
                    data-building-id={access.building_id}
                    aria-label={t("customer_permissions.role_select_label")}
                    value={access.access_role}
                    disabled={accessBusy || isSelf}
                    onChange={(event) =>
                      handleRoleChange(
                        access,
                        event.target.value as CustomerAccessRole,
                      )
                    }
                    style={{ maxWidth: 220, height: 32, flex: "1 1 160px" }}
                  >
                    <option value="CUSTOMER_USER">
                      {t(accessRoleLabelKey("CUSTOMER_USER"))}
                    </option>
                    <option value="CUSTOMER_LOCATION_MANAGER">
                      {t(accessRoleLabelKey("CUSTOMER_LOCATION_MANAGER"))}
                    </option>
                    {/* H-6/H-7: only show CCA when grantable, or when the row
                        already holds it (so a CA who cannot promote still
                        sees the current value). */}
                    {(canGrantCustomerCompanyAdmin ||
                      access.access_role === "CUSTOMER_COMPANY_ADMIN") && (
                      <option value="CUSTOMER_COMPANY_ADMIN">
                        {t(accessRoleLabelKey("CUSTOMER_COMPANY_ADMIN"))}
                      </option>
                    )}
                  </select>

                  <label
                    style={{ display: "flex", gap: 4, alignItems: "center" }}
                    title={t("customer_permissions.active_toggle_label")}
                  >
                    <input
                      type="checkbox"
                      data-testid="contact-permissions-active-toggle"
                      data-building-id={access.building_id}
                      checked={isActive}
                      disabled={accessBusy || isSelf}
                      onChange={(event) =>
                        handleToggleActive(access, event.target.checked)
                      }
                    />
                    <span className="muted small">
                      {t("customer_permissions.active_toggle_label")}
                    </span>
                  </label>

                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    data-testid="contact-permissions-edit-button"
                    onClick={() => openEditor(access)}
                    disabled={membership === null}
                  >
                    <Pencil size={13} strokeWidth={2} />
                    {t("customer_contacts.permissions_panel_edit_button")}
                  </button>

                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="contact-permissions-remove-button"
                    data-building-id={access.building_id}
                    onClick={() => openRemoveDialog(access)}
                    disabled={accessBusy || isSelf}
                    aria-label={t("customer_permissions.remove_access_label")}
                    title={t("customer_permissions.remove_access_label")}
                  >
                    <Trash2 size={13} strokeWidth={2} />
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* Secondary link to the full matrix. */}
      <div style={{ marginTop: 12 }}>
        <Link
          to={matrixHref}
          className="btn btn-ghost btn-sm"
          data-testid="customer-contact-manage-permissions"
        >
          <ExternalLink size={13} strokeWidth={2} />
          {t("customer_contacts.permissions_panel_matrix_link")}
        </Link>
        <div className="muted small" style={{ marginTop: 6 }}>
          {t("customer_contacts.permissions_panel_matrix_hint")}
        </div>
      </div>

      {/* Reused matrix modal — verbatim, so its locked testids
          (section-customer-overrides-editor, customer-overrides-*) keep
          belonging to the matrix specs. */}
      <PermissionEditorModal
        open={editingAccess !== null}
        membership={membership}
        access={editingAccess}
        policy={policy}
        draft={overrideDraft}
        setDraft={setOverrideDraft}
        onClose={closeEditor}
        onSave={handleSaveOverrides}
        saving={overrideSaving}
        isSelf={editingIsSelf}
      />

      <ConfirmDialog
        ref={removeRef}
        title={t("customer_form.dialog_revoke_access_title", {
          email: membership?.user_email ?? "",
          building: removeTarget?.building_name ?? "",
        })}
        body={t("customer_form.dialog_revoke_access_body")}
        confirmLabel={t("customer_form.access_remove_button")}
        onConfirm={handleConfirmRemove}
        onCancel={() => setRemoveTarget(null)}
        busy={removeBusy}
        destructive
      />
    </div>
  );
}
