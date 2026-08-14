import { useId, useState } from "react";
import { Link, useNavigate } from "react-router";
import { useAuth } from "./AuthContext";
import { authApi } from "./authApi";
import { ApiError } from "../live/apiClient";
import { getOperatorKey, setOperatorKey } from "../live/operatorKey";
import { Button } from "../components/ui/button";

function describeSetupError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 401) return "That Operator Key is incorrect.";
    if (e.status === 409) return "Another account already uses that email.";
    if (e.status === 422) return "Password must be at least 8 characters.";
    if (e.status === 400) return "This deployment doesn't recognize its own organization yet. Contact whoever manages the platform.";
    if (
      e.status === 503 &&
      typeof e.body === "object" &&
      e.body !== null &&
      "detail" in e.body &&
      e.body.detail === "no_organization_bootstrapped"
    ) {
      return "No organization has been created on this deployment yet, so there's no Owner role to claim.";
    }
    if (e.status === 503) return "No Operator Key is configured on this deployment yet.";
  }
  return "Couldn't set up the account. Check your connection and try again.";
}

// The Organisation Owner role is established automatically on first boot
// (RBAC.md) -- the organisation's own deployment already designates it,
// the same way an org chart designates a role before a specific person
// is hired into it. But the Owner account's password only ever existed
// as a one-time line in the deploy log, with no way for a real person to
// actually retrieve it or create their own login. This page is that
// missing path: the Operator Key lets whoever holds it securely claim
// the Owner role the organisation already established, with their own
// email and password. The key is a secure way to exercise that
// pre-existing authority, not the source of it.
export function SetupOwnerPage() {
  const formId = useId();
  const { login } = useAuth();
  const navigate = useNavigate();

  const [operatorKey, setOperatorKeyInput] = useState(getOperatorKey());
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (password !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    setSubmitting(true);
    try {
      await authApi.setupOwner(email, password, operatorKey);
      setOperatorKey(operatorKey);
      await login(email, password);
      navigate("/organization", { replace: true });
    } catch (err) {
      setError(describeSetupError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="flex items-center justify-center min-h-screen p-6"
      style={{ backgroundColor: "var(--pr-bg-primary)" }}
    >
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2.5 mb-8 justify-center">
          <img src="/payreality-logo.png" alt="" className="w-8 h-8 rounded-lg flex-shrink-0" />
          <h1 className="text-base font-semibold" style={{ color: "var(--pr-text-primary)" }}>
            Pay<span style={{ color: "var(--pr-warning-amber)" }}>Reality</span>
          </h1>
        </div>

        <div
          className="p-6 rounded-xl"
          style={{ backgroundColor: "var(--pr-bg-card)", border: "1px solid var(--pr-overlay-05)" }}
        >
          <h2 className="text-sm font-medium mb-1" style={{ color: "var(--pr-text-primary)" }}>
            Set up your account
          </h2>
          <p className="text-xs mb-5" style={{ color: "var(--pr-text-muted)" }}>
            The Operator Key is the same credential the sidebar's "Operator Key" field asks for.
            Your organisation already established the Owner role when this platform was deployed;
            holding the Operator Key lets you securely claim that existing role with your own
            email and password. It doesn't grant you anything the deployment didn't already
            authorise.
          </p>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor={`${formId}-operator-key`}
                className="block text-xs font-medium mb-1.5"
                style={{ color: "var(--pr-text-muted)" }}
              >
                Operator Key
              </label>
              <input
                id={`${formId}-operator-key`}
                type="password"
                required
                value={operatorKey}
                onChange={(e) => setOperatorKeyInput(e.target.value)}
                className="w-full text-sm px-3 py-2 rounded-lg"
                style={{ backgroundColor: "var(--pr-input-bg)", color: "var(--pr-text-primary)", border: "1px solid var(--pr-overlay-08)" }}
              />
            </div>
            <div>
              <label
                htmlFor={`${formId}-email`}
                className="block text-xs font-medium mb-1.5"
                style={{ color: "var(--pr-text-muted)" }}
              >
                Your email
              </label>
              <input
                id={`${formId}-email`}
                type="email"
                required
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full text-sm px-3 py-2 rounded-lg"
                style={{ backgroundColor: "var(--pr-input-bg)", color: "var(--pr-text-primary)", border: "1px solid var(--pr-overlay-08)" }}
              />
            </div>
            <div>
              <label
                htmlFor={`${formId}-password`}
                className="block text-xs font-medium mb-1.5"
                style={{ color: "var(--pr-text-muted)" }}
              >
                New password
              </label>
              <input
                id={`${formId}-password`}
                type="password"
                required
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full text-sm px-3 py-2 rounded-lg"
                style={{ backgroundColor: "var(--pr-input-bg)", color: "var(--pr-text-primary)", border: "1px solid var(--pr-overlay-08)" }}
              />
            </div>
            <div>
              <label
                htmlFor={`${formId}-confirm-password`}
                className="block text-xs font-medium mb-1.5"
                style={{ color: "var(--pr-text-muted)" }}
              >
                Confirm password
              </label>
              <input
                id={`${formId}-confirm-password`}
                type="password"
                required
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full text-sm px-3 py-2 rounded-lg"
                style={{ backgroundColor: "var(--pr-input-bg)", color: "var(--pr-text-primary)", border: "1px solid var(--pr-overlay-08)" }}
              />
            </div>

            {error && (
              <p role="alert" className="text-xs" style={{ color: "var(--pr-critical-red)" }}>{error}</p>
            )}

            <Button type="submit" disabled={submitting} pending={submitting} className="w-full">
              {submitting ? "Setting up..." : "Set up account"}
            </Button>
          </form>

          <p className="text-xs mt-4 text-center" style={{ color: "var(--pr-text-muted)" }}>
            Already have an account?{" "}
            <Link to="/login" style={{ color: "var(--pr-authority-blue)" }}>Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}
