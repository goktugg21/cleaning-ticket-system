import { useTranslation } from "react-i18next";

import type { HourType, TimesheetEmployee } from "../../api/timesheets.types";
import type { BuildingAdmin } from "../../api/types";
import { hourTypeLabel } from "../../lib/hourTypeLabel";

/**
 * Sprint 152.2 — the employee / hour-type / building filter row, shared
 * by the Entries tab and the Overview tab.
 *
 * EXTRACTED rather than copied. Both tabs filter the same collection
 * with the same three controls, and a second hand-maintained copy is
 * exactly the "written once, omitted elsewhere" defect this project has
 * paid for repeatedly — the Sprint 126 permission group that rendered a
 * headerless column for three sprints, and the Sprint 142.1 uniqueness
 * pre-check that was fixed in one serializer and left broken in its
 * twin. One component means a fourth filter is added once.
 *
 * Deliberately NOT including the PERIOD controls: the two tabs differ
 * there on purpose (Entries has a plain from/to pair, Overview has the
 * week/range mode switch), and folding both into one component would
 * make it a switch statement pretending to be a shared control.
 */
export interface HoursFilterValues {
  employee: number | "";
  hour_type: number | "";
  building: number | "";
}

export interface HoursFilterRowProps {
  values: HoursFilterValues;
  onChange: (patch: Partial<HoursFilterValues>) => void;
  employees: TimesheetEmployee[];
  hourTypes: HourType[];
  buildings: BuildingAdmin[];
  /** Distinguishes the two tabs' DOM ids and test ids. */
  idPrefix: string;
  disabled?: boolean;
}

export function HoursFilterRow({
  values,
  onChange,
  employees,
  hourTypes,
  buildings,
  idPrefix,
  disabled = false,
}: HoursFilterRowProps) {
  const { t } = useTranslation("common");

  return (
    <>
      <div className="field" style={{ margin: 0 }}>
        <label className="field-label" htmlFor={`${idPrefix}-filter-employee`}>
          {t("hours_admin.filter_employee")}
        </label>
        <select
          id={`${idPrefix}-filter-employee`}
          className="field-select"
          value={values.employee === "" ? "" : String(values.employee)}
          onChange={(event) =>
            onChange({
              employee:
                event.target.value === "" ? "" : Number(event.target.value),
            })
          }
          data-testid={`${idPrefix}-filter-employee`}
          disabled={disabled}
        >
          <option value="">{t("hours_admin.filter_all")}</option>
          {employees.map((employee) => (
            <option key={employee.id} value={employee.id}>
              {employee.full_name || employee.email}
            </option>
          ))}
        </select>
      </div>

      <div className="field" style={{ margin: 0 }}>
        <label className="field-label" htmlFor={`${idPrefix}-filter-hour-type`}>
          {t("hours_admin.filter_hour_type")}
        </label>
        <select
          id={`${idPrefix}-filter-hour-type`}
          className="field-select"
          value={values.hour_type === "" ? "" : String(values.hour_type)}
          onChange={(event) =>
            onChange({
              hour_type:
                event.target.value === "" ? "" : Number(event.target.value),
            })
          }
          data-testid={`${idPrefix}-filter-hour-type`}
          disabled={disabled}
        >
          <option value="">{t("hours_admin.filter_all")}</option>
          {hourTypes.map((hourType) => (
            <option key={hourType.id} value={hourType.id}>
              {hourTypeLabel(hourType, t)}
            </option>
          ))}
        </select>
      </div>

      <div className="field" style={{ margin: 0 }}>
        <label className="field-label" htmlFor={`${idPrefix}-filter-building`}>
          {t("hours_admin.filter_building")}
        </label>
        <select
          id={`${idPrefix}-filter-building`}
          className="field-select"
          value={values.building === "" ? "" : String(values.building)}
          onChange={(event) =>
            onChange({
              building:
                event.target.value === "" ? "" : Number(event.target.value),
            })
          }
          data-testid={`${idPrefix}-filter-building`}
          disabled={disabled}
        >
          <option value="">{t("hours_admin.filter_all")}</option>
          {buildings.map((building) => (
            <option key={building.id} value={building.id}>
              {building.name}
            </option>
          ))}
        </select>
      </div>
    </>
  );
}
