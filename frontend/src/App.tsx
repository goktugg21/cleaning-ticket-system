import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useParams,
} from "react-router-dom";
import { Suspense, lazy } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { ToastProvider } from "./components/ToastProvider";
import { AdminRoute } from "./components/AdminRoute";
import { CustomerReadRoute } from "./components/CustomerReadRoute";
import { ExtraWorkRoute } from "./components/ExtraWorkRoute";
import { PlannedWorkRoute } from "./components/PlannedWorkRoute";
import { BillingRoute } from "./components/BillingRoute";
import { CustomerRoute } from "./components/CustomerRoute";
import { ReportsRoute } from "./components/ReportsRoute";
import { StaffRequestReviewRoute } from "./components/StaffRequestReviewRoute";
import { TimesheetsRoute } from "./components/TimesheetsRoute";
import { SlaWarningsRoute } from "./components/SlaWarningsRoute";
import { SuperAdminRoute } from "./components/SuperAdminRoute";
import { AppShell } from "./layout/AppShell";
import { HistoryRecorder } from "./hooks/useRecordHistory";
import { AcceptInvitationPage } from "./pages/AcceptInvitationPage";
import { CreateExtraWorkPage } from "./pages/CreateExtraWorkPage";
import { CreateTicketPage } from "./pages/CreateTicketPage";
import { NewWorkPage } from "./pages/NewWorkPage";
import { AgendaPage } from "./pages/AgendaPage";
import { DashboardPage } from "./pages/DashboardPage";
import { MyHoursPage } from "./pages/MyHoursPage";
import { ExtraWorkDetailPage } from "./pages/ExtraWorkDetailPage";
import { ExtraWorkListPage } from "./pages/ExtraWorkListPage";
import { PlannedWorkListPage } from "./pages/planned-work/PlannedWorkListPage";
import { RecurringJobDetailPage } from "./pages/planned-work/RecurringJobDetailPage";
import { RecurringJobFormPage } from "./pages/planned-work/RecurringJobFormPage";
import { LoginPage } from "./pages/LoginPage";
import { MyEmployeesPage } from "./pages/MyEmployeesPage";
import { MyInvoiceDetailPage } from "./pages/MyInvoiceDetailPage";
import { MyInvoicesPage } from "./pages/MyInvoicesPage";
import { MyMeldingenPage } from "./pages/MyMeldingenPage";
import { MyDocumentsPage } from "./pages/MyDocumentsPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { InboxPage } from "./pages/InboxPage";
import { ResetPasswordConfirmPage } from "./pages/ResetPasswordConfirmPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TicketDetailPage } from "./pages/TicketDetailPage";
import { AuditLogsAdminPage } from "./pages/admin/AuditLogsAdminPage";
import { BuildingDetailPage } from "./pages/admin/BuildingDetailPage";
import { BuildingFormPage } from "./pages/admin/BuildingFormPage";
import { BuildingsAdminPage } from "./pages/admin/BuildingsAdminPage";
import { BuildingManagerCustomerContactsPage } from "./pages/admin/BuildingManagerCustomerContactsPage";
import { BuildingManagerCustomerDetailPage } from "./pages/admin/BuildingManagerCustomerDetailPage";
import { BuildingManagerCustomersPage } from "./pages/admin/BuildingManagerCustomersPage";
import { CompaniesAdminPage } from "./pages/admin/CompaniesAdminPage";
import { CompanyDetailPage } from "./pages/admin/CompanyDetailPage";
import { CompanyFormPage } from "./pages/admin/CompanyFormPage";
import { CustomerContactsPage } from "./pages/admin/CustomerContactsPage";
import { CustomerFormPage } from "./pages/admin/CustomerFormPage";
import { EmployeesAdminPage } from "./pages/admin/EmployeesAdminPage";
import { CustomerPricingPage } from "./pages/admin/CustomerPricingPage";
import { CustomersAdminPage } from "./pages/admin/CustomersAdminPage";
// Sprint 28 Batch 13 — view-first refactor of the customer detail
// surface. `/admin/customers/:id` (Overview) and `/permissions` are
// now genuinely different pages instead of two routes onto the same
// `CustomerFormPage`. `CustomerFormPage` itself is preserved as the
// create flow (`/admin/customers/new`) and as the basics editor
// (`/admin/customers/:id/edit`).
import { CustomerBuildingsPage } from "./pages/admin/customer/CustomerBuildingsPage";
import { CustomerExtraWorkPage } from "./pages/admin/customer/CustomerExtraWorkPage";
// Sprint 162 §4 — one customer's contracts, beside their other sections.
import { CustomerContractsPage } from "./pages/admin/customer/CustomerContractsPage";
// Sprint 166 §4 — the SCREEN for the hours comparison. Sprint 165
// shipped the endpoint and no interface.
import { HoursComparisonPage } from "./pages/reports/HoursComparisonPage";
import { CustomerInvoicesPage } from "./pages/admin/customer/CustomerInvoicesPage";
import { CustomerReportsPage } from "./pages/admin/customer/CustomerReportsPage";
import { CustomerDocumentsPage } from "./pages/admin/customer/CustomerDocumentsPage";
import { CustomerLabelsPage } from "./pages/admin/customer/CustomerLabelsPage";
import { CustomerTicketsPage } from "./pages/admin/customer/CustomerTicketsPage";
import { CustomerOverviewPage } from "./pages/admin/customer/CustomerOverviewPage";
import { CustomerPermissionsPage } from "./pages/admin/customer/CustomerPermissionsPage";
import { CustomerSettingsPage } from "./pages/admin/customer/CustomerSettingsPage";
import { CustomerUsersPage } from "./pages/admin/customer/CustomerUsersPage";
import { InvitationsAdminPage } from "./pages/admin/InvitationsAdminPage";
import { HoursAdminPage } from "./pages/admin/HoursAdminPage";
// Sprint W4-Q §2 — per-company thresholds for the three time-driven
// SLA warnings. SA / CA only, on its own guard (see SlaWarningsRoute).
import { SlaWarningsAdminPage } from "./pages/admin/SlaWarningsAdminPage";
// Sprint 160 — contracts. Eagerly imported like the other admin
// pages; the module is small and the route is behind its own guard.
import { ContractsAdminPage } from "./pages/admin/contracts/ContractsAdminPage";
import { ContractDetailPage } from "./pages/admin/contracts/ContractDetailPage";
import { ContractsRoute } from "./components/ContractsRoute";
import { CatalogsAdminPage } from "./pages/admin/CatalogsAdminPage";
import { ServicesAdminPage } from "./pages/admin/ServicesAdminPage";
import { StaffAssignmentRequestsAdminPage } from "./pages/admin/StaffAssignmentRequestsAdminPage";
import { UserDetailPage } from "./pages/admin/UserDetailPage";
import { UserFormPage } from "./pages/admin/UserFormPage";
import { UsersAdminPage } from "./pages/admin/UsersAdminPage";

// ReportsPage is lazy-loaded. recharts 2.x does not tree-shake cleanly
// from its main entry, so route-level splitting is the lever available
// for keeping it out of the initial bundle.
//
// Sprint 152.2 recorded TWO corrections here. One of them has since
// expired and is removed rather than left to mislead in its turn:
// `HoursCharts` (the Uren Overview tab) was named as a second recharts
// consumer, and it no longer exists — every `recharts` import in the
// tree is now under `pages/reports/charts/`, reached only through
// ReportsPage. "ReportsPage is the only consumer" is true again.
//
// The other correction still stands, and was re-measured at W-PW1:
// the charting library does NOT land in a separate chunk. The build
// emits no recharts chunk — `ReportsPage-*.js` is ~51 kB, far too
// small to contain it, while `index-*.js` is ~2,754 kB. recharts is in
// the entry bundle whatever this lazy import does.
//
// Splitting it out for real would mean a deliberate `manualChunks`
// change measured against the real consumer set — its own piece of
// work. The lazy import stays because it still splits ReportsPage's
// OWN code.
const ReportsPage = lazy(() =>
  import("./pages/reports/ReportsPage").then((m) => ({ default: m.ReportsPage })),
);

// Invoicing Phase 4b — the provider "Facturen" page (due panel + invoice
// list) + the dedicated invoice-detail page. Split like ReportsPage to keep
// the initial bundle small.
const FacturenPage = lazy(() =>
  import("./pages/FacturenPage").then((m) => ({ default: m.FacturenPage })),
);
const InvoiceDetailPage = lazy(() =>
  import("./pages/InvoiceDetailPage").then((m) => ({
    default: m.InvoiceDetailPage,
  })),
);

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
  const { t } = useTranslation("common");

  if (loading) {
    return (
      <main className="auth-page">
        <p className="muted">{t("loading")}</p>
      </main>
    );
  }

  if (!me) {
    return <Navigate to="/login" replace />;
  }

  return <AppShell>{children}</AppShell>;
}

/**
 * Sprint 28 Batch 12 — role dispatcher for the three customer/contact
 * routes that admit BUILDING_MANAGER. For BM, render the read-only
 * variant; for admins, render the existing edit-capable admin page.
 *
 * The route wrapper `CustomerReadRoute` already enforces the role
 * wall (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER) — this
 * helper only picks the component.
 */
function ByRole({
  bm,
  admin,
}: {
  bm: ReactNode;
  admin: ReactNode;
}) {
  const { me } = useAuth();
  return <>{me?.role === "BUILDING_MANAGER" ? bm : admin}</>;
}

/**
 * IA 2026-06-25 — param-preserving redirect for the retired customer
 * content tabs (/meldingen -> /tickets?filter=meldingen,
 * /quote-requests -> /extra-work?filter=quote_requests). A plain
 * <Navigate to="literal"> cannot carry the :id param, hence the wrapper.
 */
function CustomerScopedRedirect({
  to,
  filter,
}: {
  to: string;
  filter: string;
}) {
  const { id } = useParams();
  return (
    <Navigate
      to={`/admin/customers/${id}/${to}?filter=${filter}`}
      replace
    />
  );
}

/**
 * FE-1 — the customer-scoped "Chargeable work" tab is retired the same
 * way (§D.2: the standalone name dies). Same param-preserving shape as
 * `CustomerScopedRedirect`, different search string: the ticket list's
 * own work filter carries the narrowing.
 */
function CustomerChargeableRedirect() {
  const { id } = useParams();
  return (
    <Navigate
      to={`/admin/customers/${id}/tickets?work=chargeable&status=ALL&period=all_time`}
      replace
    />
  );
}

/**
 * FE-1 (Addendum D §D.3.2) — Werkplanning is the STAFF landing page.
 * The dashboard route itself stays; only where a staff member LANDS
 * changes. Everyone else keeps the dashboard.
 */
function HomeRoute() {
  const { me } = useAuth();
  if (me?.role === "STAFF") {
    return <Navigate to="/agenda" replace />;
  }
  return <DashboardPage />;
}

/**
 * FE-1 (§D.3.2) — for STAFF the bell feed lives as a tab inside
 * Berichten; the standalone notifications page redirects there so the
 * topbar bell's "see all" and old deep links keep working. Every other
 * role keeps the standalone page.
 */
function NotificationsRoute() {
  const { me } = useAuth();
  if (me?.role === "STAFF") {
    return <Navigate to="/inbox?tab=notifications" replace />;
  }
  return <NotificationsPage />;
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <BrowserRouter>
          {/* W14 §3 — the app remembers where it has been, so a back
              link can go BACK to it instead of pushing a fourth entry
              onto the pile. One mount, above the routes, because every
              route change has to be seen. See lib/navHistory.ts. */}
          <HistoryRecorder />
          <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/password/reset/confirm"
            element={<ResetPasswordConfirmPage />}
          />
          <Route path="/invite/accept" element={<AcceptInvitationPage />} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <HomeRoute />
              </ProtectedRoute>
            }
          />
          {/* RF-3 (Ramazan 2026-06-23) — top-level Tickets LIST page.
              Reuses the dashboard's tickets surface (filters / presets /
              bulk-confirm / pagination) via the `variant` prop instead of a
              duplicated second implementation; New Ticket is reached from
              inside it. Same ProtectedRoute gate as the dashboard — scoping
              stays backend-side. Defined ABOVE /tickets/new and /tickets/:id
              (exact static path; RRv6 ranks it correctly regardless). */}
          <Route
            path="/tickets"
            element={
              <ProtectedRoute>
                <DashboardPage key="tickets-page" variant="tickets-page" />
              </ProtectedRoute>
            }
          />
          {/* FE-1 (Addendum D §D.2) — "Chargeable work" is dead as a
              name and as a page. The tickets born from a meerwerk ARE
              tickets; the work queue shows them behind its own work
              filter with the type pill saying where each came from. The
              old deep link keeps working: it lands on the queue with
              the meerwerk narrowing preselected and no status pin
              (`status=ALL` parses to "no status filter", which is what
              the old sub-page showed). Static path, so it must stay
              above /tickets/:id. */}
          <Route
            path="/tickets/chargeable"
            element={
              <Navigate to="/tickets?work=chargeable&status=ALL&period=all_time" replace />
            }
          />
          {/* W11 — ONE DOOR. Asks what happened and picks the record
              type from the answers, then hands off to one of the create
              routes below, all of which are unchanged and still work as
              deep links. `ProtectedRoute` only: which options the page
              offers is a role question it answers itself, and the route
              each answer lands on keeps its own guard. */}
          <Route
            path="/new"
            element={
              <ProtectedRoute>
                <NewWorkPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/tickets/new"
            element={
              <ProtectedRoute>
                <CreateTicketPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/tickets/:id"
            element={
              <ProtectedRoute>
                <TicketDetailPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <SettingsPage />
              </ProtectedRoute>
            }
          />
          {/* M1 B3 — in-app notifications page. Caller-scoped (the feed is
              recipient=request.user only), so a plain ProtectedRoute is
              sufficient; the topbar bell is the primary entry. */}
          <Route
            path="/notifications"
            element={
              <ProtectedRoute>
                <NotificationsRoute />
              </ProtectedRoute>
            }
          />
          {/* RF-1 — WhatsApp-style aggregated message inbox. Caller-scoped
              (the backend scopes threads to the viewer), so a plain
              ProtectedRoute is sufficient. Visible to provider + customer
              roles via the sidebar Berichten entry. */}
          <Route
            path="/inbox"
            element={
              <ProtectedRoute>
                <InboxPage />
              </ProtectedRoute>
            }
          />
          {/* Phase B — staff "My Work" agenda. Caller-scoped (my-slots is
              empty for non-assignees), so it sits behind the plain
              ProtectedRoute; the nav entry is gated to STAFF + provider
              management. */}
          <Route
            path="/agenda"
            element={
              <ProtectedRoute>
                <AgendaPage />
              </ProtectedRoute>
            }
          />
          {/* Employees directory — customer-facing entry point.
              Caller-scoped via me.customer_ids[0]; the backend
              re-gates the customer-employees endpoint, so a plain
              ProtectedRoute is sufficient. */}
          <Route
            path="/my/meldingen"
            element={
              <ProtectedRoute>
                <MyMeldingenPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/my/employees"
            element={
              <ProtectedRoute>
                <MyEmployeesPage />
              </ProtectedRoute>
            }
          />
          {/* Invoicing Phase 5 — the customer "Facturen" surface (read-only).
              CustomerRoute admits ONLY CUSTOMER_USER; everyone else bounces
              to "/". The backend also returns an empty scope for non-customers. */}
          <Route
            path="/my/facturen"
            element={
              <CustomerRoute>
                <MyInvoicesPage />
              </CustomerRoute>
            }
          />
          {/* Sprint 126 — customer-side Documents (CUSTOMER_USER only; the
              sidebar entry is additionally gated on can_manage_documents). */}
          <Route
            path="/my/documents"
            element={
              <CustomerRoute>
                <MyDocumentsPage />
              </CustomerRoute>
            }
          />
          <Route
            path="/my/facturen/:id"
            element={
              <CustomerRoute>
                <MyInvoiceDetailPage />
              </CustomerRoute>
            }
          />
          {/* Sprint 26C — Extra Work MVP. STAFF is excluded by the
              ExtraWorkRoute guard because the backend's
              scope_extra_work_for returns .none() for staff in this
              MVP (no staff-execution surface yet). */}
          <Route
            path="/extra-work"
            element={
              <ExtraWorkRoute>
                <ExtraWorkListPage />
              </ExtraWorkRoute>
            }
          />
          <Route
            path="/extra-work/new"
            element={
              <ExtraWorkRoute>
                <CreateExtraWorkPage />
              </ExtraWorkRoute>
            }
          />
          {/* M3 (SoT Addendum A.5) — dedicated quote-request page.
              Defined ABOVE /extra-work/:id; React Router v6 ranks
              static segments over dynamic params anyway, but the
              explicit ordering keeps the intent obvious. Same gate as
              /extra-work/new. */}
          <Route
            path="/extra-work/request-quote"
            element={
              <ExtraWorkRoute>
                <CreateExtraWorkPage intentMode="quote" />
              </ExtraWorkRoute>
            }
          />
          <Route
            path="/extra-work/:id"
            element={
              <ExtraWorkRoute>
                <ExtraWorkDetailPage />
              </ExtraWorkRoute>
            }
          />
          {/* Sprint 11/12 — provider-only planned / recurring work.
              PlannedWorkRoute gates STAFF + CUSTOMER_USER out (the
              backend viewsets 403 them on every route). */}
          <Route
            path="/planned-work"
            element={
              <PlannedWorkRoute>
                <PlannedWorkListPage />
              </PlannedWorkRoute>
            }
          />
          <Route
            path="/planned-work/new"
            element={
              <PlannedWorkRoute>
                <RecurringJobFormPage />
              </PlannedWorkRoute>
            }
          />
          <Route
            path="/planned-work/:id/edit"
            element={
              <PlannedWorkRoute>
                <RecurringJobFormPage />
              </PlannedWorkRoute>
            }
          />
          <Route
            path="/planned-work/:id"
            element={
              <PlannedWorkRoute>
                <RecurringJobDetailPage />
              </PlannedWorkRoute>
            }
          />
          <Route
            path="/admin/companies"
            element={
              <AdminRoute>
                <CompaniesAdminPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/companies/new"
            element={
              <AdminRoute>
                <CompanyFormPage />
              </AdminRoute>
            }
          />
          {/* Sprint 29 Batch 29.3 — view-first split. The
              `/admin/companies/:id` URL now renders a read-only detail
              page; an explicit role-gated Edit button on that page
              navigates to `/admin/companies/:id/edit`, which still
              mounts the existing `CompanyFormPage`. `/new` is unchanged
              and continues to use the form. */}
          <Route
            path="/admin/companies/:id/edit"
            element={
              <AdminRoute>
                <CompanyFormPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/companies/:id"
            element={
              <AdminRoute>
                <CompanyDetailPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/buildings"
            element={
              <AdminRoute>
                <BuildingsAdminPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/buildings/new"
            element={
              <AdminRoute>
                <BuildingFormPage />
              </AdminRoute>
            }
          />
          {/* Sprint 29 Batch 29.4 — view-first split mirroring 29.3
              (companies). `/admin/buildings/:id` now renders the
              read-only `BuildingDetailPage`; the explicit Edit button
              navigates to `/admin/buildings/:id/edit` which still
              mounts `BuildingFormPage`. `/new` is unchanged. */}
          <Route
            path="/admin/buildings/:id/edit"
            element={
              <AdminRoute>
                <BuildingFormPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/buildings/:id"
            element={
              <AdminRoute>
                <BuildingDetailPage />
              </AdminRoute>
            }
          />
          {/* Sprint 28 Batch 12 — BM read-only access on customer
              list + detail. Admins keep the existing
              `CustomersAdminPage` / `CustomerFormPage`; BM gets the
              new read-only variants. `/admin/customers/new` stays
              admin-only — BM has no create surface. */}
          <Route
            path="/admin/customers"
            element={
              <CustomerReadRoute>
                <ByRole
                  bm={<BuildingManagerCustomersPage />}
                  admin={<CustomersAdminPage />}
                />
              </CustomerReadRoute>
            }
          />
          <Route
            path="/admin/customers/new"
            element={
              <AdminRoute>
                <CustomerFormPage />
              </AdminRoute>
            }
          />
          {/* Sprint 28 Batch 13 — for admins, `/admin/customers/:id`
              is now the view-first `CustomerOverviewPage` (summary +
              quicklinks), NOT the legacy edit form. BM still gets
              `BuildingManagerCustomerDetailPage` (unchanged). The
              old edit form is reachable at `/admin/customers/:id/edit`
              and remains the create flow at `/admin/customers/new`. */}
          <Route
            path="/admin/customers/:id"
            element={
              <CustomerReadRoute>
                <ByRole
                  bm={<BuildingManagerCustomerDetailPage />}
                  admin={<CustomerOverviewPage />}
                />
              </CustomerReadRoute>
            }
          />
          <Route
            path="/admin/customers/:id/edit"
            element={
              <AdminRoute>
                <CustomerFormPage />
              </AdminRoute>
            }
          />
          {/* Sprint 28 Batch 13 — customer-scoped sub-routes get real
              view-first pages. The shared sidebar mode still keys on
              `/admin/customers/:id/*` (see `AppShell.tsx`); the only
              change here is each entry now points at a dedicated
              page instead of a placeholder or the legacy mega-form. */}
          <Route
            path="/admin/customers/:id/buildings"
            element={
              <AdminRoute>
                <CustomerBuildingsPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/customers/:id/users"
            element={
              <AdminRoute>
                <CustomerUsersPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/customers/:id/permissions"
            element={
              <AdminRoute>
                <CustomerPermissionsPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/customers/:id/extra-work"
            element={
              <AdminRoute>
                <CustomerExtraWorkPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/customers/:id/contracts"
            element={
              <AdminRoute>
                <CustomerContractsPage />
              </AdminRoute>
            }
          />
          {/* FE-1 — the customer-scoped "Chargeable work" tab is
              retired (§D.2); the deep link lands on the customer's own
              ticket list with the meerwerk narrowing preselected. */}
          <Route
            path="/admin/customers/:id/chargeable"
            element={<CustomerChargeableRedirect />}
          />
          <Route
            path="/admin/customers/:id/tickets"
            element={
              <AdminRoute>
                <CustomerTicketsPage />
              </AdminRoute>
            }
          />
          {/* #108 Part E — customer-scoped Invoices (view-only Facturen
              slice) + Reports (EW revenue, customer preset fixed). */}
          <Route
            path="/admin/customers/:id/invoices"
            element={
              <AdminRoute>
                <CustomerInvoicesPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/customers/:id/reports"
            element={
              <AdminRoute>
                <CustomerReportsPage />
              </AdminRoute>
            }
          />
          {/* Sprint 126 — customer Documents sub-tab (SA/CA only; the backend
              404s BM/STAFF and the sidebar entry is hidden for them). */}
          <Route
            path="/admin/customers/:id/documents"
            element={
              <AdminRoute>
                <CustomerDocumentsPage />
              </AdminRoute>
            }
          />
          {/* Sprint 128 — per-customer Extra Work label management. SA/CA
              write, BUILDING_MANAGER read (they hold the relabel action) —
              CustomerReadRoute admits the trio; the page gates its write
              controls on isProviderAdmin so a BM sees it read-only. */}
          <Route
            path="/admin/customers/:id/labels"
            element={
              <CustomerReadRoute>
                <CustomerLabelsPage />
              </CustomerReadRoute>
            }
          />
          {/* IA 2026-06-25 — the Meldingen and Quote-requests tabs merged
              into Tickets / Extra werk (filter chips). The retired routes
              redirect with the chip pre-applied so no deep link breaks. */}
          <Route
            path="/admin/customers/:id/meldingen"
            element={
              <CustomerScopedRedirect to="tickets" filter="meldingen" />
            }
          />
          <Route
            path="/admin/customers/:id/quote-requests"
            element={
              <CustomerScopedRedirect to="extra-work" filter="quote_requests" />
            }
          />
          {/* Sprint 28 Batch 12 — BM read-only contacts surface. */}
          <Route
            path="/admin/customers/:id/contacts"
            element={
              <CustomerReadRoute>
                <ByRole
                  bm={<BuildingManagerCustomerContactsPage />}
                  admin={<CustomerContactsPage />}
                />
              </CustomerReadRoute>
            }
          />
          {/* Sprint 28 Batch 5 — per-customer contract pricing. The
              real page; mirrors the Batch 4 contacts shape. */}
          <Route
            path="/admin/customers/:id/pricing"
            element={
              <AdminRoute>
                <CustomerPricingPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/customers/:id/settings"
            element={
              <AdminRoute>
                <CustomerSettingsPage />
              </AdminRoute>
            }
          />
          {/* Sprint 28 Batch 5 — provider-wide service catalog. Single
              page with two tabs (Services + Categories) to honour
              §3 "no data dumps". */}
          <Route
            path="/admin/services"
            element={
              <AdminRoute>
                <ServicesAdminPage />
              </AdminRoute>
            }
          />
          {/* Sprint 178 §1 — the Catalogs area. Same AdminRoute gate as
              every other per-company admin screen; the individual
              catalogs keep their own endpoint permissions unchanged. */}
          <Route
            path="/admin/catalogs"
            element={
              <AdminRoute>
                <CatalogsAdminPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/users"
            element={
              <AdminRoute>
                <UsersAdminPage />
              </AdminRoute>
            }
          />
          {/* Sprint 29 Batch 29.6 — view-first split mirroring 29.3
              (companies) and 29.4 (buildings). `/admin/users/:id` now
              renders the read-only `UserDetailPage`; the explicit Edit
              button navigates to `/admin/users/:id/edit` which still
              mounts `UserFormPage`. `/new` is unchanged. */}
          <Route
            path="/admin/users/:id/edit"
            element={
              <AdminRoute>
                <UserFormPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/users/:id"
            element={
              <AdminRoute>
                <UserDetailPage />
              </AdminRoute>
            }
          />
          {/* Employees directory — provider-wide. CustomerReadRoute
              admits SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER
              (BM read-only); STAFF / CUSTOMER_USER are bounced. */}
          <Route
            path="/admin/employees"
            element={
              <CustomerReadRoute>
                <EmployeesAdminPage />
              </CustomerReadRoute>
            }
          />
          <Route
            path="/admin/invitations"
            element={
              <AdminRoute>
                <InvitationsAdminPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/audit-logs"
            element={
              <SuperAdminRoute>
                <AuditLogsAdminPage />
              </SuperAdminRoute>
            }
          />
          {/* Sprint 23B — staff assignment request review queue.
              StaffRequestReviewRoute admits SUPER_ADMIN, COMPANY_ADMIN,
              AND BUILDING_MANAGER (the latter is invisible to the rest
              of the admin nav, but needs this single queue). */}
          <Route
            path="/admin/staff-assignment-requests"
            element={
              <StaffRequestReviewRoute>
                <StaffAssignmentRequestsAdminPage />
              </StaffRequestReviewRoute>
            }
          />
          {/* Sprint 152 — employee hours (urenregistratie). Two
              surfaces, two guards: `/my-hours` for every provider-side
              role, `/admin/hours` for SA / CA. Customer-side users are
              redirected by the guard and 403'd by every endpoint. */}
          <Route
            path="/my-hours"
            element={
              <TimesheetsRoute>
                <MyHoursPage />
              </TimesheetsRoute>
            }
          />
          <Route
            path="/admin/hours"
            element={
              <TimesheetsRoute manager>
                <HoursAdminPage />
              </TimesheetsRoute>
            }
          />
          {/* Sprint W4-Q §2 — the SLA warning thresholds. */}
          <Route
            path="/admin/sla-warnings"
            element={
              <SlaWarningsRoute>
                <SlaWarningsAdminPage />
              </SlaWarningsRoute>
            }
          />
          {/* Sprint 160 — contracts. Its own guard rather than
              AdminRoute: BUILDING_MANAGER is a READER here (narrowed
              server-side to the contracts covering their buildings) and
              AdminRoute would lock them out, while widening AdminRoute
              would hand them the whole admin group. */}
          <Route
            path="/admin/contracts"
            element={
              <ContractsRoute>
                <ContractsAdminPage />
              </ContractsRoute>
            }
          />
          <Route
            path="/admin/contracts/:contractId"
            element={
              <ContractsRoute>
                <ContractDetailPage />
              </ContractsRoute>
            }
          />
          <Route
            path="/reports"
            element={
              <ReportsRoute>
                <Suspense
                  fallback={
                    <div className="loading-bar">
                      <div className="loading-bar-fill" />
                    </div>
                  }
                >
                  <ReportsPage />
                </Suspense>
              </ReportsRoute>
            }
          />
          <Route
            path="/reports/hours-comparison"
            element={
              <ReportsRoute>
                <HoursComparisonPage />
              </ReportsRoute>
            }
          />
          <Route
            path="/invoices"
            element={
              <BillingRoute>
                <Suspense
                  fallback={
                    <div className="loading-bar">
                      <div className="loading-bar-fill" />
                    </div>
                  }
                >
                  <FacturenPage />
                </Suspense>
              </BillingRoute>
            }
          />
          <Route
            path="/invoices/:id"
            element={
              <BillingRoute>
                <Suspense
                  fallback={
                    <div className="loading-bar">
                      <div className="loading-bar-fill" />
                    </div>
                  }
                >
                  <InvoiceDetailPage />
                </Suspense>
              </BillingRoute>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  );
}


