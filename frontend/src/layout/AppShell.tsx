import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  BadgeEuro,
  BarChart3,
  Bell,
  Building2,
  CalendarCheck,
  CalendarClock,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Contact,
  FileText,
  LayoutGrid,
  Mail,
  MailPlus,
  MapPin,
  Megaphone,
  Menu,
  Package,
  PlusCircle,
  Receipt,
  Settings,
  ShieldCheck,
  Sparkles,
  Tag,
  Ticket,
  UserCog,
  Users,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthContext";
import {
  canAccessAdminArea,
  canAccessAgenda,
  canAccessAuditLogs,
  canAccessExtraWork,
  canAccessPlannedWork,
  canAccessReports,
  canAccessStaffRequestReview,
  isBuildingManager,
  isCustomerUser,
  roleLabelKey,
} from "../auth/permissions";
import { useLanguageSync } from "../i18n/useLanguageSync";
import { UserMenu } from "../components/UserMenu";
import { NotificationBell } from "../components/NotificationBell";
import { getCompany, getCustomer } from "../api/admin";
import { getInitials } from "../lib/initials";

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

function navClass({ isActive }: { isActive: boolean }) {
  return isActive ? "nav-item active" : "nav-item";
}

/**
 * Sprint 28 Batch 15.5 — sidebar customer-context chip.
 *
 * Renders inside the customer-scoped sidebar branch only. Shows the
 * customer name and, when resolvable, the provider company name so
 * an operator deep-linking to `/admin/customers/:id/…` immediately
 * sees which customer the submenu is scoped to.
 *
 * The chip fetches `getCustomer(id)` and then `getCompany(customer.company)`.
 * `CustomerAdmin` does not currently carry `company_name`, and we
 * deliberately don't add it to the customer serializer in this
 * batch (the backend slot is owned by the parallel scope_summary
 * work). The two REST calls together are tiny and only fire when
 * the sidebar mode is `customer-scoped`, so they're a non-issue
 * for top-level routes.
 */
function CustomerContextChip({ customerId }: { customerId: string }) {
  const { t } = useTranslation("common");
  const [name, setName] = useState<string | null>(null);
  const [companyName, setCompanyName] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const numericId = Number.parseInt(customerId, 10);
    // Bail without touching state: the initial values are already
    // null and triggering a setState in an effect's synchronous body
    // earns a react-hooks/set-state-in-effect lint error. The chip
    // simply shows the loading placeholder for the unreachable
    // non-numeric route which is fine because the URL regex in
    // deriveSidebarMode only matches positive integers anyway.
    if (!Number.isFinite(numericId)) {
      return;
    }
    getCustomer(numericId)
      .then(async (customer) => {
        if (cancelled) return;
        setName(customer.name);
        // Best-effort company-name resolve. Failure here must not
        // break the chip — the customer name is the primary content.
        try {
          const company = await getCompany(customer.company);
          if (cancelled) return;
          setCompanyName(company.name);
        } catch {
          if (!cancelled) setCompanyName(null);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setName(null);
          setCompanyName(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [customerId]);

  return (
    <div
      className="sidebar-customer-chip"
      data-testid="sidebar-customer-context-chip"
    >
      <div className="sidebar-customer-chip-eyebrow">
        {t("nav.customer_submenu.scoped_to")}
      </div>
      <div className="sidebar-customer-chip-name">{name ?? "…"}</div>
      {companyName && (
        <div className="sidebar-customer-chip-company">{companyName}</div>
      )}
    </div>
  );
}

interface AppShellProps {
  children?: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const { me } = useAuth();
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

  // M3 (SoT Addendum A.5) — Extra Work nav GROUP expansion. Default-
  // expanded whenever any child route is active; a manual toggle
  // overrides the default and lives in component state only (no
  // persistence — a refresh re-derives from the URL).
  const extraWorkChildActive =
    location.pathname.startsWith("/extra-work") ||
    location.pathname.startsWith("/planned-work");
  const [extraWorkManualOpen, setExtraWorkManualOpen] = useState<
    boolean | null
  >(null);
  const extraWorkOpen = extraWorkManualOpen ?? extraWorkChildActive;

  const userName =
    me?.full_name?.trim() || me?.email || t("topbar.user_fallback");
  // Role label resolves through the central role/key map in
  // auth/permissions.ts so every role (including STAFF) has a label and
  // a future seventh role won't silently fall through to "User".
  const roleLabel = t(roleLabelKey(me?.role));

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
          <div className="brand-icon">CO</div>
          <div>
            <div className="brand-name">{t("brand.name")}</div>
            <div className="brand-tag">{t("brand.tagline")}</div>
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
              {/* Sprint 28 Batch 15.5 — customer-context chip. */}
              <CustomerContextChip customerId={sidebar.customerId} />
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
              {/* Sprint 28 Batch 12 — BM-trimmed customer-scoped
                  submenu. BUILDING_MANAGER only has read-only access
                  to Overview + Contacts. The other entries
                  (Buildings, Users, Permissions, Pricing, Extra
                  Work, Settings) are admin-only edit surfaces and
                  hiding them keeps the role's surface area
                  consistent with the route guards. */}
              {!isBuildingManager(me?.role) && (
                <>
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
                    to={`/admin/customers/${sidebar.customerId}/quote-requests`}
                    className={navClass}
                    data-testid="sidebar-customer-quote-requests"
                  >
                    <span className="nav-icon">
                      <FileText size={16} strokeWidth={2} />
                    </span>
                    {t("nav.customer_submenu.quote_requests")}
                  </NavLink>
                  <NavLink
                    to={`/admin/customers/${sidebar.customerId}/tickets`}
                    className={navClass}
                    data-testid="sidebar-customer-tickets"
                  >
                    <span className="nav-icon">
                      <Ticket size={16} strokeWidth={2} />
                    </span>
                    {t("nav.customer_submenu.tickets")}
                  </NavLink>
                  <NavLink
                    to={`/admin/customers/${sidebar.customerId}/meldingen`}
                    className={navClass}
                    data-testid="sidebar-customer-meldingen"
                  >
                    <span className="nav-icon">
                      <Megaphone size={16} strokeWidth={2} />
                    </span>
                    {t("nav.customer_submenu.meldingen")}
                  </NavLink>
                </>
              )}
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
              {!isBuildingManager(me?.role) && (
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
              )}
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
              {/* RF-3 (Ramazan 2026-06-23) — providers/staff open a
                  top-level Tickets LIST (New Ticket lives inside it),
                  mirroring the Extra Work entry, instead of the old bare
                  jump straight to the create form. Customers keep the
                  fast melding-create entry (their list is My meldingen). */}
              {isCustomerUser(me?.role) ? (
                <NavLink to="/tickets/new" className={navClass}>
                  <span className="nav-icon">
                    <PlusCircle size={16} strokeWidth={2} />
                  </span>
                  {t("nav.new_melding")}
                </NavLink>
              ) : (
                <NavLink
                  to="/tickets"
                  className={navClass}
                  data-testid="sidebar-tickets"
                >
                  <span className="nav-icon">
                    <Ticket size={16} strokeWidth={2} />
                  </span>
                  {t("nav.tickets")}
                </NavLink>
              )}
              {canAccessAgenda(me?.role) && (
                <NavLink
                  to="/agenda"
                  className={navClass}
                  data-testid="sidebar-agenda"
                >
                  <span className="nav-icon">
                    <CalendarCheck size={16} strokeWidth={2} />
                  </span>
                  {t("nav.my_work")}
                </NavLink>
              )}
              <NavLink to="/notifications" className={navClass}>
                <span className="nav-icon">
                  <Bell size={16} strokeWidth={2} />
                </span>
                {t("nav.notifications")}
              </NavLink>
              {/* M3 (SoT Addendum A.5) — "Extra Work" is a nav GROUP
                  with three indented children. Routes are unchanged;
                  this is IA only. Group gate = the same
                  canAccessExtraWork as the old flat link; the
                  Recurring Work child keeps its canAccessPlannedWork
                  gate; Request a Quote uses the same gate as the
                  /extra-work/new entry (ExtraWorkRoute ⇒
                  canAccessExtraWork — no new role logic). */}
              {canAccessExtraWork(me?.role) && (
                <>
                  <button
                    type="button"
                    className="nav-item"
                    data-testid="sidebar-extra-work-group"
                    aria-expanded={extraWorkOpen}
                    onClick={() =>
                      setExtraWorkManualOpen(
                        (current) => !(current ?? extraWorkChildActive),
                      )
                    }
                    style={{
                      width: "100%",
                      border: "none",
                      background: "none",
                      font: "inherit",
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                  >
                    <span className="nav-icon">
                      <Receipt size={16} strokeWidth={2} />
                    </span>
                    {t("nav.extra_work")}
                    <span
                      style={{
                        marginLeft: "auto",
                        display: "inline-flex",
                        alignItems: "center",
                      }}
                      aria-hidden="true"
                    >
                      {extraWorkOpen ? (
                        <ChevronDown size={14} strokeWidth={2} />
                      ) : (
                        <ChevronRight size={14} strokeWidth={2} />
                      )}
                    </span>
                  </button>
                  {extraWorkOpen && (
                    <>
                      <NavLink
                        to="/extra-work"
                        className={({ isActive }) =>
                          navClass({
                            // The list link matches every /extra-work/*
                            // path; carve the quote page out so only its
                            // own child lights up there.
                            isActive:
                              isActive &&
                              !location.pathname.startsWith(
                                "/extra-work/request-quote",
                              ),
                          })
                        }
                        data-testid="sidebar-extra-work-request"
                        style={{ paddingLeft: 34 }}
                      >
                        <span className="nav-icon">
                          <ClipboardList size={16} strokeWidth={2} />
                        </span>
                        {t("nav.extra_work_request")}
                      </NavLink>
                      {canAccessPlannedWork(me?.role) && (
                        <NavLink
                          to="/planned-work"
                          className={navClass}
                          data-testid="sidebar-planned-work"
                          style={{ paddingLeft: 34 }}
                        >
                          <span className="nav-icon">
                            <CalendarClock size={16} strokeWidth={2} />
                          </span>
                          {t("nav.planned_work")}
                        </NavLink>
                      )}
                      <NavLink
                        to="/extra-work/request-quote"
                        className={navClass}
                        data-testid="sidebar-request-quote"
                        style={{ paddingLeft: 34 }}
                      >
                        <span className="nav-icon">
                          <BadgeEuro size={16} strokeWidth={2} />
                        </span>
                        {t("nav.request_quote")}
                      </NavLink>
                    </>
                  )}
                </>
              )}
              {canAccessReports(me?.role) && (
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

              {canAccessAdminArea(me?.role) && (
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
                  {/* Employees directory — provider-wide. Shown to
                      SA / CA inside the admin group; BUILDING_MANAGER
                      gets its own entry below (BM has no admin group). */}
                  <NavLink
                    to="/admin/employees"
                    className={navClass}
                    data-testid="sidebar-employees"
                  >
                    <span className="nav-icon">
                      <Contact size={16} strokeWidth={2} />
                    </span>
                    {t("nav.employees")}
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
                  {canAccessAuditLogs(me?.role) && (
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
              {canAccessStaffRequestReview(me?.role) && (
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

              {/* Employees directory — BM read-only entry. BM does not
                  see the admin group above, so the link lives here next
                  to the staff-requests queue (the other BM-visible
                  provider surface). SA / CA already have it in the
                  admin group, so this entry is BM-only. */}
              {isBuildingManager(me?.role) && (
                <NavLink
                  to="/admin/employees"
                  className={navClass}
                  data-testid="sidebar-employees-bm"
                >
                  <span className="nav-icon">
                    <Contact size={16} strokeWidth={2} />
                  </span>
                  {t("nav.employees")}
                </NavLink>
              )}

              {/* Mijn meldingen — customer-facing entry. Lists the
                  customer's own meldingen (REPORT-type tickets), scoped
                  server-side. */}
              {me?.role === "CUSTOMER_USER" && (
                <NavLink
                  to="/my/meldingen"
                  className={navClass}
                  data-testid="sidebar-my-meldingen"
                >
                  <span className="nav-icon">
                    <Megaphone size={16} strokeWidth={2} />
                  </span>
                  {t("nav.my_meldingen")}
                </NavLink>
              )}
              {/* Employees directory — customer-facing entry. Customer
                  users get a limited nav; this is their telephone-book
                  view of the colleagues at their own customer. */}
              {me?.role === "CUSTOMER_USER" && (
                <NavLink
                  to="/my/employees"
                  className={navClass}
                  data-testid="sidebar-my-employees"
                >
                  <span className="nav-icon">
                    <Contact size={16} strokeWidth={2} />
                  </span>
                  {t("nav.employees")}
                </NavLink>
              )}
            </>
          )}
        </nav>

        <div className="sidebar-footer">
          <div>
            <div className="footer-sys-name">{t("brand.system_short")}</div>
            <div className="footer-sys-ver">{t("brand.system_version")}</div>
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
          <div className="topbar-context">
            <span className="topbar-context-icon" aria-hidden="true">
              <Sparkles size={16} strokeWidth={2.2} />
            </span>
            <div className="topbar-context-text">
              <span className="topbar-context-eyebrow">
                {t("brand.tagline")}
              </span>
              <span className="topbar-context-name">{t("brand.name")}</span>
            </div>
          </div>
          <div className="topbar-right">
            <NotificationBell />
            <UserMenu />
          </div>
        </header>

        <main className="page-canvas">{children ?? <Outlet />}</main>
      </div>
    </div>
  );
}


