import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { getApiError } from "../../api/client";
import { listBuildings, listCompanies } from "../../api/admin";
import type { AdminListParams } from "../../api/admin";
import type { BuildingAdmin, CompanyAdmin } from "../../api/types";

type ActiveFilter = "true" | "false" | "all";

const DEBOUNCE_MS = 300;

function formatDate(value: string): string {
  try {
    return new Date(value).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
    });
  } catch {
    return value;
  }
}

export function BuildingsAdminPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [buildings, setBuildings] = useState<BuildingAdmin[]>([]);
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

  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companiesLoaded, setCompaniesLoaded] = useState(false);

  const [savedBanner, setSavedBanner] = useState("");

  useEffect(() => {
    const flags: Array<[string, string]> = [
      ["saved", "Building saved."],
      ["deactivated", "Building deactivated."],
      ["reactivated", "Building reactivated."],
    ];
    let banner = "";
    let dirty = false;
    for (const [key, message] of flags) {
      if (searchParams.get(key) === "ok") {
        banner = message;
        dirty = true;
      }
    }
    if (dirty) {
      setSavedBanner(banner);
      const next = new URLSearchParams(searchParams);
      for (const [key] of flags) next.delete(key);
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  // Load companies once for the filter dropdown. The list is paginated server
  // side; pull a generous page so most installs fit in one request.
  useEffect(() => {
    let cancelled = false;
    listCompanies({ is_active: "true", page_size: 200 })
      .then((response) => {
        if (cancelled) return;
        setCompanies(response.results);
        // Auto-select for COMPANY_ADMIN with exactly one company in scope.
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
    return params;
  }, [page, searchActive, activeFilter, companyFilter]);

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

  const companyName = useCallback(
    (id: number) => companies.find((c) => c.id === id)?.name ?? `Company #${id}`,
    [companies],
  );

  const hasActiveFilters = Boolean(
    searchActive || activeFilter !== "true" || (companyFilter !== "" && !companyDropdownDisabled),
  );

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            Admin
          </div>
          <h2 className="page-title">Buildings</h2>
          <p className="page-sub">
            {loading ? "Loading buildings…" : `${count} ${count === 1 ? "building" : "buildings"}`}
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
            Refresh
          </button>
          <Link className="btn btn-primary btn-sm" to="/admin/buildings/new">
            <Plus size={14} strokeWidth={2.5} />
            Create new
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
            <span className="filter-label">Search</span>
            <input
              className="filter-control"
              type="search"
              placeholder="Name, address, city…"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </div>
          <div className="filter-field">
            <span className="filter-label">Status</span>
            <select
              className="filter-control"
              value={activeFilter}
              onChange={(event) => {
                setActiveFilter(event.target.value as ActiveFilter);
                setPage(1);
              }}
            >
              <option value="true">Active</option>
              <option value="false">Inactive</option>
              <option value="all">All</option>
            </select>
          </div>
          <div className="filter-field">
            <span className="filter-label">Company</span>
            <select
              className="filter-control"
              value={companyFilter === "" ? "" : String(companyFilter)}
              onChange={(event) => {
                const v = event.target.value;
                setCompanyFilter(v === "" ? "" : Number(v));
                setPage(1);
              }}
              disabled={companyDropdownDisabled}
            >
              <option value="">All companies</option>
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
                onClick={() => {
                  setSearchInput("");
                  setActiveFilter("true");
                  if (!companyDropdownDisabled) setCompanyFilter("");
                  setPage(1);
                }}
              >
                Clear
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
                <th>Name</th>
                <th>Company</th>
                <th>Address</th>
                <th>Created</th>
                <th>Status</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {buildings.map((building) => (
                <tr key={building.id}>
                  <td className="td-subject">
                    <Link to={`/admin/buildings/${building.id}`}>{building.name}</Link>
                  </td>
                  <td>{companyName(building.company)}</td>
                  <td>
                    {[building.city, building.postal_code].filter(Boolean).join(" ")}
                  </td>
                  <td className="td-date">{formatDate(building.created_at)}</td>
                  <td>
                    <span
                      className={`cell-tag cell-tag-${building.is_active ? "open" : "closed"}`}
                    >
                      <i />
                      {building.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td>
                    <Link
                      className="btn btn-ghost btn-sm"
                      to={`/admin/buildings/${building.id}`}
                    >
                      Edit
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {!loading && buildings.length === 0 && (
            <div className="empty-state">
              <div className="empty-icon">＋</div>
              <div className="empty-title">
                {hasActiveFilters ? "No buildings match your filters" : "No buildings yet"}
              </div>
              <p className="empty-sub">
                {hasActiveFilters
                  ? "Try clearing filters or switching the status tab."
                  : "Create the first building to get started."}
              </p>
              {!hasActiveFilters && (
                <Link className="btn btn-primary btn-sm" to="/admin/buildings/new">
                  Create building
                </Link>
              )}
            </div>
          )}
        </div>

        {(previous || next) && (
          <div className="pagination">
            <span className="pagination-info">
              Page {page} · {count} total
            </span>
            <div className="pagination-controls">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={loading || !previous || page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                Previous
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                disabled={loading || !next}
                onClick={() => setPage((current) => current + 1)}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
