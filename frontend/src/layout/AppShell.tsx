import type { ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  BarChart3,
  Building2,
  LayoutGrid,
  PlusCircle,
  Settings,
  Star,
} from "lucide-react";
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
  return isActive ? "nav-item active" : "nav-item";
}

interface AppShellProps {
  children?: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const { me, logout } = useAuth();
  const navigate = useNavigate();

  const userName =
    me?.full_name?.trim() || me?.email || "Facility user";
  const userEmail = me?.email || "";
  const roleLabel = formatRole(me?.role);

  function handleLogout() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-icon">FM</div>
          <div>
            <div className="brand-name">FacilityPro</div>
            <div className="brand-tag">Cleaning operations</div>
          </div>
        </div>

        <div className="sidebar-user">
          <div className="user-avatar-block">{getInitials(userName)}</div>
          <div style={{ minWidth: 0 }}>
            <div className="user-name">{userName}</div>
            <div className="user-role">{roleLabel}</div>
          </div>
        </div>

        <nav className="sidebar-nav" aria-label="Main navigation">
          <div className="nav-group-label">Operations</div>
          <NavLink to="/" end className={navClass}>
            <span className="nav-icon">
              <LayoutGrid size={16} strokeWidth={2} />
            </span>
            Dashboard
          </NavLink>
          <NavLink to="/tickets/new" className={navClass}>
            <span className="nav-icon">
              <PlusCircle size={16} strokeWidth={2} />
            </span>
            New ticket
          </NavLink>

          <div className="nav-group-label" style={{ marginTop: 8 }}>
            Portfolio
          </div>
          <span className="nav-item disabled">
            <span className="nav-icon">
              <Building2 size={16} strokeWidth={2} />
            </span>
            Facilities
          </span>
          <span className="nav-item disabled">
            <span className="nav-icon">
              <Star size={16} strokeWidth={2} />
            </span>
            Assets
          </span>

          <div className="nav-group-label" style={{ marginTop: 8 }}>
            Analytics
          </div>
          <span className="nav-item disabled">
            <span className="nav-icon">
              <BarChart3 size={16} strokeWidth={2} />
            </span>
            Reports
          </span>

          <div className="nav-group-label" style={{ marginTop: 8 }}>
            System
          </div>
          <span className="nav-item disabled">
            <span className="nav-icon">
              <Settings size={16} strokeWidth={2} />
            </span>
            Settings
          </span>
        </nav>

        <div className="sidebar-footer">
          <div>
            <div className="footer-sys-name">VERIDIAN</div>
            <div className="footer-sys-ver">Ops Console v1.0</div>
          </div>
          <div className="status-dot">Online</div>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-left">
            <span className="topbar-kicker">Ticket Management</span>
            <span className="topbar-title">Facility service desk</span>
          </div>
          <div className="topbar-right">
            <div className="topbar-identity">
              <div className="identity-text">
                <div className="identity-name">{userName}</div>
                {userEmail && (
                  <div className="identity-email">{userEmail}</div>
                )}
              </div>
              <span className="identity-role">{roleLabel}</span>
            </div>
            <div className="topbar-divider" />
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={handleLogout}
            >
              Sign out
            </button>
          </div>
        </header>

        <main className="page-canvas">{children ?? <Outlet />}</main>
      </div>
    </div>
  );
}
