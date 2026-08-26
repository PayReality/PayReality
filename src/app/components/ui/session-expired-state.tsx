import { useLocation, useNavigate } from "react-router";
import { ShieldAlert } from "lucide-react";
import { Button } from "./button";
import { Card } from "./card";

/**
 * Product Experience Remediation Milestone 1: the single, centrally-
 * triggered recovery state for an expired session -- rendered by
 * RequireAuth the moment AuthContext's `sessionExpired` flag flips true
 * (apiClient.setSessionExpiredHandler), replacing the previous pattern
 * of each page showing its own dead-end "your session has expired...
 * Retry" text (Retry re-sent the same expired token and could only
 * ever fail again). Deliberately not an automatic redirect: the app
 * stays on the current route so the user can see where they were
 * before choosing to sign in again, and "Sign in again" carries them
 * to /login with the current location remembered, so a successful
 * login returns them here (LoginPage already reads `location.state.from`
 * for this).
 */
export function SessionExpiredState() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <div className="flex items-center justify-center min-h-screen p-6" style={{ backgroundColor: "var(--pr-bg-primary)" }}>
      <Card className="w-full max-w-sm text-center" padding={28}>
        <div
          className="mx-auto mb-4 flex items-center justify-center"
          style={{ width: 40, height: 40, borderRadius: 10, backgroundColor: "rgba(245,158,11,0.1)" }}
        >
          <ShieldAlert className="w-5 h-5" style={{ color: "var(--pr-warning-amber)" }} aria-hidden="true" />
        </div>
        <h1 className="text-sm font-semibold mb-1.5" style={{ color: "var(--pr-text-primary)" }}>
          Your session has expired
        </h1>
        <p className="text-xs mb-5" style={{ color: "var(--pr-text-muted)" }}>
          For your security, you've been signed out. Sign in again to pick up where you left off.
        </p>
        <Button
          className="w-full"
          onClick={() => navigate("/login", { replace: true, state: { from: location.pathname } })}
        >
          Sign in again
        </Button>
      </Card>
    </div>
  );
}
