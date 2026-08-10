/**
 * Sprint 159 §4 — put people into a provider company, from the company's
 * own page.
 *
 * ## Why this dialog has a BUILDINGS picker
 *
 * "Add an employee to this company" has no single row behind it.
 * `companies/views_summary.py::_company_employee_queryset` already
 * documents why: a COMPANY_ADMIN is attached through
 * `CompanyUserMembership`, but a STAFF member belongs to a company
 * through `BuildingStaffVisibility` and a BUILDING_MANAGER through
 * `BuildingManagerAssignment`. There is no `User.company` to set. The
 * real write is "attach this person to these buildings", which is
 * exactly what `/api/buildings/bulk-link/` does.
 *
 * So the dialog asks for both halves rather than inventing a
 * company-level attachment that the read side would then have to guess
 * at. Picking nothing but people would leave an "employee" the
 * employees card cannot see — a write that appears to succeed and
 * changes nothing on screen.
 *
 * ## Two pickers for people, not one plus a role switch
 *
 * The same reason `AssignPeopleDialog` has two: eligibility differs by
 * role, the relation written differs by role (`staff` vs `managers`),
 * and the owner has asked twice now for both at once rather than one
 * operation per role.
 *
 * A NON-native overlay, conditionally mounted, like every other editing
 * modal here (CLAUDE.md §3).
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { EntityPicker } from "../../../components/EntityPicker";
import type { EntityPickerOption } from "../../../components/EntityPicker";

export function CompanyEmployeeDialog({
  buildingOptions,
  managerOptions,
  workerOptions,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  /** The company's OWN buildings. A person cannot be attached to
   *  somebody else's, and the endpoint would refuse it anyway. */
  buildingOptions: EntityPickerOption[];
  managerOptions: EntityPickerOption[];
  workerOptions: EntityPickerOption[];
  busy?: boolean;
  error?: string;
  onCancel: () => void;
  onConfirm: (args: {
    buildingIds: number[];
    managerIds: number[];
    workerIds: number[];
  }) => void;
}) {
  const { t } = useTranslation("common");
  const [buildingIds, setBuildingIds] = useState<number[]>([]);
  const [managerIds, setManagerIds] = useState<number[]>([]);
  const [workerIds, setWorkerIds] = useState<number[]>([]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  const peopleCount = managerIds.length + workerIds.length;
  const canConfirm = buildingIds.length > 0 && peopleCount > 0;

  return (
    <div
      data-testid="company-employee-modal"
      role="dialog"
      aria-modal="true"
      aria-label={t("company_detail.employee_add_title")}
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
          maxWidth: 900,
          width: "100%",
          padding: 24,
          maxHeight: "90vh",
          overflowY: "auto",
        }}
      >
        <h3 style={{ marginTop: 0, marginBottom: 4 }}>
          {t("company_detail.employee_add_title")}
        </h3>
        <p className="muted small" style={{ marginTop: 0, marginBottom: 16 }}>
          {t("company_detail.employee_add_desc")}
        </p>

        {error && (
          <div
            className="alert-error"
            role="alert"
            style={{ marginBottom: 12 }}
            data-testid="company-employee-error"
          >
            {error}
          </div>
        )}

        <div className="assign-people-columns">
          <div className="field">
            <span className="field-label">
              {t("company_detail.employee_add_buildings")}
            </span>
            <EntityPicker
              options={buildingOptions}
              selectedIds={buildingIds}
              onChange={setBuildingIds}
              disabled={busy}
              emptyText={t("company_detail.buildings_empty")}
              testIdPrefix="company-employee-buildings"
            />
          </div>
          <div className="field">
            <span className="field-label">
              {t("assign_people.managers_label")}
            </span>
            <EntityPicker
              options={managerOptions}
              selectedIds={managerIds}
              onChange={setManagerIds}
              disabled={busy}
              emptyText={t("company_detail.no_manager_candidates")}
              testIdPrefix="company-employee-managers"
            />
          </div>
          <div className="field">
            <span className="field-label">
              {t("assign_people.workers_label")}
            </span>
            <EntityPicker
              options={workerOptions}
              selectedIds={workerIds}
              onChange={setWorkerIds}
              disabled={busy}
              emptyText={t("company_detail.no_worker_candidates")}
              testIdPrefix="company-employee-workers"
            />
          </div>
        </div>

        {/* The mandatory "N x M" line — the operator is about to create
            `people x buildings` links from two lists. */}
        <p
          className="week-setup-summary"
          role="status"
          data-testid="company-employee-summary"
        >
          {t("company_detail.employee_add_summary", {
            people: peopleCount,
            buildings: buildingIds.length,
            links: peopleCount * buildingIds.length,
          })}
        </p>

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
            className="btn btn-secondary btn-sm"
            onClick={onCancel}
            disabled={busy}
            data-testid="company-employee-cancel"
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy || !canConfirm}
            onClick={() => onConfirm({ buildingIds, managerIds, workerIds })}
            data-testid="company-employee-confirm"
          >
            {t("building_detail.add")}
          </button>
        </div>
      </div>
    </div>
  );
}
