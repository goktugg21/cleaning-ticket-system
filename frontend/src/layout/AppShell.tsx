import type { ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

const ROLE_LABEL: Record<string, string> = {
  SUPER_ADMIN: "Super admin",
  COMPANY_ADMIN: "Company admin",
  BUILDING_MANAGER: "Manager",
  CUSTOMER_USER: "Customer",
};

function getInitials(value: string | undefined): string {
  if (!value) return "FM";

  const clean = value.split("@")[0].replace(/[._-]+/g, " ");
  const parts = clean.split(" ").filter(Boolean);

  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }

  return clean.slice(0, 2).toUpperCase();
}

function formatRole(role: string | undefined): string {
  if (!role) return "User";
  return ROLE_LABEL[role] ?? role.replaceAll("_", " ").toLowerCase();
}

function navClass({ isActive }: { isActive: boolean }) {
  return isActive ? "enterprise-nav-link active" : "enterprise-nav-link";
}

interface AppShellProps {
  children?: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const { me, logout } = useAuth();
  const navigate = useNavigate();

  const currentUser = me as
    | {
        full_name?: string;
        email?: string;
        role?: string;
      }
    | null
    | undefined;

  const userName = currentUser?.full_name?.trim() || currentUser?.email || "Facility user";
  const userEmail = currentUser?.email || "";
  const roleLabel = formatRole(currentUser?.role);

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="enterprise-shell">
      <aside className="enterprise-sidebar">
        <div className="enterprise-brand">
          <div className="brand-mark">FM</div>
          <div>
            <p className="brand-title">FacilityPro</p>
            <p className="brand-subtitle">Cleaning operations</p>
          </div>
        </div>

        <div className="enterprise-user-card">
          <div className="user-avatar">{getInitials(userName)}</div>
          <div>
            <p className="user-name">{userName}</p>
            <p className="user-meta">{roleLabel}</p>
          </div>
        </div>

        <nav className="enterprise-nav" aria-label="Main navigation">
          <NavLink to="/" end className={navClass}>
            <span className="nav-icon">▦</span>
            <span>Dashboard</span>
          </NavLink>

          <NavLink to="/tickets/new" className={navClass}>
            <span className="nav-icon">＋</span>
            <span>New ticket</span>
          </NavLink>

          <span className="enterprise-nav-link disabled">
            <span className="nav-icon">⌂</span>
            <span>Facilities</span>
          </span>

          <span className="enterprise-nav-link disabled">
            <span className="nav-icon">◇</span>
            <span>Assets</span>
          </span>

          <span className="enterprise-nav-link disabled">
            <span className="nav-icon">◌</span>
            <span>Reports</span>
          </span>

          <span className="enterprise-nav-link disabled">
            <span className="nav-icon">⚙</span>
            <span>Settings</span>
          </span>
        </nav>

        <div className="enterprise-sidebar-footer">
          <div>
            <p className="system-name">VERIDIAN</p>
            <p className="system-meta">Ops console v1.0</p>
          </div>
          <div className="system-status">
            <span></span>
            Online
          </div>
        </div>
      </aside>

      <div className="enterprise-workspace">
        <header className="enterprise-topbar">
          <div>
            <p className="topbar-kicker">Ticket Management</p>
            <h1>Facility service desk</h1>
          </div>

          <div className="topbar-actions">
            <div className="topbar-identity">
              <div>
                <p>{userName}</p>
                <span>{userEmail}</span>
              </div>
              <b>{roleLabel}</b>
            </div>

            <button type="button" className="button secondary compact" onClick={handleLogout}>
              Log out
            </button>
          </div>
        </header>

        <main className="enterprise-content">
          {children ?? <Outlet />}
        </main>
      </div>
    </div>
  );
}
