// Sprint 26C — Extra Work route guard.
//
// Admits SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER, and
// CUSTOMER_USER. STAFF is excluded because the backend's
// `scope_extra_work_for` returns `.none()` for staff in this MVP
// (no staff-execution surface yet), so the page would render an
// empty list. We mirror the backend gate in the SPA so staff
// users don't see a link that leads to nothing actionable.
import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { AppShell } from "../layout/AppShell";


const ALLOWED_ROLES = new Set([
  "SUPER_ADMIN",
  "COMPANY_ADMIN",
  "BUILDING_MANAGER",
  "CUSTOMER_USER",
]);


export function ExtraWorkRoute({ children }: { children: ReactNode }) {
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

  if (!ALLOWED_ROLES.has(me.role)) {
    return <Navigate to="/" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
