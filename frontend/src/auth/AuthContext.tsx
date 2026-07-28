import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  api,
  clearAuthTokens,
  getRefreshToken,
  logoutRefreshToken,
  onSessionExpired,
  setAuthTokens,
} from "../api/client";
import type { Me } from "../api/types";

interface AuthContextValue {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  reloadMe: () => Promise<void>;
  // Sprint 129 — true after a mid-session refresh failed (involuntary
  // logout). LoginPage reads it to explain why the user is back at login.
  sessionExpired: boolean;
}

interface TokenResponse {
  access: string;
  refresh: string;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [sessionExpired, setSessionExpired] = useState(false);

  const reloadMe = useCallback(async () => {
    const response = await api.get<Me>("/auth/me/");
    setMe(response.data);
  }, []);

  const logout = useCallback(() => {
    const refresh = getRefreshToken();
    if (refresh) {
      logoutRefreshToken(refresh).catch(() => {
        // Local logout must succeed even if the server already rejected the token.
      });
    }
    clearAuthTokens();
    delete api.defaults.headers.common.Authorization;
    setMe(null);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const response = await api.post<TokenResponse>("/auth/token/", { email, password });
    setAuthTokens(response.data.access, response.data.refresh);
    api.defaults.headers.common.Authorization = `Bearer ${response.data.access}`;
    setSessionExpired(false); // a fresh login clears any stale expiry notice
    await reloadMe();
  }, [reloadMe]);

  // Sprint 129 — react to an involuntary logout (a mid-session token refresh
  // that failed, see api/client.ts). Clear the auth state so the route
  // guards send the user to /login, and flag it so LoginPage explains why.
  // Registered ONCE and cleaned up on unmount. Idempotent, since concurrent
  // 401s can fire the handler more than once. It does NOT navigate itself, so
  // it cannot loop when the user is already on /login — there `me` is already
  // null and no guard redirects.
  useEffect(() => {
    return onSessionExpired(() => {
      delete api.defaults.headers.common.Authorization;
      setMe(null);
      setSessionExpired(true);
    });
  }, []);

  useEffect(() => {
    const token = localStorage.getItem("accessToken");
    if (!token) {
      setLoading(false);
      return;
    }

    api.defaults.headers.common.Authorization = `Bearer ${token}`;

    reloadMe()
      .catch(() => logout())
      .finally(() => setLoading(false));
  }, [logout, reloadMe]);

  const value = useMemo(
    () => ({ me, loading, login, logout, reloadMe, sessionExpired }),
    [me, loading, login, logout, reloadMe, sessionExpired]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
