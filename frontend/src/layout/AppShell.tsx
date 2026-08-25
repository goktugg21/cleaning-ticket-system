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

// The ADMIN nav group's own entries, in the order they render. Kept
// beside the group it describes: anything added to the group below is
// added here, and anything under `/admin` that is NOT in this list is by
// definition a standalone entry that must not open the group.
const ADMIN_GROUP_PATHS = [
  "/admin/companies",
  "/admin/buildings",
  "/admin/customers",
  "/admin/services",
  "/admin/catalogs",
  "/admin/hours",
  "/admin/contracts",
  "/admin/users",
  "/admin/employees",
  "/admin/invitations",
  "/admin/audit-logs",
  "/admin/sla-warnings",
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

  // W-NAV1 — the parent is a pure disclosure control (no route of its
  // own), so this test names the routes its CHILDREN own.
  //
  // W-NAV2 — `/extra-work` dropped OUT of it. That route left the group
  // to become the top-level "Quotes" entry, and a group that reads as
  // current while a top-level sibling is the lit row is the two-rows-in-
  // one-accent defect W-NAV1.4 removed. What is left is exactly the two
  // children: `/tickets/chargeable` (One-off work) and `/planned-work`
  // (Recurring work), each matched across its own subtree so the group
  // stays current on a detail page, not just the list.
  const extraWorkChildActive =
    location.pathname.startsWith("/planned-work") ||
    location.pathname.startsWith("/tickets/chargeable");

  // W-NAV2 — NOT a gate; a dead-control guard. Both children carry the
  // gates they always carried, and for a CUSTOMER_USER both are false
  // (One-off work is `!isCustomerUser`, Recurring work is
  // provider-management-only). Before W-NAV2 the group still held
  // Quotes and the Forms links for that role; now it would render an
  // opener that discloses an empty list. The role keeps the same one
  // destination it had — /extra-work — as the top-level Quotes entry.
  const extraWorkGroupHasChildren =
    !isCustomerUser(me?.role) || canAccessPlannedWork(me?.role);

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

  // W-NAV1.5 — ADMIN folds, exactly the way Extra Work does.
  //
  // Twelve admin entries were the longest run in the sidebar and every
  // one of them is a setup screen an operator visits occasionally, while
  // the operations entries above are the daily ones — so the list a
  // person needs least was taking the most room. Same three rules as
  // Extra Work: CLOSED on load, OPEN while the current route is inside
  // it, and the operator's own toggle winning over both until they
  // navigate away. Same one derived value, same reason (an override
  // carrying the path it was made on simply stops applying when the
  // pathname changes, so no effect has to reset it — a resync effect
  // here would be a synchronous setState in an effect body, which
  // CLAUDE.md forbids).
  //
  // Nothing is hidden by this: the group opens itself whenever the
  // current page is one of its own, so an operator can never be on an
  // admin screen with the group shut and no idea where they are.
  const [adminManual, setAdminManual] = useState<{
    path: string;
    open: boolean;
  } | null>(null);

  // Every route the group's entries point at -- LISTED, not matched by
  // an `/admin` prefix.
  //
  // The prefix was not the honest test of "inside ADMIN", because not
  // everything under `/admin` is in this group. `Staff requests` lives
  // at `/admin/staff-assignment-requests` and is rendered OUTSIDE the
  // group on purpose -- its own comment below says why: a BUILDING
  // MANAGER gets that one queue without seeing the rest of the admin
  // entries. Under the prefix, opening it swung the whole twelve-entry
  // group open and left the operator looking at a list they had not
  // asked for, with the entry they were actually on sitting outside it.
  //
  // Membership is now the group's OWN routes and nothing else, so a
  // future standalone entry under `/admin` cannot re-acquire this bug by
  // accident. A route matches when it IS one of these or is nested under
  // one (`/admin/contracts/12`); `/admin/customers/:id` swaps the
  // sidebar into customer-scoped mode and this branch does not render at
  // all, so it costs nothing here.
  const adminChildActive = ADMIN_GROUP_PATHS.some(
    (path) =>
      location.pathname === path ||
      location.pathname.startsWith(`${path}/`),
  );

  const adminOpen =
    adminManual && adminManual.path === location.pathname
      ? adminManual.open
      : adminChildActive;

  const toggleAdmin = () =>
    setAdminManual({ path: location.pathname, open: !adminOpen });

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
                  end
                  className={navClass}
                  data-testid="sidebar-tickets"
                >
                  <span className="nav-icon">
                    <Ticket size={16} strokeWidth={2} />
                  </span>
                  {t("nav.tickets")}
                </NavLink>
              )}
              {/* W-NAV1.1 — the Chargeable work entry that stood here as
                  a child of Tickets is GONE. Sprint 181 §5 put it here;
                  W-NAV1 then gave the Extra Work folder a second door
                  onto the same route, and two entries for one page in
                  one sidebar is one too many. The Extra Work folder's
                  entry is the one door now.

                  The ROUTE is untouched — /tickets/chargeable still
                  resolves, the folder entry points at it, and so does
                  the customer-scoped submenu's own Chargeable work
                  entry. Only this nav row went. */}
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
              {/* W-NAV2 — the owner's final Extra Work structure. The
                  folder holds the two ways work actually happens:
                  ONE-OFF (a single chargeable job) and RECURRING (a
                  standing schedule). Everything else that used to hang
                  here has moved out:

                  - "Extra Work Quote" (/extra-work) is now the
                    top-level "Quotes" entry above Reports. Quoting is
                    its own activity, not a sub-item of extra work, and
                    it is the one entry a CUSTOMER_USER has here.
                  - The FORMS sub-group is gone entirely. All three
                    create routes keep their own doors on the pages
                    they belong to (verified before deleting):
                    /extra-work/new and /extra-work/request-quote from
                    ExtraWorkListPage's create chooser, /planned-work/new
                    from PlannedWorkListPage's "New" button and the same
                    chooser — plus all three from /new (NewWorkPage).
                    No route changed; only nav rows went.

                  GATES ARE UNCHANGED. The group keeps canAccessExtraWork
                  and its children keep the gates they carried as rows:
                  One-off work is `!isCustomerUser` (copied from the
                  Tickets-side entry it doors onto, because
                  canAccessExtraWork admits CUSTOMER_USER and that route
                  does not) and Recurring work is canAccessPlannedWork.

                  `extraWorkGroupHasChildren` is the one new thing, and
                  it is not a gate: with Quotes and Forms gone, a
                  CUSTOMER_USER's children both evaluate false, and
                  rendering an opener that discloses nothing is a dead
                  control. The role sees exactly what it saw before —
                  /extra-work, now called Quotes and one click closer. */}
              {canAccessExtraWork(me?.role) && extraWorkGroupHasChildren && (
                <>
                  {/* W-NAV1.4 — the group row is a `nav-item` like every
                      other sidebar row, plus TWO modifiers, and no inline
                      styles: `nav-item-group` carries what a <button>
                      needs that an <a> does not (full width, left-aligned
                      text), and `nav-item-group-current` is the
                      "the page you are on lives in here" state.

                      That second state is deliberately NOT `.active`.
                      `.active` is what a lit nav ENTRY looks like, and
                      while the group is open its own child carries it —
                      two rows in the same accent, one of which is not a
                      destination, is the thing that read wrong. The
                      group modifier tints the label only: it says
                      "in here" without competing with the one row that
                      says "here". */}
                  <button
                    type="button"
                    className={
                      extraWorkChildActive
                        ? "nav-item nav-item-group nav-item-group-current"
                        : "nav-item nav-item-group"
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
                    <span className="nav-item-group-label">
                      {t("nav.extra_work")}
                    </span>
                    <span className="nav-item-group-chevron">
                      {extraWorkOpen ? (
                        <ChevronDown size={14} strokeWidth={2.4} />
                      ) : (
                        <ChevronRight size={14} strokeWidth={2.4} />
                      )}
                    </span>
                  </button>
                  {extraWorkOpen && (
                    <>
                      {/* W-NAV2 — the SAME route the Tickets-side
                          "Chargeable work" entry used to own, renamed to
                          what the owner calls it. One page, one door.
                          No `end`: /tickets/chargeable has no nav
                          sibling under it, and the Tickets entry above
                          carries `end`, so this row is the only one that
                          can light on this path. */}
                      {!isCustomerUser(me?.role) && (
                        <NavLink
                          to="/tickets/chargeable"
                          className={navChildClass}
                          data-testid="sidebar-extra-work-chargeable"
                        >
                          <span className="nav-icon">
                            <BadgeEuro size={16} strokeWidth={2} />
                          </span>
                          {t("nav.one_off_work")}
                        </NavLink>
                      )}
                      {/* W-NAV2 — `end` DROPPED with the Forms group.
                          It was there to stop this row lighting while
                          the operator sat on the /planned-work/new row
                          below it; that row is gone, nothing else in the
                          sidebar matches /planned-work/*, so the entry
                          now stays lit across its own subtree (the
                          create form and every job detail page) instead
                          of leaving the sidebar dark. Still exactly one
                          lit row. */}
                      {canAccessPlannedWork(me?.role) && (
                        <NavLink
                          to="/planned-work"
                          className={navChildClass}
                          data-testid="sidebar-planned-work"
                        >
                          <span className="nav-icon">
                            <CalendarClock size={16} strokeWidth={2} />
                          </span>
                          {t("nav.planned_work")}
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
              {/* W-NAV2 — Quotes: the SAME page /extra-work always was
                  (ExtraWorkListPage), promoted out of the Extra Work
                  folder to a top-level entry directly above Reports,
                  and named for what it does. No new route, no new page,
                  no new gate: canAccessExtraWork is the gate the
                  "Extra Work Quote" child carried and the same gate
                  ExtraWorkRoute applies to the route itself.

                  No `end`. The child it replaced had one, to stop it
                  lighting while the operator sat on the Forms rows for
                  /extra-work/new and /extra-work/request-quote. Those
                  rows are gone and nothing else in the sidebar matches
                  /extra-work/*, so Quotes now stays lit across its own
                  subtree — the two create forms and every request
                  detail page — which is where the operator actually is
                  when they got there from this list. Still exactly one
                  lit row: the Extra Work group no longer counts
                  /extra-work as a child (see `extraWorkChildActive`). */}
              {canAccessExtraWork(me?.role) && (
                <NavLink
                  to="/extra-work"
                  className={navClass}
                  data-testid="sidebar-quotes"
                >
                  <span className="nav-icon">
                    <Receipt size={16} strokeWidth={2} />
                  </span>
                  {t("nav.quotes")}
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
                  {/* W-NAV1.5 — ADMIN is a disclosure now, and the row
                      that opens it replaces the plain `nav-group-label`
                      that used to head this run. It reuses the SAME
                      primitives the Extra Work group uses — `nav-item`
                      plus the two group modifiers, the same chevron
                      pair, the same aria-expanded and the same two
                      existing expand/collapse labels — rather than
                      inventing a second kind of foldable section.

                      The gate is UNCHANGED: `canAccessAdminArea` still
                      decides whether any of this exists, and every
                      entry inside keeps whatever gate it already had.
                      Folding is not a gate. */}
                  <button
                    type="button"
                    className={
                      adminChildActive
                        ? "nav-item nav-item-group nav-item-group-current"
                        : "nav-item nav-item-group"
                    }
                    aria-expanded={adminOpen}
                    aria-label={t(
                      adminOpen ? "nav.collapse_group" : "nav.expand_group",
                      { group: t("nav.admin_group") },
                    )}
                    onClick={toggleAdmin}
                    data-testid="sidebar-admin-toggle"
                  >
                    <span className="nav-icon">
                      <ShieldCheck size={16} strokeWidth={2} />
                    </span>
                    <span className="nav-item-group-label">
                      {t("nav.admin_group")}
                    </span>
                    <span className="nav-item-group-chevron">
                      {adminOpen ? (
                        <ChevronDown size={14} strokeWidth={2.4} />
                      ) : (
                        <ChevronRight size={14} strokeWidth={2.4} />
                      )}
                    </span>
                  </button>
                  {adminOpen && (
                    <>
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


