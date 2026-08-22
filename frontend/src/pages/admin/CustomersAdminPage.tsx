import type { FormEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getApiError } from "../../api/client";
import { SortableHeader } from "../../components/SortableHeader";
import type { SortState } from "../../components/SortableHeader";
import {
  bulkDeactivateCustomers,
  bulkLinkBuildings,
  bulkUpdateCustomers,
  deactivateCustomer,
  listAllBuildings,
  listAllCompanies,
  listCustomers,
  reactivateCustomer,
  updateCustomer,
} from "../../api/admin";
import type { AdminListParams } from "../../api/admin";
import type { BuildingAdmin, CompanyAdmin, CustomerAdmin } from "../../api/types";
import { CUSTOMER_LIFECYCLE_VALUES } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import type { ConfirmDialogHandle } from "../../components/ConfirmDialog";
import { BulkAssignDialog } from "../../components/BulkAssignDialog";
import { BulkEditDialog } from "../../components/BulkEditDialog";
import { EditModeToggle } from "../../components/EditModeToggle";
import { MultiSelectToolbar } from "../../components/MultiSelectToolbar";
import { useEditMode } from "../../lib/useEditMode";
import { useSavedBanner } from "../../hooks/useSavedBanner";

type ActiveFilter = "true" | "false" | "all";

/**
 * Sprint 153 §3.3 — the columns a header click can sort by. Each entry
 * names a `CustomerViewSet.ordering_fields` entry; the backend allowlist
 * is the authority and silently ignores anything not on it.
 */
type SortField = "name" | "contact_email" | "is_active";

/** Sprint 185 §3 — the lifecycle's colour, reusing the app's existing
 *  status tones rather than inventing a sixth palette. NOTICE is the one
 *  that costs money — you are still cleaning, still incurring cost — so
 *  it gets the waiting tone that means "needs attention", not the
 *  neutral one that means "nothing to see". */
const LIFECYCLE_TONE: Record<string, string> = {
  PROSPECT: "cell-tag-muted",
  ONBOARDING: "cell-tag-in_progress",
  ACTIVE: "cell-tag-open",
  NOTICE: "cell-tag-waiting_customer_approval",
  CHURNED: "cell-tag-closed",
};

type SortDirection = "asc" | "desc";

const DEBOUNCE_MS = 300;


export function CustomersAdminPage() {
  const navigate = useNavigate();
  const { t } = useTranslation("common");

  const [customers, setCustomers] = useState<CustomerAdmin[]>([]);
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
  // Sprint 185 §3 — a SEPARATE axis from `is_active` above. Filtering by
  // one must never imply the other; they answer different questions.
  const [lifecycleFilter, setLifecycleFilter] = useState<string>("");
  const [companyFilter, setCompanyFilter] = useState<number | "">("");
  const [buildingFilter, setBuildingFilter] = useState<number | "">("");
  const [sortField, setSortField] = useState<SortField>("name");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");

  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companiesLoaded, setCompaniesLoaded] = useState(false);
  const [buildings, setBuildings] = useState<BuildingAdmin[]>([]);

  // Sprint 153 §3.4 — bulk selection. Ids only; the rows themselves are
  // re-read from `customers` at action time.
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkBusy, setBulkBusy] = useState(false);
  const bulkDialogRef = useRef<ConfirmDialogHandle>(null);

  // Sprint 154 §D/§F — bulk edit and bulk assign-buildings.
  const [bulkEditOpen, setBulkEditOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [assignBuildingIds, setAssignBuildingIds] = useState<number[]>([]);
  const [assignOptions, setAssignOptions] = useState<BuildingAdmin[]>([]);
  const [assignError, setAssignError] = useState("");

  // Sprint 153 §3.5 — edit-in-place. `editTarget` is the row being
  // edited; the form component is KEYED by its id so the seed values
  // come from the prop on mount instead of from a syncing effect
  // (CLAUDE.md §3 — no synchronous setState in an effect body).
  const [editTarget, setEditTarget] = useState<CustomerAdmin | null>(null);

  const [savedBanner, setSavedBanner] = useSavedBanner({
    saved: t("customers.banner_saved"),
    deactivated: t("customers.banner_deactivated"),
    reactivated: t("customers.banner_reactivated"),
  });

  // Companies for the filter dropdown.
  useEffect(() => {
    let cancelled = false;
    listAllCompanies({ is_active: "true" })
      .then((response) => {
        if (cancelled) return;
        setCompanies(response);
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

  // Buildings reload whenever the company filter changes. Sprint 153
  // removed the Building COLUMN (a customer sits in many buildings, so
  // one column was a lie) but kept the building FILTER, which is a
  // genuinely useful narrowing — hence this effect stays.
  useEffect(() => {
    if (companyFilter === "") {
      setBuildings([]);
      return;
    }
    let cancelled = false;
    listAllBuildings({ is_active: "true", company: companyFilter })
      .then((response) => {
        if (!cancelled) setBuildings(response);
      })
      .catch(() => {
        if (!cancelled) setBuildings([]);
      });
    return () => {
      cancelled = true;
    };
  }, [companyFilter]);

  // When the company filter changes, drop a stale building selection.
  useEffect(() => {
    if (
      buildingFilter !== "" &&
      buildings.length > 0 &&
      !buildings.some((b) => b.id === buildingFilter)
    ) {
      setBuildingFilter("");
    }
  }, [buildings, buildingFilter]);

  const companyDropdownDisabled = companiesLoaded && companies.length <= 1;

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setSearchActive(searchInput.trim());
      setPage(1);
      // Sprint 153 §3.4 — a hidden-but-selected row being deactivated is
      // a real surprise, so every narrowing of the view drops the
      // selection. Done in the handlers (and in this settled timeout),
      // never in a synchronous effect body.
      setSelectedIds([]);
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [searchInput]);

  const queryParams = useMemo<AdminListParams>(() => {
    const params: AdminListParams = { page };
    if (searchActive) params.search = searchActive;
    if (activeFilter !== "all") params.is_active = activeFilter;
    if (lifecycleFilter !== "") params.lifecycle = lifecycleFilter;
    if (companyFilter !== "") params.company = companyFilter;
    if (buildingFilter !== "") params.building = buildingFilter;
    params.ordering = sortDirection === "desc" ? `-${sortField}` : sortField;
    return params;
  }, [
    page,
    searchActive,
    lifecycleFilter,
    activeFilter,
    companyFilter,
    buildingFilter,
    sortField,
    sortDirection,
  ]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await listCustomers(queryParams);
      setCustomers(response.results);
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

  // Sprint 153 §3.1 — the ACTIVE tile needs its own count. Counting the
  // rendered rows would count one page, not the tenant. `page_size=1`
  // asks the server for the number and one throwaway row rather than
  // loosening `pagination_class` (Sprint 134 did that to three viewsets
  // and broke the list pages' own prev/next; Sprint 135 reverted it).
  // Deliberately NOT narrowed by search / status — the tile answers
  // "how many active customers exist", not "how many match the filter".
  const activeCountParams = useMemo<AdminListParams>(() => {
    const params: AdminListParams = { is_active: "true", page_size: 1 };
    if (companyFilter !== "") params.company = companyFilter;
    return params;
  }, [companyFilter]);

  const [countsReloadToken, setCountsReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    listCustomers(activeCountParams)
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
      buildingFilter !== "" ||
      (companyFilter !== "" && !companyDropdownDisabled),
  );

  // --- sorting ---------------------------------------------------------
  //
  // The page reset and the selection reset happen HERE, in the click
  // handler, and not in an effect watching the sort state. Sprint 152
  // §10 added six set-state-in-effect violations of exactly that shape
  // on its first draft; the ESLint baseline is what enforces the rule.
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
  const pageIds = useMemo(() => customers.map((c) => c.id), [customers]);
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

  // Sprint 155 §4 — the checkbox column and the bulk toolbar exist only
  // inside edit mode. Same split as the Buildings list: the MODE comes
  // from the shared controller, the cross-page SELECTION stays this
  // page's own, and `onExit` keeps "leaving edit mode clears the
  // selection" true. See lib/useEditMode.ts.
  const edit = useEditMode(pageIds, { onExit: () => setSelectedIds([]) });

  async function handleConfirmBulkDeactivate() {
    if (selectedIds.length === 0) return;
    setBulkBusy(true);
    setError("");
    const targeted = [...selectedIds];
    try {
      const result = await bulkDeactivateCustomers(targeted);
      bulkDialogRef.current?.close();
      // Local state FIRST, refetch after. The server call already
      // succeeded, so the row state is known here; waiting for the
      // refetch to reveal it leaves the table showing stale ACTIVE tags
      // for as long as the request takes.
      setCustomers((current) =>
        current.map((customer) =>
          targeted.includes(customer.id)
            ? { ...customer, is_active: false }
            : customer,
        ),
      );
      setSelectedIds([]);
      setSavedBanner(
        t("customers.bulk_deactivated", { count: result.deactivated }),
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

  // --- bulk edit (§D) --------------------------------------------------

  async function handleBulkEdit(patch: Record<string, string>) {
    setBulkBusy(true);
    setError("");
    const targeted = [...selectedIds];
    try {
      const result = await bulkUpdateCustomers(targeted, patch);
      setBulkEditOpen(false);
      setSelectedIds([]);
      setSavedBanner(t("bulk_edit.updated", { count: result.updated }));
      setCountsReloadToken((token) => token + 1);
      await load();
    } catch (err) {
      // Verbatim, and the dialog STAYS OPEN so the operator can correct
      // the field rather than losing their selection.
      setError(getApiError(err));
      setBulkEditOpen(false);
    } finally {
      setBulkBusy(false);
    }
  }

  // --- assign buildings (§F, the customers-side direction) -------------

  function openAssignBuildings() {
    setAssignBuildingIds([]);
    setAssignError("");
    setAssignOpen(true);
    // Exhaustive paging (the Sprint 120/135 pattern), so a provider with
    // hundreds of buildings gets all of them and not a truncated first
    // page. `listAllBuildings` loops until `next` is null.
    const company =
      companyFilter !== ""
        ? companyFilter
        : customers.find((c) => selectedIds.includes(c.id))?.company;
    listAllBuildings(
      company === undefined
        ? { is_active: "true" }
        : { is_active: "true", company },
    )
      .then(setAssignOptions)
      .catch((err) => setAssignError(getApiError(err)));
  }

  async function handleConfirmAssignBuildings() {
    setBulkBusy(true);
    setAssignError("");
    try {
      const result = await bulkLinkBuildings({
        buildings: assignBuildingIds,
        relation: "customers",
        targets: selectedIds,
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

  // --- edit in place ---------------------------------------------------
  function handleEditSaved(updated: CustomerAdmin) {
    setEditTarget(null);
    setCustomers((current) =>
      current.map((customer) =>
        customer.id === updated.id ? updated : customer,
      ),
    );
    setSavedBanner(t("customers.banner_saved"));
    setCountsReloadToken((token) => token + 1);
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("nav.admin_group")}
          </div>
          <h2 className="page-title">{t("nav.customers")}</h2>
          <p className="page-sub">
            {loading
              ? t("customers.loading")
              : t("customers.count", { count })}
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
          <Link className="btn btn-primary btn-sm" to="/admin/customers/new">
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

      {/* Sprint 153 §3.6 — the tiles live INSIDE the list card, above the
          filter bar, so the page reads as one block instead of
          header / gap / filters / gap / table. */}
      <div className="card" style={{ overflow: "hidden" }}>
        <div
          className="summary-grid"
          data-testid="customers-stat-tiles"
          style={{
            gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
            margin: "14px 18px 4px",
          }}
        >
          <div className="summary-stat" data-testid="customers-stat-total">
            <span className="summary-stat-label">
              {t("customers.stat_total")}
            </span>
            <span className="summary-stat-value">{count}</span>
            <span className="summary-stat-meta">
              {t("customers.stat_total_meta")}
            </span>
          </div>
          <div className="summary-stat" data-testid="customers-stat-active">
            <span className="summary-stat-label">
              {t("customers.stat_active")}
            </span>
            <span className="summary-stat-value">{activeCount ?? "—"}</span>
            <span className="summary-stat-meta">
              {t("customers.stat_active_meta")}
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
              placeholder={t("customers.search_placeholder")}
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
          {/* Sprint 185 §3 — where the relationship IS, beside whether
              the account is switched on. The one an operator reaches for
              is "Notice period": who is leaving, and are we still
              serving them properly. */}
          <div className="filter-field">
            <span className="filter-label">{t("customers.lifecycle")}</span>
            <select
              className="filter-control"
              value={lifecycleFilter}
              data-testid="customers-filter-lifecycle"
              onChange={(event) => {
                setLifecycleFilter(event.target.value);
                setPage(1);
                setSelectedIds([]);
              }}
            >
              <option value="">{t("customers.lifecycle_all")}</option>
              {CUSTOMER_LIFECYCLE_VALUES.map((value) => (
                <option key={value} value={value}>
                  {t(`customers.lifecycle_${value.toLowerCase()}`)}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-field">
            <span className="filter-label">{t("company")}</span>
            {/* Cap the Company select so it matches Search / Status / Building
                instead of stretching the filter-bar's 1fr track. */}
            <select
              className="filter-control"
              style={{ maxWidth: 220 }}
              value={companyFilter === "" ? "" : String(companyFilter)}
              onChange={(event) => {
                const v = event.target.value;
                setCompanyFilter(v === "" ? "" : Number(v));
                setBuildingFilter("");
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
          <div className="filter-field">
            <span className="filter-label">{t("building")}</span>
            <select
              className="filter-control"
              value={buildingFilter === "" ? "" : String(buildingFilter)}
              onChange={(event) => {
                const v = event.target.value;
                setBuildingFilter(v === "" ? "" : Number(v));
                setPage(1);
                setSelectedIds([]);
              }}
              disabled={companyFilter === "" || buildings.length === 0}
            >
              <option value="">{t("admin.all_buildings")}</option>
              {buildings.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
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
                  setBuildingFilter("");
                  setPage(1);
                  setSelectedIds([]);
                }}
              >
                {t("clear")}
              </button>
            )}
            {pageIds.length > 0 && (
              <EditModeToggle
                editMode={edit.editMode}
                onToggle={edit.toggleMode}
                disabled={bulkBusy}
                testId="customers-edit-mode-toggle"
              />
            )}
          </div>
        </form>

        {/* Sprint 153 §3.4 — the toolbar appears only with a selection. */}
        {edit.editMode && (
          <MultiSelectToolbar
            selectedCount={selectedIds.length}
            onSelectAll={() =>
              setSelectedIds((current) => [
                ...new Set([...current, ...pageIds]),
              ])
            }
            onClearAll={() => setSelectedIds([])}
            disabled={bulkBusy}
            actions={[
              // Sprint 154 §D — the label says Delete because that is what
              // an operator means, but the server DEACTIVATES: customers
              // are never hard-deleted (invoices and extra work PROTECT
              // the row). The confirm body says so in plain words, so the
              // label and the behaviour do not disagree.
              {
                key: "delete",
                label: t("customers.bulk_delete"),
                destructive: true,
                onClick: () => bulkDialogRef.current?.open(),
              },
              {
                key: "edit",
                label: t("customers.bulk_edit"),
                onClick: () => setBulkEditOpen(true),
              },
              {
                key: "assign-buildings",
                label: t("customers.assign_buildings"),
                onClick: () => openAssignBuildings(),
              },
            ]}
            testIdPrefix="customers-bulk"
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
                      aria-label={t("customers.select_page")}
                      data-testid="customers-select-page"
                    />
                  </th>
                )}
                <SortableHeader
                  label={t("admin.col_name")}
                  sort={sortStateFor("name")}
                  testId="customers-sort-name"
                  onSort={() => handleSort("name")}
                  sortByLabel={t("customers.sort_by", {
                    column: t("admin.col_name"),
                  })}
                />
                <th>{t("company")}</th>
                <SortableHeader
                  label={t("customers.col_contact_email")}
                  sort={sortStateFor("contact_email")}
                  testId="customers-sort-contact_email"
                  onSort={() => handleSort("contact_email")}
                  sortByLabel={t("customers.sort_by", {
                    column: t("customers.col_contact_email"),
                  })}
                />
                <th>{t("customers.col_buildings")}</th>
                <th>{t("customers.col_users")}</th>
                <th>{t("customers.col_contacts")}</th>
                <th>{t("customers.lifecycle")}</th>
                <SortableHeader
                  label={t("status")}
                  sort={sortStateFor("is_active")}
                  testId="customers-sort-is_active"
                  onSort={() => handleSort("is_active")}
                  sortByLabel={t("customers.sort_by", { column: t("status") })}
                />
                <th aria-label={t("admin.col_actions")} />
              </tr>
            </thead>
            <tbody>
              {customers.map((customer) => {
                const detailPath = `/admin/customers/${customer.id}`;
                const openDetail = () => navigate(detailPath);
                return (
                  <tr
                    key={customer.id}
                    className="admin-row-clickable"
                    role="link"
                    tabIndex={0}
                    aria-label={t("admin.view") + ": " + customer.name}
                    /* W14 §3 — one click, one history entry. The row
                       navigates AND contains a `<Link>` to the same
                       place, so a click on the link pushed twice and
                       the browser's Back then landed on the page it was
                       pressed from. Same defect, same fix, as the
                       tickets list. */
                    onClick={(event) => {
                      if ((event.target as HTMLElement).closest("a,button")) {
                        return;
                      }
                      openDetail();
                    }}
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
                          checked={selectedIds.includes(customer.id)}
                          onChange={() => toggleRow(customer.id)}
                          disabled={bulkBusy}
                          aria-label={t("customers.select_row", {
                            name: customer.name,
                          })}
                          data-testid={`customers-select-${customer.id}`}
                        />
                      </td>
                    )}
                    <td className="td-subject">
                      <Link to={detailPath}>{customer.name}</Link>
                    </td>
                    <td>{companyName(customer.company)}</td>
                    <td>{customer.contact_email || "—"}</td>
                    <td>{customer.linked_building_count}</td>
                    <td>{customer.user_count}</td>
                    <td>{customer.contact_count}</td>
                    <td>
                      <span
                        className={`cell-tag ${
                          LIFECYCLE_TONE[customer.lifecycle] ?? "cell-tag-muted"
                        }`}
                        data-testid={`customers-lifecycle-${customer.id}`}
                      >
                        <i />
                        {t(
                          `customers.lifecycle_${(customer.lifecycle || "active").toLowerCase()}`,
                        )}
                      </span>
                    </td>
                    <td>
                      <span
                        className={`cell-tag cell-tag-${customer.is_active ? "open" : "closed"}`}
                      >
                        <i />
                        {customer.is_active
                          ? t("admin.status_active")
                          : t("admin.status_inactive")}
                      </span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        data-testid={`customers-edit-${customer.id}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          setEditTarget(customer);
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

        {/* Sprint 22 final polish: phone-width parallel card list.
            Sprint 153: every column change above is mirrored here, or the
            phone layout silently drifts from the table. */}
        <ul
          className="admin-card-list"
          data-testid="admin-card-list"
          aria-label={t("nav.customers")}
        >
          {customers.map((customer) => {
            const detailPath = `/admin/customers/${customer.id}`;
            return (
              <li key={customer.id} className="admin-card">
                <Link
                  to={detailPath}
                  className="admin-card-link"
                  aria-label={`${t("admin.view")}: ${customer.name}`}
                >
                  <div className="admin-card-head">
                    <span className="admin-card-title">{customer.name}</span>
                    <span
                      className={`cell-tag cell-tag-${customer.is_active ? "open" : "closed"}`}
                    >
                      <i />
                      {customer.is_active
                        ? t("admin.status_active")
                        : t("admin.status_inactive")}
                    </span>
                  </div>
                  <dl className="admin-card-meta">
                    <div className="admin-card-meta-row">
                      <dt>{t("company")}</dt>
                      <dd>{companyName(customer.company)}</dd>
                    </div>
                    {customer.contact_email && (
                      <div className="admin-card-meta-row">
                        <dt>{t("customers.col_contact_email")}</dt>
                        <dd>{customer.contact_email}</dd>
                      </div>
                    )}
                    <div className="admin-card-meta-row">
                      <dt>{t("customers.col_buildings")}</dt>
                      <dd>{customer.linked_building_count}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("customers.col_users")}</dt>
                      <dd>{customer.user_count}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("customers.col_contacts")}</dt>
                      <dd>{customer.contact_count}</dd>
                    </div>
                  </dl>
                </Link>
                <div className="admin-card-actions">
                  <button
                    type="button"
                    className="btn btn-ghost btn-sm"
                    data-testid={`customers-card-edit-${customer.id}`}
                    onClick={() => setEditTarget(customer)}
                  >
                    {t("admin.edit")}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>

        {!loading && customers.length === 0 && (
          <div className="empty-state">
            <div className="empty-icon">＋</div>
            <div className="empty-title">
              {hasActiveFilters
                ? t("customers.empty_filtered_title")
                : t("customers.empty_initial_title")}
            </div>
            <p className="empty-sub">
              {hasActiveFilters
                ? t("admin.empty_filtered_desc")
                : t("customers.empty_initial_desc")}
            </p>
            {!hasActiveFilters && (
              <Link className="btn btn-primary btn-sm" to="/admin/customers/new">
                {t("customers.create")}
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
          <dialog> mounted behind `{cond && ...}` is invisible and its
          trigger looks dead (Sprint 128); unmounting an open one can
          leave the page inert (Sprint 118). CLAUDE.md §3. */}
      <ConfirmDialog
        ref={bulkDialogRef}
        title={t("customers.bulk_delete_title")}
        body={t("customers.bulk_delete_body", {
          count: selectedIds.length,
        })}
        confirmLabel={t("customers.bulk_delete")}
        onConfirm={handleConfirmBulkDeactivate}
        busy={bulkBusy}
        destructive
      />

      {bulkEditOpen && (
        <BulkEditDialog
          title={t("customers.bulk_edit_title", { count: selectedIds.length })}
          intro={t("customers.bulk_edit_intro")}
          fields={[
            {
              key: "language",
              label: t("customers.field_language"),
              options: [
                { value: "nl", label: `${t("language_dutch")} (nl)` },
                { value: "en", label: `${t("language_english")} (en)` },
              ],
            },
            {
              key: "status",
              label: t("customers.field_status"),
              options: [
                { value: "active", label: t("admin.status_active") },
                { value: "inactive", label: t("admin.status_inactive") },
              ],
            },
          ]}
          onCancel={() => setBulkEditOpen(false)}
          onSubmit={handleBulkEdit}
          busy={bulkBusy}
          testIdPrefix="customers-bulk-edit"
        />
      )}

      {assignOpen && (
        <BulkAssignDialog
          title={t("customers.assign_buildings_title")}
          summary={t("customers.assign_buildings_summary", {
            buildings: assignBuildingIds.length,
            customers: selectedIds.length,
          })}
          options={assignOptions.map((b) => ({
            id: b.id,
            label: b.name,
            sublabel: [b.city, b.address].filter(Boolean).join(" — "),
          }))}
          selectedIds={assignBuildingIds}
          onChange={setAssignBuildingIds}
          onCancel={() => setAssignOpen(false)}
          onConfirm={handleConfirmAssignBuildings}
          confirmLabel={t("bulk_link.confirm")}
          busy={bulkBusy}
          error={assignError}
          emptyText={t("customers.assign_buildings_empty")}
          contextTitle={t("customers.selected_customers")}
          contextItems={customers
            .filter((c) => selectedIds.includes(c.id))
            .map((c) => c.name)}
          testIdPrefix="customers-assign-buildings"
        />
      )}

      {editTarget && (
        <CustomerQuickEditDialog
          key={editTarget.id}
          customer={editTarget}
          onClose={() => setEditTarget(null)}
          onSaved={handleEditSaved}
        />
      )}
    </div>
  );
}

/**
 * Sprint 153 §3.5 — edit the five basics without leaving the list.
 *
 * This REPLACES the row's link to `/admin/customers/:id/edit`; the full
 * `CustomerFormPage` route is untouched and still reachable from the
 * customer detail page's "Edit basics" action and from the link at the
 * foot of this dialog. It carries far more than these five fields, so
 * this is a shortcut for the common edit, not a replacement.
 *
 * Deliberately a non-native overlay, matching the CustomerContactsPage
 * create/edit modal: the form needs its own Cancel/Save toolbar without
 * inheriting `<dialog>`'s focus quirks, and that is the established
 * idiom for an editing modal in this codebase (ConfirmDialog remains
 * the native `<dialog>`, ref-driven, for confirmations).
 *
 * The parent KEYS this component by customer id, so the initial state
 * below is seeded from the prop exactly once per customer — no effect
 * syncing prop to state (CLAUDE.md §3).
 */
function CustomerQuickEditDialog({
  customer,
  onClose,
  onSaved,
}: {
  customer: CustomerAdmin;
  onClose: () => void;
  onSaved: (updated: CustomerAdmin) => void;
}) {
  const { t } = useTranslation("common");
  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const [name, setName] = useState(customer.name);
  const [contactEmail, setContactEmail] = useState(customer.contact_email);
  const [phone, setPhone] = useState(customer.phone);
  const [language, setLanguage] = useState(customer.language);
  const [isActive, setIsActive] = useState(customer.is_active);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  // `is_active` is READ-ONLY on CustomerSerializer, so status cannot ride
  // along on the PATCH — it would be silently dropped and the dialog
  // would report a save that never happened. The lifecycle has its own
  // two endpoints, with their own gates: DELETE (soft) for deactivate,
  // and POST /reactivate/ which is SUPER_ADMIN-only. This dialog drives
  // those, and only offers reactivation to a SUPER_ADMIN — matching the
  // gate already applied on the customer Settings and Overview pages.
  const canReactivate = isSuperAdmin;
  const statusLocked = !customer.is_active && !canReactivate;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFormError("");
    try {
      // Basics first. A COMPANY_ADMIN's scope excludes INACTIVE
      // customers, so patching after a deactivate would 404 on the row
      // it just deactivated.
      let updated = await updateCustomer(customer.id, {
        name,
        contact_email: contactEmail,
        phone,
        language,
      });

      if (isActive !== customer.is_active) {
        if (isActive) {
          updated = await reactivateCustomer(customer.id);
        } else {
          await deactivateCustomer(customer.id);
          updated = { ...updated, is_active: false };
        }
      }

      onSaved(updated);
    } catch (err) {
      // Verbatim, in the dialog. Swallowing it would leave the operator
      // staring at a form that silently refused to save.
      setFormError(getApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      data-testid="customer-quick-edit-modal"
      role="dialog"
      aria-modal="true"
      aria-label={t("customers.edit_dialog_title")}
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
          maxWidth: 520,
          width: "100%",
          padding: 24,
          maxHeight: "90vh",
          overflowY: "auto",
        }}
      >
        <h3 className="section-title" style={{ marginTop: 0, marginBottom: 4 }}>
          {t("customers.edit_dialog_title")}
        </h3>
        <p className="muted small" style={{ marginTop: 0, marginBottom: 16 }}>
          {t("customers.edit_dialog_intro")}
        </p>

        {formError && (
          <div
            className="alert-error"
            role="alert"
            style={{ marginBottom: 12 }}
            data-testid="customer-quick-edit-error"
          >
            {formError}
          </div>
        )}

        <div className="field">
          <label className="field-label" htmlFor="quick-edit-name">
            {t("customers.field_name")} *
          </label>
          <input
            id="quick-edit-name"
            className="field-input"
            type="text"
            value={name}
            onChange={(event) => setName(event.target.value)}
            data-testid="customer-quick-edit-name"
            required
            disabled={busy}
          />
        </div>

        <div className="form-2col">
          <div className="field">
            <label className="field-label" htmlFor="quick-edit-email">
              {t("customers.field_contact_email")}
            </label>
            <input
              id="quick-edit-email"
              className="field-input"
              type="email"
              value={contactEmail}
              onChange={(event) => setContactEmail(event.target.value)}
              data-testid="customer-quick-edit-email"
              disabled={busy}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="quick-edit-phone">
              {t("customers.field_phone")}
            </label>
            <input
              id="quick-edit-phone"
              className="field-input"
              type="tel"
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              data-testid="customer-quick-edit-phone"
              disabled={busy}
            />
          </div>
        </div>

        <div className="form-2col">
          <div className="field">
            <label className="field-label" htmlFor="quick-edit-language">
              {t("customers.field_language")}
            </label>
            <select
              id="quick-edit-language"
              className="field-select"
              value={language}
              onChange={(event) => setLanguage(event.target.value)}
              data-testid="customer-quick-edit-language"
              disabled={busy}
            >
              <option value="nl">{t("language_dutch")} (nl)</option>
              <option value="en">{t("language_english")} (en)</option>
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="quick-edit-status">
              {t("customers.field_status")}
            </label>
            <select
              id="quick-edit-status"
              className="field-select"
              value={isActive ? "true" : "false"}
              onChange={(event) => setIsActive(event.target.value === "true")}
              data-testid="customer-quick-edit-status"
              disabled={busy || statusLocked}
              title={
                statusLocked
                  ? t("customer_view.settings.reactivate_consequence")
                  : undefined
              }
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
            to={`/admin/customers/${customer.id}/edit`}
            className="btn btn-ghost btn-sm"
            data-testid="customer-quick-edit-full-form"
          >
            {t("customers.edit_dialog_full_form")}
          </Link>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onClose}
              disabled={busy}
              data-testid="customer-quick-edit-cancel"
            >
              {t("cancel")}
            </button>
            <button
              type="submit"
              className="btn btn-primary btn-sm"
              disabled={busy}
              data-testid="customer-quick-edit-save"
            >
              {busy ? t("admin_form.saving") : t("admin_form.save_changes")}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
