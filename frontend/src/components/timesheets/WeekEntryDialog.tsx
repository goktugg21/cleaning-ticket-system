/**
 * Sprint 159 §1 — enter a week. ONE modal, opened by the one primary
 * button on the Hours page.
 *
 * ## hours2 Part 3 — the grid stops multiplying the impossible
 *
 * Until this wave the dialog built its rows as a PRODUCT: every selected
 * employee x every selected building x every selected job. A cleaner
 * was offered rows in buildings they cannot enter and on jobs they are
 * not on, and the operator had to know which of the twelve rows were
 * real. The three pickers that produced that product (buildings, jobs,
 * and the "N x M = rows" arithmetic under them) are gone.
 *
 * Now picking EMPLOYEES proposes rows. For each person the server is
 * asked what it already knows (`GET /api/reports/week-assignments/`):
 * the jobs they are on this week — their ticket slots, and the days
 * the plan put them on via the spawned ticket — and the buildings they
 * may enter. One row per (person, job) lands in the grid with the job's
 * building prefilled and the hours empty. Reconciliation is unchanged:
 * a proposal that already has hours this week IS the saved row.
 *
 * Exceptions stay possible through **Add a row**: one bar, one person
 * at a time, whose building and job pickers are filtered to THAT
 * person's grants and jobs. A building somebody cannot enter and a job
 * they are not on are offered nowhere — not in the proposal, not in
 * the bar.
 *
 * ## Part 4a — the job picker's two groups
 *
 * The Add-row job picker is a native `<select>` with two labelled
 * groups: **Jobs** (real ticket records this person is on) and
 * **General** (the Contract / Other buckets, which name a kind of work
 * rather than a record). The paragraph that used to explain that
 * difference is gone — the grouping IS the explanation. Extra-work
 * records are not offered: pre-spawn nothing can have hours, and
 * post-spawn the hours belong on the ticket the work became.
 *
 * ## Part 4b — the lock, said where the week is
 *
 * The week input carries the same Open / Closed chip the Hours page's
 * week bar wears (`.badge-approved` / `.badge-closed`, the
 * `weeks.status_*` strings), so a past week reads as allowed-until-
 * locked rather than forbidden. The sentence under it, for a closed
 * week, still says what to do about it.
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
 * write into a closed week regardless. The assignment read is a third
 * independent read for the same reason: if it fails, the grid still
 * shows the week's saved rows and says the proposal could not be made.
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
import { decodeSource, encodeSource, hourSourceLabel } from "../../lib/hourSource";
import { formatIsoWeek, parseIsoWeek } from "../../lib/isoWeek";
import type { IsoWeek } from "../../lib/isoWeek";
import { HoursWeekGrid } from "./HoursWeekGrid";
import type { GridSeedRow } from "./HoursWeekGrid";

/** The picker's sentinel for "these hours are not tied to a location".
 *  `TimeEntry.building` is nullable BY DESIGN and stays that way — this
 *  is a UI affordance for choosing null, mapped back to null before it
 *  reaches the grid. Zero is safe because every real building id is a
 *  positive auto-increment pk. Still exported: the contract-hours bulk
 *  dialog shares it. */
export const NO_BUILDING_ID = 0;

/** The Add-row building select's value for "no building". A string
 *  sentinel because the select's value is a string and `""` already
 *  means "not chosen yet". */
const ADD_NO_BUILDING = "none";

/** The two type-only buckets the General group offers. */
const GENERAL_SOURCES = ["CONTRACT", "OTHER"] as const;

/** Stable empty seeds so the grid's memo does not recompute per render. */
const NO_SEED_BUILDINGS: (number | null)[] = [];

/** A manually added block: what the grid seeds plus what the chip says. */
interface ManualSeed extends GridSeedRow {
  label: string;
}

function seedKey(seed: GridSeedRow): string {
  return `${seed.building ?? ""}:${seed.source_type}:${seed.source_id ?? ""}`;
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

  /** Sprint 177 §7 / 179B — the titles the grid's Job column reads.
   *  Labels only now; the picking happens per person below. */
  const [sourceOptions, setSourceOptions] = useState<HourSourceOption[]>([]);

  /** hours2 Part 3 — the server's answer per selected person. */
  const [assignments, setAssignments] = useState<WeekAssignments | null>(null);
  const [assignmentsError, setAssignmentsError] = useState("");

  /** The Add-row bar. */
  const [addPersonChoice, setAddPersonChoice] = useState<number | "">("");
  const [addBuilding, setAddBuilding] = useState("");
  const [addJob, setAddJob] = useState("");
  const [addError, setAddError] = useState("");
  const [manualSeeds, setManualSeeds] = useState<Record<number, ManualSeed[]>>(
    {},
  );

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
  useEffect(() => {
    if (employeeIds.length === 0) return;
    let cancelled = false;
    /* W10 — fill this week from the standing agreements BEFORE reading
       it, so a contracted week is never blank and nobody has to press
       anything weekly. Idempotent server-side, and it never touches a
       week that already has rows, so re-opening a week the operator has
       edited changes nothing. A failure is not fatal: the sheet then
       simply shows what is already there. */
    const ready = fillWeekFromContracts({
      iso_year: week.isoYear,
      iso_week: week.isoWeek,
      company: companyId ?? "",
    }).catch(() => undefined);
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
  }, [employeeIds, week, companyId]);

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
   *  The Job column names rows that already have hours this week, and
   *  those may point at work the per-person proposal does not list (a
   *  ticket that has since closed). Non-fatal: a title that cannot be
   *  resolved falls back to "Ticket #41". */
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

  /** hours2 Part 3 — what may be PROPOSED for the selected people this
   *  week. Re-read when the people or the week change. A failure keeps
   *  the grid on its saved rows and says so; it never throws away what
   *  the entries read returned. */
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

  /** The proposal per person: their assignments this week, then the
   *  rows the operator added by hand. */
  const seedRowsByEmployee = useMemo(() => {
    const out: Record<number, GridSeedRow[]> = {};
    for (const id of employeeIds) {
      const rows: GridSeedRow[] = (personById.get(id)?.assignments ?? []).map(
        (job) => ({
          building: job.building,
          source_type: job.source_type,
          source_id: job.source_id,
        }),
      );
      for (const manual of manualSeeds[id] ?? []) {
        rows.push({
          building: manual.building,
          source_type: manual.source_type,
          source_id: manual.source_id,
        });
      }
      out[id] = rows;
    }
    return out;
  }, [employeeIds, personById, manualSeeds]);

  const proposedCount = employeeIds.reduce(
    (sum, id) => sum + (personById.get(id)?.assignments.length ?? 0),
    0,
  );

  /** People with nothing proposed and nothing saved this week: named,
   *  so the operator knows the empty grid is an answer, not a failure. */
  const idleNames = assignmentsReady
    ? employeeIds
        .filter(
          (id) =>
            (personById.get(id)?.assignments.length ?? 0) === 0 &&
            (entriesByEmployee[id]?.length ?? 0) === 0 &&
            (manualSeeds[id]?.length ?? 0) === 0,
        )
        .map(employeeName)
    : [];

  /** Titles for the Job column: the caller-wide picker list plus every
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

  // ---- the Add-row bar ---------------------------------------------
  //
  // The person is DERIVED from the choice and the selection: a chosen
  // person who is then deselected falls back to the first selected one,
  // with no effect to correct the state.
  const addPerson: number | "" =
    addPersonChoice !== "" && employeeIds.includes(addPersonChoice)
      ? addPersonChoice
      : employeeIds.length > 0
        ? employeeIds[0]
        : "";
  const addPersonRow = addPerson === "" ? null : (personById.get(addPerson) ?? null);
  const addBuildingOptions = useMemo(
    () =>
      addPersonRow
        ? buildings.filter((building) =>
            addPersonRow.building_ids.includes(building.id),
          )
        : [],
    [buildings, addPersonRow],
  );
  const addJobOptions = addPersonRow?.jobs ?? [];

  const buildingLabel = (id: number | null) =>
    id === null
      ? t("hours_week_grid.no_building")
      : (buildings.find((building) => building.id === id)?.name ?? String(id));

  function addRow() {
    if (addPerson === "" || addBuilding === "" || addJob === "") return;
    const building =
      addBuilding === ADD_NO_BUILDING ? null : Number(addBuilding);
    const source = decodeSource(addJob);
    const seed: GridSeedRow = {
      building,
      source_type: source.source_type,
      source_id: source.source_id,
    };
    const key = seedKey(seed);
    const alreadySeeded = (seedRowsByEmployee[addPerson] ?? []).some(
      (row) => seedKey(row) === key,
    );
    const alreadySaved = (entriesByEmployee[addPerson] ?? []).some(
      (entry) =>
        seedKey({
          building: entry.building ?? null,
          source_type: entry.source_type || "",
          source_id: entry.source_id ?? null,
        }) === key,
    );
    if (alreadySeeded || alreadySaved) {
      setAddError(t("week_setup.add_row_exists"));
      return;
    }
    setAddError("");
    const label = [
      employeeName(addPerson),
      buildingLabel(building),
      hourSourceLabel(
        source.source_type,
        source.source_id,
        jobTitleOptions,
        t,
        t("hours_week_grid.no_source"),
      ),
    ].join(" · ");
    setManualSeeds((current) => ({
      ...current,
      [addPerson]: [...(current[addPerson] ?? []), { ...seed, label }],
    }));
    setAddJob("");
  }

  function removeManual(personId: number, key: string) {
    setManualSeeds((current) => ({
      ...current,
      [personId]: (current[personId] ?? []).filter(
        (seed) => seedKey(seed) !== key,
      ),
    }));
  }

  const manualList = employeeIds.flatMap((id) =>
    (manualSeeds[id] ?? []).map((seed) => ({ personId: id, seed })),
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
          // Sprint 167 §1 — sized to its CONTENT. No height floor: empty
          // it is two pickers and a hint; it grows as rows appear; at
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

        {/* The two choices, SIDE BY SIDE: who, and which week. */}
        <div
          className="week-entry-setup-row week-entry-setup-row--two"
          data-testid="week-entry-setup"
        >
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
                {lockLoading
                  ? t("weeks.status_loading")
                  : weekClosed
                    ? t("weeks.status_closed")
                    : t("weeks.status_open")}
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
            {/* The live row count. What is about to be PROPOSED, said
                before it is — the one line on this screen that claims to
                say what is about to happen. */}
            <p
              className="week-setup-summary"
              data-testid="week-setup-summary"
              role="status"
            >
              {employeeIds.length === 0
                ? t("week_setup.proposed_none")
                : t("week_setup.proposed_summary", {
                    rows: proposedCount,
                    employees: employeeIds.length,
                    count: proposedCount,
                  })}
            </p>
            {/* Sprint 179B §3 — the reconciliation rule, said once and
                where the count is. */}
            <p className="muted small week-setup-summary-hint">
              {t("week_setup.summary_hint")}
            </p>
          </div>
        </div>

        {assignmentsError && (
          <div
            className="alert-error"
            role="alert"
            style={{ marginBottom: 12 }}
            data-testid="week-setup-assignments-error"
          >
            {t("week_setup.assignments_error")} {assignmentsError}
          </div>
        )}

        {idleNames.length > 0 && (
          <p
            className="muted small"
            style={{ marginTop: 0, marginBottom: 12 }}
            data-testid="week-setup-idle"
          >
            {t("week_setup.no_work_for", { names: idleNames.join(", ") })}
          </p>
        )}

        {/* Add a row — the exception door. One person at a time, and
            both pickers are filtered to THAT person: the buildings they
            may enter, the jobs they are on. */}
        {employeeIds.length > 0 && (
          <div className="week-entry-addrow" data-testid="week-setup-addrow">
            <span className="week-entry-addrow-title">
              {t("week_setup.add_row_title")}
            </span>
            <div className="field">
              <label className="field-label" htmlFor="week-setup-add-person">
                {t("week_setup.add_row_person")}
              </label>
              <select
                id="week-setup-add-person"
                className="field-input"
                value={addPerson}
                onChange={(event) => {
                  setAddPersonChoice(
                    event.target.value === "" ? "" : Number(event.target.value),
                  );
                  setAddBuilding("");
                  setAddJob("");
                  setAddError("");
                }}
                data-testid="week-setup-add-person"
              >
                {gridEmployees.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="week-setup-add-building">
                {t("week_setup.add_row_building")}
              </label>
              <select
                id="week-setup-add-building"
                className="field-input"
                value={addBuilding}
                onChange={(event) => {
                  setAddBuilding(event.target.value);
                  setAddError("");
                }}
                disabled={addPersonRow === null}
                data-testid="week-setup-add-building"
              >
                <option value="">{t("week_setup.add_row_pick")}</option>
                {/* Offered FIRST: for hours not tied to a site it is the
                    only correct answer. */}
                <option value={ADD_NO_BUILDING}>
                  {t("hours_week_grid.no_building")}
                </option>
                {addBuildingOptions.map((building) => (
                  <option key={building.id} value={building.id}>
                    {building.name}
                  </option>
                ))}
              </select>
              {addPersonRow !== null && addBuildingOptions.length === 0 && (
                <p className="muted small" style={{ marginTop: 4 }}>
                  {t("week_setup.add_row_no_buildings", {
                    name: addPerson === "" ? "" : employeeName(addPerson),
                  })}
                </p>
              )}
            </div>
            <div className="field">
              <label className="field-label" htmlFor="week-setup-add-job">
                {t("week_setup.add_row_job")}
              </label>
              {/* Part 4a — two labelled groups. The grouping is the
                  explanation; there is no paragraph under it. */}
              <select
                id="week-setup-add-job"
                className="field-input"
                value={addJob}
                onChange={(event) => {
                  setAddJob(event.target.value);
                  setAddError("");
                }}
                disabled={addPersonRow === null}
                data-testid="week-setup-add-job"
              >
                <option value="">{t("week_setup.add_row_pick")}</option>
                <optgroup label={t("week_setup.add_row_group_jobs")}>
                  {addJobOptions.map((job) => (
                    <option
                      key={`${job.source_type}:${job.source_id}`}
                      value={encodeSource(job.source_type, job.source_id)}
                    >
                      {job.title}
                    </option>
                  ))}
                </optgroup>
                <optgroup label={t("week_setup.add_row_group_general")}>
                  {GENERAL_SOURCES.map((sourceType) => (
                    <option key={sourceType} value={sourceType}>
                      {t(`hour_source.${sourceType}`)}
                    </option>
                  ))}
                </optgroup>
              </select>
              {addPersonRow?.jobs_truncated && (
                <p className="muted small" style={{ marginTop: 4 }}>
                  {t("week_setup.jobs_truncated", {
                    count: addPersonRow.jobs.length,
                  })}
                </p>
              )}
            </div>
            <div className="field">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={addRow}
                disabled={
                  addPerson === "" || addBuilding === "" || addJob === ""
                }
                data-testid="week-setup-add-row"
              >
                {t("week_setup.add_row_button")}
              </button>
            </div>
            {addError && (
              <p
                className="form-error"
                style={{ gridColumn: "1 / -1", margin: 0 }}
                data-testid="week-setup-add-error"
              >
                {addError}
              </p>
            )}
            {manualList.length > 0 && (
              <div className="week-entry-added" data-testid="week-setup-added">
                {manualList.map(({ personId, seed }) => (
                  <span
                    key={`${personId}:${seedKey(seed)}`}
                    className="cell-tag cell-tag-muted"
                    data-testid="week-setup-added-row"
                  >
                    {seed.label}
                    <button
                      type="button"
                      className="btn btn-ghost btn-sm"
                      style={{ marginLeft: 4, padding: "0 4px" }}
                      onClick={() => removeManual(personId, seedKey(seed))}
                      aria-label={t("week_setup.remove_added_row", {
                        name: seed.label,
                      })}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* `jobTitleOptions` gives the grid's Job column its titles;
            `showSource` is on because these rows CAN belong to a job.
            The per-person proposal travels as `seedRowsByEmployee`; the
            shared seeds are empty, so nothing is multiplied. */}
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
