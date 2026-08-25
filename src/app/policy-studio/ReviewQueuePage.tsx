import { useEffect, useState } from "react";
import { Link } from "react-router";
import { policyStudioApi } from "./api";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Skeleton } from "../components/ui/skeleton";
import type { RuntimePolicy } from "./types";
import { describeApiError } from "../live/format";
import { describePolicy } from "./describePolicy";
import { useAuth } from "../auth/AuthContext";
import { ROLE_LABELS } from "../auth/types";

// The real decision-rights model for this screen, mirrored from
// server/app/domain/rbac/permissions.py's ROLE_PERMISSIONS (Reviewer,
// Governance Administrator, and Organisation Owner are the only roles
// granted authority.review). Shown here so decision rights are visible
// up front rather than discovered only after a failed approve/reject
// call (Platform Audit, Governance/Policy Studio section).
const APPROVAL_ROLE_LABEL = "Reviewer, Governance Administrator, or Organisation Owner";

export function ReviewQueuePage() {
  const { user, hasPermission } = useAuth();
  const [pending, setPending] = useState<RuntimePolicy[] | null>(null);
  const [approver, setApprover] = useState("");
  const [rejectReason, setRejectReason] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<{ policyKey: string; action: "approve" | "reject" } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Only disable when we positively know the signed-in user lacks the
  // permission -- with no session (Operator Key bypass still active),
  // stay permissive rather than guessing.
  const lacksPermission = !!user && !hasPermission("authority.review");

  function load() {
    setLoadError(null);
    policyStudioApi.list("pending_review").then(setPending).catch((e) => setLoadError(describeApiError(e, "Loading the review queue")));
  }

  useEffect(load, []);

  // Session identity replaces free-text reviewer entry (Stage I.6): a
  // logged-in user's name is already known server-side (Stage D records
  // approver_user_id/reviewer_user_id from the session regardless of what
  // string this field sends), so there's no reason to ask them to type
  // it. The Operator-Key-only path (no session) keeps free text.
  useEffect(() => {
    if (user) setApprover(user.name);
  }, [user]);

  async function handleApprove(policyKey: string) {
    if (!approver.trim()) {
      setMessage("Enter your name before approving.");
      return;
    }
    try {
      await policyStudioApi.approve(policyKey, approver);
      load();
    } catch (e) {
      setMessage(describeApiError(e, "Approve"));
    }
  }

  async function handleReject(policyKey: string) {
    const reason = rejectReason[policyKey];
    if (!approver.trim() || !reason?.trim()) {
      setMessage("Enter your name and a rejection reason.");
      return;
    }
    try {
      await policyStudioApi.reject(policyKey, approver, reason);
      load();
    } catch (e) {
      setMessage(describeApiError(e, "Reject"));
    }
  }

  return (
    <div className="p-8 max-w-2xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <h1 className="mb-2" style={{ color: "var(--pr-text-primary)" }}>Approvals</h1>
      <p style={{ color: "var(--pr-text-muted)", fontSize: 12, marginBottom: 4 }}>
        {user ? "Recorded as the reviewer for each rule below." : "Enter your name to record who reviewed each rule below."}
      </p>
      <p style={{ color: "var(--pr-text-disabled)", fontSize: 12, marginBottom: 16 }}>
        Requires: {APPROVAL_ROLE_LABEL}.
        {lacksPermission && (
          <span style={{ color: "var(--pr-warning-amber)" }}> Your role ({user ? ROLE_LABELS[user.role] ?? user.role : ""}) doesn't include this permission.</span>
        )}
      </p>

      <label htmlFor="reviewer-name" className={user ? undefined : "sr-only"}>
        {user ? "Reviewer (you)" : "Your name"}
      </label>
      <input
        id="reviewer-name"
        placeholder="Your name"
        value={approver}
        onChange={(e) => setApprover(e.target.value)}
        readOnly={!!user}
        style={{
          backgroundColor: user ? "var(--pr-bg-primary)" : "var(--pr-bg-hover)",
          border: "1px solid var(--pr-overlay-10)",
          color: user ? "var(--pr-text-muted)" : "var(--pr-text-primary)",
          borderRadius: 6,
          padding: "6px 8px",
          fontSize: 13,
          marginBottom: 16,
          width: 260,
        }}
      />

      {message && (
        <p role="alert" style={{ color: "var(--pr-warning-amber)", marginBottom: 12 }}>{message}</p>
      )}

      {loadError && (
        <Alert severity="warning" style={{ marginBottom: 12 }}>
          <div className="flex items-center gap-3">
            <span>{loadError}</span>
            <Button variant="ghost" size="sm" onClick={load}>Retry</Button>
          </div>
        </Alert>
      )}

      {!pending && !loadError && (
        <div className="space-y-3">
          <Skeleton height={80} radius={12} />
          <Skeleton height={80} radius={12} />
        </div>
      )}

      {pending?.length === 0 && <p style={{ color: "var(--pr-text-muted)" }}>Nothing pending review.</p>}

      {pending?.map((p) => (
        <Card key={p.policy_key} padding={16} style={{ marginBottom: 12 }}>
          <div className="flex items-center justify-between gap-3 mb-2">
            <Link to={`/governance/${p.policy_key}`} style={{ color: "var(--pr-authority-blue)" }}>
              {p.name} (v{p.version})
            </Link>
            <div className="flex gap-2" style={{ flexShrink: 0 }}>
              {confirming?.policyKey === p.policy_key ? (
                <>
                  <button
                    onClick={async () => {
                      setSubmitting(true);
                      try {
                        if (confirming.action === "approve") await handleApprove(p.policy_key);
                        else await handleReject(p.policy_key);
                      } finally {
                        setSubmitting(false);
                        setConfirming(null);
                      }
                    }}
                    disabled={submitting}
                    className="rounded-lg border disabled:opacity-60"
                    style={{
                      color: confirming.action === "approve" ? "var(--pr-trust-green)" : "var(--pr-critical-red)",
                      fontSize: 13,
                      padding: "6px 12px",
                      borderColor: confirming.action === "approve" ? "rgba(34,197,94,0.3)" : "rgba(239,68,68,0.3)",
                    }}
                  >
                    {submitting ? "Working..." : `Confirm ${confirming.action}`}
                  </button>
                  <button
                    onClick={() => setConfirming(null)}
                    disabled={submitting}
                    style={{ color: "var(--pr-text-muted)", fontSize: 13, padding: "6px 12px" }}
                  >
                    Cancel
                  </button>
                </>
              ) : (
                <>
                  <button
                    onClick={() => setConfirming({ policyKey: p.policy_key, action: "approve" })}
                    disabled={lacksPermission}
                    title={lacksPermission ? `Requires ${APPROVAL_ROLE_LABEL}` : undefined}
                    className="rounded-lg border"
                    style={{
                      color: lacksPermission ? "var(--pr-text-disabled)" : "var(--pr-trust-green)",
                      fontSize: 13,
                      padding: "6px 12px",
                      borderColor: lacksPermission ? "var(--pr-overlay-10)" : "rgba(34,197,94,0.3)",
                      opacity: lacksPermission ? 0.6 : 1,
                    }}
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => setConfirming({ policyKey: p.policy_key, action: "reject" })}
                    disabled={lacksPermission}
                    title={lacksPermission ? `Requires ${APPROVAL_ROLE_LABEL}` : undefined}
                    className="rounded-lg border"
                    style={{
                      color: lacksPermission ? "var(--pr-text-disabled)" : "var(--pr-critical-red)",
                      fontSize: 13,
                      padding: "6px 12px",
                      borderColor: lacksPermission ? "var(--pr-overlay-10)" : "rgba(239,68,68,0.3)",
                      opacity: lacksPermission ? 0.6 : 1,
                    }}
                  >
                    Reject
                  </button>
                </>
              )}
            </div>
          </div>
          <p style={{ color: "var(--pr-text-secondary)", fontSize: 13, marginBottom: 10 }}>
            {describePolicy(p)}
            {p.constraints.risk_level && (
              <span style={{ color: "var(--pr-warning-amber)" }}> &middot; {p.constraints.risk_level} risk</span>
            )}
          </p>
          <label htmlFor={`reject-reason-${p.policy_key}`} className="sr-only">Rejection reason</label>
          <input
            id={`reject-reason-${p.policy_key}`}
            placeholder="Reason (required to reject)"
            value={rejectReason[p.policy_key] ?? ""}
            onChange={(e) => setRejectReason((prev) => ({ ...prev, [p.policy_key]: e.target.value }))}
            style={{
              backgroundColor: "var(--pr-bg-hover)",
              border: "1px solid var(--pr-overlay-10)",
              color: "var(--pr-text-primary)",
              borderRadius: 6,
              padding: "6px 8px",
              fontSize: 13,
              width: "100%",
            }}
          />
        </Card>
      ))}
    </div>
  );
}
