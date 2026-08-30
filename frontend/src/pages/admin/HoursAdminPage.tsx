import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
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
} from "../../api/timesheets.types";
import type { BuildingAdmin, CompanyAdmin } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { PageHeader } from "../../components/PageHeader";
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
import { jobTitleFirst } from "../../components/timesheets/jobTitle";
import { hourTypeLabel, hourTypeLabelFrom } from "../../lib/hourTypeLabel";
import { HoursFilterRow } from "./HoursFilterRow";
import { ContractHoursTab } from "./ContractHoursTab";

/**
 * W-HR1 §2 — TWO tabs. There were seven, in three named groups.
 *
 * The owner's complaint was that the Overview tab "shows everything and
 * explains nothing", and the audit agreed with him about more than that
 * one tab: seven surfaces over one subject, four of which were the same
 * numbers a fourth way round. What is left is the two questions an
 * operator actually arrives with:
 *
 *   worked    what was worked this week, and is the week final
 *   schedule  what each person is scheduled to work, per week
 *
 * ## What was deleted and where it went
 *
 * **Overview** — deleted outright. Every figure on it restated one
 * number the entries table already carried; period charts and
 * breakdowns are Reports' job, and Reports does it properly. What it
 * uniquely OWNED was week close/reopen, and that moved onto Worked,
 * where the week it acts on is the week on screen.
 *
 * **Approval** — deleted. Approving a standing agreement is one row
 * changing state, so it is a ROW ACTION on Schedule now, next to the
 * row it approves, instead of a screen that reproduced the same table
 * three times under three status headings.
 *
 * **Contract work types** and **Hour types** — deleted from here. Both
 * are per-company CATALOGS and both already render, from the same
 * components, on /admin/catalogs. Two entry points to one catalog is
 * how they drift; the catalog page is the one owner now.
 *
 * **Cost per hour** — moved to /admin/employees, onto the employee's
 * own row (`EmployeeRatePanel`). A rate belongs to a person, and the
 * person is already there.
 *
 * ## One constant, iterated by the renderer
 *
 * Renamed from `HOURS_TAB_GROUPS`, because there are no groups any
 * more and a name that says otherwise is the drift CLAUDE.md warns
 * about. A new tab added to `Tab` and not to this list is a
 * compile-time hole, not a silent one, because `key` is typed `Tab`.
 *
 * NOT exported, and that is `react-refresh/only-export-components`
 * rather than a preference: a non-component export from a file that
 * exports a component is a lint error, and the baseline is frozen.
 */
type Tab = "worked" | "schedule";

const HOURS_TABS: { key: Tab; labelKey: string; testId: string }[] = [
  {
    key: "worked",
    labelKey: "hours_admin.tab_entries",
    testId: "hours-tab-worked",
  },
  {
    key: "schedule",
    labelKey: "contract_hours.tab",
    testId: "hours-tab-schedule",
  },
];

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
 * The "Uren" admin area. W-HR1 §2 cut it from seven tabs to two — see
 * `HOURS_TABS` above for what went where.
 *
 * ## What the Worked tab is
 *
 *   title + ONE primary button (enter a week)
 *   a WEEK BAR: which week, one status chip, one state-dependent
 *     button (Week afsluiten / Heropenen)
 *   one WRAPPING row of filters
 *   ONE table, with an Edit toggle that makes its cells editable and
 *     saves every change at once, and the week's totals as its FOOTER
 *   real prev/next off the endpoint's own pagination
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

  /* W-UX F41 — the tab and the week are URL state (`?tab=schedule`,
   * `?week=2026-W35`), the ticket page's exact rule: absence is the
   * default, writes replace history, a reload or a shared link lands on
   * the same view. */
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTab: Tab =
    searchParams.get("tab") === "schedule" ? "schedule" : "worked";
  const initialWeek: IsoWeek =
    parseIsoWeek(searchParams.get("week") ?? "") ?? currentIsoWeek();
  const [tab, setTabState] = useState<Tab>(initialTab);
  const setTab = useCallback(
    (next: Tab) => {
      setTabState(next);
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev);
          if (next === "worked") params.delete("tab");
          else params.set("tab", next);
          return params;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  /** W-HR1 §2 — the week the lock chip and the one button act on, and
   *  the week the table opens on. Its own state rather than derived
   *  from `date_from`: a lock is a fact about a WEEK, and a hand-typed
   *  range of three months has no lock state to show. */
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
          const stored = Number(
            window.localStorage.getItem(HOURS_COMPANY_STORAGE_KEY),
          );
          const remembered = response.some((c) => c.id === stored)
            ? stored
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
  const fetchKey = `${tab}|${JSON.stringify(queryFilters)}|${page}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const loading =
    tab === "worked" && (companyPending || loadedKey !== fetchKey);

  useEffect(() => {
    if (tab !== "worked" || companyPending) return;
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
  }, [tab, queryFilters, page, fetchKey, companyPending]);

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
    if (tab !== "worked" || companyPending) return;
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
  }, [tab, companyPending, week, company, weekStatusKey]);

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

  // Sprint 164 — the wrapper used to carry a class with no rule behind
  // it, the same hole the gate found on MyHoursPage last sprint. A JS
  // comment, not a JSX one: a JSX comment cannot sit between `return (`
  // and the element, which is a mistake I have now made twice.
  return (
    /* W5 fix 5 — a named root so this page's title spacing can be fixed
       without touching the global `.page-title` every page shares. */
    <div className="hours-admin-page">
      <PageHeader
        title={t("hours_admin.title")}
        subtitle={t("hours_admin.subtitle")}
        actions={
          tab === "worked" && !editing ? (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              data-testid="hours-enter-week-button"
              onClick={() => setWeekModalOpen(true)}
              disabled={loading || activeHourTypes.length === 0}
            >
              {t("hours_admin.enter_week_button")}
            </button>
          ) : undefined
        }
      />

      {companyLoadError && (
        <div className="alert-error" role="alert" style={{ marginBottom: 16 }}>
          {companyLoadError}
        </div>
      )}

      {/* W-HR1 §2 — two tabs, the house `composer-toggle` shape every
          other tabbed admin page uses (CatalogsAdminPage's is the same
          markup). The grouped bar with its captions and its dividers
          existed to make seven pills legible; two pills do not need a
          taxonomy above them.
          Iterated from `HOURS_TABS`, never a second local array. */}
      <div
        className="composer-toggle"
        role="tablist"
        aria-label={t("hours_admin.tabs_aria")}
        style={{ marginBottom: 16 }}
      >
        {HOURS_TABS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            role="tab"
            aria-selected={tab === entry.key}
            className={`composer-toggle-btn ${tab === entry.key ? "active" : ""}`}
            data-testid={entry.testId}
            onClick={() => setTab(entry.key)}
          >
            {t(entry.labelKey)}
          </button>
        ))}
      </div>

      {tab === "schedule" && (
        <ContractHoursTab
          companyId={company}
          buildings={buildings}
          employees={employees}
          hourTypes={hourTypes}
        />
      )}

      {tab === "worked" && (
        <>
          {/* W-HR1 §2 — THE WEEK BAR: which week, is it final, and the
              one button that changes that.

              Everything about a week lock used to live on the deleted
              Overview tab, two clicks from the hours it governs. The
              chip and the button are here, above the rows they act on,
              and the arrows move the table with them (`goToWeek`).

              ONE state-dependent button, never two: a week is open or
              closed, and offering both verbs at once asks the operator
              to work out which one is live. */}
          <div
            className="card"
            data-testid="hours-week-bar"
            style={{
              display: "flex",
              alignItems: "center",
              flexWrap: "wrap",
              gap: 10,
              padding: "12px 16px",
              marginBottom: 16,
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

            <div style={{ marginLeft: "auto" }}>
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
          </div>

          {/* W-HR1 §2 — the filter row WRAPS instead of clipping.

              It was `.hours-filter-line`: `flex-wrap: nowrap` with
              `overflow-x: auto`, so at 1366 the "Tot" field ended 121px
              past the card's right edge and "Filters wissen" 223px past
              it — both reachable only by scrolling a bar nothing said
              was scrollable. This is `.filter-bar`, the house filter
              shape every other admin list uses (and the Schedule tab
              beside this one): it wraps to a second line and every
              control is on screen at every width. */}
          <div
            className="card filter-bar"
            data-testid="hours-filters"
            style={{ marginBottom: 16, borderBottom: "1px solid var(--border)" }}
          >
            {showCompanySelector && (
              <div className="filter-field">
                <span className="filter-label">
                  {t("catalog.company_selector_label")}
                </span>
                <select
                  id="hours-company-selector"
                  className="filter-control"
                  value={company === "" ? "" : String(company)}
                  onChange={(event) => {
                    const value = event.target.value;
                    setCompany(value === "" ? "" : Number(value));
                    setPage(1);
                    setEditing(false);
                    setDrafts({});
                    if (value !== "") {
                      window.localStorage.setItem(
                        HOURS_COMPANY_STORAGE_KEY,
                        value,
                      );
                    }
                  }}
                  data-testid="hours-company-selector"
                >
                  {/* Disabled placeholder: there is no "all companies"
                      state. It renders only before the list resolves. */}
                  <option value="" disabled>
                    {t("catalog.company_selector_placeholder")}
                  </option>
                  {companies.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.name}
                    </option>
                  ))}
                </select>
              </div>
            )}

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
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                data-testid="hours-filters-period-toggle"
                aria-expanded={periodOpen}
                onClick={() => setPeriodToggle((v) => !v)}
              >
                {periodOpen
                  ? t("hours_admin.period_toggle_close")
                  : t("hours_admin.period_toggle_open")}
              </button>
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

          {loadError && (
            <div
              className="alert-error"
              role="alert"
              style={{ marginBottom: 16 }}
            >
              {loadError}
            </div>
          )}

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
              <div className="section-head" style={{ padding: "14px 16px 0" }}>
                <div>
                  <div className="section-head-title">
                    {t("hours_admin.list_title")}
                  </div>
                  {/* Sprint 172 §3 — the two tabs record DIFFERENT
                      things and the owner could not tell which from the
                      buttons. Said in one line, in his words. */}
                  <div className="section-head-sub">
                    {t("hours_admin.entries_subtitle")}
                  </div>
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
                      {/* Export describes exactly the rows below it, so
                          it sits with them. It used to head the tile
                          strip that is now this table's footer. */}
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        data-testid="hours-export-csv"
                        onClick={() => void handleExport()}
                        disabled={exportBusy || loading}
                      >
                        {exportBusy
                          ? t("hours_admin.export_busy")
                          : t("hours_admin.export_csv")}
                      </button>
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
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{t("hours_admin.col_date")}</th>
                      <th>{t("hours_admin.col_week")}</th>
                      <th>{t("hours_admin.col_employee")}</th>
                      <th>{t("hours_admin.col_source")}</th>
                      <th>{t("hours_admin.col_hour_type")}</th>
                      <th>{t("hours_admin.col_hours")}</th>
                      <th>
                        {/* P-4 — a plain word and a click-to-teach: what
                            "weighted" is, in one sentence. */}
                        <abbr
                          title={t("hours_admin.col_weighted_teach")}
                          style={{ textDecoration: "underline dotted", cursor: "help" }}
                          data-testid="hours-col-weighted"
                        >
                          {t("hours_admin.col_weighted")}
                        </abbr>
                      </th>
                      <th>{t("hours_admin.col_building")}</th>
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
                              formatDate(entry.date, dateLocale)
                            )}
                          </td>
                          <td className="muted small">
                            {formatIsoWeek({
                              isoYear: entry.iso_year,
                              isoWeek: entry.iso_week,
                            })}
                            {entry.is_locked && (
                              <span
                                className="badge badge-closed"
                                style={{ marginLeft: 6 }}
                              >
                                {t("weeks.status_closed")}
                              </span>
                            )}
                          </td>
                          <td>{entry.employee_name}</td>
                          {/* Sprint 173 §1 — WHERE the hour came from.
                              Read-only in the table: the source is set
                              by the flow that logged the hour, not
                              retyped by hand. */}
                          <td>
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
                            ) : entry.source_type &&
                              entry.source_type !== "OTHER" ? (
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
                          {/* Weighted is derived server-side from the
                              snapshot; it updates on the refresh after
                              Save, never optimistically. */}
                          <td className="muted">{entry.weighted_hours}</td>
                          <td className="muted small">
                            {cellsEditable ? (
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
                            ) : (
                              (entry.building_name ?? "—")
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

                      Hours and Weighted sit under their own columns.
                      Every figure is the SAME summary payload the rows
                      were filtered with, so the footer can never
                      describe a different set from the body. */}
                  {summary && entries.length > 0 && (
                    <tfoot data-testid="hours-entries-totals">
                      <tr>
                        <td colSpan={5}>
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
                        <td className="muted" data-testid="hours-total-weighted">
                          {summary.total_weighted_hours}
                        </td>
                        <td colSpan={editing ? 3 : 2} className="muted small">
                          {t("hours_admin.entries_total", {
                            count: summary.total_entries,
                          })}
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
                >
                  <h3 className="empty-title" style={{ marginBottom: 8 }}>
                    {t("hours_admin.empty_title")}
                  </h3>
                  <p className="muted" style={{ margin: 0 }}>
                    {t("hours_admin.empty_description")}
                  </p>
                  {!editing && activeHourTypes.length > 0 && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      style={{ marginTop: 14 }}
                      onClick={() => setWeekModalOpen(true)}
                      data-testid="hours-empty-enter-week"
                    >
                      {t("hours_admin.enter_week_button")}
                    </button>
                  )}
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
        </>
      )}

      {/* Conditionally mounted overlay, like every other editing modal
          here. `ConfirmDialog` below stays native and ref-driven; the
          two are deliberately different things (CLAUDE.md §3). */}
      {weekModalOpen && (
        <WeekEntryDialog
          employees={employees}
          buildings={buildings}
          hourTypes={activeHourTypes}
          companyId={company === "" ? undefined : company}
          /* The week the bar is on, not always the current one: the
             operator who paged back to week 33 to enter a missing day
             means week 33. */
          initialWeek={week}
          onClose={() => setWeekModalOpen(false)}
          onSaved={async (changed) => {
            setWeekModalOpen(false);
            await refreshEntries();
            pushToast({
              variant: "success",
              title: t("hours_week_grid.saved", { count: changed }),
            });
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
