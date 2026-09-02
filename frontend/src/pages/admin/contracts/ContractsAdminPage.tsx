import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { SyntheticEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { FileSignature, Plus, RefreshCw, SlidersHorizontal } from "lucide-react";
import { EmptyState } from "../../../components/EmptyState";
import { useTranslation } from "react-i18next";

import { listAllCompanies } from "../../../api/admin";
import { getApiError } from "../../../api/client";
import { CONTRACT_STATUS_TAG } from "../../../lib/contractStatusTag";
import { deleteContract, getContractStats, listContracts } from "../../../api/contracts";
import type {
  Contract,
  ContractBuildingRef,
  ContractFilters,
  ContractStats,
} from "../../../api/contracts.types";
import type { CompanyAdmin } from "../../../api/types";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../../components/ConfirmDialog";
import { EditModeToggle } from "../../../components/EditModeToggle";
import { MultiSelectToolbar } from "../../../components/MultiSelectToolbar";
import { SortableHeader } from "../../../components/SortableHeader";
import type { SortState } from "../../../components/SortableHeader";
import { useAuth } from "../../../auth/AuthContext";
import {
  canAccessAdminArea,
  canManageContracts,
  canReadCustomerArea,
} from "../../../auth/permissions";
import { useEditMode } from "../../../lib/useEditMode";
import { ContractFormDialog } from "./ContractFormDialog";
import { ContractTypesTab } from "./ContractTypesTab";
import { contractSentence } from "../../../components/contracts/contractSentence";
import { contractTypeLabel } from "../../../lib/contractTypeLabel";
import { formatDate, formatMoney } from "./contractTables";
import { CONTRACT_ROAD } from "../../../lib/contractRoad";
import type { ContractRoadKey } from "../../../lib/contractRoad";
import { RoadTabs, TeachHead } from "../../../components/guide/RoadTabs";
import { StartHere } from "../../../components/guide/StartHere";
import { TeachEmpty } from "../../../components/guide/TeachEmpty";
import { CompanyScopeSelect } from "../../../components/guide/CompanyScopeSelect";
import {
  readScopeCompany,
  rememberScopeCompany,
} from "../../../lib/useCompanyScope";

const DEBOUNCE_MS = 300;

type SortField = "customer" | "start_date" | "status";
type SortDirection = "asc" | "desc";

type ContractListView = ContractRoadKey | "cancelled";

/** What each tab asks the SERVER for. */
const ROAD_QUERY: Record<
  ContractListView,
  { status: NonNullable<ContractFilters["status"]>; ending?: "exclude" }
> = {
  draft: { status: "DRAFT" },
  active: { status: "ACTIVE", ending: "exclude" },
  ending: { status: "ENDING" },
  ended: { status: "EXPIRED" },
  cancelled: { status: "CANCELLED" },
};

function parseListView(raw: string | null): ContractListView {
  if (raw === "cancelled") return "cancelled";
  return (CONTRACT_ROAD as readonly string[]).includes(raw ?? "")
    ? (raw as ContractRoadKey)
    : "active";
}

/**
 * Sprint 160 §3 / P-11 C — the contracts list.
 *
 * The shape Sprints 154/155 settled for the other admin lists: dense
 * sortable table, `MultiSelectToolbar` behind the `useEditMode` gate,
 * and the parallel `.admin-card-list` for phone width kept in step with
 * the table rather than being a second, drifting layout.
 *
 * P-11 C is the clarity pass (the functional freeze holds): the page
 * answers ONE question — "what each customer pays for on a fixed basis,
 * per building, and for how long" — with five fixed columns (Customer ·
 * Locations · Period · Monthly amount · Status) and nothing else. The
 * seven stat tiles are gone (Addendum D §D.22: never a KPI card row),
 * the three-view grouping and the Prices/Hours + Per maand/Per jaar
 * selects are gone with them, and with them went the dynamic per-project
 * columns, the "Other" fold and the grand-total row. The filters stay
 * folded behind the one Filter button; edit mode keeps its own slim row
 * above the table so no capability is lost.
 */
export function ContractsAdminPage() {
  const navigate = useNavigate();
  const { t, i18n } = useTranslation("contracts");
  const { me } = useAuth();
  // The shared predicate, not an inline role list: a second copy of
  // "who may change commercial terms" is the drift CLAUDE.md warns about.
  const canManage = canManageContracts(me?.role);
  // P-8R F — the connected-facts links on a row point at pages with their
  // own guards: a building detail is admin-only, a customer detail admits
  // a BUILDING_MANAGER through its own variant. A link a role cannot
  // follow is a dead door, so each renders as a plain name instead.
  const canOpenBuilding = canAccessAdminArea(me?.role);
  const canOpenCustomer = canReadCustomerArea(me?.role);

  const [contracts, setContracts] = useState<Contract[]>([]);
  const [count, setCount] = useState(0);
  const [next, setNext] = useState<string | null>(null);
  const [previous, setPrevious] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState("");

  const [searchInput, setSearchInput] = useState("");
  const [searchActive, setSearchActive] = useState("");
  const [pageTab, setPageTab] = useState<"list" | "types">("list");
  // P-12 C1 — the road tab lives in the URL, so a reload and Back land
  // where the person was (§D.22 rule 3).
  const [searchParams, setSearchParams] = useSearchParams();
  const listView = parseListView(searchParams.get("tab"));
  const setListView = (next: ContractListView) => {
    const params = new URLSearchParams(searchParams);
    if (next === "active") params.delete("tab");
    else params.set("tab", next);
    setSearchParams(params, { replace: true });
    setPage(1);
  };
  // The guidance numbers: counts and money per road step, and the
  // Start-here facts. Company-scoped, deliberately NOT search-scoped —
  // the tabs describe the road, not the current narrowing.
  const [stats, setStats] = useState<ContractStats | null>(null);
  // Sprint 187 §6c — WHICH provider company. `company_name` has been
  // in every row's JSON and `?company=` accepted by the endpoint
  // since contracts shipped, so this is frontend-only. The pattern
  // is `BuildingsAdminPage`'s verbatim: load once exhaustively,
  // auto-select when exactly one company comes back, derive the
  // disabled state rather than storing it.
  const [companyFilter, setCompanyFilter] = useState<number | "">("");
  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [customerFilter, setCustomerFilter] = useState<number | "">("");
  const [buildingFilter, setBuildingFilter] = useState<number | "">("");
  const [typeFilter, setTypeFilter] = useState<number | "">("");

  const [sortField, setSortField] = useState<SortField>("start_date");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

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

  // Sprint 187 §6c — loaded once, exhaustively (Sprint 135: a tenant
  // with more than one page of companies must not get a silently
  // truncated dropdown).
  useEffect(() => {
    let cancelled = false;
    listAllCompanies({ is_active: "true" })
      .then((rows) => {
        if (cancelled) return;
        setCompanies(rows);
        // Auto-select for a COMPANY_ADMIN with exactly one company in
        // scope: the filter is then a fact, not a question. P-12
        // §D.24.2: with more, the session's shared Finance-pages
        // choice — else the lowest id — is the working company.
        if (rows.length === 1) {
          setCompanyFilter(rows[0].id);
        } else if (rows.length > 1) {
          const stored = readScopeCompany();
          const chosen =
            stored != null && rows.some((row) => row.id === stored)
              ? stored
              : [...rows].sort((a, b) => a.id - b.id)[0].id;
          setCompanyFilter((current) => (current === "" ? chosen : current));
        }
      })
      .catch(() => {
        if (!cancelled) setCompanies([]);
      })
    return () => {
      cancelled = true;
    };
  }, []);

  const filters: ContractFilters = useMemo(
    () => ({
      search: searchActive || undefined,
      status: ROAD_QUERY[listView].status,
      ending: ROAD_QUERY[listView].ending,
      company: companyFilter || undefined,
      customer: customerFilter || undefined,
      building: buildingFilter || undefined,
      type: typeFilter || undefined,
      sort: `${sortDirection === "desc" ? "-" : ""}${sortField}`,
      page,
    }),
    [
      searchActive,
      listView,
      companyFilter,
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

  // P-11 C — ONE fetch: the list page. The `/contracts/stats/` call fed
  // the seven tiles only; it went with them.
  useEffect(() => {
    let cancelled = false;
    listContracts(filters)
      .then((list) => {
        if (cancelled) return;
        setContracts(list.results);
        setCount(list.count);
        setNext(list.next);
        setPrevious(list.previous);
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

  // P-12 C1 — the road's numbers, in one read beside the list.
  useEffect(() => {
    let cancelled = false;
    getContractStats({ company: companyFilter || undefined })
      .then((response) => {
        if (!cancelled) setStats(response);
      })
      .catch(() => {
        // The list still works; the tabs then show no counts.
        if (!cancelled) setStats(null);
      });
    return () => {
      cancelled = true;
    };
  }, [companyFilter, reloadToken]);

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

  const locale = i18n.language;

  /** P-11 C — the Period column: the term in the customer's words.
   *  An open end is not a dash but "since {start}". Shared by the
   *  table and the phone cards so the two cannot drift. */
  const periodLabel = (row: Contract): string =>
    row.end_date
      ? `${formatDate(row.start_date, locale)} – ${formatDate(row.end_date, locale)}`
      : t("table.periodSince", { start: formatDate(row.start_date, locale) });

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
    customerFilter !== "" ||
    buildingFilter !== "" ||
    typeFilter !== "";
  /* P-4 (Part F) — the chips on the Filter button: one label per
     active filter, in the person's words. */
  const activeFilterChips: string[] = [
    customerFilter !== ""
      ? (uniqueRefs(contracts.map((row) => ({ id: row.customer, name: row.customer_name ?? "" }))).find(
          (row) => String(row.id) === String(customerFilter),
        )?.name ?? t("filters.customer"))
      : "",
    buildingFilter !== "" ? t("filters.building") : "",
    typeFilter !== "" ? t("filters.type") : "",
  ].filter(Boolean);
  // P-2 §5 — nothing at all (not "nothing matches"): the one card.
  // P-11 C — `count` is the list's own total; the stats fetch that used
  // to answer this is gone with the tiles.
  const showEmptyCard =
    !loading && !error && !filtersActive && stats !== null && stats.total === 0;

  const clearFilters = () => {
    setSearchInput("");
    setSearchActive("");
    setCustomerFilter("");
    setBuildingFilter("");
    setTypeFilter("");
    setPage(1);
  };

  // P-11 C — five fixed columns (Customer · Locations · Period ·
  // Monthly amount · Status); the select column joins in edit mode.
  // Only the empty row spans them now.
  const totalColumnCount = 5 + (editMode.editMode ? 1 : 0);

  // P-12 C1 — the road's counts and money lines, from the stats read.
  // Active excludes ending-soon so the four tabs partition.
  const roadCounts: Record<ContractListView, number> = {
    draft: stats?.draft ?? 0,
    active: Math.max((stats?.active ?? 0) - (stats?.ending_soon ?? 0), 0),
    ending: stats?.ending_soon ?? 0,
    ended: stats?.expired ?? 0,
    cancelled: stats?.cancelled ?? 0,
  };
  const roadMoneyValue: Record<ContractListView, string> = {
    draft: String(stats?.draft ?? 0),
    active: formatMoney(stats?.monthly_by_status.active ?? "0.00", locale),
    ending: formatMoney(stats?.monthly_by_status.ending_soon ?? "0.00", locale),
    ended: String(stats?.expired ?? 0),
    cancelled: String(stats?.cancelled ?? 0),
  };

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("list.eyebrow")}
          </div>
          <h2 className="page-title">{t("list.title")}</h2>
          {/* P-8R F — ONE purpose line (Addendum D §D.15 item 9); the
              P-11 C wording is the owner's own sentence. */}
          <p className="page-sub" data-testid="contracts-purpose">
            {t("list.purpose")}
          </p>
        </div>
        <div className="page-header-actions">
          {/* P-12 §D.24.2 — one company at a time; the choice is the
              session's, shared with the other Finance pages. */}
          <CompanyScopeSelect
            companies={companies}
            companyId={companyFilter}
            onChange={(id) => {
              setCompanyFilter(id);
              setCustomerFilter("");
              setBuildingFilter("");
              setTypeFilter("");
              setPage(1);
              rememberScopeCompany(id);
            }}
            testId="contracts-company-filter"
          />
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
        className="customer-tabs"
        role="tablist"
        aria-label={t("types.tabsAria")}
        style={{ marginBottom: 16 }}
      >
        <button
          type="button"
          role="tab"
          aria-selected={pageTab === "list"}
          className={`customer-tab ${pageTab === "list" ? "active" : ""}`}
          onClick={() => setPageTab("list")}
          data-testid="contracts-page-tab-list"
        >
          {t("list.title")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={pageTab === "types"}
          className={`customer-tab ${pageTab === "types" ? "active" : ""}`}
          onClick={() => setPageTab("types")}
          data-testid="contracts-page-tab-types"
        >
          {t("types.title")}
        </button>
      </div>

      {pageTab === "types" && <ContractTypesTab />}

      {/* P-12 C1 (§D.24 rule 2) — the ONE thing waiting: a draft
          without lines beats the contract ending soonest. */}
      {pageTab === "list" &&
        stats?.start_here &&
        (stats.start_here.draft_no_lines ? (
          <StartHere
            testId="contracts-start-here"
            action={{
              label: t("road.start_draft_action"),
              to: `/admin/contracts/${stats.start_here.draft_no_lines.id}`,
            }}
          >
            {t("road.start_draft", {
              no: stats.start_here.draft_no_lines.contract_no,
              customer: stats.start_here.draft_no_lines.customer_name,
            })}
          </StartHere>
        ) : stats.start_here.ending_soonest ? (
          <StartHere
            testId="contracts-start-here"
            action={{
              label: t("road.start_ending_action"),
              to: `/admin/contracts/${stats.start_here.ending_soonest.id}`,
            }}
          >
            {t("road.start_ending", {
              no: stats.start_here.ending_soonest.contract_no,
              customer: stats.start_here.ending_soonest.customer_name,
              date: stats.start_here.ending_soonest.end_date
                ? formatDate(stats.start_here.ending_soonest.end_date, locale)
                : "",
            })}
          </StartHere>
        ) : null)}

      {/* P-12 C1 (§D.24 rule 3) — the road: draft, active, ending,
          ended, numbered in the order things happen. Cancelled is off
          the road, behind the link at the foot of the last tab. */}
      {pageTab === "list" && !showEmptyCard && (
        <>
          {listView === "cancelled" ? (
            <div className="guide-teach" data-testid="contracts-cancelled-head">
              <div className="guide-teach-words">
                <h2 className="guide-teach-title">
                  {t("road.cancelled_title")}
                  {stats ? ` (${stats.cancelled})` : ""}
                </h2>
                <p className="guide-teach-body">{t("road.cancelled_body")}</p>
              </div>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setListView("ended")}
                data-testid="contracts-cancelled-back"
              >
                {t("road.cancelled_back")}
              </button>
            </div>
          ) : (
            <>
              <RoadTabs
                steps={CONTRACT_ROAD.map((key) => ({
                  key,
                  step: t(`road.${key}_step`),
                  label: t(`road.${key}_label`),
                  count: stats ? roadCounts[key] : null,
                }))}
                activeKey={listView}
                onSelect={(key) => setListView(key)}
                ariaLabel={t("road.aria")}
                testIdPrefix="contracts-road"
              />
              <TeachHead
                testId="contracts-road-teach"
                title={t(`road.${listView}_title`)}
                body={t(`road.${listView}_body`)}
                money={
                  stats
                    ? {
                        value: roadMoneyValue[listView],
                        label: t(`road.${listView}_money_label`, {
                          count: roadCounts[listView],
                          without_lines: stats.draft_without_lines,
                        }),
                      }
                    : undefined
                }
              />
              {/* §D.22 rule 9 — cancelled behind a link, at the foot of
                  the last tab, never a tab of its own. */}
              {listView === "ended" && (stats?.cancelled ?? 0) > 0 && (
                <p className="muted small" style={{ margin: "-6px 0 10px" }}>
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    onClick={() => setListView("cancelled")}
                    data-testid="contracts-cancelled-link"
                  >
                    {t("road.cancelled_link", { count: stats?.cancelled ?? 0 })}
                  </button>
                </p>
              )}
            </>
          )}
        </>
      )}

      {error && (
        <div className="alert-error" style={{ marginBottom: 16 }} role="alert">
          {error}
        </div>
      )}

      {/* Filters, table and pagination live inside ONE card, so the
          page reads as a single block — the shape BuildingsAdminPage
          settled on rather than header-gap-filters-gap-table.

          `hidden` rather than unmounted: the list owns the page's reads
          and its filter state, and tearing all of that down to look at
          a catalog would refetch everything on the way back. */}
      {/* P-2 §5 — with no contracts at all, ONE card that says what a
          contract is and offers the one obvious action; the filters and
          the table appear only once one exists. */}
      {pageTab === "list" && showEmptyCard && (
        <EmptyState
          icon={FileSignature}
          title={t("empty.title")}
          description={t("empty.desc")}
          testId="contracts-empty"
          action={
            canManage ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => setFormOpen(true)}
                data-testid="contracts-empty-new"
              >
                <Plus size={14} strokeWidth={2.5} />
                {t("actions.newContract")}
              </button>
            ) : undefined
          }
        />
      )}
      <div
        className="card"
        style={{ overflow: "hidden" }}
        hidden={pageTab !== "list" || showEmptyCard}
      >
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
          <button type="submit" className="btn btn-secondary btn-sm" data-testid="contracts-search-apply">
            {t("filters.apply")}
          </button>
          {/* P-4 (Part F) — the five filters fold behind ONE Filter button
              with the active ones as chips (the tickets-list pattern);
              the search and Apply stay outside. P-11 C — the two display
              selects (Prices/Hours, Per maand/Per jaar) left the fold:
              the Monthly-amount column is fixed now. */}
          <details
            className="filter-fold"
            open={activeFilterChips.length > 0}
            data-testid="contracts-filter-fold"
          >
            <summary className="filter-fold-summary" data-testid="contracts-filter-toggle">
              <SlidersHorizontal size={14} strokeWidth={2.4} aria-hidden="true" />
              {t("filters.fold_label")}
              {activeFilterChips.length > 0 && (
                <span className="filter-fold-count">
                  {t("filters.fold_active", { count: activeFilterChips.length })}
                </span>
              )}
              {activeFilterChips.map((label) => (
                <span className="filter-fold-chip" key={label}>
                  {label}
                </span>
              ))}
            </summary>
            <div className="filter-fold-body">
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
                    name: contractTypeLabel(
                      row.contract_type_name,
                      row.contract_type_standard_slot,
                      t,
                    ),
                  })),
              ).map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          </div>
            </div>
          </details>
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

        {/* P-11 C — the view pills are gone (the list is the one view,
            Addendum D §D.22), but edit mode was mounted in that bar and
            must stay reachable: the toggle keeps a slim right-aligned
            row of its own above the table so no capability is lost. */}
        {canManage && (
          <div
            className="contract-view-bar"
            style={{ justifyContent: "flex-end" }}
          >
            <EditModeToggle
              editMode={editMode.editModeRequested}
              onToggle={editMode.toggleMode}
              testId="contracts-edit-toggle"
            />
          </div>
        )}

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

        {loading && (
          <div className="loading-bar" style={{ margin: 0 }}>
            <div className="loading-bar-fill" />
          </div>
        )}

        <div className="table-wrap admin-list-wrap">
          {/* FE-6 (§D.8.4) — `data-table-fit` lets cells wrap, so the
              list reads inside its card instead of scrolling. */}
          <table className="data-table data-table-dense data-table-fit">
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
                  label={t("table.customer")}
                  sort={sortStateFor("customer")}
                  testId="contracts-sort-customer"
                  sortByLabel={t("table.sortBy", {
                    column: t("table.customer"),
                  })}
                  onSort={() => onSort("customer")}
                />
                <th>{t("table.locations")}</th>
                {/* P-11 C — the Period column sorts by start date; the
                    backend `sort` whitelist has no combined period
                    field, and the start is what orders a term. */}
                <SortableHeader
                  label={t("table.period")}
                  sort={sortStateFor("start_date")}
                  testId="contracts-sort-period"
                  sortByLabel={t("table.sortBy", { column: t("table.period") })}
                  onSort={() => onSort("start_date")}
                />
                <th className="contract-num">{t("table.monthlyAmount")}</th>
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
              {contracts.map((row) => (
                <tr
                  key={row.id}
                  className="admin-row-clickable"
                  role="link"
                  tabIndex={0}
                  aria-label={`${t("actions.open")}: ${row.contract_no}`}
                  onClick={(event) => {
                    // P-8R F — the row carries inline links; a click or
                    // an Enter on one of them must open THAT page and
                    // not also the contract (the `ClickableRow` rule,
                    // applied to this row).
                    if (fromInnerControl(event)) return;
                    navigate(`/admin/contracts/${row.id}`);
                  }}
                  onKeyDown={(event) => {
                    if (fromInnerControl(event)) return;
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      navigate(`/admin/contracts/${row.id}`);
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
                  <td>
                    {row.customer_name && canOpenCustomer ? (
                      <Link
                        to={`/admin/customers/${row.customer}`}
                        className="row-fact-link"
                        data-testid={`contracts-row-customer-${row.id}`}
                        onClick={(event) => event.stopPropagation()}
                      >
                        {row.customer_name}
                      </Link>
                    ) : (
                      (row.customer_name ?? "")
                    )}
                    {/* P-3 §C.1 / P-11 C — the row reads as a sentence,
                        now under the customer it belongs to. */}
                    <span
                      className="contract-sentence"
                      data-testid={`contracts-sentence-${row.id}`}
                    >
                      {contractSentence(row, t, locale)}
                    </span>
                  </td>
                  <td>
                    {row.buildings.length === 0 ? (
                      <span className="muted-empty">{t("sentence.no_locations")}</span>
                    ) : (
                      <BuildingsCell
                        buildings={row.buildings}
                        linked={canOpenBuilding}
                        testIdPrefix={`contracts-row-building-${row.id}`}
                        moreLabel={(n) => t("table.andMore", { count: n })}
                      />
                    )}
                  </td>
                  <td data-testid={`contracts-period-${row.id}`}>
                    {periodLabel(row)}
                  </td>
                  <td className="contract-num">
                    {formatMoney(row.monthly_amount, locale)}
                  </td>
                  <td>
                    <span className={`cell-tag ${CONTRACT_STATUS_TAG[row.status]}`}>
                      {t(`status.${row.status}`)}
                    </span>
                  </td>
                </tr>
              ))}
              {!loading && contracts.length === 0 && (
                <tr>
                  <td colSpan={totalColumnCount}>
                    {filtersActive || Boolean(searchActive) ? (
                      <span className="muted">{t("table.emptyFiltered")}</span>
                    ) : (
                      <TeachEmpty
                        testId={`contracts-road-empty-${listView}`}
                        title={t(`road.${listView}_empty_title`)}
                        body={t(`road.${listView}_empty_body`)}
                      />
                    )}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* The phone-width layout, kept in step with the table above:
            the same five facts, nothing more (P-11 C). */}
        <ul className="admin-card-list" data-testid="contracts-card-list">
          {contracts.map((row) => (
            <li key={row.id} className="admin-card">
              <div className="admin-card-head">
                <Link
                  to={`/admin/contracts/${row.id}`}
                  className="admin-card-title admin-card-link"
                >
                  {row.customer_name ?? row.contract_no}
                </Link>
                <span className={`cell-tag ${CONTRACT_STATUS_TAG[row.status]}`}>
                  {t(`status.${row.status}`)}
                </span>
              </div>
              <div className="admin-card-meta-row">
                <span className="admin-card-meta contract-sentence">
                  {contractSentence(row, t, locale)}
                </span>
              </div>
              {row.buildings.length > 0 && (
                <div className="admin-card-meta-row">
                  <span className="admin-card-meta">
                    <BuildingsCell
                      buildings={row.buildings}
                      linked={canOpenBuilding}
                      testIdPrefix={`contracts-card-building-${row.id}`}
                      moreLabel={(n) => t("table.andMore", { count: n })}
                    />
                  </span>
                </div>
              )}
              <div className="admin-card-meta-row">
                <span className="admin-card-meta">{periodLabel(row)}</span>
              </div>
              <div className="admin-card-meta-row">
                <span className="admin-card-meta">
                  {t("table.monthlyAmount")}:{" "}
                  {formatMoney(row.monthly_amount, locale)}
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

/**
 * The Locations cell: the first two names plus a "+N" chip. Bounded on
 * purpose — a contract can cover a dozen buildings, and an unbounded
 * cell looks fine on seed data and destroys the row height on real
 * data. Same shape as the buildings list's Customers cell.
 */
function BuildingsCell({
  buildings,
  linked,
  testIdPrefix,
  moreLabel,
}: {
  buildings: ContractBuildingRef[];
  /** P-8R F — each shown name is a link to the building's own page.
   *  Off for a role the building detail's guard would turn away. */
  linked: boolean;
  testIdPrefix: string;
  moreLabel: (n: number) => string;
}) {
  const shown = buildings.slice(0, 2);
  const hidden = buildings.length - shown.length;
  return (
    <span>
      {shown.map((building, index) => (
        <Fragment key={building.id}>
          {index > 0 ? ", " : ""}
          {linked ? (
            <Link
              to={`/admin/buildings/${building.id}`}
              className="row-fact-link"
              data-testid={`${testIdPrefix}-${building.id}`}
              onClick={(event) => event.stopPropagation()}
            >
              {building.name}
            </Link>
          ) : (
            building.name
          )}
        </Fragment>
      ))}
      {hidden > 0 && (
        <span className="cell-tag cell-tag-muted" style={{ marginLeft: 6 }}>
          {moreLabel(hidden)}
        </span>
      )}
    </span>
  );
}

/**
 * P-8R F — did this event start on a control INSIDE the row (a link, a
 * button, the edit-mode checkbox)? Then the row must not also react:
 * `ClickableRow` makes the same check, and this table's rows are not
 * `ClickableRow` yet. Covers keyboard too — an Enter on a focused inline
 * link bubbles to the row, and without this the row would open the
 * contract on top of the page the link opened.
 */
function fromInnerControl(event: SyntheticEvent<HTMLTableRowElement>): boolean {
  if (!(event.target instanceof HTMLElement)) return false;
  const inner = event.target.closest("a,button,input,select,textarea,label");
  return inner !== null && inner !== event.currentTarget;
}
