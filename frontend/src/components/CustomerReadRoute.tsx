import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { AppShell } from "../layout/AppShell";

/**
 * Sprint 28 Batch 12 — route wrapper for the read-only BM customer
 * surfaces.
 *
 * Admits SUPER_ADMIN + COMPANY_ADMIN (who reach the existing admin
 * pages) AND BUILDING_MANAGER (who reach the read-only BM pages —
 * the caller of this wrapper dispatches by role and renders the
 * BM-specific component). The wrapper itself is role-permissive; the
 * read-only narrowing lives inside the BM page components.
 *
 * STAFF / CUSTOMER_USER / anonymous are bounced to the dashboard
 * with the same `admin_required` query string the AdminRoute uses,
 * keeping the redirect-on-deny pattern consistent.
 */
const CUSTOMER_READ_ROLES = new Set([
  "SUPER_ADMIN",
  "COMPANY_ADMIN",
  "BUILDING_MANAGER",
]);

export function CustomerReadRoute({ children }: { children: ReactNode }) {
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

  if (!CUSTOMER_READ_ROLES.has(me.role)) {
    return <Navigate to="/?admin_required=ok" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
