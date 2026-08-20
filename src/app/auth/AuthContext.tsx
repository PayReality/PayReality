import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { authApi } from "./authApi";
import { clearSessionToken, getSessionToken, setSessionToken } from "../live/sessionToken";
import { identify, reset as resetAnalytics } from "../services/analytics";
import { DEMO_MODE } from "../demo/config";
import { demoCurrentUser } from "../demo/fixtures/users";
import { ensureDemoAgentKeysSeeded } from "../demo/seedAgentKeys";
import type { CurrentUser } from "./types";

interface AuthContextValue {
  user: CurrentUser | null;
  // Undetermined yet (checking an existing session token on first load),
  // distinct from "checked, and there is no user" -- RequireAuth needs
  // this distinction to avoid a login-page flash on every page load.
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  hasPermission: (permission: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  // The public demo build never has a real session -- it signs every
  // visitor in as the same canned identity immediately, skipping the
  // token check and /v1/auth/me round-trip below entirely.
  const [user, setUser] = useState<CurrentUser | null>(DEMO_MODE ? demoCurrentUser : null);
  const [loading, setLoading] = useState(!DEMO_MODE);

  // Runs once per app mount, unconditionally in demo builds -- see
  // seedAgentKeys.ts for why the demo's own fixture agents need this
  // before LiveTestIntent.tsx's agent picker can show any of them.
  useEffect(() => {
    if (DEMO_MODE) ensureDemoAgentKeysSeeded();
  }, []);

  useEffect(() => {
    if (DEMO_MODE) return;
    if (!getSessionToken()) {
      setLoading(false);
      return;
    }
    authApi
      .me()
      .then((current) => {
        setUser(current);
        // Restoring an existing session on reload identifies the same way a
        // fresh login does -- Mixpanel should know who this is regardless of
        // whether the session token came from this page load or an earlier one.
        identify({ id: current.id, role: current.role, organization_id: current.organization_id });
      })
      .catch(() => clearSessionToken())
      .finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string) {
    const response = await authApi.login(email, password);
    setSessionToken(response.token);
    setUser(response.user);
    identify({ id: response.user.id, role: response.user.role, organization_id: response.user.organization_id });
  }

  async function logout() {
    try {
      await authApi.logout();
    } finally {
      clearSessionToken();
      setUser(null);
      resetAnalytics();
    }
  }

  function hasPermission(permission: string): boolean {
    return user?.permissions.includes(permission) ?? false;
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, hasPermission }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
