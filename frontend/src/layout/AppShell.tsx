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
  FilePlus2,
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

  // Sprint 156 §2 — the Extra Work group defaults to CLOSED, every load.
  //
  // Sprint 155 defaulted it OPEN on the reasoning that closed-by-default
  // was what made the old M3 group a two-click detour. That reasoning
  // does not apply once the parent LABEL navigates: the list is one
  // click away whether the group is open or shut, so the children being
  // folded costs nothing and the sidebar is shorter. The owner asked for
  // closed; there is no longer an argument against it.
  //
  // What keeps this from hiding anything (the §9 rule, and `## NEXT`
  // item 19's standing objection to disclosure groups): clicking the
  // label BOTH navigates and opens the group. So the one gesture an
  // operator naturally makes reveals the children — they can never end
  // up on /extra-work with the group shut and no idea the other three
  // entries exist.
  //
  // Plain state, not URL-derived: deriving it from the route would
  // re-open the group the moment the operator navigated inside it,
  // silently undoing the collapse they just asked for.
  // Sprint 157 §6 — three rules at once: CLOSED when the app loads, OPEN
  // while the current route is one of the group's children, and the
  // operator's own toggle winning over both until they navigate away.
  //
  // All three fall out of ONE derived value, which is the point: the
  // override carries the path it was made on, so it simply stops
  // applying when the pathname changes. No effect resets it — and a
  // resync effect here would be a synchronous setState in an effect
  // body, which CLAUDE.md forbids and which §6 rules out explicitly.
  //
  // (§6 describes `AppShell` as already holding
  // `extraWorkManualOpen ?? extraWorkChildActive`. It did not — it held
  // a plain boolean from Sprint 156. The behaviour asked for is what is
  // built here.)
  const [extraWorkManual, setExtraWorkManual] = useState<{
    path: string;
    open: boolean;
  } | null>(null);

  // W-NAV1 — the parent is a pure disclosure control now (no route of
  // its own), so `/extra-work` itself IS a child ("Extra Work Quote")
  // and belongs in this test. Chargeable Work is a second door onto
  // `/tickets/chargeable` (the existing Tickets-side route), so it is
  // counted here too — the group must read as active from either door.
  const extraWorkChildActive =
    location.pathname === "/extra-work" ||
    location.pathname.startsWith("/extra-work/") ||
    location.pathname.startsWith("/planned-work") ||
    location.pathname.startsWith("/tickets/chargeable");

  const extraWorkOpen =
    extraWorkManual && extraWorkManual.path === location.pathname
      ? extraWorkManual.open
      : extraWorkChildActive;

  /** Toggle for THIS route. Navigating anywhere else lets it lapse. */
  const toggleExtraWork = () =>
    setExtraWorkManual({
      path: location.pathname,
      open: !extraWorkOpen,
    });

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
                  {/* Sprint 186 §4 — the customer's work pages read in
                      the SAME shape and the SAME order as the main
                      navigation: Tickets, then Chargeable work as a
                      CHILD of it, then Extra work. Sprint 184 §3b added
                      Chargeable work here as a third sibling, so the one
                      relationship the main nav states — these are the
                      same tickets, narrowed to the ones born from an
                      Extra Work — had to be learned twice, and the
                      customer submenu listed the three in the opposite
                      order to the nav above it. */}
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
                    to={`/admin/customers/${sidebar.customerId}/chargeable`}
                    className={navChildClass}
                    data-testid="sidebar-customer-chargeable"
                  >
                    <span className="nav-icon">
                      <BadgeEuro size={16} strokeWidth={2} />
                    </span>
                    {t("nav.customer_submenu.chargeable")}
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
          ) : (
            <>
              <div className="nav-group-label">{t("nav.operations_group")}</div>
              <NavLink to="/" end className={navClass}>
                <span className="nav-icon">
                  <LayoutGrid size={16} strokeWidth={2} />
                </span>
                {t("nav.dashboard")}
              </NavLink>
              {/* W11 — ONE DOOR, at the top, above every list.
                  It asks what happened and picks the record type from
                  the answers. The specialised entries further down this
                  menu are untouched and still go straight to their own
                  forms, for people who already know which one they
                  want. */}
              <NavLink to="/new" className={navClass} data-testid="sidebar-new">
                <span className="nav-icon">
                  <PlusCircle size={16} strokeWidth={2} />
                </span>
                {t("nav.new_work")}
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
              {/* Sprint 181 §5 — chargeable work, as its own entry under
                  Tickets. A CHILD row, because that is what it is: the
                  same tickets, narrowed to the ones born from an Extra
                  Work. Provider-side only — a customer's meldingen list
                  is not the place to slice our billing pipeline. */}
              {!isCustomerUser(me?.role) && (
                <NavLink
                  to="/tickets/chargeable"
                  className={navChildClass}
                  data-testid="sidebar-chargeable-work"
                >
                  <span className="nav-icon">
                    <BadgeEuro size={16} strokeWidth={2} />
                  </span>
                  {t("nav.chargeable_work")}
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
              {/* RF-1 — aggregated message inbox. Visible to all roles;
                  the badge polls the unread-count endpoint. */}
              <NavLink to="/inbox" className={navClass} data-testid="sidebar-inbox">
                <span className="nav-icon">
                  <MessagesSquare size={16} strokeWidth={2} />
                </span>
                {t("nav.inbox")}
                <InboxNavBadge />
              </NavLink>
              {/* W-NAV1 — Extra Work becomes a PURE disclosure opener:
                  clicking it only expands/collapses, it navigates
                  nowhere. Sprint 155 §1 made the parent a link (label
                  navigates to /extra-work, a separate chevron folds the
                  children) specifically to avoid a click costing an
                  extra step to reach the list; that trade-off is gone
                  now that the list itself — "Extra Work Quote" — is a
                  child of the group, one click away the moment it opens
                  the group. A single control does both jobs a
                  `nav-parent-row` used to split across two elements.

                  Gates are UNCHANGED: the group and its Extra-Work
                  children share canAccessExtraWork (the same gate
                  ExtraWorkRoute applies to /extra-work/new and
                  /extra-work/request-quote); the two Recurring Work
                  entries (list + create form) keep canAccessPlannedWork,
                  because /planned-work and /planned-work/new share the
                  same PlannedWorkRoute guard in App.tsx.

                  Chargeable Work carries `!isCustomerUser`, copied from
                  the Tickets-side entry it doors onto — NOT because this
                  new entry needs a gate of its own, but because
                  `canAccessExtraWork` returns true for CUSTOMER_USER
                  (the melding-request surface) while the Tickets-side
                  entry is explicitly `!isCustomerUser`-gated. Nesting
                  this door under Extra Work without repeating that check
                  would have handed a CUSTOMER_USER a route they cannot
                  reach today — the exact regression "role gating exactly
                  as today" rules out. No route changed and no new role
                  logic — IA only. */}
              {canAccessExtraWork(me?.role) && (
                <>
                  <button
                    type="button"
                    className={
                      extraWorkChildActive ? "nav-item active" : "nav-item"
                    }
                    aria-expanded={extraWorkOpen}
                    aria-label={t(
                      extraWorkOpen
                        ? "nav.collapse_group"
                        : "nav.expand_group",
                      { group: t("nav.extra_work") },
                    )}
                    onClick={toggleExtraWork}
                    data-testid="sidebar-extra-work-toggle"
                  >
                    <span className="nav-icon">
                      <Receipt size={16} strokeWidth={2} />
                    </span>
                    <span style={{ flex: 1, textAlign: "left" }}>
                      {t("nav.extra_work")}
                    </span>
                    {extraWorkOpen ? (
                      <ChevronDown size={14} strokeWidth={2.4} />
                    ) : (
                      <ChevronRight size={14} strokeWidth={2.4} />
                    )}
                  </button>
                  {extraWorkOpen && (
                    <>
                      {/* W-NAV1 — the list page itself, now named for
                          what it is: the quotation side of the split
                          this list already draws internally (Quote &
                          price vs. Work started). `end` keeps this
                          entry — not the Forms links below — lit when
                          the operator is on /extra-work exactly. */}
                      <NavLink
                        to="/extra-work"
                        end
                        className={navChildClass}
                        data-testid="sidebar-extra-work-quote"
                      >
                        <span className="nav-icon">
                          <Receipt size={15} strokeWidth={2} />
                        </span>
                        {t("nav.extra_work_quote")}
                      </NavLink>
                      {/* W-NAV1 — the SAME route as the Tickets-side
                          "Chargeable work" entry (nav.chargeable_work,
                          reused verbatim). One page, two doors: this is
                          not a copy of ExtraWorkListPage or a new
                          component, just a second NavLink onto
                          /tickets/chargeable — gated `!isCustomerUser`
                          like that entry, since this dropdown's own
                          canAccessExtraWork gate admits CUSTOMER_USER
                          and the Tickets-side door does not. */}
                      {!isCustomerUser(me?.role) && (
                        <NavLink
                          to="/tickets/chargeable"
                          className={navChildClass}
                          data-testid="sidebar-extra-work-chargeable"
                        >
                          <span className="nav-icon">
                            <BadgeEuro size={15} strokeWidth={2} />
                          </span>
                          {t("nav.chargeable_work")}
                        </NavLink>
                      )}
                      {canAccessPlannedWork(me?.role) && (
                        <NavLink
                          to="/planned-work"
                          className={navChildClass}
                          data-testid="sidebar-planned-work"
                        >
                          <span className="nav-icon">
                            <CalendarClock size={15} strokeWidth={2} />
                          </span>
                          {t("nav.planned_work")}
                        </NavLink>
                      )}
                      {/* W-NAV1 — Forms: a labelled sub-group of create
                          routes, reusing the SAME two primitives the
                          customer-scoped sidebar already uses for a
                          labelled subsection (`nav-group-label` +
                          `nav-item-child`) rather than adding a new
                          indent level or a new CSS pattern. */}
                      <div
                        className="nav-group-label"
                        style={{ marginTop: 4 }}
                      >
                        {t("nav.forms_group")}
                      </div>
                      {/* Sprint 155 §1 — a nav entry for a route that
                          already existed. /extra-work/new was only
                          reachable from a button on the list page, so
                          the direct-order form had no home in the
                          menu. No new page and no new route. */}
                      <NavLink
                        to="/extra-work/new"
                        className={navChildClass}
                        data-testid="sidebar-extra-work-new"
                      >
                        <span className="nav-icon">
                          <FilePlus2 size={15} strokeWidth={2} />
                        </span>
                        {t("nav.extra_work_request")}
                      </NavLink>
                      <NavLink
                        to="/extra-work/request-quote"
                        className={navChildClass}
                        data-testid="sidebar-request-quote"
                      >
                        <span className="nav-icon">
                          <BadgeEuro size={15} strokeWidth={2} />
                        </span>
                        {t("nav.request_quote")}
                      </NavLink>
                      {/* W-NAV1 — the recurring-job CREATE form. Same
                          gate as the list entry above: /planned-work/new
                          shares PlannedWorkRoute with /planned-work in
                          App.tsx, so an actor who cannot see the list
                          cannot see its create form either. */}
                      {canAccessPlannedWork(me?.role) && (
                        <NavLink
                          to="/planned-work/new"
                          className={navChildClass}
                          data-testid="sidebar-recurring-work-new"
                        >
                          <span className="nav-icon">
                            <CalendarClock size={15} strokeWidth={2} />
                          </span>
                          {t("nav.recurring_work_new")}
                        </NavLink>
                      )}
                    </>
                  )}
                </>
              )}
              {/* Recurring Work is a child of the group above when the
                  actor can see Extra Work at all. An actor who has
                  canAccessPlannedWork but NOT canAccessExtraWork would
                  otherwise lose the entry entirely, so it stays a
                  top-level link for them — the gates are unchanged, the
                  nesting is not a gate. */}
              {!canAccessExtraWork(me?.role) &&
                canAccessPlannedWork(me?.role) && (
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
              {/* Sprint 171 §1 — the hours comparison has NO nav child.
                  It is a card on the Reports page that opens a modal,
                  which is what the owner asked for three times; a nav
                  CHILD is a sub-page as far as an operator is
                  concerned, and this entry is what he kept seeing. The
                  ROUTE stays, so an existing link still works. */}
              {canAccessBilling(me?.role) && (
                <NavLink to="/invoices" className={navClass}>
                  <span className="nav-icon">
                    <BadgeEuro size={16} strokeWidth={2} />
                  </span>
                  {t("nav.invoices")}
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
                  {/* Sprint 178 §1 — ONE place for every per-company
                      catalog. The old entry points (Hours, Contracts,
                      Services) all still work; this is where an operator
                      setting a company up can FIND them without already
                      knowing which of three screens each lives on. */}
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
                  {/* Sprint 152 — the Uren admin area. Gated on
                      `canManageTimesheets` (SA / CA), NOT on the admin
                      group alone: the group also admits nobody else
                      today, but the backend rule is its own and the
                      nav should mirror that rule, not a coincidence. */}
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
                  {/* Sprint 160 — contracts. The label itself
                      navigates (the Sprint 156 rule); BUILDING_MANAGER
                      gets its own entry below, outside this group, the
                      way the Employees directory does. The i18n key is
                      read from the `contracts` NAMESPACE rather than
                      `common`, so the module owns its own strings. */}
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
                  {/* Sprint W4-Q §2 — when the three time-driven
                      warnings fire, per company. Gated on
                      `canManageSlaWarnings` rather than on the admin
                      group: the group and the predicate admit the same
                      pair today, and the predicate is the one that
                      mirrors the backend's permission class, so it is
                      the one that must govern the link. The route uses
                      the SAME predicate (SlaWarningsRoute) so the nav
                      can never offer a screen the route refuses. */}
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

              {/* Sprint 160 — contracts, BM read-only entry. A BM does
                  not see the admin group above, so the link lives here
                  next to the Employees directory (the other BM-visible
                  provider surface). The backend narrows them to the
                  contracts covering their own buildings. */}
              {isBuildingManager(me?.role) && (
                <NavLink
                  to="/admin/contracts"
                  className={navClass}
                  data-testid="sidebar-contracts-bm"
                >
                  <span className="nav-icon">
                    <FileText size={16} strokeWidth={2} />
                  </span>
                  {t("nav.contracts", { ns: "contracts" })}
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
              {/* Invoicing Phase 5 — the customer "Facturen" surface: a
                  read-only list of the customer's own SENT invoices. */}
              {me?.role === "CUSTOMER_USER" && (
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
              )}
              {/* Sprint 126 — customer Documents. Gated on the module key
                  (via me.can_manage_documents — the effective-permissions
                  endpoint is provider-only, so the flag is surfaced on /me/). */}
              {me?.role === "CUSTOMER_USER" && me.can_manage_documents && (
                <NavLink
                  to="/my/documents"
                  className={navClass}
                  data-testid="sidebar-my-documents"
                >
                  <span className="nav-icon">
                    <Files size={16} strokeWidth={2} />
                  </span>
                  {t("documents.my_nav")}
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


