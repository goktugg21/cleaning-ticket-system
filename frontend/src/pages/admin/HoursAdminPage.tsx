import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { listAllBuildings, listAllCompanies } from "../../api/admin";
import { getApiError } from "../../api/client";
import {
  createTimeEntry,
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
  TimeEntryWritePayload,
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
import { fromDateString, toDateString } from "../../lib/isoWeek";
import { HourTypesTab } from "./HourTypesTab";
import { HoursFilterRow } from "./HoursFilterRow";
import { HoursOverviewTab } from "./HoursOverviewTab";

// Sprint 152.2 — "weeks" became the OVERVIEW tab: the read-only
// analytical surface (period selector, graphs, breakdowns), which
// still owns week close/reopen because a lock acts on a PERIOD, not
// on an entry. The tab KEY is unchanged so the stored value stays
// stable; only the label and the content moved.
type Tab = "entries" | "hour_types" | "weeks";

// Sprint 152 — the SUPER_ADMIN's provider company, remembered across
// visits. Its OWN key, not shared with the catalog's
// (`osius.catalog.company`): the two surfaces are navigated
// independently, and making a choice in one silently move the other is
// the kind of coupling that reads as a bug. Same rationale as Sprint
// 150's: localStorage, not a server-side preference — a view
// convenience, not a permission and not something anyone else inherits.
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

// Sprint 152.1 — the admin entry form. Every field is a STRING here and
// converted at submit: a `<select>`/`<input>` value is a string, and
// keeping numbers in form state means a parse on every render plus an
// empty-string special case at each one.
interface EntryFormState {
  employee: string;
  date: string;
  hour_type: string;
  hours: string;
  building: string;
  note: string;
}

function emptyEntryForm(): EntryFormState {
  return {
    employee: "",
    date: toDateString(new Date()),
    hour_type: "",
    hours: "",
    building: "",
    note: "",
  };
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
 * Sprint 152 — the "Uren" admin area (SUPER_ADMIN / COMPANY_ADMIN).
 * Three tabs: the company-wide entries overview with its totals panel
 * and CSV export, the hour-type catalog, and week close/reopen.
 *
 * Follows the `ServicesAdminPage` conventions, including the Sprint
 * 149/150 company model for a SUPER_ADMIN: exactly ONE provider company
 * is in view at a time, seeded from the operator's remembered choice
 * and otherwise from the LOWEST id (the deployment's first tenant, not
 * an alphabetical accident). The seed is set inside the fetch's
 * `.then()`, never in an effect body — CLAUDE.md bans a synchronous
 * setState there, and that exact pattern caused the Sprint 143
 * customer-lock regression.
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
  const [company, setCompany] = useState<number | "">("");
  // Its own error state, not shared with the list's: a missing SELECTOR
  // blocks creates and needs a reload, a stale LIST fixes itself on the
  // next mutation. Sharing one made Sprint 142's carry-overs cancel each
  // other out (see ServicesAdminPage's `companyLoadError`).
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

  // Sprint 152.1 — the entry form. Sprint 152 shipped this tab READ-ONLY
  // because the sprint prompt asked only for an overview, which left the
  // module unable to do the thing it exists for: an admin recording
  // hours for an employee. The backend accepted it all along.
  const [entryMode, setEntryMode] = useState<"create" | "edit" | null>(null);
  const [editingEntry, setEditingEntry] = useState<TimeEntry | null>(null);
  const [entryForm, setEntryForm] = useState<EntryFormState>(emptyEntryForm);
  const [entryFormError, setEntryFormError] = useState("");
  const [entryFormBusy, setEntryFormBusy] = useState(false);

  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);
  const [deleteTarget, setDeleteTarget] = useState<TimeEntry | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  const showCompanySelector = isSuperAdmin && companies.length > 1;

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
      })
      .catch(() => {
        // Fail loudly. A silently absent selector leaves a SUPER_ADMIN on
        // a multi-tenant deployment with no control and then a
        // `timesheet_company_required` 400 they cannot act on.
        if (!cancelled) setCompanyLoadError(t("catalog.company_load_failed"));
      });
    return () => {
      cancelled = true;
    };
  }, [isSuperAdmin, t]);

  // The filter pickers. Reloaded when the company changes so a
  // SUPER_ADMIN switching tenants does not keep the previous one's
  // employees in the dropdown.
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      // Sprint 152.1 — the module's OWN picker endpoint, narrowed to the
      // selected company. Sprint 152 used `/api/employees/` here, which
      // takes no `?company=` and returns no company either: for a
      // SUPER_ADMIN that mixed several providers' people into one
      // dropdown where every wrong pick 400s. That was tolerable while
      // the field was only a FILTER; it is not once the same list names
      // the employee on a write. See `views_employees.py`.
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
  }, [company]);

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
  const loading = tab === "entries" && loadedKey !== fetchKey;

  useEffect(() => {
    if (tab !== "entries") return;
    let cancelled = false;
    // The table and its totals come from the SAME filter object, so the
    // panel under the table always describes the table.
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
  }, [tab, queryFilters, page, fetchKey]);

  // Only ACTIVE hour types are offerable for a write — an archived one
  // is rejected server-side (`hour_type_archived`). The unfiltered list
  // still backs the FILTER dropdown, where an archived type is a
  // perfectly reasonable thing to search for.
  const activeHourTypes = useMemo(
    () => hourTypes.filter((hourType) => hourType.is_active),
    [hourTypes],
  );

  /**
   * A form value that no longer names anything offerable collapses HERE,
   * at the point of use — never through a resync effect that writes back
   * into form state. That pattern is what produced the Sprint 143
   * customer-lock regression, and CLAUDE.md bans the synchronous
   * setState it needs.
   *
   * It happens for real: a SUPER_ADMIN switching company reloads the
   * employee, hour-type and building lists underneath an open form, and
   * an edit form seeded from an entry whose hour type has since been
   * archived would otherwise show a value with no matching <option> —
   * which a <select> renders as a blank box that silently submits the
   * stale id.
   */
  const effectiveFormEmployee = employees.some(
    (employee) => String(employee.id) === entryForm.employee,
  )
    ? entryForm.employee
    : "";
  const effectiveFormHourType = activeHourTypes.some(
    (hourType) => String(hourType.id) === entryForm.hour_type,
  )
    ? entryForm.hour_type
    : "";
  const effectiveFormBuilding = buildings.some(
    (building) => String(building.id) === entryForm.building,
  )
    ? entryForm.building
    : "";

  /**
   * Re-read the entries page and its totals after a mutation. NEVER
   * THROWS: the write already committed, so a failed re-read must not
   * turn a saved row into a form error or wedge a busy flag. Stale list
   * plus a visible page-level message, never silence. (Same contract as
   * `HourTypesTab.refresh`.)
   *
   * Re-reads rather than merging locally, because a write can move a row
   * OUT of the current view entirely — a date edit past the filtered
   * range, or an employee change under an employee filter. A local merge
   * can drop a row but never bring one back.
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

  function openCreateEntry() {
    setEntryMode("create");
    setEditingEntry(null);
    setEntryForm(emptyEntryForm());
    setEntryFormError("");
  }

  function openEditEntry(entry: TimeEntry) {
    setEntryMode("edit");
    setEditingEntry(entry);
    setEntryForm({
      employee: String(entry.employee),
      date: entry.date,
      hour_type: String(entry.hour_type),
      hours: entry.hours,
      building: entry.building === null ? "" : String(entry.building),
      note: entry.note,
    });
    setEntryFormError("");
  }

  function closeEntryModal() {
    setEntryMode(null);
    setEditingEntry(null);
    setEntryFormError("");
  }

  async function handleEntrySubmit(event: FormEvent) {
    event.preventDefault();
    // The EFFECTIVE values, not the raw ones: a select whose value
    // collapsed above must not still submit the stale id it is no longer
    // displaying.
    if (
      !effectiveFormEmployee ||
      !entryForm.date ||
      !effectiveFormHourType ||
      !entryForm.hours.trim()
    ) {
      setEntryFormError(t("hours_admin.entry_error_required_fields"));
      return;
    }
    setEntryFormBusy(true);
    setEntryFormError("");
    const payload: TimeEntryWritePayload = {
      employee: Number(effectiveFormEmployee),
      date: entryForm.date,
      hour_type: Number(effectiveFormHourType),
      hours: entryForm.hours.trim(),
      building:
        effectiveFormBuilding === "" ? null : Number(effectiveFormBuilding),
      note: entryForm.note.trim(),
      // The page's selected company, as the DISAMBIGUATOR the serializer
      // documents. On UPDATE the field is read-only server-side (the
      // tenant anchor never moves), so sending it there is harmless.
      ...(company === "" ? {} : { company }),
    };
    try {
      if (entryMode === "create") {
        await createTimeEntry(payload);
      } else if (entryMode === "edit" && editingEntry) {
        await updateTimeEntry(editingEntry.id, payload);
      }
      await refreshEntries();
      closeEntryModal();
    } catch (err) {
      // The server's message VERBATIM — including `week_closed`, which
      // names the week and says what to do about it. The UI avoids
      // offering doomed actions (`is_locked` disables the row buttons)
      // but the server is the authority, and a page that was open while
      // an admin closed the week will still get here.
      setEntryFormError(getApiError(err));
    } finally {
      setEntryFormBusy(false);
    }
  }

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

  return (
    <div className="page">
      <PageHeader
        title={t("hours_admin.title")}
        subtitle={t("hours_admin.subtitle")}
        actions={
          tab === "entries" ? (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              data-testid="hours-add-entry-button"
              onClick={openCreateEntry}
              disabled={loading || hourTypes.length === 0}
            >
              {t("hours_admin.add_entry_button")}
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
          aria-selected={tab === "weeks"}
          className={`composer-toggle-btn ${tab === "weeks" ? "active" : ""}`}
          data-testid="hours-tab-weeks"
          onClick={() => setTab("weeks")}
        >
          {t("hours_admin.tab_overview")}
        </button>
      </div>

      {showCompanySelector && (
        <div className="field" style={{ maxWidth: 320, marginBottom: 16 }}>
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
              if (value !== "") {
                window.localStorage.setItem(HOURS_COMPANY_STORAGE_KEY, value);
              }
            }}
            data-testid="hours-company-selector"
          >
            {/* Disabled placeholder: there is no "all companies" state.
                It renders only before the list resolves, so the select
                never shows a blank box or a company nobody picked. */}
            <option value="" disabled>
              {t("catalog.company_selector_placeholder")}
            </option>
            {companies.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name}
              </option>
            ))}
          </select>
          <p className="field-hint muted small">
            {t("hours_admin.company_selector_hint")}
          </p>
        </div>
      )}

      {tab === "entries" && (
        <>
          <div
            className="card"
            style={{ padding: "16px 18px", marginBottom: 16 }}
            data-testid="hours-filters"
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                gap: 12,
              }}
            >
              {/* Sprint 152.2 — the SHARED filter row. The Overview tab
                  filters the same collection with the same three
                  controls; a second hand-maintained copy is the
                  "written once, omitted elsewhere" defect this project
                  keeps paying for. */}
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
                data-testid="hours-filters-reset"
                onClick={() => {
                  setFilters(EMPTY_FILTERS);
                  setPage(1);
                }}
              >
                {t("hours_admin.filter_reset")}
              </button>
              {/* The CSV button moved into the report heading (Sprint
                  152.1) — it exports the REPORT, and sitting among the
                  filters made it read as "export the table". */}
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

          {/* Sprint 152.1 — the REPORT section. `build_summary` has
              computed `by_week` since Sprint 152 and the frontend typed
              it, but nothing rendered it: the per-week breakdown is one
              of the five things the agreed design asked for and the
              owner could not find it.

              Kept on the entries tab rather than given its own "Rapport"
              tab, deliberately. The totals are computed from the SAME
              filter object as the table above them, so the numbers
              always describe the rows on screen — a separate tab would
              buy discoverability and put that property at risk the first
              time the two drifted. Made unmissable with a titled section
              instead. */}
          {summary && (
            <section
              className="card"
              style={{ padding: "18px 22px", marginBottom: 16 }}
              data-testid="hours-summary"
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between",
                  gap: 12,
                  marginBottom: 12,
                }}
              >
                <div>
                  <h3 className="section-title" style={{ margin: 0 }}>
                    {t("hours_admin.report_title")}
                  </h3>
                  <p className="muted small" style={{ margin: "4px 0 0" }}>
                    {t("hours_admin.report_subtitle")}
                  </p>
                </div>
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

              {summary.total_entries === 0 ? (
                /* Words, not a wall of 0.00 — a grid of zeroes reads as
                   a broken feature rather than an empty filter. */
                <p className="muted" style={{ margin: 0 }}
                   data-testid="hours-summary-empty">
                  {t("hours_admin.report_empty")}
                </p>
              ) : (
                <>
                  <div className="detail-kv-list">
                    <div className="detail-kv-row">
                      <span className="detail-kv-label">
                        {t("hours_admin.summary_entries")}
                      </span>
                      <span
                        className="detail-kv-val"
                        data-testid="hours-summary-entries"
                      >
                        {summary.total_entries}
                      </span>
                    </div>
                    <div className="detail-kv-row">
                      <span className="detail-kv-label">
                        {t("hours_admin.summary_hours")}
                      </span>
                      <span
                        className="detail-kv-val"
                        data-testid="hours-summary-hours"
                      >
                        {summary.total_hours}
                      </span>
                    </div>
                    <div className="detail-kv-row">
                      <span className="detail-kv-label">
                        {t("hours_admin.summary_weighted")}
                      </span>
                      <span
                        className="detail-kv-val"
                        data-testid="hours-summary-weighted"
                      >
                        {summary.total_weighted_hours}
                      </span>
                    </div>
                  </div>

                  <h4
                    className="eyebrow"
                    style={{ margin: "18px 0 8px" }}
                  >
                    {t("hours_admin.report_by_hour_type")}
                  </h4>
                  <div className="table-wrap">
                    <table
                      className="data-table"
                      data-testid="hours-report-by-hour-type"
                    >
                      <thead>
                        <tr>
                          <th>{t("hours_admin.col_hour_type")}</th>
                          {/* Labelled "current" because it is: the
                              weighted total beside it comes from the
                              SNAPSHOTS, so after a multiplier edit that
                              left closed weeks alone the two can
                              legitimately disagree. Naming the column
                              is what stops an operator concluding the
                              numbers are wrong. */}
                          <th>{t("hours_admin.col_current_multiplier")}</th>
                          <th>{t("hours_admin.col_entries")}</th>
                          <th>{t("hours_admin.col_hours")}</th>
                          <th>{t("hours_admin.col_weighted_from_snapshot")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {summary.by_hour_type.map((bucket) => (
                          <tr
                            key={bucket.hour_type}
                            data-testid="hours-report-hour-type-row"
                          >
                            <td>{bucket.hour_type_name}</td>
                            <td className="muted small">
                              x{bucket.current_multiplier}
                            </td>
                            <td className="muted small">{bucket.entries}</td>
                            <td>{bucket.hours}</td>
                            <td className="muted">{bucket.weighted_hours}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <h4
                    className="eyebrow"
                    style={{ margin: "18px 0 8px" }}
                  >
                    {t("hours_admin.report_by_week")}
                  </h4>
                  <div className="table-wrap">
                    <table
                      className="data-table"
                      data-testid="hours-report-by-week"
                    >
                      <thead>
                        <tr>
                          <th>{t("hours_admin.col_week")}</th>
                          <th>{t("hours_admin.col_period")}</th>
                          <th>{t("hours_admin.col_entries")}</th>
                          <th>{t("hours_admin.col_hours")}</th>
                          <th>{t("hours_admin.col_weighted")}</th>
                          <th>{t("hours_admin.col_week_status")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {summary.by_week.map((bucket) => (
                          <tr
                            key={`${bucket.iso_year}-${bucket.iso_week}`}
                            data-testid="hours-report-week-row"
                            data-closed={bucket.is_closed ? "true" : "false"}
                          >
                            <td>
                              {bucket.iso_year}-W
                              {String(bucket.iso_week).padStart(2, "0")}
                            </td>
                            <td className="muted small">
                              {formatDate(bucket.week_start, dateLocale)} –{" "}
                              {formatDate(bucket.week_end, dateLocale)}
                            </td>
                            <td className="muted small">{bucket.entries}</td>
                            <td>{bucket.hours}</td>
                            <td className="muted">{bucket.weighted_hours}</td>
                            <td>
                              <span
                                className={
                                  bucket.is_closed
                                    ? "badge badge-closed"
                                    : "badge badge-approved"
                                }
                              >
                                {bucket.is_closed
                                  ? t("weeks.status_closed")
                                  : t("weeks.status_open")}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </section>
          )}

          {loading ? (
            <div className="loading-bar">
              <div className="loading-bar-fill" />
            </div>
          ) : (
            <div className="card" data-testid="hours-entries-list">
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
                      <th>{t("hours_admin.col_actions")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((entry) => (
                      <tr
                        key={entry.id}
                        data-testid="hours-entry-row"
                        data-entry-id={entry.id}
                        data-locked={entry.is_locked ? "true" : "false"}
                      >
                        <td>{formatDate(entry.date, dateLocale)}</td>
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
                        <td>{entry.hour_type_name}</td>
                        <td>{entry.hours}</td>
                        <td className="muted">{entry.weighted_hours}</td>
                        <td className="muted small">
                          {entry.building_name ?? "—"}
                        </td>
                        <td className="muted small">{entry.note || "—"}</td>
                        <td>
                          <div style={{ display: "flex", gap: 6 }}>
                            {/* Disabled on a locked week: the server
                                refuses the write either way, this only
                                avoids offering an action that cannot
                                succeed. */}
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              data-testid="hours-entry-edit-button"
                              onClick={() => openEditEntry(entry)}
                              disabled={entry.is_locked}
                            >
                              {t("hours_admin.edit_button")}
                            </button>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              data-testid="hours-entry-delete-button"
                              onClick={() => openDeleteEntry(entry)}
                              disabled={entry.is_locked}
                            >
                              {t("hours_admin.delete_button")}
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
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
                  justifyContent: "space-between",
                  gap: 12,
                  padding: "12px 16px",
                }}
                data-testid="hours-entries-pagination"
              >
                <span className="muted small">
                  {t("hours_admin.pagination_summary", {
                    shown: entries.length,
                    total: entryCount,
                  })}
                </span>
                <div style={{ display: "flex", gap: 8 }}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="hours-entries-prev"
                    onClick={() => setPage((current) => Math.max(1, current - 1))}
                    disabled={page <= 1}
                  >
                    {t("hours_admin.prev_page")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid="hours-entries-next"
                    onClick={() => setPage((current) => current + 1)}
                    disabled={!hasNext}
                  >
                    {t("hours_admin.next_page")}
                  </button>
                </div>
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

      {entryMode !== null && (
        <div
          data-testid="hours-entry-modal"
          role="dialog"
          aria-modal="true"
          aria-label={
            entryMode === "create"
              ? t("hours_admin.add_entry_modal_title")
              : t("hours_admin.edit_entry_modal_title")
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
            onSubmit={handleEntrySubmit}
            className="card"
            style={{
              maxWidth: 560,
              width: "100%",
              padding: 24,
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <h3 style={{ marginTop: 0, marginBottom: 12 }}>
              {entryMode === "create"
                ? t("hours_admin.add_entry_modal_title")
                : t("hours_admin.edit_entry_modal_title")}
            </h3>

            {entryFormError && (
              <div
                className="alert-error"
                role="alert"
                style={{ marginBottom: 12 }}
                data-testid="hours-entry-modal-error"
              >
                {entryFormError}
              </div>
            )}

            <div className="field">
              <label className="field-label" htmlFor="hours-entry-employee">
                {t("hours_admin.field_employee")} *
              </label>
              <select
                id="hours-entry-employee"
                className="field-select"
                value={effectiveFormEmployee}
                onChange={(event) =>
                  setEntryForm((prev) => ({
                    ...prev,
                    employee: event.target.value,
                  }))
                }
                data-testid="hours-entry-input-employee"
                required
                disabled={entryFormBusy}
              >
                <option value="">
                  {t("hours_admin.field_employee_empty")}
                </option>
                {employees.map((employee) => (
                  <option key={employee.id} value={employee.id}>
                    {employee.full_name || employee.email}
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="hours-entry-date">
                {t("my_hours.field_date")} *
              </label>
              <input
                id="hours-entry-date"
                className="field-input"
                type="date"
                value={entryForm.date}
                onChange={(event) =>
                  setEntryForm((prev) => ({
                    ...prev,
                    date: event.target.value,
                  }))
                }
                data-testid="hours-entry-input-date"
                required
                disabled={entryFormBusy}
              />
              <div className="muted small" style={{ marginTop: 4 }}>
                {t("my_hours.field_date_hint")}
              </div>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="hours-entry-hour-type">
                {t("my_hours.field_hour_type")} *
              </label>
              <select
                id="hours-entry-hour-type"
                className="field-select"
                value={effectiveFormHourType}
                onChange={(event) =>
                  setEntryForm((prev) => ({
                    ...prev,
                    hour_type: event.target.value,
                  }))
                }
                data-testid="hours-entry-input-hour-type"
                required
                disabled={entryFormBusy}
              >
                <option value="">
                  {t("my_hours.field_hour_type_empty")}
                </option>
                {activeHourTypes.map((hourType) => (
                  <option key={hourType.id} value={hourType.id}>
                    {hourType.name} (x{hourType.multiplier})
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="hours-entry-hours">
                {t("my_hours.field_hours")} *
              </label>
              <input
                id="hours-entry-hours"
                className="field-input"
                type="number"
                min="0.25"
                max="24"
                step="0.25"
                value={entryForm.hours}
                onChange={(event) =>
                  setEntryForm((prev) => ({
                    ...prev,
                    hours: event.target.value,
                  }))
                }
                data-testid="hours-entry-input-hours"
                required
                disabled={entryFormBusy}
              />
            </div>

            <div className="field">
              <label className="field-label" htmlFor="hours-entry-building">
                {t("my_hours.field_building")}
              </label>
              <select
                id="hours-entry-building"
                className="field-select"
                value={effectiveFormBuilding}
                onChange={(event) =>
                  setEntryForm((prev) => ({
                    ...prev,
                    building: event.target.value,
                  }))
                }
                data-testid="hours-entry-input-building"
                disabled={entryFormBusy}
              >
                <option value="">{t("my_hours.field_building_empty")}</option>
                {buildings.map((building) => (
                  <option key={building.id} value={building.id}>
                    {building.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label className="field-label" htmlFor="hours-entry-note">
                {t("my_hours.field_note")}
              </label>
              <textarea
                id="hours-entry-note"
                className="field-input"
                rows={3}
                value={entryForm.note}
                onChange={(event) =>
                  setEntryForm((prev) => ({
                    ...prev,
                    note: event.target.value,
                  }))
                }
                data-testid="hours-entry-input-note"
                disabled={entryFormBusy}
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
                onClick={closeEntryModal}
                disabled={entryFormBusy}
                data-testid="hours-entry-modal-cancel"
              >
                {t("my_hours.cancel")}
              </button>
              <button
                type="submit"
                className="btn btn-primary btn-sm"
                disabled={entryFormBusy}
                data-testid="hours-entry-modal-save"
              >
                {entryFormBusy ? t("admin_form.saving") : t("my_hours.save")}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Unconditionally rendered and ref-driven (CLAUDE.md §3): a
          native <dialog> wrapped in a condition mounts INVISIBLE and its
          trigger button looks dead. */}
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
