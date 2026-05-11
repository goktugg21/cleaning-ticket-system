import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { AppShell } from "../layout/AppShell";

/**
 * Sprint 23B — guard for `/admin/staff-assignment-requests`.
 *
 * Mirrors `AdminRoute` but ALSO allows `BUILDING_MANAGER`.
 * Building managers need this single admin queue to approve /
 * reject requests for their assigned buildings; they do not see
 * the rest of the admin nav group. STAFF and CUSTOMER_USER are
 * redirected to the dashboard — STAFF requests assignment via
 * the ticket-detail button instead.
 */
const REVIEWERS = new Set(["SUPER_ADMIN", "COMPANY_ADMIN", "BUILDING_MANAGER"]);

export function StaffRequestReviewRoute({ children }: { children: ReactNode }) {
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

  if (!REVIEWERS.has(me.role)) {
    return <Navigate to="/?admin_required=ok" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
