import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { CheckCircle2, Clock, Send, ShieldAlert, XCircle } from "lucide-react";
import { apiClient } from "../apiClient";
import { signBody } from "../crypto";
import { getAgentPrivateKey } from "../agentKeyStore";
import { describeApiError, describeReason, formatStatus } from "../format";
import { policyStudioApi } from "../../policy-studio/api";
import { track, trackError } from "../../services/analytics";
import { HelpIcon } from "../../help/HelpIcon";
import { NextStepGuidance } from "../../help/NextStepGuidance";
import { useAuth } from "../../auth/AuthContext";
import { Card } from "../../components/ui/card";
import { Alert } from "../../components/ui/alert";
import { Button } from "../../components/ui/button";
import type { LiveAgent, LiveDecision, SubmitIntentResult } from "../types";

const POLL_MAX_ATTEMPTS = 60;
const POLL_INTERVAL_MS = 2000;

const OUTCOME_STYLE: Record<string, { bg: string; fg: string; icon: typeof CheckCircle2 }> = {
  ALLOW: { bg: "rgba(34,197,94,0.1)", fg: "var(--pr-trust-green)", icon: CheckCircle2 },
  DENY: { bg: "rgba(239,68,68,0.1)", fg: "var(--pr-critical-red)", icon: XCircle },
  HUMAN_REVIEW: { bg: "rgba(245,158,11,0.1)", fg: "var(--pr-warning-amber)", icon: ShieldAlert },
};

export function LiveTestIntent() {
  const { user } = useAuth();
  const [agents, setAgents] = useState<LiveAgent[] | null>(null);
  const [agentsError, setAgentsError] = useState<string | null>(null);
  const [actions, setActions] = useState<string[]>([]);
  const [agentId, setAgentId] = useState("");
  const [action, setAction] = useState("");
  const [amount, setAmount] = useState("10000");
  const [currency, setCurrency] = useState("USD");
  const [result, setResult] = useState<SubmitIntentResult | null>(null);
  const [decision, setDecision] = useState<LiveDecision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [pollTimedOut, setPollTimedOut] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [resolverName, setResolverName] = useState("");
  const [resolveError, setResolveError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  function loadAgents() {
    setAgentsError(null);
    apiClient.get<{ agents: LiveAgent[] }>("/v1/agents").then((r) => setAgents(r.agents)).catch((e) => setAgentsError(describeApiError(e, "Loading agents")));
  }

  useEffect(() => {
    loadAgents();
    // The same live vocabulary endpoint ScopeFields.tsx already uses,
    // never a second hardcoded copy of the known actions (the exact
    // drift bug DOMAIN_REFACTOR_PLAN.md's item 5 already named).
    policyStudioApi
      .getVocabulary()
      .then((v) => {
        setActions(v.actions);
        setAction((current) => current || v.actions[0] || "");
      })
      .catch(() => setActions([]));
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  // Session identity replaces free-text reviewer entry (Stage I.6): a
  // logged-in user's name is already known server-side (Stage D records
  // resolved_by_user_id from the session regardless of what string this
  // field sends), so there's no reason to ask them to type it. The
  // Operator-Key-only path (no session) keeps the free-text field as is.
  useEffect(() => {
    if (user) setResolverName(user.name);
  }, [user]);

  const signableAgents = (agents ?? []).filter((a) => getAgentPrivateKey(a.id) && a.certificate_id);

  const startPolling = (decisionId: string) => {
    let attempts = 0;
    pollRef.current = window.setInterval(async () => {
      attempts += 1;
      const latest = await apiClient.get<LiveDecision>(`/v1/decisions/${decisionId}`);
      setDecision(latest);
      if (latest.status === "RESOLVED") {
        if (pollRef.current) window.clearInterval(pollRef.current);
      } else if (attempts >= POLL_MAX_ATTEMPTS) {
        if (pollRef.current) window.clearInterval(pollRef.current);
        setPollTimedOut(true);
      }
    }, POLL_INTERVAL_MS);
  };

  const handleSubmit = async () => {
    setError(null);
    setResult(null);
    setDecision(null);
    setPollTimedOut(false);
    setSubmitting(true);
    if (pollRef.current) window.clearInterval(pollRef.current);

    const agent = agents?.find((a) => a.id === agentId);
    const privateKey = agentId ? getAgentPrivateKey(agentId) : null;
    if (!agent || !privateKey || !agent.certificate_id) {
      setError("Select an agent that was registered in this browser (Live Agents page).");
      setSubmitting(false);
      return;
    }

    const body = {
      agent_id: agentId,
      action,
      amount: Number(amount),
      currency,
      counterparty: "vendor_772",
      context: { cost_center: "EMEA-04" },
      requested_at: new Date().toISOString(),
      nonce: crypto.randomUUID(),
    };
    const rawBody = JSON.stringify(body);
    const signature = signBody(new TextEncoder().encode(rawBody), privateKey);

    const submittedAt = Date.now();
    track("Runtime Intent Submitted", { agent_id: agentId, intent_type: action });

    // Split into two try/catches (previously one) so a failure submitting
    // the signed Intent and a failure fetching its resulting Decision are
    // distinguishable for analytics -- they're different failure modes
    // (Runtime Intent Submission Failed vs Runtime Decision Failed) that
    // used to be indistinguishable, both landing in the same catch block.
    let submitted: SubmitIntentResult;
    try {
      submitted = await apiClient.postSigned<SubmitIntentResult>("/v1/intents", rawBody, {
        "X-PayReality-Key-Id": agent.certificate_id,
        "X-PayReality-Signature": signature,
      });
      setResult(submitted);
    } catch (e) {
      setError(describeApiError(e, "Submission"));
      trackError("Runtime Intent Submission Failed", {
        error_type: e instanceof Error ? e.name : "unknown_error",
        component: "live_test_intent",
        duration_ms: Date.now() - submittedAt,
      });
      setSubmitting(false);
      return;
    }

    try {
      const latest = await apiClient.get<LiveDecision>(`/v1/decisions/${submitted.decision.decision_id}`);
      setDecision(latest);

      const latencyMs = Date.now() - submittedAt;
      track("Runtime Decision Produced", {
        agent_id: agentId,
        decision_id: submitted.decision.decision_id,
        intent_type: action,
        decision_result: submitted.decision.outcome,
        time_to_decision: latencyMs,
        runtime_decision_latency_ms: latencyMs,
        evidence_generation_ms: latencyMs, // Evidence is produced in the same server round-trip as the Decision; there's no separate client-observable generation step to time.
      });
      if (submitted.decision.outcome === "HUMAN_REVIEW") {
        track("Human Review Triggered", { agent_id: agentId, decision_id: submitted.decision.decision_id });
      }

      if (submitted.status === "PENDING") startPolling(submitted.decision.decision_id);
    } catch (e) {
      setError(describeApiError(e, "Submission"));
      trackError("Runtime Decision Failed", {
        error_type: e instanceof Error ? e.name : "unknown_error",
        component: "decision_fetch",
        duration_ms: Date.now() - submittedAt,
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleResolve = async (resolution: "approved" | "denied") => {
    if (!decision) return;
    setResolving(true);
    setResolveError(null);
    const startedAt = Date.now();
    try {
      await apiClient.post(`/v1/decisions/${decision.id}/resolve`, {
        resolution,
        resolved_by: resolverName.trim() || "unspecified reviewer",
        reason: resolution === "approved" ? "Reviewed and approved." : "Reviewed and denied.",
      });
      const latest = await apiClient.get<LiveDecision>(`/v1/decisions/${decision.id}`);
      setDecision(latest);
      track("Human Review Completed", { decision_id: decision.id, decision_result: resolution });
    } catch (e) {
      setResolveError(describeApiError(e, "Resolution"));
      trackError("Runtime Decision Failed", {
        error_type: e instanceof Error ? e.name : "unknown_error",
        component: "decision_resolution",
        duration_ms: Date.now() - startedAt,
      });
    } finally {
      setResolving(false);
    }
  };

  const style = decision ? OUTCOME_STYLE[decision.outcome] : null;

  return (
    <div className="p-8 max-w-3xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <div className="mb-8">
        <div className="flex items-center gap-1.5 mb-2">
          <h1 style={{ color: "var(--pr-text-primary)" }}>Decisions</h1>
          <HelpIcon articleId="runtime_decision" />
        </div>
        <p style={{ color: "var(--pr-text-muted)" }}>
          See what happens when an agent tries to act: watch it get checked against your active
          rules in real time and come back approved, blocked, or sent to a human.
        </p>
      </div>

      <Card padding={24} className="mb-6" data-tour="intent-form">
        {agents !== null && signableAgents.length === 0 && (
          <p className="text-sm mb-4" style={{ color: "var(--pr-warning-amber)" }}>
            No agents with a signing key in this browser yet. Register one on the{" "}
            <Link to="/agents" style={{ color: "var(--pr-authority-blue)" }}>Agents page</Link> first.
          </p>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
          <div>
            <label htmlFor="intent-agent" className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Agent</label>
            <select
              id="intent-agent"
              value={agentId}
              onChange={(e) => setAgentId(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            >
              <option value="">Select an agent...</option>
              {signableAgents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="intent-action" className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Action</label>
            <select
              id="intent-action"
              value={action}
              onChange={(e) => setAction(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            >
              {actions.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="intent-amount" className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Amount</label>
            <input
              id="intent-amount"
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            />
          </div>
          <div>
            <label htmlFor="intent-currency" className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Currency</label>
            <input
              id="intent-currency"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            />
          </div>
        </div>

        {agentsError && (
          <Alert severity="warning" className="text-sm mb-4">
            <div className="flex items-center gap-3">
              <span>{agentsError}</span>
              <Button variant="ghost" size="sm" onClick={loadAgents}>Retry</Button>
            </div>
          </Alert>
        )}

        <button
          onClick={handleSubmit}
          disabled={!agentId || !action || submitting}
          className="px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 disabled:opacity-40"
          style={{ backgroundColor: "var(--pr-authority-blue)", color: "#fff" }}
        >
          <Send className="w-4 h-4" /> {submitting ? "Submitting..." : "Submit signed intent"}
        </button>

        {error && (
          <Alert severity="error" className="text-sm mt-4">{error}</Alert>
        )}
      </Card>

      {decision && style && (
        <Card padding={24} role="status" aria-live="polite" data-tour="decision-outcome">
          <p className="text-xs font-medium uppercase tracking-widest mb-3" style={{ color: "var(--pr-text-muted)" }}>
            Decision
          </p>
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ backgroundColor: style.bg }}>
              <style.icon className="w-5 h-5" style={{ color: style.fg }} />
            </div>
            <div>
              <p className="font-semibold" style={{ color: style.fg }}>{formatStatus(decision.outcome)}</p>
              <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>{describeReason(decision.reason)}</p>
            </div>
          </div>

          {decision.evaluated_mandate_ids.length > 0 && (
            <div
              className="p-3 mb-2"
              style={{ borderLeft: "3px solid var(--pr-authority-blue)", backgroundColor: "var(--pr-overlay-04)", borderRadius: 6 }}
            >
              <p className="text-xs font-medium mb-1" style={{ color: "var(--pr-authority-blue)" }}>Authority verified</p>
              <p className="text-xs font-mono" style={{ color: "var(--pr-text-secondary)" }}>
                Authorized under Mandate{decision.evaluated_mandate_ids.length > 1 ? "s" : ""}: {decision.evaluated_mandate_ids.join(", ")}
              </p>
            </div>
          )}

          {decision.enterprise_system_name && (
            <div className="mb-4">
              <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>Enterprise System</p>
              <p className="text-sm" style={{ color: "var(--pr-text-primary)" }}>{decision.enterprise_system_name}</p>
            </div>
          )}

          {decision.status === "PENDING" && !pollTimedOut && (
            <div className="flex items-center gap-2 mb-4 p-3 rounded-lg" style={{ backgroundColor: "rgba(245,158,11,0.06)" }}>
              <Clock className="w-4 h-4 animate-pulse" style={{ color: "var(--pr-warning-amber)" }} />
              <span className="text-sm" style={{ color: "var(--pr-text-secondary)" }}>
                Awaiting human review (checking every 2 seconds)...
              </span>
            </div>
          )}

          {decision.status === "PENDING" && pollTimedOut && (
            <Alert severity="warning" className="mb-4">
              <div className="flex items-center gap-3">
                <span>
                  Still awaiting human review after {Math.round((POLL_MAX_ATTEMPTS * POLL_INTERVAL_MS) / 60000)} minutes.
                  Stopped checking automatically; refresh to check again.
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setPollTimedOut(false);
                    startPolling(decision.id);
                  }}
                >
                  Resume checking
                </Button>
              </div>
            </Alert>
          )}

          {decision.outcome === "HUMAN_REVIEW" && decision.status === "PENDING" && (
            <div>
              <label htmlFor="resolver-name" className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                {user ? "Reviewer (you)" : "Your name (recorded as the reviewer for this decision)"}
              </label>
              <input
                id="resolver-name"
                value={resolverName}
                onChange={(e) => setResolverName(e.target.value)}
                readOnly={!!user}
                placeholder="Jane Smith"
                className="w-full max-w-xs mb-3 px-3 py-2 rounded-lg border text-sm"
                style={{
                  backgroundColor: user ? "var(--pr-bg-primary)" : "var(--pr-bg-hover)",
                  borderColor: "var(--pr-overlay-10)",
                  color: user ? "var(--pr-text-muted)" : "var(--pr-text-primary)",
                }}
              />
              <div className="flex gap-3">
                <button
                  onClick={() => handleResolve("approved")}
                  disabled={resolving}
                  className="flex-1 px-4 py-2 rounded-lg text-sm flex items-center justify-center gap-2"
                  style={{ backgroundColor: "rgba(34,197,94,0.1)", color: "var(--pr-trust-green)" }}
                >
                  <CheckCircle2 className="w-4 h-4" /> Approve
                </button>
                <button
                  onClick={() => handleResolve("denied")}
                  disabled={resolving}
                  className="flex-1 px-4 py-2 rounded-lg text-sm flex items-center justify-center gap-2"
                  style={{ backgroundColor: "rgba(239,68,68,0.1)", color: "var(--pr-critical-red)" }}
                >
                  <XCircle className="w-4 h-4" /> Deny
                </button>
              </div>
              {resolveError && (
                <Alert severity="error" className="text-sm mt-3">{resolveError}</Alert>
              )}
            </div>
          )}

          {decision.resolution && (
            <p className="text-sm" style={{ color: "var(--pr-text-primary)" }}>
              Resolved <strong>{decision.resolution.resolution}</strong> by {decision.resolution.resolved_by}
            </p>
          )}

          {result && (
            <p className="text-xs mt-4 font-mono" style={{ color: "var(--pr-text-muted)" }}>
              evidence_id: {result.evidence_id}
            </p>
          )}
        </Card>
      )}

      {result && decision && decision.status !== "PENDING" && (
        <NextStepGuidance
          message="This decision produced a signed Evidence record. See exactly what was recorded and verify it hasn't been tampered with."
          actionLabel="View Evidence"
          actionPath="/evidence"
        />
      )}
    </div>
  );
}
