import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { AdminRoute } from "./components/AdminRoute";
import { AppShell } from "./layout/AppShell";
import { AcceptInvitationPage } from "./pages/AcceptInvitationPage";
import { CreateTicketPage } from "./pages/CreateTicketPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { ResetPasswordConfirmPage } from "./pages/ResetPasswordConfirmPage";
import { TicketDetailPage } from "./pages/TicketDetailPage";
import { BuildingFormPage } from "./pages/admin/BuildingFormPage";
import { BuildingsAdminPage } from "./pages/admin/BuildingsAdminPage";
import { CompaniesAdminPage } from "./pages/admin/CompaniesAdminPage";
import { CompanyFormPage } from "./pages/admin/CompanyFormPage";
import { CustomerFormPage } from "./pages/admin/CustomerFormPage";
import { CustomersAdminPage } from "./pages/admin/CustomersAdminPage";
import { InvitationsAdminPage } from "./pages/admin/InvitationsAdminPage";
import { UserFormPage } from "./pages/admin/UserFormPage";
import { UsersAdminPage } from "./pages/admin/UsersAdminPage";

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
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
