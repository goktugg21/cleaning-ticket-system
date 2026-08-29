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
  Files,
  FileText,
  LayoutGrid,
  Mail,
  MailPlus,
  MapPin,
  Megaphone,
  MessagesSquare,
  Menu,
  Library,
  MoreHorizontal,
  Package,
  PlusCircle,
  Receipt,
  Settings,
  ShieldCheck,
  Siren,
  Sparkles,
  Tag,
  Tags,
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
import { getCompany, getCustomer } from "../api/admin";
import { getInitials } from "../lib/initials";

// Sprint 28 Batch 3 — sidebar mode is URL-derived (not React state)
// so a browser refresh on a customer-scoped route preserves the
// customer-scoped sidebar. The regex matches
// `/admin/customers/:id` and `/admin/customers/:id/<anything>`
// where :id is a positive integer; it deliberately does NOT match
// `/admin/customers` (the list page) or `/admin/customers/new`.
const CUSTOMER_SCOPED_PATH = /^\/admin\/customers\/(\d+)(?:\/.*)?$/;

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

// Sprint 155 §1 — a child row inside a nav group. A MODIFIER on the same
// `.nav-item` class, not a parallel class: the two would drift on the
// next hover/active tweak, and the only difference is the indent.
function navChildClass({ isActive }: { isActive: boolean }) {
  return isActive ? "nav-item nav-item-child active" : "nav-item nav-item-child";
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
              <div className="nav-group-label">
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
                  {/* Sprint 166 §5 — Contracts. The page and its route
                      have existed since Sprint 162 and there was NO way
                      to reach them: no sidebar entry, so only a typed
                      URL. Placed next to Pricing and Extra Work because
                      all three are the customer's money. Gated the same
                      way the page is — provider-side only; a contract
                      carries negotiated prices. */}
                  {canAccessContracts(me?.role) && (
                    <NavLink
                      to={`/admin/customers/${sidebar.customerId}/contracts`}
                      className={navClass}
                      data-testid="sidebar-customer-contracts"
                    >
                      <span className="nav-icon">
                        <FileText size={16} strokeWidth={2} />
                      </span>
                      {t("nav.customer_submenu.contracts")}
                    </NavLink>
                  )}
                  {/* FE-1 — the "Chargeable work" child entry is gone
                      (§D.2: the standalone name dies). The route
                      redirects to the customer's ticket list with the
                      meerwerk narrowing preselected; the list's type
                      pill carries the relationship the child entry used
                      to state. */}
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
                  {/* IA 2026-06-25 — Meldingen and Offerteaanvragen merged
                      into these two as filter chips (4 content tabs -> 2). */}
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
                  {/* #108 Part E — customer-scoped Invoices + Reports. */}
                  <NavLink
                    to={`/admin/customers/${sidebar.customerId}/invoices`}
                    className={navClass}
                    data-testid="sidebar-customer-invoices"
                  >
                    <span className="nav-icon">
                      <BadgeEuro size={16} strokeWidth={2} />
                    </span>
                    {t("nav.customer_submenu.invoices")}
                  </NavLink>
                  <NavLink
                    to={`/admin/customers/${sidebar.customerId}/reports`}
                    className={navClass}
                    data-testid="sidebar-customer-reports"
                  >
                    <span className="nav-icon">
                      <BarChart3 size={16} strokeWidth={2} />
                    </span>
                    {t("nav.customer_submenu.reports")}
                  </NavLink>
                  {/* Sprint 126 — customer Documents (SA/CA only; BM is
                      already excluded from this block). */}
                  <NavLink
                    to={`/admin/customers/${sidebar.customerId}/documents`}
                    className={navClass}
                    data-testid="sidebar-customer-documents"
                  >
                    <span className="nav-icon">
                      <Files size={16} strokeWidth={2} />
                    </span>
                    {t("nav.customer_submenu.documents")}
                  </NavLink>
                </>
              )}
              {/* Sprint 128 — Extra Work label management (Afdelingen +
                  Werktypes). OUTSIDE the !isBuildingManager block: BM reads it
                  read-only (they hold the relabel action), SA/CA manage. */}
              <NavLink
                to={`/admin/customers/${sidebar.customerId}/labels`}
                className={navClass}
                data-testid="sidebar-customer-labels"
              >
                <span className="nav-icon">
                  <Tags size={16} strokeWidth={2} />
                </span>
                {t("nav.customer_submenu.labels")}
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
          ) : isCustomer ? (
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
                  is today's /extra-work page; the request child is
                  today's quote-request form. The FE-2 guided flow will
                  replace the child, not this structure. Gate unchanged:
                  canAccessExtraWork admits CUSTOMER_USER. */}
              {canAccessExtraWork(me?.role) && (
                <>
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
                  <NavLink
                    to="/extra-work/request-quote"
                    className={navChildClass}
                    data-testid="sidebar-request-quote"
                  >
                    <span className="nav-icon">
                      <FileText size={16} strokeWidth={2} />
                    </span>
                    {t("nav.request_quote")}
                  </NavLink>
                </>
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
                  <NavLink to="/admin/customers" className={navClass}>
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
                  <NavLink to="/admin/users" className={navClass}>
                    <span className="nav-icon">
                      <UserCog size={16} strokeWidth={2} />
                    </span>
                    {t("nav.users")}
                  </NavLink>
                </>
              )}
              {/* Employees directory: SA/CA through the admin area, BM
                  through its own read-only entry — the same two doors
                  as before, now one row with the union gate. */}
              {(canAccessAdminArea(me?.role) ||
                isBuildingManager(me?.role)) && (
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
              )}
              {canAccessAdminArea(me?.role) && (
                <NavLink to="/admin/invitations" className={navClass}>
                  <span className="nav-icon">
                    <MailPlus size={16} strokeWidth={2} />
                  </span>
                  {t("nav.invitations")}
                </NavLink>
              )}
              {/* Sprint 23B — staff assignment requests review queue.
                  BM sees this one queue without the rest of the admin
                  entries, exactly as before. */}
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

              <div className="nav-group-label">{t("nav.group_systeem")}</div>
              {canAccessAdminArea(me?.role) && (
                <>
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
                  {/* Sprint 178 §1 — ONE place for every per-company
                      catalog. */}
                  <NavLink
                    to="/admin/catalogs"
                    className={navClass}
                    data-testid="sidebar-catalogs"
                  >
                    <span className="nav-icon">
                      <Library size={16} strokeWidth={2} />
                    </span>
                    {t("nav.catalogs")}
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
