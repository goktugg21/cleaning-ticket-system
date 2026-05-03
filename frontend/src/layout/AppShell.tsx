import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

interface AppShellProps {
  children: ReactNode;
}

const ROLE_LABEL: Record<string, string> = {
  SUPER_ADMIN: "Super admin",
  COMPANY_ADMIN: "Company admin",
  BUILDING_MANAGER: "Building manager",
  CUSTOMER_USER: "Customer",
};

export function AppShell({ children }: AppShellProps) {
  const { me, logout } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">CT</span>
          <div>
            <p className="brand-title">Cleaning Tickets</p>
            <p className="brand-sub">Operations console</p>
          </div>
        </div>

        <nav className="nav">
          <NavLink to="/" end className="nav-link">
            <span aria-hidden>▣</span> Tickets
          </NavLink>
          <NavLink to="/tickets/new" className="nav-link">
            <span aria-hidden>＋</span> New ticket
          </NavLink>
        </nav>

        <div className="sidebar-footer">
          <p className="muted small">Need help? Contact your admin.</p>
        </div>
      </aside>

      <div className="shell-main">
        <header className="appbar">
          <div>
            <p className="eyebrow">Logged in</p>
            <p className="appbar-user">
              <strong>{me?.full_name?.trim() || me?.email}</strong>
              <span className="role-pill">{ROLE_LABEL[me?.role ?? ""] ?? me?.role}</span>
            </p>
            {me?.full_name?.trim() && me.email !== me.full_name && (
              <p className="muted small">{me.email}</p>
            )}
          </div>
          <button className="secondary" onClick={handleLogout}>
            Log out
          </button>
        </header>

        <main className="content">{children}</main>
      </div>
    </div>
  );
}
