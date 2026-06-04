import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Contact, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  listProviderEmployees,
  updateStaffProfile,
} from "../../api/admin";
import type {
  EmploymentType,
  ProviderEmployee,
  Role,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { isProviderAdmin } from "../../auth/permissions";
import { EmptyState } from "../../components/EmptyState";
import { RoleBadge } from "../../components/RoleBadge";
import {
  employmentTypeLabelKey,
  roleLabelKey,
} from "../../lib/enumLabels";

/**
 * Employees directory (provider side).
 *
 * View-first per `docs/product/meeting-2026-05-15-system-requirements.md`
 * §3: the table loads read-only. SUPER_ADMIN / COMPANY_ADMIN get an
 * inline employment-type editor on STAFF rows only (revealed by an
 * explicit "Edit" affordance); BUILDING_MANAGER sees the directory
 * read-only with no edit control. Full account management still lives
 * on the Users page — each row links there via "Manage account".
 *
 * Backend: GET /api/employees/ (`CustomerReadRoute` admits SA / CA /
 * BM; STAFF / CUSTOMER_USER are bounced before reaching the page).
 */

// The three provider-side roles the directory can filter on. STAFF +
// the two provider-admin roles + BUILDING_MANAGER are the only values
// the backend accepts on ?role=.
const ROLE_FILTER_OPTIONS: Role[] = [
  "COMPANY_ADMIN",
  "BUILDING_MANAGER",
  "STAFF",
];

const EMPLOYMENT_TYPE_OPTIONS: EmploymentType[] = [
  "INTERNAL_STAFF",
  "ZZP",
  "INHUUR",
];

export function EmployeesAdminPage() {
  const { me } = useAuth();
  const { t } = useTranslation("common");
  const canEdit = isProviderAdmin(me?.role);

  const [employees, setEmployees] = useState<ProviderEmployee[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [roleFilter, setRoleFilter] = useState<Role | "">("");
  const [employmentTypeFilter, setEmploymentTypeFilter] = useState<
    EmploymentType | ""
  >("");

  // Inline-edit state: the STAFF row currently being edited + the
  // pending employment-type value + a per-row busy flag.
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editValue, setEditValue] = useState<EmploymentType>("INTERNAL_STAFF");
  const [editBusy, setEditBusy] = useState(false);
  const [editError, setEditError] = useState("");

  const queryParams = useMemo(() => {
    const params: {
      role?: Role;
      employment_type?: EmploymentType;
    } = {};
    if (roleFilter) params.role = roleFilter;
    if (employmentTypeFilter) params.employment_type = employmentTypeFilter;
    return params;
  }, [roleFilter, employmentTypeFilter]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await listProviderEmployees(queryParams);
      setEmployees(response.results);
      setCount(response.count);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setLoading(false);
    }
  }, [queryParams]);

  useEffect(() => {
    load(); // eslint-disable-line react-hooks/set-state-in-effect
  }, [load]);

  const hasActiveFilters = Boolean(roleFilter || employmentTypeFilter);

  function startEdit(row: ProviderEmployee) {
    setEditingId(row.id);
    setEditValue(row.employment_type ?? "INTERNAL_STAFF");
    setEditError("");
  }

  function cancelEdit() {
    setEditingId(null);
    setEditError("");
  }

  async function saveEdit(row: ProviderEmployee) {
    setEditBusy(true);
    setEditError("");
    try {
      await updateStaffProfile(row.id, { employment_type: editValue });
      setEditingId(null);
      await load();
    } catch (err) {
      setEditError(getApiError(err));
    } finally {
      setEditBusy(false);
    }
  }

  return (
    <div data-testid="employees-admin-page">
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("nav.admin_group")}
          </div>
          <h2 className="page-title">{t("employees.page_title")}</h2>
          <p className="page-sub">
            {loading
              ? t("employees.loading")
              : t("employees.count", { count })}
          </p>
        </div>
        <div className="page-header-actions">
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

      <p className="section-explainer" data-testid="employees-explainer">
        {t("employees.explainer")}
      </p>

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      <div className="card" style={{ overflow: "hidden" }}>
        <div className="filter-bar">
          <div className="filter-field">
            <span className="filter-label">{t("employees.filter_role")}</span>
            <select
              className="filter-control"
              data-testid="employees-filter-role"
              value={roleFilter}
              onChange={(event) =>
                setRoleFilter(event.target.value as Role | "")
              }
            >
              <option value="">{t("employees.filter_role_all")}</option>
              {ROLE_FILTER_OPTIONS.map((role) => (
                <option key={role} value={role}>
                  {t(roleLabelKey(role))}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-field">
            <span className="filter-label">
              {t("employees.filter_employment_type")}
            </span>
            <select
              className="filter-control"
              data-testid="employees-filter-employment-type"
              value={employmentTypeFilter}
              onChange={(event) =>
                setEmploymentTypeFilter(event.target.value as EmploymentType | "")
              }
            >
              <option value="">
                {t("employees.filter_employment_type_all")}
              </option>
              {EMPLOYMENT_TYPE_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {t(employmentTypeLabelKey(value))}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-actions">
            {hasActiveFilters && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                data-testid="employees-filters-clear"
                onClick={() => {
                  setRoleFilter("");
                  setEmploymentTypeFilter("");
                }}
              >
                {t("clear")}
              </button>
            )}
          </div>
        </div>

        {loading && (
          <div className="loading-bar" style={{ margin: 0 }}>
            <div className="loading-bar-fill" />
          </div>
        )}

        <div className="table-wrap admin-list-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("employees.col_name")}</th>
                <th>{t("employees.col_email")}</th>
                <th>{t("employees.col_role")}</th>
                <th>{t("employees.col_employment_type")}</th>
                <th>{t("status")}</th>
                <th aria-label={t("admin.col_actions")} />
              </tr>
            </thead>
            <tbody>
              {employees.map((row) => {
                const isStaff = row.role === "STAFF";
                const isEditing = editingId === row.id;
                return (
                  <tr key={row.id} data-testid="employee-row" data-role={row.role}>
                    <td className="td-subject">{row.full_name || "—"}</td>
                    <td>{row.email}</td>
                    <td data-testid="employee-row-role">
                      <RoleBadge role={row.role} />
                    </td>
                    <td data-testid="employee-row-employment-type">
                      {isEditing ? (
                        <div
                          style={{
                            display: "flex",
                            gap: 8,
                            alignItems: "center",
                            flexWrap: "wrap",
                          }}
                        >
                          <select
                            className="field-select"
                            data-testid="employee-employment-type-select"
                            value={editValue}
                            onChange={(event) =>
                              setEditValue(event.target.value as EmploymentType)
                            }
                            disabled={editBusy}
                          >
                            {EMPLOYMENT_TYPE_OPTIONS.map((value) => (
                              <option key={value} value={value}>
                                {t(employmentTypeLabelKey(value))}
                              </option>
                            ))}
                          </select>
                          <button
                            type="button"
                            className="btn btn-primary btn-sm"
                            data-testid="employee-employment-type-save"
                            onClick={() => saveEdit(row)}
                            disabled={editBusy}
                          >
                            {editBusy
                              ? t("admin_form.saving")
                              : t("employees.edit_save")}
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            onClick={cancelEdit}
                            disabled={editBusy}
                          >
                            {t("employees.edit_cancel")}
                          </button>
                          {editError && (
                            <span
                              className="field-error"
                              role="alert"
                              data-testid="employee-employment-type-error"
                            >
                              {editError}
                            </span>
                          )}
                        </div>
                      ) : row.employment_type ? (
                        <span>{t(employmentTypeLabelKey(row.employment_type))}</span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      <span
                        className={`cell-tag cell-tag-${
                          row.is_active ? "open" : "closed"
                        }`}
                      >
                        <i />
                        {row.is_active
                          ? t("admin.status_active")
                          : t("admin.status_inactive")}
                      </span>
                    </td>
                    <td>
                      <div
                        style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
                      >
                        {canEdit && isStaff && !isEditing && (
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            data-testid="employee-edit-employment-type"
                            onClick={() => startEdit(row)}
                          >
                            {t("employees.edit_employment_type")}
                          </button>
                        )}
                        {/* The Users admin surface is SA/CA-only (AdminRoute),
                            so only show the deep-link to viewers who can use
                            it; a BUILDING_MANAGER would be bounced. */}
                        {canEdit && (
                          <Link
                            className="btn btn-ghost btn-sm"
                            to={`/admin/users/${row.id}`}
                            data-testid="employee-manage-account"
                          >
                            {t("employees.manage_account")}
                          </Link>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {!loading && employees.length === 0 && (
          <EmptyState
            icon={Contact}
            title={
              hasActiveFilters
                ? t("employees.empty_filtered_title")
                : t("employees.empty_initial_title")
            }
            description={
              hasActiveFilters
                ? t("admin.empty_filtered_desc")
                : t("employees.empty_initial_desc")
            }
          />
        )}
      </div>
    </div>
  );
}
