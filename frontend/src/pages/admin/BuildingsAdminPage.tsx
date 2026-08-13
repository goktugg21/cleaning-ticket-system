import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getApiError } from "../../api/client";
import { SortableHeader } from "../../components/SortableHeader";
import type { SortState } from "../../components/SortableHeader";
import {
  bulkDeactivateBuildings,
  bulkLinkBuildings,
  bulkUpdateBuildings,
  deactivateBuilding,
  listAllCompanies,
  listAllCustomers,
  listBuildings,
  reactivateBuilding,
  updateBuilding,
  listBuildingTypes,
} from "../../api/admin";
import type { AdminListParams } from "../../api/admin";
import type {
  BuildingTypeOption,
  BuildingAdmin,
  CompanyAdmin,
  CustomerAdmin,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { BulkAssignDialog } from "../../components/BulkAssignDialog";
import { BulkEditDialog } from "../../components/BulkEditDialog";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { EditModeToggle } from "../../components/EditModeToggle";
import { MultiSelectToolbar } from "../../components/MultiSelectToolbar";
import { useEditMode } from "../../lib/useEditMode";
import { useSavedBanner } from "../../hooks/useSavedBanner";

type ActiveFilter = "true" | "false" | "all";

/**
 * Sprint 154 §E — the columns a header click can sort by. Each names a
 * `BuildingViewSet.ordering_fields` entry; the backend allowlist is the
 * authority and silently ignores anything not on it.
 */
type SortField = "name" | "city" | "created_at" | "is_active";
type SortDirection = "asc" | "desc";

const DEBOUNCE_MS = 300;

function formatDate(value: string, locale: string): string {
  try {
    return new Date(value).toLocaleDateString(locale, {
      year: "numeric",
      month: "short",
      day: "2-digit",
    });
  } catch {
    return value;
  }
}


/**
 * The Customers cell: the first two names plus a "+N" chip. Bounded on
 * purpose — a building in a shopping centre can serve dozens of
 * customers, and an unbounded cell looks fine on seed data and destroys
 * the row height on real data. The server sends at most three names plus
 * the true total (`customer_names`), so this never has the whole list to
 * leak in the first place.
 */
function CustomerNamesCell({
  names,
  total,
  moreLabel,
}: {
  names: string[];
  total: number;
  moreLabel: (n: number) => string;
}) {
  if (total === 0) return <span className="muted-empty">—</span>;
  const shown = names.slice(0, 2);
  const hidden = total - shown.length;
  return (
    <span className="building-customers-cell">
      {shown.join(", ")}
      {hidden > 0 && (
        <span className="cell-tag cell-tag-muted" style={{ marginLeft: 6 }}>
          {moreLabel(hidden)}
        </span>
      )}
    </span>
  );
}

export function BuildingsAdminPage() {
  const navigate = useNavigate();
  const { t, i18n } = useTranslation("common");
  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const [buildings, setBuildings] = useState<BuildingAdmin[]>([]);
  const [count, setCount] = useState(0);
  const [activeCount, setActiveCount] = useState<number | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [previous, setPrevious] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [searchInput, setSearchInput] = useState("");
  const [searchActive, setSearchActive] = useState("");
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("true");
  const [companyFilter, setCompanyFilter] = useState<number | "">("");
  // Sprint 178 §1 — the building-type filter and the catalog behind it.
  const [buildingTypeFilter, setBuildingTypeFilter] = useState<number | "">("");
  const [buildingTypes, setBuildingTypes] = useState<BuildingTypeOption[]>([]);
  const [sortField, setSortField] = useState<SortField>("name");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");

  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companiesLoaded, setCompaniesLoaded] = useState(false);

  // Sprint 154 §E/§F — bulk selection and its three actions.
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkBusy, setBulkBusy] = useState(false);
  const bulkDialogRef = useRef<ConfirmDialogHandle>(null);
  const [bulkEditOpen, setBulkEditOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignCustomerIds, setAssignCustomerIds] = useState<number[]>([]);
  const [assignOptions, setAssignOptions] = useState<CustomerAdmin[]>([]);
  const [assignError, setAssignError] = useState("");

  // Row edit-in-place, keyed by building id so the form seeds from the
  // prop on mount rather than from a syncing effect (CLAUDE.md §3).
  const [editTarget, setEditTarget] = useState<BuildingAdmin | null>(null);

  const [savedBanner, setSavedBanner] = useSavedBanner({
    saved: t("buildings.banner_saved"),
    deactivated: t("buildings.banner_deactivated"),
    reactivated: t("buildings.banner_reactivated"),
  });

  // Load companies once for the filter dropdown. Sprint 135 — fetched
  // exhaustively (listAllCompanies) so a tenant with more than one page
  // of companies still gets a complete dropdown, not a silently truncated
  // one.
  useEffect(() => {
    let cancelled = false;
    listAllCompanies({ is_active: "true" })
      .then((response) => {
        if (cancelled) return;
        setCompanies(response);
        // Auto-select for COMPANY_ADMIN with exactly one company in scope.
        if (response.length === 1) {
          setCompanyFilter(response[0].id);
        }
      })
      .finally(() => {
        if (!cancelled) setCompaniesLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const companyDropdownDisabled = companiesLoaded && companies.length <= 1;

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setSearchActive(searchInput.trim());
      setPage(1);
      // A hidden-but-selected row being archived is a real surprise, so
      // every narrowing of the view drops the selection. Done in the
      // handlers and in this settled timeout, never in an effect body.
      setSelectedIds([]);
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [searchInput]);

  /** Sprint 178 §1 — the catalog the filter offers.
   *
   *  Reloads when the company filter changes, and CLEARS the chosen type
   *  at the same time: type ids are per company, so a leftover id would
   *  filter another company's list by something it does not have and
   *  quietly return nothing. */
  useEffect(() => {
    let cancelled = false;
    // The chosen type is cleared by the company select's own handler, not
    // here: `react-hooks/set-state-in-effect` forbids a synchronous
    // setState in an effect body, and resetting where the operator ACTS
    // is the clearer place for it anyway.
    listBuildingTypes(companyFilter)
      .then((options) => {
        if (!cancelled) setBuildingTypes(options.filter((o) => o.is_active));
      })
      .catch(() => {
        if (!cancelled) setBuildingTypes([]);
      });
    return () => {
      cancelled = true;
    };
  }, [companyFilter]);

  const queryParams = useMemo<AdminListParams>(() => {
    const params: AdminListParams = { page };
    if (searchActive) params.search = searchActive;
    if (activeFilter !== "all") params.is_active = activeFilter;
    if (companyFilter !== "") params.company = companyFilter;
    // Sprint 178 §1 — THE point of the building-type catalog. The owner's
    // example is a type only one building uses that must still appear in
    // the filters; without this line the catalog is a dropdown, not a
    // taxonomy.
    if (buildingTypeFilter !== "") params.building_type = buildingTypeFilter;
    params.ordering = sortDirection === "desc" ? `-${sortField}` : sortField;
    return params;
  }, [
    page,
    searchActive,
    activeFilter,
    companyFilter,
    buildingTypeFilter,
    sortField,
    sortDirection,
  ]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await listBuildings(queryParams);
      setBuildings(response.results);
      setCount(response.count);
      setNext(response.next);
      setPrevious(response.previous);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setLoading(false);
    }
  }, [queryParams]);

  useEffect(() => {
    load();
  }, [load]);

  // The ACTIVE tile needs its own count — the rendered rows are one page.
  // `page_size=1` asks the server for the number and one throwaway row
  // rather than loosening `pagination_class`, which is a contract with
  // every other caller (Sprint 134 broke three viewsets that way; Sprint
  // 135 reverted it).
  const activeCountParams = useMemo<AdminListParams>(() => {
    const params: AdminListParams = { is_active: "true", page_size: 1 };
    if (companyFilter !== "") params.company = companyFilter;
    return params;
  }, [companyFilter]);

  const [countsReloadToken, setCountsReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    listBuildings(activeCountParams)
      .then((response) => {
        if (!cancelled) setActiveCount(response.count);
      })
      .catch(() => {
        if (!cancelled) setActiveCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [activeCountParams, countsReloadToken]);

  const companyName = useCallback(
    (id: number) =>
      companies.find((c) => c.id === id)?.name ??
      t("buildings.company_fallback", { id }),
    [companies, t],
  );

  const hasActiveFilters = Boolean(
    searchActive ||
      activeFilter !== "true" ||
      (companyFilter !== "" && !companyDropdownDisabled),
  );

  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";

  // --- sorting ---------------------------------------------------------
  const handleSort = useCallback(
    (field: SortField) => {
      if (sortField === field) {
        setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
      } else {
        setSortField(field);
        setSortDirection("asc");
      }
      setPage(1);
      setSelectedIds([]);
    },
    [sortField],
  );

  const sortStateFor = (field: SortField): SortState =>
    sortField !== field
      ? "none"
      : sortDirection === "asc"
        ? "ascending"
        : "descending";

  // --- selection -------------------------------------------------------
  const pageIds = useMemo(() => buildings.map((b) => b.id), [buildings]);
  const selectedOnPage = useMemo(
    () => selectedIds.filter((id) => pageIds.includes(id)),
    [selectedIds, pageIds],
  );
  const allOnPageSelected =
    pageIds.length > 0 && selectedOnPage.length === pageIds.length;

  const toggleRow = (id: number) =>
    setSelectedIds((current) =>
      current.includes(id)
        ? current.filter((existing) => existing !== id)
        : [...current, id],
    );

  const togglePage = () =>
    setSelectedIds((current) =>
      allOnPageSelected
        ? current.filter((id) => !pageIds.includes(id))
        : [...new Set([...current, ...pageIds])],
    );

  // Sprint 155 §4 — nothing is directly editable. The checkbox column
  // and the bulk toolbar exist only inside edit mode; outside it this is
  // a clean read-only list whose rows still navigate to the detail page.
  //
  // The MODE comes from the shared controller so the derived-mode rule
  // lives in one place, but the SELECTION stays this page's own: it
  // spans pages (select-all unions the current page into what is already
  // chosen) and the hook's selection is filtered to the keys it is
  // handed, which here is one page. `onExit` keeps "leaving edit mode
  // clears the selection" true anyway.
  const edit = useEditMode(pageIds, { onExit: () => setSelectedIds([]) });

  // --- bulk actions ----------------------------------------------------

  async function handleConfirmBulkDelete() {
    if (selectedIds.length === 0) return;
    setBulkBusy(true);
    setError("");
    const targeted = [...selectedIds];
    try {
      const result = await bulkDeactivateBuildings(targeted);
      bulkDialogRef.current?.close();
      // Local state FIRST, refetch after: the server call already
      // succeeded, so the row state is known here.
      setBuildings((current) =>
        current.map((b) =>
          targeted.includes(b.id) ? { ...b, is_active: false } : b,
        ),
      );
      setSelectedIds([]);
      setSavedBanner(
        t("buildings.banner_bulk_deleted", { count: result.deactivated }),
      );
      setCountsReloadToken((token) => token + 1);
      await load();
    } catch (err) {
      setError(getApiError(err));
      bulkDialogRef.current?.close();
    } finally {
      setBulkBusy(false);
    }
  }

  async function handleBulkEdit(patch: Record<string, string>) {
    setBulkBusy(true);
    setError("");
    try {
      const result = await bulkUpdateBuildings([...selectedIds], patch);
      setBulkEditOpen(false);
      setSelectedIds([]);
      setSavedBanner(t("bulk_edit.updated", { count: result.updated }));
      setCountsReloadToken((token) => token + 1);
      await load();
    } catch (err) {
      setError(getApiError(err));
      setBulkEditOpen(false);
    } finally {
      setBulkBusy(false);
    }
  }

  // --- assign customers (§F, the buildings-side direction) -------------

  function openAssignCustomers() {
    setAssignCustomerIds([]);
    setAssignError("");
    setAssignOpen(true);
    // Exhaustive paging (the Sprint 120/135 pattern) so a provider with
    // hundreds of customers gets all of them, not a truncated first page.
    const company =
      companyFilter !== ""
        ? companyFilter
        : buildings.find((b) => selectedIds.includes(b.id))?.company;
    listAllCustomers(
      company === undefined
        ? { is_active: "true" }
        : { is_active: "true", company },
    )
      .then(setAssignOptions)
      .catch((err) => setAssignError(getApiError(err)));
  }

  async function handleConfirmAssignCustomers() {
    setBulkBusy(true);
    setAssignError("");
    try {
      const result = await bulkLinkBuildings({
        buildings: selectedIds,
        relation: "customers",
        targets: assignCustomerIds,
        mode: "link",
      });
      setAssignOpen(false);
      setSelectedIds([]);
      setSavedBanner(t("bulk_link.linked", { count: result.created }));
      await load();
    } catch (err) {
      setAssignError(getApiError(err));
    } finally {
      setBulkBusy(false);
    }
  }

  function handleEditSaved(updated: BuildingAdmin) {
    setEditTarget(null);
    setBuildings((current) =>
      current.map((b) => (b.id === updated.id ? { ...b, ...updated } : b)),
    );
    setSavedBanner(t("buildings.banner_saved"));
    setCountsReloadToken((token) => token + 1);
  }

  const moreLabel = (n: number) => t("buildings.more_customers", { count: n });

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("nav.admin_group")}
          </div>
          <h2 className="page-title">{t("nav.buildings")}</h2>
          <p className="page-sub">
            {loading ? t("buildings.loading") : t("buildings.count", { count })}
          </p>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={load}
            disabled={loading}
          >
            <RefreshCw size={14} strokeWidth={2.5} />
            {t("refresh")}
          </button>
          <Link className="btn btn-primary btn-sm" to="/admin/buildings/new">
            <Plus size={14} strokeWidth={2.5} />
            {t("admin.create_new")}
          </Link>
        </div>
      </div>

      {savedBanner && (
        <div className="alert-info" style={{ marginBottom: 16 }} role="status">
          {savedBanner}
        </div>
      )}

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      <div className="card" style={{ overflow: "hidden" }}>
        {/* Tiles inside the list card, above the filter bar, so the page
            reads as one block instead of header-gap-filters-gap-table. */}
        <div
          className="summary-grid"
          data-testid="buildings-stat-tiles"
          style={{
            gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
            margin: "14px 18px 4px",
          }}
        >
          <div className="summary-stat" data-testid="buildings-stat-total">
            <span className="summary-stat-label">
              {t("buildings.stat_total")}
            </span>
            <span className="summary-stat-value">{count}</span>
            <span className="summary-stat-meta">
              {t("buildings.stat_total_meta")}
            </span>
          </div>
          <div className="summary-stat" data-testid="buildings-stat-active">
            <span className="summary-stat-label">
              {t("buildings.stat_active")}
            </span>
            <span className="summary-stat-value">{activeCount ?? "—"}</span>
            <span className="summary-stat-meta">
              {t("buildings.stat_active_meta")}
            </span>
          </div>
        </div>

        <form
          className="filter-bar"
          onSubmit={(event) => {
            event.preventDefault();
            setSearchActive(searchInput.trim());
            setPage(1);
            setSelectedIds([]);
          }}
        >
          <div className="filter-field search">
            <span className="filter-label">{t("search")}</span>
            <input
              className="filter-control"
              type="search"
              placeholder={t("buildings.search_placeholder")}
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </div>
          <div className="filter-field">
            <span className="filter-label">{t("status")}</span>
            <select
              className="filter-control"
              value={activeFilter}
              onChange={(event) => {
                setActiveFilter(event.target.value as ActiveFilter);
                setPage(1);
                setSelectedIds([]);
              }}
            >
              <option value="true">{t("admin.status_active")}</option>
              <option value="false">{t("admin.status_inactive")}</option>
              <option value="all">{t("admin.status_all")}</option>
            </select>
          </div>
          {/* Sprint 178 §1 — filter by the company's own building type.
              Shown only when there is a catalog to filter BY: an empty
              dropdown is a control that looks broken. */}
          {buildingTypes.length > 0 && (
            <div className="filter-field">
              <span className="filter-label">
                {t("buildings.filter_building_type")}
              </span>
              <select
                className="filter-control"
                style={{ maxWidth: 220 }}
                value={buildingTypeFilter === "" ? "" : String(buildingTypeFilter)}
                onChange={(event) => {
                  const value = event.target.value;
                  setBuildingTypeFilter(value === "" ? "" : Number(value));
                  setPage(1);
                  setSelectedIds([]);
                }}
                data-testid="buildings-filter-building-type"
              >
                <option value="">{t("buildings.filter_type_all")}</option>
                {buildingTypes.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="filter-field">
            <span className="filter-label">{t("company")}</span>
            {/* Cap the Company select so it matches Search / Status instead
                of stretching to fill the filter-bar's 1fr track. */}
            <select
              className="filter-control"
              style={{ maxWidth: 220 }}
              value={companyFilter === "" ? "" : String(companyFilter)}
              onChange={(event) => {
                const v = event.target.value;
                setCompanyFilter(v === "" ? "" : Number(v));
                // Sprint 178 §1 — type ids are PER COMPANY, so a leftover
                // id would filter the new company's list by something it
                // does not have and quietly return nothing.
                setBuildingTypeFilter("");
                setPage(1);
                setSelectedIds([]);
              }}
              disabled={companyDropdownDisabled}
            >
              <option value="">{t("admin.all_companies")}</option>
              {companies.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-actions">
            {hasActiveFilters && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                data-testid="filters-clear"
                onClick={() => {
                  setSearchInput("");
                  setActiveFilter("true");
                  if (!companyDropdownDisabled) setCompanyFilter("");
                  setPage(1);
                  setSelectedIds([]);
                }}
              >
                {t("clear")}
              </button>
            )}
            {/* Sprint 155 §4 — the intent step. Hidden, not disabled,
                when the page has no rows: a control that cannot work
                should not be offered (the running Sprint 138-143
                theme). */}
            {pageIds.length > 0 && (
              <EditModeToggle
                editMode={edit.editMode}
                onToggle={edit.toggleMode}
                disabled={bulkBusy}
                testId="buildings-edit-mode-toggle"
              />
            )}
          </div>
        </form>

        {edit.editMode && (
          <MultiSelectToolbar
            selectedCount={selectedIds.length}
            onSelectAll={() =>
              setSelectedIds((current) => [...new Set([...current, ...pageIds])])
            }
            onClearAll={() => setSelectedIds([])}
            disabled={bulkBusy}
            actions={[
              // "Delete" is what an operator means; the server archives.
              // The confirm body says so, so label and behaviour agree.
              {
                key: "delete",
                label: t("buildings.bulk_delete"),
                destructive: true,
                onClick: () => bulkDialogRef.current?.open(),
              },
              {
                key: "edit",
                label: t("buildings.bulk_edit"),
                onClick: () => setBulkEditOpen(true),
              },
              {
                key: "assign-customers",
                label: t("buildings.assign_customers"),
                onClick: () => openAssignCustomers(),
              },
            ]}
            testIdPrefix="buildings-bulk"
          />
        )}

        {loading && (
          <div className="loading-bar" style={{ margin: 0 }}>
            <div className="loading-bar-fill" />
          </div>
        )}

        <div className="table-wrap admin-list-wrap">
          <table className="data-table data-table-dense">
            <thead>
              <tr>
                {edit.editMode && (
                  <th className="th-select">
                    <input
                      type="checkbox"
                      checked={allOnPageSelected}
                      onChange={togglePage}
                      disabled={pageIds.length === 0 || bulkBusy}
                      aria-label={t("buildings.select_page")}
                      data-testid="buildings-select-page"
                    />
                  </th>
                )}
                <SortableHeader
                  label={t("admin.col_name")}
                  sort={sortStateFor("name")}
                  testId="buildings-sort-name"
                  onSort={() => handleSort("name")}
                  sortByLabel={t("buildings.sort_by", {
                    column: t("admin.col_name"),
                  })}
                />
                <th>{t("company")}</th>
                <SortableHeader
                  label={t("buildings.col_city")}
                  sort={sortStateFor("city")}
                  testId="buildings-sort-city"
                  onSort={() => handleSort("city")}
                  sortByLabel={t("buildings.sort_by", {
                    column: t("buildings.col_city"),
                  })}
                />
                <th>{t("buildings.col_customers")}</th>
                <SortableHeader
                  label={t("created")}
                  sort={sortStateFor("created_at")}
                  testId="buildings-sort-created_at"
                  onSort={() => handleSort("created_at")}
                  sortByLabel={t("buildings.sort_by", { column: t("created") })}
                />
                <SortableHeader
                  label={t("status")}
                  sort={sortStateFor("is_active")}
                  testId="buildings-sort-is_active"
                  onSort={() => handleSort("is_active")}
                  sortByLabel={t("buildings.sort_by", { column: t("status") })}
                />
                <th aria-label={t("admin.col_actions")} />
              </tr>
            </thead>
            <tbody>
              {buildings.map((building) => {
                const detailPath = `/admin/buildings/${building.id}`;
                const openDetail = () => navigate(detailPath);
                return (
                  <tr
                    key={building.id}
                    className="admin-row-clickable"
                    role="link"
                    tabIndex={0}
                    aria-label={t("admin.view") + ": " + building.name}
                    onClick={openDetail}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openDetail();
                      }
                    }}
                  >
                    {edit.editMode && (
                      <td
                        className="td-select"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <input
                          type="checkbox"
                          checked={selectedIds.includes(building.id)}
                          onChange={() => toggleRow(building.id)}
                          disabled={bulkBusy}
                          aria-label={t("buildings.select_row", {
                            name: building.name,
                          })}
                          data-testid={`buildings-select-${building.id}`}
                        />
                      </td>
                    )}
                    <td className="td-subject">
                      <Link to={detailPath}>{building.name}</Link>
                    </td>
                    <td>{companyName(building.company)}</td>
                    <td>
                      {[building.city, building.postal_code]
                        .filter(Boolean)
                        .join(" ") || "—"}
                    </td>
                    <td>
                      <CustomerNamesCell
                        names={building.customer_names?.names ?? []}
                        total={
                          building.customer_names?.total ??
                          building.customer_count ??
                          0
                        }
                        moreLabel={moreLabel}
                      />
                    </td>
                    <td className="td-date">
                      {formatDate(building.created_at, dateLocale)}
                    </td>
                    <td>
                      <span
                        className={`cell-tag cell-tag-${building.is_active ? "open" : "closed"}`}
                      >
                        <i />
                        {building.is_active
                          ? t("admin.status_active")
                          : t("admin.status_inactive")}
                      </span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        data-testid={`buildings-edit-${building.id}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          setEditTarget(building);
                        }}
                      >
                        {t("admin.edit")}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Sprint 22 final polish: phone-width parallel card list. Every
            column change above is mirrored here, or the phone layout
            silently drifts from the table. */}
        <ul
          className="admin-card-list"
          data-testid="admin-card-list"
          aria-label={t("nav.buildings")}
        >
          {buildings.map((building) => {
            const detailPath = `/admin/buildings/${building.id}`;
            const address = [building.city, building.postal_code]
              .filter(Boolean)
              .join(" ");
            return (
              <li key={building.id} className="admin-card">
                <Link
                  to={detailPath}
                  className="admin-card-link"
                  aria-label={`${t("admin.view")}: ${building.name}`}
                >
                  <div className="admin-card-head">
                    <span className="admin-card-title">{building.name}</span>
                    <span
                      className={`cell-tag cell-tag-${building.is_active ? "open" : "closed"}`}
                    >
                      <i />
                      {building.is_active
                        ? t("admin.status_active")
                        : t("admin.status_inactive")}
                    </span>
                  </div>
                  <dl className="admin-card-meta">
                    <div className="admin-card-meta-row">
                      <dt>{t("company")}</dt>
                      <dd>{companyName(building.company)}</dd>
                    </div>
                    {address && (
                      <div className="admin-card-meta-row">
                        <dt>{t("buildings.col_city")}</dt>
                        <dd>{address}</dd>
                      </div>
                    )}
                    <div className="admin-card-meta-row">
                      <dt>{t("buildings.col_customers")}</dt>
                      <dd>
                        <CustomerNamesCell
                          names={building.customer_names?.names ?? []}
                          total={
                            building.customer_names?.total ??
                            building.customer_count ??
                            0
                          }
                          moreLabel={moreLabel}
                        />
                      </dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("created")}</dt>
                      <dd>{formatDate(building.created_at, dateLocale)}</dd>
                    </div>
                  </dl>
                </Link>
                <div className="admin-card-actions">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid={`buildings-card-edit-${building.id}`}
                    onClick={() => setEditTarget(building)}
                  >
                    {t("admin.edit")}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>

        {!loading && buildings.length === 0 && (
          <div className="empty-state">
            <div className="empty-icon">＋</div>
            <div className="empty-title">
              {hasActiveFilters
                ? t("buildings.empty_filtered_title")
                : t("buildings.empty_initial_title")}
            </div>
            <p className="empty-sub">
              {hasActiveFilters
                ? t("admin.empty_filtered_desc")
                : t("buildings.empty_initial_desc")}
            </p>
            {!hasActiveFilters && (
              <Link className="btn btn-primary btn-sm" to="/admin/buildings/new">
                {t("buildings.create")}
              </Link>
            )}
          </div>
        )}

        {(previous || next) && (
          <div className="pagination">
            <span className="pagination-info">
              {t("admin.pagination_page", { page, total: count })}
            </span>
            <div className="pagination-controls">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={loading || !previous || page <= 1}
                onClick={() => {
                  setPage((current) => Math.max(1, current - 1));
                  setSelectedIds([]);
                }}
              >
                {t("previous")}
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={loading || !next}
                onClick={() => {
                  setPage((current) => current + 1);
                  setSelectedIds([]);
                }}
              >
                {t("next")}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Rendered UNCONDITIONALLY and driven through the ref. A native
          <dialog> behind `{cond && ...}` is invisible and its trigger
          looks dead (Sprint 128); unmounting an open one can leave the
          page inert (Sprint 118). CLAUDE.md §3. */}
      <ConfirmDialog
        ref={bulkDialogRef}
        title={t("buildings.bulk_delete_title")}
        body={t("buildings.bulk_delete_body", { count: selectedIds.length })}
        confirmLabel={t("buildings.bulk_delete")}
        onConfirm={handleConfirmBulkDelete}
        busy={bulkBusy}
        destructive
      />

      {bulkEditOpen && (
        <BulkEditDialog
          title={t("buildings.bulk_edit_title", { count: selectedIds.length })}
          intro={t("buildings.bulk_edit_intro")}
          fields={[
            {
              key: "city",
              label: t("buildings.field_city"),
              type: "text",
              placeholder: t("bulk_edit.leave_unchanged"),
            },
            {
              key: "postal_code",
              label: t("buildings.field_postal_code"),
              type: "text",
              placeholder: t("bulk_edit.leave_unchanged"),
            },
            {
              key: "country",
              label: t("buildings.field_country"),
              type: "text",
              placeholder: t("bulk_edit.leave_unchanged"),
            },
            {
              key: "status",
              label: t("buildings.field_status"),
              options: [
                { value: "active", label: t("admin.status_active") },
                { value: "inactive", label: t("admin.status_inactive") },
              ],
            },
          ]}
          onCancel={() => setBulkEditOpen(false)}
          onSubmit={handleBulkEdit}
          busy={bulkBusy}
          testIdPrefix="buildings-bulk-edit"
        />
      )}

      {assignOpen && (
        <BulkAssignDialog
          title={t("buildings.assign_customers_title")}
          summary={t("buildings.assign_customers_summary", {
            customers: assignCustomerIds.length,
            buildings: selectedIds.length,
          })}
          options={assignOptions.map((c) => ({
            id: c.id,
            label: c.name,
            sublabel: c.contact_email,
          }))}
          selectedIds={assignCustomerIds}
          onChange={setAssignCustomerIds}
          onCancel={() => setAssignOpen(false)}
          onConfirm={handleConfirmAssignCustomers}
          confirmLabel={t("bulk_link.confirm")}
          busy={bulkBusy}
          error={assignError}
          emptyText={t("buildings.assign_customers_empty")}
          contextTitle={t("buildings.selected_buildings")}
          contextItems={buildings
            .filter((b) => selectedIds.includes(b.id))
            .map((b) => b.name)}
          testIdPrefix="buildings-assign-customers"
        />
      )}

      {editTarget && (
        <BuildingQuickEditDialog
          key={editTarget.id}
          building={editTarget}
          canReactivate={isSuperAdmin}
          onClose={() => setEditTarget(null)}
          onSaved={handleEditSaved}
        />
      )}
    </div>
  );
}

/**
 * Sprint 154 §E — edit a building's basics without leaving the list.
 * The full `BuildingFormPage` route is untouched and still linked from
 * the foot of this dialog.
 *
 * Keyed by building id by the parent, so the initial state below seeds
 * from the prop exactly once per building — no effect syncing prop to
 * state (CLAUDE.md §3).
 *
 * A non-native overlay, conditionally mounted; see `BulkAssignDialog`
 * for why that is the correct half of the CLAUDE.md dialog rule.
 */
function BuildingQuickEditDialog({
  building,
  canReactivate,
  onClose,
  onSaved,
}: {
  building: BuildingAdmin;
  canReactivate: boolean;
  onClose: () => void;
  onSaved: (updated: BuildingAdmin) => void;
}) {
  const { t } = useTranslation("common");
  const [name, setName] = useState(building.name);
  const [address, setAddress] = useState(building.address);
  const [city, setCity] = useState(building.city);
  const [postalCode, setPostalCode] = useState(building.postal_code);
  const [country, setCountry] = useState(building.country);
  const [isActive, setIsActive] = useState(building.is_active);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  // `is_active` is READ-ONLY on BuildingSerializer, exactly as it is on
  // the customer one, so status cannot ride along on the PATCH — DRF
  // would drop it silently and this dialog would report a save that
  // never happened. The lifecycle has its own two endpoints, and
  // reactivation is SUPER_ADMIN-only.
  const statusLocked = !building.is_active && !canReactivate;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFormError("");
    try {
      // Basics first: a COMPANY_ADMIN's scope excludes inactive
      // buildings, so patching after a deactivate would 404 on the row
      // it just deactivated.
      let updated = await updateBuilding(building.id, {
        name,
        address,
        city,
        postal_code: postalCode,
        country,
      });
      if (isActive !== building.is_active) {
        if (isActive) {
          updated = await reactivateBuilding(building.id);
        } else {
          await deactivateBuilding(building.id);
          updated = { ...updated, is_active: false };
        }
      }
      onSaved(updated);
    } catch (err) {
      setFormError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      data-testid="building-quick-edit-modal"
      role="dialog"
      aria-modal="true"
      aria-label={t("buildings.edit_dialog_title")}
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
        <h3 style={{ marginTop: 0, marginBottom: 4 }}>
          {t("buildings.edit_dialog_title")}
        </h3>
        <p className="muted small" style={{ marginTop: 0, marginBottom: 16 }}>
          {t("buildings.edit_dialog_intro")}
        </p>

        {formError && (
          <div
            className="alert-error"
            role="alert"
            style={{ marginBottom: 12 }}
            data-testid="building-quick-edit-error"
          >
            {formError}
          </div>
        )}

        <div className="field">
          <label className="field-label" htmlFor="building-quick-name">
            {t("buildings.field_name")} *
          </label>
          <input
            id="building-quick-name"
            className="field-input"
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            data-testid="building-quick-edit-name"
            required
            disabled={busy}
          />
        </div>

        <div className="field">
          <label className="field-label" htmlFor="building-quick-address">
            {t("buildings.field_address")}
          </label>
          <input
            id="building-quick-address"
            className="field-input"
            type="text"
            value={address}
            onChange={(event) => setAddress(event.target.value)}
            data-testid="building-quick-edit-address"
            disabled={busy}
          />
        </div>

        <div className="form-2col">
          <div className="field">
            <label className="field-label" htmlFor="building-quick-city">
              {t("buildings.field_city")}
            </label>
            <input
              id="building-quick-city"
              className="field-input"
              type="text"
              value={city}
              onChange={(event) => setCity(event.target.value)}
              data-testid="building-quick-edit-city"
              disabled={busy}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="building-quick-postal">
              {t("buildings.field_postal_code")}
            </label>
            <input
              id="building-quick-postal"
              className="field-input"
              type="text"
              value={postalCode}
              onChange={(event) => setPostalCode(event.target.value)}
              data-testid="building-quick-edit-postal-code"
              disabled={busy}
            />
          </div>
        </div>

        <div className="form-2col">
          <div className="field">
            <label className="field-label" htmlFor="building-quick-country">
              {t("buildings.field_country")}
            </label>
            <input
              id="building-quick-country"
              className="field-input"
              type="text"
              value={country}
              onChange={(event) => setCountry(event.target.value)}
              data-testid="building-quick-edit-country"
              disabled={busy}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="building-quick-status">
              {t("buildings.field_status")}
            </label>
            <select
              id="building-quick-status"
              className="field-select"
              value={isActive ? "true" : "false"}
              onChange={(event) => setIsActive(event.target.value === "true")}
              data-testid="building-quick-edit-status"
              disabled={busy || statusLocked}
            >
              <option value="true">{t("admin.status_active")}</option>
              <option value="false">{t("admin.status_inactive")}</option>
            </select>
          </div>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            flexWrap: "wrap",
            marginTop: 8,
          }}
        >
          <Link
            to={`/admin/buildings/${building.id}/edit`}
            className="btn btn-ghost btn-sm"
            data-testid="building-quick-edit-full-form"
          >
            {t("buildings.edit_dialog_full_form")}
          </Link>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onClose}
              disabled={busy}
              data-testid="building-quick-edit-cancel"
            >
              {t("cancel")}
            </button>
            <button
              type="submit"
              className="btn btn-primary btn-sm"
              disabled={busy}
              data-testid="building-quick-edit-save"
            >
              {busy ? t("admin_form.saving") : t("admin_form.save_changes")}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
