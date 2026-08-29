/**
 * Sprint 159 §1 — enter a week. ONE modal, opened by the one primary
 * button on the Hours page.
 *
 * ## W-HOURS4 Task 1 — the reference system's flow, with two refinements
 *
 * The owner signed off a mock: the dialog is the reference system's
 * entry flow — pick **Employees** (chips), pick **Buildings** (chips),
 * pick the **week** — with two things the reference does not do.
 *
 * **1. Rows are the VALID (person, building) pairs only.** Building
 * grants are the hard wall. For every selected person the server is
 * asked what it already knows (`GET /api/reports/week-assignments/`,
 * keyed by THE DIALOG'S week): the buildings they may enter and the
 * jobs they are on that week. A pair the grants do not allow never
 * materialises as a row; one quiet line counts and names the skipped
 * pairs ("1 skipped: Gökhan × B3 — no access"). "No building" is a
 * legitimate seat (hours not tied to a site) and is valid for everyone.
 *
 * **2. A job is linked PER ROW, optionally.** Under the person's name
 * on each row sits "+ link a job (optional)" (`RowJobPicker`): "This
 * week" lists that person's real planned jobs in THAT building for the
 * selected week; "No job — general hours" is the default; "Search other
 * work…" finds any open job in a building the person may enter — the
 * reference system's freedom, helping on an unassigned job is
 * enterable. A chosen job is a small removable tag on the row; an
 * untagged row saves as General, exactly as before.
 *
 * The top-level job picker and the "Add a row" bar of hours2 Part 3/4
 * are gone: the pairs ARE the rows, and the job is a property of a
 * row, not a third dimension multiplied into the grid.
 *
 * ## Terminal work
 *
 * "This week" shows what `/reports/week-assignments/` proposes for the
 * selected week. That endpoint offers OPEN work only (it excludes
 * closed / cancelled / rejected tickets for every week), so in the
 * current week a finished job is not offered — as ruled. In a PAST
 * week the ruling wants since-closed work offered too (backfilling
 * truth is legitimate); that is a one-predicate change in
 * `backend/reports/week_assignments.py::_open_tickets`, which this
 * dialog does not own. Search stays free and saving stays allowed: the
 * lock that matters is the WEEK lock.
 *
 * ## The fill row, the hour-type rows and the week save are unchanged
 *
 * They belong to `HoursWeekGrid`, which this dialog hands the pairs to
 * as per-person seeds (`seedRowsByEmployee`). Reconciliation is as it
 * was: a pair that already has hours this week IS the saved row, not a
 * blank twin of it.
 *
 * ## Three independent reads, deliberately NOT one Promise.all
 *
 * Sprint 155 shipped the entries and the lock combined and it was a
 * real bug, caught by measuring the built page: `weeks/status/` 400s
 * for a SUPER_ADMIN who has not disambiguated a company, which rejected
 * the combined promise and threw away the ENTRIES. Split, a failure in
 * the lock read can never discard the entries, and an unknown lock
 * state defaults to OPEN — the SERVER refuses a write into a closed
 * week regardless. The assignment read is the third independent read:
 * if it fails, the grid still shows the week's saved rows, no pair
 * rows are proposed (the wall cannot be checked), and the dialog says
 * so.
 *
 * A NON-native overlay, conditionally mounted, like every other editing
 * modal in this codebase. CLAUDE.md's render-unconditionally rule is
 * about the native `<dialog>` element; `ConfirmDialog` stays native and
 * ref-driven where it is used.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../api/client";
import {
  fetchWeekStatus,
  fillWeekFromContracts,
  listTimeEntries,
  listWeekAssignments,
} from "../../api/timesheets";
import type {
  WeekAssignmentPerson,
  WeekAssignments,
} from "../../api/timesheets";
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
import type { GridJobPicker, GridSeedRow } from "./HoursWeekGrid";

/** The picker's sentinel for "these hours are not tied to a location".
 *  `TimeEntry.building` is nullable BY DESIGN and stays that way — this
 *  is a UI affordance for choosing null, mapped back to null before it
 *  reaches the grid. Zero is safe because every real building id is a
 *  positive auto-increment pk. Still exported: the contract-hours bulk
 *  dialog shares it. */
export const NO_BUILDING_ID = 0;

/** Stable empty seeds so the grid's memo does not recompute per render. */
const NO_SEED_BUILDINGS: (number | null)[] = [];

/** One pair the wall refused. */
interface SkippedPair {
  employee: number;
  building: number;
}

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
  const [buildingIds, setBuildingIds] = useState<number[]>([]);
  const [week, setWeek] = useState<IsoWeek>(initialWeek);

  const [entriesByEmployee, setEntriesByEmployee] = useState<
    Record<number, TimeEntry[]>
  >({});
  const [weekClosed, setWeekClosed] = useState(false);
  /** Which (week, company) the lock answer belongs to. The chip reads
   *  "Loading…" until this matches the week on screen — the Hours
   *  page's own pattern, and the only way to re-enter loading without
   *  a synchronous setState in an effect body. */
  const [lockKey, setLockKey] = useState<string | null>(null);

  /** Sprint 177 §7 / 179B — the titles the grid's job tags read. */
  const [sourceOptions, setSourceOptions] = useState<HourSourceOption[]>([]);

  /** hours2 Part 3 — the server's answer per selected person: the
   *  buildings they may enter (the wall) and the jobs they are on THIS
   *  week (the "This week" group of every row's job picker). */
  const [assignments, setAssignments] = useState<WeekAssignments | null>(null);
  const [assignmentsError, setAssignmentsError] = useState("");

  // Sprint 169 §1 — the modal grows to CONTAIN an open picker list,
  // and shrinks back when it closes. See `usePickerReserve` for why a
  // portalled list cannot be contained by CSS alone.
  const { modalRef, spacerRef, reserve, onPickerOpenChange } =
    usePickerReserve();

  /**
   * Sprint 180 §2 — Escape still closes, but not over unsaved hours.
   *
   * All three close routes (Escape, Cancel, backdrop) go through
   * `requestClose`, which closes immediately when the grid is clean
   * and asks first when it is not. The dirty flag is REPORTED by the
   * grid from its own event handlers (`onDirtyChange`), never derived
   * in an effect here.
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
  /** W-FIX1 D1 (audit F6) — which (week, company, people) setups this
   *  dialog has already asked the server to fill. The fill is a WRITE;
   *  it used to fire on every picker change and every week glanced at.
   *  It now fires once per confirmed setup — both pickers non-empty —
   *  and never twice for the same one while this dialog is open. */
  const filledSetups = useRef(new Set<string>());
  useEffect(() => {
    if (employeeIds.length === 0) return;
    let cancelled = false;
    /* W10 — fill this week from the standing agreements BEFORE reading
       it, so a contracted week is never blank and nobody has to press
       anything weekly. Idempotent server-side (and serialised there
       since W-FIX1 D1), and it never touches a week that already has
       rows, so re-opening a week the operator has edited changes
       nothing. A failure is not fatal: the sheet then simply shows what
       is already there. */
    const setupKey = `${week.isoYear}-W${week.isoWeek}|${companyId ?? ""}|${[
      ...employeeIds,
    ]
      .sort((a, b) => a - b)
      .join(",")}`;
    const shouldFill =
      buildingIds.length > 0 && !filledSetups.current.has(setupKey);
    if (shouldFill) filledSetups.current.add(setupKey);
    const ready = shouldFill
      ? fillWeekFromContracts({
          iso_year: week.isoYear,
          iso_week: week.isoWeek,
          company: companyId ?? "",
        }).catch(() => undefined)
      : Promise.resolve(undefined);
    ready.then(() =>
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
      }),
    );
    return () => {
      cancelled = true;
    };
  }, [employeeIds, buildingIds, week, companyId]);

  // The lock, read INDEPENDENTLY — see the header comment.
  const currentLockKey = `${week.isoYear}-${week.isoWeek}|${companyId ?? ""}`;
  useEffect(() => {
    let cancelled = false;
    fetchWeekStatus({
      iso_year: week.isoYear,
      iso_week: week.isoWeek,
      company: companyId ?? "",
    })
      .then((status) => {
        if (cancelled) return;
        setWeekClosed(status.is_closed);
        setLockKey(currentLockKey);
      })
      .catch(() => {
        if (cancelled) return;
        setWeekClosed(false);
        setLockKey(currentLockKey);
      });
    return () => {
      cancelled = true;
    };
  }, [week, companyId, currentLockKey]);
  const lockLoading = lockKey !== currentLockKey;

  /** Sprint 177 §7 — load the pickable jobs once, for their TITLES.
   *
   *  A saved row's tag may point at work the per-person proposal does
   *  not list (a ticket that has since closed). Non-fatal: a title that
   *  cannot be resolved falls back to "Ticket #41". */
  useEffect(() => {
    let cancelled = false;
    listHourSources()
      .then((options) => {
        if (!cancelled) setSourceOptions(options);
      })
      .catch(() => {
        /* non-fatal: rows still render with the fallback label */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /** hours2 Part 3 — the wall and this week's jobs for the selected
   *  people. Re-read when the people or the week change, and KEYED BY
   *  THE DIALOG'S WEEK: paging the week input to W34 asks for W34's
   *  jobs, not today's. A failure keeps the grid on its saved rows and
   *  says so; it never throws away what the entries read returned. */
  useEffect(() => {
    if (employeeIds.length === 0) return;
    let cancelled = false;
    listWeekAssignments({
      iso_year: week.isoYear,
      iso_week: week.isoWeek,
      company: companyId ?? "",
      employees: employeeIds,
    })
      .then((data) => {
        if (cancelled) return;
        setAssignments(data);
        setAssignmentsError("");
      })
      .catch((err) => {
        if (!cancelled) setAssignmentsError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [employeeIds, week, companyId]);

  /** The answer, keyed by person — and only when it is the answer for
   *  THIS week, so paging to another week never seeds last week's jobs
   *  while the new read is in flight. */
  const personById = useMemo(() => {
    const map = new Map<number, WeekAssignmentPerson>();
    if (
      assignments &&
      assignments.iso_year === week.isoYear &&
      assignments.iso_week === week.isoWeek
    ) {
      for (const person of assignments.employees) {
        map.set(person.employee, person);
      }
    }
    return map;
  }, [assignments, week]);
  /** True once every selected person has an answer for this week. A
   *  pair row never materialises before the wall has been read. */
  const assignmentsReady = employeeIds.every((id) => personById.has(id));

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
  const employeeName = (id: number) =>
    gridEmployees.find((employee) => employee.id === id)?.name ?? String(id);

  const buildingLabel = (id: number | null) =>
    id === null || id === NO_BUILDING_ID
      ? t("hours_week_grid.no_building")
      : (buildings.find((building) => building.id === id)?.name ?? String(id));

  /**
   * Task 1b — the rows: every VALID (person, building) pair, untagged.
   *
   * Valid means the building is in the person's grants for this
   * company (the `building_ids` the assignments read returned), or the
   * seat is "No building", which needs no grant. Anything else is
   * counted and named, never seeded. Nothing is seeded at all until
   * the wall has been read for every selected person.
   */
  const { seedRowsByEmployee, skippedPairs, rowCount } = useMemo(() => {
    const out: Record<number, GridSeedRow[]> = {};
    const skipped: SkippedPair[] = [];
    let count = 0;
    if (assignmentsReady) {
      for (const employeeId of employeeIds) {
        const person = personById.get(employeeId);
        const rows: GridSeedRow[] = [];
        for (const buildingId of buildingIds) {
          if (buildingId === NO_BUILDING_ID) {
            rows.push({ building: null, source_type: "", source_id: null });
            count += 1;
          } else if (person && person.building_ids.includes(buildingId)) {
            rows.push({
              building: buildingId,
              source_type: "",
              source_id: null,
            });
            count += 1;
          } else {
            skipped.push({ employee: employeeId, building: buildingId });
          }
        }
        out[employeeId] = rows;
      }
    }
    return { seedRowsByEmployee: out, skippedPairs: skipped, rowCount: count };
  }, [assignmentsReady, employeeIds, buildingIds, personById]);

  /** Titles for the job tags: the caller-wide picker list plus every
   *  job the proposal named, so a proposed row is never "Ticket #41". */
  const jobTitleOptions = useMemo(() => {
    const seen = new Set(
      sourceOptions.map((option) => `${option.source_type}:${option.source_id ?? ""}`),
    );
    const extra: HourSourceOption[] = [];
    for (const person of personById.values()) {
      for (const job of person.jobs) {
        const key = `${job.source_type}:${job.source_id}`;
        if (seen.has(key)) continue;
        seen.add(key);
        extra.push(job);
      }
    }
    return extra.length > 0 ? [...sourceOptions, ...extra] : sourceOptions;
  }, [sourceOptions, personById]);

  /**
   * Task 1c — what every row's job picker offers.
   *
   * "This week" is the person's proposal for THIS building in THE
   * SELECTED WEEK, straight from the week-keyed read above. Search is
   * free: the person's own jobs (any week) that match, plus what
   * `/reports/hour-sources/` finds for the query — both narrowed to
   * TICKET records in buildings the person may enter, each job once.
   * Extra-work records are not offered: pre-spawn nothing can have
   * hours, post-spawn the hours belong on the ticket the work became.
   */
  const jobPicker = useMemo<GridJobPicker>(
    () => ({
      thisWeek: (employeeId, buildingId) => {
        if (buildingId === null) return [];
        return (personById.get(employeeId)?.assignments ?? []).filter(
          (job) => job.building === buildingId,
        );
      },
      search: async (employeeId, _buildingId, query) => {
        // W-HOURS5 Task 7 — candidates only; the picker applies its own
        // code-and-title matcher, so "TCK-373" (which the server's
        // title search cannot find) still meets its job among the
        // person's own. The server call narrows the wider pool by
        // title; the person's jobs list is handed over whole.
        const person = personById.get(employeeId);
        const allowed = new Set(person?.building_ids ?? []);
        const seen = new Set<number>();
        const out: HourSourceOption[] = [];
        const add = (job: HourSourceOption) => {
          if (
            job.source_type !== "TICKET" ||
            job.source_id === null ||
            job.building === null ||
            !allowed.has(job.building) ||
            seen.has(job.source_id)
          ) {
            return;
          }
          seen.add(job.source_id);
          out.push(job);
        };
        for (const job of person?.jobs ?? []) add(job);
        for (const job of await listHourSources(query.trim())) add(job);
        return out;
      },
      onOpenChange: onPickerOpenChange,
    }),
    [personById, onPickerOpenChange],
  );

  const skippedText = skippedPairs
    .map(
      (pair) =>
        `${employeeName(pair.employee)} × ${buildingLabel(pair.building)}`,
    )
    .join(", ");

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
          // Sprint 167 §1 — sized to its CONTENT. No height floor: empty
          // it is three pickers and a hint; it grows as rows appear; at
          // 85vh the GRID scrolls inside it.
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

        {/* The three choices, SIDE BY SIDE: who, where, and which week. */}
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
              options={[
                // Offered FIRST: for hours not tied to a site it is the
                // only correct answer, and it needs no grant.
                {
                  id: NO_BUILDING_ID,
                  label: t("hours_week_grid.no_building"),
                  sublabel: t("week_setup.no_building_hint"),
                },
                ...buildings.map((building) => ({
                  id: building.id,
                  label: building.name,
                })),
              ]}
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

          <div className="field">
            <span className="field-label">{t("week_setup.week_label")}</span>
            <div className="week-setup-week-line">
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
              {/* Part 4b — the SAME chip the Hours page's week bar
                  wears, so a past week reads as open-until-locked. */}
              <span
                className={
                  weekClosed ? "badge badge-closed" : "badge badge-approved"
                }
                data-testid="week-setup-lock"
                data-closed={weekClosed ? "true" : "false"}
              >
                {lockLoading ? (
                  <span
                    className="skeleton-line"
                    style={{ width: 54, height: 10, display: "inline-block" }}
                    aria-hidden="true"
                  />
                ) : weekClosed ? (
                  t("weeks.status_closed")
                ) : (
                  t("weeks.status_open")
                )}
              </span>
            </div>
            {/* Sprint 179B §3 — the lock, said where the week is chosen,
                from the moment the dialog opens. */}
            {weekClosed && (
              <p
                className="muted small week-setup-locked"
                role="status"
                data-testid="week-setup-locked"
              >
                {t("week_setup.week_closed_hint")}
              </p>
            )}
            {/* The live row count: the pairs about to be rows, said
                before they are — the one line on this screen that
                claims to say what is about to happen. */}
            <p
              className="week-setup-summary"
              data-testid="week-setup-summary"
              role="status"
              title={t("week_setup.summary_hint")}
            >
              {employeeIds.length === 0 || buildingIds.length === 0
                ? t("week_setup.pairs_none")
                : !assignmentsReady
                  ? t("week_setup.pairs_pending")
                  : t("week_setup.pairs_summary", {
                      count: rowCount,
                      employees: employeeIds.length,
                      buildings: buildingIds.length,
                    })}
            </p>
            {/* Task 1b — the quiet count line that names the pairs the
                wall refused. Absent when nothing was skipped. */}
            {skippedPairs.length > 0 && (
              <p
                className="muted small week-setup-summary-hint"
                role="status"
                data-testid="week-setup-skipped"
              >
                {t("week_setup.skipped_pairs", {
                  count: skippedPairs.length,
                  pairs: skippedText,
                })}
              </p>
            )}
            {/* Sprint 179B §3 — the reconciliation rule, said once and
                where the count is. */}
          </div>
        </div>

        {assignmentsError && (
          <div
            className="alert-error"
            role="alert"
            style={{ marginBottom: 12 }}
            data-testid="week-setup-assignments-error"
          >
            {t("week_setup.assignments_error", { detail: assignmentsError })}
          </div>
        )}

        {/* `jobTitleOptions` gives the job tags their titles; `showSource`
            is on because these rows CAN belong to a job, and `jobPicker`
            puts the choice on the row itself. The pairs travel as
            `seedRowsByEmployee`; the shared seeds are empty, so nothing
            is multiplied. */}
        <HoursWeekGrid
          /* Sprint 180 §2 — KEYED BY THE WEEK, CLAUDE.md's own rule for
             prop-derived state: the grid's typed cells are keyed by DATE
             and Save posts one iso week, so remounting per week makes
             the screen and the pending write the same thing. */
          key={`${week.isoYear}-W${week.isoWeek}`}
          week={week}
          employees={gridEmployees}
          companyId={companyId}
          hourTypes={hourTypes}
          buildings={buildings}
          entriesByEmployee={entriesByEmployee}
          seedBuildingIds={NO_SEED_BUILDINGS}
          seedRowsByEmployee={seedRowsByEmployee}
          sourceOptions={jobTitleOptions}
          showSource
          jobPicker={jobPicker}
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
            which is CLAUDE.md's rule for a native `<dialog>`. */}
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
