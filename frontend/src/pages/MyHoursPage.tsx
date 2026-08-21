import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../api/client";
import { listAllBuildings } from "../api/admin";
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
  // W12 §2 — the grid is no longer behind a toggle. It WAS the week's
  // one entry surface hidden behind a button labelled "Weekraster",
  // opening onto "0 assignments / no rows for this week yet" — a
  // mechanic to understand before a single hour could be typed. It is
  // the page now, and the table below it is the record.
  const { me } = useAuth();
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
      const [entryPage, status] = await Promise.all([
        listTimeEntries({
          iso_year: week.isoYear,
          iso_week: week.isoWeek,
          page_size: 200,
        }),
        fetchWeekStatus({ iso_year: week.isoYear, iso_week: week.isoWeek }),
      ]);
      setEntries(entryPage.results);
      setWeekClosed(status.is_closed);
      setLoadError("");
    } catch (err) {
      setLoadError(getApiError(err));
    }
  }, [week]);

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
      fetchWeekStatus({ iso_year: week.isoYear, iso_week: week.isoWeek }),
    ])
      .then(([entryPage, status]) => {
        if (cancelled) return;
        setEntries(entryPage.results);
        setWeekClosed(status.is_closed);
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
  }, [week, weekKey, myEmployeeId]);

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
  return (
    <div>
      <PageHeader
        title={t("my_hours.title")}
        subtitle={t("my_hours.subtitle")}
        actions={
          <button
            type="button"
            className="btn btn-primary btn-sm"
            data-testid="my-hours-add-button"
            onClick={() => openCreate()}
            disabled={weekClosed || loading || hourTypes.length === 0}
          >
            {t("my_hours.add_button")}
          </button>
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
        <div className="loading-bar">
          <div className="loading-bar-fill" />
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
            /* Sprint 179B §2 — this page's rows come from whatever the
               week already holds, and those can be tagged to a job by
               the admin wizard, so the column belongs here too. */
            sourceOptions={sourceOptions}
            showSource
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
        </div>
        )}

        {/* W12 §2 — the record of what is already filed, and ONLY when
            there is something filed.
            An empty week used to show it anyway, as a second empty
            state ("no hours yet — add your first entry") pointing at a
            second way to do what the grid above was already offering.
            A worker opening a blank week now has exactly one surface
            and one verb. */}
        {entries.length > 0 && (
        <div className="card" data-testid="my-hours-list">
          <BoundedList
            size="lg"
            count={entries.length}
            ariaLabel={t("my_hours.list_aria")}
            testIdPrefix="my-hours"
            className="table-wrap"
          >
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t("my_hours.col_date")}</th>
                  <th>{t("my_hours.col_hour_type")}</th>
                  <th>{t("my_hours.col_hours")}</th>
                  <th>{t("my_hours.col_weighted")}</th>
                  <th>{t("my_hours.col_building")}</th>
                  {/* Sprint 179B §2 — the same column the week grid
                      gained. A row that belongs to a ticket or an extra
                      work said so nowhere on this page. */}
                  <th>{t("my_hours.col_job")}</th>
                  <th>{t("my_hours.col_note")}</th>
                  <th>{t("my_hours.col_actions")}</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr
                    key={entry.id}
                    data-testid="my-hours-row"
                    data-entry-id={entry.id}
                  >
                    <td>{formatDayLabel(entry.date, dateLocale)}</td>
                    <td>
                      {hourTypeLabelFrom(
                        entry.hour_type_name,
                        entry.hour_type_standard_slot,
                        t,
                      )}
                    </td>
                    <td>{entry.hours}</td>
                    <td className="muted">{entry.weighted_hours}</td>
                    <td className="muted small">{entry.building_name ?? "—"}</td>
                    <td className="muted small" data-testid="my-hours-job">
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
        </>
      )}

      {/* W12 §2 — totals of nothing are not a total. */}
      {entries.length > 0 && (
      <section
        className="card"
        style={{ marginTop: 16, padding: "18px 22px" }}
        data-testid="my-hours-totals"
      >
        <div className="eyebrow" style={{ marginBottom: 8 }}>
          {t("my_hours.totals_title")}
        </div>
        <div className="detail-kv-list">
          <div className="detail-kv-row">
            <span className="detail-kv-label">{t("my_hours.total_hours")}</span>
            <span className="detail-kv-val" data-testid="my-hours-total-raw">
              {totalHours}
            </span>
          </div>
          <div className="detail-kv-row">
            <span className="detail-kv-label">
              {t("my_hours.total_weighted")}
            </span>
            <span
              className="detail-kv-val"
              data-testid="my-hours-total-weighted"
            >
              {totalWeighted}
            </span>
          </div>
          {perTypeTotals.map((bucket) => (
            <div className="detail-kv-row" key={bucket.id}>
              <span className="detail-kv-label">{bucket.name}</span>
              <span className="detail-kv-val">{bucket.hours}</span>
            </div>
          ))}
        </div>
      </section>
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
                    {hourTypeLabel(hourType, t)} (x{hourType.multiplier})
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
