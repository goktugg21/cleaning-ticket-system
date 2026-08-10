/**
 * Sprint 159 §1 — enter a week. ONE modal, opened by the one primary
 * button on the Hours page.
 *
 * It replaces `WeekSetupDialog` + the in-page week grid, which were two
 * halves of this and the reason the page had a grid on it AND a grid in
 * a modal. The owner's verdict on that arrangement — *the hours area has
 * got very confused* — was about exactly that duplication.
 *
 * The order inside is the reference system's:
 *
 *   1. the choices, SIDE BY SIDE (employees, buildings, hour types,
 *      week) — the owner asked for this explicitly, rather than stacked
 *      down the page;
 *   2. the grid those choices produce, one row per (employee, building,
 *      hour type);
 *   3. Cancel / Save.
 *
 * ## Two independent reads, deliberately NOT one Promise.all
 *
 * Sprint 155 shipped them combined and it was a real bug, caught by
 * measuring the built page: `weeks/status/` 400s for a SUPER_ADMIN who
 * has not disambiguated a company (`timesheet_company_required`), which
 * rejected the combined promise and threw away the ENTRIES — whose own
 * request had returned 200. The grid rendered empty over a week that had
 * rows in it. Split, a failure in the lock read can never discard the
 * entries, and an unknown lock state defaults to OPEN — which only
 * affects whether the cells look editable, because the SERVER refuses a
 * write into a closed week regardless.
 *
 * A NON-native overlay, conditionally mounted, like every other editing
 * modal in this codebase. CLAUDE.md's render-unconditionally rule is
 * about the native `<dialog>` element; `ConfirmDialog` stays native and
 * ref-driven where it is used.
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchWeekStatus, listTimeEntries } from "../../api/timesheets";
import type {
  HourType,
  TimeEntry,
  TimesheetEmployee,
} from "../../api/timesheets.types";
import type { BuildingAdmin } from "../../api/types";
import { EntityPicker } from "../EntityPicker";
import { formatIsoWeek, parseIsoWeek } from "../../lib/isoWeek";
import type { IsoWeek } from "../../lib/isoWeek";
import { HoursWeekGrid } from "./HoursWeekGrid";

/** The picker's sentinel for "these hours are not tied to a location".
 *  `TimeEntry.building` is nullable BY DESIGN and stays that way — this
 *  is a UI affordance for choosing null, mapped back to null before it
 *  reaches the grid. Zero is safe because every real building id is a
 *  positive auto-increment pk. */
export const NO_BUILDING_ID = 0;

export function WeekEntryDialog({
  employees,
  buildings,
  hourTypes,
  companyId,
  initialWeek,
  onClose,
  onSaved,
}: {
  employees: TimesheetEmployee[];
  buildings: BuildingAdmin[];
  /** ACTIVE hour types only — an archived one is refused server-side. */
  hourTypes: HourType[];
  companyId?: number | null;
  initialWeek: IsoWeek;
  onClose: () => void;
  /** The page refreshes its list and closes this. */
  onSaved: (changed: number) => void | Promise<void>;
}) {
  const { t } = useTranslation("common");

  const [employeeIds, setEmployeeIds] = useState<number[]>([]);
  const [buildingIds, setBuildingIds] = useState<number[]>([NO_BUILDING_ID]);
  const [hourTypeIds, setHourTypeIds] = useState<number[]>([]);
  const [week, setWeek] = useState<IsoWeek>(initialWeek);

  const [entriesByEmployee, setEntriesByEmployee] = useState<
    Record<number, TimeEntry[]>
  >({});
  const [weekClosed, setWeekClosed] = useState(false);

  // Escape closes. One effect, and it touches only a listener — no
  // setState in an effect body.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  // The week's existing entries, one read PER selected employee with
  // `allSettled`, so a failure for one person cannot discard anybody
  // else's rows. The request count is bounded by the operator's own
  // selection.
  useEffect(() => {
    if (employeeIds.length === 0) return;
    let cancelled = false;
    Promise.allSettled(
      employeeIds.map((employeeId) =>
        listTimeEntries({
          employee: employeeId,
          iso_year: week.isoYear,
          iso_week: week.isoWeek,
          page_size: 200,
        }).then((page) => [employeeId, page.results] as const),
      ),
    ).then((results) => {
      if (cancelled) return;
      const next: Record<number, TimeEntry[]> = {};
      for (const result of results) {
        if (result.status === "fulfilled") {
          const [employeeId, rows] = result.value;
          next[employeeId] = rows;
        }
      }
      setEntriesByEmployee(next);
    });
    return () => {
      cancelled = true;
    };
  }, [employeeIds, week]);

  // The lock, read INDEPENDENTLY — see the header comment.
  useEffect(() => {
    let cancelled = false;
    fetchWeekStatus({
      iso_year: week.isoYear,
      iso_week: week.isoWeek,
      company: companyId ?? "",
    })
      .then((status) => {
        if (!cancelled) setWeekClosed(status.is_closed);
      })
      .catch(() => {
        if (!cancelled) setWeekClosed(false);
      });
    return () => {
      cancelled = true;
    };
  }, [week, companyId]);

  const buildingOptions = useMemo(
    () => [
      // Offered FIRST: for a cleaner whose hours are not tied to a site
      // it is the only correct answer and should not be hunted for at
      // the bottom of a long list.
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

  /** The blocks the grid renders, DERIVED from the selection and the
   *  employee list — so a selected employee who disappears (company
   *  switch, deactivation) simply stops having rows, with no effect to
   *  resync and no stale name on screen. */
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

  /** The sentinel is translated back to null HERE, so nothing
   *  downstream ever sees a building id of 0. */
  const seedBuildingIds = useMemo(
    () => buildingIds.map((id) => (id === NO_BUILDING_ID ? null : id)),
    [buildingIds],
  );

  return (
    <div
      data-testid="week-entry-modal"
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
          maxWidth: 1180,
          width: "100%",
          padding: 24,
          maxHeight: "92vh",
          overflowY: "auto",
        }}
      >
        <h3 style={{ marginTop: 0, marginBottom: 4 }}>
          {t("week_setup.title")}
        </h3>
        <p className="muted small" style={{ marginTop: 0, marginBottom: 16 }}>
          {t("week_setup.subtitle")}
        </p>

        {/* The four choices, SIDE BY SIDE. */}
        <div className="week-entry-setup-row" data-testid="week-entry-setup">
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

          <div className="field">
            <span className="field-label">
              {t("week_setup.hour_types_label")}
            </span>
            <EntityPicker
              options={hourTypes.map((hourType) => ({
                id: hourType.id,
                label: hourType.name,
              }))}
              selectedIds={hourTypeIds}
              onChange={setHourTypeIds}
              emptyText={t("week_setup.no_hour_types")}
              testIdPrefix="week-setup-hour-types"
            />
          </div>

          <div className="field">
            <span className="field-label">{t("week_setup.week_label")}</span>
            <input
              className="field-input"
              type="week"
              value={formatIsoWeek(week)}
              onChange={(event) => {
                const parsed = parseIsoWeek(event.target.value);
                if (parsed) setWeek(parsed);
              }}
              data-testid="week-setup-week"
            />
            {/* The live row count. Never omitted: "4 employees x 3
                buildings = 12 rows" is the difference between a
                confident confirm and a surprise. */}
            <p
              className="week-setup-summary"
              data-testid="week-setup-summary"
              role="status"
            >
              {t("week_setup.summary", {
                employees: employeeIds.length,
                buildings: buildingIds.length,
                rows:
                  employeeIds.length *
                  buildingIds.length *
                  Math.max(1, hourTypeIds.length),
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
          entriesByEmployee={entriesByEmployee}
          seedBuildingIds={seedBuildingIds}
          seedHourTypeIds={hourTypeIds}
          weekClosed={weekClosed}
          onSaved={onSaved}
          onCancel={onClose}
        />
      </div>
    </div>
  );
}
