import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { AppShell } from "../layout/AppShell";

const STAFF_ROLES = new Set(["SUPER_ADMIN", "COMPANY_ADMIN"]);

export function AdminRoute({ children }: { children: ReactNode }) {
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

  if (!STAFF_ROLES.has(me.role)) {
    // Mirror ProtectedRoute's redirect-on-deny pattern; the dashboard renders
    // an admin_required banner when this query string is present.
    return <Navigate to="/?admin_required=ok" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
