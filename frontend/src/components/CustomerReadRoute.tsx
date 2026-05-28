import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { canReadCustomerArea } from "../auth/permissions";
import { AppShell } from "../layout/AppShell";

/**
 * Route wrapper for the read-only BM customer surfaces.
 *
 * Admits the provider management trio (SA + COMPANY_ADMIN reach the
 * existing admin pages; BUILDING_MANAGER reaches the read-only BM
 * pages — the caller of this wrapper dispatches by role and renders
 * the BM-specific component). The wrapper itself is role-permissive;
 * read-only narrowing lives inside the BM page components.
 *
 * STAFF / CUSTOMER_USER / anonymous are bounced to the dashboard with
 * the `admin_required` query string for consistency with AdminRoute.
 */
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

  if (!canReadCustomerArea(me.role)) {
    return <Navigate to="/?admin_required=ok" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
