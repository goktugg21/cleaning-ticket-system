import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { canAccessAdminArea } from "../auth/permissions";
import { AppShell } from "../layout/AppShell";

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

  if (!canAccessAdminArea(me.role)) {
    // Mirror ProtectedRoute's redirect-on-deny pattern; the dashboard renders
    // an admin_required banner when this query string is present.
    return <Navigate to="/?admin_required=ok" replace />;
  }

  return <AppShell>{children}</AppShell>;
}
