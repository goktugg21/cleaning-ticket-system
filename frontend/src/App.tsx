import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Suspense, lazy } from "react";
import type { ReactNode } from "react";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { AdminRoute } from "./components/AdminRoute";
import { ExtraWorkRoute } from "./components/ExtraWorkRoute";
import { ReportsRoute } from "./components/ReportsRoute";
import { StaffRequestReviewRoute } from "./components/StaffRequestReviewRoute";
import { SuperAdminRoute } from "./components/SuperAdminRoute";
import { AppShell } from "./layout/AppShell";
import { AcceptInvitationPage } from "./pages/AcceptInvitationPage";
import { CreateExtraWorkPage } from "./pages/CreateExtraWorkPage";
import { CreateTicketPage } from "./pages/CreateTicketPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ExtraWorkDetailPage } from "./pages/ExtraWorkDetailPage";
import { ExtraWorkListPage } from "./pages/ExtraWorkListPage";
import { LoginPage } from "./pages/LoginPage";
import { ResetPasswordConfirmPage } from "./pages/ResetPasswordConfirmPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TicketDetailPage } from "./pages/TicketDetailPage";
import { AuditLogsAdminPage } from "./pages/admin/AuditLogsAdminPage";
import { BuildingFormPage } from "./pages/admin/BuildingFormPage";
import { BuildingsAdminPage } from "./pages/admin/BuildingsAdminPage";
import { CompaniesAdminPage } from "./pages/admin/CompaniesAdminPage";
import { CompanyFormPage } from "./pages/admin/CompanyFormPage";
import { CustomerFormPage } from "./pages/admin/CustomerFormPage";
import { CustomerSubPagePlaceholder } from "./pages/admin/CustomerSubPagePlaceholder";
import { CustomersAdminPage } from "./pages/admin/CustomersAdminPage";
import { InvitationsAdminPage } from "./pages/admin/InvitationsAdminPage";
import { StaffAssignmentRequestsAdminPage } from "./pages/admin/StaffAssignmentRequestsAdminPage";
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

export default function App() {
  return (
    <AuthProvider>
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
          <Route
            path="/extra-work/:id"
            element={
              <ExtraWorkRoute>
                <ExtraWorkDetailPage />
              </ExtraWorkRoute>
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
          <Route
            path="/admin/companies/:id"
            element={
              <AdminRoute>
                <CompanyFormPage />
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
          <Route
            path="/admin/buildings/:id"
            element={
              <AdminRoute>
                <BuildingFormPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/customers"
            element={
              <AdminRoute>
                <CustomersAdminPage />
              </AdminRoute>
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
          <Route
            path="/admin/customers/:id"
            element={
              <AdminRoute>
                <CustomerFormPage />
              </AdminRoute>
            }
          />
          {/* Sprint 28 Batch 3 — customer-scoped submenu routes.
              The sidebar (see `AppShell.tsx`) switches into a
              customer-scoped mode under `/admin/customers/:id/*`.
              Most sub-routes render `CustomerSubPagePlaceholder`
              (a "coming soon" empty state); they will be replaced
              by real sub-pages in later batches (Contacts — Batch
              4; cart UX — Batch 6; view-first refactor — Batch
              13). `permissions` is the deliberate exception:
              re-renders `CustomerFormPage` so the Sprint 27E
              permission editor stays reachable without touching
              the parent page. */}
          <Route
            path="/admin/customers/:id/buildings"
            element={
              <AdminRoute>
                <CustomerSubPagePlaceholder />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/customers/:id/users"
            element={
              <AdminRoute>
                <CustomerSubPagePlaceholder />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/customers/:id/permissions"
            element={
              <AdminRoute>
                <CustomerFormPage />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/customers/:id/extra-work"
            element={
              <AdminRoute>
                <CustomerSubPagePlaceholder />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/customers/:id/contacts"
            element={
              <AdminRoute>
                <CustomerSubPagePlaceholder />
              </AdminRoute>
            }
          />
          <Route
            path="/admin/customers/:id/settings"
            element={
              <AdminRoute>
                <CustomerSubPagePlaceholder />
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
          <Route
            path="/admin/users/:id"
            element={
              <AdminRoute>
                <UserFormPage />
              </AdminRoute>
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
    </AuthProvider>
  );
}
