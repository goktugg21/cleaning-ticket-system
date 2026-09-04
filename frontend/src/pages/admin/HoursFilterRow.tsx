import { useTranslation } from "react-i18next";

import type { HourType, TimesheetEmployee } from "../../api/timesheets.types";
import type { BuildingAdmin } from "../../api/types";
import { hourTypeLabel } from "../../lib/hourTypeLabel";

/**
 * The employee / source / hour-type / building filter controls on the
 * Hours admin's Worked tab.
 *
 * W-HR1 §2 — it was shared with the Overview tab, which is deleted, so
 * this now has ONE caller. Kept as its own file rather than inlined:
 * four pickers and their empty-option handling are the bulk of the
 * filter row, and folding them back into an 1100-line page is the
 * direction this area has been moving away from.
 *
 * The markup is the house `.filter-field` / `.filter-label` /
 * `.filter-control` set, so the row wraps inside `.filter-bar` the way
 * every other admin list's does. It was `.field` / `.field-select`
 * inside a nowrap, horizontally-scrolling `.hours-filter-line`, which
 * is why the last two controls sat off the right edge at 1366.
 *
 * Deliberately NOT including the PERIOD controls: the week bar and the
 * from/to pair belong to the page, which owns the week.
 */
export interface HoursFilterValues {
  employee: number | "";
  hour_type: number | "";
  building: number | "";
  /** Sprint 174 §1 — WHERE the hour came from. Sprint 173 added the
   *  column and the API filter and stopped there; the owner looked for
   *  the control and it was not on the screen.
   *
   *  OPTIONAL, and the control renders only when the caller passes
   *  it — a filter that appears whether or not the screen wants it is
   *  how a filter row grows past what any one screen needs. */
  source_type?: string;
}

export interface HoursFilterRowProps {
  values: HoursFilterValues;
  onChange: (patch: Partial<HoursFilterValues>) => void;
  employees: TimesheetEmployee[];
  hourTypes: HourType[];
  buildings: BuildingAdmin[];
  /** Prefixes the DOM ids and test ids. */
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
      <div className="filter-field">
        <span className="filter-label">
          {t("hours_admin.filter_employee")}
        </span>
        <select
          id={`${idPrefix}-filter-employee`}
          className="filter-control"
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

      {values.source_type !== undefined && (
      <div className="filter-field">
        <span className="filter-label">
          {t("hours_admin.filter_source")}
        </span>
        <select
          id={`${idPrefix}-filter-source`}
          className="filter-control"
          value={values.source_type}
          onChange={(event) => onChange({ source_type: event.target.value })}
          data-testid={`${idPrefix}-filter-source`}
          disabled={disabled}
        >
          <option value="">{t("hours_admin.filter_all_sources")}</option>
          {(["CONTRACT", "EXTRA_WORK", "TICKET", "OTHER"] as const).map(
            (value) => (
              <option key={value} value={value}>
                {t(`hour_source.${value}`)}
              </option>
            ),
          )}
        </select>
      </div>
      )}

      <div className="filter-field">
        <span className="filter-label">
          {t("hours_admin.filter_hour_type")}
        </span>
        <select
          id={`${idPrefix}-filter-hour-type`}
          className="filter-control"
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

      <div className="filter-field">
        <span className="filter-label">
          {t("hours_admin.filter_building")}
        </span>
        <select
          id={`${idPrefix}-filter-building`}
          className="filter-control"
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
