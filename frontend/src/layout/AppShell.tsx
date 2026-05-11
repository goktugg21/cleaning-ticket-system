import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  BarChart3,
  Building2,
  ClipboardList,
  LayoutGrid,
  MailPlus,
  MapPin,
  Menu,
  PlusCircle,
  Settings,
  UserCog,
  Users,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthContext";
import { useLanguageSync } from "../i18n/useLanguageSync";

const STAFF_ROLES = new Set(["SUPER_ADMIN", "COMPANY_ADMIN"]);
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
            <NavLink to="/admin/staff-assignment-requests" className={navClass}>
              <span className="nav-icon">
                <ClipboardList size={16} strokeWidth={2} />
              </span>
              {t("nav.staff_requests")}
            </NavLink>
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
