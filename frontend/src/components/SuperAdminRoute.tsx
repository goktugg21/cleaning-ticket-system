import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { canAccessAuditLogs } from "../auth/permissions";
import { AppShell } from "../layout/AppShell";

/**
 * Guard for SUPER_ADMIN-only SPA pages (`/admin/audit-logs`).
 *
 * Distinct from `AdminRoute`, which permits both SUPER_ADMIN and
 * COMPANY_ADMIN. The audit-log feed is super-admin-only on the backend
 * (`audit/views.py::AuditLogViewSet` uses `IsSuperAdmin`); the gate
 * here mirrors `canAccessAuditLogs` so company admins do not reach the
 * page (which would 403 on every request).
 */
export function SuperAdminRoute({ children }: { children: ReactNode }) {
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

  if (!canAccessAuditLogs(me.role)) {
    return <Navigate to="/?admin_required=ok" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
