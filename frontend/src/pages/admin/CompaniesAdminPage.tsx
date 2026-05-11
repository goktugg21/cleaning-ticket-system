import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getApiError } from "../../api/client";
import { listCompanies } from "../../api/admin";
import type { AdminListParams } from "../../api/admin";
import type { CompanyAdmin } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { useSavedBanner } from "../../hooks/useSavedBanner";

type ActiveFilter = "true" | "false" | "all";

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

export function CompaniesAdminPage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation("common");
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

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

  const [savedBanner] = useSavedBanner({
    saved: t("companies.banner_saved"),
    deactivated: t("companies.banner_deactivated"),
    reactivated: t("companies.banner_reactivated"),
  });

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

  const dateLocale = i18n.language === "nl" ? "nl-NL" : "en-US";

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("nav.admin_group")}
          </div>
          <h2 className="page-title">{t("nav.companies")}</h2>
          <p className="page-sub">
            {loading
              ? t("companies.loading")
              : t("companies.count", { count })}
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
          {isSuperAdmin && (
            <Link className="btn btn-primary btn-sm" to="/admin/companies/new">
              <Plus size={14} strokeWidth={2.5} />
              {t("admin.create_new")}
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
            <span className="filter-label">{t("search")}</span>
            <input
              className="filter-control"
              type="search"
              placeholder={t("companies.search_placeholder")}
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
          <div className="filter-actions">
            {hasActiveFilters && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                data-testid="filters-clear"
                onClick={() => {
                  setSearchInput("");
                  setActiveFilter("true");
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

        <div className="table-wrap admin-list-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("admin.col_name")}</th>
                <th>{t("companies.col_slug")}</th>
                <th>{t("companies.col_default_language")}</th>
                <th>{t("created")}</th>
                <th>{t("status")}</th>
                <th aria-label={t("admin.col_actions")} />
              </tr>
            </thead>
            <tbody>
              {companies.map((company) => {
                const editPath = `/admin/companies/${company.id}`;
                const openEdit = () => navigate(editPath);
                return (
                  <tr
                    key={company.id}
                    className="admin-row-clickable"
                    role="link"
                    tabIndex={0}
                    aria-label={t("admin.edit") + ": " + company.name}
                    onClick={openEdit}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openEdit();
                      }
                    }}
                  >
                    <td className="td-subject">
                      <Link to={editPath}>{company.name}</Link>
                    </td>
                    <td>{company.slug}</td>
                    <td>{company.default_language}</td>
                    <td className="td-date">{formatDate(company.created_at, dateLocale)}</td>
                    <td>
                      <span
                        className={`cell-tag cell-tag-${company.is_active ? "open" : "closed"}`}
                      >
                        <i />
                        {company.is_active
                          ? t("admin.status_active")
                          : t("admin.status_inactive")}
                      </span>
                    </td>
                    <td>
                      <Link
                        className="btn btn-ghost btn-sm"
                        to={editPath}
                      >
                        {t("admin.edit")}
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Sprint 22 final polish: phone-width parallel card list.
            Hidden via CSS @media (min-width: 601px). The desktop
            table above stays in the DOM at all widths so Playwright
            tablet/desktop assertions still resolve. */}
        <ul
          className="admin-card-list"
          data-testid="admin-card-list"
          aria-label={t("nav.companies")}
        >
          {companies.map((company) => {
            const editPath = `/admin/companies/${company.id}`;
            return (
              <li key={company.id} className="admin-card">
                <Link
                  to={editPath}
                  className="admin-card-link"
                  aria-label={`${t("admin.edit")}: ${company.name}`}
                >
                  <div className="admin-card-head">
                    <span className="admin-card-title">{company.name}</span>
                    <span
                      className={`cell-tag cell-tag-${company.is_active ? "open" : "closed"}`}
                    >
                      <i />
                      {company.is_active
                        ? t("admin.status_active")
                        : t("admin.status_inactive")}
                    </span>
                  </div>
                  <dl className="admin-card-meta">
                    <div className="admin-card-meta-row">
                      <dt>{t("companies.col_slug")}</dt>
                      <dd>{company.slug}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("companies.col_default_language")}</dt>
                      <dd>{company.default_language}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("created")}</dt>
                      <dd>{formatDate(company.created_at, dateLocale)}</dd>
                    </div>
                  </dl>
                  <div className="admin-card-actions">
                    <span className="btn btn-ghost btn-sm">
                      {t("admin.edit")}
                    </span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>

        {!loading && companies.length === 0 && (
          <div className="empty-state">
            <div className="empty-icon">＋</div>
            <div className="empty-title">
              {hasActiveFilters
                ? t("companies.empty_filtered_title")
                : t("companies.empty_initial_title")}
            </div>
            <p className="empty-sub">
              {hasActiveFilters
                ? t("admin.empty_filtered_desc")
                : isSuperAdmin
                  ? t("companies.empty_initial_desc_admin")
                  : t("companies.empty_initial_desc_other")}
            </p>
            {isSuperAdmin && !hasActiveFilters && (
              <Link className="btn btn-primary btn-sm" to="/admin/companies/new">
                {t("companies.create")}
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
