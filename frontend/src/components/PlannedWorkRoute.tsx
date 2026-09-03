import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
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
  // P-15 (P-14's S4 finding) — the first paint speaks the app's
  // language; "Loading…" was the one hardcoded English word before a
  // Dutch page.
  const { t } = useTranslation("common");

  if (loading) {
    return (
      <main className="auth-page">
        <p className="muted">{t("loading")}</p>
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
