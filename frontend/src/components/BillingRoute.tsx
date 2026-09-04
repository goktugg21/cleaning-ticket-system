import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { canAccessBilling } from "../auth/permissions";
import { AppShell } from "../layout/AppShell";

// RF-13 (#106) — route guard for the "Facturen" invoices overview.
// Cloned from ReportsRoute: SA/CA/BM in, everyone else back to "/".
export function BillingRoute({ children }: { children: ReactNode }) {
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

  if (!canAccessBilling(me.role)) {
    return <Navigate to="/" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
