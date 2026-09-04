import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { canAccessAdminArea } from "../auth/permissions";
import { AppShell } from "../layout/AppShell";

export function AdminRoute({ children }: { children: ReactNode }) {
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

  if (!canAccessAdminArea(me.role)) {
    // Mirror ProtectedRoute's redirect-on-deny pattern; the dashboard renders
    // an admin_required banner when this query string is present.
    return <Navigate to="/?admin_required=ok" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
