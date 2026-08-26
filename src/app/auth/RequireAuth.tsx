import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { useAuth } from "./AuthContext";
import { DEMO_MODE } from "../demo/config";
import { SessionExpiredState } from "../components/ui/session-expired-state";

// Gates the entire app: every route except /login and /setup-owner
// (see routes.tsx's ProtectedLayout) renders only for a signed-in human.
// This is a UI-layer decision, separate from the Operator Key superuser
// bypass, which remains an API-level concern (verify_operator_key /
// require_permission, server side) untouched by this component -- an
// SDK or curl call with the Operator Key header still works exactly as
// before; this only controls what the browser shows a human with no
// session.
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading, sessionExpired } = useAuth();
  const location = useLocation();

  // Checked before `loading`/`user`: a session that expired mid-use
  // already cleared `user` (AuthContext's handler), so without this
  // check RequireAuth would fall through to the plain "no session at
  // all" branch below and silently bounce to /login with no
  // explanation -- the exact dead-end UX this milestone fixes.
  if (sessionExpired && !DEMO_MODE) {
    return <SessionExpiredState />;
  }

  if (loading) {
    return (
      <div
        className="flex items-center justify-center h-full"
        style={{ color: "var(--pr-text-muted)", minHeight: "50vh" }}
      >
        Loading...
      </div>
    );
  }

  // The public demo build (VITE_PUBLIC_DEMO_MODE) is the one place this
  // gate is intentionally bypassed -- AuthContext supplies a canned demo
  // identity in that build, so `user` below is never null there. Every
  // other deployment (including production) enforces the real session
  // check underneath, same as always.
  if (DEMO_MODE) return <>{children}</>;

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}

export function RequirePermission({
  permission,
  children,
}: {
  permission: string;
  children: ReactNode;
}) {
  const { hasPermission } = useAuth();
  if (!hasPermission(permission)) {
    return (
      <div className="p-8" style={{ color: "var(--pr-text-muted)" }}>
        You don't have permission to view this page. Ask your Organisation Owner to change your role
        if you believe this is wrong.
      </div>
    );
  }
  return <>{children}</>;
}
