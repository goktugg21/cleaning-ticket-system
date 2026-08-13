/**
 * Sprint 168 §1 — Bulk assignment for contract hours.
 *
 * Sprint 167 built the model, the tab, the tiles, the filters and the
 * table, and no way to add a row. The tab therefore read "no contract
 * hours recorded yet" forever and the approval screen had nothing to
 * approve. This is the missing half, and without it the other two
 * screens are decoration.
 *
 * ## It REUSES the week grid, it does not copy it
 *
 * `HoursWeekGrid` already owns the block layout, the fill-all line, the
 * per-block `+ Add type`, and — the one that took three sprints to get
 * right — the Sprint 166 rule that a row added with `+ Add type` is
 * never touched by the fill line. A second grid would drift from all
 * four. What actually differs here is the DESTINATION, so only the
 * destination is passed: `onSaveCells` takes the cells the grid
 * collected and writes them as contract hours instead of time entries.
 *
 * ## Why a week, when a contract-hours row has no week
 *
 * A contract-hours row is a weekly PATTERN: Monday through Sunday, no
 * date. The grid's columns are dates. So the dialog picks the ISO week
 * that CONTAINS the valid-from date, hands the grid that week, and maps
 * each date back to its weekday on the way out. The week is a rendering
 * frame, never stored — what gets written is `valid_from` plus seven
 * weekday values, exactly as the model defines them.
 *
 * A NON-native overlay, conditionally mounted, like every other editing
 * modal here.
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import type { HourType, TimesheetEmployee } from "../../api/timesheets.types";
import type { BuildingAdmin } from "../../api/types";
import { ChipMultiSelect } from "../ChipMultiSelect";
import { usePickerReserve } from "../../lib/usePickerReserve";
import { workTypeLabel } from "../../lib/workTypeLabel";
import { fromDateString, isoWeekOf, toDateString } from "../../lib/isoWeek";
import { HoursWeekGrid } from "./HoursWeekGrid";
import type { GridCell } from "./HoursWeekGrid";
import { NO_BUILDING_ID } from "./WeekEntryDialog";

const DAYS = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
] as const;

interface WorkTypeOption {
  id: number;
  name: string;
  standard_slot?: string;
}

/** One row as the bulk endpoint wants it: a pair, a type, seven days. */
interface BulkRow {
  employee: number;
  building: number | null;
  hour_type: number;
  work_type: number | null;
  monday: string;
  tuesday: string;
  wednesday: string;
  thursday: string;
  friday: string;
  saturday: string;
  sunday: string;
}

export function ContractHoursBulkDialog({
  employees,
  buildings,
  hourTypes,
  workTypes,
  companyId,
  onClose,
  onSaved,
}: {
  employees: TimesheetEmployee[];
  buildings: BuildingAdmin[];
  /** ACTIVE hour types only — an archived one is refused server-side. */
  hourTypes: HourType[];
  workTypes: WorkTypeOption[];
  companyId?: number | null;
  onClose: () => void;
  onSaved: (created: number) => void | Promise<void>;
}) {
  const { t } = useTranslation("common");

  const [employeeIds, setEmployeeIds] = useState<number[]>([]);
  const [buildingIds, setBuildingIds] = useState<number[]>([]);
  const [workType, setWorkType] = useState<number | "">("");
  const [validFrom, setValidFrom] = useState(() =>
    toDateString(new Date()),
  );

  // Sprint 169 §1 — the modal grows to CONTAIN an open picker list,
  // and shrinks back when it closes. See `usePickerReserve` for why a
  // portalled list cannot be contained by CSS alone.
  const { modalRef, spacerRef, reserve, onPickerOpenChange } =
    usePickerReserve();

  // Escape closes. One effect, and it touches only a listener.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  /** The rendering frame: the ISO week containing valid-from. */
  const week = useMemo(() => {
    try {
      return isoWeekOf(fromDateString(validFrom));
    } catch {
      return isoWeekOf(new Date());
    }
  }, [validFrom]);

  const buildingOptions = useMemo(
    () => [
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

  const gridEmployees = useMemo(
    () =>
      employees
        .filter((employee) => employeeIds.includes(employee.id))
        .map((employee) => ({
          id: employee.id,
          name: employee.full_name || employee.email,
        })),
    [employees, employeeIds],
  );

  const seedBuildingIds = useMemo(
    () => buildingIds.map((id) => (id === NO_BUILDING_ID ? null : id)),
    [buildingIds],
  );

  /**
   * The cells the grid collected, folded into contract-hours rows.
   *
   * The grid emits one cell per (employee, hour type, building, DATE).
   * A contract-hours row is one (employee, hour type, building) with
   * seven weekday columns, so the fold is by that triple and the date
   * becomes the column. `getDay()` is 0=Sunday and the grid is
   * Monday-first, hence the rotation.
   */
  async function saveCells(cells: GridCell[]): Promise<number> {
    const byKey = new Map<string, BulkRow>();
    for (const cell of cells) {
      const key = `${cell.employee}:${cell.building ?? 0}:${cell.hour_type}`;
      let row = byKey.get(key);
      if (!row) {
        row = {
          employee: cell.employee,
          building: cell.building,
          hour_type: cell.hour_type,
          work_type: workType === "" ? null : workType,
          monday: "0",
          tuesday: "0",
          wednesday: "0",
          thursday: "0",
          friday: "0",
          saturday: "0",
          sunday: "0",
        };
        byKey.set(key, row);
      }
      const index = (fromDateString(cell.date).getDay() + 6) % 7;
      row[DAYS[index]] = cell.hours;
    }
    const rows = [...byKey.values()];
    if (rows.length === 0) return 0;
    // ONE request, all-or-nothing server-side: an operator who filled in
    // twelve rows and got eight saved could not tell which four missed.
    const response = await api.post("/timesheets/contract-hours/bulk/", {
      valid_from: validFrom,
      rows,
    });
    const created = Array.isArray(response.data) ? response.data.length : 0;
    await onSaved(created);
    return created;
  }

  return (
    <div
      data-testid="contract-hours-bulk-modal"
      role="dialog"
      aria-modal="true"
      aria-label={t("contract_hours.bulk_title")}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        // Anchored to the TOP, for the Sprint 167 reason: a centred
        // dialog that grows moves its own header out from under the
        // operator's cursor.
        alignItems: "flex-start",
        justifyContent: "center",
        zIndex: 100,
        padding: 16,
        paddingTop: "6vh",
        overflowY: "auto",
      }}
    >
      <div
        ref={modalRef}
        className="card week-entry-modal"
        style={{
          width: "min(96vw, 1180px)",
          maxWidth: 1180,
          padding: 24,
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <h3 className="section-title" style={{ marginTop: 0, marginBottom: 4 }}>
          {t("contract_hours.bulk_title")}
        </h3>
        <p className="muted small" style={{ marginTop: 0, marginBottom: 16 }}>
          {t("contract_hours.bulk_subtitle")}
        </p>

        <div className="week-entry-setup-row" data-testid="bulk-setup">
          <div className="field">
            <span className="field-label">
              {t("week_setup.employees_label")}
            </span>
            <ChipMultiSelect
              options={employees.map((employee) => ({
                id: employee.id,
                label: employee.full_name || employee.email,
                sublabel: employee.email,
              }))}
              selectedIds={employeeIds}
              onChange={setEmployeeIds}
              placeholder={t("week_setup.select_workers")}
              removeLabel={(label) =>
                t("week_setup.remove_worker", { name: label })
              }
              emptyText={t("hours_week_grid.no_employees")}
              onOpenChange={onPickerOpenChange}
              testIdPrefix="bulk-employees"
            />
          </div>

          <div className="field">
            <span className="field-label">
              {t("week_setup.buildings_label")}
            </span>
            <ChipMultiSelect
              options={buildingOptions}
              selectedIds={buildingIds}
              onChange={setBuildingIds}
              placeholder={t("week_setup.select_buildings")}
              removeLabel={(label) =>
                t("week_setup.remove_building", { name: label })
              }
              emptyText={t("week_setup.no_buildings")}
              onOpenChange={onPickerOpenChange}
              testIdPrefix="bulk-buildings"
            />
          </div>

          <div className="field">
            <span className="field-label">
              {t("contract_hours.valid_from")}
            </span>
            <input
              className="field-input"
              type="date"
              value={validFrom}
              onChange={(event) => setValidFrom(event.target.value)}
              data-testid="bulk-valid-from"
            />
            <p className="muted small" style={{ margin: "6px 0 0" }}>
              {t("contract_hours.bulk_week_hint")}
            </p>
          </div>

          <div className="field">
            <span className="field-label">
              {t("contract_hours.work_type")}
            </span>
            {/* Sprint 169 §2 — an empty catalog SAYS so. An empty
                dropdown with no explanation reads as broken, and until
                this sprint there was no screen anywhere that could put
                a row in it. */}
            <select
              className="field-input"
              value={workType}
              onChange={(event) =>
                setWorkType(
                  event.target.value === "" ? "" : Number(event.target.value),
                )
              }
              data-testid="bulk-work-type"
            >
              <option value="">{t("contract_hours.no_work_type")}</option>
              {workTypes.map((type) => (
                <option key={type.id} value={type.id}>
                  {workTypeLabel(type.name, type.standard_slot, t)}
                </option>
              ))}
            </select>
            {workTypes.length === 0 && (
              <p className="muted small" data-testid="bulk-no-work-types">
                {t("work_types.none_yet")}
              </p>
            )}
            <p
              className="week-setup-summary"
              data-testid="bulk-summary"
              role="status"
            >
              {t("week_setup.summary", {
                employees: employeeIds.length,
                buildings: buildingIds.length,
                rows: employeeIds.length * buildingIds.length,
              })}
            </p>
          </div>
        </div>

        <HoursWeekGrid
          week={week}
          employees={gridEmployees}
          companyId={companyId}
          hourTypes={hourTypes}
          buildings={buildings}
          // Nothing pre-fills: this writes NEW standing agreements, and
          // showing an existing one here would invite editing it in a
          // dialog whose Save creates rows rather than amending them.
          entriesByEmployee={{}}
          seedBuildingIds={seedBuildingIds}
          weekClosed={false}
          onSaved={onClose}
          onCancel={onClose}
          onSaveCells={saveCells}
        />
        {/* Sprint 170 §8 — the reserve, as a real element. Its TOP is
            where the modal's content ends and does not move when its
            own height changes, which is what makes the measurement
            self-consistent. */}
        <div
          ref={spacerRef}
          style={{ flex: "0 0 auto", height: reserve }}
          aria-hidden="true"
          data-testid="picker-reserve-spacer"
        />
      </div>
    </div>
  );
}
