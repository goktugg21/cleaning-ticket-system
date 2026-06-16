import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Suspense, lazy } from "react";
import type { ReactNode } from "react";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { ToastProvider } from "./components/ToastProvider";
import { AdminRoute } from "./components/AdminRoute";
import { CustomerReadRoute } from "./components/CustomerReadRoute";
import { ExtraWorkRoute } from "./components/ExtraWorkRoute";
import { PlannedWorkRoute } from "./components/PlannedWorkRoute";
import { ReportsRoute } from "./components/ReportsRoute";
import { StaffRequestReviewRoute } from "./components/StaffRequestReviewRoute";
import { SuperAdminRoute } from "./components/SuperAdminRoute";
import { AppShell } from "./layout/AppShell";
import { AcceptInvitationPage } from "./pages/AcceptInvitationPage";
import { CreateExtraWorkPage } from "./pages/CreateExtraWorkPage";
import { CreateTicketPage } from "./pages/CreateTicketPage";
import { AgendaPage } from "./pages/AgendaPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ExtraWorkDetailPage } from "./pages/ExtraWorkDetailPage";
import { ExtraWorkListPage } from "./pages/ExtraWorkListPage";
import { PlannedWorkListPage } from "./pages/planned-work/PlannedWorkListPage";
import { RecurringJobDetailPage } from "./pages/planned-work/RecurringJobDetailPage";
import { RecurringJobFormPage } from "./pages/planned-work/RecurringJobFormPage";
import { LoginPage } from "./pages/LoginPage";
import { MyEmployeesPage } from "./pages/MyEmployeesPage";
import { NotificationsPage } from "./pages/NotificationsPage";
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
import { CustomerOverviewPage } from "./pages/admin/customer/CustomerOverviewPage";
import { CustomerPermissionsPage } from "./pages/admin/customer/CustomerPermissionsPage";
import { CustomerSettingsPage } from "./pages/admin/customer/CustomerSettingsPage";
import { CustomerUsersPage } from "./pages/admin/customer/CustomerUsersPage";
import { InvitationsAdminPage } from "./pages/admin/InvitationsAdminPage";
import { ServicesAdminPage } from "./pages/admin/ServicesAdminPage";
import { StaffAssignmentRequestsAdminPage } from "./pages/admin/StaffAssignmentRequestsAdminPage";
import { UserDetailPage } from "./pages/admin/UserDetailPage";
import { UserFormPage } from "./pages/admin/UserFormPage";
import { UsersAdminPage } from "./pages/admin/UsersAdminPage";

// ReportsPage is the only consumer of recharts. Lazy-loaded so the
// charting library lands in a separate chunk and the non-reports bundle
// stays at the pre-Reports baseline. recharts 2.x does not tree-shake
// cleanly from its main entry; route-level code splitting is the only
// way to keep the initial bundle small.
const ReportsPage = lazy(() =>
  import("./pages/reports/ReportsPage").then((m) => ({ default: m.ReportsPage })),
);

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();

  if (loading) {
    return (
      <main className="auth-page">
        <p className="muted">Loading…</p>
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

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <BrowserRouter>
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
                <DashboardPage />
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
                <NotificationsPage />
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
            path="/my/employees"
            element={
              <ProtectedRoute>
                <MyEmployeesPage />
              </ProtectedRoute>
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
          <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  );
}


