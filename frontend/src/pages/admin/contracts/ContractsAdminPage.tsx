import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { getApiError } from "../../../api/client";
import {
  deleteContract,
  getContractStats,
  listContracts,
} from "../../../api/contracts";
import type {
  Contract,
  ContractFilters,
  ContractStats,
  ContractStatus,
} from "../../../api/contracts.types";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";
import { EditModeToggle } from "../../../components/EditModeToggle";
import { MultiSelectToolbar } from "../../../components/MultiSelectToolbar";
import { SortableHeader } from "../../../components/SortableHeader";
import type { SortState } from "../../../components/SortableHeader";
import { useAuth } from "../../../auth/AuthContext";
import { canManageContracts } from "../../../auth/permissions";
import { useEditMode } from "../../../lib/useEditMode";
import { ContractFormDialog } from "./ContractFormDialog";
import { ContractTypesTab } from "./ContractTypesTab";
import {
  MAX_PROJECT_COLUMNS,
  buildProjectColumns,
  formatMoney,
  formatNumber,
  groupContracts,
  perPeriodValue,
  withGroupTotals,
} from "./contractTables";
import type {
  ContractGroupRow,
  GroupBy,
  Measure,
  Timeframe,
} from "./contractTables";

const DEBOUNCE_MS = 300;

type SortField =
  | "contract_no"
  | "customer"
  | "type"
  | "start_date"
  | "end_date"
  | "status";
type SortDirection = "asc" | "desc";

const STATUS_OPTIONS: ContractStatus[] = [
  "ACTIVE",
  "DRAFT",
  "EXPIRED",
  "CANCELLED",
];

/**
 * Sprint 160 §3 — the contracts list.
 *
 * The shape Sprints 154/155 settled for the other admin lists: dense
 * sortable table, `MultiSelectToolbar` behind the `useEditMode` gate,
 * and the parallel `.admin-card-list` for phone width kept in step with
 * the table rather than being a second, drifting layout.
 *
 * Three things here are specific to contracts and worth reading before
 * changing:
 *
 *  1. **Three views, ONE fetcher.** List / Customer Summary / Building
 *     Summary are three GROUPINGS of the same fetched page, derived in
 *     `contractTables.groupContracts`. Three fetchers would be three
 *     things to keep in step, and the summaries would silently disagree
 *     with the list the moment a filter changed on one and not the
 *     others.
 *  2. **The per-project columns are dynamic and BOUNDED.** They come
 *     from the contract lines, so the column set is per tenant. A table
 *     that grows a column per project looks fine on four projects and
 *     breaks on forty, so the top N by value are shown and the rest
 *     fold into one "Other" column that SAYS how many it swallowed
 *     (the Sprint 152.2 rule).
 *  3. **The stat tiles read the same filters as the table**, so they
 *     describe what is on screen rather than the whole tenant.
 */
export function ContractsAdminPage() {
  const navigate = useNavigate();
  const { t, i18n } = useTranslation("contracts");
  const { me } = useAuth();
  // The shared predicate, not an inline role list: a second copy of
  // "who may change commercial terms" is the drift CLAUDE.md warns about.
  const canManage = canManageContracts(me?.role);

  const [contracts, setContracts] = useState<Contract[]>([]);
  const [stats, setStats] = useState<ContractStats | null>(null);
  const [count, setCount] = useState(0);
  const [next, setNext] = useState<string | null>(null);
  const [previous, setPrevious] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState("");

  const [searchInput, setSearchInput] = useState("");
  const [searchActive, setSearchActive] = useState("");
  const [pageTab, setPageTab] = useState<"list" | "types">("list");
  const [statusFilter, setStatusFilter] = useState<ContractStatus | "">("");
  const [customerFilter, setCustomerFilter] = useState<number | "">("");
  const [buildingFilter, setBuildingFilter] = useState<number | "">("");
  const [typeFilter, setTypeFilter] = useState<number | "">("");

  const [sortField, setSortField] = useState<SortField>("start_date");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  const [groupBy, setGroupBy] = useState<GroupBy>("none");
  const [measure, setMeasure] = useState<Measure>("prices");
  const [timeframe, setTimeframe] = useState<Timeframe>("monthly");

  /** Sprint 165 §4 — which summary groups are COLLAPSED. Collapsed
   *  rather than expanded is the stored state, so the default (all
   *  open) needs no seeding when the grouping changes and a group that
   *  appears later is not silently hidden. */
  const [collapsed, setCollapsed] = useState<string[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  // Bumped by Refresh and after a mutation. It is part of the request
  // key below, so "reload" and "the filters changed" are the same
  // mechanism rather than two paths that can drift.
  const [reloadToken, setReloadToken] = useState(0);
  const deleteDialogRef = useRef<ConfirmDialogHandle>(null);

  const editMode = useEditMode<number>(contracts.map((row) => row.id));

  // The search box debounces into `searchActive`; the fetch depends on
  // the debounced value only, so a keystroke does not fire a request.
  useEffect(() => {
    const handle = window.setTimeout(() => {
      setSearchActive(searchInput.trim());
      setPage(1);
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [searchInput]);

  const filters: ContractFilters = useMemo(
    () => ({
      search: searchActive || undefined,
      status: statusFilter || undefined,
      customer: customerFilter || undefined,
      building: buildingFilter || undefined,
      type: typeFilter || undefined,
      sort: `${sortDirection === "desc" ? "-" : ""}${sortField}`,
      page,
    }),
    [
      searchActive,
      statusFilter,
      customerFilter,
      buildingFilter,
      typeFilter,
      sortField,
      sortDirection,
      page,
    ],
  );

  // `loading` is DERIVED, not set in an effect: it is true from the
  // moment the request key changes until THAT request lands. A
  // synchronous `setLoading(true)` in an effect body is the shape
  // CLAUDE.md forbids and `react-hooks/set-state-in-effect` is already
  // at its baseline for — and deriving it is simply more accurate too,
  // because it cannot be left stuck on by a fetch that was superseded.
  const requestKey = `${JSON.stringify(filters)}:${reloadToken}`;
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let cancelled = false;
    // The tiles take the SAME filters as the table (minus the page), so
    // they total what is being shown rather than the whole tenant.
    const tileFilters = { ...filters };
    delete tileFilters.page;
    Promise.all([listContracts(filters), getContractStats(tileFilters)])
      .then(([list, tiles]) => {
        if (cancelled) return;
        setContracts(list.results);
        setCount(list.count);
        setNext(list.next);
        setPrevious(list.previous);
        setStats(tiles);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(getApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoadedKey(requestKey);
      });
    return () => {
      cancelled = true;
    };
  }, [filters, requestKey]);

  const reload = () => setReloadToken((current) => current + 1);

  const sortStateFor = (field: SortField): SortState => {
    if (field !== sortField) return "none";
    return sortDirection === "asc" ? "ascending" : "descending";
  };

  const onSort = (field: SortField) => {
    if (field === sortField) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDirection("asc");
    }
    setPage(1);
  };

  const projectColumns = useMemo(
    () => buildProjectColumns(contracts, measure, timeframe),
    [contracts, measure, timeframe],
  );

  const groups = useMemo(
    () =>
      withGroupTotals(groupContracts(contracts, groupBy), measure, timeframe),
    [contracts, groupBy, measure, timeframe],
  );

  const locale = i18n.language;

  /** Hours totals for the contracts ON SCREEN, for the Hours tiles.
   *  `/contracts/stats/` answers in money only; scaling to a year uses
   *  the same MONTHS_PER_PERIOD rule the row values do. */
  const shownHours = useMemo(() => {
    const monthly = contracts.reduce(
      (sum, row) => sum + perPeriodValue(row, "hours", "monthly"),
      0,
    );
    return { monthly, yearly: monthly * 12 };
  }, [contracts]);

  const removeSelected = async () => {
    setBusy(true);
    try {
      for (const id of editMode.selection) {
        await deleteContract(id);
      }
      deleteDialogRef.current?.close();
      editMode.exit();
      reload();
    } catch (err) {
      setError(getApiError(err));
      deleteDialogRef.current?.close();
    } finally {
      setBusy(false);
    }
  };

  const filtersActive =
    Boolean(searchActive) ||
    statusFilter !== "" ||
    customerFilter !== "" ||
    buildingFilter !== "" ||
    typeFilter !== "";

  const clearFilters = () => {
    setSearchInput("");
    setSearchActive("");
    setStatusFilter("");
    setCustomerFilter("");
    setBuildingFilter("");
    setTypeFilter("");
    setPage(1);
  };

  // Contract statuses reuse the table's existing `cell-tag` vocabulary
  // rather than inventing a badge palette. Mapping stated once, here, so
  // the table and the phone cards cannot drift apart.
  const STATUS_TAG: Record<ContractStatus, string> = {
    ACTIVE: "cell-tag-open",
    DRAFT: "cell-tag-muted",
    EXPIRED: "cell-tag-closed",
    CANCELLED: "cell-tag-rejected",
  };

  const measureLabel =
    measure === "prices"
      ? timeframe === "monthly"
        ? t("table.monthly")
        : t("table.yearly")
      : t("table.hours");

  const fixedColumnCount = 5 + (editMode.editMode ? 1 : 0);
  const totalColumnCount =
    fixedColumnCount + projectColumns.columns.length +
    (projectColumns.folded > 0 ? 1 : 0) + 1;

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("list.eyebrow")}
          </div>
          <h2 className="page-title">{t("list.title")}</h2>
          <p className="page-sub">
            {loading ? t("list.loading") : t("table.countLabel", { count })}
          </p>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={reload}
            disabled={loading}
            data-testid="contracts-refresh"
          >
            <RefreshCw size={14} strokeWidth={2.5} />
            {t("actions.refresh")}
          </button>
          {canManage && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={() => setFormOpen(true)}
              data-testid="contracts-new"
            >
              <Plus size={14} strokeWidth={2.5} />
              {t("actions.newContract")}
            </button>
          )}
        </div>
      </div>

      {/* Sprint 168 §5 — the type CATALOG needs a screen, because a new
          company starts with an empty one and the type field on a
          contract is required: without this, a new tenant cannot create
          a single contract. */}
      <div
        className="composer-toggle"
        role="tablist"
        aria-label={t("types.tabsAria")}
        style={{ marginBottom: 16 }}
      >
        <button
          type="button"
          role="tab"
          aria-selected={pageTab === "list"}
          className={`composer-toggle-btn ${pageTab === "list" ? "active" : ""}`}
          onClick={() => setPageTab("list")}
          data-testid="contracts-page-tab-list"
        >
          {t("list.title")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={pageTab === "types"}
          className={`composer-toggle-btn ${pageTab === "types" ? "active" : ""}`}
          onClick={() => setPageTab("types")}
          data-testid="contracts-page-tab-types"
        >
          {t("types.title")}
        </button>
      </div>

      {pageTab === "types" && <ContractTypesTab />}

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      {/* Tiles, filters, table and pagination live inside ONE card, so the
          page reads as a single block — the shape BuildingsAdminPage
          settled on rather than header-gap-filters-gap-table.

          `hidden` rather than unmounted: the list owns the page's reads
          and its filter state, and tearing all of that down to look at
          a catalog would refetch everything on the way back. */}
      <div
        className="card"
        style={{ overflow: "hidden" }}
        hidden={pageTab !== "list"}
      >
        <div
          className="summary-grid"
          data-testid="contracts-stats"
          style={{
            gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
            margin: "14px 18px 4px",
          }}
        >
          <div className="summary-stat" data-testid="contracts-stat-total">
            <span className="summary-stat-label">{t("stats.total")}</span>
            <span className="summary-stat-value">{stats?.total ?? 0}</span>
          </div>
          <div className="summary-stat">
            <span className="summary-stat-label">{t("stats.active")}</span>
            <span className="summary-stat-value">{stats?.active ?? 0}</span>
          </div>
          <div className="summary-stat">
            <span className="summary-stat-label">{t("stats.draft")}</span>
            <span className="summary-stat-value">{stats?.draft ?? 0}</span>
          </div>
          <div className="summary-stat">
            <span className="summary-stat-label">{t("stats.expired")}</span>
            <span className="summary-stat-value">{stats?.expired ?? 0}</span>
          </div>
          {/* Sprint 165 §4 — the two money tiles follow the
              Prices / Hours toggle. They used to be money whatever the
              table showed, which left a euro figure sitting above a
              column of hours. The reference switches both together.

              The hours figures come from the ROWS on screen rather than
              from `/stats/`: that endpoint answers in money only, and
              adding an hours aggregate to it is a backend change this
              sprint's scope does not include. The tile labels say
              "shown" so the difference from the money tiles — which are
              tenant-wide — is stated rather than hidden. */}
          <div className="summary-stat">
            <span className="summary-stat-label">
              {measure === "prices"
                ? t("stats.monthlyTotal")
                : t("stats.hoursPerMonth")}
            </span>
            <span className="summary-stat-value">
              {measure === "prices"
                ? formatMoney(stats?.monthly_total ?? "0", locale)
                : formatNumber(shownHours.monthly, locale)}
            </span>
          </div>
          <div className="summary-stat">
            <span className="summary-stat-label">
              {measure === "prices"
                ? t("stats.yearlyTotal")
                : t("stats.hoursPerYear")}
            </span>
            <span className="summary-stat-value">
              {measure === "prices"
                ? formatMoney(stats?.yearly_total ?? "0", locale)
                : formatNumber(shownHours.yearly, locale)}
            </span>
          </div>
        </div>

        <form
          className="filter-bar"
          onSubmit={(event) => {
            event.preventDefault();
            setSearchActive(searchInput.trim());
            setPage(1);
          }}
        >
          <div className="filter-field search">
            <span className="filter-label">{t("filters.search")}</span>
            <input
              className="filter-control"
              type="search"
              placeholder={t("filters.searchPlaceholder")}
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              data-testid="contracts-search"
            />
          </div>
          <div className="filter-field">
            <span className="filter-label">{t("filters.status")}</span>
            <select
              className="filter-control"
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value as ContractStatus | "");
                setPage(1);
              }}
              data-testid="contracts-status-filter"
            >
              <option value="">{t("filters.allStatuses")}</option>
              {STATUS_OPTIONS.map((value) => (
                <option key={value} value={value}>
                  {t(`status.${value}`)}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-field">
            <span className="filter-label">{t("filters.customer")}</span>
            <select
              className="filter-control"
              style={{ maxWidth: 220 }}
              value={customerFilter}
              onChange={(event) => {
                setCustomerFilter(
                  event.target.value === "" ? "" : Number(event.target.value),
                );
                setPage(1);
              }}
              data-testid="contracts-customer-filter"
            >
              <option value="">{t("filters.allCustomers")}</option>
              {uniqueRefs(
                contracts.map((row) => ({
                  id: row.customer,
                  name: row.customer_name ?? "",
                })),
              ).map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-field">
            <span className="filter-label">{t("filters.building")}</span>
            <select
              className="filter-control"
              style={{ maxWidth: 220 }}
              value={buildingFilter}
              onChange={(event) => {
                setBuildingFilter(
                  event.target.value === "" ? "" : Number(event.target.value),
                );
                setPage(1);
              }}
              data-testid="contracts-building-filter"
            >
              <option value="">{t("filters.allBuildings")}</option>
              {uniqueRefs(contracts.flatMap((row) => row.buildings)).map(
                (row) => (
                  <option key={row.id} value={row.id}>
                    {row.name}
                  </option>
                ),
              )}
            </select>
          </div>
          <div className="filter-field">
            <span className="filter-label">{t("filters.type")}</span>
            <select
              className="filter-control"
              style={{ maxWidth: 180 }}
              value={typeFilter}
              onChange={(event) => {
                setTypeFilter(
                  event.target.value === "" ? "" : Number(event.target.value),
                );
                setPage(1);
              }}
              data-testid="contracts-type-filter"
            >
              <option value="">{t("filters.allTypes")}</option>
              {uniqueRefs(
                contracts
                  .filter((row) => row.contract_type !== null)
                  .map((row) => ({
                    id: row.contract_type as number,
                    name: row.contract_type_name ?? "",
                  })),
              ).map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          </div>
        </form>

        {/* The filter-is-on line, one click from clear — the Sprint 158
            §2 rule, reusing the notice style that sprint introduced. */}
        {filtersActive && (
          <div
            className="status-chip-notice"
            style={{ margin: "0 18px 10px" }}
            data-testid="contracts-filter-notice"
          >
            <span>{t("filters.activeNotice")}</span>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={clearFilters}
              data-testid="contracts-clear-filters"
            >
              {t("filters.clear")}
            </button>
          </div>
        )}

        <div className="contract-view-bar">
          <div className="status-tabs" role="group" aria-label={t("views.groupLabel")}>
            {(
              [
                ["none", t("views.list")],
                ["customer", t("views.byCustomer")],
                ["building", t("views.byBuilding")],
              ] as [GroupBy, string][]
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={value === groupBy ? "active" : ""}
                aria-pressed={value === groupBy}
                onClick={() => setGroupBy(value)}
                data-testid={`contracts-groupby-${value}`}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="status-tabs" role="group" aria-label={t("views.measureLabel")}>
            {(
              [
                ["prices", t("views.prices")],
                ["hours", t("views.hours")],
              ] as [Measure, string][]
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={value === measure ? "active" : ""}
                aria-pressed={value === measure}
                onClick={() => setMeasure(value)}
                data-testid={`contracts-measure-${value}`}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="status-tabs" role="group" aria-label={t("views.timeframeLabel")}>
            {(
              [
                ["monthly", t("views.monthly")],
                ["yearly", t("views.yearly")],
              ] as [Timeframe, string][]
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={value === timeframe ? "active" : ""}
                aria-pressed={value === timeframe}
                onClick={() => setTimeframe(value)}
                data-testid={`contracts-timeframe-${value}`}
              >
                {label}
              </button>
            ))}
          </div>
          {canManage && (
            <EditModeToggle
              editMode={editMode.editModeRequested}
              onToggle={editMode.toggleMode}
              testId="contracts-edit-toggle"
            />
          )}
        </div>

        {editMode.editMode && (
          <div style={{ padding: "0 18px" }}>
            <MultiSelectToolbar
              selectedCount={editMode.selection.length}
              onSelectAll={editMode.selectAll}
              onClearAll={editMode.clear}
              disabled={busy}
              testIdPrefix="contracts"
              actions={[
                {
                  key: "delete",
                  label: t("actions.deleteSelected"),
                  destructive: true,
                  disabled: editMode.selection.length === 0 || busy,
                  onClick: () => deleteDialogRef.current?.open(),
                },
              ]}
            />
          </div>
        )}

        {projectColumns.folded > 0 && (
          <p
            className="muted small"
            style={{ margin: "0 18px 8px" }}
            data-testid="contracts-folded-notice"
          >
            {t("table.projectsFolded", { count: projectColumns.folded })}
          </p>
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
                {editMode.editMode && (
                  <th className="th-select">
                    <input
                      type="checkbox"
                      checked={editMode.allSelected}
                      onChange={() =>
                        editMode.allSelected
                          ? editMode.clear()
                          : editMode.selectAll()
                      }
                      aria-label={t("table.selectPage")}
                      data-testid="contracts-select-page"
                    />
                  </th>
                )}
                <SortableHeader
                  label={t("table.contractNo")}
                  sort={sortStateFor("contract_no")}
                  testId="contracts-sort-no"
                  sortByLabel={t("table.sortBy", {
                    column: t("table.contractNo"),
                  })}
                  onSort={() => onSort("contract_no")}
                />
                <SortableHeader
                  label={t("table.customer")}
                  sort={sortStateFor("customer")}
                  testId="contracts-sort-customer"
                  sortByLabel={t("table.sortBy", {
                    column: t("table.customer"),
                  })}
                  onSort={() => onSort("customer")}
                />
                <th>{t("table.locations")}</th>
                <SortableHeader
                  label={t("table.type")}
                  sort={sortStateFor("type")}
                  testId="contracts-sort-type"
                  sortByLabel={t("table.sortBy", { column: t("table.type") })}
                  onSort={() => onSort("type")}
                />
                {projectColumns.columns.map((column) => (
                  <th key={column.key} className="contract-num">
                    {column.label}
                  </th>
                ))}
                {projectColumns.folded > 0 && (
                  <th className="contract-num">{t("table.otherProjects")}</th>
                )}
                <th className="contract-num">{measureLabel}</th>
                <SortableHeader
                  label={t("table.status")}
                  sort={sortStateFor("status")}
                  testId="contracts-sort-status"
                  sortByLabel={t("table.sortBy", { column: t("table.status") })}
                  onSort={() => onSort("status")}
                />
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => (
                <ContractGroup
                  key={group.key}
                  group={group}
                  groupBy={groupBy}
                  columns={projectColumns}
                  measure={measure}
                  timeframe={timeframe}
                  locale={locale}
                  editMode={editMode}
                  statusTag={STATUS_TAG}
                  totalColumnCount={totalColumnCount}
                  onOpen={(id) => navigate(`/admin/contracts/${id}`)}
                  collapsed={collapsed.includes(group.key)}
                  onToggleCollapse={() =>
                    setCollapsed((current) =>
                      current.includes(group.key)
                        ? current.filter((key) => key !== group.key)
                        : [...current, group.key],
                    )
                  }
                  t={t}
                />
              ))}
              {/* Sprint 165 §4 — the GRAND TOTAL the reference ends
                  each view with. It totals the rows ON SCREEN, which is
                  what the operator is looking at; the tenant-wide
                  figures are the tiles above. */}
              {contracts.length > 0 && (
                <tr className="contract-grand-total">
                  <td colSpan={totalColumnCount - 2}>
                    <strong>{t("table.grandTotal")}</strong>
                  </td>
                  <td className="contract-num">
                    <strong>
                      {measure === "prices"
                        ? formatMoney(
                            contracts.reduce(
                              (sum, row) =>
                                sum + perPeriodValue(row, "prices", timeframe),
                              0,
                            ),
                            locale,
                          )
                        : formatNumber(
                            contracts.reduce(
                              (sum, row) =>
                                sum + perPeriodValue(row, "hours", timeframe),
                              0,
                            ),
                            locale,
                          )}
                    </strong>
                  </td>
                  <td />
                </tr>
              )}
              {!loading && contracts.length === 0 && (
                <tr>
                  <td colSpan={totalColumnCount} className="muted">
                    {filtersActive
                      ? t("table.emptyFiltered")
                      : t("table.empty")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* The phone-width layout, kept in step with the table above. */}
        <ul className="admin-card-list" data-testid="contracts-card-list">
          {contracts.map((row) => (
            <li key={row.id} className="admin-card">
              <div className="admin-card-head">
                <Link
                  to={`/admin/contracts/${row.id}`}
                  className="admin-card-title admin-card-link"
                >
                  {row.contract_no}
                </Link>
                <span className={`cell-tag ${STATUS_TAG[row.status]}`}>
                  {t(`status.${row.status}`)}
                </span>
              </div>
              <div className="admin-card-meta-row">
                <span className="admin-card-meta">{row.customer_name}</span>
              </div>
              <div className="admin-card-meta-row">
                <span className="admin-card-meta">
                  {row.buildings.map((b) => b.name).join(", ") || "—"}
                </span>
              </div>
              <div className="admin-card-meta-row">
                <span className="admin-card-meta">
                  {measureLabel}:{" "}
                  {measure === "prices"
                    ? formatMoney(perPeriodValue(row, "prices", timeframe), locale)
                    : formatNumber(perPeriodValue(row, "hours", timeframe), locale)}
                </span>
              </div>
            </li>
          ))}
        </ul>

        {(previous || next) && (
          <div className="pagination">
            <span className="pagination-info">
              {t("table.countLabel", { count })}
            </span>
            <div className="pagination-controls">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={!previous || loading}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                data-testid="contracts-prev"
              >
                {t("actions.previous")}
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={!next || loading}
                onClick={() => setPage((current) => current + 1)}
                data-testid="contracts-next"
              >
                {t("actions.next")}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Rendered UNCONDITIONALLY and driven entirely through the ref —
          a native <dialog> wrapped in `{open && ...}` mounts invisible
          and the trigger looks dead (CLAUDE.md §3, Sprint 128). */}
      <ConfirmDialog
        ref={deleteDialogRef}
        title={t("delete.title")}
        body={t("delete.body", { count: editMode.selection.length })}
        confirmLabel={t("delete.confirm")}
        destructive
        busy={busy}
        onConfirm={() => void removeSelected()}
      />

      <ContractFormDialog
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onCreated={(created) => {
          setFormOpen(false);
          navigate(`/admin/contracts/${created.id}`);
        }}
      />
    </div>
  );
}

function uniqueRefs(
  rows: { id: number; name: string }[],
): { id: number; name: string }[] {
  const seen = new Map<number, string>();
  for (const row of rows) {
    if (!seen.has(row.id)) seen.set(row.id, row.name);
  }
  return [...seen.entries()]
    .map(([id, name]) => ({ id, name }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

function ContractGroup({
  group,
  groupBy,
  columns,
  measure,
  timeframe,
  locale,
  editMode,
  statusTag,
  totalColumnCount,
  onOpen,
  collapsed,
  onToggleCollapse,
  t,
}: {
  group: ContractGroupRow;
  groupBy: GroupBy;
  columns: ReturnType<typeof buildProjectColumns>;
  measure: Measure;
  timeframe: Timeframe;
  locale: string;
  editMode: ReturnType<typeof useEditMode<number>>;
  statusTag: Record<ContractStatus, string>;
  totalColumnCount: number;
  onOpen: (id: number) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const format = measure === "prices" ? formatMoney : formatNumber;
  return (
    <>
      {groupBy !== "none" && (
        <tr
          className="contract-group-row"
          data-testid={`contracts-group-${group.key}`}
        >
          <td colSpan={totalColumnCount - 2}>
            {/* The whole header toggles the group — the reference's
                expandable summary rows. A button rather than a click
                handler on the cell, so it is keyboard reachable and
                announces its state. */}
            <button
              type="button"
              className="btn btn-ghost btn-sm contract-group-toggle"
              aria-expanded={!collapsed}
              onClick={onToggleCollapse}
              data-testid={`contracts-group-toggle-${group.key}`}
            >
              <span aria-hidden="true">{collapsed ? "\u25b8" : "\u25be"}</span>
              <strong>{group.label}</strong>
              <span className="muted small">
                {t("table.groupCount", { count: group.rows.length })}
              </span>
            </button>
          </td>
          <td className="contract-num">
            <strong>{format(group.total, locale)}</strong>
          </td>
          <td />
        </tr>
      )}
      {(groupBy === "none" || !collapsed) && group.rows.map((row) => (
        <tr
          key={`${group.key}-${row.id}`}
          className="admin-row-clickable"
          role="link"
          tabIndex={0}
          aria-label={`${t("actions.open")}: ${row.contract_no}`}
          onClick={() => onOpen(row.id)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              onOpen(row.id);
            }
          }}
        >
          {editMode.editMode && (
            <td
              className="td-select"
              onClick={(event) => event.stopPropagation()}
            >
              <input
                type="checkbox"
                checked={editMode.isSelected(row.id)}
                onChange={() => editMode.toggle(row.id)}
                aria-label={t("table.selectRow", { name: row.contract_no })}
                data-testid={`contracts-select-${row.id}`}
              />
            </td>
          )}
          <td className="td-subject">{row.contract_no}</td>
          <td>{row.customer_name ?? <span className="muted-empty">—</span>}</td>
          <td>
            {row.buildings.length === 0 ? (
              <span className="muted-empty">—</span>
            ) : (
              <BuildingsCell
                names={row.buildings.map((building) => building.name)}
                moreLabel={(n) => t("table.andMore", { count: n })}
              />
            )}
          </td>
          <td>
            {row.contract_type_name ?? <span className="muted-empty">—</span>}
          </td>
          {columns.columns.map((column) => (
            <td key={column.key} className="contract-num">
              {format(column.valueFor(row), locale)}
            </td>
          ))}
          {columns.folded > 0 && (
            <td className="contract-num">{format(columns.otherFor(row), locale)}</td>
          )}
          <td className="contract-num">
            {format(perPeriodValue(row, measure, timeframe), locale)}
          </td>
          <td>
            <span className={`cell-tag ${statusTag[row.status]}`}>
              {t(`status.${row.status}`)}
            </span>
          </td>
        </tr>
      ))}
    </>
  );
}

/**
 * The Locations cell: the first two names plus a "+N" chip. Bounded on
 * purpose — a contract can cover a dozen buildings, and an unbounded
 * cell looks fine on seed data and destroys the row height on real
 * data. Same shape as the buildings list's Customers cell.
 */
function BuildingsCell({
  names,
  moreLabel,
}: {
  names: string[];
  moreLabel: (n: number) => string;
}) {
  const shown = names.slice(0, 2);
  const hidden = names.length - shown.length;
  return (
    <span>
      {shown.join(", ")}
      {hidden > 0 && (
        <span className="cell-tag cell-tag-muted" style={{ marginLeft: 6 }}>
          {moreLabel(hidden)}
        </span>
      )}
    </span>
  );
}

export { MAX_PROJECT_COLUMNS };
