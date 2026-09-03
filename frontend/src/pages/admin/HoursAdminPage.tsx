import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useLocation, useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { listAllBuildings, listAllCompanies } from "../../api/admin";
import { getApiError } from "../../api/client";
import {
  decodeSource,
  encodeSource,
  hourSourceLabel,
} from "../../lib/hourSource";
import { listHourSources } from "../../api/reports";
import type { HourSourceOption } from "../../api/reports";
import {
  closeWeek,
  deleteTimeEntry,
  downloadTimesheetSummaryCsv,
  fetchTimesheetSummary,
  fetchWeekStatus,
  listHourTypes,
  listTimeEntries,
  listWeeksWithHours,
  listTimesheetEmployees,
  reopenWeek,
  updateTimeEntry,
} from "../../api/timesheets";
import type {
  HourType,
  TimeEntry,
  TimeEntryFilters,
  TimesheetEmployee,
  TimesheetSummary,
  WeekStatus,
  WeekWithHours,
} from "../../api/timesheets.types";
import type { BuildingAdmin, CompanyAdmin } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ClickableRow } from "../../components/ClickableRow";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { PageHeader } from "../../components/PageHeader";
import { CompanyScopeSelect } from "../../components/guide/CompanyScopeSelect";
import {
  readScopeCompany,
  rememberScopeCompany,
} from "../../lib/useCompanyScope";
import { StartHere } from "../../components/guide/StartHere";
import { DoneBanner } from "../../components/guide/DoneBanner";
import { useDoneBanner } from "../../components/guide/useDoneBanner";
import { TeachEmpty } from "../../components/guide/TeachEmpty";
import { HIGHLIGHT_CLASS, HIGHLIGHT_MS } from "../../components/guide/highlight";
import { HowThisWorks } from "../../components/guide/HowThisWorks";
import { WhatHappens } from "../../components/guide/WhatHappens";
import { useToast } from "../../components/ToastProvider";
import {
  currentIsoWeek,
  formatIsoWeek,
  fromDateString,
  isoWeekDays,
  parseIsoWeek,
  shiftIsoWeek,
  toDateString,
} from "../../lib/isoWeek";
import type { IsoWeek } from "../../lib/isoWeek";
import { WeekEntryDialog } from "../../components/timesheets/WeekEntryDialog";
import { OverflowMenu } from "../../components/OverflowMenu";
import { formatHours, lastSavedWeekBefore } from "../../lib/weeksWithHours";
import { jobTitleFirst } from "../../components/timesheets/jobTitle";
import { hourTypeLabel, hourTypeLabelFrom } from "../../lib/hourTypeLabel";
import { HoursFilterRow } from "./HoursFilterRow";
import { ContractHoursTab } from "./ContractHoursTab";
import { HOURS_TABS, hoursTabOf } from "./hoursTabs";

/**
 * P-14 A1 — Agreed hours come back as a TAB.
 *
 * P-13 W6 took the "Weekly schedule" view off this page, calling it
 * planning. It is not: it is each person's standing weekly pattern
 * per building (`timesheets.ContractHours`, Draft → Submitted →
 * Agreed), the thing that seeds the standard lines in Enter hours —
 * a Hours concept, and the owner wants it where it was. The page is
 * now the People-style pair of URL-backed tabs: **Hours worked**
 * (`/admin/hours`) | **Agreed hours** (`/admin/hours/agreed`), the
 * table in `hoursTabs.ts` (vitest-pinned). The P-13 `?tab=schedule`
 * deep link redirects onto the Agreed tab so no saved link goes dead.
 */

// Sprint 152 — the SUPER_ADMIN's provider company, remembered across
// visits. Its OWN key, not shared with the catalog's
// (`osius.catalog.company`): the two surfaces are navigated
// independently, and making a choice in one silently move the other is
// the kind of coupling that reads as a bug.
const HOURS_COMPANY_STORAGE_KEY = "osius.hours.company";

interface EntryFilterState {
  employee: number | "";
  hour_type: number | "";
  building: number | "";
  source_type: string;
  date_from: string;
  date_to: string;
}

/**
 * W-HR1 §2 — the page opens on THIS WEEK, not on "everything ever".
 *
 * The Worked tab now carries a week bar that owns the lock chip and the
 * close/reopen button, and the table under it has to describe the same
 * week or the two disagree. So the week writes `date_from`/`date_to`,
 * and those two inputs stay hand-editable for the odd wider range —
 * which is the only thing the deleted Overview tab's range mode was
 * ever used for.
 *
 * A function, not a constant: the current week is not a constant.
 */
function weekFilters(week: IsoWeek): EntryFilterState {
  const days = isoWeekDays(week);
  return {
    employee: "",
    hour_type: "",
    building: "",
    source_type: "",
    date_from: toDateString(days[0]),
    date_to: toDateString(days[6]),
  };
}

/** One row's pending inline edit. Every field is a STRING: a `<select>`
 *  / `<input>` value is a string, and keeping numbers here means a parse
 *  on every render plus an empty-string special case at each one. */
interface EntryDraft {
  date: string;
  hour_type: string;
  hours: string;
  building: string;
  note: string;
  /** Sprint 178 §4a — "TYPE:id", or "TYPE" for a type-only source. */
  source: string;
}

function draftOf(entry: TimeEntry): EntryDraft {
  return {
    date: entry.date,
    hour_type: String(entry.hour_type),
    hours: entry.hours,
    building: entry.building === null ? "" : String(entry.building),
    note: entry.note,
    source: encodeSource(entry.source_type, entry.source_id),
  };
}

function draftsDiffer(a: EntryDraft, b: EntryDraft): boolean {
  return (
    a.date !== b.date ||
    a.hour_type !== b.hour_type ||
    a.hours.trim() !== b.hours.trim() ||
    a.building !== b.building ||
    a.note !== b.note ||
    a.source !== b.source
  );
}

function formatDate(value: string, locale: string): string {
  if (!value) return "—";
  try {
    return fromDateString(value).toLocaleDateString(locale, {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return value;
  }
}

/**
 * The "Uren" admin area. W-HR1 §2 cut it from seven tabs to two; P-13
 * W6 cut the remaining toggle; P-14 A1 brought Agreed hours back as
 * the second URL-backed tab (see the header comment above). What
 * follows describes the WORKED tab.
 *
 * ## What the page is
 *
 *   Start here, the week CARD (which week, one status chip, Enter
 *     hours, Week afsluiten / Heropenen, the per-person rows),
 *     Earlier weeks
 *   then ONE fold, "All entries": the wrapping filter row and the raw
 *     per-entry table, with an Edit toggle that makes its cells
 *     editable and saves every change at once, the week's totals as
 *     its FOOTER, and real prev/next off the endpoint's own pagination
 *
 * No stat tiles, no 420px scroll window over the table, no second copy
 * of the same numbers anywhere on the page.
 *
 * ## The week is the period
 *
 * The bar owns the week; `date_from`/`date_to` are what it resolves to
 * and stay hand-editable for a wider range (the one thing the deleted
 * Overview tab's range mode was for). Clearing the filters returns to
 * the bar's week rather than to "every hour ever filed".
 *
 * The lock chip and the one button therefore always have a week to act
 * on — which is why closing a week moved here from a tab two clicks
 * away, where the hours it governs were not on screen.
 *
 * ## Company resolution
 *
 * Sprint 149/150's model for a SUPER_ADMIN: exactly ONE provider
 * company is in view at a time, seeded from the operator's remembered
 * choice and otherwise from the LOWEST id (the deployment's first
 * tenant, not an alphabetical accident). The seed is set inside the
 * fetch's `.then()`, never in an effect body — CLAUDE.md bans a
 * synchronous setState there.
 *
 * Sprint 159's gate holds: for a SUPER_ADMIN the reads WAIT until the
 * company is known. Measured on the built Sprint 158 page, the first
 * render fired `/timesheets/employees/` and `/timesheets/summary/` with
 * no company and took two 400s (`company is required when more than one
 * provider Company exists`) before the retry, which put a red error
 * banner on screen for as long as the company list took to resolve.
 *
 * A COMPANY_ADMIN sees no selector at all: they have one company and
 * `""` means "let the backend resolve it", which is what every write
 * path here already does.
 */
export function HoursAdminPage() {
  const { t, i18n } = useTranslation("common");
  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";
  const { me } = useAuth();
  const { push: pushToast } = useToast();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  /* W-UX F41 — the week is URL state (`?week=2026-W35`), the ticket
   * page's exact rule: absence is the default, writes replace history,
   * a reload or a shared link lands on the same view. P-14 A1 — the
   * tab is URL state too (the PATH: `/admin/hours/agreed`), derived
   * each render, never stored. */
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const activeTab = hoursTabOf(location.pathname, searchParams.get("tab"));
  const agreedView = activeTab === "agreed";
  const initialWeek: IsoWeek =
    parseIsoWeek(searchParams.get("week") ?? "") ?? currentIsoWeek();

  /** W-HR1 §2 — the week the lock chip and the one button act on, and
   *  the week the table opens on. Its own state rather than derived
   *  from `date_from`: a lock is a fact about a WEEK, and a hand-typed
   *  range of three months has no lock state to show. */
  /** P-11 B3 — a deep link may ask the grid to OPEN on people
   *  ("?enter=3,9" — the ticket page's Enter-hours door lands the
   *  office user on the grid at the job's week with the crew
   *  preselected). Consumed on close, so Back does not reopen it;
   *  never copied into state (derived each render). */
  const enterIds = useMemo(() => {
    const raw = searchParams.get("enter");
    if (!raw) return [] as number[];
    return raw
      .split(",")
      .map((part) => Number(part))
      .filter((value) => Number.isInteger(value) && value > 0);
  }, [searchParams]);
  const [enterConsumed, setEnterConsumed] = useState(false);

  const [week, setWeekState] = useState<IsoWeek>(initialWeek);
  const setWeek = useCallback(
    (next: IsoWeek) => {
      setWeekState(next);
      const current = currentIsoWeek();
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev);
          if (next.isoYear === current.isoYear && next.isoWeek === current.isoWeek) {
            params.delete("week");
          } else {
            params.set("week", formatIsoWeek(next));
          }
          return params;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );
  const [weekStatus, setWeekStatus] = useState<WeekStatus | null>(null);
  // P-9 D3 — which weeks of the shown year hold saved hours.
  const [weeksWithHours, setWeeksWithHours] = useState<WeekWithHours[]>([]);
  const [lockBusy, setLockBusy] = useState(false);
  const closeWeekRef = useRef<ConfirmDialogHandle>(null);
  const reopenWeekRef = useRef<ConfirmDialogHandle>(null);

  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companiesResolved, setCompaniesResolved] = useState(!isSuperAdmin);
  const [company, setCompany] = useState<number | "">("");
  // Its own error state, not shared with the list's: a missing SELECTOR
  // blocks writes and needs a reload, a stale LIST fixes itself on the
  // next mutation.
  const [companyLoadError, setCompanyLoadError] = useState("");

  const [entries, setEntries] = useState<TimeEntry[]>([]);
  const [entryCount, setEntryCount] = useState(0);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [summary, setSummary] = useState<TimesheetSummary | null>(null);
  const [loadError, setLoadError] = useState("");
  const [exportBusy, setExportBusy] = useState(false);

  const [filters, setFilters] = useState<EntryFilterState>(() =>
    weekFilters(initialWeek),
  );
  const [employees, setEmployees] = useState<TimesheetEmployee[]>([]);
  const [hourTypes, setHourTypes] = useState<HourType[]>([]);
  const [buildings, setBuildings] = useState<BuildingAdmin[]>([]);

  const [weekModalOpen, setWeekModalOpen] = useState(false);
  /** P-11 B1 — who the grid opens on (the week card's Edit). */
  const [weekModalPreselect, setWeekModalPreselect] = useState<number[]>([]);
  /** P-13 O4 — the one line the grid shows when it was opened FROM
   *  Start here ("These N have no hours in week W yet."). Captured at
   *  the click, so a refresh while the dialog is open cannot rewrite
   *  it; empty for every other door into the dialog. */
  const [weekModalNote, setWeekModalNote] = useState("");

  // The inline table editor. `drafts` holds ONLY the rows the operator
  // has touched, so "what changed" is the map itself and no diffing of
  // the whole page is needed.
  const [editing, setEditing] = useState(false);
  const [periodToggle, setPeriodToggle] = useState(false);
  const [drafts, setDrafts] = useState<Record<number, EntryDraft>>({});
  const [saveBusy, setSaveBusy] = useState(false);
  const [saveError, setSaveError] = useState("");

  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
  // W-T3 §1 — ERRORS AT THE ACTION. All four mutations here reported
  // into `loadError`, the banner that also carries "this page could not
  // load", and the three confirms CLOSED their dialog on the way. The
  // operator watched the dialog vanish and the row stay, with the
  // reason in a banner that reads like a page-level fault.
  //
  // Now each confirm keeps its dialog OPEN and names the refusal inside
  // it (`ConfirmDialog.body` is a ReactNode, so this needs no change to
  // that shared component), and the export names its failure at the
  // toolbar. `loadError` keeps the loads.
  const [confirmError, setConfirmError] = useState("");
  const [exportError, setExportError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<TimeEntry | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  // P-12 B4 — the after-save banner (rule 4) and the saved people's
  // ten-second tint on the week card.
  const hoursDone = useDoneBanner("hours-admin");
  const [savedHighlight, setSavedHighlight] = useState<number[]>([]);
  useEffect(() => {
    if (savedHighlight.length === 0) return;
    const timer = window.setTimeout(() => setSavedHighlight([]), HIGHLIGHT_MS);
    return () => window.clearTimeout(timer);
  }, [savedHighlight]);

  const showCompanySelector = isSuperAdmin && companies.length > 1;
  /** True while a SUPER_ADMIN's company is still unknown. Every read
   *  waits on it — see the class docstring. */
  const companyPending =
    isSuperAdmin &&
    (!companiesResolved || (companies.length > 1 && company === ""));

  useEffect(() => {
    if (!isSuperAdmin) return;
    let cancelled = false;
    listAllCompanies({ is_active: "true" })
      .then((response) => {
        if (cancelled) return;
        setCompanies(response);
        if (response.length > 1) {
          // P-12 §D.24.2 — the SESSION's shared Finance-pages choice
          // wins; the page's old per-browser key is read as a fallback
          // so an existing operator's pick survives the switch once.
          const sessionStored = readScopeCompany();
          const legacy = Number(
            window.localStorage.getItem(HOURS_COMPANY_STORAGE_KEY),
          );
          const remembered =
            sessionStored != null && response.some((c) => c.id === sessionStored)
              ? sessionStored
              : response.some((c) => c.id === legacy)
                ? legacy
                : null;
          const primary = response.reduce(
            (lowest, c) => (c.id < lowest.id ? c : lowest),
            response[0],
          );
          setCompany((current) =>
            current === "" ? (remembered ?? primary.id) : current,
          );
        }
        setCompaniesResolved(true);
      })
      .catch(() => {
        // Fail loudly. A silently absent selector leaves a SUPER_ADMIN on
        // a multi-tenant deployment with no control and then a
        // `timesheet_company_required` 400 they cannot act on.
        if (cancelled) return;
        setCompanyLoadError(t("catalog.company_load_failed"));
        setCompaniesResolved(true);
      });
    return () => {
      cancelled = true;
    };
  }, [isSuperAdmin, t]);

  // The filter pickers. Reloaded when the company changes so a
  // SUPER_ADMIN switching tenants does not keep the previous one's
  // employees in the dropdown.
  useEffect(() => {
    if (companyPending) return;
    let cancelled = false;
    Promise.all([
      // The module's OWN picker endpoint, narrowed to the selected
      // company. `/api/employees/` takes no `?company=` and returns
      // none either, so for a SUPER_ADMIN it mixes several providers'
      // people into one dropdown where every wrong pick 400s.
      listTimesheetEmployees(company),
      listHourTypes(company === "" ? {} : { company }),
      listAllBuildings({
        is_active: "true",
        ...(company === "" ? {} : { company }),
      }),
    ])
      .then(([employeeRows, types, buildingRows]) => {
        if (cancelled) return;
        setEmployees(employeeRows);
        setHourTypes(types);
        setBuildings(buildingRows);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(getApiError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [company, companyPending]);

  /**
   * Change a filter AND return to page 1.
   *
   * The page reset belongs to the EVENT, not to an effect watching the
   * filters: an effect doing `setPage(1)` is a synchronous setState in
   * an effect body (CLAUDE.md; `react-hooks/set-state-in-effect`). It
   * also has to happen at all — a narrower filter left on page 3 of the
   * old result set renders as "no results", which reads as a broken
   * filter rather than a stale page number.
   */
  const patchFilters = useCallback((patch: Partial<EntryFilterState>) => {
    setFilters((prev) => ({ ...prev, ...patch }));
    setPage(1);
    // A filter change replaces the rows under the editor, so pending
    // drafts would be pointing at rows that are no longer on screen.
    setEditing(false);
    setDrafts({});
  }, []);

  /**
   * W-HR1 §2 — moving to another week moves the table with it.
   *
   * The week bar is the period control; `date_from`/`date_to` are what
   * it resolves to and stay hand-editable. Done in the HANDLER, never
   * an effect watching `week`: a synchronous setState in an effect body
   * is banned (CLAUDE.md §3, `react-hooks/set-state-in-effect`).
   */
  const goToWeek = useCallback(
    (next: IsoWeek) => {
      const days = isoWeekDays(next);
      setWeek(next);
      setFilters((prev) => ({
        ...prev,
        date_from: toDateString(days[0]),
        date_to: toDateString(days[6]),
      }));
      setPage(1);
      setEditing(false);
      setDrafts({});
    },
    // `setWeek` is the URL-writing wrapper above, not a bare state
    // setter, so it is a real dependency.
    [setWeek],
  );

  const queryFilters: TimeEntryFilters = useMemo(
    () => ({
      company,
      employee: filters.employee,
      hour_type: filters.hour_type,
      building: filters.building,
      source_type: filters.source_type,
      date_from: filters.date_from,
      date_to: filters.date_to,
    }),
    [company, filters],
  );

  // Derived `loading` — see `MyHoursPage` for why it is not stored in
  // state and set from the effect body.
  const fetchKey = `${JSON.stringify(queryFilters)}|${page}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading =
    !agreedView && (companyPending || loadedKey !== fetchKey);

  useEffect(() => {
    if (agreedView || companyPending) return;
    let cancelled = false;
    // The table and its footer totals come from the SAME filter object,
    // so the numbers always describe the rows on screen.
    Promise.all([
      listTimeEntries({ ...queryFilters, page }),
      fetchTimesheetSummary(queryFilters),
    ])
      .then(([entryPage, summaryPayload]) => {
        if (cancelled) return;
        setEntries(entryPage.results);
        setEntryCount(entryPage.count);
        setHasNext(Boolean(entryPage.next));
        setSummary(summaryPayload);
        setLoadError("");
        setLoadedKey(fetchKey);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(getApiError(err));
        setLoadedKey(fetchKey);
      });
    return () => {
      cancelled = true;
    };
  }, [agreedView, queryFilters, page, fetchKey, companyPending]);

  /** P-9 D3 — WHERE THE HOURS ARE: the year's weeks that hold saved
   *  hours, for the strip on the week bar and the empty week's
   *  sentence. Keyed on `entries` as well as the year, so it is re-read
   *  whenever the table is (a save, a delete, a week change) and a week
   *  is marked the moment its hours land. Non-fatal: without it the
   *  strip shows no marks and the sentence names no week. */
  useEffect(() => {
    if (agreedView || companyPending) return;
    let cancelled = false;
    listWeeksWithHours({ iso_year: week.isoYear, company })
      .then((data) => {
        if (!cancelled) setWeeksWithHours(data.weeks);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [agreedView, companyPending, company, week.isoYear, entries]);
  const lastSavedWeek = lastSavedWeekBefore(weeksWithHours, week);
  /** True while the table shows exactly the week on the bar and nothing
   *  narrower — the state in which "no hours saved for week N" is the
   *  truth rather than "no hours match these filters". */
  /** Sprint 178 §4a — the sources the source column may be corrected to.
   *
   *  The SAME endpoint the week-setup picker uses, so the two paths
   *  cannot disagree about what a valid source is. Non-fatal: an
   *  unreachable picker must not stop somebody fixing a row's hours. */
  const [sourceOptions, setSourceOptions] = useState<HourSourceOption[]>([]);
  useEffect(() => {
    let cancelled = false;
    listHourSources()
      .then((options) => {
        if (!cancelled) setSourceOptions(options);
      })
      .catch(() => {
        /* non-fatal: the rest of the row is still editable */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  /** P-11 B1 — the week card's own read: EVERY entry of the week on
   *  the bar (exhaustive pages, the Sprint 120 pattern), whatever the
   *  filters narrow the table below to. Keyed on `entries` like the
   *  weeks read, so a save or a delete refreshes it. Non-fatal. */
  const [weekCardEntries, setWeekCardEntries] = useState<TimeEntry[]>([]);
  useEffect(() => {
    if (agreedView || companyPending) return;
    let cancelled = false;
    (async () => {
      const all: TimeEntry[] = [];
      let cardPage = 1;
      for (;;) {
        const response = await listTimeEntries({
          company,
          iso_year: week.isoYear,
          iso_week: week.isoWeek,
          page: cardPage,
          page_size: 200,
        });
        all.push(...response.results);
        if (!response.next || cardPage >= 10) break;
        cardPage += 1;
      }
      if (!cancelled) setWeekCardEntries(all);
    })().catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [agreedView, companyPending, company, week, entries]);

  /** The card's rows: one per person with hours this week, standard
   *  hours and job hours apart, the job refs named. */
  const weekPeople = useMemo(() => {
    const byEmployee = new Map<
      number,
      {
        id: number;
        name: string;
        buildings: Set<string>;
        standard: number;
        jobs: number;
        jobRefs: Map<string, { label: string; hours: number }>;
      }
    >();
    for (const entry of weekCardEntries) {
      const bucket = byEmployee.get(entry.employee) ?? {
        id: entry.employee,
        name: entry.employee_name,
        buildings: new Set<string>(),
        standard: 0,
        jobs: 0,
        jobRefs: new Map<string, { label: string; hours: number }>(),
      };
      if (entry.building_name) bucket.buildings.add(entry.building_name);
      const entryHours = Number(entry.hours) || 0;
      if (
        entry.source_type === "TICKET" ||
        entry.source_type === "EXTRA_WORK"
      ) {
        bucket.jobs += entryHours;
        const refKey = `${entry.source_type}:${entry.source_id ?? ""}`;
        const label = jobTitleFirst(
          hourSourceLabel(
            entry.source_type,
            entry.source_id ?? null,
            sourceOptions,
            t,
            t("hours_week_grid.no_source"),
          ),
        );
        const ref = bucket.jobRefs.get(refKey) ?? { label, hours: 0 };
        ref.hours += entryHours;
        bucket.jobRefs.set(refKey, ref);
      } else {
        bucket.standard += entryHours;
      }
      byEmployee.set(entry.employee, bucket);
    }
    return [...byEmployee.values()].sort((a, b) =>
      a.name.localeCompare(b.name),
    );
  }, [weekCardEntries, sourceOptions, t]);
  const weekCardTotal = weekPeople.reduce(
    (sum, person) => sum + person.standard + person.jobs,
    0,
  );

  // P-12 B2 — who has NO hours yet this week (drives Start here); the
  // printed total for the sentences.
  const missingPeople = useMemo(
    () => employees.filter((e) => !weekPeople.some((p) => p.id === e.id)),
    [employees, weekPeople],
  );
  const weekHoursLabel = weekCardTotal.toLocaleString(dateLocale, {
    maximumFractionDigits: 2,
  });

  /** P-13 O4 — Start here's button SAYS WHO it is for: at most four
   *  first names, then "and N more". Derived from the same
   *  `missingPeople` memo that preselects the dialog, so the button
   *  and the grid can never disagree about who is missing. */
  const startHereLabel = useMemo(() => {
    // P-15 (P-14's S4 finding) — two people who share a first name are
    // indistinguishable ("Ahmet, Ahmet"), so colliding entries print
    // their full name; and an email fallback prints whole, never a
    // whitespace-split of an address that has no spaces.
    const shown = missingPeople.slice(0, 4);
    const firsts = shown.map((p) =>
      p.full_name.trim() ? p.full_name.trim().split(/\s+/)[0] : p.email,
    );
    const names = shown.map((p, index) => {
      const first = firsts[index];
      const collides =
        firsts.filter((other) => other === first).length > 1;
      return collides && p.full_name.trim() ? p.full_name.trim() : first;
    });
    if (missingPeople.length > 4) {
      return t("hours_admin.enter_for_names_more", {
        names: names.join(", "),
        count: missingPeople.length - 4,
      });
    }
    const joined =
      names.length > 1
        ? `${names.slice(0, -1).join(", ")} ${t("hours_admin.names_and")} ${
            names[names.length - 1]
          }`
        : (names[0] ?? "");
    return t("hours_admin.enter_for_names", { names: joined });
  }, [missingPeople, t]);

  /** P-11 B1 — the "Earlier weeks" table: every week of the year with
   *  hours except the one on the bar, newest first. */
  const earlierWeeks = useMemo(
    () =>
      [...weeksWithHours]
        .filter(
          (row) =>
            !(row.iso_year === week.isoYear && row.iso_week === week.isoWeek),
        )
        .sort(
          (a, b) => b.iso_year - a.iso_year || b.iso_week - a.iso_week,
        ),
    [weeksWithHours, week],
  );
  const weekRangeLabel = useCallback(
    (isoYear: number, isoWeek: number) => {
      const days = isoWeekDays({ isoYear, isoWeek });
      const opts = { day: "numeric", month: "short" } as const;
      return `${days[0].toLocaleDateString(dateLocale, opts)} \u2013 ${days[6].toLocaleDateString(dateLocale, opts)}`;
    },
    [dateLocale],
  );

  const weekOnly = useMemo(() => {
    const base = weekFilters(week);
    return (Object.keys(base) as (keyof EntryFilterState)[]).every(
      (key) => (filters[key] ?? "") === (base[key] ?? ""),
    );
  }, [filters, week]);

  /**
   * W-HR1 §2 — is the week on screen closed?
   *
   * Its own read, on its own key: it depends on the WEEK and the
   * company, not on the entry filters, so narrowing to one employee
   * must not re-ask whether the week is locked. Non-fatal — the chip
   * falls back to "loading" and the entries table is unaffected.
   */
  const weekStatusKey = `${week.isoYear}-${week.isoWeek}|${company}`;
  const [weekStatusLoadedKey, setWeekStatusLoadedKey] = useState<string | null>(
    null,
  );
  useEffect(() => {
    if (agreedView || companyPending) return;
    let cancelled = false;
    fetchWeekStatus({
      iso_year: week.isoYear,
      iso_week: week.isoWeek,
      company,
    })
      .then((status) => {
        if (cancelled) return;
        setWeekStatus(status);
        setWeekStatusLoadedKey(weekStatusKey);
      })
      .catch(() => {
        if (cancelled) return;
        setWeekStatus(null);
        setWeekStatusLoadedKey(weekStatusKey);
      });
    return () => {
      cancelled = true;
    };
  }, [agreedView, companyPending, week, company, weekStatusKey]);

  const weekRange = weekFilters(week);
  const periodOpen =
    periodToggle ||
    filters.date_from !== weekRange.date_from ||
    filters.date_to !== weekRange.date_to;
  const weekStatusLoading = weekStatusLoadedKey !== weekStatusKey;
  const weekClosed = weekStatus?.is_closed ?? false;

  /** Re-read the lock after acting on it. Never throws: the write has
   *  already committed, and a failed re-read must not turn a closed
   *  week into a form error. */
  const refreshWeekStatus = useCallback(async () => {
    try {
      setWeekStatus(
        await fetchWeekStatus({
          iso_year: week.isoYear,
          iso_week: week.isoWeek,
          company,
        }),
      );
    } catch {
      setWeekStatus(null);
    }
  }, [week, company]);

  // Only ACTIVE hour types are offerable for a write — an archived one
  // is rejected server-side (`hour_type_archived`). The unfiltered list
  // still backs the FILTER dropdown, where an archived type is a
  // perfectly reasonable thing to search for.
  const activeHourTypes = useMemo(
    () => hourTypes.filter((hourType) => hourType.is_active),
    [hourTypes],
  );

  /**
   * Re-read the entries page and its totals after a mutation. NEVER
   * THROWS: the write already committed, so a failed re-read must not
   * turn a saved row into a form error or wedge a busy flag.
   *
   * Re-reads rather than merging locally, because a write can move a row
   * OUT of the current view entirely — a date edit past the filtered
   * range, or an hour-type change under an hour-type filter. A local
   * merge can drop a row but never bring one back.
   */
  const refreshEntries = useCallback(async () => {
    try {
      const [entryPage, summaryPayload] = await Promise.all([
        listTimeEntries({ ...queryFilters, page }),
        fetchTimesheetSummary(queryFilters),
      ]);
      setEntries(entryPage.results);
      setEntryCount(entryPage.count);
      setHasNext(Boolean(entryPage.next));
      setSummary(summaryPayload);
      setLoadError("");
    } catch {
      setLoadError(t("admin.refresh_after_save_failed"));
    }
  }, [queryFilters, page, t]);

  // ---- the inline editor -------------------------------------------

  /** The row's current state: the pending draft if it has one, the
   *  saved values otherwise. Read at the point of USE rather than
   *  seeded into state on entering edit mode — a draft per row for a
   *  page nobody edited is state that can go stale against a refresh. */
  const draftFor = (entry: TimeEntry): EntryDraft =>
    drafts[entry.id] ?? draftOf(entry);

  const patchDraft = (entry: TimeEntry, patch: Partial<EntryDraft>) =>
    setDrafts((current) => ({
      ...current,
      [entry.id]: { ...(current[entry.id] ?? draftOf(entry)), ...patch },
    }));

  /** Only the rows whose draft actually DIFFERS from what is stored.
   *  Touching a field and putting it back is not a change, and sending
   *  it would re-snapshot the multiplier for nothing. */
  const changedEntries = entries.filter(
    (entry) =>
      entry.id in drafts && draftsDiffer(drafts[entry.id], draftOf(entry)),
  );

  function cancelEditing() {
    setEditing(false);
    setDrafts({});
    setSaveError("");
  }

  /**
   * Save every changed row, then leave edit mode.
   *
   * One PATCH per row, deliberately: `updateTimeEntry` is the normal
   * `TimeEntry` save path, so the serializer re-snapshots
   * `multiplier_snapshot` and re-derives `iso_year`/`iso_week` for each
   * one. The week-grid bulk endpoint cannot serve this — it is keyed on
   * (employee, hour type, building, date) and carries no note, so it
   * can neither move a row's date nor edit its text.
   *
   * `allSettled`, not `all`: a row the server refuses (a closed week
   * reached while the page was open) must not discard the rows that
   * saved. The ones that failed keep their drafts and their error, and
   * edit mode stays open on exactly those.
   */
  async function saveAll() {
    if (changedEntries.length === 0) {
      cancelEditing();
      return;
    }
    setSaveBusy(true);
    setSaveError("");
    const results = await Promise.allSettled(
      changedEntries.map((entry) => {
        const draft = drafts[entry.id];
        return updateTimeEntry(entry.id, {
          date: draft.date,
          hour_type: Number(draft.hour_type),
          hours: draft.hours.trim(),
          building: draft.building === "" ? null : Number(draft.building),
          note: draft.note.trim(),
          // Sprint 178 §4a — the source, corrected from the edit path.
          // `source_type` / `source_id` were already writable on this
          // serializer; nothing on any screen had ever sent them.
          ...decodeSource(draft.source),
        }).then(() => entry.id);
      }),
    );

    const failed: number[] = [];
    let firstError = "";
    results.forEach((result, index) => {
      if (result.status === "rejected") {
        failed.push(changedEntries[index].id);
        // The server's message VERBATIM — including `week_closed`,
        // which names the week and says what to do about it.
        if (!firstError) firstError = getApiError(result.reason);
      }
    });

    const saved = results.length - failed.length;
    await refreshEntries();

    if (failed.length === 0) {
      setDrafts({});
      setEditing(false);
      pushToast({
        variant: "success",
        title: t("hours_admin.edit_saved", { count: saved }),
      });
    } else {
      setDrafts((current) => {
        const kept: Record<number, EntryDraft> = {};
        for (const id of failed) if (current[id]) kept[id] = current[id];
        return kept;
      });
      setSaveError(
        t("hours_admin.edit_partly_failed", {
          saved,
          failed: failed.length,
          detail: firstError,
        }),
      );
    }
    setSaveBusy(false);
  }

  // ---- delete -------------------------------------------------------

  function openDeleteEntry(entry: TimeEntry) {
    setDeleteTarget(entry);
    setConfirmError("");
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
      await refreshEntries();
      deleteDialogRef.current?.close();
      setDeleteTarget(null);
    } catch (err) {
      setConfirmError(getApiError(err));
    } finally {
      setDeleteBusy(false);
    }
  }

  // ---- the week lock ------------------------------------------------

  async function handleConfirmCloseWeek() {
    setLockBusy(true);
    try {
      await closeWeek({
        iso_year: week.isoYear,
        iso_week: week.isoWeek,
        company,
      });
      await refreshWeekStatus();
      await refreshEntries();
      pushToast({
        variant: "success",
        title: t("weeks.close_done", { week: formatIsoWeek(week) }),
      });
      // Closed on SUCCESS only. In `finally` it closed on failure too,
      // taking the reason off screen with it.
      closeWeekRef.current?.close();
    } catch (err) {
      setConfirmError(getApiError(err));
    } finally {
      setLockBusy(false);
    }
  }

  async function handleConfirmReopenWeek() {
    setLockBusy(true);
    try {
      await reopenWeek({
        iso_year: week.isoYear,
        iso_week: week.isoWeek,
        company,
      });
      await refreshWeekStatus();
      await refreshEntries();
      pushToast({
        variant: "success",
        title: t("weeks.reopen_done", { week: formatIsoWeek(week) }),
      });
      // Closed on SUCCESS only. In `finally` it closed on failure too,
      // taking the reason off screen with it.
      reopenWeekRef.current?.close();
    } catch (err) {
      setConfirmError(getApiError(err));
    } finally {
      setLockBusy(false);
    }
  }

  const handleExport = useCallback(async () => {
    setExportBusy(true);
    try {
      await downloadTimesheetSummaryCsv(queryFilters);
    } catch (err) {
      setExportError(getApiError(err));
      pushToast({ variant: "error", title: t("hours_admin.export_failed") });
    } finally {
      setExportBusy(false);
    }
  }, [queryFilters, pushToast, t]);

  /** W-HR1 §2 — the week's totals, as the TABLE'S FOOTER.
   *
   *  They were four tiles above the table. Tiles are for figures that
   *  are ABOUT something else on the page; these are the sum of the
   *  column they sat above, which is a totals row. Same summary
   *  payload, same filter object as the rows, so they always describe
   *  what is on screen. */

  // P-14 A1 — the P-13 `?tab=schedule` deep link lands on the Agreed
  // tab's real address (below every hook; a redirect is a render).
  if (agreedView && !location.pathname.includes("/agreed")) {
    return <Navigate to="/admin/hours/agreed" replace />;
  }

  // Sprint 164 — the wrapper used to carry a class with no rule behind
  // it, the same hole the gate found on MyHoursPage last sprint. A JS
  // comment, not a JSX one: a JSX comment cannot sit between `return (`
  // and the element, which is a mistake I have now made twice.
  return (
    /* W5 fix 5 — a named root so this page's title spacing can be fixed
       without touching the global `.page-title` every page shares. */
    <div className="hours-admin-page">
      <PageHeader
        /* P-14 A1 — ONE page title ("Hours"); each tab's own section
           title names the tab (the P-13 report flagged the doubled
           header on the schedule view). */
        title={t("hours_admin.title")}
        subtitle={agreedView ? undefined : t("hours_admin.subtitle")}
        actions={
          /* P-12 §D.24.2 — the company, top right; the choice is
             shared with the other Finance pages through the session.
             Enter hours moved onto the week card (B2): the card is the
             week's home, the header only says whose hours these are. */
          showCompanySelector ? (
            <CompanyScopeSelect
              companies={companies}
              companyId={company}
              onChange={(id) => {
                setCompany(id);
                setPage(1);
                setEditing(false);
                setDrafts({});
                rememberScopeCompany(id);
              }}
              testId="hours-company-selector"
            />
          ) : undefined
        }
      />

      {/* P-14 A1 — the People-style tab strip; the URL is the state. */}
      <div
        className="customer-tabs"
        role="tablist"
        aria-label={t("hours_admin.title")}
        style={{ marginBottom: 16 }}
        data-testid="hours-tabs"
      >
        {HOURS_TABS.map((spec) => (
          <Link
            key={spec.key}
            to={spec.path}
            role="tab"
            aria-selected={spec.key === activeTab}
            className={`customer-tab${spec.key === activeTab ? " active" : ""}`}
            data-testid={`hours-tab-${spec.key}`}
          >
            {t(spec.labelKey)}
          </Link>
        ))}
      </div>

      {companyLoadError && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {companyLoadError}
        </div>
      )}

      {agreedView && (
        <>
          {/* P-13 §D.24 rule 8 — what THIS tab can do. Every line
              verified against `timesheets/fill.py` and the
              `ContractHours` model before it was written. */}
          <HowThisWorks
            pageKey="hours-agreed"
            testId="hours-agreed-how"
            lines={[
              t("contract_hours.how_1"),
              t("contract_hours.how_2"),
              t("contract_hours.how_3"),
            ]}
          />
          {/* P-14 A1 — the road, as ONE teach sentence. */}
          <p
            className="muted small"
            style={{ margin: "0 0 12px" }}
            data-testid="hours-agreed-road"
          >
            {t("contract_hours.road_teach")}
          </p>
          <ContractHoursTab
            companyId={company}
            buildings={buildings}
            employees={employees}
            hourTypes={hourTypes}
          />
        </>
      )}

      {!agreedView && (
        <>
          {/* P-13 §D.24 rule 8 — what this page CAN do. */}
          <HowThisWorks
            pageKey="hours"
            testId="hours-how"
            lines={[
              t("hours_admin.how_1"),
              t("hours_admin.how_2"),
              t("hours_admin.how_3"),
              t("hours_admin.how_4"),
            ]}
          />

          {/* P-12 §D.24 rule 4 — what just happened, what did not,
              and the one next step; survives one reload. */}
          {hoursDone.done && (
            <DoneBanner
              done={hoursDone.done}
              onDismiss={hoursDone.dismiss}
              testId="hours-done"
            />
          )}

          {/* P-12 §D.24 rule 2 — the ONE thing waiting: people whose
              week is still empty, else (everyone in) the close. Hidden
              when the week is closed or nothing waits.
              P-13 J — and while the Done banner is up: one voice. */}
          {!hoursDone.done &&
            !companyPending &&
            !loading &&
            !weekStatusLoading &&
            !weekClosed &&
            employees.length > 0 &&
            (missingPeople.length > 0 ? (
              <StartHere
                testId="hours-start-here"
                action={{
                  /* P-13 O4 — this button and the week card's both said
                     "Enter hours"; this one now SAYS WHO it opens on. */
                  label: startHereLabel,
                  onClick: () => {
                    setWeekModalPreselect(missingPeople.map((e) => e.id));
                    setWeekModalNote(
                      t("hours_admin.preselect_note", {
                        count: missingPeople.length,
                        week: week.isoWeek,
                      }),
                    );
                    setWeekModalOpen(true);
                  },
                }}
              >
                {weekPeople.length === 0
                  ? t("hours_admin.start_here_empty", {
                      week: week.isoWeek,
                      count: missingPeople.length,
                    })
                  : t("hours_admin.start_here_missing", {
                      hours: weekHoursLabel,
                      people: weekPeople.length,
                      count: missingPeople.length,
                    })}
              </StartHere>
            ) : weekPeople.length > 0 ? (
              <StartHere
                testId="hours-start-here"
                action={{
                  label: t("weeks.close_button"),
                  onClick: () => {
                    setConfirmError("");
                    closeWeekRef.current?.open();
                  },
                }}
              >
                {t("hours_admin.start_here_close", {
                  hours: weekHoursLabel,
                  people: weekPeople.length,
                })}
              </StartHere>
            ) : null)}

          {/* P-12 B2/B3 — the week card is the week's HOME: the
              stepper, the Open→Closed road, the teach line, Enter
              hours and Close/Reopen all sit on the card, above the
              per-person rows they act on. (The separate week bar and
              the header button folded in here.) */}
          <div
            className="card"
            data-testid="hours-week-card"
            style={{ marginBottom: 16, padding: "14px 16px" }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                flexWrap: "wrap",
                gap: 10,
                marginBottom: 10,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm icon-only"
                  data-testid="hours-week-prev"
                  aria-label={t("contract_hours.prev_week")}
                  title={t("contract_hours.prev_week")}
                  onClick={() => goToWeek(shiftIsoWeek(week, -1))}
                >
                  <ChevronLeft size={15} strokeWidth={2.2} />
                </button>
                <strong data-testid="hours-week-label">
                  {formatIsoWeek(week)}
                </strong>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm icon-only"
                  data-testid="hours-week-next"
                  aria-label={t("contract_hours.next_week")}
                  title={t("contract_hours.next_week")}
                  onClick={() => goToWeek(shiftIsoWeek(week, 1))}
                >
                  <ChevronRight size={15} strokeWidth={2.2} />
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  data-testid="hours-week-this"
                  onClick={() => goToWeek(currentIsoWeek())}
                >
                  {t("my_hours.this_week")}
                </button>
              </div>

              {/* ONE chip. The state, said once. */}
              <span
                className={
                  weekClosed ? "badge badge-closed" : "badge badge-approved"
                }
                data-testid="hours-week-status"
                data-closed={weekClosed ? "true" : "false"}
              >
                {weekStatusLoading ? (
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
              {weekClosed && weekStatus?.lock && (
                <span className="muted small" data-testid="hours-week-closed-by">
                  {t("weeks.closed_by", {
                    name: weekStatus.lock.closed_by_name,
                    when: new Date(weekStatus.lock.closed_at).toLocaleString(
                      dateLocale,
                      {
                        day: "2-digit",
                        month: "short",
                        year: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      },
                    ),
                  })}
                </span>
              )}

              {/* P-14 A2 — the two buttons share ONE baseline; the
                  rule-8 pre-read is ONE line under the pair (it used
                  to sit under Enter hours alone and pushed it up).
                  P-14 A4 — Enter hours is a normal secondary button
                  (the page's one primary door is Start here), and it
                  no longer greys out on every routine table refresh:
                  the only real block is having no active hour types. */}
              <div
                style={{
                  marginLeft: "auto",
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "flex-end",
                  gap: 4,
                }}
                className="hours-week-lock-actions"
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    flexWrap: "wrap",
                  }}
                >
                  {!editing && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      data-testid="hours-enter-week-button"
                      onClick={() => {
                        setWeekModalPreselect([]);
                        setWeekModalNote("");
                        setWeekModalOpen(true);
                      }}
                      disabled={activeHourTypes.length === 0}
                    >
                      {t("hours_admin.enter_week_button")}
                    </button>
                  )}
                  {weekClosed ? (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      data-testid="hours-week-reopen"
                      onClick={() => {
                        setConfirmError("");
                        reopenWeekRef.current?.open();
                      }}
                      disabled={weekStatusLoading || lockBusy || companyPending}
                    >
                      {t("weeks.reopen_button")}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      data-testid="hours-week-close"
                      onClick={() => {
                        setConfirmError("");
                        closeWeekRef.current?.open();
                      }}
                      disabled={weekStatusLoading || lockBusy || companyPending}
                    >
                      {t("weeks.close_button")}
                    </button>
                  )}
                </div>
                {!editing && !weekClosed && (
                  <WhatHappens testId="hours-week-what">
                    {t("hours_admin.what_week_buttons")}
                  </WhatHappens>
                )}
              </div>
            </div>

            {/* P-13 W6 — the "1 · Enter / 2 · Close" road is gone: the
                week's Open/Closed chip above already says the state.
                P-14 A4 — the closing consequence is said ONCE: this
                sentence carries the money fact; the lock mechanics are
                the one-liner under the buttons. */}
            <p
              className="muted small"
              style={{ margin: "0 0 12px" }}
              data-testid="hours-week-teach"
            >
              {t("hours_admin.week_teach")}
            </p>

            {weekPeople.length > 0 ? (
              <>
                <div
                  className="section-head-title"
                  data-testid="hours-week-card-total"
                >
                  {t("hours_week_grid.grand_total", {
                    hours: weekCardTotal.toLocaleString(dateLocale, {
                      maximumFractionDigits: 2,
                    }),
                    count: weekPeople.length,
                  })}
                </div>
                <p className="muted small" style={{ margin: "2px 0 10px" }}>
                  {t("hours_admin.week_card_sub")}
                </p>
                <div className="table-wrap">
                  <table className="data-table data-table-dense">
                    <thead>
                      <tr>
                        <th>{t("hours_admin.week_card_person")}</th>
                        <th style={{ textAlign: "right" }}>
                          {t("hours_admin.week_card_standard")}
                        </th>
                        <th>{t("hours_admin.week_card_jobs")}</th>
                        <th style={{ textAlign: "right" }}>
                          {t("hours_week_grid.week")}
                        </th>
                        <th aria-hidden="true" />
                      </tr>
                    </thead>
                    <tbody>
                      {weekPeople.map((person) => (
                        /* P-13 D (O3, §D.22 rule 9) — the whole row
                           opens the grid ON this person, exactly what
                           its Edit button does. */
                        <ClickableRow
                          key={person.id}
                          className={
                            savedHighlight.includes(person.id)
                              ? HIGHLIGHT_CLASS
                              : undefined
                          }
                          testId={`hours-week-card-row-${person.id}`}
                          inert={loading || activeHourTypes.length === 0}
                          onActivate={() => {
                            setWeekModalPreselect([person.id]);
                            setWeekModalNote("");
                            setWeekModalOpen(true);
                          }}
                        >
                          <td className="td-subject">
                            {person.name}
                            {person.buildings.size > 0 && (
                              <span className="hours-week-line-sub">
                                {[...person.buildings].join(", ")}
                              </span>
                            )}
                          </td>
                          <td style={{ textAlign: "right" }}>
                            {t("hours_week_grid.person_total", {
                              hours: person.standard.toLocaleString(dateLocale, {
                                maximumFractionDigits: 2,
                              }),
                            })}
                          </td>
                          <td data-testid={`hours-week-card-jobs-${person.id}`}>
                            {person.jobRefs.size === 0 ? (
                              <span className="muted">{"\u2014"}</span>
                            ) : (
                              <>
                                {t("hours_week_grid.person_total", {
                                  hours: person.jobs.toLocaleString(dateLocale, {
                                    maximumFractionDigits: 2,
                                  }),
                                })}
                                <span className="hours-week-line-sub">
                                  {[...person.jobRefs.values()]
                                    .map(
                                      (ref) =>
                                        `${ref.label} (${ref.hours.toLocaleString(
                                          dateLocale,
                                          { maximumFractionDigits: 2 },
                                        )} ${t("hours_admin.hour_unit")})`,
                                    )
                                    .join(" \u00b7 ")}
                                </span>
                              </>
                            )}
                          </td>
                          <td style={{ textAlign: "right", fontWeight: 700 }}>
                            {t("hours_week_grid.person_total", {
                              hours: (
                                person.standard + person.jobs
                              ).toLocaleString(dateLocale, {
                                maximumFractionDigits: 2,
                              }),
                            })}
                          </td>
                          <td style={{ textAlign: "right" }}>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              onClick={() => {
                                setWeekModalPreselect([person.id]);
                                setWeekModalNote("");
                                setWeekModalOpen(true);
                              }}
                              disabled={loading || activeHourTypes.length === 0}
                              data-testid={`hours-week-card-edit-${person.id}`}
                            >
                              {t("hours_admin.week_card_edit")}
                            </button>
                          </td>
                        </ClickableRow>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              /* P-12 §D.24 rule 5 — the empty week teaches how hours
                 get here. */
              <TeachEmpty
                testId="hours-week-empty"
                title={t("hours_admin.week_empty_title", { week: week.isoWeek })}
                body={t("hours_admin.week_empty_body")}
              />
            )}
          </div>

          {/* P-11 B1 — Earlier weeks: the year's weeks that hold
              hours, each with its people, its hours and its lock
              state; Open moves the bar there. Replaces the P-9 dot
              strip on this page — the same facts, readable. */}
          {earlierWeeks.length > 0 && (
            <div
              className="card"
              data-testid="hours-earlier-weeks"
              style={{ marginBottom: 16, padding: "14px 16px" }}
            >
              <div className="section-head-title">
                {t("hours_admin.earlier_weeks_title")}
              </div>
              <p className="muted small" style={{ margin: "2px 0 10px" }}>
                {t("hours_admin.earlier_weeks_sub")}
              </p>
              <div className="table-wrap">
                <table className="data-table data-table-dense">
                  <thead>
                    <tr>
                      <th>{t("hours_admin.earlier_weeks_week")}</th>
                      <th style={{ textAlign: "right" }}>
                        {t("hours_admin.earlier_weeks_people")}
                      </th>
                      <th style={{ textAlign: "right" }}>
                        {t("hours_admin.earlier_weeks_hours")}
                      </th>
                      <th>{t("hours_admin.earlier_weeks_status")}</th>
                      <th aria-hidden="true" />
                    </tr>
                  </thead>
                  <tbody>
                    {earlierWeeks.map((row) => (
                      /* P-13 D (O3, §D.22 rule 9) — the whole row opens
                         the week; the Open button stays for the eye. */
                      <ClickableRow
                        key={`${row.iso_year}-${row.iso_week}`}
                        testId={`hours-earlier-week-${row.iso_year}-${row.iso_week}`}
                        onActivate={() =>
                          goToWeek({
                            isoYear: row.iso_year,
                            isoWeek: row.iso_week,
                          })
                        }
                      >
                        <td className="td-subject">
                          {t("hours_admin.earlier_weeks_label", {
                            week: row.iso_week,
                          })}
                          <span className="hours-week-line-sub">
                            {weekRangeLabel(row.iso_year, row.iso_week)}
                          </span>
                        </td>
                        <td style={{ textAlign: "right" }}>{row.people}</td>
                        <td style={{ textAlign: "right" }}>
                          {t("hours_week_grid.person_total", {
                            hours: formatHours(row.hours, dateLocale),
                          })}
                        </td>
                        <td>
                          <span
                            className={
                              row.is_closed
                                ? "badge badge-closed"
                                : "badge badge-approved"
                            }
                          >
                            {row.is_closed
                              ? t("weeks.status_closed")
                              : t("weeks.status_open")}
                          </span>
                          {row.is_closed && row.closed_by_name && (
                            <span
                              className="muted small"
                              style={{ marginLeft: 8 }}
                            >
                              {t("weeks.closed_by", {
                                name: row.closed_by_name,
                                when: row.closed_at
                                  ? new Date(row.closed_at).toLocaleDateString(
                                      dateLocale,
                                      { day: "2-digit", month: "short" },
                                    )
                                  : "",
                              })}
                            </span>
                          )}
                        </td>
                        <td style={{ textAlign: "right" }}>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            onClick={() =>
                              goToWeek({
                                isoYear: row.iso_year,
                                isoWeek: row.iso_week,
                              })
                            }
                            data-testid={`hours-earlier-week-open-${row.iso_year}-${row.iso_week}`}
                          >
                            {t("hours_admin.earlier_weeks_open")}
                          </button>
                        </td>
                      </ClickableRow>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Load failures stay OUTSIDE the fold: an error inside a
              closed <details> is an error nobody sees. */}
          {loadError && (
            <div
              className="alert-error"
              role="alert"
              style={{ marginBottom: 16 }}
            >
              {loadError}
            </div>
          )}

          {/* P-13 W6 — the OLD per-entry log, folded away. The week
              card above is the page; the raw lines are the receipt,
              behind one door at the bottom. Filters, edit mode,
              pagination and the empty states all live inside. */}
          <details className="form-fold" data-testid="hours-all-entries">
            <summary
              className="form-fold-summary"
              data-testid="hours-all-entries-summary"
            >
              {/* P-14 A4 — with "Other period" on, the fold names the
                  ACTIVE period, not the week bar's week: the rows
                  inside describe the range, and the summary must not
                  claim a week they no longer match. */}
              {filters.date_from !== weekRange.date_from ||
              filters.date_to !== weekRange.date_to
                ? t("hours_admin.all_entries_summary_period", {
                    from: formatDate(filters.date_from, dateLocale),
                    to: formatDate(filters.date_to, dateLocale),
                    count: entryCount,
                  })
                : t("hours_admin.all_entries_summary", {
                    week: week.isoWeek,
                    count: entryCount,
                  })}
            </summary>

          {/* W-HR1 §2 — the filter row WRAPS instead of clipping.

              It was `.hours-filter-line`: `flex-wrap: nowrap` with
              `overflow-x: auto`, so at 1366 the "Tot" field ended 121px
              past the card's right edge and "Filters wissen" 223px past
              it — both reachable only by scrolling a bar nothing said
              was scrollable. This is `.filter-bar`, the house filter
              shape every other admin list uses (and the Schedule view
              behind `?tab=schedule`): it wraps to a second line and
              every control is on screen at every width. */}
          <div
            className="card filter-bar"
            data-testid="hours-filters"
            style={{ marginBottom: 16, borderBottom: "1px solid var(--border)" }}
          >
            {/* The four shared pickers. `HoursFilterRow` is now this
                page's only caller (the Overview tab that shared it is
                gone), and it moved to the `.filter-field` shape with
                the row around it. */}
            <HoursFilterRow
              values={{
                employee: filters.employee,
                hour_type: filters.hour_type,
                building: filters.building,
                source_type: filters.source_type,
              }}
              onChange={patchFilters}
              employees={employees}
              hourTypes={hourTypes}
              buildings={buildings}
              idPrefix="hours"
            />

            {/* Van / Tot: what the week bar resolved to, and the only
                way to ask for a range that is not one week. FE-7
                (§D.6.4): folded — the week bar owns the period; the
                pair unfolds on request or when a range is in force. */}
            {periodOpen && (
            <>
            <div className="filter-field">
              <span className="filter-label">
                {t("hours_admin.filter_date_from")}
              </span>
              <input
                id="hours-filter-from"
                className="filter-control"
                type="date"
                value={filters.date_from}
                onChange={(event) =>
                  patchFilters({ date_from: event.target.value })
                }
                data-testid="hours-filter-date-from"
              />
            </div>

            <div className="filter-field">
              <span className="filter-label">
                {t("hours_admin.filter_date_to")}
              </span>
              <input
                id="hours-filter-to"
                className="filter-control"
                type="date"
                value={filters.date_to}
                onChange={(event) =>
                  patchFilters({ date_to: event.target.value })
                }
                data-testid="hours-filter-date-to"
              />
            </div>
            </>
            )}

            <div className="filter-actions">
              {/* P-11 B1 — the period toggle moved into the More menu
                  beside Export CSV; the date inputs still unfold here
                  when it is on. */}
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                data-testid="hours-filters-reset"
                onClick={() => {
                  // Back to the week on the bar, not to "everything
                  // ever": the bar is the period control, and clearing
                  // the filters must not silently widen the table to
                  // every hour the company has ever filed.
                  setFilters(weekFilters(week));
                  setPage(1);
                  setPeriodToggle(false);
                  cancelEditing();
                }}
              >
                {t("hours_admin.filter_reset")}
              </button>
            </div>
          </div>

          {loading ? (
            <div
              className="card skeleton-table"
              aria-hidden="true"
              data-testid="hours-entries-skeleton"
            >
              {[0, 1, 2, 3, 4, 5].map((row) => (
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
            <div className="card" data-testid="hours-entries-list">
              {/* The Edit toggle. Sprint 155 §4's rule holds — nothing
                  on this table is directly editable; the operator asks
                  for edit mode first, and only then do the cells become
                  inputs and the row actions appear. What is new is that
                  leaving it is ONE Save for the whole table rather than
                  a modal per row. */}
              {/* P-13 W6 — no title line in here: the fold's summary
                  already names this ("All entries for week N"), and
                  the teach sentence lives on the week card, once. */}
              <div className="section-head" style={{ padding: "14px 16px 0" }}>
                <div>
                  <div className="section-head-sub">
                    {t("hours_admin.pagination_summary", {
                      shown: entries.length,
                      total: entryCount,
                    })}
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {editing ? (
                    <>
                      {/* Sprint 170 §2 — say what edit mode IS. The
                          table looks similar either way at a glance,
                          and the operator arrived here expecting row
                          selection. */}
                      <span
                        className="muted small"
                        data-testid="hours-edit-hint"
                      >
                        {t("hours_admin.edit_hint")}
                      </span>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={cancelEditing}
                        disabled={saveBusy}
                        data-testid="hours-edit-cancel"
                      >
                        {t("cancel")}
                      </button>
                      <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        onClick={() => void saveAll()}
                        // Sprint 170 §2 — DISABLED when there is
                        // nothing to save.
                        //
                        // Reproduced first: Edit already turns all 25
                        // rows into 125 inputs, typing 5.50 moves the
                        // counter 0 -> 1, Save posts cleanly and the
                        // value survives a reload. The mechanism was
                        // never broken. What was broken is that Save
                        // sat ENABLED reading "Alles bewaren (0)", so
                        // an operator who pressed it before changing
                        // anything got no request, no toast and no
                        // change - which is indistinguishable from a
                        // button that does not work, and teaches them
                        // not to trust it.
                        disabled={saveBusy || changedEntries.length === 0}
                        data-testid="hours-edit-save-all"
                      >
                        {saveBusy
                          ? t("admin_form.saving")
                          : changedEntries.length === 0
                            ? t("hours_admin.save_all_none")
                            : t("hours_admin.save_all", {
                                count: changedEntries.length,
                              })}
                      </button>
                    </>
                  ) : (
                    <>
                      {/* P-11 B1 — Export CSV and the "Other period"
                          fold live behind ONE More menu: two quiet
                          verbs, one door. */}
                      <OverflowMenu
                        label={t("hours_admin.more_menu")}
                        testIdPrefix="hours-more"
                        items={[
                          {
                            key: "export",
                            label: exportBusy
                              ? t("hours_admin.export_busy")
                              : t("hours_admin.export_csv"),
                            onClick: () => void handleExport(),
                            disabled: exportBusy || loading,
                          },
                          {
                            key: "period",
                            label: periodOpen
                              ? t("hours_admin.period_toggle_close")
                              : t("hours_admin.period_toggle_open"),
                            onClick: () => {
                              if (periodOpen) {
                                setPeriodToggle(false);
                                setFilters(weekFilters(week));
                              } else {
                                setPeriodToggle(true);
                              }
                            },
                            pressed: periodOpen,
                          },
                        ]}
                      />
                      {exportError && (
                        <span
                          className="alert-error"
                          role="alert"
                          data-testid="hours-export-error"
                        >
                          {exportError}
                        </span>
                      )}
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => setEditing(true)}
                        disabled={entries.length === 0}
                        data-testid="hours-edit-toggle"
                      >
                        {t("hours_admin.edit_button")}
                      </button>
                    </>
                  )}
                </div>
              </div>

              {saveError && (
                <div
                  className="alert-error"
                  role="alert"
                  style={{ margin: "12px 16px 0" }}
                  data-testid="hours-edit-error"
                >
                  {saveError}
                </div>
              )}

              {/* W-HR1 §2 — THE 420px CAP IS GONE.

                  The table was wrapped in `BoundedList size="lg"`,
                  which put a 420px scroll window over a 25-row page and
                  sliced whichever row happened to land on the boundary
                  in half — a page inside a page, with a half-row at the
                  seam that reads as a rendering fault.

                  It still respects CLAUDE.md #8: that rule asks a
                  server-collection list to be "scrollable, PAGINATED,
                  or explicitly capped", and this one is paginated for
                  real, off the endpoint's own `next`/`previous`
                  (`StandardResultsSetPagination`, 25 a page) with the
                  prev/next buttons below. A page of 25 rows is the
                  bound. Nesting a second, smaller bound inside it was
                  belt and braces that cut the belt.

                  The empty state moves out of the wrapper and under the
                  table, where the same copy renders. */}
              <div className="table-wrap">
                {/* P-13 W6 — SIX read columns: Date · Person · Where /
                    on what · Type · Hours · Note. Week is the fold's
                    summary; the source folded into the Where cell (a
                    job ref for job lines, the building otherwise); the
                    Hours × factor column went with the log's ceremony —
                    its TOTAL stays in the footer, where pay is read. */}
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{t("hours_admin.col_date")}</th>
                      <th>{t("hours_admin.col_employee")}</th>
                      <th>{t("hours_admin.col_where")}</th>
                      <th>{t("hours_admin.col_hour_type")}</th>
                      <th>{t("hours_admin.col_hours")}</th>
                      <th>{t("hours_admin.col_note")}</th>
                      {/* The actions column EXISTS only inside edit
                          mode, so the read view keeps exactly the
                          geometry it had — the same rule the building
                          relation cards follow. */}
                      {editing && <th>{t("hours_admin.col_actions")}</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((entry) => {
                      const draft = draftFor(entry);
                      // A locked row stays text even in edit mode: the
                      // server refuses the write either way, and
                      // offering an input that cannot be saved is the
                      // "control that lies" defect this sprint is
                      // about.
                      const cellsEditable = editing && !entry.is_locked;
                      return (
                        <tr
                          key={entry.id}
                          data-testid="hours-entry-row"
                          data-entry-id={entry.id}
                          data-locked={entry.is_locked ? "true" : "false"}
                        >
                          <td>
                            {cellsEditable ? (
                              <input
                                className="field-input hours-inline-input"
                                type="date"
                                value={draft.date}
                                onChange={(event) =>
                                  patchDraft(entry, {
                                    date: event.target.value,
                                  })
                                }
                                disabled={saveBusy}
                                aria-label={t("hours_admin.col_date")}
                                data-testid={`hours-inline-date-${entry.id}`}
                              />
                            ) : (
                              <>
                                {formatDate(entry.date, dateLocale)}
                                {/* P-13 W6 — the Week column is gone
                                    (the fold's summary names the week);
                                    the lock badge it carried rides on
                                    the date now. */}
                                {entry.is_locked && (
                                  <span
                                    className="badge badge-closed"
                                    style={{ marginLeft: 6 }}
                                  >
                                    {t("weeks.status_closed")}
                                  </span>
                                )}
                              </>
                            )}
                          </td>
                          <td>{entry.employee_name}</td>
                          {/* P-13 W6 — WHERE, or ON WHAT: one cell.
                              A job line (ticket / extra work) shows its
                              job ref; every other line shows the
                              building. In edit mode the cell stacks the
                              two editors it merged, so the source and
                              the building stay independently
                              correctable. */}
                          <td className="muted small">
                            {/* Sprint 178 §4a — EDITABLE now. Sprint 177
                                put the picker in the week SETUP only, so
                                a source could be chosen once and never
                                corrected. Hours get fixed a week later
                                all the time, and a source on the wrong
                                job is exactly that kind of thing.

                                Same option list as the setup dialog
                                (`listHourSources`), so the two paths
                                cannot drift on what a valid source is. */}
                            {cellsEditable ? (
                              <div style={{ display: "grid", gap: 4 }}>
                              <select
                                className="field-select"
                                value={draft.source}
                                onChange={(event) =>
                                  patchDraft(entry, {
                                    source: event.target.value,
                                  })
                                }
                                disabled={saveBusy}
                                aria-label={t("hours_admin.col_source")}
                                data-testid={`hours-entry-source-${entry.id}`}
                              >
                                <option value="">
                                  {t("my_hours.field_job_empty")}
                                </option>
                                {/* The row's CURRENT source stays
                                    offerable even if the job has since
                                    closed and left the picker: otherwise
                                    editing the hours of a finished job
                                    would silently retag it. */}
                                {draft.source &&
                                  !sourceOptions.some(
                                    (option) =>
                                      encodeSource(
                                        option.source_type,
                                        option.source_id,
                                      ) === draft.source,
                                  ) && (
                                    <option value={draft.source}>
                                      {(() => {
                                        const src = decodeSource(draft.source);
                                        return hourSourceLabel(
                                          src.source_type,
                                          src.source_id,
                                          sourceOptions,
                                          t,
                                          t("hours_week_grid.no_source"),
                                        );
                                      })()}
                                    </option>
                                  )}
                                {sourceOptions.map((option) => (
                                  <option
                                    key={encodeSource(
                                      option.source_type,
                                      option.source_id,
                                    )}
                                    value={encodeSource(
                                      option.source_type,
                                      option.source_id,
                                    )}
                                  >
                                    {option.title}
                                  </option>
                                ))}
                              </select>
                              <select
                                className="field-input hours-inline-input"
                                value={
                                  buildings.some(
                                    (b) => String(b.id) === draft.building,
                                  )
                                    ? draft.building
                                    : ""
                                }
                                onChange={(event) =>
                                  patchDraft(entry, {
                                    building: event.target.value,
                                  })
                                }
                                disabled={saveBusy}
                                aria-label={t("hours_admin.col_building")}
                                data-testid={`hours-inline-building-${entry.id}`}
                              >
                                <option value="">
                                  {t("my_hours.field_building_empty")}
                                </option>
                                {buildings.map((building) => (
                                  <option key={building.id} value={building.id}>
                                    {building.name}
                                  </option>
                                ))}
                              </select>
                              </div>
                            ) : entry.source_type === "TICKET" ||
                              entry.source_type === "EXTRA_WORK" ? (
                              /* Sprint 179B §2 — the TITLE, the same one
                                 the select above offers. Reading the row
                                 printed "Ticket #41" while editing the
                                 very same row printed the ticket's
                                 title, so one screen answered "which
                                 job" two different ways. `#41` remains
                                 the fallback for a job the picker no
                                 longer lists, which is where the raw id
                                 belonged all along. */
                              /* W-HOURS6 — the NAME first ("final test ·
                                 TCK-373"), the full label as the tooltip. */
                              <span
                                className="cell-tag cell-tag-muted"
                                title={hourSourceLabel(
                                  entry.source_type,
                                  entry.source_id,
                                  sourceOptions,
                                  t,
                                  "—",
                                )}
                                data-testid="hours-entry-job"
                              >
                                {jobTitleFirst(
                                  hourSourceLabel(
                                    entry.source_type,
                                    entry.source_id,
                                    sourceOptions,
                                    t,
                                    "—",
                                  ),
                                )}
                              </span>
                            ) : entry.building_name ? (
                              entry.building_name
                            ) : (
                              <span className="muted-empty">—</span>
                            )}
                          </td>
                          <td>
                            {cellsEditable ? (
                              <select
                                className="field-input hours-inline-input"
                                value={
                                  activeHourTypes.some(
                                    (h) => String(h.id) === draft.hour_type,
                                  )
                                    ? draft.hour_type
                                    : ""
                                }
                                onChange={(event) =>
                                  patchDraft(entry, {
                                    hour_type: event.target.value,
                                  })
                                }
                                disabled={saveBusy}
                                aria-label={t("hours_admin.col_hour_type")}
                                data-testid={`hours-inline-hour-type-${entry.id}`}
                              >
                                {/* An archived type the row still
                                    points at has no <option>, which a
                                    <select> renders as a blank box —
                                    so it collapses to this placeholder
                                    instead of silently submitting a
                                    stale id. */}
                                <option value="">
                                  {t("my_hours.field_hour_type_empty")}
                                </option>
                                {activeHourTypes.map((hourType) => (
                                  <option key={hourType.id} value={hourType.id}>
                                    {hourTypeLabel(hourType, t)} (
                                    {t("hour_types.multiplier_note", {
                                      n: hourType.multiplier,
                                    })}
                                    )
                                  </option>
                                ))}
                              </select>
                            ) : (
                              hourTypeLabelFrom(
                                entry.hour_type_name,
                                entry.hour_type_standard_slot,
                                t,
                              )
                            )}
                          </td>
                          <td>
                            {cellsEditable ? (
                              <input
                                className="field-input hours-inline-input hours-inline-hours"
                                type="number"
                                min="0.25"
                                max="24"
                                step="0.25"
                                value={draft.hours}
                                onChange={(event) =>
                                  patchDraft(entry, {
                                    hours: event.target.value,
                                  })
                                }
                                disabled={saveBusy}
                                aria-label={t("hours_admin.col_hours")}
                                data-testid={`hours-inline-hours-${entry.id}`}
                              />
                            ) : (
                              entry.hours
                            )}
                          </td>
                          <td className="muted small">
                            {cellsEditable ? (
                              <input
                                className="field-input hours-inline-input"
                                type="text"
                                value={draft.note}
                                onChange={(event) =>
                                  patchDraft(entry, {
                                    note: event.target.value,
                                  })
                                }
                                disabled={saveBusy}
                                aria-label={t("hours_admin.col_note")}
                                data-testid={`hours-inline-note-${entry.id}`}
                              />
                            ) : (
                              entry.note || "—"
                            )}
                          </td>
                          {editing && (
                            <td>
                              <button
                                type="button"
                                className="btn btn-ghost btn-sm"
                                data-testid="hours-entry-delete-button"
                                onClick={() => openDeleteEntry(entry)}
                                disabled={entry.is_locked || saveBusy}
                              >
                                {t("hours_admin.delete_button")}
                              </button>
                            </td>
                          )}
                        </tr>
                      );
                    })}
                  </tbody>

                  {/* W-HR1 §2 — THE WEEK'S TOTALS, AS THE FOOTER.
                      Four tiles above the table said "Totaal uren",
                      "Medewerkers", "Gebouwen", "Regels" — three of
                      which were counts of the very columns underneath.
                      A totals ROW belongs to its table, aligns with the
                      columns it sums, and does not compete with the
                      week bar for the top of the page.

                      Hours sits under its own column. Every figure is
                      the SAME summary payload the rows were filtered
                      with, so the footer can never describe a
                      different set from the body. P-13 W6 — the
                      Hours × factor COLUMN is gone; its total stays
                      here (it is the number pay is calculated from,
                      and this sprint is about money staying visible). */}
                  {summary && entries.length > 0 && (
                    <tfoot data-testid="hours-entries-totals">
                      <tr>
                        <td colSpan={4}>
                          <strong>{t("hours_admin.summary_title")}</strong>{" "}
                          <span className="muted small">
                            {t("hours_admin.pagination_summary", {
                              shown: entries.length,
                              total: entryCount,
                            })}
                          </span>
                        </td>
                        <td data-testid="hours-total-hours">
                          <strong>{summary.total_hours}</strong>
                        </td>
                        <td colSpan={editing ? 2 : 1} className="muted small">
                          {t("hours_admin.entries_total", {
                            count: summary.total_entries,
                          })}
                          {" · "}
                          <span
                            title={t("hours_admin.col_weighted_teach")}
                            data-testid="hours-total-weighted"
                          >
                            {t("hours_admin.col_weighted")}{" "}
                            {summary.total_weighted_hours}
                          </span>
                        </td>
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>

              {entries.length === 0 && (
                <div
                  style={{ padding: "32px 24px", textAlign: "center" }}
                  data-testid="hours-entries-empty"
                  data-empty-kind={weekOnly ? "week" : "filters"}
                >
                  {/* P-9 D3 — THE EMPTY WEEK SAYS WHERE THE HOURS ARE.
                      The current week opens empty by construction; the
                      sentence names the week, the last week that holds
                      hours, and offers to open it. A narrowed table (a
                      person, a type, a range) keeps the filter words. */}
                  <h3
                    className="empty-title"
                    style={{ marginBottom: 8 }}
                    data-testid="hours-empty-title"
                  >
                    {weekOnly
                      ? t("hours_weeks.empty_week_title", { week: week.isoWeek })
                      : t("hours_admin.empty_title")}
                  </h3>
                  <p
                    className="muted"
                    style={{ margin: 0 }}
                    data-testid="hours-empty-last-saved"
                  >
                    {!weekOnly
                      ? t("hours_admin.empty_description")
                      : lastSavedWeek
                        ? t("hours_weeks.last_saved_week", {
                            week: lastSavedWeek.iso_week,
                            hours: formatHours(lastSavedWeek.hours, dateLocale),
                          })
                        : t("hours_weeks.no_saved_weeks", { year: week.isoYear })}
                  </p>
                  <div
                    style={{
                      display: "flex",
                      gap: 8,
                      justifyContent: "center",
                      marginTop: 14,
                      flexWrap: "wrap",
                    }}
                  >
                    {weekOnly && lastSavedWeek && (
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        data-testid="hours-empty-open-last-week"
                        onClick={() =>
                          goToWeek({
                            isoYear: lastSavedWeek.iso_year,
                            isoWeek: lastSavedWeek.iso_week,
                          })
                        }
                      >
                        {t("hours_weeks.open_week", { week: lastSavedWeek.iso_week })}
                      </button>
                    )}
                    {!editing && activeHourTypes.length > 0 && (
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => {
                          setWeekModalNote("");
                          setWeekModalOpen(true);
                        }}
                        data-testid="hours-empty-enter-week"
                      >
                        {t("hours_admin.enter_week_button")}
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* Real prev/next off the endpoint's own pagination — the
                  list is `StandardResultsSetPagination`, so a company's
                  year of hours is never all in one response. */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "flex-end",
                  gap: 8,
                  padding: "12px 16px",
                }}
                data-testid="hours-entries-pagination"
              >
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  data-testid="hours-entries-prev"
                  onClick={() => {
                    cancelEditing();
                    setPage((current) => Math.max(1, current - 1));
                  }}
                  disabled={page <= 1}
                >
                  {t("hours_admin.prev_page")}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  data-testid="hours-entries-next"
                  onClick={() => {
                    cancelEditing();
                    setPage((current) => current + 1);
                  }}
                  disabled={!hasNext}
                >
                  {t("hours_admin.next_page")}
                </button>
              </div>
            </div>
          )}
          </details>
        </>
      )}

      {/* Conditionally mounted overlay, like every other editing modal
          here. `ConfirmDialog` below stays native and ref-driven; the
          two are deliberately different things (CLAUDE.md §3). */}
      {(weekModalOpen ||
        (!agreedView &&
          !enterConsumed &&
          enterIds.length > 0 &&
          !loading &&
          activeHourTypes.length > 0)) && (
        <WeekEntryDialog
          employees={employees}
          buildings={buildings}
          hourTypes={activeHourTypes}
          companyId={company === "" ? undefined : company}
          /* The week the bar is on, not always the current one: the
             operator who paged back to week 33 to enter a missing day
             means week 33. */
          initialWeek={week}
          initialEmployeeIds={
            weekModalOpen ? weekModalPreselect : enterIds
          }
          /* P-13 O4 — only the Start-here door sets this; every other
             opener clears it. */
          preselectNote={
            weekModalOpen && weekModalNote ? weekModalNote : undefined
          }
          onClose={() => {
            setEnterConsumed(true);
            setWeekModalOpen(false);
            setWeekModalNote("");
          }}
          onSaved={async (changed, saved) => {
            setEnterConsumed(true);
            setWeekModalOpen(false);
            setWeekModalNote("");
            await refreshEntries();
            // P-12 B4 (§D.24 rule 4) — the page says WHO was saved and
            // the one next step, and highlights those people on the
            // week card; a bare toast is never the only feedback.
            if (changed > 0 && saved && saved.length > 0) {
              const details = saved
                .map((s) => {
                  const person = employees.find((e) => e.id === s.employee);
                  const name =
                    person?.full_name?.trim() || person?.email || String(s.employee);
                  return `${name} ${s.hours.toLocaleString(dateLocale, {
                    maximumFractionDigits: 2,
                  })} ${t("hours_admin.hour_unit")}`;
                })
                .join(", ");
              hoursDone.announce({
                title: t("hours_admin.saved_banner_title", {
                  details,
                  week: week.isoWeek,
                }),
                body: t("hours_admin.saved_banner_body"),
              });
              setSavedHighlight(saved.map((s) => s.employee));
            } else {
              pushToast({
                variant: "success",
                title: t("hours_week_grid.saved", { count: changed }),
              });
            }
          }}
        />
      )}

      <ConfirmDialog
        ref={deleteDialogRef}
        title={t("hours_admin.delete_confirm_title")}
        body={
          <>
            {t("hours_admin.delete_confirm_body")}
            {confirmError && (
              <div
                className="alert-error"
                role="alert"
                data-testid="hours-confirm-error"
              >
                {confirmError}
              </div>
            )}
          </>
        }
        confirmLabel={t("hours_admin.delete_button")}
        onConfirm={handleConfirmDelete}
        onCancel={handleCancelDelete}
        busy={deleteBusy}
        destructive
      />

      {/* W-HR1 §2 — THE TWO GREEN PARAGRAPHS, AS THE CONFIRM BODIES.

          The deleted Overview tab opened with an `alert-info` box
          holding two paragraphs explaining what closing and reopening a
          week do. They were permanent prose above a control most
          visits never touched — read once, then furniture. Their
          content is here, in the modal that appears at the moment the
          operator is about to do the thing, which is the only moment it
          means anything.

          Rendered UNCONDITIONALLY and driven through the ref, both of
          them (CLAUDE.md §3): a native <dialog> behind a condition is
          invisible, and its trigger looks dead. */}
      <ConfirmDialog
        ref={closeWeekRef}
        title={t("weeks.close_confirm_title", { week: formatIsoWeek(week) })}
        body={
          <>
            {t("weeks.close_confirm_body", { week: formatIsoWeek(week) })}
            {confirmError && (
              <div
                className="alert-error"
                role="alert"
                data-testid="hours-confirm-error"
              >
                {confirmError}
              </div>
            )}
          </>
        }
        confirmLabel={t("weeks.close_button")}
        onConfirm={handleConfirmCloseWeek}
        busy={lockBusy}
      />

      <ConfirmDialog
        ref={reopenWeekRef}
        title={t("weeks.reopen_confirm_title", { week: formatIsoWeek(week) })}
        body={
          <>
            {t("weeks.reopen_confirm_body")}
            {confirmError && (
              <div
                className="alert-error"
                role="alert"
                data-testid="hours-confirm-error"
              >
                {confirmError}
              </div>
            )}
          </>
        }
        confirmLabel={t("weeks.reopen_button")}
        onConfirm={handleConfirmReopenWeek}
        busy={lockBusy}
        destructive
      />
    </div>
  );
}
