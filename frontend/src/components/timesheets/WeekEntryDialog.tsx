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
import { ChipMultiSelect } from "../ChipMultiSelect";
import { usePickerReserve } from "../../lib/usePickerReserve";
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
  // Sprint 165 §2 — nothing is chosen until the operator chooses. This
  // opened with NO_BUILDING already ticked, which made it easy to save
  // a week of hours against no location without noticing. "No building"
  // stays AVAILABLE in the list; it is simply not picked for them.
  const [buildingIds, setBuildingIds] = useState<number[]>([]);
  const [week, setWeek] = useState<IsoWeek>(initialWeek);

  const [entriesByEmployee, setEntriesByEmployee] = useState<
    Record<number, TimeEntry[]>
  >({});
  const [weekClosed, setWeekClosed] = useState(false);

  // Sprint 169 §1 — the modal grows to CONTAIN an open picker list,
  // and shrinks back when it closes. See `usePickerReserve` for why a
  // portalled list cannot be contained by CSS alone.
  const { modalRef, spacerRef, reserve, onPickerOpenChange } =
    usePickerReserve();

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
        // Sprint 167 §1 — anchored to the TOP, not centred. A centred
        // dialog that grows moves its own header upward, so every row
        // the operator adds slides the controls out from under their
        // cursor. Growing downward from a fixed top edge is the
        // behaviour asked for, and centring cannot give it.
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
          // Sprint 167 §1 — sized to its CONTENT.
          //
          // Sprint 166 was told to make this "large enough to work in"
          // and gave it a min-height, which is how an empty dialog
          // became a vast white box holding one line of text. That was
          // my overcorrection and the instruction behind it was wrong:
          // a dialog should be as tall as what is in it.
          //
          // So there is NO height floor. Empty it is three pickers and
          // a hint and stands about that tall; it grows as rows appear;
          // at 85vh it stops growing and the GRID scrolls inside it
          // (`.hours-week-table-wrap`, which owns the wide/tall thing).
          // The width keeps Sprint 166's rule, which was the half of
          // that change that was right.
          width: "min(96vw, 1180px)",
          maxWidth: 1180,
          padding: 24,
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
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
              testIdPrefix="week-setup-employees"
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
              testIdPrefix="week-setup-buildings"
            />
          </div>

          {/* Sprint 162 §1c — the hour-type step is GONE. The grid now
              carries `+ Add type` per block, which is the only way a
              type is chosen, so asking for types up front was asking
              the same question twice and pre-committing the answer.
              Removing it was unsafe before that control existed and is
              safe now, which is why it waited. */}

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
              {/* One BLOCK per (employee, building) now, each opening
                  with a single default hour-type row. The old count
                  multiplied by the chosen types, which no longer
                  exist as a setup choice. */}
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
          entriesByEmployee={entriesByEmployee}
          seedBuildingIds={seedBuildingIds}
          weekClosed={weekClosed}
          onSaved={onSaved}
          onCancel={onClose}
        />
        {/* Sprint 170 §8 — see `usePickerReserve`. */}
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
