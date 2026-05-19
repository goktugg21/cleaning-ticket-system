import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
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
  CustomerPermissionKey,
  CustomerUserBuildingAccess,
  CustomerUserMembership,
} from "../../../api/types";
import { CUSTOMER_PERMISSION_KEYS } from "../../../api/types";
import { useAuth } from "../../../auth/AuthContext";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";
import { EmptyState } from "../../../components/EmptyState";
import { StickySaveBar } from "../../../components/StickySaveBar";
import { useToast } from "../../../components/ToastProvider";
import { useTechnicalKeysToggle } from "../../../hooks/useTechnicalKeysToggle";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";
import { OverrideDrawer } from "./permissions/OverrideDrawer";
import type { OverrideDraft } from "./permissions/OverrideDrawer";
import { PolicyToggleGrid } from "./permissions/PolicyToggleGrid";
import type { PolicyDraft } from "./permissions/PolicyToggleGrid";
import { UserAccessCard } from "./permissions/UserAccessCard";
import { ZoneHeader } from "./permissions/ZoneHeader";
import {
  buildOverridesPayload,
  draftValueFromOverride,
} from "./permissions/effectiveResolver";
import { Users as UsersIcon } from "lucide-react";

/**
 * Sprint 28 Batch 15.2 — Customer Permissions page rebuild.
 *
 * Reorganises the page into three vertical zones:
 *   1. Customer-company policy (upstream constraint) — 2x2 toggle
 *      cards + StickySaveBar.
 *   2. Users and building access — one card per CustomerUserMembership
 *      with per-building chips for sub-role + active + a custom-
 *      permissions pill.
 *   3. Override drawer — slides in from the right when the operator
 *      clicks a "Custom permissions" pill. Shows the 16 customer
 *      permission keys grouped by domain with tri-state inherit /
 *      allow / deny radios + an inline Effective: ... hint computed
 *      against the current policy + sub-role.
 *
 * All locked testids (customer-permissions-page,
 * section-customer-company-policy, section-customer-users,
 * section-customer-overrides-editor on the drawer,
 * customer-access-badge, customer-access-role-select,
 * customer-access-active-toggle, customer-access-overrides-button,
 * customer-overrides-table, customer-overrides-row,
 * customer-overrides-radio, customer-overrides-close,
 * customer-overrides-save, customer-policy-toggle,
 * customer-policy-save, customer-user-access-summary) are preserved.
 *
 * Per-access changes (sub-role, active toggle, add/remove building)
 * still save immediately; only policy and overrides are drafted.
 */
export function CustomerPermissionsPage() {
  const { id } = useParams();
  const { t } = useTranslation("common");
  const { me } = useAuth();
  const { push: pushToast } = useToast();

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  // ------- Top-level data state -------
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
  const [accessBusyUserId, setAccessBusyUserId] = useState<number | null>(null);

  // ------- Override drawer state -------
  const [editingOverrideFor, setEditingOverrideFor] = useState<{
    membership: CustomerUserMembership;
    access: CustomerUserBuildingAccess;
  } | null>(null);
  const emptyOverrideDraft = useMemo<OverrideDraft>(() => {
    const d = {} as OverrideDraft;
    for (const key of CUSTOMER_PERMISSION_KEYS) d[key] = "inherit";
    return d;
  }, []);
  const [overrideDraft, setOverrideDraft] =
    useState<OverrideDraft>(emptyOverrideDraft);
  const [overrideSaving, setOverrideSaving] = useState(false);

  // ------- Revoke-access dialog state -------
  const revokeAccessDialogRef = useRef<ConfirmDialogHandle>(null);
  const [revokeAccessTarget, setRevokeAccessTarget] = useState<{
    membership: CustomerUserMembership;
    access: CustomerUserBuildingAccess;
  } | null>(null);

  // ------- Policy panel state -------
  const [policy, setPolicy] = useState<CustomerCompanyPolicyAdmin | null>(null);
  const [policyLoading, setPolicyLoading] = useState(true);
  const [policyError, setPolicyError] = useState("");
  const [policySaving, setPolicySaving] = useState(false);
  const [policyDraft, setPolicyDraft] = useState<PolicyDraft>({
    customer_users_can_create_tickets: true,
    customer_users_can_approve_ticket_completion: true,
    customer_users_can_create_extra_work: true,
    customer_users_can_approve_extra_work_pricing: true,
  });

  const isSelfAccess = (access: CustomerUserBuildingAccess) =>
    me?.id === access.user_id;
  const canGrantCustomerCompanyAdmin = me?.role === "SUPER_ADMIN";

  // Sprint 29 Batch 29.1 — operator-controlled toggle for the
  // "Affects: customer.ticket.approve_own, ..." sub-lines on
  // each policy card. Default OFF; persisted in localStorage.
  const [showTechKeys, setShowTechKeys] = useTechnicalKeysToggle();

  // ------- Initial load -------
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

  // ------- Per-user building access load -------
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

  // ------- Policy load -------
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

  const isPolicyDirty = useMemo(() => {
    if (!policy) return false;
    return (
      policyDraft.customer_users_can_create_tickets !==
        policy.customer_users_can_create_tickets ||
      policyDraft.customer_users_can_approve_ticket_completion !==
        policy.customer_users_can_approve_ticket_completion ||
      policyDraft.customer_users_can_create_extra_work !==
        policy.customer_users_can_create_extra_work ||
      policyDraft.customer_users_can_approve_extra_work_pricing !==
        policy.customer_users_can_approve_extra_work_pricing
    );
  }, [policy, policyDraft]);

  // ------- Helpers ------------------------------------------------------

  async function reloadAccessFor(userId: number) {
    if (numericId === null) return;
    try {
      const response = await listCustomerUserAccess(numericId, userId);
      setAccessByUserId((prev) => ({ ...prev, [userId]: response.results }));
    } catch (err) {
      pushToast({
        variant: "error",
        title: t("customer_permissions.toast_save_failed"),
        description: getApiError(err),
      });
    }
  }

  function pushSaveFailure(err: unknown) {
    pushToast({
      variant: "error",
      title: t("customer_permissions.toast_save_failed"),
      description: getApiError(err),
    });
  }

  // ------- Per-access handlers (immediate-save) -------------------------

  async function handleAddAccess(
    membership: CustomerUserMembership,
    buildingId: number,
  ) {
    if (numericId === null) return;
    setAccessBusyUserId(membership.user_id);
    try {
      await addCustomerUserAccess(numericId, membership.user_id, buildingId);
      await reloadAccessFor(membership.user_id);
      pushToast({
        variant: "success",
        title: t("customer_permissions.toast_access_added"),
      });
    } catch (err) {
      pushSaveFailure(err);
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
    setAccessBusyUserId(membership.user_id);
    try {
      await updateCustomerUserAccessRole(
        numericId,
        membership.user_id,
        access.building_id,
        newRole,
      );
      await reloadAccessFor(membership.user_id);
      pushToast({
        variant: "success",
        title: t("customer_permissions.toast_access_role_saved"),
      });
    } catch (err) {
      pushSaveFailure(err);
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
    setAccessBusyUserId(membership.user_id);
    try {
      await updateCustomerUserAccess(
        numericId,
        membership.user_id,
        access.building_id,
        { is_active: nextActive },
      );
      await reloadAccessFor(membership.user_id);
      pushToast({
        variant: "success",
        title: t("customer_permissions.toast_access_active_saved", {
          state: nextActive
            ? t("customer_permissions.toast_access_active_state.active")
            : t("customer_permissions.toast_access_active_state.inactive"),
        }),
      });
    } catch (err) {
      pushSaveFailure(err);
    } finally {
      setAccessBusyUserId(null);
    }
  }

  // ------- Override drawer handlers -------------------------------------

  function openOverrideEditor(
    membership: CustomerUserMembership,
    access: CustomerUserBuildingAccess,
  ) {
    const draft = {} as OverrideDraft;
    for (const key of CUSTOMER_PERMISSION_KEYS) {
      draft[key as CustomerPermissionKey] = draftValueFromOverride(
        access.permission_overrides ?? {},
        key as CustomerPermissionKey,
      );
    }
    setOverrideDraft(draft);
    setEditingOverrideFor({ membership, access });
  }

  function closeOverrideEditor() {
    setEditingOverrideFor(null);
    setOverrideDraft(emptyOverrideDraft);
  }

  async function handleSaveOverrides() {
    if (numericId === null || !editingOverrideFor) return;
    const { membership, access } = editingOverrideFor;
    setOverrideSaving(true);
    try {
      await updateCustomerUserAccess(
        numericId,
        membership.user_id,
        access.building_id,
        { permission_overrides: buildOverridesPayload(overrideDraft) },
      );
      await reloadAccessFor(membership.user_id);
      pushToast({
        variant: "success",
        title: t("customer_permissions.toast_overrides_saved"),
      });
      closeOverrideEditor();
    } catch (err) {
      pushSaveFailure(err);
    } finally {
      setOverrideSaving(false);
    }
  }

  // ------- Revoke access dialog -----------------------------------------

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
    setAccessBusyUserId(membership.user_id);
    try {
      await removeCustomerUserAccess(
        numericId,
        membership.user_id,
        access.building_id,
      );
      await reloadAccessFor(membership.user_id);
      revokeAccessDialogRef.current?.close();
      setRevokeAccessTarget(null);
      pushToast({
        variant: "success",
        title: t("customer_permissions.toast_access_removed"),
      });
    } catch (err) {
      pushSaveFailure(err);
      revokeAccessDialogRef.current?.close();
    } finally {
      setAccessBusyUserId(null);
    }
  }

  // ------- Policy save --------------------------------------------------

  async function handleSavePolicy() {
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
      pushToast({
        variant: "success",
        title: t("customer_permissions.toast_policy_saved"),
      });
    } catch (err) {
      const message = getApiError(err);
      setPolicyError(message);
      pushToast({
        variant: "error",
        title: t("customer_permissions.toast_save_failed"),
        description: message,
      });
    } finally {
      setPolicySaving(false);
    }
  }

  // Sprint 29 Batch 29.2 — focus-on-mount via URL params. The Edit
  // Basics page deep-links here with ?focus_user=<id> (row-level) or
  // ?focus_user=<id>&focus_building=<id> (per-chip). After the
  // customer + per-user access lists resolve, scroll the matching
  // UserAccessCard into view, optionally open the OverrideDrawer for
  // that (user, building) pair, and consume the params so a refresh
  // does not re-fire the effect.
  const [searchParams, setSearchParams] = useSearchParams();
  const focusUserParam = searchParams.get("focus_user");
  const focusBuildingParam = searchParams.get("focus_building");
  const focusConsumedRef = useRef(false);

  useEffect(() => {
    if (focusConsumedRef.current) return;
    if (!focusUserParam || loading || !customer) return;
    const userIdNum = Number(focusUserParam);
    if (!Number.isFinite(userIdNum) || userIdNum <= 0) {
      focusConsumedRef.current = true;
      return;
    }
    const membership = members.find((m) => m.user_id === userIdNum) ?? null;
    if (!membership) {
      // User is not in the customer's membership list — silently
      // drop the params and render the page normally.
      focusConsumedRef.current = true;
      const next = new URLSearchParams(searchParams);
      next.delete("focus_user");
      next.delete("focus_building");
      setSearchParams(next, { replace: true });
      return;
    }

    const userCard = document.getElementById(`user-access-card-${userIdNum}`);
    if (userCard) {
      userCard.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    if (focusBuildingParam) {
      const buildingIdNum = Number(focusBuildingParam);
      if (Number.isFinite(buildingIdNum) && buildingIdNum > 0) {
        const accesses = accessByUserId[userIdNum] ?? [];
        const access =
          accesses.find((a) => a.building_id === buildingIdNum) ?? null;
        if (access) {
          // Defer the drawer-opening setState off the effect tick so
          // it does not chain with the searchParams replace below
          // (the existing CustomerPermissionsPage useEffects use the
          // same queueMicrotask pattern for the same reason).
          queueMicrotask(() => openOverrideEditor(membership, access));
        }
      }
    }

    focusConsumedRef.current = true;
    const next = new URLSearchParams(searchParams);
    next.delete("focus_user");
    next.delete("focus_building");
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    focusUserParam,
    focusBuildingParam,
    loading,
    customer,
    members,
    accessByUserId,
  ]);

  const customerName = customer?.name ?? "";
  const isActive = customer?.is_active ?? true;
  const editingAccess = editingOverrideFor?.access ?? null;
  const editingMembership = editingOverrideFor?.membership ?? null;
  const editingIsSelf = editingAccess ? isSelfAccess(editingAccess) : false;

  return (
    <div data-testid="customer-permissions-page">
      <CustomerSubPageHeader customerName={customerName} isActive={isActive} />

      {loadError && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
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

          {/* ------------------- Zone 1 — Policy --------------------- */}
          <section
            className="card permissions-zone permissions-zone-policy"
            data-testid="section-customer-company-policy"
          >
            <ZoneHeader
              title={t("customer_permissions.zone_policy_title")}
              helper={t("customer_permissions.zone_policy_helper")}
            />

            <label
              className="tech-keys-toggle"
              data-testid="show-technical-keys-toggle"
            >
              <input
                type="checkbox"
                checked={showTechKeys}
                onChange={(e) => setShowTechKeys(e.target.checked)}
              />
              <span>{t("customer_permissions.show_technical_keys")}</span>
            </label>

            {policyError && (
              <div className="alert-error" role="alert">
                {policyError}
              </div>
            )}

            {policyLoading || !policy ? (
              <div className="loading-bar">
                <div className="loading-bar-fill" />
              </div>
            ) : (
              <>
                <PolicyToggleGrid
                  draft={policyDraft}
                  setDraft={setPolicyDraft}
                  disabled={policySaving}
                  showTechnicalKeys={showTechKeys}
                />
                <StickySaveBar
                  dirty={isPolicyDirty}
                  saving={policySaving}
                  onSave={handleSavePolicy}
                  onCancel={() =>
                    policy &&
                    setPolicyDraft({
                      customer_users_can_create_tickets:
                        policy.customer_users_can_create_tickets,
                      customer_users_can_approve_ticket_completion:
                        policy.customer_users_can_approve_ticket_completion,
                      customer_users_can_create_extra_work:
                        policy.customer_users_can_create_extra_work,
                      customer_users_can_approve_extra_work_pricing:
                        policy.customer_users_can_approve_extra_work_pricing,
                    })
                  }
                  testId="customer-policy-save-bar"
                  saveTestId="customer-policy-save"
                />
              </>
            )}
          </section>

          {/* ------------------- Zone 2 — Users ---------------------- */}
          <section
            className="card permissions-zone permissions-zone-users"
            data-testid="section-customer-users"
          >
            <ZoneHeader
              title={t("customer_permissions.zone_users_title")}
              helper={t("customer_permissions.zone_users_helper")}
            />

            {members.length === 0 ? (
              <EmptyState
                icon={UsersIcon}
                title={t("customer_permissions.no_members_yet")}
                description={t("customer_view.users.explainer", {
                  customer: customerName,
                })}
              />
            ) : (
              <div className="permissions-user-cards">
                {members.map((membership) => (
                  <UserAccessCard
                    key={membership.id}
                    customerId={customer.id}
                    customerName={customerName}
                    membership={membership}
                    accesses={accessByUserId[membership.user_id] ?? []}
                    linkedBuildings={linkedBuildings}
                    policy={policy}
                    meId={me?.id}
                    canGrantCustomerCompanyAdmin={canGrantCustomerCompanyAdmin}
                    busy={accessBusyUserId === membership.user_id}
                    onRoleChange={(access, newRole) =>
                      handleAccessRoleChange(membership, access, newRole)
                    }
                    onActiveToggle={(access, nextActive) =>
                      handleToggleAccessActive(membership, access, nextActive)
                    }
                    onOpenOverrides={(access) =>
                      openOverrideEditor(membership, access)
                    }
                    onRemoveAccess={(access) =>
                      openRevokeAccessDialog(membership, access)
                    }
                    onAddBuilding={(buildingId) =>
                      handleAddAccess(membership, buildingId)
                    }
                  />
                ))}
              </div>
            )}
          </section>

          {/* ------------------- Zone 3 — Override drawer ------------ */}
          <OverrideDrawer
            open={editingOverrideFor !== null}
            membership={editingMembership}
            access={editingAccess}
            policy={policy}
            draft={overrideDraft}
            setDraft={setOverrideDraft}
            onClose={closeOverrideEditor}
            onSave={handleSaveOverrides}
            saving={overrideSaving}
            isSelf={editingIsSelf}
          />

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




