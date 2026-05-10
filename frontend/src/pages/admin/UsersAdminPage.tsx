import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { MailPlus, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getApiError } from "../../api/client";
import { listUsers } from "../../api/admin";
import type { AdminListParams } from "../../api/admin";
import type { Role, UserAdmin } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { useSavedBanner } from "../../hooks/useSavedBanner";

type ActiveFilter = "true" | "false" | "all";

const DEBOUNCE_MS = 300;

const ROLE_KEYS: Record<Role, string> = {
  SUPER_ADMIN: "common:roles.super_admin",
  COMPANY_ADMIN: "common:roles.company_admin",
  BUILDING_MANAGER: "common:roles.building_manager",
  CUSTOMER_USER: "common:roles.customer_user",
};

const ALL_ROLES: Role[] = [
  "SUPER_ADMIN",
  "COMPANY_ADMIN",
  "BUILDING_MANAGER",
  "CUSTOMER_USER",
];

export function UsersAdminPage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation("common");
  const isSuperAdmin = me?.role === "SUPER_ADMIN";

  const [users, setUsers] = useState<UserAdmin[]>([]);
  const [count, setCount] = useState(0);
  const [next, setNext] = useState<string | null>(null);
  const [previous, setPrevious] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Search is handled client-side because /api/users/ does not yet support
  // ?search=. We still send it on the query string in case the backend gains
  // support later; today it is harmlessly ignored. Documented in api/admin.ts.
  const [searchInput, setSearchInput] = useState("");
  const [searchActive, setSearchActive] = useState("");
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("true");
  const [roleFilter, setRoleFilter] = useState<Role[]>([]);

  const [savedBanner] = useSavedBanner({
    saved: t("users.banner_saved"),
    deactivated: t("users.banner_deactivated"),
    reactivated: t("users.banner_reactivated"),
  });

  // COMPANY_ADMIN can only meaningfully filter by the three roles they manage.
  const availableRoles: Role[] = useMemo(
    () => (isSuperAdmin ? ALL_ROLES : ALL_ROLES.filter((r) => r !== "SUPER_ADMIN")),
    [isSuperAdmin],
  );

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setSearchActive(searchInput.trim());
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [searchInput]);

  const queryParams = useMemo<AdminListParams>(() => {
    const params: AdminListParams = { page };
    if (activeFilter !== "all") params.is_active = activeFilter;
    if (roleFilter.length > 0) params.role = roleFilter.join(",");
    return params;
  }, [page, activeFilter, roleFilter]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await listUsers(queryParams);
      setUsers(response.results);
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

  // Client-side search filter on the current page (see note above).
  const visibleUsers = useMemo(() => {
    if (!searchActive) return users;
    const needle = searchActive.toLowerCase();
    return users.filter(
      (u) =>
        u.email.toLowerCase().includes(needle) ||
        (u.full_name ?? "").toLowerCase().includes(needle),
    );
  }, [users, searchActive]);

  const hasActiveFilters = Boolean(
    searchActive || activeFilter !== "true" || roleFilter.length > 0,
  );

  function toggleRole(role: Role) {
    setRoleFilter((current) =>
      current.includes(role) ? current.filter((r) => r !== role) : [...current, role],
    );
    setPage(1);
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="eyebrow" style={{ marginBottom: 8 }}>
            {t("nav.admin_group")}
          </div>
          <h2 className="page-title">{t("nav.users")}</h2>
          <p className="page-sub">
            {loading
              ? t("users.loading")
              : t("users.count", { count })}
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
          <Link className="btn btn-primary btn-sm" to="/admin/invitations">
            <MailPlus size={14} strokeWidth={2.5} />
            {t("users.invite_user")}
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
          }}
        >
          <div className="filter-field search">
            <span className="filter-label">{t("search")}</span>
            <input
              className="filter-control"
              type="search"
              placeholder={t("users.search_placeholder")}
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
          <div className="filter-field" style={{ flexBasis: "100%" }}>
            <span className="filter-label">{t("users.roles_label")}</span>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {availableRoles.map((role) => {
                const active = roleFilter.includes(role);
                return (
                  <button
                    key={role}
                    type="button"
                    className={`btn btn-sm ${active ? "btn-primary" : "btn-secondary"}`}
                    onClick={() => toggleRole(role)}
                    aria-pressed={active}
                    data-role={role}
                  >
                    {t(ROLE_KEYS[role])}
                  </button>
                );
              })}
            </div>
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
                  setRoleFilter([]);
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
                <th>{t("users.col_email")}</th>
                <th>{t("users.col_full_name")}</th>
                <th>{t("users.col_role")}</th>
                <th>{t("users.col_language")}</th>
                <th>{t("status")}</th>
                <th aria-label={t("admin.col_actions")} />
              </tr>
            </thead>
            <tbody>
              {visibleUsers.map((user) => {
                const editPath = `/admin/users/${user.id}`;
                const openEdit = () => navigate(editPath);
                return (
                  <tr
                    key={user.id}
                    className="admin-row-clickable"
                    role="link"
                    tabIndex={0}
                    aria-label={t("admin.edit") + ": " + user.email}
                    onClick={openEdit}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openEdit();
                      }
                    }}
                  >
                    <td className="td-subject">
                      <Link to={editPath}>{user.email}</Link>
                    </td>
                    <td>{user.full_name || "—"}</td>
                    <td data-testid="user-row-role" data-role={user.role}>
                      {t(ROLE_KEYS[user.role] ?? "common:roles.fallback")}
                    </td>
                    <td>{user.language}</td>
                    <td>
                      <span
                        className={`cell-tag cell-tag-${user.is_active ? "open" : "closed"}`}
                      >
                        <i />
                        {user.is_active
                          ? t("admin.status_active")
                          : t("admin.status_inactive")}
                      </span>
                    </td>
                    <td>
                      <Link className="btn btn-ghost btn-sm" to={editPath}>
                        {t("admin.edit")}
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {!loading && visibleUsers.length === 0 && (
            <div className="empty-state">
              <div className="empty-icon">＋</div>
              <div className="empty-title">
                {hasActiveFilters
                  ? t("users.empty_filtered_title")
                  : t("users.empty_initial_title")}
              </div>
              <p className="empty-sub">
                {hasActiveFilters
                  ? t("admin.empty_filtered_desc")
                  : t("users.empty_initial_desc")}
              </p>
              {!hasActiveFilters && (
                <Link className="btn btn-primary btn-sm" to="/admin/invitations">
                  {t("users.invite_user")}
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
