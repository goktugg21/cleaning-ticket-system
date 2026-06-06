import { useCallback, useEffect, useMemo, useState } from "react";
import { Contact, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../api/client";
import {
  listCustomerEmployees,
  listCustomerUserAccess,
  updateCustomerUserAccessRole,
} from "../api/admin";
import type {
  CustomerAccessRole,
  CustomerEmployee,
  CustomerUserBuildingAccess,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { isProviderAdmin } from "../auth/permissions";
import { accessRoleLabelKey } from "../lib/enumLabels";
import { AccessRoleBadge } from "./AccessRoleBadge";
import { EmptyState } from "./EmptyState";
import { StatusBadge } from "./StatusBadge";

/**
 * Shared customer-employees directory.
 *
 * Mounted by `MyEmployeesPage` (the customer-facing `/my/employees`
 * directory). It fetches `GET /api/customers/<cid>/employees/`, renders a
 * read-only table (view-first per the 2026-05-15 stakeholder doc §3),
 * and exposes an access-role filter dropdown.
 *
 * Edit affordance — "Edit access role" opens a small modal that lists
 * the user's per-building access rows and lets the editor change the
 * access_role per building. The modal data comes from
 * `listCustomerUserAccess`; each change PATCHes
 * `updateCustomerUserAccessRole`. The backend is the source of truth:
 * it 400s policy-blocked CCA grants and 403s the actor's own row — we
 * surface those inline.
 *
 * canEdit:
 *   - SUPER_ADMIN / COMPANY_ADMIN: always.
 *   - CUSTOMER_USER: only when the viewer's OWN directory row carries
 *     customer_access_role === "CUSTOMER_COMPANY_ADMIN".
 *   - everyone else (BM / CLM / CU): no edit affordance.
 */

const ACCESS_ROLE_OPTIONS: CustomerAccessRole[] = [
  "CUSTOMER_USER",
  "CUSTOMER_LOCATION_MANAGER",
  "CUSTOMER_COMPANY_ADMIN",
];

export interface CustomerEmployeesDirectoryProps {
  customerId: number;
  /**
   * Optional opt-out from the edit affordance even when the caller
   * would otherwise be allowed to edit (e.g. a read-only embed). The
   * backend remains the source of truth regardless.
   */
  canEditOverride?: boolean;
}

export function CustomerEmployeesDirectory({
  customerId,
  canEditOverride,
}: CustomerEmployeesDirectoryProps) {
  const { me } = useAuth();
  const { t } = useTranslation("common");

  const [employees, setEmployees] = useState<CustomerEmployee[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [accessRoleFilter, setAccessRoleFilter] = useState<
    CustomerAccessRole | ""
  >("");

  // Codex #1 (PR #76) — the viewer's OWN effective access role, resolved by
  // a dedicated UNFILTERED lookup (effect below) so the table's access-role
  // filter can never hide the viewer's own CCA row and strip edit rights.
  const [viewerAccessRole, setViewerAccessRole] =
    useState<CustomerAccessRole | null>(null);

  // Edit modal state.
  const [editTarget, setEditTarget] = useState<CustomerEmployee | null>(null);
  const [accessRows, setAccessRows] = useState<CustomerUserBuildingAccess[]>([]);
  const [modalLoading, setModalLoading] = useState(false);
  const [modalError, setModalError] = useState("");
  const [savingBuildingId, setSavingBuildingId] = useState<number | null>(null);

  const queryParams = useMemo(() => {
    const params: { access_role?: CustomerAccessRole } = {};
    if (accessRoleFilter) params.access_role = accessRoleFilter;
    return params;
  }, [accessRoleFilter]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await listCustomerEmployees(customerId, queryParams);
      setEmployees(response.results);
      setCount(response.count);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setLoading(false);
    }
  }, [customerId, queryParams]);

  useEffect(() => {
    load(); // eslint-disable-line react-hooks/set-state-in-effect
  }, [load]);

  // Codex #1 — resolve the viewer's OWN effective access role from an
  // UNFILTERED lookup, independent of `accessRoleFilter`. Only customer
  // users need it (provider admins are always canEdit). Keyed on
  // customer/identity, NOT on the filter, so filtering by CLM/CU can never
  // strip a CCA's edit affordance. The directory endpoint admits the viewer
  // to read their own customer regardless of access role, so a CLM/CU
  // simply resolves to a non-CCA role here (no edit).
  useEffect(() => {
    if (me?.role !== "CUSTOMER_USER") {
      setViewerAccessRole(null); // eslint-disable-line react-hooks/set-state-in-effect
      return;
    }
    let cancelled = false;
    listCustomerEmployees(customerId)
      .then((resp) => {
        if (cancelled) return;
        const own = resp.results.find((row) => row.id === me.id);
        setViewerAccessRole(own?.customer_access_role ?? null);
      })
      .catch(() => {
        if (!cancelled) setViewerAccessRole(null);
      });
    return () => {
      cancelled = true;
    };
  }, [customerId, me]);

  const canEdit =
    canEditOverride ??
    (isProviderAdmin(me?.role) ||
      viewerAccessRole === "CUSTOMER_COMPANY_ADMIN");

  const hasActiveFilters = Boolean(accessRoleFilter);

  const openEditModal = useCallback(
    async (row: CustomerEmployee) => {
      setEditTarget(row);
      setAccessRows([]);
      setModalError("");
      setModalLoading(true);
      try {
        const response = await listCustomerUserAccess(customerId, row.id);
        setAccessRows(response.results);
      } catch (err) {
        setModalError(getApiError(err));
      } finally {
        setModalLoading(false);
      }
    },
    [customerId],
  );

  function closeEditModal() {
    setEditTarget(null);
    setAccessRows([]);
    setModalError("");
    setSavingBuildingId(null);
  }

  async function changeAccessRole(
    accessRow: CustomerUserBuildingAccess,
    nextRole: CustomerAccessRole,
  ) {
    if (!editTarget || nextRole === accessRow.access_role) return;
    setSavingBuildingId(accessRow.building_id);
    setModalError("");
    try {
      const updated = await updateCustomerUserAccessRole(
        customerId,
        editTarget.id,
        accessRow.building_id,
        nextRole,
      );
      setAccessRows((prev) =>
        prev.map((r) => (r.building_id === accessRow.building_id ? updated : r)),
      );
      // Refresh the directory so the highest-effective access-role
      // column reflects the change.
      await load();
    } catch (err) {
      setModalError(getApiError(err));
    } finally {
      setSavingBuildingId(null);
    }
  }

  return (
    <div data-testid="customer-employees-directory">
      <div
        className="filter-bar"
        style={{ alignItems: "flex-end", marginBottom: 0 }}
      >
        <div className="filter-field">
          <span className="filter-label">
            {t("customer_employees.filter_access_role")}
          </span>
          <select
            className="filter-control"
            data-testid="customer-employees-filter-access-role"
            value={accessRoleFilter}
            onChange={(event) =>
              setAccessRoleFilter(event.target.value as CustomerAccessRole | "")
            }
          >
            <option value="">
              {t("customer_employees.filter_access_role_all")}
            </option>
            {ACCESS_ROLE_OPTIONS.map((value) => (
              <option key={value} value={value}>
                {t(accessRoleLabelKey(value))}
              </option>
            ))}
          </select>
        </div>
        <div className="filter-actions">
          {hasActiveFilters && (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              data-testid="customer-employees-filters-clear"
              onClick={() => setAccessRoleFilter("")}
            >
              {t("clear")}
            </button>
          )}
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={load}
            disabled={loading}
          >
            <RefreshCw size={14} strokeWidth={2.5} />
            {t("refresh")}
          </button>
        </div>
      </div>

      <p className="muted small" data-testid="customer-employees-count">
        {loading
          ? t("customer_employees.loading")
          : t("customer_employees.count", { count })}
      </p>

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      {loading && (
        <div className="loading-bar" style={{ margin: 0 }}>
          <div className="loading-bar-fill" />
        </div>
      )}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("customer_employees.col_name")}</th>
              <th>{t("customer_employees.col_email")}</th>
              <th>{t("customer_employees.col_access_role")}</th>
              <th>{t("status")}</th>
              {canEdit && <th aria-label={t("admin.col_actions")} />}
            </tr>
          </thead>
          <tbody>
            {employees.map((row) => (
              <tr key={row.id} data-testid="customer-employee-row">
                <td className="td-subject">{row.full_name || "—"}</td>
                <td>{row.email}</td>
                <td data-testid="customer-employee-access-role">
                  <AccessRoleBadge accessRole={row.customer_access_role} />
                </td>
                <td>
                  <StatusBadge
                    variant="cell"
                    status={{
                      kind: "generic",
                      tone: row.is_active ? "open" : "neutral",
                      label: row.is_active
                        ? t("admin.status_active")
                        : t("admin.status_inactive"),
                    }}
                  />
                </td>
                {canEdit && (
                  <td>
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      data-testid="customer-employee-edit-access-role"
                      onClick={() => openEditModal(row)}
                    >
                      {t("customer_employees.edit_access_role")}
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!loading && employees.length === 0 && (
        <EmptyState
          icon={Contact}
          title={
            hasActiveFilters
              ? t("customer_employees.empty_filtered_title")
              : t("customer_employees.empty_initial_title")
          }
          description={
            hasActiveFilters
              ? t("admin.empty_filtered_desc")
              : t("customer_employees.empty_initial_desc")
          }
        />
      )}

      {editTarget && (
        <div
          data-testid="customer-employee-edit-modal"
          role="dialog"
          aria-modal="true"
          aria-label={t("customer_employees.edit_modal_title")}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.4)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 100,
            padding: 16,
          }}
        >
          <div
            className="card"
            style={{
              maxWidth: 560,
              width: "100%",
              padding: 24,
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <h3 style={{ marginTop: 0, marginBottom: 4 }}>
              {t("customer_employees.edit_modal_title")}
            </h3>
            <p className="muted small" style={{ marginBottom: 16 }}>
              {t("customer_employees.edit_modal_subtitle", {
                name: editTarget.full_name || editTarget.email,
              })}
            </p>

            {modalError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="customer-employee-edit-modal-error"
              >
                {modalError}
              </div>
            )}

            {modalLoading ? (
              <div className="loading-bar">
                <div className="loading-bar-fill" />
              </div>
            ) : accessRows.length === 0 ? (
              <p
                className="muted small"
                data-testid="customer-employee-edit-no-access"
              >
                {t("customer_employees.edit_no_access")}
              </p>
            ) : (
              <div className="table-wrap" style={{ overflowX: "visible" }}>
                {/* Override the global .data-table min-width (860px) so this
                    2-column modal table fits the 560px modal without forcing
                    a horizontal scrollbar. */}
                <table className="data-table" style={{ minWidth: 0 }}>
                  <thead>
                    <tr>
                      <th>{t("customer_employees.col_building")}</th>
                      <th>{t("customer_employees.col_access_role")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {accessRows.map((accessRow) => (
                      <tr
                        key={accessRow.id}
                        data-testid="customer-employee-edit-row"
                      >
                        <td>{accessRow.building_name}</td>
                        <td>
                          <select
                            className="field-select"
                            data-testid="customer-employee-access-role-select"
                            value={accessRow.access_role}
                            disabled={
                              savingBuildingId === accessRow.building_id
                            }
                            onChange={(event) =>
                              changeAccessRole(
                                accessRow,
                                event.target.value as CustomerAccessRole,
                              )
                            }
                          >
                            {ACCESS_ROLE_OPTIONS.map((value) => (
                              <option key={value} value={value}>
                                {t(accessRoleLabelKey(value))}
                              </option>
                            ))}
                          </select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 8,
                marginTop: 16,
              }}
            >
              <button
                type="button"
                className="btn btn-secondary"
                data-testid="customer-employee-edit-close"
                onClick={closeEditModal}
                disabled={savingBuildingId !== null}
              >
                {t("customer_employees.edit_close")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
