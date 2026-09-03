import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../api/client";
import { listAllBuildings, listAllCompanies } from "../api/admin";
import { listHourSources } from "../api/reports";
import type { HourSourceOption } from "../api/reports";
import {
  createTimeEntry,
  deleteTimeEntry,
  fetchWeekStatus,
  fillWeekFromContracts,
  listContractHoursPatterns,
  listHourTypes,
  listTimeEntries,
  listWeeksWithHours,
  updateTimeEntry,
} from "../api/timesheets";
import type {
  ContractHoursPattern,
  HourType,
  TimeEntry,
  TimeEntryWritePayload,
} from "../api/timesheets.types";
import type { BuildingAdmin } from "../api/types";
import { BoundedList } from "../components/BoundedList";
import {
  hourTypeLabel,
  hourTypeLabelFrom,
} from "../lib/hourTypeLabel";
import { ConfirmDialog } from "../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../components/ConfirmDialog";
import { PageHeader } from "../components/PageHeader";
import {
  currentIsoWeek,
  formatIsoWeek,
  fromDateString,
  isoWeekDays,
  isoWeekOf,
  isoWeekStart,
  shiftIsoWeek,
  sumDecimalStrings,
  toDateString,
} from "../lib/isoWeek";
import type { IsoWeek } from "../lib/isoWeek";
import type { WeekWithHours } from "../api/timesheets.types";
import { WeekHoursStrip } from "../components/timesheets/WeekHoursStrip";
import { formatHours, lastSavedWeekBefore } from "../lib/weeksWithHours";
import {
  decodeSource,
  encodeSource,
  hourSourceLabel,
} from "../lib/hourSource";
import { HoursWeekGrid } from "../components/timesheets/HoursWeekGrid";
import { useAuth } from "../auth/AuthContext";

interface EntryFormState {
  date: string;
  hour_type: string;
  hours: string;
  building: string;
  note: string;
  /** Sprint 180 §3 — "TYPE:id", or bare "TYPE" for a type-only source
   *  (Contract / Other), or "" for none. The `lib/hourSource` encoding
   *  the entries table already uses, so one decoder serves both. */
  source: string;
}

/** P-15 — the remembered company pick for a multi-company worker, in
 *  the `osius.<module>.company` shape the other modules use. */
const MY_HOURS_COMPANY_KEY = "osius.myhours.company";

function emptyForm(date: string): EntryFormState {
  return { date, hour_type: "", hours: "", building: "", note: "", source: "" };
}

function formatDayLabel(value: string, locale: string): string {
  try {
    return fromDateString(value).toLocaleDateString(locale, {
      weekday: "short",
      day: "2-digit",
      month: "short",
    });
  } catch {
    return value;
  }
}

/**
 * Sprint 152 — "Mijn uren": the own-hours surface, for every
 * provider-side role (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER /
 * STAFF). Customer-side users never reach it — the route guard hides it
 * and every backend endpoint 403s them independently.
 *
 * One ISO week at a time. The week is the unit the whole module is
 * organised around (it is what gets closed), so a page that showed "the
 * last 30 days" would be showing something the lock rule has no opinion
 * about.
 *
 * When the shown week is CLOSED the page says so and disables its own
 * actions. That is a courtesy, not the enforcement: the server rejects
 * every write into a closed week with `week_closed` regardless of what
 * this page offers.
 */
export function MyHoursPage() {
  const { t, i18n } = useTranslation("common");
  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";

  const [week, setWeek] = useState<IsoWeek>(() => currentIsoWeek());
  const [entries, setEntries] = useState<TimeEntry[]>([]);
  // P-9 D3 — which weeks of the shown year hold this person's hours.
  const [weeksWithHours, setWeeksWithHours] = useState<WeekWithHours[]>([]);
  // W12 §2 — the grid is no longer behind a toggle. It WAS the week's
  // one entry surface hidden behind a button labelled "Weekraster",
  // opening onto "0 assignments / no rows for this week yet" — a
  // mechanic to understand before a single hour could be typed. It is
  // the page now, and the table below it is the record.
  const { me } = useAuth();
  /** P-15 (P-14's S2 finding) — a worker whose timesheet scope spans
   *  MORE THAN ONE provider company (building assignments in two
   *  tenants) hit "company is required…" on every load: the
   *  contract-hours prefill and the closed-week status silently failed
   *  and the red banner blamed the worker for input they never gave.
   *  The page now RESOLVES a company — the only one when there is one,
   *  the remembered/first otherwise, with a picker when the scope has
   *  more than one (the admin Hours page's shape) — and sends it on
   *  the two calls that need it. */
  const companyIds = useMemo(() => me?.company_ids ?? [], [me?.company_ids]);
  const [companyPick, setCompanyPick] = useState<number | "">(() => {
    try {
      const stored = Number(
        window.localStorage.getItem(MY_HOURS_COMPANY_KEY),
      );
      return Number.isFinite(stored) && stored > 0 ? stored : "";
    } catch {
      return "";
    }
  });
  const company =
    companyIds.length === 0
      ? undefined
      : companyIds.length === 1
        ? companyIds[0]
        : companyIds.includes(companyPick as number)
          ? (companyPick as number)
          : companyIds[0];
  /** Names for the picker — read only when there is a choice to make;
   *  `/companies/` is scoped, so a worker reads exactly their own. */
  const [companyNames, setCompanyNames] = useState<Record<number, string>>({});
  useEffect(() => {
    if (companyIds.length <= 1) return;
    let cancelled = false;
    listAllCompanies()
      .then((rows) => {
        if (cancelled) return;
        const names: Record<number, string> = {};
        for (const row of rows) names[row.id] = row.name;
        setCompanyNames(names);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [companyIds]);
  // On THIS page the employee is always the signed-in user. The server
  // enforces that independently (a non-manager naming someone else is a
  // 403), so this only decides what the grid writes, never what it may.
  const myEmployeeId = me?.id ?? null;
  // Sprint 155 §5 — the grid's two props, for a one-person page. Both
  // are derived (no effect, no second copy of `entries` to keep in
  // step): the block list is this user, and every entry on the page is
  // already theirs.
  const gridEmployees = useMemo(
    () =>
      myEmployeeId === null
        ? []
        : [
            {
              id: myEmployeeId,
              name: me?.full_name?.trim() || me?.email || "",
            },
          ],
    [myEmployeeId, me?.full_name, me?.email],
  );
  const gridEntries = useMemo(
    () => (myEmployeeId === null ? {} : { [myEmployeeId]: entries }),
    [myEmployeeId, entries],
  );
  const [hourTypes, setHourTypes] = useState<HourType[]>([]);
  const [buildings, setBuildings] = useState<BuildingAdmin[]>([]);
  const [weekClosed, setWeekClosed] = useState(false);
  /** Sprint 179B §2 — the pickable jobs, purely so a stored
   *  `(source_type, source_id)` can be printed as words. */
  const [sourceOptions, setSourceOptions] = useState<HourSourceOption[]>([]);
  /** W12 §5 — this person's standing agreements covering the shown
   *  week, read for ONE purpose: which weekdays they are scheduled to
   *  work. See `quietDays` below. */
  const [patterns, setPatterns] = useState<ContractHoursPattern[]>([]);
  const [loadError, setLoadError] = useState("");
  /** W12 §3 — "the grid holds hours that are not saved yet", reported
   *  by the grid from its own event handlers. It is what makes paging
   *  to another week ask first instead of discarding them silently. */
  const [gridDirty, setGridDirty] = useState(false);

  // `loading` is DERIVED, not stored: it is true exactly while the week
  // in view is not the week last loaded. Storing it would mean a
  // `setLoading(true)` in the effect body, which CLAUDE.md bans (and
  // eslint's `react-hooks/set-state-in-effect` catches) — a synchronous
  // setState there causes a cascading render. The key settles in the
  // fetch's own callbacks, including the failure one, so an error stops
  // the spinner instead of leaving it up forever behind the banner.
  const weekKey = `${week.isoYear}-W${week.isoWeek}`;
  const [loadedWeekKey, setLoadedWeekKey] = useState<string | null>(null);
  const loading = loadedWeekKey !== weekKey;

  const [mode, setMode] = useState<"create" | "edit" | null>(null);
  const [editing, setEditing] = useState<TimeEntry | null>(null);
  const [form, setForm] = useState<EntryFormState>(() =>
    emptyForm(toDateString(isoWeekStart(currentIsoWeek()))),
  );
  const [formError, setFormError] = useState("");
  const [formBusy, setFormBusy] = useState(false);

  /** W-HR1 §4 — the day whose entries are expanded under the grid, as
   *  an ISO date. `null` is the page's resting state: the footer opens
   *  as seven chips and nothing else, and a day's detail is one click.
   *
   *  Deliberately NOT reset when the week changes. Clearing it there
   *  would be a synchronous setState in an effect body, which CLAUDE.md
   *  bans; instead `openDayIso` below only resolves a day that is
   *  actually in the week on screen, so a stale date renders nothing. */
  const [openDay, setOpenDay] = useState<string | null>(null);

  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
  const [deleteTarget, setDeleteTarget] = useState<TimeEntry | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  /** W12 §3 — the week the four navigation controls are asking for
   *  while the "you have unsaved hours" dialog is up. A ref, not state:
   *  nothing renders it, and holding it in state would re-render the
   *  whole page on every blocked click. */
  const leaveDialogRef = useRef<ConfirmDialogHandle>(null);
  const pendingWeekRef = useRef<IsoWeek | null>(null);

  const weekDays = useMemo(() => isoWeekDays(week), [week]);
  const weekStartLabel = useMemo(
    () => weekDays[0].toLocaleDateString(dateLocale, {
      day: "2-digit",
      month: "short",
      year: "numeric",
    }),
    [weekDays, dateLocale],
  );
  const weekEndLabel = useMemo(
    () => weekDays[6].toLocaleDateString(dateLocale, {
      day: "2-digit",
      month: "short",
      year: "numeric",
    }),
    [weekDays, dateLocale],
  );

  /**
   * Re-read this week's entries plus its lock state. NEVER THROWS —
   * every caller runs it after a mutation that already committed, so a
   * failed re-read must not wedge a busy flag or turn a saved row into a
   * form error. Stale list plus a visible page-level error, never
   * silence. (Same contract as `ManagedUnitsTab.refreshUnits`.)
   */
  const refresh = useCallback(async () => {
    try {
      const [entryPage, status, withHours] = await Promise.all([
        listTimeEntries({
          iso_year: week.isoYear,
          iso_week: week.isoWeek,
          page_size: 200,
        }),
        // P-15 — the resolved company rides along; without it a
        // two-company worker's status read 400s on every load.
        fetchWeekStatus({
          iso_year: week.isoYear,
          iso_week: week.isoWeek,
          ...(company !== undefined ? { company } : {}),
        }),
        // P-9 D3 — non-fatal: the strip then shows no marks.
        listWeeksWithHours({ iso_year: week.isoYear }).catch(() => null),
      ]);
      setEntries(entryPage.results);
      setWeekClosed(status.is_closed);
      if (withHours) setWeeksWithHours(withHours.weeks);
      setLoadError("");
    } catch (err) {
      setLoadError(getApiError(err));
    }
  }, [week, company]);

  // Week navigation reloads the week. The lock status is fetched
  // ALONGSIDE the entries rather than derived from them: an empty week
  // has no entry to read `is_locked` off, and an empty week can very
  // much be closed.
  useEffect(() => {
    let cancelled = false;
    /* W12 §1 — fill this week from THIS person's standing agreements
       before reading it, which is what the admin week wizard has done
       since W10 and this page never did.

       That asymmetry is the whole of the owner's first complaint: W10
       wrote the fill, wired it into the wizard, and left the endpoint
       manager-only — so a contracted worker opening their own week got
       a blank sheet, and could not have filled it even if a button had
       been offered. The endpoint now admits the person whose week it
       is and fills theirs alone.

       Idempotent and window-bounded server-side, and it never touches
       a week that already holds a row, so calling it on every week
       change re-fills nothing and overwrites nothing. A failure is not
       fatal: the sheet then shows what is already there.

       `employee` is sent EXPLICITLY, and it is this page's own user.
       For a STAFF member the server ignores it and uses the caller
       anyway — but a SUPER_ADMIN or COMPANY_ADMIN also has a "My
       hours", and for them an omitted `employee` means "the whole
       company", so opening their own page would have quietly
       materialised every colleague's week. This page is about one
       person's hours in every other respect and it is about one
       person's hours here. */
    (myEmployeeId === null
      ? Promise.resolve()
      : fillWeekFromContracts({
          iso_year: week.isoYear,
          iso_week: week.isoWeek,
          employee: myEmployeeId,
          // P-15 — a two-company worker's fill 400'd without it.
          ...(company !== undefined ? { company } : {}),
        })
    )
      .catch(() => undefined)
      .then(() =>
    Promise.all([
      listTimeEntries({
        iso_year: week.isoYear,
        iso_week: week.isoWeek,
        page_size: 200,
      }),
      fetchWeekStatus({
        iso_year: week.isoYear,
        iso_week: week.isoWeek,
        ...(company !== undefined ? { company } : {}),
      }),
      // P-9 D3 — the year's weeks with hours, read with the week so a
      // saved week is marked as soon as the sheet re-reads. Non-fatal.
      listWeeksWithHours({ iso_year: week.isoYear }).catch(() => null),
    ])
      .then(([entryPage, status, withHours]) => {
        if (cancelled) return;
        setEntries(entryPage.results);
        setWeekClosed(status.is_closed);
        if (withHours) setWeeksWithHours(withHours.weeks);
        setLoadError("");
        setLoadedWeekKey(weekKey);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(getApiError(err));
        setLoadedWeekKey(weekKey);
      }));
    return () => {
      cancelled = true;
    };
  }, [week, weekKey, myEmployeeId, company]);

  /**
   * W12 §5 — the weekly PATTERN behind the day columns.
   *
   * Read from the standing agreements in force during this week, and
   * used for one thing: telling a day this person is scheduled to work
   * apart from one they are not. The agreement is where that fact is
   * already written, so nothing here is a second copy of it and no
   * screen asks anybody which days they work.
   *
   * Non-fatal on failure and non-fatal on absence: a worker with no
   * agreement has no stated pattern, and the fallback below invents
   * none for them beyond the calendar's own weekend.
   */
  useEffect(() => {
    if (myEmployeeId === null) return;
    let cancelled = false;
    listContractHoursPatterns({
      employee: myEmployeeId,
      valid_between_start: toDateString(isoWeekStart(week)),
      valid_between_end: toDateString(isoWeekDays(week)[6]),
    })
      .then((rows) => {
        if (!cancelled) setPatterns(rows);
      })
      .catch(() => {
        /* non-fatal: the seven days then read as the plain week */
      });
    return () => {
      cancelled = true;
    };
  }, [myEmployeeId, week]);

  // The form's pickers. Fetched once — they do not depend on the week.
  // Only ACTIVE hour types: an archived one is not offerable for a new
  // entry and the server rejects it (`hour_type_archived`).
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listHourTypes({ is_active: true }),
      listAllBuildings({ is_active: "true" }),
    ])
      .then(([types, buildingRows]) => {
        if (cancelled) return;
        setHourTypes(types);
        setBuildings(buildingRows);
      })
      .catch((err) => {
        if (cancelled) return;
        // Its own message: without the pickers the FORM is unusable
        // even though the list below it is fine.
        setLoadError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /**
   * Sprint 179B §2 — the JOB titles, for the Job column below and for
   * the week grid's own.
   *
   * Non-fatal on failure, the same way the week wizard's picker is: the
   * job is a refinement of an hours row, and a list that could not load
   * must not stop somebody seeing or entering their week. Without it the
   * column falls back to "Ticket #41" — a label, not a blank.
   */
  useEffect(() => {
    let cancelled = false;
    listHourSources()
      .then((options) => {
        if (!cancelled) setSourceOptions(options);
      })
      .catch(() => {
        /* non-fatal: the rows still render, from their type and id */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const totalHours = useMemo(
    () => sumDecimalStrings(entries.map((entry) => entry.hours)),
    [entries],
  );
  const totalWeighted = useMemo(
    () => sumDecimalStrings(entries.map((entry) => entry.weighted_hours)),
    [entries],
  );
  const perTypeTotals = useMemo(() => {
    const buckets = new Map<number, { name: string; hours: string[] }>();
    for (const entry of entries) {
      const bucket = buckets.get(entry.hour_type) ?? {
        name: hourTypeLabelFrom(
          entry.hour_type_name,
          entry.hour_type_standard_slot,
          t,
        ),
        hours: [],
      };
      bucket.hours.push(entry.hours);
      buckets.set(entry.hour_type, bucket);
    }
    return [...buckets.entries()].map(([id, bucket]) => ({
      id,
      name: bucket.name,
      hours: sumDecimalStrings(bucket.hours),
    }));
  }, [entries, t]);

  /**
   * W-HR1 §4 — did any hour this week get WEIGHTED at all?
   *
   * `multiplier_snapshot` is the multiplier that actually produced
   * `weighted_hours` (the type's CURRENT one can differ on an entry in
   * a closed week), so it is the only field that answers this honestly.
   * With every hour at x1.00 the weighted total is the plain total, and
   * printing both taught the reader that one of the two labels is
   * decoration.
   */
  const hasWeighting = useMemo(
    () => entries.some((entry) => Number(entry.multiplier_snapshot) !== 1),
    [entries],
  );

  /** The expanded day, but only if it belongs to the week on screen —
   *  see `openDay`. */
  const openDayIso = useMemo(() => {
    if (openDay === null) return null;
    return weekDays.some((day) => toDateString(day) === openDay)
      ? openDay
      : null;
  }, [openDay, weekDays]);

  const openDayEntries = useMemo(
    () =>
      openDayIso === null
        ? []
        : entries.filter((entry) => entry.date === openDayIso),
    [entries, openDayIso],
  );

  /**
   * W12 §5 — the days the grid prints quietly: the ones this person is
   * not scheduled to work.
   *
   * Two sources, in order, and the order is the point:
   *
   *  1. a standing agreement in force this week — a weekday it puts at
   *     zero is a day this person does not work, stated by the
   *     agreement itself. Several agreements (two buildings, say) are
   *     summed, so a Saturday worked at one of them is not quiet;
   *  2. no agreement at all — then nobody has stated a pattern and this
   *     page will not invent one. It falls back to the calendar's own
   *     distinction, Saturday and Sunday, which is a fact about the
   *     week rather than a claim about the person.
   *
   * Either way the columns stay editable. Covering a Saturday shift is
   * precisely when an accurate hour matters.
   */
  const quietDays = useMemo(() => {
    const dayFields = [
      "monday",
      "tuesday",
      "wednesday",
      "thursday",
      "friday",
      "saturday",
      "sunday",
    ] as const;
    if (patterns.length === 0) {
      return [toDateString(weekDays[5]), toDateString(weekDays[6])];
    }
    return dayFields
      .map((field, index) => ({ field, index }))
      .filter(({ field }) =>
        patterns.every((pattern) => Number(pattern[field]) === 0),
      )
      .map(({ index }) => toDateString(weekDays[index]));
  }, [patterns, weekDays]);

  /**
   * W12 §2 — what the grid seeds an EMPTY week with.
   *
   * The page used to pass `[]`, which meant no seed, which meant no
   * block, which meant no row — and `+ Add type` lives inside a block,
   * so an empty week offered literally no way in through the grid. The
   * owner's screenshot is that state: "0 assignments", "no rows for
   * this week yet", and a fill control above a table with nothing to
   * fill.
   *
   * One seat, and only while the week is genuinely empty: a week that
   * already holds rows is seeded from those rows, and adding a blank
   * "no building" line beside them would be a row nobody asked for.
   */
  const gridSeed = useMemo<(number | null)[]>(
    () => (entries.length === 0 ? [null] : []),
    [entries.length],
  );

  /** P-12 B1 — the one person's bookable buildings, for the grid's
   *  "+ Add a line" choice. The scoped buildings read above is exactly
   *  "their own access". */
  const myBookableBuildingIds = useMemo<Record<number, number[]>>(
    () =>
      myEmployeeId === null
        ? {}
        : { [myEmployeeId]: buildings.map((building) => building.id) },
    [myEmployeeId, buildings],
  );

  /**
   * W12 §3 — every route to another week runs through here.
   *
   * The grid posts the week it is showing and is remounted per week, so
   * paging away used to discard whatever was typed and not yet saved —
   * which the grid warned about in a permanent sentence above the
   * table. The warning is gone and the loss is asked about at the
   * moment it would happen, which is the only moment it means anything.
   */
  function requestWeek(next: IsoWeek) {
    if (gridDirty) {
      pendingWeekRef.current = next;
      leaveDialogRef.current?.open();
      return;
    }
    setWeek(next);
  }

  function handleConfirmLeaveWeek() {
    const next = pendingWeekRef.current;
    pendingWeekRef.current = null;
    leaveDialogRef.current?.close();
    setGridDirty(false);
    if (next) setWeek(next);
  }

  function handleCancelLeaveWeek() {
    pendingWeekRef.current = null;
    leaveDialogRef.current?.close();
  }

  function openCreate(dateValue?: string) {
    setMode("create");
    setEditing(null);
    setForm(emptyForm(dateValue ?? toDateString(weekDays[0])));
    setFormError("");
  }

  function openEdit(entry: TimeEntry) {
    setMode("edit");
    setEditing(entry);
    setForm({
      date: entry.date,
      hour_type: String(entry.hour_type),
      hours: entry.hours,
      building: entry.building === null ? "" : String(entry.building),
      note: entry.note,
      source: encodeSource(entry.source_type, entry.source_id),
    });
    setFormError("");
  }

  function closeModal() {
    setMode(null);
    setEditing(null);
    setFormError("");
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!form.date || !form.hour_type || !form.hours.trim()) {
      setFormError(t("my_hours.error_required_fields"));
      return;
    }
    setFormBusy(true);
    setFormError("");
    const payload: TimeEntryWritePayload = {
      date: form.date,
      hour_type: Number(form.hour_type),
      hours: form.hours.trim(),
      building: form.building === "" ? null : Number(form.building),
      note: form.note.trim(),
      // Sprint 180 §3 — the decoder turns "" back into OTHER with no id,
      // which is the column's own default, so clearing the field puts
      // the row back to the state an untagged row has rather than
      // leaving whatever was there before.
      ...decodeSource(form.source),
    };
    try {
      if (mode === "create") {
        await createTimeEntry(payload);
      } else if (mode === "edit" && editing) {
        await updateTimeEntry(editing.id, payload);
      }
      // A date edit can move an entry out of the shown week entirely;
      // re-read rather than merge so the list stays honest about what
      // this week now contains.
      await refresh();
      closeModal();
    } catch (err) {
      setFormError(getApiError(err));
    } finally {
      setFormBusy(false);
    }
  }

  function openDeleteDialog(entry: TimeEntry) {
    setDeleteTarget(entry);
    deleteDialogRef.current?.open();
  }

  function handleCancelDelete() {
    deleteDialogRef.current?.close();
    setDeleteTarget(null);
  }

  async function handleConfirmDelete() {
    if (!deleteTarget) return;
    setDeleteBusy(true);
    try {
      await deleteTimeEntry(deleteTarget.id);
      await refresh();
      deleteDialogRef.current?.close();
      setDeleteTarget(null);
    } catch (err) {
      // Most often `week_closed` from a stale page whose week was
      // closed by an admin while it was open here.
      setLoadError(getApiError(err));
      deleteDialogRef.current?.close();
    } finally {
      setDeleteBusy(false);
    }
  }

  // Sprint 162 — this wrapper used to carry a `page` class that had no
  // rule behind it and never has; the other pages use a bare wrapper.
  // Found by the Sprint 161 undefined-class gate while this file was
  // open for §1c. (The gate greps for class literals textually, so
  // naming the class here would make it report itself.)
  // P-15 (P-14's S4 finding) — the no-hour-types truth renders ONCE:
  // the banner below carries it, so the button's reason line stands
  // down for that case (it still says why on a closed week).
  const addDisabledReason = weekClosed
    ? t("my_hours.add_disabled_closed")
    : null;
  // P-9 D3 — the last week before this one that holds hours.
  const lastSavedWeek = lastSavedWeekBefore(weeksWithHours, week);
  return (
    <div>
      <PageHeader
        title={t("my_hours.title")}
        subtitle={t("my_hours.subtitle")}
        actions={
          <span className="page-header-action-with-reason">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              data-testid="my-hours-add-button"
              onClick={() => openCreate()}
              disabled={weekClosed || loading || hourTypes.length === 0}
              title={addDisabledReason ?? undefined}
            >
              {t("my_hours.add_button")}
            </button>
            {/* P-5 S4.2 (§D.6 rule 14) — a disabled control says why. */}
            {addDisabledReason && (
              <span className="muted small" data-testid="my-hours-add-disabled-reason">
                {addDisabledReason}
              </span>
            )}
          </span>
        }
      />

      <div className="card" style={{ padding: "14px 16px", marginBottom: 16 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          {/* P-15 — the two-company worker picks WHICH company's week
              administration this page asks about (fill, closed-state).
              One company: no control, resolved silently. */}
          {companyIds.length > 1 && (
            <label
              className="muted small"
              data-testid="my-hours-company-picker"
              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
            >
              {t("my_hours.company_label")}
              <select
                className="field-select"
                value={company}
                onChange={(event) => {
                  const picked = Number(event.target.value);
                  setCompanyPick(picked);
                  try {
                    window.localStorage.setItem(
                      MY_HOURS_COMPANY_KEY,
                      String(picked),
                    );
                  } catch {
                    /* storage unavailable — the pick still applies */
                  }
                }}
              >
                {companyIds.map((id) => (
                  <option key={id} value={id}>
                    {companyNames[id] ?? `#${id}`}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="my-hours-prev-week"
            onClick={() => requestWeek(shiftIsoWeek(week, -1))}
          >
            {t("my_hours.previous_week")}
          </button>
          <div style={{ minWidth: 200, textAlign: "center" }}>
            <div style={{ fontWeight: 600 }} data-testid="my-hours-week-label">
              {formatIsoWeek(week)}
            </div>
            <div className="muted small">
              {weekStartLabel} – {weekEndLabel}
            </div>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="my-hours-next-week"
            onClick={() => requestWeek(shiftIsoWeek(week, 1))}
          >
            {t("my_hours.next_week")}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            data-testid="my-hours-this-week"
            onClick={() => requestWeek(currentIsoWeek())}
          >
            {t("my_hours.this_week")}
          </button>
          <div className="field" style={{ margin: 0, minWidth: 180 }}>
            <label className="sr-only" htmlFor="my-hours-week-jump">
              {t("my_hours.jump_to_week")}
            </label>
            {/* A DATE jump, not a week jump: `<input type="week">` is
                not supported in Firefox or Safari, so a plain date input
                is the portable control. Any day of a week selects that
                whole week. */}
            <input
              id="my-hours-week-jump"
              className="field-input"
              type="date"
              data-testid="my-hours-week-jump"
              value={toDateString(weekDays[0])}
              onChange={(event) => {
                if (!event.target.value) return;
                requestWeek(isoWeekOf(fromDateString(event.target.value)));
              }}
            />
          </div>
          {/* P-9 D3 — which weeks of the year hold hours (the same strip
              the admin Hours page carries); a click moves the sheet. */}
          <WeekHoursStrip
            year={week.isoYear}
            week={week}
            weeks={weeksWithHours}
            onPick={requestWeek}
            testIdPrefix="my-hours-week"
          />
        </div>
      </div>

      {weekClosed && (
        <div
          className="alert-info"
          role="status"
          style={{ marginBottom: 16 }}
          data-testid="my-hours-week-closed-notice"
        >
          {t("my_hours.week_closed_notice", { week: formatIsoWeek(week) })}
        </div>
      )}

      {loadError && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {loadError}
        </div>
      )}

      {hourTypes.length === 0 && !loading && (
        <div
          className="alert-info"
          role="status"
          style={{ marginBottom: 16 }}
          data-testid="my-hours-no-hour-types"
        >
          {t("my_hours.no_hour_types")}
        </div>
      )}

      {loading ? (
        <div className="card skeleton-table" aria-hidden="true" data-testid="my-hours-skeleton">
          {[0, 1, 2, 3].map((row) => (
            <div className="skeleton-row" key={row}>
              <span className="skeleton-line" />
              <span className="skeleton-line" />
              <span className="skeleton-line" />
              <span className="skeleton-line" />
              <span className="skeleton-line" />
              <span className="skeleton-line" />
            </div>
          ))}
        </div>
      ) : (
        <>
        {/* W12 §2 — the grid, open, and the page's primary surface.
            No toggle, no head strip: the card above already says which
            week this is and the header says whose hours these are, so
            the strip's title and count restated both and then spent two
            sentences teaching grid mechanics. `employee` is omitted: a
            non-manager may only ever write their own hours, and the
            server forces that regardless of what is sent.

            Rendered only once we know WHO is signed in. Handed an
            empty employee list the grid says "choose one or more
            employees first", which is a sentence with no meaning on a
            page that has no chooser. */}
        {/* P-9 D3 — THE EMPTY WEEK SAYS WHERE THE HOURS ARE, in the
            admin Hours page's words: the week, the last saved week, a
            button to open it, and the page's own entry action. */}
        {entries.length === 0 && (
          <div
            className="card"
            style={{ marginBottom: 16, padding: "16px 18px" }}
            data-testid="my-hours-week-empty"
          >
            <strong data-testid="my-hours-empty-title">
              {t("hours_weeks.empty_week_title", { week: week.isoWeek })}
            </strong>
            <p
              className="muted small"
              style={{ margin: "4px 0 0" }}
              data-testid="my-hours-empty-last-saved"
            >
              {lastSavedWeek
                ? t("hours_weeks.last_saved_week", {
                    week: lastSavedWeek.iso_week,
                    hours: formatHours(lastSavedWeek.hours, dateLocale),
                  })
                : t("hours_weeks.no_saved_weeks", { year: week.isoYear })}
            </p>
            <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
              {lastSavedWeek && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  data-testid="my-hours-empty-open-last-week"
                  onClick={() =>
                    requestWeek({
                      isoYear: lastSavedWeek.iso_year,
                      isoWeek: lastSavedWeek.iso_week,
                    })
                  }
                >
                  {t("hours_weeks.open_week", { week: lastSavedWeek.iso_week })}
                </button>
              )}
              {!addDisabledReason && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  data-testid="my-hours-empty-enter"
                  onClick={() => openCreate()}
                >
                  {t("hours_admin.enter_week_button")}
                </button>
              )}
            </div>
          </div>
        )}
        {gridEmployees.length > 0 && (
        <div
          className="card"
          style={{ marginBottom: 16, padding: "16px 18px" }}
          data-testid="my-hours-week-grid-card"
        >
          <HoursWeekGrid
            /* Sprint 180 §2 — keyed by the week, for the same reason
               the week wizard is: the grid's cells are keyed by date
               and Save posts one week, so anything typed for the week
               you just paged away from was invisible AND unsaveable. */
            key={weekKey}
            week={week}
            /* Sprint 155 §5 — the grid renders a block per employee it
               is given. Here that is exactly one person: this page
               writes only the signed-in user's own hours, so there is
               no selector and nothing to choose. Same component as the
               admin page, one member in the list. */
            employees={gridEmployees}
            hourTypes={hourTypes}
            buildings={buildings}
            entriesByEmployee={gridEntries}
            /* W12 §2 — one seat on an EMPTY week, so there is always a
               row to type in and `+ Add type` is always reachable. See
               `gridSeed`. */
            seedBuildingIds={gridSeed}
            /* P-12 B1 — "+ Add a line"'s building choice: this
               person's own scoped building list (the same one the
               entry form's picker shows). */
            personBuildingIds={myBookableBuildingIds}
            /* Sprint 179B §2 — this page's rows come from whatever the
               week already holds, and those can be tagged to a job by
               the admin wizard, so the column belongs here too. */
            sourceOptions={sourceOptions}
            /* W12 §2 / §3 — both off for a worker: the head restated
               the week and explained mechanics, and "fill this weekday
               on every row" is an admin verb that needed a paragraph of
               rules to be usable. */
            showHead={false}
            showApplyRow={false}
            /* W12 §5 — the days this person is not scheduled for. */
            quietDays={quietDays}
            weekClosed={weekClosed}
            onDirtyChange={setGridDirty}
            onSaved={refresh}
          />

          {/* W-HR1 §4 — THE FOOTER OF THE ONE EDITOR.

              The totals used to be a card of their own BELOW a second
              table that listed the same hours the grid above was
              already showing and editing. Two surfaces for one week,
              and the numbers describing them floated free of both. They
              are the grid's footer now, in the grid's own card, the way
              a table's totals row belongs to its table.

              Nothing the deleted list could do is gone: its per-entry
              Edit and Delete live in the day panel below, one click
              from the day they belong to. */}
          {entries.length > 0 && (
            <div
              style={{
                marginTop: 14,
                paddingTop: 12,
                borderTop: "1px solid var(--border)",
              }}
              data-testid="my-hours-totals"
            >
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  alignItems: "baseline",
                  gap: "6px 20px",
                }}
              >
                <span className="detail-kv-label">
                  {t("my_hours.total_hours")}
                </span>
                <strong data-testid="my-hours-total-raw">{totalHours}</strong>

                {/* W-HR1 §4 — the weighted total, ONLY when weighting
                    happened. Every hour type in this deployment sits at
                    x1.00 unless somebody set otherwise, and on such a
                    week "8,00" and "8,00" stood side by side under two
                    different labels — a number that teaches the reader
                    the label means nothing. Read off
                    `multiplier_snapshot`, the multiplier that actually
                    produced `weighted_hours`, not the type's current
                    one. */}
                {hasWeighting && (
                  <>
                    <span className="detail-kv-label">
                      {t("my_hours.total_weighted")}
                    </span>
                    <strong data-testid="my-hours-total-weighted">
                      {totalWeighted}
                    </strong>
                  </>
                )}

                {/* The per-type split, ONLY when there is a split. With
                    one hour type in the week its single row repeated
                    the total a third time. */}
                {perTypeTotals.length > 1 &&
                  perTypeTotals.map((bucket) => (
                    <span key={bucket.id} className="muted small">
                      {bucket.name} {bucket.hours}
                    </span>
                  ))}
              </div>

              {/* W-HR1 §4 — DEPTH ON CLICK, per day.
                  One chip per weekday carrying that day's hours; the
                  chip opens the day's own entries, with the Edit and
                  Delete the deleted list used to carry. The chip is the
                  click target rather than a grid cell: a cell is a text
                  input, and a click there has to keep meaning "put the
                  caret here and type". */}
              <div
                style={{
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 6,
                  marginTop: 10,
                }}
                data-testid="my-hours-day-strip"
              >
                {weekDays.map((dayDate) => {
                  const iso = toDateString(dayDate);
                  const dayEntries = entries.filter((e) => e.date === iso);
                  const label = formatDayLabel(iso, dateLocale);
                  const isOpen = openDay === iso;
                  return (
                    <button
                      key={iso}
                      type="button"
                      className={`btn btn-sm ${isOpen ? "btn-secondary" : "btn-ghost"}`}
                      onClick={() => setOpenDay(isOpen ? null : iso)}
                      aria-expanded={isOpen}
                      data-testid={`my-hours-day-${iso}`}
                      data-day-count={dayEntries.length}
                    >
                      {label}
                      {dayEntries.length > 0 && (
                        <>
                          {" · "}
                          <strong>
                            {sumDecimalStrings(dayEntries.map((e) => e.hours))}
                          </strong>
                        </>
                      )}
                    </button>
                  );
                })}
              </div>

              {openDayIso !== null && (
                <div style={{ marginTop: 10 }} data-testid="my-hours-day-panel">
                  {/* P-16 (P-14 S4) — hours dated after today (the
                      SERVER's is_future, never the browser clock) say
                      so, once per day, amber. A flag, never a block. */}
                  {openDayEntries.some((entry) => entry.is_future) && (
                    <p
                      className="alert-warning small"
                      style={{ margin: "0 0 8px", padding: "6px 10px" }}
                      data-testid="my-hours-future-note"
                    >
                      {t("my_hours.future_note")}
                    </p>
                  )}
                  {/* Bounded, like every list over a server collection
                      (CLAUDE.md #8). `sm` because this is ONE day of
                      ONE person — the 260px step is the right size for
                      it, and a day that somehow holds twenty rows
                      scrolls rather than pushing the grid off screen. */}
                  <BoundedList
                    size="sm"
                    count={openDayEntries.length}
                    ariaLabel={t("my_hours.list_aria")}
                    testIdPrefix="my-hours-day"
                    className="table-wrap"
                    emptyState={
                      <p className="muted small" style={{ margin: "8px 0 0" }}>
                        {t("my_hours.day_empty")}
                      </p>
                    }
                  >
                    <table className="data-table data-table-dense">
                      <thead>
                        <tr>
                          <th>{t("my_hours.col_hour_type")}</th>
                          <th>{t("my_hours.col_hours")}</th>
                          {hasWeighting && (
                            <th>{t("my_hours.col_weighted")}</th>
                          )}
                          <th>{t("my_hours.col_building")}</th>
                          <th>{t("my_hours.col_job")}</th>
                          <th>{t("my_hours.col_note")}</th>
                          <th>{t("my_hours.col_actions")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {openDayEntries.map((entry) => (
                          <tr
                            key={entry.id}
                            data-testid="my-hours-row"
                            data-entry-id={entry.id}
                          >
                            <td>
                              {hourTypeLabelFrom(
                                entry.hour_type_name,
                                entry.hour_type_standard_slot,
                                t,
                              )}
                            </td>
                            <td>{entry.hours}</td>
                            {hasWeighting && (
                              <td className="muted">{entry.weighted_hours}</td>
                            )}
                            <td className="muted small">
                              {entry.building_name ?? "—"}
                            </td>
                            <td
                              className="muted small"
                              data-testid="my-hours-job"
                            >
                              {hourSourceLabel(
                                entry.source_type,
                                entry.source_id,
                                sourceOptions,
                                t,
                                "—",
                              )}
                            </td>
                            <td className="muted small">{entry.note || "—"}</td>
                            <td>
                              <div style={{ display: "flex", gap: 6 }}>
                                <button
                                  type="button"
                                  className="btn btn-ghost btn-sm"
                                  data-testid="my-hours-edit-button"
                                  onClick={() => openEdit(entry)}
                                  disabled={entry.is_locked}
                                >
                                  {t("my_hours.edit_button")}
                                </button>
                                <button
                                  type="button"
                                  className="btn btn-ghost btn-sm"
                                  data-testid="my-hours-delete-button"
                                  onClick={() => openDeleteDialog(entry)}
                                  disabled={entry.is_locked}
                                >
                                  {t("my_hours.delete_button")}
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </BoundedList>
                </div>
              )}
            </div>
          )}
        </div>
        )}

        </>
      )}

      {mode !== null && (
        <div
          data-testid="my-hours-modal"
          role="dialog"
          aria-modal="true"
          aria-label={
            mode === "create"
              ? t("my_hours.add_modal_title")
              : t("my_hours.edit_modal_title")
          }
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
          <form
            onSubmit={handleSubmit}
            className="card"
            style={{
              maxWidth: 560,
              width: "100%",
              padding: 24,
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <h3 className="section-title" style={{ marginTop: 0, marginBottom: 12 }}>
              {mode === "create"
                ? t("my_hours.add_modal_title")
                : t("my_hours.edit_modal_title")}
            </h3>

            {formError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="my-hours-modal-error"
              >
                {formError}
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="my-hours-date">
                {t("my_hours.field_date")} *
              </label>
              <input
                id="my-hours-date"
                className="field-input"
                type="date"
                value={form.date}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, date: event.target.value }))
                }
                data-testid="my-hours-input-date"
                required
                disabled={formBusy}
              />
              <div className="muted small" style={{ marginTop: 4 }}>
                {t("my_hours.field_date_hint")}
              </div>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="my-hours-hour-type">
                {t("my_hours.field_hour_type")} *
              </label>
              <select
                id="my-hours-hour-type"
                className="field-select"
                value={form.hour_type}
                onChange={(event) =>
                  setForm((prev) => ({
                    ...prev,
                    hour_type: event.target.value,
                  }))
                }
                data-testid="my-hours-input-hour-type"
                required
                disabled={formBusy}
              >
                <option value="">{t("my_hours.field_hour_type_empty")}</option>
                {hourTypes.map((hourType) => (
                  <option key={hourType.id} value={hourType.id}>
                    {hourTypeLabel(hourType, t)} ({t("hour_types.multiplier_note", { n: hourType.multiplier })})
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="my-hours-hours">
                {t("my_hours.field_hours")} *
              </label>
              <input
                id="my-hours-hours"
                className="field-input"
                type="number"
                min="0.25"
                max="24"
                step="0.25"
                value={form.hours}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, hours: event.target.value }))
                }
                data-testid="my-hours-input-hours"
                required
                disabled={formBusy}
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="my-hours-building">
                {t("my_hours.field_building")}
              </label>
              <select
                id="my-hours-building"
                className="field-select"
                value={form.building}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, building: event.target.value }))
                }
                data-testid="my-hours-input-building"
                disabled={formBusy}
              >
                <option value="">{t("my_hours.field_building_empty")}</option>
                {buildings.map((building) => (
                  <option key={building.id} value={building.id}>
                    {building.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Sprint 180 §3 — WHICH JOB, editable at last.
                Sprint 179B put the job in the list on this page and left
                it read-only, so the one screen that showed a wrong job
                was the one screen that could not correct it. The options
                and the encoding are the entries table's — the same
                `listHourSources()` list and the same
                `encodeSource`/`decodeSource` pair — so the two paths
                cannot drift on what a valid source is. */}
            <div className="field">
              <label className="field-label" htmlFor="my-hours-source">
                {t("my_hours.field_job")}
              </label>
              <select
                id="my-hours-source"
                className="field-select"
                value={form.source}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, source: event.target.value }))
                }
                data-testid="my-hours-input-source"
                disabled={formBusy}
              >
                <option value="">{t("my_hours.field_job_empty")}</option>
                {/* The row's CURRENT job stays offerable even when the
                    job has since closed and left the picker: without it,
                    editing the hours of a finished ticket would silently
                    retag them. Same guard the entries table carries. */}
                {form.source &&
                  !sourceOptions.some(
                    (option) =>
                      encodeSource(option.source_type, option.source_id) ===
                      form.source,
                  ) && (
                    <option value={form.source}>
                      {hourSourceLabel(
                        decodeSource(form.source).source_type,
                        decodeSource(form.source).source_id,
                        sourceOptions,
                        t,
                        t("hours_week_grid.no_source"),
                      )}
                    </option>
                  )}
                {sourceOptions.map((option) => (
                  <option
                    key={encodeSource(option.source_type, option.source_id)}
                    value={encodeSource(option.source_type, option.source_id)}
                  >
                    {option.title}
                  </option>
                ))}
              </select>
              <div className="field-hint">{t("my_hours.field_job_hint")}</div>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="my-hours-note">
                {t("my_hours.field_note")}
              </label>
              <textarea
                id="my-hours-note"
                className="field-input"
                rows={3}
                value={form.note}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, note: event.target.value }))
                }
                data-testid="my-hours-input-note"
                disabled={formBusy}
              />
            </div>

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                gap: 8,
                marginTop: 12,
              }}
            >
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={closeModal}
                disabled={formBusy}
                data-testid="my-hours-modal-cancel"
              >
                {t("my_hours.cancel")}
              </button>
              <button
                type="submit"
                className="btn btn-primary btn-sm"
                disabled={formBusy}
                data-testid="my-hours-modal-save"
              >
                {formBusy ? t("admin_form.saving") : t("my_hours.save")}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Unconditionally rendered and ref-driven (CLAUDE.md §3): a
          native <dialog> wrapped in a condition mounts INVISIBLE and the
          trigger looks dead. */}
      {/* W12 §3 — asked at the moment work would be lost, in place of a
          sentence that sat above the table permanently warning about
          it. Ref-driven and unconditional, like its neighbour. */}
      <ConfirmDialog
        ref={leaveDialogRef}
        title={t("my_hours.leave_week_title")}
        body={t("my_hours.leave_week_body")}
        confirmLabel={t("my_hours.leave_week_confirm")}
        onConfirm={handleConfirmLeaveWeek}
        onCancel={handleCancelLeaveWeek}
        destructive
      />

      <ConfirmDialog
        ref={deleteDialogRef}
        title={t("my_hours.delete_confirm_title")}
        body={t("my_hours.delete_confirm_body")}
        confirmLabel={t("my_hours.delete_button")}
        onConfirm={handleConfirmDelete}
        onCancel={handleCancelDelete}
        busy={deleteBusy}
        destructive
      />
    </div>
  );
}
