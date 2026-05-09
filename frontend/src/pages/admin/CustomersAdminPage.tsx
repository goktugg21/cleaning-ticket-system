import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getApiError } from "../../api/client";
import { listBuildings, listCompanies, listCustomers } from "../../api/admin";
import type { AdminListParams } from "../../api/admin";
import type { BuildingAdmin, CompanyAdmin, CustomerAdmin } from "../../api/types";
import { useSavedBanner } from "../../hooks/useSavedBanner";

type ActiveFilter = "true" | "false" | "all";

const DEBOUNCE_MS = 300;

export function CustomersAdminPage() {
  const { t } = useTranslation("common");

  const [customers, setCustomers] = useState<CustomerAdmin[]>([]);
  const [count, setCount] = useState(0);
  const [next, setNext] = useState<string | null>(null);
  const [previous, setPrevious] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [searchInput, setSearchInput] = useState("");
  const [searchActive, setSearchActive] = useState("");
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("true");
  const [companyFilter, setCompanyFilter] = useState<number | "">("");
  const [buildingFilter, setBuildingFilter] = useState<number | "">("");

  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companiesLoaded, setCompaniesLoaded] = useState(false);
  const [buildings, setBuildings] = useState<BuildingAdmin[]>([]);

  const [savedBanner] = useSavedBanner({
    saved: t("customers.banner_saved"),
    deactivated: t("customers.banner_deactivated"),
    reactivated: t("customers.banner_reactivated"),
  });

  // Companies for the filter dropdown.
  useEffect(() => {
    let cancelled = false;
    listCompanies({ is_active: "true", page_size: 200 })
      .then((response) => {
        if (cancelled) return;
        setCompanies(response.results);
        if (response.results.length === 1) {
          setCompanyFilter(response.results[0].id);
        }
      })
      .finally(() => {
        if (!cancelled) setCompaniesLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Buildings reload whenever the company filter changes.
  useEffect(() => {
    if (companyFilter === "") {
      setBuildings([]);
      return;
    }
    let cancelled = false;
    listBuildings({ is_active: "true", page_size: 200, company: companyFilter })
      .then((response) => {
        if (!cancelled) setBuildings(response.results);
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
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [searchInput]);

  const queryParams = useMemo<AdminListParams>(() => {
    const params: AdminListParams = { page };
    if (searchActive) params.search = searchActive;
    if (activeFilter !== "all") params.is_active = activeFilter;
    if (companyFilter !== "") params.company = companyFilter;
    if (buildingFilter !== "") params.building = buildingFilter;
    return params;
  }, [page, searchActive, activeFilter, companyFilter, buildingFilter]);

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

  const companyName = useCallback(
    (id: number) =>
      companies.find((c) => c.id === id)?.name ??
      t("buildings.company_fallback", { id }),
    [companies, t],
  );
  const buildingName = useCallback(
    (id: number | null) => {
      // Sprint 14: legacy building can be null on consolidated customers.
      if (id === null) return "—";
      return (
        buildings.find((b) => b.id === id)?.name ??
        t("customers.building_fallback", { id })
      );
    },
    [buildings, t],
  );

  const hasActiveFilters = Boolean(
    searchActive ||
      activeFilter !== "true" ||
      buildingFilter !== "" ||
      (companyFilter !== "" && !companyDropdownDisabled),
  );

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

      <div className="card" style={{ overflow: "hidden" }}>
        <form
          className="filter-bar"
          onSubmit={(event) => {
            event.preventDefault();
            setSearchActive(searchInput.trim());
            setPage(1);
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
              }}
            >
              <option value="true">{t("admin.status_active")}</option>
              <option value="false">{t("admin.status_inactive")}</option>
              <option value="all">{t("admin.status_all")}</option>
            </select>
          </div>
          <div className="filter-field">
            <span className="filter-label">{t("company")}</span>
            <select
              className="filter-control"
              value={companyFilter === "" ? "" : String(companyFilter)}
              onChange={(event) => {
                const v = event.target.value;
                setCompanyFilter(v === "" ? "" : Number(v));
                setBuildingFilter("");
                setPage(1);
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
                }}
              >
                {t("clear")}
              </button>
            )}
          </div>
        </form>

        {loading && (
          <div className="loading-bar" style={{ margin: 0 }}>
            <div className="loading-bar-fill" />
          </div>
        )}

        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("admin.col_name")}</th>
                <th>{t("company")}</th>
                <th>{t("building")}</th>
                <th>{t("customers.col_contact_email")}</th>
                <th>{t("status")}</th>
                <th aria-label={t("admin.col_actions")} />
              </tr>
            </thead>
            <tbody>
              {customers.map((customer) => (
                <tr key={customer.id}>
                  <td className="td-subject">
                    <Link to={`/admin/customers/${customer.id}`}>{customer.name}</Link>
                  </td>
                  <td>{companyName(customer.company)}</td>
                  <td>{buildingName(customer.building)}</td>
                  <td>{customer.contact_email || "—"}</td>
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
                    <Link
                      className="btn btn-ghost btn-sm"
                      to={`/admin/customers/${customer.id}`}
                    >
                      {t("admin.edit")}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

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
        </div>

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
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                {t("previous")}
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={loading || !next}
                onClick={() => setPage((current) => current + 1)}
              >
                {t("next")}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
