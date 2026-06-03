import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { canAccessPlannedWork } from "../auth/permissions";
import { AppShell } from "../layout/AppShell";

// Sprint 11/12 frontend — route guard for the provider-only planned-work
// surface. Mirrors `ReportsRoute`: it reuses the existing
// `canAccessPlannedWork` (= isProviderManagementRole) predicate and adds
// no new client-side permission logic. The backend viewsets remain the
// security boundary (403 STAFF / CUSTOMER_USER on every route).
export function PlannedWorkRoute({ children }: { children: ReactNode }) {
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

  if (!canAccessPlannedWork(me.role)) {
    return <Navigate to="/" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
