import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Contact, Pencil, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  createEmployeeHourlyRate,
  deleteEmployeeHourlyRate,
  listEmployeeHourlyRates,
  updateEmployeeHourlyRate,
} from "../../api/labourRates";
import type { EmployeeHourlyRate } from "../../api/labourRates";
import {
  bulkLinkBuildings,
  listAllBuildings,
  listAllCompanies,
  listProviderEmployees,
  updateStaffProfile,
} from "../../api/admin";
import type {
  BuildingAdmin,
  CompanyAdmin,
  EmploymentType,
  ProviderEmployee,
  Role,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { isProviderAdmin } from "../../auth/permissions";
import { BulkAssignDialog } from "../../components/BulkAssignDialog";
import { ClickableRow } from "../../components/ClickableRow";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { EmployeeRatePanel } from "./EmployeeRatePanel";
import type { NewRatePayload } from "./EmployeeRatePanel";
import { EditModeToggle } from "../../components/EditModeToggle";
import { MultiSelectToolbar } from "../../components/MultiSelectToolbar";
import { useEditMode } from "../../lib/useEditMode";
import { EmptyState } from "../../components/EmptyState";
import { RoleBadge } from "../../components/RoleBadge";
import { StatusBadge } from "../../components/StatusBadge";
import { useToast } from "../../components/ToastProvider";
import {
  employmentTypeLabelKey,
  roleLabelKey,
} from "../../lib/enumLabels";

/**
 * Employees directory (provider side).
 *
 * View-first per `docs/product/requirements-meeting-2026-05-15.md`
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

/** Today as an ISO date, for "what does this person cost right now". */
function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

/**
 * The rate in force on `onDate` — the LATEST row starting on or before
 * it, which is the identical rule the server applies when it costs an
 * hour (`reports.labour_cost.RateBook.rate_on`).
 *
 * Rows arrive newest-first from the API (`Meta.ordering` is
 * `-valid_from, -id`), so this is a find, not a sort. It is a READ of
 * what the server will do, never a second source of truth: no cost
 * figure on any screen is computed here.
 */
function rateInForce(
  rows: EmployeeHourlyRate[],
  onDate: string,
): EmployeeHourlyRate | undefined {
  return rows.find((row) => row.valid_from <= onDate);
}

export function EmployeesAdminPage() {
  const { me } = useAuth();
  const { t } = useTranslation("common");
  const { push: pushToast } = useToast();
  const canEdit = isProviderAdmin(me?.role);
  /** W-HR1 §3 — a wage is personal data. The rate column, the expander
   *  and every rate request are for provider admins only; the endpoint
   *  403s a BUILDING_MANAGER independently, and this page admits one. */
  const canSeeRates = isProviderAdmin(me?.role);

  const [employees, setEmployees] = useState<ProviderEmployee[]>([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [roleFilter, setRoleFilter] = useState<Role | "">("");
  // Sprint 187B §2 — the company filter, same established pattern as
  // Buildings and the Users page: loaded once, auto-selected and disabled
  // when exactly one company comes back (a single-company admin has
  // nothing to choose between).
  const [companyFilter, setCompanyFilter] = useState<number | "">("");
  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companiesLoaded, setCompaniesLoaded] = useState(false);
  const [employmentTypeFilter, setEmploymentTypeFilter] = useState<
    EmploymentType | ""
  >("");

  // Inline-edit state: the STAFF row currently being edited + the
  // pending employment-type value + a per-row busy flag.
  // Sprint 156 §8 — bulk assign workers to buildings, FROM the worker's
  // side. The other direction has existed since Sprint 154 (the building
  // page's Staff and Managers cards), and one worker at a time has been
  // editable from their own page since Sprint 23A; what was missing was
  // "these six people, onto these three buildings".
  //
  // It reuses `/api/buildings/bulk-link/` unchanged — that endpoint
  // already takes N buildings x M targets, so this direction needed no
  // new mechanism, only an entry point. Adding a second bulk endpoint
  // for the mirror case is exactly what the prompt forbids and what the
  // relation-spec table exists to make unnecessary.
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignBuildingIds, setAssignBuildingIds] = useState<number[]>([]);
  const [assignBusy, setAssignBusy] = useState(false);
  const [assignError, setAssignError] = useState("");
  const [buildingOptions, setBuildingOptions] = useState<BuildingAdmin[]>([]);

  async function openAssign() {
    setAssignBuildingIds([]);
    setAssignError("");
    setAssignOpen(true);
    if (buildingOptions.length === 0) {
      // Loaded on first open rather than on mount: most visits to this
      // page never assign anybody, and `listAllBuildings` pages through
      // the whole collection.
      try {
        setBuildingOptions(await listAllBuildings({ is_active: "true" }));
      } catch (err) {
        setAssignError(getApiError(err));
      }
    }
  }

  async function runAssign() {
    // The selection can hold both roles, and the two go to DIFFERENT
    // link tables — a STAFF member to `staff`, a BUILDING_MANAGER to
    // `managers`. Splitting here rather than asking the operator which
    // relation they mean: the person's role already answers it, and
    // making them choose would let them choose wrong.
    const staffIds = linkableRows
      .filter((r) => edit.isSelected(r.id) && r.role === "STAFF")
      .map((r) => r.id);
    const managerIds = linkableRows
      .filter((r) => edit.isSelected(r.id) && r.role === "BUILDING_MANAGER")
      .map((r) => r.id);
    setAssignBusy(true);
    setAssignError("");
    try {
      // Two calls at most, each all-or-nothing on the server. Not one
      // call: `relation` is per-request by design, and widening it to a
      // per-target field would change the endpoint's shape for every
      // existing caller.
      if (staffIds.length > 0) {
        await bulkLinkBuildings({
          buildings: assignBuildingIds,
          relation: "staff",
          targets: staffIds,
          mode: "link",
        });
      }
      if (managerIds.length > 0) {
        await bulkLinkBuildings({
          buildings: assignBuildingIds,
          relation: "managers",
          targets: managerIds,
          mode: "link",
        });
      }
      setAssignOpen(false);
      edit.exit();
      await load();
    } catch (err) {
      setAssignError(getApiError(err));
    } finally {
      setAssignBusy(false);
    }
  }
  const linkableRows = employees.filter(
    (row) => row.role === "STAFF" || row.role === "BUILDING_MANAGER",
  );
  const edit = useEditMode(linkableRows.map((row) => row.id));

  // ---- W-HR1 §3: the cost of an hour, per person -------------------
  /** Every rate row in the company filter's scope, paged exhaustively
   *  by the API helper. ONE read for the whole table rather than one
   *  per row: the column shows a rate for every employee, and N
   *  requests for N rows is the pattern this codebase does not use. */
  const [rates, setRates] = useState<EmployeeHourlyRate[]>([]);
  const [ratesError, setRatesError] = useState("");
  const [rateBusy, setRateBusy] = useState(false);
  /** The employee whose rate history is expanded, or `null`. */
  const [openRatesFor, setOpenRatesFor] = useState<number | null>(null);
  const rateDeleteRef = useRef<ConfirmDialogHandle>(null);
  const pendingRateDelete = useRef<EmployeeHourlyRate | null>(null);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editValue, setEditValue] = useState<EmploymentType>("INTERNAL_STAFF");
  const [editBusy, setEditBusy] = useState(false);
  const [editError, setEditError] = useState("");

  // Loaded exhaustively so a tenant with more than one page of companies
  // gets a complete dropdown rather than a silently truncated one.
  useEffect(() => {
    let cancelled = false;
    listAllCompanies({ is_active: "true" })
      .then((response) => {
        if (cancelled) return;
        setCompanies(response);
        if (response.length === 1) {
          setCompanyFilter(response[0].id);
        }
      })
      .finally(() => {
        if (!cancelled) setCompaniesLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const companyDropdownDisabled = companiesLoaded && companies.length <= 1;

  const queryParams = useMemo(() => {
    const params: {
      role?: Role;
      employment_type?: EmploymentType;
      company?: number;
    } = {};
    if (roleFilter) params.role = roleFilter;
    if (employmentTypeFilter) params.employment_type = employmentTypeFilter;
    if (companyFilter !== "") params.company = companyFilter;
    return params;
  }, [roleFilter, employmentTypeFilter, companyFilter]);

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
    // Sprint 156 §8 — the `eslint-disable-line
    // react-hooks/set-state-in-effect` that lived here is gone: the rule
    // stopped firing on this line and ESLint reported the directive
    // itself as unused, which counted as a new warning against the
    // frozen baseline. Removing a directive that no longer suppresses
    // anything is the fix; adding a second one to silence the first
    // would be the opposite of the rule.
    load();
  }, [load]);

  // ---- W-HR1 §3: reading and writing a rate ------------------------
  /** The rate read, as a PROMISE returning rows — it deliberately sets
   *  no state of its own, so the effect below and the mutation handlers
   *  can both use it under their different rules. */
  const fetchRates = useCallback(() => {
    if (!canSeeRates) return Promise.resolve<EmployeeHourlyRate[]>([]);
    return listEmployeeHourlyRates(
      companyFilter === "" ? {} : { company: companyFilter },
    );
  }, [canSeeRates, companyFilter]);

  useEffect(() => {
    let cancelled = false;
    // A promise CHAIN, never an `async` helper called from the effect
    // body: `react-hooks/set-state-in-effect` fires on the latter even
    // when every setState in it sits after an `await`, and the ESLint
    // baseline is frozen (CLAUDE.md §3). A setState inside a `.then`
    // callback does not trip it, because the callback genuinely is not
    // the effect body. Measured: the `async` version cost exactly one
    // new error against the 42-problem baseline.
    fetchRates()
      .then((rows) => {
        if (cancelled) return;
        setRates(rows);
        setRatesError("");
      })
      .catch((err) => {
        // Non-fatal, and deliberately so: the directory's own job is
        // the people, and a rate endpoint that refuses must not blank
        // the table of names.
        if (cancelled) return;
        setRates([]);
        setRatesError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [fetchRates]);

  /** Re-read after a mutation. NOT called from an effect — a save
   *  handler awaits it — so it may set state directly, and it is a
   *  separate function from the effect above precisely because the two
   *  live under different rules. */
  const reloadRates = useCallback(async () => {
    try {
      setRates(await fetchRates());
      setRatesError("");
    } catch (err) {
      setRatesError(getApiError(err));
    }
  }, [fetchRates]);

  const ratesByEmployee = useMemo(() => {
    const map = new Map<number, EmployeeHourlyRate[]>();
    for (const row of rates) {
      const list = map.get(row.employee);
      if (list) list.push(row);
      else map.set(row.employee, [row]);
    }
    return map;
  }, [rates]);

  const today = todayIso();

  /** The rate detail row spans the WHOLE table. Seven fixed columns
   *  (name, email, phone, role, company, employment type, status) plus
   *  the two conditional ones — the edit-mode checkbox and the rate
   *  column itself. Counted here rather than hardcoded, so a new column
   *  cannot leave the panel one cell short. */
  const detailColSpan =
    7 + (edit.editMode ? 1 : 0) + (canSeeRates ? 1 : 0);

  async function createRate(employeeId: number, payload: NewRatePayload) {
    if (companyFilter === "") {
      setRatesError(t("labour_rates.company_required"));
      return;
    }
    setRateBusy(true);
    setRatesError("");
    try {
      await createEmployeeHourlyRate({
        company: companyFilter,
        employee: employeeId,
        hourly_rate: payload.hourly_rate,
        valid_from: payload.valid_from,
        note: payload.note,
      });
      await reloadRates();
      pushToast({ variant: "success", title: t("labour_rates.saved") });
    } catch (err) {
      setRatesError(getApiError(err));
    } finally {
      setRateBusy(false);
    }
  }

  async function correctRate(row: EmployeeHourlyRate, hourlyRate: string) {
    setRateBusy(true);
    setRatesError("");
    try {
      await updateEmployeeHourlyRate(row.id, { hourly_rate: hourlyRate });
      await reloadRates();
      pushToast({ variant: "success", title: t("labour_rates.corrected") });
    } catch (err) {
      setRatesError(getApiError(err));
    } finally {
      setRateBusy(false);
    }
  }

  function askDeleteRate(row: EmployeeHourlyRate) {
    pendingRateDelete.current = row;
    rateDeleteRef.current?.open();
  }

  async function confirmDeleteRate() {
    const row = pendingRateDelete.current;
    pendingRateDelete.current = null;
    rateDeleteRef.current?.close();
    if (!row) return;
    setRateBusy(true);
    try {
      await deleteEmployeeHourlyRate(row.id);
      await reloadRates();
      pushToast({ variant: "success", title: t("labour_rates.deleted") });
    } catch (err) {
      setRatesError(getApiError(err));
    } finally {
      setRateBusy(false);
    }
  }

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

      {/* W-T3 §3 — the explainer deleted: it described what the list
          obviously is and pointed at controls already on screen. */}
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
          <div className="filter-field">
            <span className="filter-label">{t("company")}</span>
            <select
              className="filter-control"
              style={{ maxWidth: 220 }}
              data-testid="employees-filter-company"
              value={companyFilter === "" ? "" : String(companyFilter)}
              onChange={(event) => {
                const value = event.target.value;
                setCompanyFilter(value === "" ? "" : Number(value));
              }}
              disabled={companyDropdownDisabled}
            >
              <option value="">{t("admin.all_companies")}</option>
              {companies.map((company) => (
                <option key={company.id} value={company.id}>
                  {company.name}
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
            {/* Sprint 156 §8 — the intent step, same gate as every other
                list since Sprint 155 §4. */}
            {linkableRows.length > 0 && (
              <EditModeToggle
                editMode={edit.editMode}
                onToggle={edit.toggleMode}
                disabled={assignBusy}
                testId="employees-edit-mode-toggle"
              />
            )}
          </div>
        </div>

        {edit.editMode && (
          <div className="list-edit-bar">
            <MultiSelectToolbar
              selectedCount={edit.selection.length}
              onSelectAll={edit.selectAll}
              onClearAll={edit.clear}
              disabled={assignBusy}
              countLabel={t("employees.bulk_selected_count", {
                count: edit.selection.length,
                total: linkableRows.length,
              })}
              actions={[
                {
                  key: "assign-buildings",
                  label: t("employees.assign_buildings"),
                  onClick: openAssign,
                },
              ]}
              testIdPrefix="employees-bulk"
            />
          </div>
        )}

        {loading && (
          <div className="loading-bar" style={{ margin: 0 }}>
            <div className="loading-bar-fill" />
          </div>
        )}

        <div className="table-wrap admin-list-wrap">
          <table className="data-table">
            <thead>
              <tr>
                {edit.editMode && (
                  <th className="th-select">
                    <input
                      type="checkbox"
                      checked={edit.allSelected}
                      onChange={() =>
                        edit.allSelected ? edit.clear() : edit.selectAll()
                      }
                      disabled={assignBusy}
                      aria-label={t("employees.assign_buildings")}
                      data-testid="employees-select-all"
                    />
                  </th>
                )}
                <th>{t("employees.col_name")}</th>
                <th>{t("employees.col_email")}</th>
                <th>{t("users.col_phone")}</th>
                <th>{t("employees.col_role")}</th>
                <th>{t("company")}</th>
                <th>{t("employees.col_employment_type")}</th>
                {/* W-HR1 §3 — the cost of one of this person's hours,
                    where the person is. Provider admins only. */}
                {canSeeRates && <th>{t("labour_rates.col_current_rate")}</th>}
                <th>{t("status")}</th>
              </tr>
            </thead>
            <tbody>
              {employees.map((row) => {
                const isStaff = row.role === "STAFF";
                const isEditing = editingId === row.id;
                const openable = canOpenAccount(me?.role, row);
                const ownRates = ratesByEmployee.get(row.id) ?? [];
                const currentRate = rateInForce(ownRates, today);
                const ratesOpen = openRatesFor === row.id;
                return (
                  <Fragment key={row.id}>
                  <ClickableRow
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
                    {edit.editMode && (
                      <td
                        className="td-select"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {/* Only STAFF and BUILDING_MANAGER are linkable:
                            those are the two roles the building link
                            tables accept. Anyone else gets no checkbox
                            rather than a checkbox that always fails. */}
                        {(row.role === "STAFF" ||
                          row.role === "BUILDING_MANAGER") && (
                          <input
                            type="checkbox"
                            checked={edit.isSelected(row.id)}
                            onChange={() => edit.toggle(row.id)}
                            disabled={assignBusy}
                            aria-label={row.full_name || row.email}
                            data-testid={`employees-select-${row.id}`}
                          />
                        )}
                      </td>
                    )}
                    <td className="td-subject">{row.full_name || "—"}</td>
                    <td>{row.email}</td>
                    {/* Sprint 154 §K — this is `User.phone`. The STAFF-only
                        `StaffProfile.phone` is deliberately NOT used here:
                        it is gated by the customer's
                        show_assigned_staff_phone policy and this
                        directory's serializer has a privacy floor that
                        forbids exposing it. Empty renders an em dash. */}
                    <td data-testid="employee-row-phone">
                      {row.phone ? (
                        <a href={`tel:${row.phone}`}>{row.phone}</a>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td data-testid="employee-row-role">
                      <RoleBadge role={row.role} compact />
                    </td>
                    {/* Sprint 187B §2 — bounded like the Users page: two
                        names then "+N more", full set in the title. A
                        person spanning many companies must not print
                        them all into a cell. */}
                    <td
                      data-testid="employee-row-companies"
                      title={row.companies.join(", ")}
                    >
                      {row.companies.length === 0 ? (
                        <span className="muted small">—</span>
                      ) : (
                        <>
                          {row.companies.slice(0, 2).join(", ")}
                          {row.companies.length > 2 && (
                            <span className="muted small">
                              {" "}
                              {t("users.companies_more", {
                                count: row.companies.length - 2,
                              })}
                            </span>
                          )}
                        </>
                      )}
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
                    {/* W-HR1 §3 — the rate in force TODAY, and the way
                        into this person's rate history. "No rate set"
                        and "costs nothing" are different claims and
                        never render the same, so an unset rate is words
                        and never € 0,00. */}
                    {canSeeRates && (
                      <td
                        data-testid="employee-row-rate"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                          }}
                        >
                          {currentRate ? (
                            <span data-testid={`employee-rate-value-${row.id}`}>
                              {`€ ${currentRate.hourly_rate}`}
                            </span>
                          ) : (
                            <span className="muted small">
                              {t("labour_rates.no_rate")}
                            </span>
                          )}
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm icon-only"
                            data-testid={`employee-rate-toggle-${row.id}`}
                            aria-expanded={ratesOpen}
                            aria-label={t("labour_rates.show_history", {
                              n: ownRates.length,
                            })}
                            title={t("labour_rates.show_history", {
                              n: ownRates.length,
                            })}
                            onClick={(event) => {
                              event.stopPropagation();
                              setOpenRatesFor(ratesOpen ? null : row.id);
                            }}
                          >
                            {ratesOpen ? (
                              <ChevronDown size={13} strokeWidth={2} />
                            ) : (
                              <ChevronRight size={13} strokeWidth={2} />
                            )}
                          </button>
                        </span>
                      </td>
                    )}
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
                  {canSeeRates && ratesOpen && (
                    <tr data-testid={`employee-rate-detail-${row.id}`}>
                      <td colSpan={detailColSpan} style={{ padding: 0 }}>
                        <EmployeeRatePanel
                          employeeName={row.full_name || row.email}
                          rates={ownRates}
                          companyBlocked={companyFilter === ""}
                          busy={rateBusy}
                          error={ratesError}
                          onCreate={(payload) =>
                            void createRate(row.id, payload)
                          }
                          onCorrect={(rateRow, value) =>
                            void correctRate(rateRow, value)
                          }
                          onDelete={askDeleteRate}
                        />
                      </td>
                    </tr>
                  )}
                  </Fragment>
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

      {/* Rendered UNCONDITIONALLY and driven through the ref, at PAGE
          level and never inside the rate panel: a native <dialog>
          mounted behind a condition is invisible and its trigger looks
          dead, and unmounting one that is still open can leave the page
          inert (CLAUDE.md §3 — Sprint 118). The rate panel is exactly
          such a conditionally-mounted subtree, so the confirmation
          lives out here. */}
      <ConfirmDialog
        ref={rateDeleteRef}
        title={t("labour_rates.delete_confirm_title")}
        body={t("labour_rates.delete_confirm_body")}
        confirmLabel={t("labour_rates.delete_button")}
        onConfirm={confirmDeleteRate}
        onCancel={() => {
          pendingRateDelete.current = null;
        }}
        busy={rateBusy}
        destructive
      />

      {/* Sprint 156 §8 — the same dialog Sprint 154 built for the other
          direction, with the same mandatory "N will be assigned to M"
          summary line. A non-native overlay, conditionally mounted. */}
      {assignOpen && (
        <BulkAssignDialog
          title={t("employees.assign_buildings")}
          summary={t("employees.assign_summary", {
            people: edit.selection.length,
            buildings: assignBuildingIds.length,
          })}
          options={buildingOptions.map((b) => ({
            id: b.id,
            label: b.name,
            sublabel: [b.city, b.address].filter(Boolean).join(" · "),
          }))}
          selectedIds={assignBuildingIds}
          onChange={setAssignBuildingIds}
          onCancel={() => setAssignOpen(false)}
          onConfirm={runAssign}
          confirmLabel={t("bulk_link.confirm")}
          busy={assignBusy}
          error={assignError}
          emptyText={t("employees.assign_no_buildings")}
          testIdPrefix="employees-assign"
        />
      )}
    </div>
  );
}
