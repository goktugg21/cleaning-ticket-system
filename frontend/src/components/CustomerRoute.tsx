import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { isCustomerUser } from "../auth/permissions";
import { AppShell } from "../layout/AppShell";

// Phase 5 — route guard for the customer "Facturen" surface. Only a
// CUSTOMER_USER may enter; a provider / staff / anyone else bounces to "/"
// (the backend also returns an empty scope for them). Mirrors BillingRoute.
export function CustomerRoute({ children }: { children: ReactNode }) {
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

  if (!isCustomerUser(me.role)) {
    return <Navigate to="/" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
