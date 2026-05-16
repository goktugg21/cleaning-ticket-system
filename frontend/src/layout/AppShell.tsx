import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  BarChart3,
  Building2,
  ChevronLeft,
  ClipboardList,
  LayoutGrid,
  Mail,
  MailPlus,
  MapPin,
  Menu,
  Package,
  PlusCircle,
  Receipt,
  Settings,
  ShieldCheck,
  Tag,
  UserCog,
  Users,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthContext";
import { useLanguageSync } from "../i18n/useLanguageSync";

const STAFF_ROLES = new Set(["SUPER_ADMIN", "COMPANY_ADMIN"]);
// Sprint 26C — Extra Work MVP. STAFF is excluded because the
// backend's scope_extra_work_for returns .none() for staff today
// (no staff-execution surface yet). Mirror the ExtraWorkRoute
// guard so staff users don't see a sidebar link that leads to an
// empty list.
const EXTRA_WORK_ROLES = new Set([
  "SUPER_ADMIN",
  "COMPANY_ADMIN",
  "BUILDING_MANAGER",
  "CUSTOMER_USER",
]);
// Sprint 23B — the staff-assignment-request review queue is for
// service-provider-side reviewers. Building managers also see it
// (their own buildings only — backend queryset gate). STAFF and
// CUSTOMER_USER never see the link; STAFF requests via the ticket
// detail "Request assignment" button instead.
const STAFF_REQUEST_REVIEW_ROLES = new Set([
  "SUPER_ADMIN",
  "COMPANY_ADMIN",
  "BUILDING_MANAGER",
]);
const REPORTS_ROLES = new Set([
  "SUPER_ADMIN",
  "COMPANY_ADMIN",
  "BUILDING_MANAGER",
]);

const ROLE_KEY: Record<string, string> = {
  SUPER_ADMIN: "roles.super_admin",
  COMPANY_ADMIN: "roles.company_admin",
  BUILDING_MANAGER: "roles.building_manager",
  CUSTOMER_USER: "roles.customer_user",
};

// Sprint 28 Batch 3 — sidebar mode is URL-derived (not React state)
// so a browser refresh on a customer-scoped route preserves the
// customer-scoped sidebar. The regex matches
// `/admin/customers/:id` and `/admin/customers/:id/<anything>`
// where :id is a positive integer; it deliberately does NOT match
// `/admin/customers` (the list page) or `/admin/customers/new`.
const CUSTOMER_SCOPED_PATH = /^\/admin\/customers\/(\d+)(?:\/.*)?$/;

interface SidebarModeState {
  mode: "top-level" | "customer-scoped";
  customerId: string | null;
}

function deriveSidebarMode(pathname: string): SidebarModeState {
  const match = CUSTOMER_SCOPED_PATH.exec(pathname);
  if (match) {
    return { mode: "customer-scoped", customerId: match[1] };
  }
  return { mode: "top-level", customerId: null };
}

function getInitials(value: string | undefined): string {
  if (!value) return "FM";

  const clean = value.split("@")[0].replace(/[._-]+/g, " ");
  const parts = clean.split(" ").filter(Boolean);

  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }

  return clean.slice(0, 2).toUpperCase();
}

function navClass({ isActive }: { isActive: boolean }) {
  return isActive ? "nav-item active" : "nav-item";
}

interface AppShellProps {
  children?: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const { me, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation("common");
  useLanguageSync();

  // Sprint 28 Batch 3 — derive sidebar mode from the current URL.
  // No useState: the mode is a pure function of pathname so it
  // survives a hard refresh / deep-link entry.
  const sidebar = deriveSidebarMode(location.pathname);

  // Sprint 12 — mobile sidebar toggle. The sidebar is `position: fixed`
  // and hidden by default below the mobile breakpoint via CSS; the
  // `.sidebar-mobile-open` class on the outer .app element flips it
  // into an overlay. Auto-close on route navigation so a tap on a
  // nav-item dismisses the menu.
  const [sidebarOpen, setSidebarOpen] = useState(false);
  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  const userName =
    me?.full_name?.trim() || me?.email || t("topbar.user_fallback");
  const userEmail = me?.email || "";
  // Role label resolves through the i18n key map: enum value (SUPER_ADMIN
  // etc.) → key (roles.super_admin) → translated label. Falls back to the
  // generic "User" key when role is missing.
  const roleLabel = me?.role
    ? t(ROLE_KEY[me.role] ?? "roles.fallback")
    : t("roles.fallback");

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className={`app${sidebarOpen ? " sidebar-mobile-open" : ""}`}>
      {sidebarOpen && (
        <button
          type="button"
          className="sidebar-backdrop"
          aria-label={t("sidebar_close")}
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-icon">FM</div>
          <div>
            <div className="brand-name">FacilityPro</div>
            <div className="brand-tag">{t("topbar.brand_tag")}</div>
          </div>
        </div>

        <div className="sidebar-user">
          <div className="user-avatar-block">{getInitials(userName)}</div>
          <div style={{ minWidth: 0 }}>
            <div className="user-name">{userName}</div>
            <div className="user-role">{roleLabel}</div>
          </div>
        </div>

        <nav className="sidebar-nav" aria-label="Main navigation">
          {sidebar.mode === "customer-scoped" && sidebar.customerId ? (
            // Sprint 28 Batch 3 — customer-scoped submenu. The
            // surrounding `AdminRoute` gate (see `App.tsx`) means
            // only SUPER_ADMIN / COMPANY_ADMIN ever reach this
            // branch; we therefore do not duplicate the role
            // filter here. The "Back" entry is a real route
            // navigation (not history.back) so deep-link entries
            // still have a sane home target.
            <>
              <NavLink
                to="/admin/customers"
                end
                className={navClass}
                data-testid="sidebar-customer-back"
              >
                <span className="nav-icon">
                  <ChevronLeft size={16} strokeWidth={2} />
                </span>
                {t("nav.customer_submenu.back")}
              </NavLink>
              <div className="nav-group-label" style={{ marginTop: 8 }}>
                {t("nav.customers")}
              </div>
              <NavLink
                to={`/admin/customers/${sidebar.customerId}`}
                end
                className={navClass}
                data-testid="sidebar-customer-overview"
              >
                <span className="nav-icon">
                  <LayoutGrid size={16} strokeWidth={2} />
                </span>
                {t("nav.customer_submenu.overview")}
              </NavLink>
              <NavLink
                to={`/admin/customers/${sidebar.customerId}/buildings`}
                className={navClass}
                data-testid="sidebar-customer-buildings"
              >
                <span className="nav-icon">
                  <MapPin size={16} strokeWidth={2} />
                </span>
                {t("nav.customer_submenu.buildings")}
              </NavLink>
              <NavLink
                to={`/admin/customers/${sidebar.customerId}/users`}
                className={navClass}
                data-testid="sidebar-customer-users"
              >
                <span className="nav-icon">
                  <UserCog size={16} strokeWidth={2} />
                </span>
                {t("nav.customer_submenu.users")}
              </NavLink>
              <NavLink
                to={`/admin/customers/${sidebar.customerId}/permissions`}
                className={navClass}
                data-testid="sidebar-customer-permissions"
              >
                <span className="nav-icon">
                  <ShieldCheck size={16} strokeWidth={2} />
                </span>
                {t("nav.customer_submenu.permissions")}
              </NavLink>
              {/* Sprint 28 Batch 5 — per-customer pricing. */}
              <NavLink
                to={`/admin/customers/${sidebar.customerId}/pricing`}
                className={navClass}
                data-testid="sidebar-customer-pricing"
              >
                <span className="nav-icon">
                  <Tag size={16} strokeWidth={2} />
                </span>
                {t("nav.customer_submenu.pricing")}
              </NavLink>
              <NavLink
                to={`/admin/customers/${sidebar.customerId}/extra-work`}
                className={navClass}
                data-testid="sidebar-customer-extra-work"
              >
                <span className="nav-icon">
                  <Receipt size={16} strokeWidth={2} />
                </span>
                {t("nav.customer_submenu.extra_work")}
              </NavLink>
              <NavLink
                to={`/admin/customers/${sidebar.customerId}/contacts`}
                className={navClass}
                data-testid="sidebar-customer-contacts"
              >
                <span className="nav-icon">
                  <Mail size={16} strokeWidth={2} />
                </span>
                {t("nav.customer_submenu.contacts")}
              </NavLink>
              <NavLink
                to={`/admin/customers/${sidebar.customerId}/settings`}
                className={navClass}
                data-testid="sidebar-customer-settings"
              >
                <span className="nav-icon">
                  <Settings size={16} strokeWidth={2} />
                </span>
                {t("nav.customer_submenu.settings")}
              </NavLink>
            </>
          ) : (
            <>
              <div className="nav-group-label">{t("nav.operations_group")}</div>
              <NavLink to="/" end className={navClass}>
                <span className="nav-icon">
                  <LayoutGrid size={16} strokeWidth={2} />
                </span>
                {t("nav.dashboard")}
              </NavLink>
              <NavLink to="/tickets/new" className={navClass}>
                <span className="nav-icon">
                  <PlusCircle size={16} strokeWidth={2} />
                </span>
                {t("nav.new_ticket")}
              </NavLink>
              {me?.role && EXTRA_WORK_ROLES.has(me.role) && (
                <NavLink to="/extra-work" className={navClass}>
                  <span className="nav-icon">
                    <Receipt size={16} strokeWidth={2} />
                  </span>
                  {t("nav.extra_work")}
                </NavLink>
              )}
              {me?.role && REPORTS_ROLES.has(me.role) && (
                <NavLink to="/reports" className={navClass}>
                  <span className="nav-icon">
                    <BarChart3 size={16} strokeWidth={2} />
                  </span>
                  {t("nav.reports")}
                </NavLink>
              )}
              <NavLink to="/settings" className={navClass}>
                <span className="nav-icon">
                  <Settings size={16} strokeWidth={2} />
                </span>
                {t("nav_settings")}
              </NavLink>

              {me?.role && STAFF_ROLES.has(me.role) && (
                <>
                  <div className="nav-group-label" style={{ marginTop: 8 }}>
                    {t("nav.admin_group")}
                  </div>
                  <NavLink to="/admin/companies" className={navClass}>
                    <span className="nav-icon">
                      <Building2 size={16} strokeWidth={2} />
                    </span>
                    {t("nav.companies")}
                  </NavLink>
                  <NavLink to="/admin/buildings" className={navClass}>
                    <span className="nav-icon">
                      <MapPin size={16} strokeWidth={2} />
                    </span>
                    {t("nav.buildings")}
                  </NavLink>
                  <NavLink to="/admin/customers" className={navClass}>
                    <span className="nav-icon">
                      <Users size={16} strokeWidth={2} />
                    </span>
                    {t("nav.customers")}
                  </NavLink>
                  {/* Sprint 28 Batch 5 — provider-wide service catalog. */}
                  <NavLink
                    to="/admin/services"
                    className={navClass}
                    data-testid="sidebar-services"
                  >
                    <span className="nav-icon">
                      <Package size={16} strokeWidth={2} />
                    </span>
                    {t("nav.services")}
                  </NavLink>
                  <NavLink to="/admin/users" className={navClass}>
                    <span className="nav-icon">
                      <UserCog size={16} strokeWidth={2} />
                    </span>
                    {t("nav.users")}
                  </NavLink>
                  <NavLink to="/admin/invitations" className={navClass}>
                    <span className="nav-icon">
                      <MailPlus size={16} strokeWidth={2} />
                    </span>
                    {t("nav.invitations")}
                  </NavLink>
                  {/*
                    Sprint 18 — audit log link is super-admin-only on the
                    backend (`audit/views.py::IsSuperAdmin`). We mirror
                    that gate here so company admins do not see a link
                    that would 403 on every visit.
                  */}
                  {me?.role === "SUPER_ADMIN" && (
                    <NavLink to="/admin/audit-logs" className={navClass}>
                      <span className="nav-icon">
                        <ClipboardList size={16} strokeWidth={2} />
                      </span>
                      {t("nav.audit_logs")}
                    </NavLink>
                  )}
                </>
              )}

              {/* Sprint 23B — staff assignment requests review queue.
                  Visible to SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER.
                  The backend viewset returns no rows for CUSTOMER_USER
                  (the link is hidden anyway since this nav block lives
                  outside STAFF_ROLES). Building managers see the link
                  even though they don't see the rest of the admin
                  group — they need this one queue. */}
              {me?.role && STAFF_REQUEST_REVIEW_ROLES.has(me.role) && (
                <NavLink
                  to="/admin/staff-assignment-requests"
                  className={navClass}
                >
                  <span className="nav-icon">
                    <ClipboardList size={16} strokeWidth={2} />
                  </span>
                  {t("nav.staff_requests")}
                </NavLink>
              )}
            </>
          )}
        </nav>

        <div className="sidebar-footer">
          <div>
            <div className="footer-sys-name">VERIDIAN</div>
            <div className="footer-sys-ver">Ops Console v1.0</div>
          </div>
          <div className="status-dot">{t("topbar.online")}</div>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <button
            type="button"
            className="sidebar-toggle"
            aria-label={sidebarOpen ? t("sidebar_close") : t("sidebar_open")}
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen((value) => !value)}
          >
            {sidebarOpen ? (
              <X size={18} strokeWidth={2.2} />
            ) : (
              <Menu size={18} strokeWidth={2.2} />
            )}
          </button>
          <div className="topbar-left">
            <span className="topbar-kicker">{t("topbar.kicker")}</span>
            <span className="topbar-title">{t("topbar.title")}</span>
          </div>
          <div className="topbar-right">
            <div className="topbar-identity">
              <div className="identity-text">
                <div className="identity-name">{userName}</div>
                {userEmail && (
                  <div className="identity-email">{userEmail}</div>
                )}
              </div>
              <span className="identity-role">{roleLabel}</span>
            </div>
            <div className="topbar-divider" />
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleLogout}
            >
              {t("sign_out")}
            </button>
          </div>
        </header>

        <main className="page-canvas">{children ?? <Outlet />}</main>
      </div>
    </div>
  );
}
