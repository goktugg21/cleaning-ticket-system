// Sprint 26C — Extra Work route guard.
//
// Admits SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER, and
// CUSTOMER_USER. STAFF was originally excluded because the backend's
// `scope_extra_work_for` returned `.none()` for staff in this MVP
// (no staff-execution surface yet), so the page would render an
// empty list.
//
// Sprint 29 Batch 29.8 opened the backend scope for STAFF (they can
// now see EWs at buildings where they have BuildingStaffVisibility,
// mirroring the ticket scope). Sprint 29 Batch 29.8.5 lifts the SPA
// gate in parallel so STAFF users no longer get redirected to the
// dashboard when they navigate to /extra-work.
import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { AppShell } from "../layout/AppShell";


const ALLOWED_ROLES = new Set([
  "SUPER_ADMIN",
  "COMPANY_ADMIN",
  "BUILDING_MANAGER",
  "CUSTOMER_USER",
  "STAFF",
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
