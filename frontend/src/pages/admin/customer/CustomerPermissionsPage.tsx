import type { FormEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import {
  addCustomerUserAccess,
  getCustomer,
  getCustomerPolicy,
  listCustomerBuildings,
  listCustomerUserAccess,
  listCustomerUsers,
  removeCustomerUserAccess,
  updateCustomerPolicy,
  updateCustomerUserAccess,
  updateCustomerUserAccessRole,
} from "../../../api/admin";
import type {
  CustomerAccessRole,
  CustomerAdmin,
  CustomerBuildingMembership,
  CustomerCompanyPolicyAdmin,
  CustomerUserBuildingAccess,
  CustomerUserMembership,
} from "../../../api/types";
import { CUSTOMER_PERMISSION_KEYS } from "../../../api/types";
import { useAuth } from "../../../auth/AuthContext";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";
import { useSavedBanner } from "../../../hooks/useSavedBanner";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

// Sprint 27E — 3-way control per permission key. Mirrors the helper
// in `CustomerFormPage.tsx`; duplicated here intentionally so the
// permissions page is self-contained (Batch 13 scope, no shared
// customer-context provider).
type OverrideTriState = "inherit" | "grant" | "revoke";

function tristateFromOverride(
  overrides: Record<string, boolean>,
  key: string,
): OverrideTriState {
  if (!(key in overrides)) return "inherit";
  return overrides[key] ? "grant" : "revoke";
}

function buildOverridesPayload(
  draft: Record<string, OverrideTriState>,
): Record<string, boolean> {
  const out: Record<string, boolean> = {};
  for (const [key, value] of Object.entries(draft)) {
    if (value === "grant") out[key] = true;
    else if (value === "revoke") out[key] = false;
  }
  return out;
}

/**
 * Sprint 28 Batch 13 — Customer Permissions page (admin variant).
 *
 * Migrates the per-access access-role + permission-override editor and
 * the `CustomerCompanyPolicy` form OUT of `CustomerFormPage.tsx`. The
 * Overview page no longer renders any permission affordances; this is
 * now the single permissions surface under `/admin/customers/:id/*`.
 *
 * Testids are preserved so the existing Sprint 27E specs continue to
 * resolve: `customer-access-role-select`, `customer-access-overrides-
 * button`, `customer-overrides-row`, `customer-overrides-radio`,
 * `customer-overrides-save`, `customer-overrides-close`,
 * `customer-policy-toggle`, `customer-policy-save`.
 */
export function CustomerPermissionsPage() {
  const { id } = useParams();
  const { t } = useTranslation("common");
  const { me } = useAuth();

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [members, setMembers] = useState<CustomerUserMembership[]>([]);
  const [linkedBuildings, setLinkedBuildings] = useState<
    CustomerBuildingMembership[]
  >([]);
  const [accessByUserId, setAccessByUserId] = useState<
    Record<number, CustomerUserBuildingAccess[]>
  >({});
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [accessError, setAccessError] = useState("");
  const [accessBusyUserId, setAccessBusyUserId] = useState<number | null>(null);

  // Override editor state.
  const [editingOverrideFor, setEditingOverrideFor] = useState<{
    membership: CustomerUserMembership;
    access: CustomerUserBuildingAccess;
  } | null>(null);
  const [overrideDraft, setOverrideDraft] = useState<
    Record<string, OverrideTriState>
  >({});
  const [overrideSaving, setOverrideSaving] = useState(false);
  const [overrideBanner, setOverrideBanner] = useSavedBanner({
    saved: t("customer_form.access_overrides_saved_banner"),
  });

  // Revoke-access dialog.
  const revokeAccessDialogRef = useRef<ConfirmDialogHandle>(null);
  const [revokeAccessTarget, setRevokeAccessTarget] = useState<{
    membership: CustomerUserMembership;
    access: CustomerUserBuildingAccess;
  } | null>(null);

  // Policy panel state.
  const [policy, setPolicy] = useState<CustomerCompanyPolicyAdmin | null>(null);
  const [policyLoading, setPolicyLoading] = useState(true);
  const [policyError, setPolicyError] = useState("");
  const [policySaving, setPolicySaving] = useState(false);
  const [policyDraft, setPolicyDraft] = useState<
    Pick<
      CustomerCompanyPolicyAdmin,
      | "customer_users_can_create_tickets"
      | "customer_users_can_approve_ticket_completion"
      | "customer_users_can_create_extra_work"
      | "customer_users_can_approve_extra_work_pricing"
    >
  >({
    customer_users_can_create_tickets: true,
    customer_users_can_approve_ticket_completion: true,
    customer_users_can_create_extra_work: true,
    customer_users_can_approve_extra_work_pricing: true,
  });
  const [policyBanner, setPolicyBanner] = useSavedBanner({
    saved: t("customer_form.policy_saved_banner"),
  });

  const isSelfAccess = (access: CustomerUserBuildingAccess) =>
    me?.id === access.user_id;

  // Initial load.
  useEffect(() => {
    let cancelled = false;
    if (numericId === null) {
      queueMicrotask(() => {
        if (!cancelled) setLoadError(t("bm_customer_detail.invalid_id"));
      });
      return () => {
        cancelled = true;
      };
    }
    setLoading(true); // eslint-disable-line react-hooks/set-state-in-effect
    setLoadError("");
    Promise.all([
      getCustomer(numericId),
      listCustomerUsers(numericId),
      listCustomerBuildings(numericId),
    ])
      .then(([customerData, membersResponse, linksResponse]) => {
        if (cancelled) return;
        setCustomer(customerData);
        setMembers(membersResponse.results);
        setLinkedBuildings(linksResponse.results);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [numericId, t]);

  // Per-user building access load. Triggered after members resolve.
  // The "empty" branch defers the reset into a microtask to keep the
  // effect body free of cascading-render lint hits (same shape as
  // `BuildingManagerCustomerDetailPage.tsx:38-81`).
  useEffect(() => {
    let cancelled = false;
    if (numericId === null || members.length === 0) {
      queueMicrotask(() => {
        if (!cancelled) setAccessByUserId({});
      });
      return () => {
        cancelled = true;
      };
    }
    (async () => {
      const next: Record<number, CustomerUserBuildingAccess[]> = {};
      for (const membership of members) {
        try {
          const response = await listCustomerUserAccess(
            numericId,
            membership.user_id,
          );
          next[membership.user_id] = response.results;
        } catch {
          next[membership.user_id] = [];
        }
      }
      if (!cancelled) setAccessByUserId(next);
    })();
    return () => {
      cancelled = true;
    };
  }, [numericId, members]);

  // Policy load.
  useEffect(() => {
    if (numericId === null) return;
    let cancelled = false;
    setPolicyLoading(true); // eslint-disable-line react-hooks/set-state-in-effect
    getCustomerPolicy(numericId)
      .then((data) => {
        if (cancelled) return;
        setPolicy(data);
        setPolicyDraft({
          customer_users_can_create_tickets:
            data.customer_users_can_create_tickets,
          customer_users_can_approve_ticket_completion:
            data.customer_users_can_approve_ticket_completion,
          customer_users_can_create_extra_work:
            data.customer_users_can_create_extra_work,
          customer_users_can_approve_extra_work_pricing:
            data.customer_users_can_approve_extra_work_pricing,
        });
        setPolicyError("");
      })
      .catch((err) => {
        if (!cancelled) setPolicyError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setPolicyLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [numericId]);

  async function handleAddAccess(
    membership: CustomerUserMembership,
    buildingId: number,
  ) {
    if (numericId === null) return;
    setAccessError("");
    setAccessBusyUserId(membership.user_id);
    try {
      await addCustomerUserAccess(numericId, membership.user_id, buildingId);
      const response = await listCustomerUserAccess(
        numericId,
        membership.user_id,
      );
      setAccessByUserId((prev) => ({
        ...prev,
        [membership.user_id]: response.results,
      }));
    } catch (err) {
      setAccessError(getApiError(err));
    } finally {
      setAccessBusyUserId(null);
    }
  }

  async function handleAccessRoleChange(
    membership: CustomerUserMembership,
    access: CustomerUserBuildingAccess,
    newRole: CustomerAccessRole,
  ) {
    if (numericId === null) return;
    if (newRole === access.access_role) return;
    setAccessError("");
    setAccessBusyUserId(membership.user_id);
    try {
      await updateCustomerUserAccessRole(
        numericId,
        membership.user_id,
        access.building_id,
        newRole,
      );
      const response = await listCustomerUserAccess(
        numericId,
        membership.user_id,
      );
      setAccessByUserId((prev) => ({
        ...prev,
        [membership.user_id]: response.results,
      }));
    } catch (err) {
      setAccessError(getApiError(err));
    } finally {
      setAccessBusyUserId(null);
    }
  }

  async function handleToggleAccessActive(
    membership: CustomerUserMembership,
    access: CustomerUserBuildingAccess,
    nextActive: boolean,
  ) {
    if (numericId === null) return;
    setAccessError("");
    setAccessBusyUserId(membership.user_id);
    try {
      await updateCustomerUserAccess(
        numericId,
        membership.user_id,
        access.building_id,
        { is_active: nextActive },
      );
      const response = await listCustomerUserAccess(
        numericId,
        membership.user_id,
      );
      setAccessByUserId((prev) => ({
        ...prev,
        [membership.user_id]: response.results,
      }));
    } catch (err) {
      setAccessError(getApiError(err));
    } finally {
      setAccessBusyUserId(null);
    }
  }

  function openOverrideEditor(
    membership: CustomerUserMembership,
    access: CustomerUserBuildingAccess,
  ) {
    const draft: Record<string, OverrideTriState> = {};
    for (const key of CUSTOMER_PERMISSION_KEYS) {
      draft[key] = tristateFromOverride(access.permission_overrides, key);
    }
    setOverrideDraft(draft);
    setEditingOverrideFor({ membership, access });
  }

  function closeOverrideEditor() {
    setEditingOverrideFor(null);
    setOverrideDraft({});
  }

  async function handleSaveOverrides() {
    if (numericId === null || !editingOverrideFor) return;
    const { membership, access } = editingOverrideFor;
    setOverrideSaving(true);
    setAccessError("");
    try {
      await updateCustomerUserAccess(
        numericId,
        membership.user_id,
        access.building_id,
        { permission_overrides: buildOverridesPayload(overrideDraft) },
      );
      const response = await listCustomerUserAccess(
        numericId,
        membership.user_id,
      );
      setAccessByUserId((prev) => ({
        ...prev,
        [membership.user_id]: response.results,
      }));
      setOverrideBanner(t("customer_form.access_overrides_saved_banner"));
      closeOverrideEditor();
    } catch (err) {
      setAccessError(getApiError(err));
    } finally {
      setOverrideSaving(false);
    }
  }

  function openRevokeAccessDialog(
    membership: CustomerUserMembership,
    access: CustomerUserBuildingAccess,
  ) {
    setRevokeAccessTarget({ membership, access });
    revokeAccessDialogRef.current?.open();
  }

  async function handleConfirmRevokeAccess() {
    if (numericId === null || !revokeAccessTarget) return;
    const { membership, access } = revokeAccessTarget;
    setAccessError("");
    setAccessBusyUserId(membership.user_id);
    try {
      await removeCustomerUserAccess(
        numericId,
        membership.user_id,
        access.building_id,
      );
      const response = await listCustomerUserAccess(
        numericId,
        membership.user_id,
      );
      setAccessByUserId((prev) => ({
        ...prev,
        [membership.user_id]: response.results,
      }));
      revokeAccessDialogRef.current?.close();
      setRevokeAccessTarget(null);
    } catch (err) {
      setAccessError(getApiError(err));
      revokeAccessDialogRef.current?.close();
    } finally {
      setAccessBusyUserId(null);
    }
  }

  async function handleSavePolicy(event: FormEvent) {
    event.preventDefault();
    if (numericId === null) return;
    setPolicySaving(true);
    setPolicyError("");
    try {
      const updated = await updateCustomerPolicy(numericId, policyDraft);
      setPolicy(updated);
      setPolicyDraft({
        customer_users_can_create_tickets:
          updated.customer_users_can_create_tickets,
        customer_users_can_approve_ticket_completion:
          updated.customer_users_can_approve_ticket_completion,
        customer_users_can_create_extra_work:
          updated.customer_users_can_create_extra_work,
        customer_users_can_approve_extra_work_pricing:
          updated.customer_users_can_approve_extra_work_pricing,
      });
      setPolicyBanner(t("customer_form.policy_saved_banner"));
    } catch (err) {
      setPolicyError(getApiError(err));
    } finally {
      setPolicySaving(false);
    }
  }

  const customerName = customer?.name ?? "";
  const isActive = customer?.is_active ?? true;

  return (
    <div data-testid="customer-permissions-page">
      <CustomerSubPageHeader
        customerName={customerName}
        isActive={isActive}
      />

      {loadError && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {loadError}
        </div>
      )}

      {loading && !customer ? (
        <div className="loading-bar">
          <div className="loading-bar-fill" />
        </div>
      ) : customer ? (
        <>
          <p
            className="section-explainer"
            data-testid="customer-permissions-explainer"
          >
            {t("customer_view.permissions.explainer", {
              customer: customerName,
            })}
          </p>
          <section
            className="card"
            data-testid="section-customer-users"
            style={{ marginBottom: 16, padding: "20px 22px" }}
          >
            <h3 className="section-title">
              {t("customer_view.permissions.title")}
            </h3>
            <p className="muted small" style={{ marginBottom: 12 }}>
              {t("customer_view.permissions.subtitle")}
            </p>

            {accessError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
              >
                {accessError}
              </div>
            )}

            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t("users.col_email")}</th>
                    <th>{t("users.col_full_name")}</th>
                    <th>{t("customer_form.col_user_access")}</th>
                  </tr>
                </thead>
                <tbody>
                  {members.map((membership) => {
                    const userAccess = accessByUserId[membership.user_id] ?? [];
                    const userAccessBuildingIds = new Set(
                      userAccess.map((a) => a.building_id),
                    );
                    const grantableBuildings = linkedBuildings.filter(
                      (l) => !userAccessBuildingIds.has(l.building_id),
                    );
                    const isThisUserBusy =
                      accessBusyUserId === membership.user_id;
                    return (
                      <tr key={membership.id}>
                        <td className="td-subject">{membership.user_email}</td>
                        <td>{membership.user_full_name || "—"}</td>
                        <td>
                          {userAccess.length === 0 ? (
                            <p
                              className="muted small"
                              style={{ marginBottom: 6 }}
                            >
                              {t("customer_form.access_no_buildings")}
                            </p>
                          ) : (
                            <div
                              style={{
                                display: "flex",
                                gap: 6,
                                flexWrap: "wrap",
                                marginBottom: 6,
                              }}
                            >
                              {userAccess.map((access) => {
                                const isSelf = isSelfAccess(access);
                                return (
                                  <span
                                    key={access.id}
                                    className="badge badge-pill"
                                    data-testid="customer-access-badge"
                                    style={{
                                      display: "inline-flex",
                                      alignItems: "center",
                                      gap: 6,
                                      padding: "2px 8px",
                                      background:
                                        access.is_active === false
                                          ? "var(--surface-3, var(--surface-2))"
                                          : "var(--surface-2)",
                                      border: "1px solid var(--border)",
                                      borderRadius: 999,
                                      fontSize: 12,
                                      opacity:
                                        access.is_active === false ? 0.6 : 1,
                                    }}
                                  >
                                    <span>{access.building_name}</span>
                                    <span aria-hidden="true">·</span>
                                    <select
                                      className="customer-access-role-select"
                                      data-testid="customer-access-role-select"
                                      data-user-id={membership.user_id}
                                      data-building-id={access.building_id}
                                      value={access.access_role}
                                      disabled={isThisUserBusy || isSelf}
                                      onChange={(event) =>
                                        handleAccessRoleChange(
                                          membership,
                                          access,
                                          event.target.value as CustomerAccessRole,
                                        )
                                      }
                                      aria-label={t(
                                        "customer_form.access_role_edit_label",
                                      )}
                                      style={{
                                        fontSize: 11,
                                        padding: "0 4px",
                                        height: 20,
                                        border: "1px solid var(--border)",
                                        borderRadius: 4,
                                        background: "transparent",
                                      }}
                                    >
                                      <option value="CUSTOMER_USER">
                                        {t("access_role.customer_user")}
                                      </option>
                                      <option value="CUSTOMER_LOCATION_MANAGER">
                                        {t(
                                          "access_role.customer_location_manager",
                                        )}
                                      </option>
                                      <option value="CUSTOMER_COMPANY_ADMIN">
                                        {t(
                                          "access_role.customer_company_admin",
                                        )}
                                      </option>
                                    </select>
                                    <label
                                      style={{
                                        display: "inline-flex",
                                        alignItems: "center",
                                        gap: 4,
                                        fontSize: 11,
                                        cursor:
                                          isThisUserBusy || isSelf
                                            ? "default"
                                            : "pointer",
                                      }}
                                      title={t(
                                        "customer_form.access_active_hint",
                                      )}
                                    >
                                      <input
                                        type="checkbox"
                                        data-testid="customer-access-active-toggle"
                                        data-user-id={membership.user_id}
                                        data-building-id={access.building_id}
                                        checked={access.is_active !== false}
                                        disabled={isThisUserBusy || isSelf}
                                        onChange={(event) =>
                                          handleToggleAccessActive(
                                            membership,
                                            access,
                                            event.target.checked,
                                          )
                                        }
                                      />
                                      <span>
                                        {t(
                                          "customer_form.access_active_label",
                                        )}
                                      </span>
                                    </label>
                                    <button
                                      type="button"
                                      className="btn btn-ghost btn-xs"
                                      data-testid="customer-access-overrides-button"
                                      data-user-id={membership.user_id}
                                      data-building-id={access.building_id}
                                      style={{
                                        height: 18,
                                        padding: "0 6px",
                                        fontSize: 11,
                                      }}
                                      onClick={() =>
                                        openOverrideEditor(membership, access)
                                      }
                                      disabled={isThisUserBusy}
                                    >
                                      {t(
                                        "customer_form.access_overrides_button",
                                      )}
                                    </button>
                                    <button
                                      type="button"
                                      className="btn btn-ghost btn-xs"
                                      style={{
                                        height: 18,
                                        padding: "0 6px",
                                        fontSize: 11,
                                      }}
                                      onClick={() =>
                                        openRevokeAccessDialog(
                                          membership,
                                          access,
                                        )
                                      }
                                      disabled={isThisUserBusy}
                                      aria-label={t(
                                        "customer_form.access_remove_button",
                                      )}
                                    >
                                      ×
                                    </button>
                                  </span>
                                );
                              })}
                            </div>
                          )}
                          <div style={{ display: "flex", gap: 6 }}>
                            <select
                              className="field-select"
                              style={{ flex: 1 }}
                              value=""
                              onChange={(event) => {
                                const v = event.target.value;
                                if (v === "") return;
                                handleAddAccess(membership, Number(v));
                                event.target.value = "";
                              }}
                              disabled={
                                isThisUserBusy ||
                                grantableBuildings.length === 0
                              }
                            >
                              <option value="">
                                {grantableBuildings.length === 0
                                  ? t("customer_form.access_no_more")
                                  : t(
                                      "customer_form.access_select_placeholder",
                                    )}
                              </option>
                              {grantableBuildings.map((l) => (
                                <option key={l.id} value={l.building_id}>
                                  {l.building_name}
                                </option>
                              ))}
                            </select>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {members.length === 0 && (
                <p className="muted small" style={{ padding: "12px 0" }}>
                  {t("customer_form.no_users_yet")}
                </p>
              )}
            </div>
          </section>

          {editingOverrideFor && (
            <section
              className="card"
              data-testid="section-customer-overrides-editor"
              style={{ marginBottom: 16, padding: "20px 22px" }}
            >
              <h3 className="section-title">
                {t("customer_form.access_overrides_section_title", {
                  email: editingOverrideFor.access.user_email,
                  building: editingOverrideFor.access.building_name,
                })}
              </h3>
              <p className="muted small" style={{ marginBottom: 12 }}>
                {t("customer_form.access_overrides_section_helper")}
              </p>

              {overrideBanner && (
                <div
                  className="alert-info"
                  role="status"
                  style={{ marginBottom: 12 }}
                >
                  {overrideBanner}
                </div>
              )}
              {isSelfAccess(editingOverrideFor.access) && (
                <div
                  className="alert-warn"
                  role="alert"
                  style={{ marginBottom: 12 }}
                >
                  {t("customer_form.access_overrides_self_edit_warning")}
                </div>
              )}
              {editingOverrideFor.access.is_active === false && (
                <div
                  className="alert-warn"
                  role="alert"
                  style={{ marginBottom: 12 }}
                >
                  {t("customer_form.access_overrides_inactive_warning")}
                </div>
              )}

              <div className="table-wrap">
                <table
                  className="data-table"
                  data-testid="customer-overrides-table"
                >
                  <tbody>
                    {CUSTOMER_PERMISSION_KEYS.map((key) => {
                      const value = overrideDraft[key] ?? "inherit";
                      return (
                        <tr
                          key={key}
                          data-testid="customer-overrides-row"
                          data-permission-key={key}
                        >
                          <td className="td-subject">
                            {t(`customer_form.permission_key.${key}`)}
                            <div
                              className="muted small"
                              style={{
                                fontFamily: "monospace",
                                fontSize: 11,
                              }}
                            >
                              {key}
                            </div>
                          </td>
                          <td>
                            <div
                              role="radiogroup"
                              aria-label={key}
                              style={{ display: "inline-flex", gap: 12 }}
                            >
                              {(["inherit", "grant", "revoke"] as const).map(
                                (opt) => (
                                  <label
                                    key={opt}
                                    style={{
                                      display: "inline-flex",
                                      alignItems: "center",
                                      gap: 4,
                                      fontSize: 12,
                                      cursor: isSelfAccess(
                                        editingOverrideFor.access,
                                      )
                                        ? "default"
                                        : "pointer",
                                    }}
                                  >
                                    <input
                                      type="radio"
                                      name={`override-${key}`}
                                      value={opt}
                                      data-testid="customer-overrides-radio"
                                      data-permission-key={key}
                                      data-tristate={opt}
                                      checked={value === opt}
                                      disabled={
                                        overrideSaving ||
                                        isSelfAccess(editingOverrideFor.access)
                                      }
                                      onChange={() =>
                                        setOverrideDraft((prev) => ({
                                          ...prev,
                                          [key]: opt,
                                        }))
                                      }
                                    />
                                    <span>
                                      {t(
                                        `customer_form.access_overrides_${opt}`,
                                      )}
                                    </span>
                                  </label>
                                ),
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div
                className="form-actions"
                style={{ display: "flex", gap: 8, marginTop: 12 }}
              >
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={closeOverrideEditor}
                  disabled={overrideSaving}
                  data-testid="customer-overrides-close"
                >
                  {t("customer_form.access_overrides_close")}
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleSaveOverrides}
                  data-testid="customer-overrides-save"
                  disabled={
                    overrideSaving ||
                    isSelfAccess(editingOverrideFor.access)
                  }
                >
                  {overrideSaving
                    ? t("admin_form.saving")
                    : t("customer_form.access_overrides_save")}
                </button>
              </div>
            </section>
          )}

          <form
            className="card"
            data-testid="section-customer-company-policy"
            style={{ padding: "20px 22px" }}
            onSubmit={handleSavePolicy}
          >
            <h3 className="section-title">
              {t("customer_form.policy_title")}
            </h3>
            <p className="muted small" style={{ marginBottom: 12 }}>
              {t("customer_form.policy_helper")}
            </p>

            {policyBanner && (
              <div
                className="alert-info"
                role="status"
                style={{ marginBottom: 12 }}
              >
                {policyBanner}
              </div>
            )}
            {policyError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
              >
                {policyError}
              </div>
            )}

            {policyLoading || !policy ? (
              <div className="loading-bar">
                <div className="loading-bar-fill" />
              </div>
            ) : (
              <>
                {(
                  [
                    [
                      "customer_users_can_create_tickets",
                      "customer_form.policy_field_create_tickets",
                    ],
                    [
                      "customer_users_can_approve_ticket_completion",
                      "customer_form.policy_field_approve_ticket_completion",
                    ],
                    [
                      "customer_users_can_create_extra_work",
                      "customer_form.policy_field_create_extra_work",
                    ],
                    [
                      "customer_users_can_approve_extra_work_pricing",
                      "customer_form.policy_field_approve_extra_work_pricing",
                    ],
                  ] as const
                ).map(([field, label]) => (
                  <div className="field" key={field}>
                    <label
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        cursor: policySaving ? "default" : "pointer",
                      }}
                    >
                      <input
                        type="checkbox"
                        data-testid="customer-policy-toggle"
                        data-policy-field={field}
                        checked={policyDraft[field]}
                        onChange={(event) =>
                          setPolicyDraft((prev) => ({
                            ...prev,
                            [field]: event.target.checked,
                          }))
                        }
                        disabled={policySaving}
                      />
                      <span>{t(label)}</span>
                    </label>
                  </div>
                ))}

                <div className="form-actions">
                  <button
                    type="submit"
                    className="btn btn-primary"
                    data-testid="customer-policy-save"
                    disabled={policySaving}
                  >
                    {policySaving
                      ? t("admin_form.saving")
                      : t("customer_form.policy_save")}
                  </button>
                </div>
              </>
            )}
          </form>

          <ConfirmDialog
            ref={revokeAccessDialogRef}
            title={t("customer_form.dialog_revoke_access_title", {
              email: revokeAccessTarget?.membership.user_email ?? "",
              building: revokeAccessTarget?.access.building_name ?? "",
            })}
            body={t("customer_form.dialog_revoke_access_body")}
            confirmLabel={t("customer_form.access_remove_button")}
            onConfirm={handleConfirmRevokeAccess}
            onCancel={() => setRevokeAccessTarget(null)}
            busy={accessBusyUserId !== null}
            destructive
          />
        </>
      ) : null}
    </div>
  );
}
