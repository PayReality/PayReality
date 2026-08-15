import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { CheckCircle2, Clock, Send, ShieldAlert, XCircle, ShieldOff } from "lucide-react";
import { apiClient } from "../apiClient";
import { signBody } from "../crypto";
import { getAgentPrivateKey } from "../agentKeyStore";
import { describeApiError, describeReason, formatStatus } from "../format";
import { policyStudioApi } from "../../policy-studio/api";
import { agentsApi } from "../../agents/api";
import { track, trackError } from "../../services/analytics";
import { HelpIcon } from "../../help/HelpIcon";
import { NextStepGuidance } from "../../help/NextStepGuidance";
import { useAuth } from "../../auth/AuthContext";
import { Card } from "../../components/ui/card";
import { Alert } from "../../components/ui/alert";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import type {
  LiveAgent,
  LiveDecision,
  SubmitIntentResult,
  LivePrincipal,
  PrincipalAuthorityContext,
  LiveEvidence,
  AuthorityContext,
  DelegationEdge,
} from "../types";

const POLL_MAX_ATTEMPTS = 60;
const POLL_INTERVAL_MS = 2000;

const OUTCOME_STYLE: Record<string, { bg: string; fg: string; icon: typeof CheckCircle2 }> = {
  ALLOW: { bg: "rgba(34,197,94,0.1)", fg: "var(--pr-trust-green)", icon: CheckCircle2 },
  DENY: { bg: "rgba(239,68,68,0.1)", fg: "var(--pr-critical-red)", icon: XCircle },
  HUMAN_REVIEW: { bg: "rgba(245,158,11,0.1)", fg: "var(--pr-warning-amber)", icon: ShieldAlert },
};

type StageState = "pending" | "done" | "unavailable" | "waiting";

const STAGE_STYLE: Record<StageState, { fg: string; bg: string; label: string }> = {
  pending: { fg: "var(--pr-text-disabled)", bg: "var(--pr-overlay-06)", label: "Pending" },
  done: { fg: "var(--pr-trust-green)", bg: "rgba(34,197,94,0.12)", label: "Confirmed" },
  unavailable: { fg: "var(--pr-text-muted)", bg: "var(--pr-overlay-05)", label: "Not available" },
  waiting: { fg: "var(--pr-warning-amber)", bg: "rgba(245,158,11,0.12)", label: "Waiting" },
};

interface Stage {
  key: string;
  label: string;
  state: StageState;
  detail: string;
}

function StageRow({ stage, isLast }: { stage: Stage; isLast: boolean }) {
  const style = STAGE_STYLE[stage.state];
  return (
    <div className="flex gap-3" style={{ paddingBottom: isLast ? 0 : 18 }}>
      <div className="flex flex-col items-center flex-shrink-0" style={{ width: 22 }}>
        <div
          className="rounded-full flex items-center justify-center text-[11px] font-bold"
          style={{ width: 22, height: 22, backgroundColor: style.bg, color: style.fg, border: `2px solid ${style.fg}` }}
        >
          {stage.state === "done" ? "✓" : stage.state === "unavailable" ? "×" : ""}
        </div>
        {!isLast && <div style={{ width: 2, flex: 1, minHeight: 18, backgroundColor: "var(--pr-overlay-08)" }} />}
      </div>
      <div className="flex-1 min-w-0" style={{ paddingTop: 1 }}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>{stage.label}</span>
          <span
            className="text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded"
            style={{ color: style.fg, backgroundColor: style.bg, whiteSpace: "nowrap" }}
          >
            {style.label}
          </span>
        </div>
        <p className="text-xs mt-0.5" style={{ color: "var(--pr-text-muted)" }}>{stage.detail}</p>
      </div>
    </div>
  );
}

function ContextRow({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5">
      <span className="text-xs flex-shrink-0" style={{ color: "var(--pr-text-muted)" }}>{label}</span>
      <span
        className="text-xs font-medium text-right"
        style={{ color: muted ? "var(--pr-text-disabled)" : "var(--pr-text-primary)", fontStyle: muted ? "italic" : "normal" }}
      >
        {value}
      </span>
    </div>
  );
}

function DelegationRow({ delegation }: { delegation: DelegationEdge }) {
  return (
    <div className="py-1.5" style={{ borderTop: "1px solid var(--pr-overlay-05)", fontSize: 12 }}>
      <span style={{ color: "var(--pr-text-primary)" }}>{delegation.operation ?? "Delegation"}</span>
      {delegation.resource_id && (
        <span style={{ color: "var(--pr-text-muted)" }}> on resource {delegation.resource_id}</span>
      )}
    </div>
  );
}

function EvidenceRecordCard({ evidence, label }: { evidence: LiveEvidence; label: string }) {
  const p = evidence.payload;
  const fields: Array<[string, string | undefined]> = [
    ["Evidence ID", evidence.evidence_id],
    ["Status", evidence.status],
    ["Key ID", evidence.key_id],
    ["Recorded at", new Date(p.recorded_at).toLocaleString()],
    ["Risk classification", p.risk_classification],
    ["Authority outcome", p.authority_outcome],
    ["Approval outcome", p.approval_outcome ?? undefined],
    ["Reviewer", p.reviewer ?? p.approver ?? undefined],
    ["Policy version", p.policy_version !== undefined ? String(p.policy_version) : undefined],
    ["Policy bundle hash", p.policy_bundle_hash],
    ["Decision engine version", p.authority_version],
    ["Previous record hash", p.previous_hash ?? "None (first record in this chain)"],
    ["Matched policies", p.matched_mandate_ids.length > 0 ? p.matched_mandate_ids.join(", ") : "None"],
    ["Signature", `${evidence.signature.slice(0, 24)}...`],
  ];
  return (
    <div className="p-3 rounded-lg" style={{ backgroundColor: "var(--pr-overlay-03)", border: "1px solid var(--pr-overlay-05)" }}>
      <p className="text-xs font-semibold mb-2" style={{ color: "var(--pr-authority-blue)" }}>{label}</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6">
        {fields.filter(([, v]) => v !== undefined).map(([k, v]) => (
          <ContextRow key={k} label={k} value={v as string} />
        ))}
      </div>
    </div>
  );
}

export function LiveTestIntent() {
  const { user } = useAuth();
  const [agents, setAgents] = useState<LiveAgent[] | null>(null);
  const [agentsError, setAgentsError] = useState<string | null>(null);
  const [actions, setActions] = useState<string[]>([]);
  const [principals, setPrincipals] = useState<LivePrincipal[]>([]);
  const [agentId, setAgentId] = useState("");
  const [action, setAction] = useState("");
  const [amount, setAmount] = useState("10000");
  const [currency, setCurrency] = useState("USD");
  const [result, setResult] = useState<SubmitIntentResult | null>(null);
  const [decision, setDecision] = useState<LiveDecision | null>(null);
  const [requestSentAt, setRequestSentAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [pollTimedOut, setPollTimedOut] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [resolverName, setResolverName] = useState("");
  const [resolveError, setResolveError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  const [principalContext, setPrincipalContext] = useState<PrincipalAuthorityContext | null>(null);
  const [principalContextError, setPrincipalContextError] = useState<string | null>(null);
  const [principalContextLoading, setPrincipalContextLoading] = useState(false);

  const [evidenceRecords, setEvidenceRecords] = useState<LiveEvidence[]>([]);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);

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
    // Same small, already-loaded-elsewhere list ScopeFields.tsx uses for
    // its principal picker -- just enough to resolve an id to a display
    // name, not a second source of truth about principals.
    agentsApi.listPrincipals().then(setPrincipals).catch(() => setPrincipals([]));
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

  // The agent this page is actually showing Business Context for: once a
  // decision exists, that decision's own agent_id (immutable fact about
  // what was evaluated); before that, whichever agent is currently
  // selected in the form, so a visitor can preview real authority context
  // before ever submitting anything.
  const contextAgentId = decision?.agent_id ?? agentId;
  const contextAgent = agents?.find((a) => a.id === contextAgentId) ?? null;
  const principalId = contextAgent?.acting_for_principal_id ?? null;
  const principalName = principalId ? principals.find((p) => p.id === principalId)?.name ?? null : null;

  useEffect(() => {
    if (!principalId) {
      setPrincipalContext(null);
      setPrincipalContextError(null);
      return;
    }
    setPrincipalContextLoading(true);
    setPrincipalContextError(null);
    agentsApi
      .getPrincipalAuthorityContext(principalId)
      .then(setPrincipalContext)
      .catch((e) => setPrincipalContextError(describeApiError(e, "Loading authority context")))
      .finally(() => setPrincipalContextLoading(false));
  }, [principalId]);

  function loadEvidence(decisionId: string) {
    setEvidenceLoading(true);
    setEvidenceError(null);
    apiClient
      .get<LiveEvidence[]>(`/v1/evidence?decision_id=${decisionId}`)
      .then((records) => {
        // Oldest first: the record created at submission time, then (only
        // once a HUMAN_REVIEW decision is resolved) the second, separate
        // record resolution_service.resolve_decision appends.
        setEvidenceRecords([...records].sort((a, b) => a.created_at.localeCompare(b.created_at)));
      })
      .catch((e) => setEvidenceError(describeApiError(e, "Loading evidence")))
      .finally(() => setEvidenceLoading(false));
  }

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
    setEvidenceRecords([]);
    setEvidenceError(null);
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
    setRequestSentAt(submittedAt);
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

    // Evidence is created synchronously at submission time regardless of
    // outcome (server/app/services/intent_service.py), so it's fetched
    // here immediately rather than waiting for the decision to resolve.
    loadEvidence(submitted.decision.decision_id);

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
      // Resolution appends a second, separate Evidence record
      // (resolution_service.resolve_decision) -- reload to pick it up.
      loadEvidence(decision.id);
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
  const originalEvidence = evidenceRecords[0] ?? null;
  const resolutionEvidence = evidenceRecords.length > 1 ? evidenceRecords[evidenceRecords.length - 1] : null;
  const authorityCtx: AuthorityContext | PrincipalAuthorityContext | null = originalEvidence?.payload.authority_context ?? principalContext;
  const delegations: DelegationEdge[] = originalEvidence?.payload.delegation_chain ?? principalContext?.delegations ?? [];

  // Runtime Authority pipeline: every stage reflects a fact this page can
  // actually confirm from real API data today. No stage here implies a
  // real-time, independently observed sub-step the backend doesn't
  // actually expose -- see RUNTIME_DECISION_CENTER_V2_SPEC.md section 6
  // for what a genuinely observable intermediate-state stream would add
  // in a later phase. (Reserved slot for a future Enterprise Knowledge
  // stage between "Delegated authority" and "Runtime policies": nothing
  // renders here today because nothing real exists yet to report.)
  const stages: Stage[] = [];
  if (decision) {
    stages.push({
      key: "intent",
      label: "Intent accepted and identity verified",
      state: "done",
      detail: "The signed request passed signature and replay checks.",
    });
    stages.push({
      key: "authority",
      label: "Delegated authority",
      state: authorityCtx ? "done" : principalContextLoading ? "pending" : "unavailable",
      detail: authorityCtx
        ? `Resolved${principalName ? `: ${principalName}` : ""}${authorityCtx.department ? `, ${authorityCtx.department}` : ""}`
        : principalContextLoading
          ? "Resolving..."
          : "No authority context resolved for this agent's principal.",
    });
    stages.push({
      key: "policies",
      label: "Runtime policies evaluated",
      state: decision.evaluated_mandates.length > 0 ? "done" : "unavailable",
      detail:
        decision.evaluated_mandates.length > 0
          ? `${decision.evaluated_mandates.length} polic${decision.evaluated_mandates.length === 1 ? "y" : "ies"} evaluated: ${decision.evaluated_mandates.join(", ")}`
          : describeReason(decision.reason) ?? "No policy matched this request.",
    });
    stages.push({
      key: "risk",
      label: "Risk classified",
      state: evidenceLoading ? "pending" : evidenceError ? "unavailable" : originalEvidence ? "done" : "unavailable",
      detail: evidenceLoading
        ? "Loading..."
        : evidenceError
          ? evidenceError
          : originalEvidence
            ? formatStatus(originalEvidence.payload.risk_classification)
            : "Not available.",
    });
    stages.push({
      key: "evidence",
      label: "Evidence recorded",
      state: result ? "done" : "pending",
      detail: result ? `Signed and hash-chained: ${result.evidence_id}` : "Awaiting result.",
    });
  }

  return (
    <div className="p-8 max-w-7xl mx-auto" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <div className="mb-6">
        <div className="flex items-center gap-1.5 mb-2">
          <h1 style={{ color: "var(--pr-text-primary)" }}>Runtime Decision Center</h1>
          <HelpIcon articleId="runtime_decision" />
        </div>
        <p style={{ color: "var(--pr-text-muted)" }}>
          The moment an AI agent asks permission to act. Submit a signed request and see it checked
          against your active rules: approved, blocked, or sent to a human, with the real evidence
          it produces.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-8">
        {/* LEFT: Business Context */}
        <div className="flex flex-col gap-4">
          <p className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--pr-text-disabled)" }}>
            Business context
          </p>
          <Card padding={20} data-tour="intent-form">
            {agents !== null && signableAgents.length === 0 && (
              <p className="text-sm mb-4" style={{ color: "var(--pr-warning-amber)" }}>
                No agents with a signing key in this browser yet. Register one on the{" "}
                <Link to="/agents" style={{ color: "var(--pr-authority-blue)" }}>Agents page</Link> first.
              </p>
            )}
            <div className="grid grid-cols-1 gap-4 mb-4">
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
              <div className="grid grid-cols-2 gap-3">
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
              className="w-full px-4 py-2 rounded-lg text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-40"
              style={{ backgroundColor: "var(--pr-authority-blue)", color: "#fff" }}
            >
              <Send className="w-4 h-4" /> {submitting ? "Submitting..." : "Submit signed intent"}
            </button>

            {error && <Alert severity="error" className="text-sm mt-4">{error}</Alert>}
          </Card>

          {contextAgent && (
            <Card padding={20}>
              <p className="text-xs font-semibold mb-2" style={{ color: "var(--pr-text-secondary)" }}>Acting identity</p>
              <ContextRow label="Agent" value={contextAgent.name} />
              <ContextRow
                label="Principal"
                value={principalName ?? (principalContextLoading ? "Loading..." : "Not resolved")}
                muted={!principalName && !principalContextLoading}
              />
              {principalContextLoading && <Skeleton height={12} width="70%" style={{ marginTop: 8 }} />}
              {principalContextError && (
                <p className="text-xs mt-2" style={{ color: "var(--pr-warning-amber)" }}>{principalContextError}</p>
              )}
              {authorityCtx && !principalContextLoading && (
                <>
                  <ContextRow label="Role" value={authorityCtx.role ?? "Not set"} muted={!authorityCtx.role} />
                  <ContextRow label="Team" value={authorityCtx.team ?? "Not set"} muted={!authorityCtx.team} />
                  <ContextRow label="Department" value={authorityCtx.department ?? "Not set"} muted={!authorityCtx.department} />
                  <ContextRow label="Business unit" value={authorityCtx.business_unit ?? "Not set"} muted={!authorityCtx.business_unit} />
                  <ContextRow label="Organization" value={authorityCtx.organization ?? "Not set"} muted={!authorityCtx.organization} />
                </>
              )}
            </Card>
          )}
        </div>

        {/* CENTER: Runtime Authority pipeline */}
        <div className="flex flex-col gap-4">
          <p className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--pr-text-disabled)" }}>
            Runtime authority
          </p>
          <Card padding={20} className="flex-1">
            {!decision && !submitting && (
              <div className="flex flex-col items-center justify-center text-center py-10">
                <Clock className="w-5 h-5 mb-3" style={{ color: "var(--pr-text-disabled)" }} />
                <p className="text-sm" style={{ color: "var(--pr-text-muted)" }}>Awaiting a request.</p>
                <p className="text-xs mt-1" style={{ color: "var(--pr-text-disabled)" }}>Submit a signed intent to see it evaluated here.</p>
              </div>
            )}
            {!decision && submitting && (
              <div className="flex flex-col items-center justify-center text-center py-10">
                <Clock className="w-5 h-5 mb-3 animate-pulse" style={{ color: "var(--pr-authority-blue)" }} />
                <p className="text-sm" style={{ color: "var(--pr-text-secondary)" }}>Evaluating...</p>
              </div>
            )}
            {decision && (
              <div>
                {stages.map((s, i) => (
                  <StageRow key={s.key} stage={s} isLast={i === stages.length - 1} />
                ))}
                {decision.status === "PENDING" && !pollTimedOut && (
                  <div className="flex items-center gap-2 mt-4 p-3 rounded-lg" style={{ backgroundColor: "rgba(245,158,11,0.06)" }}>
                    <Clock className="w-4 h-4 animate-pulse" style={{ color: "var(--pr-warning-amber)" }} />
                    <span className="text-sm" style={{ color: "var(--pr-text-secondary)" }}>
                      Awaiting human review (checking every 2 seconds)...
                    </span>
                  </div>
                )}
                {decision.status === "PENDING" && pollTimedOut && (
                  <Alert severity="warning" className="mt-4">
                    <div className="flex items-center gap-3">
                      <span>
                        Still awaiting human review after {Math.round((POLL_MAX_ATTEMPTS * POLL_INTERVAL_MS) / 60000)} minutes.
                        Stopped checking automatically; refresh to check again.
                      </span>
                      <Button variant="ghost" size="sm" onClick={() => { setPollTimedOut(false); startPolling(decision.id); }}>
                        Resume checking
                      </Button>
                    </div>
                  </Alert>
                )}
              </div>
            )}
          </Card>
        </div>

        {/* RIGHT: Decision */}
        <div className="flex flex-col gap-4">
          <p className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--pr-text-disabled)" }}>
            Decision
          </p>
          <Card padding={20} className="flex-1" role="status" aria-live="polite" data-tour="decision-outcome">
            {!decision && !error && (
              <div className="flex flex-col items-center justify-center text-center py-10">
                <p className="text-sm" style={{ color: "var(--pr-text-muted)" }}>No decision yet.</p>
              </div>
            )}

            {!decision && error && (
              <div>
                <div className="flex items-center gap-3 mb-3">
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ backgroundColor: "var(--pr-overlay-06)" }}>
                    <ShieldOff className="w-5 h-5" style={{ color: "var(--pr-text-secondary)" }} />
                  </div>
                  <p className="font-semibold" style={{ color: "var(--pr-text-secondary)" }}>Could not evaluate</p>
                </div>
                <p className="text-xs mb-3" style={{ color: "var(--pr-text-muted)" }}>{error}</p>
                <p className="text-xs" style={{ color: "var(--pr-text-disabled)" }}>
                  Not a model's judgment call. A rule, evaluated the same way every time, fail-closed by
                  default: if the engine can't confirm an action is authorized, it never defaults to allow.
                </p>
              </div>
            )}

            {decision && style && (
              <div>
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ backgroundColor: style.bg }}>
                    <style.icon className="w-5 h-5" style={{ color: style.fg }} />
                  </div>
                  <div>
                    <p className="font-semibold" style={{ color: style.fg }}>{formatStatus(decision.outcome)}</p>
                    <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>{describeReason(decision.reason)}</p>
                  </div>
                </div>

                <div className="mb-3">
                  <ContextRow label="Policies evaluated" value={decision.evaluated_mandates.length > 0 ? decision.evaluated_mandates.join(", ") : "None"} />
                  {decision.evaluated_mandate_ids.length > 0 && (
                    <ContextRow label="Mandate IDs" value={decision.evaluated_mandate_ids.join(", ")} />
                  )}
                  {decision.enterprise_system_name && (
                    <ContextRow label="Enterprise system" value={decision.enterprise_system_name} />
                  )}
                  <ContextRow
                    label="Risk classification"
                    value={
                      evidenceLoading
                        ? "Loading..."
                        : originalEvidence
                          ? formatStatus(originalEvidence.payload.risk_classification)
                          : "Not available"
                    }
                    muted={!evidenceLoading && !originalEvidence}
                  />
                  <ContextRow label="Evidence recorded" value={result ? "Yes" : "No"} />
                </div>

                {decision.outcome === "HUMAN_REVIEW" && decision.status === "PENDING" && (
                  <div className="mt-3">
                    <label htmlFor="resolver-name" className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                      {user ? "Reviewer (you)" : "Your name (recorded as the reviewer for this decision)"}
                    </label>
                    <input
                      id="resolver-name"
                      value={resolverName}
                      onChange={(e) => setResolverName(e.target.value)}
                      readOnly={!!user}
                      placeholder="Jane Smith"
                      className="w-full mb-3 px-3 py-2 rounded-lg border text-sm"
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
                    {resolveError && <Alert severity="error" className="text-sm mt-3">{resolveError}</Alert>}
                  </div>
                )}

                {decision.resolution && (
                  <p className="text-sm mt-2" style={{ color: "var(--pr-text-primary)" }}>
                    Resolved <strong>{decision.resolution.resolution}</strong> by {decision.resolution.resolved_by}
                  </p>
                )}

                {result && (
                  <p className="text-xs mt-4 font-mono" style={{ color: "var(--pr-text-muted)" }}>
                    evidence_id: {result.evidence_id}
                  </p>
                )}
              </div>
            )}
          </Card>
        </div>
      </div>

      {decision && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
          {/* Authority chain: one hop only, agent <- principal. No
             multi-level chain is shown because none is resolvable from
             today's data model (RUNTIME_DECISION_CENTER_V2_SPEC.md
             section 7). */}
          <Card padding={20}>
            <p className="text-sm font-semibold mb-3" style={{ color: "var(--pr-text-primary)" }}>Authority chain</p>
            {principalContextLoading && <Skeleton height={14} width="60%" />}
            {!principalContextLoading && principalName && (
              <div className="flex items-center gap-2 text-sm mb-2" style={{ color: "var(--pr-text-primary)" }}>
                <span className="px-2 py-1 rounded" style={{ backgroundColor: "var(--pr-overlay-06)" }}>{principalName}</span>
                <span style={{ color: "var(--pr-text-disabled)" }}>&rarr;</span>
                <span className="px-2 py-1 rounded" style={{ backgroundColor: "rgba(77,124,254,0.12)", color: "var(--pr-authority-blue)" }}>
                  {contextAgent?.name ?? "Agent"}
                </span>
              </div>
            )}
            {!principalContextLoading && !principalName && (
              <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>No principal resolved for this agent.</p>
            )}
            {delegations.length > 0 && (
              <div className="mt-2">
                <p className="text-xs mb-1" style={{ color: "var(--pr-text-muted)" }}>Active delegations</p>
                {delegations.map((d) => <DelegationRow key={d.id} delegation={d} />)}
              </div>
            )}
          </Card>

          {/* Runtime policy evaluation: the real, flat list of matched
             mandates only. No per-condition breakdown is shown; that
             would require wiring the Simulator's explainer to live
             traffic (spec Phase 2), not something to fake here. */}
          <Card padding={20}>
            <p className="text-sm font-semibold mb-1" style={{ color: "var(--pr-text-primary)" }}>Runtime policies evaluated</p>
            <p className="text-xs mb-3" style={{ color: "var(--pr-text-muted)" }}>
              Policies that matched this request. Condition-level detail isn't available in this view yet.
            </p>
            {decision.evaluated_mandates.length === 0 && (
              <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>{describeReason(decision.reason) ?? "No policy matched."}</p>
            )}
            {decision.evaluated_mandates.map((key) => (
              <div key={key} className="py-1.5" style={{ borderTop: "1px solid var(--pr-overlay-05)", fontSize: 13 }}>
                <span className="font-mono" style={{ color: "var(--pr-text-primary)" }}>{key}</span>
              </div>
            ))}
          </Card>
        </div>
      )}

      {decision && (
        <div className="mb-6">
          <p className="text-sm font-semibold mb-3" style={{ color: "var(--pr-text-primary)" }}>Evidence</p>
          <Card padding={20}>
            {evidenceLoading && <Skeleton height={14} width="40%" />}
            {evidenceError && (
              <Alert severity="warning" className="text-sm mb-3">
                <div className="flex items-center gap-3">
                  <span>{evidenceError}</span>
                  <Button variant="ghost" size="sm" onClick={() => loadEvidence(decision.id)}>Retry</Button>
                </div>
              </Alert>
            )}
            {!evidenceLoading && !evidenceError && evidenceRecords.length === 0 && (
              <p className="text-sm" style={{ color: "var(--pr-text-muted)" }}>No evidence record loaded yet.</p>
            )}
            <div className="flex flex-col gap-3">
              {originalEvidence && <EvidenceRecordCard evidence={originalEvidence} label="Recorded at submission" />}
              {resolutionEvidence && <EvidenceRecordCard evidence={resolutionEvidence} label="Recorded at resolution" />}
            </div>
            {originalEvidence && (
              <Link to="/evidence" className="text-xs mt-3 inline-block" style={{ color: "var(--pr-authority-blue)" }}>
                Open the full Evidence record &rarr;
              </Link>
            )}
          </Card>
        </div>
      )}

      {decision && (
        <div className="mb-6">
          <p className="text-sm font-semibold mb-3" style={{ color: "var(--pr-text-primary)" }}>Timeline</p>
          <Card padding={20}>
            <div className="flex flex-col">
              {requestSentAt && (
                <div className="flex gap-3 pb-3" style={{ borderBottom: "1px solid var(--pr-overlay-05)" }}>
                  <span className="text-xs font-mono flex-shrink-0" style={{ color: "var(--pr-text-disabled)", width: 90 }}>
                    {new Date(requestSentAt).toLocaleTimeString()}
                  </span>
                  <span className="text-sm" style={{ color: "var(--pr-text-primary)" }}>Request sent (this browser)</span>
                </div>
              )}
              {originalEvidence && (
                <div className="flex gap-3 py-3" style={{ borderBottom: "1px solid var(--pr-overlay-05)" }}>
                  <span className="text-xs font-mono flex-shrink-0" style={{ color: "var(--pr-text-disabled)", width: 90 }}>
                    {new Date(originalEvidence.created_at).toLocaleTimeString()}
                  </span>
                  <span className="text-sm" style={{ color: "var(--pr-text-primary)" }}>
                    Evidence recorded: {formatStatus(decision.outcome)}
                  </span>
                </div>
              )}
              {resolutionEvidence && decision.resolution && (
                <div className="flex gap-3 pt-3">
                  <span className="text-xs font-mono flex-shrink-0" style={{ color: "var(--pr-text-disabled)", width: 90 }}>
                    {new Date(decision.resolution.created_at).toLocaleTimeString()}
                  </span>
                  <span className="text-sm" style={{ color: "var(--pr-text-primary)" }}>
                    Resolved {decision.resolution.resolution} by {decision.resolution.resolved_by}
                  </span>
                </div>
              )}
              {!requestSentAt && !originalEvidence && (
                <p className="text-sm" style={{ color: "var(--pr-text-muted)" }}>No timeline events yet.</p>
              )}
            </div>
          </Card>
        </div>
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
