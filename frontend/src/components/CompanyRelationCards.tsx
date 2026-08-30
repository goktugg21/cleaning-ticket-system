import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { getApiError } from "../api/client";
import {
  bulkDeactivateBuildings,
  bulkDeactivateCustomers,
  bulkLinkBuildings,
  listAllUsersByRole,
  listCompanyBuildings,
  listCompanyCustomers,
  listCompanyEmployees,
} from "../api/admin";
import type {
  CompanyBuildingRow,
  CompanyCustomerRow,
  CompanyEmployee,
  UserAdmin,
} from "../api/types";
import { ConfirmDialog } from "./ConfirmDialog";
import type { ConfirmDialogHandle } from "./ConfirmDialog";
import { EditModeToggle } from "./EditModeToggle";
import { MultiSelectToolbar } from "./MultiSelectToolbar";
import { useEditMode } from "../lib/useEditMode";
import { BoundedList } from "./BoundedList";
import { useAuth } from "../auth/AuthContext";
import { roleLabelKey } from "../auth/permissions";
import type { Role } from "../api/types";
import { CompanyEmployeeDialog } from "../pages/admin/company/CompanyEmployeeDialog";

/**
 * Sprint 163 §4 — the company's three relation cards (employees,
 * buildings, customers), extracted so BOTH the company detail page and
 * the company edit page can carry them.
 *
 * ## Why a component rather than a second copy
 *
 * Sprint 159 shipped these cards on the detail page and they work. The
 * edit page has never had them, and three sprints in a row deferred
 * adding them because the only cheap route was to paste ~460 lines of
 * stateful JSX into a second file. That would have put a second copy of
 * the company-boundary rule into the codebase — a customer belongs to
 * exactly one provider — and a duplicated rule is the failure this
 * repository keeps recording. So the extraction IS the work.
 *
 * ## What it owns
 *
 * Everything: its three fetches, its three `useEditMode` controllers,
 * its dialogs, its busy and error state, and its own reload token. The
 * host page passes a company id and nothing else, which is what makes
 * mounting it on a second page one line rather than a negotiation over
 * twenty props.
 *
 * `readOnly` exists for a host that wants the cards as a read surface;
 * the edit page and the detail page both pass it false. It gates the
 * Edit affordance only — the BACKEND is the boundary, and every write
 * below still goes through the same scoped endpoints
 * (`/api/buildings/bulk-link/`, the company-admin views) that refuse a
 * cross-tenant target regardless of what this flag says.
 */
export function CompanyRelationCards({
  companyId,
  readOnly = false,
}: {
  companyId: number;
  readOnly?: boolean;
}) {
  const { t } = useTranslation("common");
  const { me } = useAuth();
  // Asked here rather than passed in: it is a question about the
  // VIEWER, not about the host page, so a prop would only be a way for
  // two hosts to answer it differently.
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const [employees, setEmployees] = useState<CompanyEmployee[]>([]);
  const [companyBuildings, setCompanyBuildings] = useState<CompanyBuildingRow[]>(
    [],
  );
  const [companyCustomers, setCompanyCustomers] = useState<CompanyCustomerRow[]>(
    [],
  );

  const canEdit = !readOnly;
  const employeeEdit = useEditMode(employees.map((row) => row.id));
  const buildingEdit = useEditMode(companyBuildings.map((row) => row.id));
  const customerEdit = useEditMode(companyCustomers.map((row) => row.id));

  const [cardBusy, setCardBusy] = useState(false);
  const [cardError, setCardError] = useState("");
  const [employeeAddOpen, setEmployeeAddOpen] = useState(false);
  const [candidates, setCandidates] = useState<{
    managers: UserAdmin[];
    workers: UserAdmin[];
  }>({ managers: [], workers: [] });

  const removeEmployeesDialogRef = useRef<ConfirmDialogHandle>(null);
  const deactivateBuildingsDialogRef = useRef<ConfirmDialogHandle>(null);
  const deactivateCustomersDialogRef = useRef<ConfirmDialogHandle>(null);

  // A reload TOKEN rather than a `load()` the effect calls: calling an
  // async loader from an effect body trips
  // `react-hooks/set-state-in-effect`, and the ESLint baseline is
  // frozen. Same shape the detail page used before the extraction.
  const [reloadKey, setReloadKey] = useState(0);
  const reload = () => setReloadKey((key) => key + 1);

  useEffect(() => {
    let cancelled = false;
    // Each read degrades to an empty card rather than failing the host
    // page: a company whose employees cannot be read must still show
    // its buildings. The host owns the company read and its errors.
    Promise.all([
      listCompanyEmployees(companyId).catch(() => []),
      listCompanyBuildings(companyId).catch(() => []),
      listCompanyCustomers(companyId).catch(() => []),
    ]).then(([employeeRows, buildingRows, customerRows]) => {
      if (cancelled) return;
      setEmployees(employeeRows);
      setCompanyBuildings(buildingRows);
      setCompanyCustomers(customerRows);
    });
    return () => {
      cancelled = true;
    };
  }, [companyId, reloadKey]);

  async function runCardWrite(work: () => Promise<void>) {
    setCardBusy(true);
    setCardError("");
    try {
      await work();
      reload();
    } catch (err) {
      setCardError(getApiError(err));
    } finally {
      setCardBusy(false);
    }
  }

  async function openEmployeeAdd() {
    setCardError("");
    setEmployeeAddOpen(true);
    if (candidates.managers.length > 0 || candidates.workers.length > 0) return;
    try {
      const [managers, workers] = await Promise.all([
        listAllUsersByRole("BUILDING_MANAGER"),
        listAllUsersByRole("STAFF"),
      ]);
      setCandidates({ managers, workers });
    } catch (err) {
      setCardError(getApiError(err));
    }
  }

  /**
   * Attach people to buildings of this company.
   *
   * TWO calls at most, because `bulk-link` takes ONE relation per
   * request and a manager and a worker are written to different
   * through-models. Each call is all-or-nothing server-side; they are
   * sequential so a failure in the second leaves a stated, re-readable
   * state rather than a race. The card re-reads either way, so what is
   * on screen after the dialog closes is what the server has.
   */
  async function confirmEmployeeAdd(args: {
    buildingIds: number[];
    managerIds: number[];
    workerIds: number[];
  }) {
    await runCardWrite(async () => {
      if (args.managerIds.length > 0) {
        await bulkLinkBuildings({
          buildings: args.buildingIds,
          relation: "managers",
          targets: args.managerIds,
          mode: "link",
        });
      }
      if (args.workerIds.length > 0) {
        await bulkLinkBuildings({
          buildings: args.buildingIds,
          relation: "staff",
          targets: args.workerIds,
          mode: "link",
        });
      }
      setEmployeeAddOpen(false);
      employeeEdit.clear();
    });
  }

  /**
   * Remove people FROM THE COMPANY — which means unlinking them from
   * every building of it, because that attachment IS what makes them an
   * employee of this company (see `CompanyEmployeeDialog`). Anything
   * less would leave them on the card.
   *
   * Grouped by role, because the relation differs; a person whose role
   * changed but whose old rows survived is handled by their CURRENT
   * role, and the leftovers stay visible on the card rather than being
   * silently guessed at.
   */
  async function removeEmployees(ids: number[]) {
    const buildingIds = companyBuildings.map((row) => row.id);
    if (buildingIds.length === 0) {
      // Reachable: `_company_employee_queryset` also admits a
      // STAFF/BUILDING_MANAGER attached by `CompanyUserMembership`
      // alone, and that person has no building link to cut. Say so
      // rather than letting the button do nothing, which is the
      // "control that lies" defect this sprint is about.
      setCardError(t("company_detail.employees_remove_no_buildings"));
      removeEmployeesDialogRef.current?.close();
      return;
    }
    const chosen = employees.filter((row) => ids.includes(row.id));
    const managers = chosen
      .filter((row) => row.role === "BUILDING_MANAGER")
      .map((row) => row.id);
    const workers = chosen
      .filter((row) => row.role === "STAFF")
      .map((row) => row.id);
    await runCardWrite(async () => {
      if (managers.length > 0) {
        await bulkLinkBuildings({
          buildings: buildingIds,
          relation: "managers",
          targets: managers,
          mode: "unlink",
        });
      }
      if (workers.length > 0) {
        await bulkLinkBuildings({
          buildings: buildingIds,
          relation: "staff",
          targets: workers,
          mode: "unlink",
        });
      }
      removeEmployeesDialogRef.current?.close();
      employeeEdit.exit();
    });
  }

  /**
   * "Remove" a building or a customer from a company is ARCHIVE, and
   * the button says so.
   *
   * `Building.company` and `Customer.company` are required FKs: there is
   * no state in which a building belongs to no provider, and moving one
   * to another provider would drag its tickets, extra work, invoices and
   * access rows across a tenant boundary — the H-1 breach §1b already
   * ruled out for customers. Archiving is the operation the system
   * actually has, so it is the one offered, under its own name.
   */
  async function deactivateBuildings(ids: number[]) {
    await runCardWrite(async () => {
      await bulkDeactivateBuildings(ids);
      deactivateBuildingsDialogRef.current?.close();
      buildingEdit.exit();
    });
  }

  async function deactivateCustomers(ids: number[]) {
    await runCardWrite(async () => {
      await bulkDeactivateCustomers(ids);
      deactivateCustomersDialogRef.current?.close();
      customerEdit.exit();
    });
  }

  return (
    <>
      {/* ONE surface for the three cards' writes. They share a busy flag
          and a re-read, so a second error state per card would only be a
          third place to forget to clear. Moved here with the cards in
          Sprint 163 §4 — it was on the host page, which meant the edit
          page would have had no way to show a card error at all. */}
      {cardError && (
        <div
          className="alert-error"
          style={{ marginBottom: 16 }}
          role="alert"
          data-testid="company-detail-card-error"
        >
          {cardError}
        </div>
      )}

      {/* Employees — the "who can do what, where" card. The
          buildings column is the reason this list exists; without it
          the page says who works here but not where. */}
      <details
        className="form-fold"
        id="company-employees"
        open
        data-testid="company-detail-employees-fold"
      >
        <summary className="form-fold-summary">
          {t("company_detail.employees_title")}
          <span className="form-fold-summary-value">{employees.length}</span>
        </summary>
      <section
        className="card"
        data-testid="company-detail-employees-card"
        style={{ padding: "20px 22px", marginBottom: 16 }}
      >
        <div className="section-head" style={{ marginBottom: 8 }}>
          <div>
            <div className="section-head-title">
              {t("company_detail.employees_title")}
            </div>
            <div className="section-head-sub">
              {t("company_detail.employees_desc")}
            </div>
          </div>
          {/* Sprint 155 §4 — Add and the selection UI live INSIDE
              edit mode; outside it the card is a clean read-only
              list and a mis-click cannot detach anybody. */}
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {(employeeEdit.editMode || employees.length === 0) && (
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => void openEmployeeAdd()}
                disabled={cardBusy || companyBuildings.length === 0}
                // With no buildings there is nothing to attach a
                // person TO, and the endpoint would refuse an empty
                // list. Said rather than left as a dead button.
                title={
                  companyBuildings.length === 0
                    ? t("company_detail.employee_add_needs_building")
                    : undefined
                }
                data-testid="company-detail-employees-add"
              >
                {t("building_detail.add")}
              </button>
            )}
            {canEdit && employees.length > 0 && (
              <EditModeToggle
                editMode={employeeEdit.editMode}
                onToggle={employeeEdit.toggleMode}
                disabled={cardBusy}
                testId="company-detail-employees-edit-toggle"
              />
            )}
          </div>
        </div>

        {employeeEdit.editMode && (
          <div className="list-edit-bar">
            <MultiSelectToolbar
              selectedCount={employeeEdit.selection.length}
              onSelectAll={employeeEdit.selectAll}
              onClearAll={employeeEdit.clear}
              disabled={cardBusy}
              actions={[
                {
                  key: "remove",
                  label: t("company_detail.employees_remove"),
                  destructive: true,
                  disabled: employeeEdit.selection.length === 0,
                  onClick: () =>
                    removeEmployeesDialogRef.current?.open(),
                },
              ]}
              testIdPrefix="company-detail-employees-bulk"
            />
          </div>
        )}

        <BoundedList
          size="md"
          count={employees.length}
          ariaLabel={t("company_detail.employees_title")}
          testIdPrefix="company-detail-employees"
          className="table-wrap"
          emptyState={
            <p className="muted small" style={{ padding: "12px 0", margin: 0 }}>
              {t("company_detail.employees_empty")}
            </p>
          }
        >
          <table className="data-table data-table-dense">
            <thead>
              {/* The checkbox column EXISTS only inside edit mode,
                  so the read view keeps exactly the geometry it
                  had. */}
              <tr>
                {employeeEdit.editMode && (
                  <th className="th-select">
                    <input
                      type="checkbox"
                      checked={employeeEdit.allSelected}
                      onChange={() =>
                        employeeEdit.allSelected
                          ? employeeEdit.clear()
                          : employeeEdit.selectAll()
                      }
                      disabled={cardBusy || employees.length === 0}
                      aria-label={t("company_detail.employees_title")}
                      data-testid="company-detail-employees-select-all"
                    />
                  </th>
                )}
                <th>{t("users.col_full_name")}</th>
                <th>{t("users.col_role")}</th>
                <th>{t("users.col_email")}</th>
                <th>{t("customer_contacts.field_phone")}</th>
                <th>{t("company_detail.col_buildings")}</th>
              </tr>
            </thead>
            <tbody>
              {employees.map((person) => (
                <tr key={person.id}>
                  {employeeEdit.editMode && (
                    <td className="td-select">
                      <input
                        type="checkbox"
                        checked={employeeEdit.isSelected(person.id)}
                        onChange={() => employeeEdit.toggle(person.id)}
                        disabled={cardBusy}
                        aria-label={person.full_name || person.email}
                        data-testid={`company-detail-employees-row-select-${person.id}`}
                      />
                    </td>
                  )}
                  <td className="td-subject">
                    <Link to={`/admin/users/${person.id}`}>
                      {person.full_name || person.email}
                    </Link>
                  </td>
                  <td>
                    {/* `role` comes off the wire as a string; the
                        label helper wants the Role union. Cast at
                        the boundary rather than widening the helper,
                        which every other caller relies on. */}
                    {t(roleLabelKey(person.role as Role))}
                  </td>
                  <td>
                    <a href={`mailto:${person.email}`}>{person.email}</a>
                  </td>
                  <td>
                    {person.phone ? (
                      <a href={`tel:${person.phone}`}>{person.phone}</a>
                    ) : (
                      <span className="muted-empty">—</span>
                    )}
                  </td>
                  <td>
                    {person.buildings.length === 0 ? (
                      <span className="muted-empty">—</span>
                    ) : (
                      <span
                        style={{ display: "flex", flexWrap: "wrap", gap: 6 }}
                      >
                        {person.buildings.map((b) => (
                          <Link
                            key={b.id}
                            to={`/admin/buildings/${b.id}`}
                            className="badge badge-normal"
                          >
                            {b.name}
                          </Link>
                        ))}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </BoundedList>
      </section>
      </details>

      {/* Buildings, each row a link to the building detail page. */}
      <details
        className="form-fold"
        id="company-buildings"
        
        data-testid="company-detail-buildings-fold"
      >
        <summary className="form-fold-summary">
          {t("company_detail.buildings_title")}
          <span className="form-fold-summary-value">{companyBuildings.length}</span>
        </summary>
      <section
        className="card"
        data-testid="company-detail-buildings-card"
        style={{ padding: "20px 22px", marginBottom: 16 }}
      >
        <div className="section-head" style={{ marginBottom: 8 }}>
          <div>
            <div className="section-head-title">
              {t("company_detail.buildings_title")}
            </div>
            <div className="section-head-sub">
              {t("company_detail.buildings_desc")}
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {/* "Add a building to this company" is a scoped CREATE,
                for the same reason "add a customer" is: `Building.
                company` is a required FK, so the only two readings
                are (a) create one under it or (b) MOVE one from
                another provider — and (b) drags its tickets, extra
                work and invoices across a tenant boundary. So (a),
                with the company pre-filled and locked. */}
            {(buildingEdit.editMode || companyBuildings.length === 0) && (
              <Link
                to={`/admin/buildings/new?company=${companyId}`}
                className="btn btn-secondary btn-sm"
                data-testid="company-detail-add-building"
              >
                {t("company_detail.add_building")}
              </Link>
            )}
            {canEdit && companyBuildings.length > 0 && (
              <EditModeToggle
                editMode={buildingEdit.editMode}
                onToggle={buildingEdit.toggleMode}
                disabled={cardBusy}
                testId="company-detail-buildings-edit-toggle"
              />
            )}
          </div>
        </div>

        {buildingEdit.editMode && (
          <div className="list-edit-bar">
            <MultiSelectToolbar
              selectedCount={buildingEdit.selection.length}
              onSelectAll={buildingEdit.selectAll}
              onClearAll={buildingEdit.clear}
              disabled={cardBusy}
              actions={[
                {
                  key: "deactivate",
                  label: t("company_detail.buildings_deactivate"),
                  destructive: true,
                  disabled: buildingEdit.selection.length === 0,
                  onClick: () =>
                    deactivateBuildingsDialogRef.current?.open(),
                },
              ]}
              testIdPrefix="company-detail-buildings-bulk"
            />
          </div>
        )}

        <BoundedList
          size="md"
          count={companyBuildings.length}
          ariaLabel={t("company_detail.buildings_title")}
          testIdPrefix="company-detail-buildings"
          className="table-wrap"
          emptyState={
            <p className="muted small" style={{ padding: "12px 0", margin: 0 }}>
              {t("company_detail.buildings_empty")}
            </p>
          }
        >
          <table className="data-table data-table-dense">
            <thead>
              <tr>
                {buildingEdit.editMode && (
                  <th className="th-select">
                    <input
                      type="checkbox"
                      checked={buildingEdit.allSelected}
                      onChange={() =>
                        buildingEdit.allSelected
                          ? buildingEdit.clear()
                          : buildingEdit.selectAll()
                      }
                      disabled={cardBusy || companyBuildings.length === 0}
                      aria-label={t("company_detail.buildings_title")}
                      data-testid="company-detail-buildings-select-all"
                    />
                  </th>
                )}
                <th>{t("admin.col_name")}</th>
                <th>{t("buildings.col_city")}</th>
                <th>{t("buildings.col_customers")}</th>
                <th>{t("status")}</th>
              </tr>
            </thead>
            <tbody>
              {companyBuildings.map((row) => (
                <tr key={row.id}>
                  {buildingEdit.editMode && (
                    <td className="td-select">
                      <input
                        type="checkbox"
                        checked={buildingEdit.isSelected(row.id)}
                        onChange={() => buildingEdit.toggle(row.id)}
                        disabled={cardBusy}
                        aria-label={row.name}
                        data-testid={`company-detail-buildings-row-select-${row.id}`}
                      />
                    </td>
                  )}
                  <td className="td-subject">
                    <Link
                      to={`/admin/buildings/${row.id}`}
                      data-testid={`company-detail-building-${row.id}`}
                    >
                      {row.name}
                    </Link>
                  </td>
                  <td>
                    {[row.city, row.postal_code].filter(Boolean).join(" · ") ||
                      row.address ||
                      "—"}
                  </td>
                  <td>{row.customer_count}</td>
                  <td>
                    {row.is_active
                      ? t("admin.status_active")
                      : t("admin.status_inactive")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </BoundedList>
      </section>
      </details>

      {/* Customers, each row a link to that customer's OVERVIEW page
          — the owner asked for this click-through explicitly. */}
      <details
        className="form-fold"
        id="company-customers"
        
        data-testid="company-detail-customers-fold"
      >
        <summary className="form-fold-summary">
          {t("company_detail.customers_title")}
          <span className="form-fold-summary-value">{companyCustomers.length}</span>
        </summary>
      <section
        className="card"
        data-testid="company-detail-customers-card"
        style={{ padding: "20px 22px", marginBottom: 16 }}
      >
        <div className="section-head" style={{ marginBottom: 8 }}>
          <div>
            <div className="section-head-title">
              {t("company_detail.customers_title")}
            </div>
            <div className="section-head-sub">
              {t("company_detail.customers_desc")}
            </div>
          </div>
          {/* Sprint 156 §1b — "Add customers to a company" is a
              scoped CREATE, not a link.

              `Customer.company` is a single ForeignKey: a customer
              belongs to exactly ONE provider. There is no
              company<->customer link table to add a row to, so the
              only two readings of "add a customer to this company"
              are (a) create one under it, or (b) MOVE an existing
              customer from another provider — and (b) would drag its
              buildings, users, access rows, prices, tickets and
              invoices across a tenant boundary, which is the H-1
              breach §1b itself calls non-negotiable. So: (a), with
              the company pre-filled and locked to this one. */}
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {isSuperAdmin &&
              (customerEdit.editMode || companyCustomers.length === 0) && (
                <Link
                  to={`/admin/customers/new?company=${companyId}`}
                  className="btn btn-secondary btn-sm"
                  data-testid="company-detail-add-customer"
                >
                  {t("company_detail.add_customer")}
                </Link>
              )}
            {canEdit && isSuperAdmin && companyCustomers.length > 0 && (
              <EditModeToggle
                editMode={customerEdit.editMode}
                onToggle={customerEdit.toggleMode}
                disabled={cardBusy}
                testId="company-detail-customers-edit-toggle"
              />
            )}
          </div>
        </div>

        {customerEdit.editMode && (
          <div className="list-edit-bar">
            <MultiSelectToolbar
              selectedCount={customerEdit.selection.length}
              onSelectAll={customerEdit.selectAll}
              onClearAll={customerEdit.clear}
              disabled={cardBusy}
              actions={[
                {
                  key: "deactivate",
                  label: t("company_detail.customers_deactivate"),
                  destructive: true,
                  disabled: customerEdit.selection.length === 0,
                  onClick: () =>
                    deactivateCustomersDialogRef.current?.open(),
                },
              ]}
              testIdPrefix="company-detail-customers-bulk"
            />
          </div>
        )}

        <BoundedList
          size="md"
          count={companyCustomers.length}
          ariaLabel={t("company_detail.customers_title")}
          testIdPrefix="company-detail-customers"
          className="table-wrap"
          emptyState={
            <p className="muted small" style={{ padding: "12px 0", margin: 0 }}>
              {t("company_detail.customers_empty")}
            </p>
          }
        >
          <table className="data-table data-table-dense">
            <thead>
              <tr>
                {customerEdit.editMode && (
                  <th className="th-select">
                    <input
                      type="checkbox"
                      checked={customerEdit.allSelected}
                      onChange={() =>
                        customerEdit.allSelected
                          ? customerEdit.clear()
                          : customerEdit.selectAll()
                      }
                      disabled={cardBusy || companyCustomers.length === 0}
                      aria-label={t("company_detail.customers_title")}
                      data-testid="company-detail-customers-select-all"
                    />
                  </th>
                )}
                <th>{t("admin.col_name")}</th>
                <th>{t("customer_view.overview.stat_linked_buildings")}</th>
                <th>{t("customer_view.overview.stat_users")}</th>
                <th>{t("status")}</th>
              </tr>
            </thead>
            <tbody>
              {companyCustomers.map((row) => (
                <tr key={row.id}>
                  {customerEdit.editMode && (
                    <td className="td-select">
                      <input
                        type="checkbox"
                        checked={customerEdit.isSelected(row.id)}
                        onChange={() => customerEdit.toggle(row.id)}
                        disabled={cardBusy}
                        aria-label={row.name}
                        data-testid={`company-detail-customers-row-select-${row.id}`}
                      />
                    </td>
                  )}
                  <td className="td-subject">
                    <Link
                      to={`/admin/customers/${row.id}`}
                      data-testid={`company-detail-customer-${row.id}`}
                    >
                      {row.name}
                    </Link>
                  </td>
                  <td>{row.building_count}</td>
                  <td>{row.user_count}</td>
                  <td>
                    {row.is_active
                      ? t("admin.status_active")
                      : t("admin.status_inactive")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </BoundedList>
      </section>
      </details>
      {/* Rendered UNCONDITIONALLY and ref-driven — a native
          <dialog> behind a condition mounts invisible and its
          trigger looks dead (CLAUDE.md §3). */}
      <ConfirmDialog
        ref={removeEmployeesDialogRef}
        title={t("company_detail.employees_remove_title")}
        body={t("company_detail.employees_remove_body", {
          count: employeeEdit.selection.length,
        })}
        confirmLabel={t("company_detail.employees_remove")}
        onConfirm={() => removeEmployees(employeeEdit.selection)}
        busy={cardBusy}
        destructive
      />

      <ConfirmDialog
        ref={deactivateBuildingsDialogRef}
        title={t("company_detail.buildings_deactivate_title")}
        body={t("company_detail.buildings_deactivate_body", {
          count: buildingEdit.selection.length,
        })}
        confirmLabel={t("company_detail.buildings_deactivate")}
        onConfirm={() => deactivateBuildings(buildingEdit.selection)}
        busy={cardBusy}
        destructive
      />

      <ConfirmDialog
        ref={deactivateCustomersDialogRef}
        title={t("company_detail.customers_deactivate_title")}
        body={t("company_detail.customers_deactivate_body", {
          count: customerEdit.selection.length,
        })}
        confirmLabel={t("company_detail.customers_deactivate")}
        onConfirm={() => deactivateCustomers(customerEdit.selection)}
        busy={cardBusy}
        destructive
      />

      {/* Conditionally mounted overlay — the deliberate other half
          of the same rule. */}
      {employeeAddOpen && (
        <CompanyEmployeeDialog
          buildingOptions={companyBuildings.map((row) => ({
            id: row.id,
            label: row.name,
            sublabel: [row.city, row.postal_code]
              .filter(Boolean)
              .join(" · "),
          }))}
          managerOptions={candidates.managers.map((person) => ({
            id: person.id,
            label: person.full_name || person.email,
            sublabel: person.email,
          }))}
          workerOptions={candidates.workers.map((person) => ({
            id: person.id,
            label: person.full_name || person.email,
            sublabel: person.email,
          }))}
          busy={cardBusy}
          error={cardError}
          onCancel={() => setEmployeeAddOpen(false)}
          onConfirm={(args) => void confirmEmployeeAdd(args)}
        />
      )}

    </>
  );
}
