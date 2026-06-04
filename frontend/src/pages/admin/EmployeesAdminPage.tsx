import { useCallback, useEffect, useMemo, useState } from "react";
import { Contact, Pencil, RefreshCw } from "lucide-react";
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
import { ClickableRow } from "../../components/ClickableRow";
import { EmptyState } from "../../components/EmptyState";
import { RoleBadge } from "../../components/RoleBadge";
import { StatusBadge } from "../../components/StatusBadge";
import {
  employmentTypeLabelKey,
  roleLabelKey,
} from "../../lib/enumLabels";

/**
 * Employees directory (provider side).
 *
 * View-first per `docs/product/meeting-2026-05-15-system-requirements.md`
 * §3: the table loads read-only. The whole row is the click target — it
 * navigates to the person's account page (/admin/users/<id>) for viewers
 * who can open it (SUPER_ADMIN: any; COMPANY_ADMIN: only ACTIVE non-
 * COMPANY_ADMIN rows — mirrors the backend CanManageUser rule and the
 * scoped Users queryset, so the row never links to a 403/404;
 * BUILDING_MANAGER: never — the directory is read-only for them).
 * SUPER_ADMIN / COMPANY_ADMIN additionally get an unobtrusive pencil to
 * edit a STAFF row's employment type in place (the control stops click
 * propagation so editing never triggers row navigation).
 *
 * Backend: GET /api/employees/ (`CustomerReadRoute` admits SA / CA /
 * BM; STAFF / CUSTOMER_USER are bounced before reaching the page).
 */

// Codex #2 (PR #76): only make a row open the Users admin surface when the
// viewer can actually open that user, so the row never links to a 403/404.
// SUPER_ADMIN may open anyone; a COMPANY_ADMIN may open only ACTIVE users
// whose role is NOT COMPANY_ADMIN (CanManageUser rejects a peer admin and
// the Users queryset hides inactive); BUILDING_MANAGER never opens accounts.
function canOpenAccount(
  viewerRole: Role | null | undefined,
  row: ProviderEmployee,
): boolean {
  if (viewerRole === "SUPER_ADMIN") return true;
  if (viewerRole === "COMPANY_ADMIN") {
    return row.is_active && row.role !== "COMPANY_ADMIN";
  }
  return false;
}

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
              </tr>
            </thead>
            <tbody>
              {employees.map((row) => {
                const isStaff = row.role === "STAFF";
                const isEditing = editingId === row.id;
                const openable = canOpenAccount(me?.role, row);
                return (
                  <ClickableRow
                    key={row.id}
                    to={openable ? `/admin/users/${row.id}` : undefined}
                    inert={!openable}
                    dataRole={row.role}
                    testId="employee-row"
                    ariaLabel={
                      openable
                        ? t("employees.open_account", {
                            name: row.full_name || row.email,
                          })
                        : undefined
                    }
                  >
                    <td className="td-subject">{row.full_name || "—"}</td>
                    <td>{row.email}</td>
                    <td data-testid="employee-row-role">
                      <RoleBadge role={row.role} compact />
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
                            onClick={(event) => event.stopPropagation()}
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
                            onClick={(event) => {
                              event.stopPropagation();
                              saveEdit(row);
                            }}
                            disabled={editBusy}
                          >
                            {editBusy
                              ? t("admin_form.saving")
                              : t("employees.edit_save")}
                          </button>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            onClick={(event) => {
                              event.stopPropagation();
                              cancelEdit();
                            }}
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
                      ) : (
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                          }}
                        >
                          {row.employment_type ? (
                            <span>
                              {t(employmentTypeLabelKey(row.employment_type))}
                            </span>
                          ) : (
                            <span className="muted">—</span>
                          )}
                          {canEdit && isStaff && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm icon-only"
                              data-testid="employee-edit-employment-type"
                              aria-label={t("employees.edit_employment_type")}
                              title={t("employees.edit_employment_type")}
                              onClick={(event) => {
                                event.stopPropagation();
                                startEdit(row);
                              }}
                            >
                              <Pencil size={13} strokeWidth={2} />
                            </button>
                          )}
                        </span>
                      )}
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
                  </ClickableRow>
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
