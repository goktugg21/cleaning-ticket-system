import type { FormEvent } from "react";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import {
  addCustomerUser,
  getCustomer,
  listCustomerUserAccess,
  listCustomerUsers,
  listUsers,
  removeCustomerUser,
} from "../../../api/admin";
import type {
  CustomerAccessRole,
  CustomerAdmin,
  CustomerUserBuildingAccess,
  CustomerUserMembership,
  UserAdmin,
} from "../../../api/types";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";
import { PermissionsRollupChip } from "../../../components/PermissionsRollupChip";
import { PermissionsRollupSummary } from "../../../components/PermissionsRollupSummary";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";

/**
 * Sprint 28 Batch 13 (rework) — Customer Users page (admin variant).
 *
 * Members add/remove + per-user per-building access summary. The
 * editor for access role + permission overrides + the customer-
 * company policy still lives on the Permissions sub-page; this page
 * only SURFACES the access pills so an operator can see what the
 * current users can do at a glance and jump to Permissions to edit.
 */
const ACCESS_ROLE_LABEL: Record<CustomerAccessRole, string> = {
  CUSTOMER_USER: "access_role.customer_user",
  CUSTOMER_LOCATION_MANAGER: "access_role.customer_location_manager",
  CUSTOMER_COMPANY_ADMIN: "access_role.customer_company_admin",
};

export function CustomerUsersPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation("common");

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [members, setMembers] = useState<CustomerUserMembership[]>([]);
  const [availableUsers, setAvailableUsers] = useState<UserAdmin[]>([]);
  const [accessByUserId, setAccessByUserId] = useState<
    Record<number, CustomerUserBuildingAccess[]>
  >({});
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [memberError, setMemberError] = useState("");
  const [memberBusy, setMemberBusy] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState<number | "">("");

  const removeDialogRef = useRef<ConfirmDialogHandle>(null);
  const [removeTarget, setRemoveTarget] =
    useState<CustomerUserMembership | null>(null);

  // Sprint 29 Batch 29.8.5 — per-row toggle for the inline
  // <PermissionsRollupSummary>. Single-expansion: clicking another row
  // collapses the previous one. The summary surfaces every (building,
  // role, override-count) tuple inline so the operator does not need
  // to navigate away.
  const [summaryUserId, setSummaryUserId] = useState<number | null>(null);

  async function loadAccessForMembers(
    customerId: number,
    rows: CustomerUserMembership[],
  ): Promise<Record<number, CustomerUserBuildingAccess[]>> {
    const next: Record<number, CustomerUserBuildingAccess[]> = {};
    // Per-user access endpoint is paginated server-side; we fan out
    // sequentially to keep the audit log on the backend readable. The
    // list is small in practice (members per customer rarely > ~20).
    for (const row of rows) {
      try {
        const response = await listCustomerUserAccess(customerId, row.user_id);
        next[row.user_id] = response.results;
      } catch {
        next[row.user_id] = [];
      }
    }
    return next;
  }

  async function reloadMembers(customerId: number) {
    try {
      const [membersResponse, candidatesResponse] = await Promise.all([
        listCustomerUsers(customerId),
        listUsers({ role: "CUSTOMER_USER", page_size: 200 }),
      ]);
      setMembers(membersResponse.results);
      const memberIds = new Set(membersResponse.results.map((m) => m.user_id));
      setAvailableUsers(
        candidatesResponse.results.filter((u) => !memberIds.has(u.id)),
      );
      const access = await loadAccessForMembers(
        customerId,
        membersResponse.results,
      );
      setAccessByUserId(access);
    } catch (err) {
      setMemberError(getApiError(err));
    }
  }

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
      listUsers({ role: "CUSTOMER_USER", page_size: 200 }),
    ])
      .then(async ([customerData, membersResponse, candidatesResponse]) => {
        if (cancelled) return;
        setCustomer(customerData);
        setMembers(membersResponse.results);
        const memberIds = new Set(
          membersResponse.results.map((m) => m.user_id),
        );
        setAvailableUsers(
          candidatesResponse.results.filter((u) => !memberIds.has(u.id)),
        );
        const access = await loadAccessForMembers(
          numericId,
          membersResponse.results,
        );
        if (!cancelled) setAccessByUserId(access);
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

  async function handleAddMember(event: FormEvent) {
    event.preventDefault();
    if (numericId === null || selectedUserId === "") return;
    setMemberError("");
    setMemberBusy(true);
    try {
      await addCustomerUser(numericId, Number(selectedUserId));
      setSelectedUserId("");
      await reloadMembers(numericId);
    } catch (err) {
      setMemberError(getApiError(err));
    } finally {
      setMemberBusy(false);
    }
  }

  function openRemoveDialog(membership: CustomerUserMembership) {
    setRemoveTarget(membership);
    removeDialogRef.current?.open();
  }

  async function handleConfirmRemove() {
    if (numericId === null || !removeTarget) return;
    setMemberBusy(true);
    setMemberError("");
    try {
      await removeCustomerUser(numericId, removeTarget.user_id);
      removeDialogRef.current?.close();
      setRemoveTarget(null);
      await reloadMembers(numericId);
    } catch (err) {
      setMemberError(getApiError(err));
      removeDialogRef.current?.close();
    } finally {
      setMemberBusy(false);
    }
  }

  const customerName = customer?.name ?? "";
  const isActive = customer?.is_active ?? true;
  const customerNameDisplay = customer?.name ?? "";
  // Per-record action — drives whether the viewer can add or remove
  // customer-user memberships on THIS customer. Backend
  // (`compute_customer_actions`) returns True for SA, COMPANY_ADMIN in
  // scope, and CUSTOMER_USER whose customer-level
  // `customer.users.manage` resolves True (the CCA admit path). Absent
  // (older response) defaults to false — safer to hide the controls
  // than to show a button the API will 403.
  const canManageMembers =
    customer?.actions?.can_manage_customer_users === true;

  return (
    <div data-testid="customer-users-page">
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
            data-testid="customer-users-permissions-hint"
          >
            {t("customer_view.users.explainer", { customer: customerName })}{" "}
            <Link to={`/admin/customers/${customer.id}/permissions`}>
              {t("customer_view.users.permission_hint")}
            </Link>
          </p>

          <section
            className="card"
            data-testid="section-customer-users"
            style={{ padding: "20px 22px" }}
          >
            <h3 className="section-title">
              {t("customer_view.users.title")}
            </h3>
            <p className="muted small" style={{ marginBottom: 12 }}>
              {t("customer_form.section_users_desc")}
            </p>

            {memberError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
              >
                {memberError}
              </div>
            )}

            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{t("users.col_email")}</th>
                    <th>{t("users.col_full_name")}</th>
                    <th>{t("customer_form.col_user_access")}</th>
                    <th aria-label={t("admin.col_actions")} />
                  </tr>
                </thead>
                <tbody>
                  {members.map((membership) => {
                    const access = accessByUserId[membership.user_id] ?? [];
                    const isSummaryOpen = summaryUserId === membership.user_id;
                    return (
                      <Fragment key={membership.id}>
                        <tr data-testid="customer-user-row">
                          <td className="td-subject">{membership.user_email}</td>
                          <td>{membership.user_full_name || "—"}</td>
                          <td data-testid="customer-user-access-summary">
                            {access.length === 0 ? (
                              <span className="muted small">
                                {t("customer_view.users.no_access_yet")}
                              </span>
                            ) : (
                              <div className="customer-user-access-pills">
                                {access.map((row) => (
                                  <span
                                    key={row.id}
                                    className={
                                      "customer-user-access-pill" +
                                      (row.is_active === false
                                        ? " inactive"
                                        : "")
                                    }
                                    title={`${row.building_name} · ${t(
                                      ACCESS_ROLE_LABEL[row.access_role],
                                    )}`}
                                  >
                                    <span>{row.building_name}</span>
                                    <span aria-hidden="true">·</span>
                                    <span>
                                      {t(ACCESS_ROLE_LABEL[row.access_role])}
                                    </span>
                                  </span>
                                ))}
                              </div>
                            )}
                            {numericId !== null && (
                              <div style={{ marginTop: 6 }}>
                                <PermissionsRollupChip
                                  customerId={numericId}
                                  userId={membership.user_id}
                                  accesses={access}
                                  onToggle={() =>
                                    setSummaryUserId((current) =>
                                      current === membership.user_id
                                        ? null
                                        : membership.user_id,
                                    )
                                  }
                                  expanded={isSummaryOpen}
                                />
                              </div>
                            )}
                          </td>
                          <td>
                            {canManageMembers && (
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                onClick={() => openRemoveDialog(membership)}
                              >
                                {t("admin_form.remove")}
                              </button>
                            )}
                          </td>
                        </tr>
                        {isSummaryOpen && numericId !== null && (
                          <tr
                            className="customer-user-row-summary"
                            data-testid={`customer-user-row-summary-${membership.user_id}`}
                          >
                            <td colSpan={4}>
                              <PermissionsRollupSummary
                                userId={membership.user_id}
                                customerId={numericId}
                                userLabel={
                                  membership.user_full_name ||
                                  membership.user_email
                                }
                                customerLabel={customerName}
                                accesses={access}
                                onOpenOverrides={(access) => {
                                  // The override drawer lives on the
                                  // Permissions page, not here.
                                  // Deep-link via 29.2's
                                  // ?focus_user=&focus_building= shape
                                  // so the drawer auto-opens on that
                                  // specific row.
                                  navigate(
                                    `/admin/customers/${numericId}/permissions?focus_user=${membership.user_id}&focus_building=${access.building_id}`,
                                  );
                                }}
                                onCollapse={() => setSummaryUserId(null)}
                              />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
              {members.length === 0 && (
                <p
                  className="muted small"
                  style={{ padding: "12px 0" }}
                  data-testid="customer-users-empty"
                >
                  {t("customer_form.no_users_yet")}
                </p>
              )}
            </div>

            {canManageMembers && (
            <form
              onSubmit={handleAddMember}
              style={{
                display: "flex",
                gap: 8,
                marginTop: 12,
                alignItems: "flex-end",
              }}
            >
              <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                <label className="field-label" htmlFor="add-customer-user">
                  {t("customer_form.add_user")}
                </label>
                <select
                  id="add-customer-user"
                  className="field-select"
                  value={selectedUserId === "" ? "" : String(selectedUserId)}
                  onChange={(event) => {
                    const v = event.target.value;
                    setSelectedUserId(v === "" ? "" : Number(v));
                  }}
                  disabled={memberBusy || availableUsers.length === 0}
                >
                  <option value="">
                    {availableUsers.length === 0
                      ? t("admin_form.no_eligible_users")
                      : t("admin_form.select_user")}
                  </option>
                  {availableUsers.map((user) => (
                    <option key={user.id} value={user.id}>
                      {user.email}
                      {user.full_name ? ` — ${user.full_name}` : ""}
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="submit"
                className="btn btn-primary"
                data-testid="member-add-button"
                disabled={memberBusy || selectedUserId === ""}
              >
                {memberBusy ? t("admin_form.adding") : t("admin_form.add")}
              </button>
            </form>
            )}

            <ConfirmDialog
              ref={removeDialogRef}
              title={t("customer_form.dialog_remove_title", {
                email: removeTarget?.user_email ?? "",
                name: customerNameDisplay,
              })}
              body={t("customer_form.dialog_remove_body")}
              confirmLabel={t("admin_form.remove")}
              onConfirm={handleConfirmRemove}
              onCancel={() => setRemoveTarget(null)}
              busy={memberBusy}
            />
          </section>
        </>
      ) : null}
    </div>
  );
}

