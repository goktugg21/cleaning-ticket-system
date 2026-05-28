// Extra Work route guard.
//
// Admits SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER, CUSTOMER_USER.
// STAFF is excluded: backend `extra_work.scoping.scope_extra_work_for`
// returns `.none()` for STAFF (the P0 staff-privacy revert,
// post-2026-05-20). STAFF still sees EW-spawned operational tickets
// through the normal ticket scope — `Ticket.extra_work_origin` surfaces
// the safe metadata subset on those tickets.
//
// Earlier Sprint 29 Batch 29.8 opened the SPA gate to STAFF in
// anticipation of a STAFF-facing EW surface. That landed before the
// staff-privacy revert closed the backend scope again; the SPA gate
// drifted out of sync. Closing it here so STAFF no longer lands on an
// empty page.
import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { canAccessExtraWork } from "../auth/permissions";
import { AppShell } from "../layout/AppShell";


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

  if (!canAccessExtraWork(me.role)) {
    return <Navigate to="/" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
