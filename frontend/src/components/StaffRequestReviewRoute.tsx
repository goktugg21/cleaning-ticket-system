import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { canAccessStaffRequestReview } from "../auth/permissions";
import { AppShell } from "../layout/AppShell";

/**
 * Guard for `/admin/staff-assignment-requests`.
 *
 * Admits SUPER_ADMIN, COMPANY_ADMIN, AND BUILDING_MANAGER. BM gets
 * this one queue (their own buildings only — backend queryset gate)
 * even though they do not see the rest of the admin nav group.
 * STAFF and CUSTOMER_USER are bounced — STAFF requests assignment
 * via the ticket-detail button instead.
 */
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

  if (!canAccessStaffRequestReview(me.role)) {
    return <Navigate to="/?admin_required=ok" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
