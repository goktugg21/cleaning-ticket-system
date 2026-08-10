import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { canAccessContracts } from "../auth/permissions";
import { AppShell } from "../layout/AppShell";

/**
 * Sprint 160 — route guard for the contracts module. Same shape as
 * `TimesheetsRoute` / `ReportsRoute`.
 *
 * Its own guard rather than `AdminRoute`, because the two answer
 * different questions: `AdminRoute` gates on the provider-admin area
 * (SA / CA), and contracts additionally admit BUILDING_MANAGER as a
 * READER — a BM sees the contracts covering the buildings they manage.
 * Reusing `AdminRoute` would lock them out of a surface the backend
 * grants them, and widening `AdminRoute` would hand them the whole
 * admin group.
 *
 * The frontend is not the boundary — every contracts endpoint enforces
 * the same rule independently, and STAFF and every customer-side role
 * are 403'd there whatever this component does. This only stops a role
 * seeing a route that would fail, and keeps the module invisible to the
 * customer side.
 */
export function ContractsRoute({ children }: { children: ReactNode }) {
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

  if (!canAccessContracts(me.role)) {
    return <Navigate to="/" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
