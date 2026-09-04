import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../auth/AuthContext";
import { canManageSlaWarnings } from "../auth/permissions";
import { AppShell } from "../layout/AppShell";

/**
 * Sprint W4-Q §2 — route guard for `/admin/sla-warnings`.
 *
 * Its own guard rather than `AdminRoute`, even though the two admit the
 * same pair of roles today. The point is that ONE predicate
 * (`canManageSlaWarnings`) governs both the sidebar entry and the route,
 * so the nav can never offer a screen the route refuses, or the reverse.
 * Pointing the route at `AdminRoute` and the link at the predicate would
 * be two independently-maintained consumers of one rule, which is the
 * shape that hid the `documents` permission group for three sprints.
 *
 * The frontend is not the boundary: `sla.views_thresholds` enforces the
 * same rule with `IsSuperAdminOrCompanyAdmin` and narrows a
 * COMPANY_ADMIN to their own companies on top of it. This only keeps a
 * customer-side user from seeing a route that would 403 — and keeps the
 * provider's internal operating rhythm invisible to them.
 */
export function SlaWarningsRoute({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth();
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

  if (!canManageSlaWarnings(me.role)) {
    // P-14 (findings) — say why, like AdminRoute does.
    return <Navigate to="/?admin_required=ok" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
