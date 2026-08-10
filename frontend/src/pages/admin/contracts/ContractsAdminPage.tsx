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
  const [statusFilter, setStatusFilter] = useState<ContractStatus | "">("");
  const [customerFilter, setCustomerFilter] = useState<number | "">("");
  const [buildingFilter, setBuildingFilter] = useState<number | "">("");
  const [typeFilter, setTypeFilter] = useState<number | "">("");

  const [sortField, setSortField] = useState<SortField>("start_date");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  const [groupBy, setGroupBy] = useState<GroupBy>("none");
  const [measure, setMeasure] = useState<Measure>("prices");
  const [timeframe, setTimeframe] = useState<Timeframe>("monthly");

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

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>{t("list.title")}</h1>
          <p className="page-subtitle">{t("list.subtitle")}</p>
        </div>
        <div className="page-header-actions">
          <button
            type="button"
            className="btn btn-ghost"
            onClick={reload}
            disabled={loading}
            data-testid="contracts-refresh"
          >
            <RefreshCw size={16} strokeWidth={2} />
            {t("actions.refresh")}
          </button>
          {canManage && (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setFormOpen(true)}
              data-testid="contracts-new"
            >
              <Plus size={16} strokeWidth={2} />
              {t("actions.newContract")}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}

      {/* Stat tiles — six figures over the CURRENT filter set. */}
      <div className="stat-strip" data-testid="contracts-stats">
        <StatTile label={t("stats.total")} value={String(stats?.total ?? 0)} />
        <StatTile
          label={t("stats.active")}
          value={String(stats?.active ?? 0)}
        />
        <StatTile label={t("stats.draft")} value={String(stats?.draft ?? 0)} />
        <StatTile
          label={t("stats.expired")}
          value={String(stats?.expired ?? 0)}
        />
        <StatTile
          label={t("stats.monthlyTotal")}
          value={formatMoney(stats?.monthly_total ?? "0", locale)}
        />
        <StatTile
          label={t("stats.yearlyTotal")}
          value={formatMoney(stats?.yearly_total ?? "0", locale)}
        />
      </div>

      {/* Filters */}
      <div className="filter-row" data-testid="contracts-filters">
        <input
          type="search"
          className="input"
          value={searchInput}
          placeholder={t("filters.searchPlaceholder")}
          aria-label={t("filters.search")}
          onChange={(event) => setSearchInput(event.target.value)}
          data-testid="contracts-search"
        />
        <select
          className="input"
          value={statusFilter}
          aria-label={t("filters.status")}
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
        <select
          className="input"
          value={customerFilter}
          aria-label={t("filters.customer")}
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
        <select
          className="input"
          value={buildingFilter}
          aria-label={t("filters.building")}
          onChange={(event) => {
            setBuildingFilter(
              event.target.value === "" ? "" : Number(event.target.value),
            );
            setPage(1);
          }}
          data-testid="contracts-building-filter"
        >
          <option value="">{t("filters.allBuildings")}</option>
          {uniqueRefs(contracts.flatMap((row) => row.buildings)).map((row) => (
            <option key={row.id} value={row.id}>
              {row.name}
            </option>
          ))}
        </select>
        <select
          className="input"
          value={typeFilter}
          aria-label={t("filters.type")}
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

      {/* The filter-is-on line, with one click to clear it — the Sprint
          158 §2 rule: a list that opens filtered must say so and must be
          clearable in one action. */}
      {filtersActive && (
        <div className="filter-notice" data-testid="contracts-filter-notice">
          <span>{t("filters.activeNotice")}</span>
          <button
            type="button"
            className="btn btn-link"
            onClick={clearFilters}
            data-testid="contracts-clear-filters"
          >
            {t("filters.clear")}
          </button>
        </div>
      )}

      {/* The three view toggles. */}
      <div className="toggle-row" data-testid="contracts-view-toggles">
        <ToggleGroup
          label={t("views.groupLabel")}
          value={groupBy}
          options={[
            { value: "none", label: t("views.list") },
            { value: "customer", label: t("views.byCustomer") },
            { value: "building", label: t("views.byBuilding") },
          ]}
          onChange={(value) => setGroupBy(value as GroupBy)}
          testId="contracts-groupby"
        />
        <ToggleGroup
          label={t("views.measureLabel")}
          value={measure}
          options={[
            { value: "prices", label: t("views.prices") },
            { value: "hours", label: t("views.hours") },
          ]}
          onChange={(value) => setMeasure(value as Measure)}
          testId="contracts-measure"
        />
        <ToggleGroup
          label={t("views.timeframeLabel")}
          value={timeframe}
          options={[
            { value: "monthly", label: t("views.monthly") },
            { value: "yearly", label: t("views.yearly") },
          ]}
          onChange={(value) => setTimeframe(value as Timeframe)}
          testId="contracts-timeframe"
        />
        {canManage && (
          <EditModeToggle
            editMode={editMode.editModeRequested}
            onToggle={editMode.toggleMode}
            testId="contracts-edit-toggle"
          />
        )}
      </div>

      {editMode.editMode && (
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
      )}

      {projectColumns.folded > 0 && (
        <p className="muted" data-testid="contracts-folded-notice">
          {t("table.projectsFolded", { count: projectColumns.folded })}
        </p>
      )}

      <div className="table-wrap">
        <table className="data-table data-table-dense">
          <thead>
            <tr>
              {editMode.editMode && <th className="col-select" />}
              <SortableHeader
                label={t("table.contractNo")}
                sort={sortStateFor("contract_no")}
                testId="contracts-sort-no"
                sortByLabel={t("table.sortBy", { column: t("table.contractNo") })}
                onSort={() => onSort("contract_no")}
              />
              <SortableHeader
                label={t("table.customer")}
                sort={sortStateFor("customer")}
                testId="contracts-sort-customer"
                sortByLabel={t("table.sortBy", { column: t("table.customer") })}
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
                <th key={column.key} className="num">
                  {column.label}
                </th>
              ))}
              {projectColumns.folded > 0 && (
                <th className="num">{t("table.otherProjects")}</th>
              )}
              <th className="num">
                {measure === "prices"
                  ? timeframe === "monthly"
                    ? t("table.monthly")
                    : t("table.yearly")
                  : t("table.hours")}
              </th>
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
                t={t}
              />
            ))}
            {!loading && contracts.length === 0 && (
              <tr>
                <td colSpan={12} className="empty-cell">
                  {filtersActive ? t("table.emptyFiltered") : t("table.empty")}
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
            <Link to={`/admin/contracts/${row.id}`} className="admin-card-title">
              {row.contract_no}
            </Link>
            <div className="admin-card-meta">{row.customer_name}</div>
            <div className="admin-card-meta">
              {row.buildings.map((building) => building.name).join(", ") || "—"}
            </div>
            <div className="admin-card-meta">
              {measure === "prices"
                ? formatMoney(
                    perPeriodValue(row, "prices", timeframe),
                    locale,
                  )
                : formatNumber(perPeriodValue(row, "hours", timeframe), locale)}
              {" · "}
              {t(`status.${row.status}`)}
            </div>
          </li>
        ))}
      </ul>

      <div className="pagination-row">
        <span className="muted">{t("table.countLabel", { count })}</span>
        <div className="pagination-actions">
          <button
            type="button"
            className="btn btn-ghost"
            disabled={!previous || loading}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
            data-testid="contracts-prev"
          >
            {t("actions.previous")}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={!next || loading}
            onClick={() => setPage((current) => current + 1)}
            data-testid="contracts-next"
          >
            {t("actions.next")}
          </button>
        </div>
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

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat-tile">
      <span className="stat-tile-label">{label}</span>
      <span className="stat-tile-value">{value}</span>
    </div>
  );
}

function ToggleGroup({
  label,
  value,
  options,
  onChange,
  testId,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  testId: string;
}) {
  return (
    <div className="toggle-group" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={`chip${option.value === value ? " chip-active" : ""}`}
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
          data-testid={`${testId}-${option.value}`}
        >
          {option.label}
        </button>
      ))}
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
  t,
}: {
  group: ContractGroupRow;
  groupBy: GroupBy;
  columns: ReturnType<typeof buildProjectColumns>;
  measure: Measure;
  timeframe: Timeframe;
  locale: string;
  editMode: ReturnType<typeof useEditMode<number>>;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const format = measure === "prices" ? formatMoney : formatNumber;
  return (
    <>
      {groupBy !== "none" && (
        <tr className="group-row" data-testid={`contracts-group-${group.key}`}>
          <td colSpan={5 + columns.columns.length + (columns.folded > 0 ? 1 : 0)}>
            <strong>{group.label}</strong>
            <span className="muted">
              {" "}
              {t("table.groupCount", { count: group.rows.length })}
            </span>
          </td>
          <td className="num">
            <strong>{format(group.total, locale)}</strong>
          </td>
          <td />
        </tr>
      )}
      {group.rows.map((row) => (
        <tr key={`${group.key}-${row.id}`}>
          {editMode.editMode && (
            <td className="col-select">
              <input
                type="checkbox"
                checked={editMode.isSelected(row.id)}
                onChange={() => editMode.toggle(row.id)}
                aria-label={t("table.selectRow", { name: row.contract_no })}
                data-testid={`contracts-select-${row.id}`}
              />
            </td>
          )}
          <td>
            <Link to={`/admin/contracts/${row.id}`}>{row.contract_no}</Link>
          </td>
          <td>{row.customer_name ?? "—"}</td>
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
          <td>{row.contract_type_name ?? "—"}</td>
          {columns.columns.map((column) => (
            <td key={column.key} className="num">
              {format(column.valueFor(row), locale)}
            </td>
          ))}
          {columns.folded > 0 && (
            <td className="num">{format(columns.otherFor(row), locale)}</td>
          )}
          <td className="num">
            {format(perPeriodValue(row, measure, timeframe), locale)}
          </td>
          <td>
            <span className={`badge badge-${row.status.toLowerCase()}`}>
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
