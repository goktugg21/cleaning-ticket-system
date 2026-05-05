import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { getApiError } from "../../api/client";
import { listCompanies } from "../../api/admin";
import type { AdminListParams } from "../../api/admin";
import type { CompanyAdmin } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";

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

export function CompaniesAdminPage() {
  const { me } = useAuth();
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const [searchParams, setSearchParams] = useSearchParams();
  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [count, setCount] = useState(0);
  const [next, setNext] = useState<string | null>(null);
  const [previous, setPrevious] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [searchInput, setSearchInput] = useState("");
  const [searchActive, setSearchActive] = useState("");
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("true");

  const [savedBanner, setSavedBanner] = useState("");

  // Surface success banners from the form pages and clean the URL so a
  // refresh does not keep showing them.
  useEffect(() => {
    const flags: Array<[string, string]> = [
      ["saved", "Company saved."],
      ["deactivated", "Company deactivated."],
      ["reactivated", "Company reactivated."],
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

  // Debounce the search input.
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
    return params;
  }, [page, searchActive, activeFilter]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await listCompanies(queryParams);
      setCompanies(response.results);
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

  const hasActiveFilters = Boolean(searchActive || activeFilter !== "true");

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            Admin
          </div>
          <h2 className="page-title">Companies</h2>
          <p className="page-sub">
            {loading
              ? "Loading companies…"
              : `${count} ${count === 1 ? "company" : "companies"}`}
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
          {isSuperAdmin && (
            <Link className="btn btn-primary btn-sm" to="/admin/companies/new">
              <Plus size={14} strokeWidth={2.5} />
              Create new
            </Link>
          )}
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
              placeholder="Name or slug…"
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
          <div className="filter-actions">
            {hasActiveFilters && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setSearchInput("");
                  setActiveFilter("true");
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
                <th>Slug</th>
                <th>Default language</th>
                <th>Created</th>
                <th>Status</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {companies.map((company) => (
                <tr key={company.id}>
                  <td className="td-subject">
                    <Link to={`/admin/companies/${company.id}`}>{company.name}</Link>
                  </td>
                  <td>{company.slug}</td>
                  <td>{company.default_language}</td>
                  <td className="td-date">{formatDate(company.created_at)}</td>
                  <td>
                    <span
                      className={`cell-tag cell-tag-${company.is_active ? "open" : "closed"}`}
                    >
                      <i />
                      {company.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td>
                    <Link
                      className="btn btn-ghost btn-sm"
                      to={`/admin/companies/${company.id}`}
                    >
                      Edit
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {!loading && companies.length === 0 && (
            <div className="empty-state">
              <div className="empty-icon">＋</div>
              <div className="empty-title">
                {hasActiveFilters ? "No companies match your filters" : "No companies yet"}
              </div>
              <p className="empty-sub">
                {hasActiveFilters
                  ? "Try clearing filters or switching the status tab."
                  : isSuperAdmin
                    ? "Create the first company to get started."
                    : "Ask a super admin to create one."}
              </p>
              {isSuperAdmin && !hasActiveFilters && (
                <Link className="btn btn-primary btn-sm" to="/admin/companies/new">
                  Create company
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
