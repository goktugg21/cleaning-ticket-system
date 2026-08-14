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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { fetchWeekStatus, listTimeEntries } from "../../api/timesheets";
import type {
  HourType,
  TimeEntry,
  TimesheetEmployee,
} from "../../api/timesheets.types";
import type { BuildingAdmin } from "../../api/types";
import { listHourSources } from "../../api/reports";
import type { HourSourceOption } from "../../api/reports";
import { ChipMultiSelect } from "../ChipMultiSelect";
import { ConfirmDialog } from "../ConfirmDialog";
import type { ConfirmDialogHandle } from "../ConfirmDialog";
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
  // Sprint 177 §7 — the JOB these hours are worked on. Optional: plenty
  // of hours belong to no particular job, and forcing a choice would be
  // worse than the untagged rows this is fixing. Chosen, it becomes a
  // seeded row per job so the source travels with the hours instead of
  // being typed twice (which is to say: never typed at all).
  const [sourceKeys, setSourceKeys] = useState<number[]>([]);
  const [sourceOptions, setSourceOptions] = useState<HourSourceOption[]>([]);
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

  /**
   * Sprint 180 §2 — Escape still closes, but not over unsaved hours.
   *
   * The listener is on `window`, so Escape closed this dialog from
   * anywhere, including with the caret inside a cell. The grid's typed
   * values live in the grid's own state and are thrown away with it: an
   * hour of typing died on one keystroke, silently, with nothing to
   * recover and no way to know it had happened. The same is true of
   * Cancel and of a click on the backdrop.
   *
   * So all three routes go through `requestClose`, which closes
   * immediately when the grid is clean and asks first when it is not.
   * The dirty flag is REPORTED by the grid from its own event handlers
   * (`onDirtyChange`), never derived in an effect here.
   */
  const [dirty, setDirty] = useState(false);
  const discardDialogRef = useRef<ConfirmDialogHandle>(null);

  const requestClose = useCallback(() => {
    if (dirty) {
      discardDialogRef.current?.open();
      return;
    }
    onClose();
  }, [dirty, onClose]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") requestClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [requestClose]);

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

  /** Sprint 177 §7 — load the pickable jobs once.
   *
   *  Non-fatal on failure, like the category options on the extra-work
   *  list: the source is an OPTIONAL refinement, and a picker that could
   *  not load must not stop somebody entering their week. */
  useEffect(() => {
    let cancelled = false;
    listHourSources()
      .then((options) => {
        if (!cancelled) setSourceOptions(options);
      })
      .catch(() => {
        /* non-fatal: hours can still be entered untagged */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /** ChipMultiSelect keys on a NUMBER id, and a source is a (type, id)
   *  PAIR — so the option list is indexed and the index is the id. The
   *  pair is recovered on the way out, never reconstructed from a
   *  parsed string. */
  const sourceChipOptions = useMemo(
    () =>
      sourceOptions.map((option, index) => ({
        id: index,
        label: option.title,
        sublabel: t(`hour_source.${option.source_type}`),
      })),
    [sourceOptions, t],
  );

  const seedSources = useMemo(
    () =>
      sourceKeys
        .map((index) => sourceOptions[index])
        .filter(Boolean)
        .map((option) => ({
          source_type: option.source_type,
          source_id: option.source_id,
        })),
    [sourceKeys, sourceOptions],
  );

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
        <h3 className="section-title" style={{ marginTop: 0, marginBottom: 4 }}>
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

          {/* Sprint 177 §7 — WHICH JOB. Optional by design; left empty
              the grid behaves exactly as it did before this sprint. */}
          {sourceChipOptions.length > 0 && (
            <div className="field">
              <span className="field-label">
                {t("week_setup.sources_label")}
              </span>
              <ChipMultiSelect
                options={sourceChipOptions}
                selectedIds={sourceKeys}
                onChange={setSourceKeys}
                placeholder={t("week_setup.select_sources")}
                removeLabel={(label) =>
                  t("week_setup.remove_source", { name: label })
                }
                emptyText={t("week_setup.no_sources")}
                onOpenChange={onPickerOpenChange}
                testIdPrefix="week-setup-sources"
              />
              <p className="muted small" style={{ marginTop: 4 }}>
                {t("week_setup.sources_hint")}
              </p>
            </div>
          )}

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
            {/* Sprint 179B §3 — the lock, said where the week is chosen.
                The grid has always carried a "this week is closed"
                banner, but the grid returns early with "pick an
                employee first" until somebody is selected, so an
                operator could page to a closed week, choose people and
                buildings, type a whole week and only meet the lock on
                Save. This renders from the moment the dialog opens. */}
            {weekClosed && (
              <p
                className="muted small week-setup-locked"
                role="status"
                data-testid="week-setup-locked"
              >
                {t("week_setup.week_closed_hint")}
              </p>
            )}
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
                  exist as a setup choice.

                  Sprint 179B §3 — and it must multiply by the JOBS.
                  Sprint 177 §7 seeds one row per job (`seedSources` ->
                  `seats` in the grid), so with two jobs picked this
                  line promised two rows and the grid produced four. The
                  count is the one thing on this screen that claims to
                  say what is about to happen, so it says it. */}
              {seedSources.length > 0
                ? t("week_setup.summary_with_jobs", {
                    employees: employeeIds.length,
                    buildings: buildingIds.length,
                    jobs: seedSources.length,
                    rows:
                      employeeIds.length *
                      buildingIds.length *
                      seedSources.length,
                  })
                : t("week_setup.summary", {
                    employees: employeeIds.length,
                    buildings: buildingIds.length,
                    rows: employeeIds.length * buildingIds.length,
                  })}
            </p>
            {/* Sprint 179B §3 — the reconciliation rule, said once and
                where the count is. A combination that already has hours
                this week is NOT given a second, empty row (the grid's
                `put()` keeps the first row for a key), and an operator
                who expected the promised number of blank rows and got
                filled ones has no other way to learn why. */}
            <p className="muted small week-setup-summary-hint">
              {t("week_setup.summary_hint")}
            </p>
          </div>
        </div>

        {/* Sprint 179B §2 — `sourceOptions` gives the grid's Job column
            its titles. The list is already loaded here for the picker,
            so the grid is handed it rather than fetching it again; and
            `showSource` is on because these rows CAN belong to a job. */}
        <HoursWeekGrid
          /* Sprint 180 §2 — KEYED BY THE WEEK, which is CLAUDE.md's own
             rule for prop-derived state. The grid's typed cells are
             keyed by DATE and Save posts exactly one iso_year/iso_week,
             so hours typed for week 32 went invisible and unsaveable the
             moment the operator paged to week 33 — they sat in state
             until the dialog closed. Remounting makes the screen and the
             pending write the same thing, and the grid's own head says
             so before it happens rather than after. */
          key={`${week.isoYear}-W${week.isoWeek}`}
          week={week}
          employees={gridEmployees}
          companyId={companyId}
          hourTypes={hourTypes}
          buildings={buildings}
          entriesByEmployee={entriesByEmployee}
          seedBuildingIds={seedBuildingIds}
          seedSources={seedSources}
          sourceOptions={sourceOptions}
          showSource
          weekClosed={weekClosed}
          onSaved={onSaved}
          onCancel={requestClose}
          onDirtyChange={setDirty}
        />
        {/* Sprint 170 §8 — see `usePickerReserve`. */}
        <div
          ref={spacerRef}
          style={{ flex: "0 0 auto", height: reserve }}
          aria-hidden="true"
          data-testid="picker-reserve-spacer"
        />

        {/* Sprint 180 §2 — the guard on Escape and Cancel.
            Rendered UNCONDITIONALLY and driven entirely through the ref,
            which is CLAUDE.md's rule for a native `<dialog>`: wrapping
            it in `{dirty && …}` mounts an invisible dialog whose trigger
            looks dead, and unmounting one while it is open can leave the
            whole page inert. */}
        <ConfirmDialog
          ref={discardDialogRef}
          title={t("week_setup.discard_title")}
          body={t("week_setup.discard_body")}
          confirmLabel={t("week_setup.discard_confirm")}
          cancelLabel={t("week_setup.discard_cancel")}
          destructive
          onConfirm={() => {
            discardDialogRef.current?.close();
            onClose();
          }}
        />
      </div>
    </div>
  );
}
