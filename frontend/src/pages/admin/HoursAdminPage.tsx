import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { listAllBuildings, listAllCompanies, listProviderEmployees } from "../../api/admin";
import { getApiError } from "../../api/client";
import {
  downloadTimesheetSummaryCsv,
  fetchTimesheetSummary,
  listHourTypes,
  listTimeEntries,
} from "../../api/timesheets";
import type {
  HourType,
  TimeEntry,
  TimeEntryFilters,
  TimesheetSummary,
} from "../../api/timesheets.types";
import type {
  BuildingAdmin,
  CompanyAdmin,
  ProviderEmployee,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { BoundedList } from "../../components/BoundedList";
import { PageHeader } from "../../components/PageHeader";
import { useToast } from "../../components/ToastProvider";
import { fromDateString } from "../../lib/isoWeek";
import { HourTypesTab } from "./HourTypesTab";
import { WeekCloseTab } from "./WeekCloseTab";

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
  const [employees, setEmployees] = useState<ProviderEmployee[]>([]);
  const [hourTypes, setHourTypes] = useState<HourType[]>([]);
  const [buildings, setBuildings] = useState<BuildingAdmin[]>([]);

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
      // The existing provider directory, called with no extra params.
      // `/api/employees/` takes no `?company=` — it scopes by VIEWER —
      // and widening it would change an endpoint the Employees page
      // shares, which is not this sprint's to change (CLAUDE.md's
      // pagination_class lesson, same principle). For a COMPANY_ADMIN
      // that is already exactly their own company. For a SUPER_ADMIN on
      // a multi-tenant deployment the dropdown spans companies — the
      // same set the Employees page already shows them — and picking
      // someone outside the selected company simply yields an empty
      // table, because the entries query is pinned to that company.
      listProviderEmployees(),
      listHourTypes(company === "" ? {} : { company }),
      listAllBuildings({
        is_active: "true",
        ...(company === "" ? {} : { company }),
      }),
    ])
      .then(([employeePage, types, buildingRows]) => {
        if (cancelled) return;
        setEmployees(employeePage.results);
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
          {t("hours_admin.tab_weeks")}
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
              <div className="field" style={{ margin: 0 }}>
                <label className="field-label" htmlFor="hours-filter-employee">
                  {t("hours_admin.filter_employee")}
                </label>
                <select
                  id="hours-filter-employee"
                  className="field-select"
                  value={filters.employee === "" ? "" : String(filters.employee)}
                  onChange={(event) =>
                    patchFilters({
                      employee:
                        event.target.value === ""
                          ? ""
                          : Number(event.target.value),
                    })
                  }
                  data-testid="hours-filter-employee"
                >
                  <option value="">{t("hours_admin.filter_all")}</option>
                  {employees.map((employee) => (
                    <option key={employee.id} value={employee.id}>
                      {employee.full_name || employee.email}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field" style={{ margin: 0 }}>
                <label className="field-label" htmlFor="hours-filter-hour-type">
                  {t("hours_admin.filter_hour_type")}
                </label>
                <select
                  id="hours-filter-hour-type"
                  className="field-select"
                  value={
                    filters.hour_type === "" ? "" : String(filters.hour_type)
                  }
                  onChange={(event) =>
                    patchFilters({
                      hour_type:
                        event.target.value === ""
                          ? ""
                          : Number(event.target.value),
                    })
                  }
                  data-testid="hours-filter-hour-type"
                >
                  <option value="">{t("hours_admin.filter_all")}</option>
                  {hourTypes.map((hourType) => (
                    <option key={hourType.id} value={hourType.id}>
                      {hourType.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field" style={{ margin: 0 }}>
                <label className="field-label" htmlFor="hours-filter-building">
                  {t("hours_admin.filter_building")}
                </label>
                <select
                  id="hours-filter-building"
                  className="field-select"
                  value={filters.building === "" ? "" : String(filters.building)}
                  onChange={(event) =>
                    patchFilters({
                      building:
                        event.target.value === ""
                          ? ""
                          : Number(event.target.value),
                    })
                  }
                  data-testid="hours-filter-building"
                >
                  <option value="">{t("hours_admin.filter_all")}</option>
                  {buildings.map((building) => (
                    <option key={building.id} value={building.id}>
                      {building.name}
                    </option>
                  ))}
                </select>
              </div>

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

          {summary && (
            <div
              className="card"
              style={{ padding: "18px 22px", marginBottom: 16 }}
              data-testid="hours-summary"
            >
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                {t("hours_admin.summary_title")}
              </div>
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
                {summary.by_hour_type.map((bucket) => (
                  <div className="detail-kv-row" key={bucket.hour_type}>
                    <span className="detail-kv-label">
                      {bucket.hour_type_name}
                    </span>
                    <span className="detail-kv-val">
                      {t("hours_admin.summary_bucket_value", {
                        hours: bucket.hours,
                        weighted: bucket.weighted_hours,
                      })}
                    </span>
                  </div>
                ))}
              </div>
            </div>
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

      {tab === "weeks" && <WeekCloseTab selectedCompany={company} />}
    </div>
  );
}
