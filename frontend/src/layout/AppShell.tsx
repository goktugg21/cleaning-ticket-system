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
  ChevronRight,
  ClipboardList,
  Contact,
  Files,
  FileText,
  LayoutGrid,
  MapPin,
  Megaphone,
  MessagesSquare,
  Menu,
  MoreHorizontal,
  Package,
  PlusCircle,
  Receipt,
  Settings,
  Siren,
  Sparkles,
  Ticket,
  Timer,
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
  canAccessBilling,
  canAccessContracts,
  canAccessReports,
  canAccessStaffRequestReview,
  canAccessTimesheets,
  canManageSlaWarnings,
  canManageTimesheets,
  isBuildingManager,
  isCustomerUser,
  roleLabelKey,
} from "../auth/permissions";
import { useLanguageSync } from "../i18n/useLanguageSync";
import { UserMenu } from "../components/UserMenu";
import { NotificationBell } from "../components/NotificationBell";
import { InboxNavBadge } from "../components/InboxNavBadge";
import { listStaffAssignmentRequests } from "../api/admin";
import { getInitials } from "../lib/initials";

// FE-1 (Addendum D §D.3.1) — the customer "Meer" group's own routes.
// Same membership-list idea the old ADMIN fold used: the group opens
// itself while the current page is one of its own, so a customer can
// never be on Settings with the fold shut and no idea where they are.
const MEER_PATHS = [
  "/inbox",
  "/notifications",
  "/my/employees",
  "/my/documents",
  "/settings",
] as const;

function navClass({ isActive }: { isActive: boolean }) {
  return isActive ? "nav-item active" : "nav-item";
}

// Sprint 155 §1 — a child row inside a nav group. A MODIFIER on the same
// `.nav-item` class, not a parallel class: the two would drift on the
// next hover/active tweak, and the only difference is the indent.
function navChildClass({ isActive }: { isActive: boolean }) {
  return isActive ? "nav-item nav-item-child active" : "nav-item nav-item-child";
}

interface AppShellProps {
  children?: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const { me } = useAuth();
  const location = useLocation();
  const { t } = useTranslation("common");
  useLanguageSync();

  // FE-6 (§D.3.4) — there is no customer-scoped sidebar mode any more.
  // A customer is a page with tabs; the Klanten entry simply stays lit
  // across its subtree.
  const customersActive = /^\/admin\/customers(\/.*)?$/.test(location.pathname);
  // FE-6 — the merged surfaces light on their tabs AND on the per-record
  // pages that still live under the old prefixes.
  const peopleActive =
    /^\/admin\/(people|users|employees|invitations)(\/.*)?$/.test(
      location.pathname,
    );
  const servicesActive =
    /^\/admin\/(services-catalogs|services|catalogs)(\/.*)?$/.test(
      location.pathname,
    );

  /* FE-6 — how many staff requests wait for a reviewer. Read from the
     existing list endpoint (`count` on a PENDING query), fetched for
     the roles that may review and re-read on every navigation so the
     badge follows approvals. Null until it lands: the entry renders
     only once the server has said "more than zero". */
  const [staffRequestCount, setStaffRequestCount] = useState<number | null>(
    null,
  );
  const mayReviewRequests = canAccessStaffRequestReview(me?.role);
  useEffect(() => {
    if (!mayReviewRequests) return;
    let cancelled = false;
    listStaffAssignmentRequests({ status: "PENDING" })
      .then((page) => {
        if (!cancelled) setStaffRequestCount(page.count);
      })
      .catch(() => {
        /* the entry simply stays hidden */
      });
    return () => {
      cancelled = true;
    };
  }, [mayReviewRequests, location.pathname]);

  // Sprint 12 — mobile sidebar toggle. The sidebar is `position: fixed`
  // and hidden by default below the mobile breakpoint via CSS; the
  // `.sidebar-mobile-open` class on the outer .app element flips it
  // into an overlay. Auto-close on route navigation so a tap on a
  // nav-item dismisses the menu.
  const [sidebarOpen, setSidebarOpen] = useState(false);
  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  // FE-1 — which nav branch this account reads. Three surfaces, one
  // shell: the customer portal (§D.3.1), the staff four-entry nav
  // (§D.3.2), and the provider console in its four groups (§D.3.3/4).
  // Role GATES are unchanged — the branches only decide grouping and
  // order; every entry still carries the predicate it always carried.
  const isCustomer = isCustomerUser(me?.role);
  const isStaffOnly = me?.role === "STAFF";

  // Tickets (the work queue) lights on the list and a ticket, never on a sibling page.
  const ticketsActive = /^\/tickets(\/\d+(\/.*)?)?$/.test(location.pathname);
  // Meerwerk (the commercial pipeline, /extra-work) lights across its
  // own subtree — the list, both create forms and every detail page.
  const meerwerkActive = /^\/extra-work(\/.*)?$/.test(location.pathname);

  // FE-1 §D.3.1 — the customer "Meer" fold. Same three rules as every
  // fold before it (Sprint 157 §6): CLOSED on load, OPEN while the
  // current route is inside it, the visitor's own toggle winning over
  // both until they navigate away. One derived value, no resync effect.
  const [meerManual, setMeerManual] = useState<{
    path: string;
    open: boolean;
  } | null>(null);

  const meerChildActive = MEER_PATHS.some(
    (path) =>
      location.pathname === path || location.pathname.startsWith(`${path}/`),
  );

  const meerOpen =
    meerManual && meerManual.path === location.pathname
      ? meerManual.open
      : meerChildActive;

  const toggleMeer = () =>
    setMeerManual({ path: location.pathname, open: !meerOpen });

  const userName =
    me?.full_name?.trim() || me?.email || t("topbar.user_fallback");
  // Role label resolves through the central role/key map in
  // auth/permissions.ts so every role (including STAFF) has a label and
  // a future seventh role won't silently fall through to "User".
  const roleLabel = t(roleLabelKey(me?.role));

  // FE-1 §D.3.1 — the word "console" disappears from the customer
  // surface: a customer is in the provider's KLANTPORTAAL, not in an
  // operations console. One computed string feeds both the sidebar
  // brand line and the topbar eyebrow, so the two can never disagree.
  const tagline = isCustomer ? t("brand.tagline_customer") : t("brand.tagline");

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
            <div className="brand-tag">{tagline}</div>
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
          {isCustomer ? (
            // ---------------------------------------------------------
            // FE-1 §D.3.1 — the CUSTOMER PORTAL nav: six entries, fixed
            // order, with everything occasional folded under "Meer".
            // No provider KPIs, no console vocabulary, no machinery.
            // ---------------------------------------------------------
            <>
              <NavLink to="/" end className={navClass}>
                <span className="nav-icon">
                  <LayoutGrid size={16} strokeWidth={2} />
                </span>
                {t("nav.start")}
              </NavLink>
              <NavLink
                to="/tickets/new"
                className={navClass}
                data-testid="sidebar-new-melding"
              >
                <span className="nav-icon">
                  <PlusCircle size={16} strokeWidth={2} />
                </span>
                {t("nav.new_melding")}
              </NavLink>
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
              {/* Meerwerk: request + track, one word (§D.2). The list
                  is the /extra-work page; requesting is the FE-2 guided
                  flow behind it. FE-5: the "request a quote" child is
                  gone — a quote is a derived outcome of the request,
                  not a place (§D.5.2). Gate unchanged:
                  canAccessExtraWork admits CUSTOMER_USER. */}
              {canAccessExtraWork(me?.role) && (
                <NavLink
                  to="/extra-work"
                  className={() => navClass({ isActive: meerwerkActive })}
                  data-testid="sidebar-meerwerk"
                >
                  <span className="nav-icon">
                    <Receipt size={16} strokeWidth={2} />
                  </span>
                  {t("nav.meerwerk")}
                </NavLink>
              )}
              <NavLink
                to="/my/facturen"
                className={navClass}
                data-testid="sidebar-my-facturen"
              >
                <span className="nav-icon">
                  <BadgeEuro size={16} strokeWidth={2} />
                </span>
                {t("customer_facturen.nav")}
              </NavLink>
              {/* "Meer" — the fold for everything occasional. Same
                  disclosure primitives as every fold before it. */}
              <button
                type="button"
                className={
                  meerChildActive
                    ? "nav-item nav-item-group nav-item-group-current"
                    : "nav-item nav-item-group"
                }
                aria-expanded={meerOpen}
                aria-label={t(
                  meerOpen ? "nav.collapse_group" : "nav.expand_group",
                  { group: t("nav.meer") },
                )}
                onClick={toggleMeer}
                data-testid="sidebar-meer-toggle"
              >
                <span className="nav-icon">
                  <MoreHorizontal size={16} strokeWidth={2} />
                </span>
                <span className="nav-item-group-label">{t("nav.meer")}</span>
                <span className="nav-item-group-chevron">
                  {meerOpen ? (
                    <ChevronDown size={14} strokeWidth={2.4} />
                  ) : (
                    <ChevronRight size={14} strokeWidth={2.4} />
                  )}
                </span>
              </button>
              {meerOpen && (
                <>
                  <NavLink
                    to="/inbox"
                    className={navChildClass}
                    data-testid="sidebar-inbox"
                  >
                    <span className="nav-icon">
                      <MessagesSquare size={16} strokeWidth={2} />
                    </span>
                    {t("nav.inbox")}
                    <InboxNavBadge />
                  </NavLink>
                  <NavLink to="/notifications" className={navChildClass}>
                    <span className="nav-icon">
                      <Bell size={16} strokeWidth={2} />
                    </span>
                    {t("nav.notifications")}
                  </NavLink>
                  <NavLink
                    to="/my/employees"
                    className={navChildClass}
                    data-testid="sidebar-my-employees"
                  >
                    <span className="nav-icon">
                      <Contact size={16} strokeWidth={2} />
                    </span>
                    {t("nav.employees")}
                  </NavLink>
                  {me?.can_manage_documents && (
                    <NavLink
                      to="/my/documents"
                      className={navChildClass}
                      data-testid="sidebar-my-documents"
                    >
                      <span className="nav-icon">
                        <Files size={16} strokeWidth={2} />
                      </span>
                      {t("documents.my_nav")}
                    </NavLink>
                  )}
                  <NavLink to="/settings" className={navChildClass}>
                    <span className="nav-icon">
                      <Settings size={16} strokeWidth={2} />
                    </span>
                    {t("nav_settings")}
                  </NavLink>
                </>
              )}
            </>
          ) : isStaffOnly ? (
            // ---------------------------------------------------------
            // FE-1 §D.3.2 — the STAFF nav: four entries. Werkplanning
            // is the landing page ("/" redirects there in App.tsx);
            // the bell feed lives as a tab inside Berichten for this
            // role. Routes are untouched — a deep link still works.
            // ---------------------------------------------------------
            <>
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
              {canAccessTimesheets(me?.role) && (
                <NavLink
                  to="/my-hours"
                  className={navClass}
                  data-testid="sidebar-my-hours"
                >
                  <span className="nav-icon">
                    <Timer size={16} strokeWidth={2} />
                  </span>
                  {t("nav.my_hours")}
                </NavLink>
              )}
              <NavLink to="/inbox" className={navClass} data-testid="sidebar-inbox">
                <span className="nav-icon">
                  <MessagesSquare size={16} strokeWidth={2} />
                </span>
                {t("nav.inbox")}
                <InboxNavBadge />
              </NavLink>
              <NavLink to="/settings" className={navClass}>
                <span className="nav-icon">
                  <Settings size={16} strokeWidth={2} />
                </span>
                {t("nav_settings")}
              </NavLink>
            </>
          ) : (
            // ---------------------------------------------------------
            // FE-1 §D.3.3/§D.3.4 — the PROVIDER console in four groups:
            // Werk / Financieel / Klanten & mensen / Systeem. Every
            // entry keeps the exact gate it carried before the regroup;
            // a heading renders only when the role sees something under
            // it (BM never sees an empty "Systeem" run).
            // ---------------------------------------------------------
            <>
              <div className="nav-group-label">{t("nav.group_werk")}</div>
              <NavLink to="/" end className={navClass}>
                <span className="nav-icon">
                  <LayoutGrid size={16} strokeWidth={2} />
                </span>
                {t("nav.dashboard")}
              </NavLink>
              {/* W11 — ONE DOOR, at the top, above every list. */}
              <NavLink to="/new" className={navClass} data-testid="sidebar-new">
                <span className="nav-icon">
                  <PlusCircle size={16} strokeWidth={2} />
                </span>
                {t("nav.new_work")}
              </NavLink>
              {/* §D.3.4 — the work queue, labelled "Tickets" (owner decision 2026-08-29): tickets and meerwerk-execution
                  on one list, told apart by the type pill. The separate
                  "Chargeable work" entries are gone; the meerwerk-only
                  view is the list's own work filter. */}
              <NavLink
                to="/tickets"
                end
                className={() => navClass({ isActive: ticketsActive })}
                data-testid="sidebar-tickets"
              >
                <span className="nav-icon">
                  <Ticket size={16} strokeWidth={2} />
                </span>
                {t("nav.tickets")}
              </NavLink>
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
              {/* §D.2 — ONE commercial pipeline, ONE name: Meerwerk.
                  The same /extra-work page the "Offertes" entry opened;
                  quotes are a phase of it, not a separate place. */}
              {canAccessExtraWork(me?.role) && (
                <NavLink
                  to="/extra-work"
                  className={() => navClass({ isActive: meerwerkActive })}
                  data-testid="sidebar-meerwerk"
                >
                  <span className="nav-icon">
                    <Receipt size={16} strokeWidth={2} />
                  </span>
                  {t("nav.meerwerk")}
                </NavLink>
              )}
              {canAccessPlannedWork(me?.role) && (
                <NavLink
                  to="/planned-work"
                  className={navClass}
                  data-testid="sidebar-planned-work"
                >
                  <span className="nav-icon">
                    <CalendarClock size={16} strokeWidth={2} />
                  </span>
                  {t("nav.planned_work")}
                </NavLink>
              )}
              <NavLink to="/notifications" className={navClass}>
                <span className="nav-icon">
                  <Bell size={16} strokeWidth={2} />
                </span>
                {t("nav.notifications")}
              </NavLink>
              <NavLink to="/inbox" className={navClass} data-testid="sidebar-inbox">
                <span className="nav-icon">
                  <MessagesSquare size={16} strokeWidth={2} />
                </span>
                {t("nav.inbox")}
                <InboxNavBadge />
              </NavLink>

              {(canAccessBilling(me?.role) ||
                canAccessContracts(me?.role) ||
                canManageTimesheets(me?.role) ||
                canAccessTimesheets(me?.role) ||
                canAccessReports(me?.role)) && (
                <div className="nav-group-label">
                  {t("nav.group_financieel")}
                </div>
              )}
              {canAccessBilling(me?.role) && (
                <NavLink to="/invoices" className={navClass}>
                  <span className="nav-icon">
                    <BadgeEuro size={16} strokeWidth={2} />
                  </span>
                  {t("nav.invoices")}
                </NavLink>
              )}
              {/* One Contracten entry for every role that may read
                  contracts — the same SA/CA/BM set that used to reach
                  it through two differently-placed rows. */}
              {canAccessContracts(me?.role) && (
                <NavLink
                  to="/admin/contracts"
                  className={navClass}
                  data-testid="sidebar-contracts"
                >
                  <span className="nav-icon">
                    <FileText size={16} strokeWidth={2} />
                  </span>
                  {t("nav.contracts", { ns: "contracts" })}
                </NavLink>
              )}
              {canManageTimesheets(me?.role) && (
                <NavLink
                  to="/admin/hours"
                  className={navClass}
                  data-testid="sidebar-hours-admin"
                >
                  <span className="nav-icon">
                    <Timer size={16} strokeWidth={2} />
                  </span>
                  {t("nav.hours_admin")}
                </NavLink>
              )}
              {/* Sprint 152 — employee hours. Every provider-side
                  role including STAFF; customer-side users see no
                  trace of the module. */}
              {canAccessTimesheets(me?.role) && (
                <NavLink
                  to="/my-hours"
                  className={navClass}
                  data-testid="sidebar-my-hours"
                >
                  <span className="nav-icon">
                    <Timer size={16} strokeWidth={2} />
                  </span>
                  {t("nav.my_hours")}
                </NavLink>
              )}
              {canAccessReports(me?.role) && (
                <NavLink to="/reports" className={navClass}>
                  <span className="nav-icon">
                    <BarChart3 size={16} strokeWidth={2} />
                  </span>
                  {t("nav.reports")}
                </NavLink>
              )}

              {(canAccessAdminArea(me?.role) ||
                isBuildingManager(me?.role) ||
                canAccessStaffRequestReview(me?.role)) && (
                <div className="nav-group-label">
                  {t("nav.group_klanten_mensen")}
                </div>
              )}
              {canAccessAdminArea(me?.role) && (
                <>
                  <NavLink
                    to="/admin/customers"
                    className={() => navClass({ isActive: customersActive })}
                    data-testid="sidebar-customers"
                  >
                    <span className="nav-icon">
                      <Users size={16} strokeWidth={2} />
                    </span>
                    {t("nav.customers")}
                  </NavLink>
                  <NavLink to="/admin/buildings" className={navClass}>
                    <span className="nav-icon">
                      <MapPin size={16} strokeWidth={2} />
                    </span>
                    {t("nav.buildings")}
                  </NavLink>
                </>
              )}
              {/* FE-6 (§D.3.4) — ONE "Mensen" entry for the users +
                  employees + invitations surface. The gate is the union
                  of the three it replaces (SA/CA everywhere, BM through
                  the employees tab), and each tab keeps its own. */}
              {(canAccessAdminArea(me?.role) ||
                isBuildingManager(me?.role)) && (
                <NavLink
                  to="/admin/people"
                  className={() => navClass({ isActive: peopleActive })}
                  data-testid="sidebar-people"
                >
                  <span className="nav-icon">
                    <UserCog size={16} strokeWidth={2} />
                  </span>
                  {t("nav.people")}
                </NavLink>
              )}
              {/* Sprint 23B — staff assignment requests review queue.
                  FE-6: badge-driven, hidden when there is nothing to
                  review. The page stays reachable by address. */}
              {canAccessStaffRequestReview(me?.role) &&
                staffRequestCount !== null &&
                staffRequestCount > 0 && (
                  <NavLink
                    to="/admin/staff-assignment-requests"
                    className={navClass}
                    data-testid="sidebar-staff-requests"
                  >
                    <span className="nav-icon">
                      <ClipboardList size={16} strokeWidth={2} />
                    </span>
                    {t("nav.staff_requests")}
                    <span
                      className="nav-badge"
                      data-testid="sidebar-staff-requests-count"
                    >
                      {staffRequestCount}
                    </span>
                  </NavLink>
                )}

              <div className="nav-group-label">{t("nav.group_systeem")}</div>
              {canAccessAdminArea(me?.role) && (
                <>
                  {/* FE-6 (§D.3.4) — ONE "Diensten & catalogi" entry. */}
                  <NavLink
                    to="/admin/services-catalogs"
                    className={() => navClass({ isActive: servicesActive })}
                    data-testid="sidebar-services-catalogs"
                  >
                    <span className="nav-icon">
                      <Package size={16} strokeWidth={2} />
                    </span>
                    {t("nav.services_catalogs")}
                  </NavLink>
                  <NavLink to="/admin/companies" className={navClass}>
                    <span className="nav-icon">
                      <Building2 size={16} strokeWidth={2} />
                    </span>
                    {t("nav.companies")}
                  </NavLink>
                </>
              )}
              {/* Sprint 18 — audit log link is super-admin-only on the
                  backend (`audit/views.py::IsSuperAdmin`). Mirrored here. */}
              {canAccessAuditLogs(me?.role) && (
                <NavLink to="/admin/audit-logs" className={navClass}>
                  <span className="nav-icon">
                    <ClipboardList size={16} strokeWidth={2} />
                  </span>
                  {t("nav.audit_logs")}
                </NavLink>
              )}
              {/* Sprint W4-Q §2 — the warning thresholds, per company. */}
              {canManageSlaWarnings(me?.role) && (
                <NavLink
                  to="/admin/sla-warnings"
                  className={navClass}
                  data-testid="sidebar-sla-warnings"
                >
                  <span className="nav-icon">
                    <Siren size={16} strokeWidth={2} />
                  </span>
                  {t("nav.sla_warnings")}
                </NavLink>
              )}
              <NavLink to="/settings" className={navClass}>
                <span className="nav-icon">
                  <Settings size={16} strokeWidth={2} />
                </span>
                {t("nav_settings")}
              </NavLink>
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
              <span className="topbar-context-eyebrow">{tagline}</span>
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
