import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { MailPlus, RefreshCw } from "lucide-react";
import { getApiError } from "../../api/client";
import { listUsers } from "../../api/admin";
import type { AdminListParams } from "../../api/admin";
import type { Role, UserAdmin } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { useSavedBanner } from "../../hooks/useSavedBanner";

type ActiveFilter = "true" | "false" | "all";

const DEBOUNCE_MS = 300;

const ROLE_LABEL: Record<Role, string> = {
  SUPER_ADMIN: "Super admin",
  COMPANY_ADMIN: "Company admin",
  BUILDING_MANAGER: "Building manager",
  CUSTOMER_USER: "Customer user",
};

const ALL_ROLES: Role[] = [
  "SUPER_ADMIN",
  "COMPANY_ADMIN",
  "BUILDING_MANAGER",
  "CUSTOMER_USER",
];

export function UsersAdminPage() {
  const { me } = useAuth();
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
    saved: "User saved.",
    deactivated: "User deactivated.",
    reactivated: "User reactivated.",
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
            Admin
          </div>
          <h2 className="page-title">Users</h2>
          <p className="page-sub">
            {loading ? "Loading users…" : `${count} ${count === 1 ? "user" : "users"}`}
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
          <Link className="btn btn-primary btn-sm" to="/admin/invitations">
            <MailPlus size={14} strokeWidth={2.5} />
            Invite user
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
            <span className="filter-label">Search</span>
            <input
              className="filter-control"
              type="search"
              placeholder="Email or name…"
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
          <div className="filter-field" style={{ flexBasis: "100%" }}>
            <span className="filter-label">Roles</span>
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
                  >
                    {ROLE_LABEL[role]}
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
                onClick={() => {
                  setSearchInput("");
                  setActiveFilter("true");
                  setRoleFilter([]);
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
                <th>Email</th>
                <th>Full name</th>
                <th>Role</th>
                <th>Language</th>
                <th>Status</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {visibleUsers.map((user) => (
                <tr key={user.id}>
                  <td className="td-subject">
                    <Link to={`/admin/users/${user.id}`}>{user.email}</Link>
                  </td>
                  <td>{user.full_name || "—"}</td>
                  <td>{ROLE_LABEL[user.role] ?? user.role}</td>
                  <td>{user.language}</td>
                  <td>
                    <span
                      className={`cell-tag cell-tag-${user.is_active ? "open" : "closed"}`}
                    >
                      <i />
                      {user.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td>
                    <Link className="btn btn-ghost btn-sm" to={`/admin/users/${user.id}`}>
                      Edit
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {!loading && visibleUsers.length === 0 && (
            <div className="empty-state">
              <div className="empty-icon">＋</div>
              <div className="empty-title">
                {hasActiveFilters ? "No users match your filters" : "No users yet"}
              </div>
              <p className="empty-sub">
                {hasActiveFilters
                  ? "Try clearing filters or switching the status tab."
                  : "Invite the first user to get started."}
              </p>
              {!hasActiveFilters && (
                <Link className="btn btn-primary btn-sm" to="/admin/invitations">
                  Invite user
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
