import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { authApi } from "./authApi";
import { setSessionExpiredHandler } from "../lib/apiClient";
import { clearSessionToken, getSessionToken, setSessionToken } from "../lib/session";
import type { CurrentUser } from "./types";

interface AuthContextValue {
  user: CurrentUser | null;
  // Undetermined yet (checking an existing token on first load), distinct
  // from "checked, and there is no user" -- avoids a login-page flash on
  // every reload of an already-signed-in session.
  loading: boolean;
  // True the moment any in-flight request discovers the session token is
  // no longer valid (apiClient's global 401 handler). Distinct from
  // `user === null`, which also covers "never signed in."
  sessionExpired: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  hasPermission: (permission: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [sessionExpired, setSessionExpired] = useState(false);

  useEffect(() => {
    setSessionExpiredHandler(() => {
      setUser((current) => (current === null ? current : null));
      setSessionExpired(true);
    });
    return () => setSessionExpiredHandler(null);
  }, []);

  useEffect(() => {
    if (!getSessionToken()) {
      setLoading(false);
      return;
    }
    authApi
      .me()
      .then((current) => setUser(current))
      .catch(() => clearSessionToken())
      .finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string) {
    const response = await authApi.login(email, password);
    setSessionToken(response.token);
    setUser(response.user);
    setSessionExpired(false);
  }

  async function logout() {
    try {
      await authApi.logout();
    } finally {
      clearSessionToken();
      setUser(null);
      setSessionExpired(false);
    }
  }

  function hasPermission(permission: string): boolean {
    return user?.permissions.includes(permission) ?? false;
  }

  return (
    <AuthContext.Provider value={{ user, loading, sessionExpired, login, logout, hasPermission }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
