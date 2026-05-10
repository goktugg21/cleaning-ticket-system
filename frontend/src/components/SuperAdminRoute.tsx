import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { AppShell } from "../layout/AppShell";

/**
 * Sprint 18 — guard for SUPER_ADMIN-only SPA pages (`/admin/audit-logs`).
 *
 * Distinct from `AdminRoute`, which permits both SUPER_ADMIN and
 * COMPANY_ADMIN. The audit-log feed is super-admin-only on the
 * backend (`audit/views.py::AuditLogViewSet` uses `IsSuperAdmin`),
 * and we mirror that gate here so company-admins do not even reach
 * the page (which would otherwise render a permission-denied error
 * on every request).
 *
 * Mirrors the redirect-on-deny pattern from `AdminRoute`: anonymous
 * → /login, wrong role → /?admin_required=ok (the dashboard reads
 * the query string and shows a banner).
 */
export function SuperAdminRoute({ children }: { children: ReactNode }) {
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

  if (me.role !== "SUPER_ADMIN") {
    return <Navigate to="/?admin_required=ok" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
