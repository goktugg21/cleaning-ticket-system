import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { canAccessTimesheets, canManageTimesheets } from "../auth/permissions";
import { AppShell } from "../layout/AppShell";

/**
 * Sprint 152 — route guard for the employee-hours module. Same shape as
 * `ReportsRoute` / `PlannedWorkRoute`.
 *
 * `manager` splits the two surfaces: the own-hours page admits every
 * provider-side role, the admin area admits SA / CA only. One component
 * with a flag rather than two near-identical files, because the pair
 * must stay in step with the backend's two permission classes and a
 * copy is what drifts.
 *
 * The frontend is not the boundary — every timesheets endpoint enforces
 * the same split independently. This only stops a customer-side user
 * seeing a route that would 403, and keeps the module invisible to them.
 *
 * Sprint 152.1 — because the non-manager branch reads
 * `canAccessTimesheets`, which no longer admits SUPER_ADMIN, an SA
 * landing on `/my-hours` is redirected to `/`. That is deliberate: the
 * page cannot work for them (see the predicate's comment), so leaving
 * the route reachable would only trade one dead end for another.
 */
export function TimesheetsRoute({
  children,
  manager = false,
}: {
  children: ReactNode;
  manager?: boolean;
}) {
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

  const allowed = manager
    ? canManageTimesheets(me.role)
    : canAccessTimesheets(me.role);
  if (!allowed) {
    // P-14 (findings) — the SAME landing AdminRoute gives: a silent
    // bounce to the dashboard read as "the link is broken"; the query
    // string puts the admins-only banner on the landing.
    return <Navigate to="/?admin_required=ok" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
