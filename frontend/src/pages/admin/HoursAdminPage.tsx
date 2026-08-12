import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { listAllBuildings, listAllCompanies } from "../../api/admin";
import { getApiError } from "../../api/client";
import {
  deleteTimeEntry,
  downloadTimesheetSummaryCsv,
  fetchTimesheetSummary,
  listHourTypes,
  listTimeEntries,
  listTimesheetEmployees,
  updateTimeEntry,
} from "../../api/timesheets";
import type {
  HourType,
  TimeEntry,
  TimeEntryFilters,
  TimesheetEmployee,
  TimesheetSummary,
} from "../../api/timesheets.types";
import type { BuildingAdmin, CompanyAdmin } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { BoundedList } from "../../components/BoundedList";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { PageHeader } from "../../components/PageHeader";
import { useToast } from "../../components/ToastProvider";
import { currentIsoWeek, fromDateString } from "../../lib/isoWeek";
import { WeekEntryDialog } from "../../components/timesheets/WeekEntryDialog";
import { hourTypeLabel, hourTypeLabelFrom } from "../../lib/hourTypeLabel";
import { HourTypesTab } from "./HourTypesTab";
import { HoursFilterRow } from "./HoursFilterRow";
import { ContractHoursApprovalTab } from "./ContractHoursApprovalTab";
import { ContractHoursTab } from "./ContractHoursTab";
import { WorkTypesTab } from "./WorkTypesTab";
import { HoursOverviewTab } from "./HoursOverviewTab";

// Sprint 152.2 — "weeks" became the OVERVIEW tab: the read-only
// analytical surface (period selector, graphs, breakdowns), which
// still owns week close/reopen because a lock acts on a PERIOD, not
// on an entry. The tab KEY is unchanged so the stored value stays
// stable; only the label and the content moved.
type Tab =
  | "entries"
  | "hour_types"
  | "weeks"
  | "contract_hours"
  | "contract_approval"
  | "work_types";

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
  date_from: string;
  date_to: string;
}

const EMPTY_FILTERS: EntryFilterState = {
  employee: "",
  hour_type: "",
  building: "",
  date_from: "",
  date_to: "",
};

/** One row's pending inline edit. Every field is a STRING: a `<select>`
 *  / `<input>` value is a string, and keeping numbers here means a parse
 *  on every render plus an empty-string special case at each one. */
interface EntryDraft {
  date: string;
  hour_type: string;
  hours: string;
  building: string;
  note: string;
}

function draftOf(entry: TimeEntry): EntryDraft {
  return {
    date: entry.date,
    hour_type: String(entry.hour_type),
    hours: entry.hours,
    building: entry.building === null ? "" : String(entry.building),
    note: entry.note,
  };
}

function draftsDiffer(a: EntryDraft, b: EntryDraft): boolean {
  return (
    a.date !== b.date ||
    a.hour_type !== b.hour_type ||
    a.hours.trim() !== b.hours.trim() ||
    a.building !== b.building ||
    a.note !== b.note
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
 * Sprint 159 §1 — the "Uren" admin area, rebuilt to the shape of the
 * reference system the owner sent.
 *
 * ## What the entries tab is now
 *
 *   title + ONE primary button (enter a week)
 *   one line of filters
 *   a row of stat tiles
 *   ONE table, with an Edit toggle that makes its cells editable and
 *   saves every change at once
 *
 * ## What was REMOVED
 *
 * The in-page week grid and its "Set up week" / "Close grid" panel: the
 * grid now lives ONLY in the modal, and having one on the page as well
 * is the duplication the owner called confusing. The per-row "Add
 * entry" / "Edit entry" modal: a modal per row is exactly what the
 * inline Edit toggle exists to replace, and a week — including a single
 * day of it — is entered in the one modal. The per-hour-type and
 * per-week report tables: the Overview tab has rendered both, over the
 * same summary payload, since Sprint 152.2, so they were a second copy
 * of an existing surface sitting under the list. The CSV export they
 * carried is kept, next to the tiles it describes.
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
 * Sprint 159 adds the gate that was missing: for a SUPER_ADMIN the
 * reads WAIT until the company is known. Measured on the built Sprint
 * 158 page, the first render fired `/timesheets/employees/` and
 * `/timesheets/summary/` with no company and took two 400s
 * (`company is required when more than one provider Company exists`)
 * before the retry, which put a red error banner on screen for as long
 * as it took the company list to resolve.
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

  const [tab, setTab] = useState<Tab>("entries");

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

  const [filters, setFilters] = useState<EntryFilterState>(EMPTY_FILTERS);
  const [employees, setEmployees] = useState<TimesheetEmployee[]>([]);
  const [hourTypes, setHourTypes] = useState<HourType[]>([]);
  const [buildings, setBuildings] = useState<BuildingAdmin[]>([]);

  const [weekModalOpen, setWeekModalOpen] = useState(false);

  // The inline table editor. `drafts` holds ONLY the rows the operator
  // has touched, so "what changed" is the map itself and no diffing of
  // the whole page is needed.
  const [editing, setEditing] = useState(false);
  const [drafts, setDrafts] = useState<Record<number, EntryDraft>>({});
  const [saveBusy, setSaveBusy] = useState(false);
  const [saveError, setSaveError] = useState("");

  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
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

  const queryFilters: TimeEntryFilters = useMemo(
    () => ({
      company,
      employee: filters.employee,
      hour_type: filters.hour_type,
      building: filters.building,
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
    tab === "entries" && (companyPending || loadedKey !== fetchKey);

  useEffect(() => {
    if (tab !== "entries" || companyPending) return;
    let cancelled = false;
    // The table and its tiles come from the SAME filter object, so the
    // numbers always describe the rows on screen.
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
      setLoadError(getApiError(err));
      deleteDialogRef.current?.close();
    } finally {
      setDeleteBusy(false);
    }
  }

  const handleExport = useCallback(async () => {
    setExportBusy(true);
    try {
      await downloadTimesheetSummaryCsv(queryFilters);
    } catch (err) {
      setLoadError(getApiError(err));
      pushToast({ variant: "error", title: t("hours_admin.export_failed") });
    } finally {
      setExportBusy(false);
    }
  }, [queryFilters, pushToast, t]);

  // The four tiles. Every number comes off the SAME summary the table
  // was filtered with; `by_employee` / `by_building` are the buckets the
  // endpoint has returned since Sprint 152.2.
  const tiles = summary
    ? [
        {
          key: "hours",
          label: t("hours_admin.tile_hours"),
          value: summary.total_hours,
        },
        {
          key: "workers",
          label: t("hours_admin.tile_workers"),
          value: String(summary.by_employee.length),
        },
        {
          key: "buildings",
          label: t("hours_admin.tile_buildings"),
          // The "no building" bucket is a real bucket but not a
          // building, so it does not count as one.
          value: String(
            summary.by_building.filter((b) => b.building !== null).length,
          ),
        },
        {
          key: "entries",
          label: t("hours_admin.tile_entries"),
          value: String(summary.total_entries),
        },
      ]
    : [];

  // Sprint 164 — the wrapper used to carry a class with no rule behind
  // it, the same hole the gate found on MyHoursPage last sprint. A JS
  // comment, not a JSX one: a JSX comment cannot sit between `return (`
  // and the element, which is a mistake I have now made twice.
  return (
    <div>
      <PageHeader
        title={t("hours_admin.title")}
        subtitle={t("hours_admin.subtitle")}
        actions={
          tab === "entries" ? (
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

      {/* Same tablist markup as ServicesAdminPage — `composer-toggle` /
          `composer-toggle-btn`, not a new tab component. */}
      <div
        className="composer-toggle"
        role="tablist"
        aria-label={t("hours_admin.tabs_aria")}
        style={{ marginBottom: 16 }}
      >
        <button
          type="button"
          role="tab"
          aria-selected={tab === "entries"}
          className={`composer-toggle-btn ${tab === "entries" ? "active" : ""}`}
          data-testid="hours-tab-entries"
          onClick={() => setTab("entries")}
        >
          {t("hours_admin.tab_entries")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "contract_hours"}
          className={`composer-toggle-btn ${tab === "contract_hours" ? "active" : ""}`}
          data-testid="hours-tab-contract-hours"
          onClick={() => setTab("contract_hours")}
        >
          {t("contract_hours.tab")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "weeks"}
          className={`composer-toggle-btn ${tab === "weeks" ? "active" : ""}`}
          data-testid="hours-tab-weeks"
          onClick={() => setTab("weeks")}
        >
          {t("hours_admin.tab_overview")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "contract_approval"}
          className={`composer-toggle-btn ${tab === "contract_approval" ? "active" : ""}`}
          data-testid="hours-tab-contract-approval"
          onClick={() => setTab("contract_approval")}
        >
          {t("contract_hours.tab_approval")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "hour_types"}
          className={`composer-toggle-btn ${tab === "hour_types" ? "active" : ""}`}
          data-testid="hours-tab-hour-types"
          onClick={() => setTab("hour_types")}
        >
          {t("hours_admin.tab_hour_types")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "work_types"}
          className={`composer-toggle-btn ${tab === "work_types" ? "active" : ""}`}
          data-testid="hours-tab-work-types"
          onClick={() => setTab("work_types")}
        >
          {t("work_types.tab")}
        </button>
      </div>

      {tab === "work_types" && <WorkTypesTab />}

      {tab === "contract_approval" && (
        <ContractHoursApprovalTab
          companyId={company}
          buildings={buildings.map((b) => ({ id: b.id, name: b.name }))}
          employees={employees.map((e) => ({
            id: e.id,
            name: e.full_name || e.email,
          }))}
        />
      )}

      {tab === "contract_hours" && (
        <ContractHoursTab
          companyId={company}
          buildings={buildings}
          employees={employees}
          hourTypes={hourTypes}
        />
      )}

      {tab === "entries" && (
        <>
          {/* ONE line of filters — the company (when there is a choice),
              the three shared pickers and the period. Sprint 156 §6a's
              rule, and the reason the company selector is no longer a
              card of its own above them. */}
          <div
            className="card hours-filter-line"
            data-testid="hours-filters"
          >
            {showCompanySelector && (
              <div className="field" style={{ margin: 0 }}>
                <label className="field-label" htmlFor="hours-company-selector">
                  {t("catalog.company_selector_label")}
                </label>
                <select
                  id="hours-company-selector"
                  className="field-select"
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

            {/* Sprint 152.2 — the SHARED filter row. The Overview tab
                filters the same collection with the same three
                controls; a second hand-maintained copy is the "written
                once, omitted elsewhere" defect this project keeps
                paying for. */}
            <HoursFilterRow
              values={{
                employee: filters.employee,
                hour_type: filters.hour_type,
                building: filters.building,
              }}
              onChange={patchFilters}
              employees={employees}
              hourTypes={hourTypes}
              buildings={buildings}
              idPrefix="hours"
            />

            <div className="field" style={{ margin: 0 }}>
              <label className="field-label" htmlFor="hours-filter-from">
                {t("hours_admin.filter_date_from")}
              </label>
              <input
                id="hours-filter-from"
                className="field-input"
                type="date"
                value={filters.date_from}
                onChange={(event) =>
                  patchFilters({ date_from: event.target.value })
                }
                data-testid="hours-filter-date-from"
              />
            </div>

            <div className="field" style={{ margin: 0 }}>
              <label className="field-label" htmlFor="hours-filter-to">
                {t("hours_admin.filter_date_to")}
              </label>
              <input
                id="hours-filter-to"
                className="field-input"
                type="date"
                value={filters.date_to}
                onChange={(event) =>
                  patchFilters({ date_to: event.target.value })
                }
                data-testid="hours-filter-date-to"
              />
            </div>

            <button
              type="button"
              className="btn btn-ghost btn-sm hours-filter-reset"
              data-testid="hours-filters-reset"
              onClick={() => {
                setFilters(EMPTY_FILTERS);
                setPage(1);
                cancelEditing();
              }}
            >
              {t("hours_admin.filter_reset")}
            </button>
          </div>

          {/* The tiles. They describe the filtered set, because they are
              computed from the same filter object as the table. */}
          {/* Sprint 165 §1 — Export is an ACTION, not a tile. It used to
              be a child of the tile grid, so it took a column and skewed
              the division; four tiles across five tracks is why they
              read as bunched. It belongs beside the section title. */}
          <div className="hours-tiles-head">
            <span className="hours-tiles-title">
              {t("hours_admin.summary_title")}
            </span>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              data-testid="hours-export-csv"
              onClick={() => void handleExport()}
              disabled={exportBusy || loading}
            >
              {exportBusy
                ? t("hours_admin.export_busy")
                : t("hours_admin.export_csv")}
            </button>
          </div>
          {/* `repeat(N, 1fr)` with N the tile count, set inline because
              only the component knows N. `auto-fit` + `minmax` was
              width-dependent: it packed as many 150px tracks as fitted
              and left the remainder empty, which is exactly the bunching
              the owner reported three times. This is the Sprint 163 §2
              solution, not a third one. */}
          <div
            className="hours-tile-row"
            data-testid="hours-tiles"
            style={{
              gridTemplateColumns: `repeat(${tiles.length}, minmax(0, 1fr))`,
            }}
          >
            {tiles.map((tile) => (
              <div
                key={tile.key}
                className="hours-tile"
                data-testid={`hours-tile-${tile.key}`}
              >
                <span className="hours-tile-label">{tile.label}</span>
                <span className="hours-tile-value">{tile.value}</span>
              </div>
            ))}
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
            <div className="loading-bar">
              <div className="loading-bar-fill" />
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
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => setEditing(true)}
                      disabled={entries.length === 0}
                      data-testid="hours-edit-toggle"
                    >
                      {t("hours_admin.edit_button")}
                    </button>
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

              <BoundedList
                size="lg"
                count={entries.length}
                ariaLabel={t("hours_admin.list_aria")}
                testIdPrefix="hours-entries"
                className="table-wrap"
                emptyState={
                  <div
                    style={{ padding: "32px 24px", textAlign: "center" }}
                    data-testid="hours-entries-empty"
                  >
                    <h3 style={{ marginBottom: 8 }}>
                      {t("hours_admin.empty_title")}
                    </h3>
                    <p className="muted" style={{ margin: 0 }}>
                      {t("hours_admin.empty_description")}
                    </p>
                  </div>
                }
              >
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{t("hours_admin.col_date")}</th>
                      <th>{t("hours_admin.col_week")}</th>
                      <th>{t("hours_admin.col_employee")}</th>
                      <th>{t("hours_admin.col_hour_type")}</th>
                      <th>{t("hours_admin.col_hours")}</th>
                      <th>{t("hours_admin.col_weighted")}</th>
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
                            {entry.iso_year}-W
                            {String(entry.iso_week).padStart(2, "0")}
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
                                    {hourTypeLabel(hourType, t)} (x
                                    {hourType.multiplier})
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
                </table>
              </BoundedList>

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

      {tab === "hour_types" && (
        <HourTypesTab
          companyRequired={showCompanySelector}
          selectedCompany={company}
        />
      )}

      {tab === "weeks" && (
        <HoursOverviewTab
          selectedCompany={company}
          employees={employees}
          hourTypes={hourTypes}
          buildings={buildings}
        />
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
          initialWeek={currentIsoWeek()}
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
        body={t("hours_admin.delete_confirm_body")}
        confirmLabel={t("hours_admin.delete_button")}
        onConfirm={handleConfirmDelete}
        onCancel={handleCancelDelete}
        busy={deleteBusy}
        destructive
      />
    </div>
  );
}
