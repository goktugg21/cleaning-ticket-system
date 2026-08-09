/**
 * Sprint 157 §1 — "Set up week": pick the people AND the buildings first,
 * then the table gets built from that choice.
 *
 * This is the fourth attempt at the same request, so it is worth being
 * explicit about what changed. Sprint 154 gave one employee and one
 * implicit building. Sprint 155 separated the grid's employees from the
 * page's filter and made the employee side multi-select. Sprint 156 let
 * a row be pointed at a building AFTER it was added. None of those is
 * what was asked for: the owner wants the employees and the buildings
 * chosen together, up front, and the rows to exist as a result.
 *
 * So the setup is a modal — his own suggestion, and the right one. It
 * separates "what am I about to type into" from "typing", which is
 * exactly the confusion that a row-by-row build creates. Confirm closes
 * the modal and the grid opens with one row per (employee, building)
 * pair already there.
 *
 * The summary line is not decoration. `4 employees x 3 buildings = 12
 * rows` is the difference between a confident confirm and a surprise,
 * and it is the same reason `BulkAssignDialog` has carried a mandatory
 * summary since Sprint 154.
 *
 * A NON-native overlay, conditionally mounted, like every other editing
 * modal in this codebase. CLAUDE.md's render-unconditionally rule is
 * about the native `<dialog>` element; `ConfirmDialog` stays native and
 * ref-driven where it is used.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { EntityPicker } from "../EntityPicker";
import type { BuildingAdmin } from "../../api/types";
import type { TimesheetEmployee } from "../../api/timesheets.types";
import { formatIsoWeek, parseIsoWeek } from "../../lib/isoWeek";
import type { IsoWeek } from "../../lib/isoWeek";

/** The sentinel the picker uses for "these hours are not tied to a
 *  location". `TimeEntry.building` is nullable BY DESIGN and stays that
 *  way — this is a UI affordance for choosing null, not a model change,
 *  and it is mapped back to null the moment the dialog confirms. Zero is
 *  safe as a sentinel because every real building id is a positive
 *  auto-increment pk. */
export const NO_BUILDING_ID = 0;

export interface WeekSetup {
  employeeIds: number[];
  /** `null` means "no building" — never `0`, which is the picker's
   *  private sentinel and must not leak past this dialog. */
  buildingIds: (number | null)[];
  week: IsoWeek;
}

export function WeekSetupDialog({
  employees,
  buildings,
  initialWeek,
  initialEmployeeIds,
  initialBuildingIds,
  onCancel,
  onConfirm,
}: {
  employees: TimesheetEmployee[];
  buildings: BuildingAdmin[];
  initialWeek: IsoWeek;
  initialEmployeeIds: number[];
  initialBuildingIds: (number | null)[];
  onCancel: () => void;
  onConfirm: (setup: WeekSetup) => void;
}) {
  const { t } = useTranslation("common");
  const firstRef = useRef<HTMLInputElement>(null);

  const [employeeIds, setEmployeeIds] = useState<number[]>(initialEmployeeIds);
  const [buildingIds, setBuildingIds] = useState<number[]>(
    initialBuildingIds.map((id) => id ?? NO_BUILDING_ID),
  );
  const [week, setWeek] = useState<IsoWeek>(initialWeek);

  // Escape closes. One effect, and it touches only a listener — no
  // setState in an effect body.
  useEffect(() => {
    firstRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  const buildingOptions = useMemo(
    () => [
      // Offered FIRST, because for a cleaner whose hours are not tied to
      // a site it is the only correct answer and should not be hunted
      // for at the bottom of a long list.
      {
        id: NO_BUILDING_ID,
        label: t("hours_week_grid.no_building"),
        sublabel: t("week_setup.no_building_hint"),
      },
      ...buildings.map((building) => ({
        id: building.id,
        label: building.name,
        sublabel: [building.city, building.address].filter(Boolean).join(" · "),
      })),
    ],
    [buildings, t],
  );

  const rowCount = employeeIds.length * buildingIds.length;
  const canConfirm = employeeIds.length > 0 && buildingIds.length > 0;

  return (
    <div
      data-testid="week-setup-modal"
      role="dialog"
      aria-modal="true"
      aria-label={t("week_setup.title")}
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
          maxWidth: 760,
          width: "100%",
          padding: 24,
          maxHeight: "90vh",
          overflowY: "auto",
        }}
      >
        <h3 style={{ marginTop: 0, marginBottom: 4 }}>
          {t("week_setup.title")}
        </h3>
        <p className="muted small" style={{ marginTop: 0, marginBottom: 16 }}>
          {t("week_setup.subtitle")}
        </p>

        <div className="field" style={{ marginBottom: 16 }}>
          <span className="field-label">{t("week_setup.week_label")}</span>
          <input
            ref={firstRef}
            className="field-input"
            type="week"
            value={formatIsoWeek(week)}
            onChange={(event) => {
              const parsed = parseIsoWeek(event.target.value);
              if (parsed) setWeek(parsed);
            }}
            style={{ width: 180 }}
            data-testid="week-setup-week"
          />
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            gap: 16,
          }}
        >
          <div className="field">
            <span className="field-label">
              {t("week_setup.employees_label")}
            </span>
            <EntityPicker
              options={employees.map((employee) => ({
                id: employee.id,
                label: employee.full_name || employee.email,
                sublabel: employee.email,
              }))}
              selectedIds={employeeIds}
              onChange={setEmployeeIds}
              emptyText={t("hours_week_grid.no_employees")}
              testIdPrefix="week-setup-employees"
            />
          </div>

          <div className="field">
            <span className="field-label">
              {t("week_setup.buildings_label")}
            </span>
            <EntityPicker
              options={buildingOptions}
              selectedIds={buildingIds}
              onChange={setBuildingIds}
              emptyText={t("week_setup.no_buildings")}
              testIdPrefix="week-setup-buildings"
            />
          </div>
        </div>

        {/* The live count. Never omitted — see the header comment. */}
        <p
          className="week-setup-summary"
          data-testid="week-setup-summary"
          role="status"
        >
          {t("week_setup.summary", {
            employees: employeeIds.length,
            buildings: buildingIds.length,
            rows: rowCount,
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
            data-testid="week-setup-cancel"
          >
            {t("cancel")}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!canConfirm}
            onClick={() =>
              onConfirm({
                employeeIds,
                // The sentinel is translated back to null HERE, so
                // nothing downstream ever sees a building id of 0.
                buildingIds: buildingIds.map((id) =>
                  id === NO_BUILDING_ID ? null : id,
                ),
                week,
              })
            }
            data-testid="week-setup-confirm"
          >
            {t("week_setup.confirm")}
          </button>
        </div>
      </div>
    </div>
  );
}
