import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { canAccessBilling } from "../auth/permissions";
import { AppShell } from "../layout/AppShell";

// RF-13 (#106) — route guard for the "Facturen" invoices overview.
// Cloned from ReportsRoute: SA/CA/BM in, everyone else back to "/".
export function BillingRoute({ children }: { children: ReactNode }) {
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

  if (!canAccessBilling(me.role)) {
    return <Navigate to="/" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
