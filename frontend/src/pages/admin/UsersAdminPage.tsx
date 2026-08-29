import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { MailPlus, RefreshCw, Users } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getApiError } from "../../api/client";
import {
  listAllCompanies,
  listAllCustomers,
  listUsers,
} from "../../api/admin";
import type { AdminListParams } from "../../api/admin";
import type {
  CompanyAdmin,
  CustomerAccessRole,
  CustomerAdmin,
  Role,
  UserAdmin,
  UserCompanies,
  UserScopeSummary,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { useSavedBanner } from "../../hooks/useSavedBanner";
import { AccessRoleBadge } from "../../components/AccessRoleBadge";
import { ClickableRow } from "../../components/ClickableRow";
import { EmptyState } from "../../components/EmptyState";
import { RoleBadge } from "../../components/RoleBadge";
import { StatusBadge } from "../../components/StatusBadge";
import {
  accessRoleLabelKey,
  isProviderRole,
  roleLabelKey,
} from "../../lib/enumLabels";

type ActiveFilter = "true" | "false" | "all";

const DEBOUNCE_MS = 300;

// Sprint 28 Batch 15.5 — per-row scope summary chip.
//
// The backend (accounts/serializers_users.py::UserAdminListSerializer)
// emits `scope_summary: { label, count }`. SUPER_ADMIN returns the
// sentinel `{ label: "all", count: -1 }` — we render it as the
// localised "All companies" label without a numeric prefix. Every
// other role returns a real positive count keyed by the dominant
// scope axis for that role.
function ScopeChip({ summary }: { summary: UserScopeSummary }) {
  const { t } = useTranslation("common");
  if (summary.count === -1) {
    return <span className="muted small">{t("users.scope_all")}</span>;
  }
  // Sprint 29 Batch 29.1 — i18next pluralization replaces the bare
  // "1 customers" rendering. The _one / _other suffix is chosen by
  // i18next based on `count`. The chip stays in a single text node;
  // CSS gives the chip its own font-weight rather than wrapping the
  // numeric prefix in <strong>.
  return (
    <span className="users-scope-chip" data-testid="users-scope-chip">
      {t(`users.scope_${summary.label}`, { count: summary.count })}
    </span>
  );
}

// Sprint 187B §1a — WHICH companies, bounded.
//
// A user can belong to many companies, so this is a list, and CLAUDE.md
// forbids rendering an unbounded server collection — at cell level that
// means a user in eight companies must not print eight names into a
// table cell. Two names, then "+N more", with the full set in the
// title attribute. `all` is the SUPER_ADMIN sentinel and keeps rendering
// as "All companies", exactly as the scope chip beside it already does.
const COMPANY_NAMES_SHOWN = 2;

function CompanyCell({ companies }: { companies: UserCompanies }) {
  const { t } = useTranslation("common");
  if (companies.all) {
    return <span className="muted small">{t("users.scope_all")}</span>;
  }
  const names = companies.names;
  if (names.length === 0) {
    // An em dash, never a blank cell: a blank one reads as a rendering
    // bug rather than "belongs to no company" (Sprint 154 §K).
    return <span className="muted small">—</span>;
  }
  const shown = names.slice(0, COMPANY_NAMES_SHOWN);
  const hidden = names.length - shown.length;
  return (
    <span data-testid="user-row-companies" title={names.join(", ")}>
      {shown.join(", ")}
      {hidden > 0 && (
        <span className="muted small">
          {" "}
          {t("users.companies_more", { count: hidden })}
        </span>
      )}
    </span>
  );
}

// Sprint 2c — the three customer access roles for the read-only filter
// toolbar (mirrors AccessRole on the backend). Labels reuse access_role.*.
const ACCESS_ROLE_OPTIONS: CustomerAccessRole[] = [
  "CUSTOMER_USER",
  "CUSTOMER_LOCATION_MANAGER",
  "CUSTOMER_COMPANY_ADMIN",
];

// Sprint 23B — STAFF is a valid filter option so reviewers can find
// existing STAFF users. The list page only reads; the create path
// (UserFormPage / invitations) deliberately omits STAFF — see the
// comment in UserFormPage. CUSTOMER_USER stays the default for
// scope-isolated listings.
const ALL_ROLES: Role[] = [
  "SUPER_ADMIN",
  "COMPANY_ADMIN",
  "BUILDING_MANAGER",
  "STAFF",
  "CUSTOMER_USER",
];

/** FE-6 — `embedded`: rendered as a tab of the Mensen surface, which
 *  owns the title; the page keeps its count line and its actions. */
export function UsersAdminPage({ embedded = false }: { embedded?: boolean } = {}) {
  const { me } = useAuth();
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
  // Single-select: the access-role column shows ONE effective role, so the
  // filter is a single value (null = no access-role filter).
  const [accessRoleFilter, setAccessRoleFilter] =
    useState<CustomerAccessRole | null>(null);

  // Sprint 187B §1c — the company filter, copying the established
  // BuildingsAdminPage pattern rather than inventing one: loaded once,
  // auto-selected when exactly one company comes back (a single-company
  // admin), and disabled in that case because there is nothing to choose.
  const [companyFilter, setCompanyFilter] = useState<number | "">("");
  // Sprint 188 — "who at this customer can log in?", the question the
  // company filter cannot answer.
  const [customerFilter, setCustomerFilter] = useState<number | "">("");
  const [customers, setCustomers] = useState<CustomerAdmin[]>([]);
  const [companies, setCompanies] = useState<CompanyAdmin[]>([]);
  const [companiesLoaded, setCompaniesLoaded] = useState(false);

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

  // Sprint 158 §3 — split by SIDE, not by concept.
  //
  // The two rows were labelled ROLES and ACCESS ROLES, and "Customer
  // user" appeared in BOTH — once as the account role and once as the
  // access role — which reads as a duplicate rather than as two
  // different things. The owner's grouping is better: everything on the
  // provider's side in one group, everything on the customer's side in
  // the other, and the customer-side account role sits with the access
  // roles it belongs with.
  //
  // Both groups stay fully visible. Sprint 157 §7 and `## NEXT` item 19
  // rule out collapsing them.
  const providerRoles = useMemo(
    () => availableRoles.filter((role) => role !== "CUSTOMER_USER"),
    [availableRoles],
  );
  const customerRoles = useMemo(
    () => availableRoles.filter((role) => role === "CUSTOMER_USER"),
    [availableRoles],
  );

  // Loaded exhaustively (listAllCompanies) so a tenant with more than one
  // page of companies gets a complete dropdown rather than a silently
  // truncated one — the Sprint 135 fix, kept.
  useEffect(() => {
    let cancelled = false;
    listAllCompanies({ is_active: "true" })
      .then((response) => {
        if (cancelled) return;
        setCompanies(response);
        // Sprint 188 — NO auto-select here, unlike Buildings/Customers.
        // Every building has a company; a SUPER_ADMIN has none, and the
        // filter deliberately drops rows holding no membership in the
        // chosen company. Auto-selecting on a one-company install (and
        // then disabling the control, as this page also used to) pinned
        // the filter on with no way back, so every platform admin
        // disappeared from the Users list permanently.
      })
      .finally(() => {
        if (!cancelled) setCompaniesLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Sprint 188 — never disabled: "All companies" must stay reachable,
  // because it is the only value that shows a SUPER_ADMIN. `companiesLoaded`
  // is still used to keep the control out of the way until it can be filled.
  const companyDropdownDisabled = !companiesLoaded;

  // Sprint 188 — the customer picker. Narrowed by the chosen company
  // when there is one, so the two filters agree instead of offering a
  // customer that the company filter has already excluded. Exhaustive
  // paging (`listAllCustomers`), not a first page: the Sprint 135 rule
  // is to fix the caller that has no pagination UI, never the endpoint.
  useEffect(() => {
    let cancelled = false;
    listAllCustomers(
      companyFilter === "" ? {} : { company: companyFilter },
    ).then((rows) => {
      if (!cancelled) setCustomers(rows);
    });
    return () => {
      cancelled = true;
    };
  }, [companyFilter]);

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
    if (accessRoleFilter) params.access_role = accessRoleFilter;
    if (companyFilter !== "") params.company = companyFilter;
    if (customerFilter !== "") params.customer = customerFilter;
    return params;
  }, [
    page,
    activeFilter,
    roleFilter,
    accessRoleFilter,
    companyFilter,
    customerFilter,
  ]);

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

  // Sprint 28 Batch 15.3 — split the visible set by side so the
  // table can render two group headers (Provider users / Customer
  // users) without changing the filter or pagination contract.
  const groupedUsers = useMemo(() => {
    const provider: UserAdmin[] = [];
    const customer: UserAdmin[] = [];
    for (const u of visibleUsers) {
      if (isProviderRole(u.role)) provider.push(u);
      else customer.push(u);
    }
    return { provider, customer };
  }, [visibleUsers]);

  const hasActiveFilters = Boolean(
    searchActive ||
      activeFilter !== "true" ||
      roleFilter.length > 0 ||
      accessRoleFilter ||
      // Sprint 188 — both narrowing pickers count, so "Clear" clears them.
      companyFilter !== "" ||
      customerFilter !== "",
  );

  function toggleRole(role: Role) {
    setRoleFilter((current) =>
      current.includes(role) ? current.filter((r) => r !== role) : [...current, role],
    );
    setPage(1);
  }

  // Single-select: clicking the active chip again clears the filter.
  function selectAccessRole(role: CustomerAccessRole) {
    setAccessRoleFilter((current) => (current === role ? null : role));
    setPage(1);
  }

  // Sprint 28 Batch 15.3 — extracted so the two-group table body can
  // share the same row rendering for the provider and customer
  // partitions.
  // UI-polish — the whole row is the click target -> the user detail
  // page (which holds the Edit affordance). The per-row "Edit" text link
  // is gone; the row never links to a 403/404 because the Users list is
  // already scoped to users the viewer can open.
  function renderUserRow(user: UserAdmin) {
    const detailPath = `/admin/users/${user.id}`;
    return (
      <ClickableRow
        key={user.id}
        to={detailPath}
        dataRole={user.role}
        ariaLabel={t("admin.view") + ": " + user.email}
      >
        <td className="td-subject">
          <Link to={detailPath}>{user.email}</Link>
        </td>
        <td>{user.full_name || "—"}</td>
        {/* Sprint 154 §K — empty renders an em dash, never a blank cell:
            a blank one reads as a rendering bug rather than "not set". */}
        <td data-testid="user-row-phone">
          {user.phone ? <a href={`tel:${user.phone}`}>{user.phone}</a> : "—"}
        </td>
        <td data-testid="user-row-role" data-role={user.role}>
          <RoleBadge role={user.role} compact />
        </td>
        <td data-testid="user-row-access-role">
          <AccessRoleBadge accessRole={user.customer_access_role} />
        </td>
        <td>
          <CompanyCell companies={user.companies} />
        </td>
        <td>{user.language}</td>
        <td data-testid="user-row-scope">
          <ScopeChip summary={user.scope_summary} />
        </td>
        <td>
          <StatusBadge
            variant="cell"
            status={{
              kind: "generic",
              tone: user.is_active ? "open" : "neutral",
              label: user.is_active
                ? t("admin.status_active")
                : t("admin.status_inactive"),
            }}
          />
        </td>
      </ClickableRow>
    );
  }

  return (
    <div>
      <div className={embedded ? "page-header page-header-embedded" : "page-header"}>
        <div>
          {!embedded && (
            <>
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                {t("nav.admin_group")}
              </div>
              <h2 className="page-title">{t("nav.users")}</h2>
            </>
          )}
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
          <Link className="btn btn-primary btn-sm" to="/admin/people/invitations">
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
          <div className="filter-field">
            <span className="filter-label">{t("company")}</span>
            {/* Capped to match Search / Status instead of stretching to
                fill the filter-bar's 1fr track — same as Buildings. */}
            <select
              className="filter-control"
              style={{ maxWidth: 220 }}
              data-testid="users-filter-company"
              value={companyFilter === "" ? "" : String(companyFilter)}
              onChange={(event) => {
                const value = event.target.value;
                setCompanyFilter(value === "" ? "" : Number(value));
                setPage(1);
              }}
              disabled={companyDropdownDisabled}
            >
              <option value="">{t("admin.all_companies")}</option>
              {companies.map((company) => (
                <option key={company.id} value={company.id}>
                  {company.name}
                </option>
              ))}
            </select>
          </div>
          <div className="filter-field">
            <span className="filter-label">{t("customer")}</span>
            <select
              className="filter-control"
              style={{ maxWidth: 220 }}
              data-testid="users-filter-customer"
              value={customerFilter === "" ? "" : String(customerFilter)}
              onChange={(event) => {
                const value = event.target.value;
                setCustomerFilter(value === "" ? "" : Number(value));
                setPage(1);
              }}
            >
              <option value="">{t("users.all_customers")}</option>
              {customers.map((customer) => (
                <option key={customer.id} value={customer.id}>
                  {customer.name}
                </option>
              ))}
            </select>
          </div>
          {/* Sprint 157 §7 — the two chip groups share ONE full-width
              row, in equal columns.

              Sprint 156 gave them `flex: 1 1 340px` each, so they grew
              into whatever was left on the line and came out ragged:
              measured 486 vs 916px at 1280 and 646 vs 1076 at 1440,
              with the ROLES chips wrapping to two lines inside the
              narrower one. Two groups of unequal width, each wrapping
              differently, is what "reads as two ragged groups" means.

              A wrapper that takes the whole row and lays the two out on
              an equal grid fixes the raggedness at the cause. They stay
              fully VISIBLE — Sprint 156 proposed collapsing them behind
              a disclosure and §7 explicitly rules that out, as does
              `## NEXT` item 19: a collapsed group can hide an ACTIVE
              filter. */}
          <div className="filter-chip-groups">
                    <div className="filter-field">
            <span className="filter-label">{t("users.provider_roles_label")}</span>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {providerRoles.map((role) => {
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
                    {t(roleLabelKey(role))}
                  </button>
                );
              })}
            </div>
          </div>
                    <div className="filter-field">
            <span className="filter-label">
              {t("users.customer_roles_label")}
            </span>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {/* The customer-side ACCOUNT role first, then the three
                  access roles. Same group, because they are the same
                  side — which is the whole point of the regrouping.

                  Sprint 161 §7 — this chip is deliberately NOT labelled
                  `roles.customer_user`. That string is "Klantgebruiker"
                  and so is `access_role.customer_user`, so the group
                  showed "Customer user" twice: once for the ACCOUNT role
                  and once for the ACCESS role. They filter different
                  things — `?role=` matches every customer-side account,
                  `?access_role=` matches one access level — so neither
                  is redundant and dropping one would remove a filter.
                  What was wrong was only the label.

                  "All customer users" is also the accurate name: this
                  chip is the whole customer side, of which the three
                  access chips are a partition, and it is the only way to
                  see all of them at once because the access filter is
                  single-select. `roles.customer_user` is untouched -
                  RoleBadge uses it everywhere else and it is right
                  there. */}
              {customerRoles.map((role) => {
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
                    {t("users.customer_role_all")}
                  </button>
                );
              })}
              {ACCESS_ROLE_OPTIONS.map((role) => {
                const active = accessRoleFilter === role;
                return (
                  <button
                    key={role}
                    type="button"
                    className={`btn btn-sm ${active ? "btn-primary" : "btn-secondary"}`}
                    onClick={() => selectAccessRole(role)}
                    aria-pressed={active}
                    data-access-role={role}
                  >
                    {t(accessRoleLabelKey(role))}
                  </button>
                );
              })}
            </div>
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
                  setAccessRoleFilter(null);
                  setCompanyFilter("");
                  setCustomerFilter("");
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
                <th>{t("users.col_email")}</th>
                <th>{t("users.col_full_name")}</th>
                <th>{t("users.col_phone")}</th>
                <th>{t("users.col_role")}</th>
                <th>{t("users.col_access_role")}</th>
                <th>{t("company")}</th>
                <th>{t("users.col_language")}</th>
                <th>{t("users.col_scope")}</th>
                <th>{t("status")}</th>
              </tr>
            </thead>
            <tbody>
              {groupedUsers.provider.length > 0 && (
                <>
                  <tr
                    className="users-group-header"
                    data-testid="users-group-provider"
                  >
                    <td colSpan={9}>
                      <span className="users-group-header-label">
                        {t("users.group_provider")}
                      </span>
                      <span className="users-group-header-count">
                        {groupedUsers.provider.length}
                      </span>
                    </td>
                  </tr>
                  {groupedUsers.provider.map(renderUserRow)}
                </>
              )}
              {groupedUsers.customer.length > 0 && (
                <>
                  <tr
                    className="users-group-header"
                    data-testid="users-group-customer"
                  >
                    <td colSpan={9}>
                      <span className="users-group-header-label">
                        {t("users.group_customer")}
                      </span>
                      <span className="users-group-header-count">
                        {groupedUsers.customer.length}
                      </span>
                    </td>
                  </tr>
                  {groupedUsers.customer.map(renderUserRow)}
                </>
              )}
            </tbody>
          </table>
        </div>

        {/* Sprint 22 final polish: phone-width parallel card list. */}
        <ul
          className="admin-card-list"
          data-testid="admin-card-list"
          aria-label={t("nav.users")}
        >
          {visibleUsers.map((user) => {
            const detailPath = `/admin/users/${user.id}`;
            return (
              <li key={user.id} className="admin-card">
                <Link
                  to={detailPath}
                  className="admin-card-link"
                  aria-label={`${t("admin.view")}: ${user.email}`}
                  data-testid="admin-user-card"
                  data-role={user.role}
                >
                  <div className="admin-card-head">
                    <span className="admin-card-title">{user.email}</span>
                    <StatusBadge
                      variant="cell"
                      status={{
                        kind: "generic",
                        tone: user.is_active ? "open" : "neutral",
                        label: user.is_active
                          ? t("admin.status_active")
                          : t("admin.status_inactive"),
                      }}
                    />
                  </div>
                  <dl className="admin-card-meta">
                    {user.full_name && (
                      <div className="admin-card-meta-row">
                        <dt>{t("users.col_full_name")}</dt>
                        <dd>{user.full_name}</dd>
                      </div>
                    )}
                    {/* Sprint 154 §K — the phone travels with the card
                        list too, or the phone layout drifts from the
                        table it mirrors. */}
                    <div className="admin-card-meta-row">
                      <dt>{t("users.col_phone")}</dt>
                      <dd>{user.phone || "—"}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("users.col_role")}</dt>
                      <dd>
                        <RoleBadge role={user.role} />
                      </dd>
                    </div>
                    {!isProviderRole(user.role) &&
                      user.customer_access_role && (
                        <div className="admin-card-meta-row">
                          <dt>{t("users.col_access_role")}</dt>
                          <dd>
                            <AccessRoleBadge
                              accessRole={user.customer_access_role}
                            />
                          </dd>
                        </div>
                      )}
                    <div className="admin-card-meta-row">
                      <dt>{t("company")}</dt>
                      <dd>
                        <CompanyCell companies={user.companies} />
                      </dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("users.col_language")}</dt>
                      <dd>{user.language}</dd>
                    </div>
                    <div className="admin-card-meta-row">
                      <dt>{t("users.col_scope")}</dt>
                      <dd>
                        <ScopeChip summary={user.scope_summary} />
                      </dd>
                    </div>
                  </dl>
                  <div className="admin-card-actions">
                    <span className="btn btn-ghost btn-sm">
                      {t("admin.view")}
                    </span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>

        {!loading && visibleUsers.length === 0 && (
          <EmptyState
            icon={Users}
            title={
              hasActiveFilters
                ? t("users.empty_filtered_title")
                : t("users.empty_initial_title")
            }
            description={
              hasActiveFilters
                ? t("admin.empty_filtered_desc")
                : t("users.empty_initial_desc")
            }
            action={
              !hasActiveFilters ? (
                <Link
                  className="btn btn-primary btn-sm"
                  to="/admin/people/invitations"
                >
                  {t("users.invite_user")}
                </Link>
              ) : undefined
            }
          />
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



