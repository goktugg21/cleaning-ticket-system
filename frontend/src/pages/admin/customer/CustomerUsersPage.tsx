import type { FormEvent } from "react";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import {
  addCustomerUser,
  getCustomer,
  listCustomerBuildings,
  listCustomerUserAccess,
  listCustomerUsers,
  listUsers,
  removeCustomerUser,
} from "../../../api/admin";
import type {
  CustomerAccessRole,
  CustomerAdmin,
  CustomerBuildingMembership,
  CustomerUserBuildingAccess,
  CustomerUserMembership,
  UserAdmin,
} from "../../../api/types";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";

import { CustomerSubPageHeader } from "./CustomerSubPageHeader";
import { CustomerUserManageModal } from "./CustomerUserManageModal";

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

// The three filterable effective access roles offered in the access-role
// filter dropdown. "" means "All" (the param is omitted server-side).
const ACCESS_ROLE_FILTER_OPTIONS: CustomerAccessRole[] = [
  "CUSTOMER_COMPANY_ADMIN",
  "CUSTOMER_LOCATION_MANAGER",
  "CUSTOMER_USER",
];

export function CustomerUsersPage() {
  const { id } = useParams();
  const { t } = useTranslation("common");

  const numericId = useMemo(() => {
    if (!id) return null;
    const parsed = Number(id);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [id]);

  const [customer, setCustomer] = useState<CustomerAdmin | null>(null);
  const [members, setMembers] = useState<CustomerUserMembership[]>([]);
  const [availableUsers, setAvailableUsers] = useState<UserAdmin[]>([]);
  const [buildings, setBuildings] = useState<CustomerBuildingMembership[]>([]);
  const [accessByUserId, setAccessByUserId] = useState<
    Record<number, CustomerUserBuildingAccess[]>
  >({});
  // Filter bar (Ramazan's 40+-people pain). Access-role + building are
  // SERVER-SIDE (passed through to ?access_role / ?building_id); search
  // is CLIENT-SIDE over the loaded members. "" = All (param omitted).
  const [filterAccessRole, setFilterAccessRole] = useState<
    CustomerAccessRole | ""
  >("");
  const [filterBuildingId, setFilterBuildingId] = useState<number | "">("");
  const [searchText, setSearchText] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [memberError, setMemberError] = useState("");
  const [memberBusy, setMemberBusy] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState<number | "">("");

  const removeDialogRef = useRef<ConfirmDialogHandle>(null);
  const [removeTarget, setRemoveTarget] =
    useState<CustomerUserMembership | null>(null);

  // SoT Addendum A.2 — DRILL-IN replaces the old inline accordion. A
  // row's "Manage" action opens a modal (CustomerUserManageModal) that
  // hosts the company-admin toggle + the per-building access editor +
  // the permission-override modal. "Click a row, edit, leave" — no
  // inline expansion.
  const [manageTarget, setManageTarget] =
    useState<CustomerUserMembership | null>(null);

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

  // Build the server-side member-list params from the current filter
  // state. Empty/All filters are omitted so the backend returns the full
  // list. The caller may pass explicit overrides (used by the filter-
  // change refetch effect so it never races the not-yet-committed state).
  function memberListParams(overrides?: {
    accessRole?: CustomerAccessRole | "";
    buildingId?: number | "";
  }): { access_role?: string; building_id?: number } {
    const accessRole = overrides?.accessRole ?? filterAccessRole;
    const buildingId = overrides?.buildingId ?? filterBuildingId;
    const params: { access_role?: string; building_id?: number } = {};
    if (accessRole !== "") params.access_role = accessRole;
    if (buildingId !== "") params.building_id = buildingId;
    return params;
  }

  async function reloadMembers(
    customerId: number,
    overrides?: {
      accessRole?: CustomerAccessRole | "";
      buildingId?: number | "";
    },
  ) {
    try {
      const [membersResponse, candidatesResponse] = await Promise.all([
        listCustomerUsers(customerId, memberListParams(overrides)),
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
    // Initial load runs with no filters committed yet (the filter state
    // is "" / "" at mount), so the member list comes back unfiltered.
    // Building options come from listCustomerBuildings — the same source
    // the Permissions / Contacts pages use for their building dropdowns.
    Promise.all([
      getCustomer(numericId),
      listCustomerUsers(numericId),
      listUsers({ role: "CUSTOMER_USER", page_size: 200 }),
      listCustomerBuildings(numericId),
    ])
      .then(
        async ([
          customerData,
          membersResponse,
          candidatesResponse,
          buildingsResponse,
        ]) => {
          if (cancelled) return;
          setCustomer(customerData);
          setBuildings(buildingsResponse.results);
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
        },
      )
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

  // Server-side filter refetch. The initial-load effect above already
  // fetched once with empty filters, so skip the very first run of this
  // effect; thereafter, any change to the access-role or building filter
  // re-fetches the member list (and its access pills) with the new
  // params. Search is purely client-side, so it deliberately does NOT
  // appear in the dependency list. All setState happens inside the async
  // reload closure after an await — never synchronously in the effect
  // body — so there is no set-state-in-effect.
  const didMountFilterRef = useRef(false);
  useEffect(() => {
    if (numericId === null) return;
    if (!didMountFilterRef.current) {
      didMountFilterRef.current = true;
      return;
    }
    void reloadMembers(numericId);
    // reloadMembers reads the latest filter state via memberListParams;
    // the effect fires on filter changes and numericId resets.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numericId, filterAccessRole, filterBuildingId]);

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

  // Client-side free-text search over the loaded (already server-
  // filtered) members. Matches on email + full name, case-insensitive.
  // An empty query shows every loaded member.
  const visibleMembers = useMemo(() => {
    const query = searchText.trim().toLowerCase();
    if (query === "") return members;
    return members.filter((m) => {
      const haystack = `${m.user_email} ${m.user_full_name ?? ""}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [members, searchText]);

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

            {/* Filter bar — access-role + building are SERVER-SIDE
                (passed through to ?access_role / ?building_id); search is
                CLIENT-SIDE over the loaded members. */}
            <div
              className="customer-users-filter-bar"
              data-testid="customer-users-filter-bar"
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 10,
                marginBottom: 14,
                alignItems: "flex-end",
              }}
            >
              <div className="field" style={{ marginBottom: 0, minWidth: 200 }}>
                <label
                  className="field-label"
                  htmlFor="customer-users-filter-access-role"
                >
                  {t("customer_view.users.filter_access_role_label")}
                </label>
                <select
                  id="customer-users-filter-access-role"
                  className="field-select"
                  data-testid="customer-users-filter-access-role"
                  value={filterAccessRole}
                  onChange={(event) =>
                    setFilterAccessRole(
                      event.target.value as CustomerAccessRole | "",
                    )
                  }
                >
                  <option value="">
                    {t("customer_view.users.filter_access_role_all")}
                  </option>
                  {ACCESS_ROLE_FILTER_OPTIONS.map((role) => (
                    <option key={role} value={role}>
                      {t(ACCESS_ROLE_LABEL[role])}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field" style={{ marginBottom: 0, minWidth: 200 }}>
                <label
                  className="field-label"
                  htmlFor="customer-users-filter-building"
                >
                  {t("customer_view.users.filter_building_label")}
                </label>
                <select
                  id="customer-users-filter-building"
                  className="field-select"
                  data-testid="customer-users-filter-building"
                  value={filterBuildingId === "" ? "" : String(filterBuildingId)}
                  onChange={(event) => {
                    const v = event.target.value;
                    setFilterBuildingId(v === "" ? "" : Number(v));
                  }}
                >
                  <option value="">
                    {t("customer_view.users.filter_building_all")}
                  </option>
                  {buildings.map((link) => (
                    <option key={link.id} value={link.building_id}>
                      {link.building_name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field" style={{ marginBottom: 0, flex: 1, minWidth: 200 }}>
                <label
                  className="field-label"
                  htmlFor="customer-users-filter-search"
                >
                  {t("customer_view.users.filter_search_label")}
                </label>
                <input
                  id="customer-users-filter-search"
                  className="field-input"
                  type="search"
                  data-testid="customer-users-filter-search"
                  value={searchText}
                  onChange={(event) => setSearchText(event.target.value)}
                  placeholder={t("customer_view.users.filter_search_placeholder")}
                />
              </div>
            </div>

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
                  {visibleMembers.map((membership) => {
                    const access = accessByUserId[membership.user_id] ?? [];
                    const isCompanyAdmin = membership.is_company_admin === true;
                    return (
                      <Fragment key={membership.id}>
                        <tr data-testid="customer-user-row">
                          <td className="td-subject">{membership.user_email}</td>
                          <td>{membership.user_full_name || "—"}</td>
                          <td data-testid="customer-user-access-summary">
                            {isCompanyAdmin ? (
                              // SoT Addendum A.1 — a company-wide CCA is
                              // ONE status across all buildings; the
                              // per-building pills are hidden for them.
                              <div
                                className="customer-user-access-pills"
                                data-testid="customer-user-company-admin-pill"
                              >
                                <span
                                  className="customer-user-access-pill"
                                  title={t(
                                    "customer_people.company_admin.all_buildings_caption",
                                  )}
                                >
                                  <span>
                                    {t(
                                      ACCESS_ROLE_LABEL.CUSTOMER_COMPANY_ADMIN,
                                    )}
                                  </span>
                                  <span aria-hidden="true">·</span>
                                  <span>
                                    {t(
                                      "customer_people.company_admin.all_buildings_short",
                                    )}
                                  </span>
                                </span>
                              </div>
                            ) : access.length === 0 ? (
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
                          </td>
                          <td>
                            <div style={{ display: "flex", gap: 6 }}>
                              <button
                                type="button"
                                className="btn btn-secondary btn-sm"
                                data-testid="customer-user-manage-button"
                                onClick={() => setManageTarget(membership)}
                              >
                                {t("customer_people.manage_button")}
                              </button>
                              {canManageMembers && (
                                <button
                                  type="button"
                                  className="btn btn-ghost btn-sm"
                                  onClick={() => openRemoveDialog(membership)}
                                >
                                  {t("admin_form.remove")}
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
              {members.length === 0 ? (
                <p
                  className="muted small"
                  style={{ padding: "12px 0" }}
                  data-testid="customer-users-empty"
                >
                  {t("customer_form.no_users_yet")}
                </p>
              ) : visibleMembers.length === 0 ? (
                <p
                  className="muted small"
                  style={{ padding: "12px 0" }}
                  data-testid="customer-users-no-matches"
                >
                  {t("customer_view.users.filter_no_matches")}
                </p>
              ) : null}
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

      {/* SoT Addendum A.2 — drill-in modal (replaces the old accordion).
          Keyed by user id so the prop-derived membership sub-state never
          resyncs in an effect. */}
      {manageTarget && numericId !== null && (
        <CustomerUserManageModal
          key={manageTarget.user_id}
          customerId={numericId}
          userId={manageTarget.user_id}
          userLabel={manageTarget.user_full_name || manageTarget.user_email}
          onClose={() => setManageTarget(null)}
          onChanged={() => reloadMembers(numericId)}
        />
      )}
    </div>
  );
}

