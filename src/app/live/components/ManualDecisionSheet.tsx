import { useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { useNavigate } from "react-router";
import { CheckCircle2, Clock, Send, XCircle } from "lucide-react";
import { apiClient } from "../apiClient";
import { signBody } from "../crypto";
import { getAgentPrivateKey } from "../agentKeyStore";
import { describeApiError, describeReason, formatStatus } from "../format";
import { policyStudioApi } from "../../policy-studio/api";
import { agentsApi } from "../../agents/api";
import { track, trackError } from "../../services/analytics";
import { notifyResourceChanged } from "../../services/resourceSync";
import { useAuth } from "../../auth/AuthContext";
import { Alert } from "../../components/ui/alert";
import { Button } from "../../components/ui/button";
import { Select } from "../../components/ui/select";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "../../components/ui/sheet";
import { OUTCOME_STYLE, describeSource } from "./decisionDisplay";
import type { LiveAgent, LiveDecision, SubmitIntentResult } from "../types";

const POLL_MAX_ATTEMPTS = 60;
const POLL_INTERVAL_MS = 2000;

// Domain Generalization Milestone: the same small, honest coercion
// Policy Studio's ConditionRow.parseValue already applies to a typed
// condition value -- reimplemented locally rather than left as an
// always-a-string field.
function parseContextValue(raw: string): string | number | boolean {
  const trimmed = raw.trim();
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  const asNumber = Number(trimmed);
  if (trimmed !== "" && !Number.isNaN(asNumber)) return asNumber;
  return raw;
}

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
  detail: ReactNode;
}

function StageRow({ stage, isLast }: { stage: Stage; isLast: boolean }) {
  const s = STAGE_STYLE[stage.state];
  return (
    <div className="flex gap-3" style={{ paddingBottom: isLast ? 0 : 14 }}>
      <div className="flex flex-col items-center flex-shrink-0" style={{ width: 20 }}>
        <div
          className="rounded-full flex items-center justify-center text-[10px] font-bold"
          style={{ width: 20, height: 20, backgroundColor: s.bg, color: s.fg, border: `2px solid ${s.fg}` }}
          aria-hidden="true"
        >
          {stage.state === "done" ? "✓" : ""}
        </div>
        {!isLast && <div style={{ width: 2, flex: 1, minHeight: 14, backgroundColor: "var(--pr-overlay-08)" }} />}
      </div>
      <div className="flex-1 min-w-0" style={{ paddingTop: 1 }}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs font-medium" style={{ color: "var(--pr-text-primary)" }}>{stage.label}</span>
          <span
            className="text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded flex-shrink-0"
            style={{ color: s.fg, backgroundColor: s.bg }}
          >
            {s.label}
          </span>
        </div>
        <p className="text-[11px] mt-0.5" style={{ color: "var(--pr-text-muted)" }}>{stage.detail}</p>
      </div>
    </div>
  );
}

interface ManualDecisionSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  // Called once a decision resolves (ALLOW/DENY, or HUMAN_REVIEW that's
  // then approved/denied inline) so the caller (Decision History) can
  // refresh its own list without waiting for a resourceSync tick.
  onSettled?: () => void;
  // Final Product Polish (found via real keyboard/focus QA): closing
  // this drawer (Escape or the X button) left focus on <body> instead
  // of returning it to the "Test Runtime Authority" button that opened
  // it. Optional so a caller that doesn't have a stable trigger ref can
  // still use this component; DecisionHistoryPage always provides one.
  triggerRef?: RefObject<HTMLElement | null>;
}

// Core Product Experience Redesign, section 4B: the manual-submission
// flow, demoted from the primary /decisions surface into a secondary,
// explicitly-labeled drawer. This creates a REAL Intent + Decision +
// Evidence with source="manual_test" -- distinct from Policy Simulation
// (a hypothetical OPA evaluation that creates no such records, reached
// from a policy's own Simulate page). Never conflate the two in copy.
export function ManualDecisionSheet({ open, onOpenChange, onSettled, triggerRef }: ManualDecisionSheetProps) {
  const navigate = useNavigate();
  const { user, hasPermission } = useAuth();
  const lacksResolvePermission = !!user && !hasPermission("decisions.resolve");

  const [agents, setAgents] = useState<LiveAgent[] | null>(null);
  const [agentsError, setAgentsError] = useState<string | null>(null);
  const [actions, setActions] = useState<string[]>([]);
  const [agentId, setAgentId] = useState("");
  const [action, setAction] = useState("");
  const [resource, setResource] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("");
  const [contextFields, setContextFields] = useState<{ key: string; value: string }[]>([{ key: "", value: "" }]);

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
    if (!open) return;
    loadAgents();
    policyStudioApi.getVocabulary().then((v) => {
      setActions(v.actions);
      setAction((current) => current || v.actions[0] || "");
    }).catch(() => setActions([]));
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [open]);

  useEffect(() => {
    if (user) setResolverName(user.name);
  }, [user]);

  const signableAgents = (agents ?? []).filter((a) => getAgentPrivateKey(a.id) && a.certificate_id);

  function resetForNextTest() {
    setResult(null);
    setDecision(null);
    setError(null);
    setPollTimedOut(false);
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
    setSubmitting(true);
    if (pollRef.current) window.clearInterval(pollRef.current);

    const agent = agents?.find((a) => a.id === agentId);
    const privateKey = agentId ? getAgentPrivateKey(agentId) : null;
    if (!agent || !privateKey || !agent.certificate_id) {
      setError("Select an agent that was registered in this browser (Agents page).");
      setSubmitting(false);
      return;
    }

    const context = Object.fromEntries(
      contextFields.filter((f) => f.key.trim() !== "").map((f) => [f.key.trim(), parseContextValue(f.value)])
    );
    const body: Record<string, unknown> = {
      agent_id: agentId,
      action,
      context,
      requested_at: new Date().toISOString(),
      nonce: crypto.randomUUID(),
      // Product Experience Remediation Milestone 1 (Decision Provenance):
      // this is the one caller that explicitly declares itself -- every
      // real SDK integration omits this field and is recorded "runtime"
      // by the server's own default.
      source: "manual_test",
    };
    if (resource.trim()) body.resource = resource.trim();
    if (amount.trim()) body.amount = Number(amount);
    if (currency.trim()) body.currency = currency.trim();
    const rawBody = JSON.stringify(body);
    const signature = signBody(new TextEncoder().encode(rawBody), privateKey);

    const submittedAt = Date.now();
    track("Runtime Intent Submitted", { agent_id: agentId, intent_type: action });

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
        component: "manual_decision_sheet",
        duration_ms: Date.now() - submittedAt,
      });
      setSubmitting(false);
      return;
    }

    notifyResourceChanged("decisions");
    notifyResourceChanged("evidence");
    onSettled?.();

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
        evidence_generation_ms: latencyMs,
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
    try {
      await apiClient.post(`/v1/decisions/${decision.id}/resolve`, {
        resolution,
        resolved_by: resolverName.trim() || "unspecified reviewer",
        reason: resolution === "approved" ? "Reviewed and approved." : "Reviewed and denied.",
      });
      notifyResourceChanged("decisions");
      notifyResourceChanged("evidence");
      onSettled?.();
      const latest = await apiClient.get<LiveDecision>(`/v1/decisions/${decision.id}`);
      setDecision(latest);
      track("Human Review Completed", { decision_id: decision.id, decision_result: resolution });
    } catch (e) {
      setResolveError(describeApiError(e, "Resolution"));
    } finally {
      setResolving(false);
    }
  };

  const style = decision ? OUTCOME_STYLE[decision.outcome] : null;

  const stages: Stage[] = [];
  if (decision) {
    stages.push({ key: "intent", label: "Intent accepted, identity verified", state: "done", detail: "Signature and replay checks passed." });
    stages.push({
      key: "policies",
      label: "Policy evaluation",
      state: decision.evaluated_mandates.length > 0 ? "done" : "unavailable",
      detail: decision.evaluated_mandates.length > 0
        ? `${decision.evaluated_mandates.length} polic${decision.evaluated_mandates.length === 1 ? "y" : "ies"} evaluated.`
        : describeReason(decision.reason) ?? "No policy matched.",
    });
    stages.push({ key: "evidence", label: "Evidence recorded", state: result ? "done" : "pending", detail: result ? `${result.evidence_id.slice(0, 12)}...` : "Awaiting result." });
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full sm:max-w-md flex flex-col p-0 gap-0"
        style={{ backgroundColor: "var(--pr-bg-card)" }}
        onCloseAutoFocus={(e) => {
          if (!triggerRef?.current) return;
          e.preventDefault();
          triggerRef.current.focus();
        }}
      >
        <SheetHeader className="border-b" style={{ borderColor: "var(--pr-overlay-05)" }}>
          <SheetTitle>Test Runtime Authority</SheetTitle>
          <SheetDescription>
            Submit a real, signed request as if it came from an agent. This creates a genuine Intent,
            Decision, and Evidence record (marked "manual test"), checked against your live rules --
            not a hypothetical simulation.
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto p-4">
          {!decision && (
            <>
              {agents !== null && signableAgents.length === 0 && (
                <p className="text-sm mb-4" style={{ color: "var(--pr-warning-amber)" }}>
                  No agents with a signing key in this browser yet. Register one on the Agents page first.
                </p>
              )}
              <div className="grid grid-cols-1 gap-3 mb-4">
                <div>
                  <label htmlFor="msd-agent" className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Agent</label>
                  <Select
                    id="msd-agent"
                    value={agentId}
                    onChange={(e) => setAgentId(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border text-sm"
                    containerClassName="block w-full"
                    style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                  >
                    <option value="">Select an agent...</option>
                    {signableAgents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                  </Select>
                </div>
                <div>
                  <label htmlFor="msd-action" className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Action</label>
                  <Select
                    id="msd-action"
                    value={action}
                    onChange={(e) => setAction(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border text-sm"
                    containerClassName="block w-full"
                    style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                  >
                    {actions.map((s) => <option key={s} value={s}>{s}</option>)}
                  </Select>
                </div>
                <div>
                  <label htmlFor="msd-resource" className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                    Resource <span style={{ color: "var(--pr-text-disabled)", fontWeight: 400 }}>(optional)</span>
                  </label>
                  <input
                    id="msd-resource"
                    value={resource}
                    onChange={(e) => setResource(e.target.value)}
                    placeholder="e.g. invoice:INV-4821"
                    className="w-full px-3 py-2 rounded-lg border text-sm"
                    style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="msd-amount" className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                      Amount <span style={{ color: "var(--pr-text-disabled)", fontWeight: 400 }}>(optional)</span>
                    </label>
                    <input
                      id="msd-amount"
                      type="number"
                      value={amount}
                      onChange={(e) => setAmount(e.target.value)}
                      className="w-full px-3 py-2 rounded-lg border text-sm"
                      style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                    />
                  </div>
                  <div>
                    <label htmlFor="msd-currency" className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                      Currency <span style={{ color: "var(--pr-text-disabled)", fontWeight: 400 }}>(optional)</span>
                    </label>
                    <input
                      id="msd-currency"
                      value={currency}
                      onChange={(e) => setCurrency(e.target.value)}
                      placeholder="USD"
                      className="w-full px-3 py-2 rounded-lg border text-sm"
                      style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                    Context <span style={{ color: "var(--pr-text-disabled)", fontWeight: 400 }}>(optional -- any field a policy's conditions reference)</span>
                  </label>
                  {contextFields.map((f, i) => (
                    <div key={i} style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                      <input
                        value={f.key}
                        onChange={(e) => { const next = [...contextFields]; next[i] = { ...next[i], key: e.target.value }; setContextFields(next); }}
                        placeholder="field"
                        className="px-2 py-1.5 rounded-lg border text-sm"
                        style={{ flex: 1, backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                      />
                      <input
                        value={f.value}
                        onChange={(e) => { const next = [...contextFields]; next[i] = { ...next[i], value: e.target.value }; setContextFields(next); }}
                        placeholder="value"
                        className="px-2 py-1.5 rounded-lg border text-sm"
                        style={{ flex: 1, backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                      />
                      <button
                        type="button"
                        onClick={() => setContextFields(contextFields.filter((_, j) => j !== i))}
                        aria-label="Remove field"
                        className="px-2 rounded-lg border text-sm"
                        style={{ borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-muted)" }}
                      >
                        &times;
                      </button>
                    </div>
                  ))}
                  <button
                    type="button"
                    onClick={() => setContextFields([...contextFields, { key: "", value: "" }])}
                    className="text-xs"
                    style={{ color: "var(--pr-authority-blue)" }}
                  >
                    + Add field
                  </button>
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
                <Send className="w-4 h-4" /> {submitting ? "Submitting..." : "Submit signed test intent"}
              </button>
              {error && <Alert severity="error" className="text-sm mt-4">{error}</Alert>}
            </>
          )}

          {!decision && submitting && (
            <div className="flex flex-col items-center justify-center text-center py-10">
              <Clock className="w-5 h-5 mb-3 animate-pulse" style={{ color: "var(--pr-authority-blue)" }} />
              <p className="text-sm" style={{ color: "var(--pr-text-secondary)" }}>Evaluating...</p>
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

              <p className="text-xs mb-4" style={{ color: "var(--pr-text-disabled)" }}>
                Source: {describeSource(decision.source)}
              </p>

              {stages.map((s, i) => <StageRow key={s.key} stage={s} isLast={i === stages.length - 1} />)}

              {decision.status === "PENDING" && !pollTimedOut && (
                <div className="flex items-center gap-2 mt-4 p-3 rounded-lg" style={{ backgroundColor: "rgba(245,158,11,0.06)" }}>
                  <Clock className="w-4 h-4 animate-pulse" style={{ color: "var(--pr-warning-amber)" }} />
                  <span className="text-xs" style={{ color: "var(--pr-text-secondary)" }}>Awaiting human review...</span>
                </div>
              )}
              {decision.status === "PENDING" && pollTimedOut && (
                <Alert severity="warning" className="mt-4 text-sm">
                  <div className="flex items-center gap-3">
                    <span>Still awaiting review. Stopped checking automatically.</span>
                    <Button variant="ghost" size="sm" onClick={() => { setPollTimedOut(false); startPolling(decision.id); }}>Resume</Button>
                  </div>
                </Alert>
              )}

              {decision.outcome === "HUMAN_REVIEW" && decision.status === "PENDING" && (
                <div className="mt-4 pt-4" style={{ borderTop: "1px solid var(--pr-overlay-05)" }}>
                  <div className="flex gap-3">
                    <button
                      onClick={() => handleResolve("approved")}
                      disabled={resolving || lacksResolvePermission}
                      className="flex-1 px-4 py-2 rounded-lg text-sm flex items-center justify-center gap-2 disabled:opacity-40"
                      style={{ backgroundColor: "rgba(34,197,94,0.1)", color: "var(--pr-trust-green)" }}
                    >
                      <CheckCircle2 className="w-4 h-4" /> Approve
                    </button>
                    <button
                      onClick={() => handleResolve("denied")}
                      disabled={resolving || lacksResolvePermission}
                      className="flex-1 px-4 py-2 rounded-lg text-sm flex items-center justify-center gap-2 disabled:opacity-40"
                      style={{ backgroundColor: "rgba(239,68,68,0.1)", color: "var(--pr-critical-red)" }}
                    >
                      <XCircle className="w-4 h-4" /> Deny
                    </button>
                  </div>
                  {resolveError && <Alert severity="error" className="text-sm mt-3">{resolveError}</Alert>}
                </div>
              )}

              {decision.resolution && (
                <p className="text-xs mt-4 pt-4" style={{ color: "var(--pr-text-primary)", borderTop: "1px solid var(--pr-overlay-05)" }}>
                  Human resolution: <strong>{decision.resolution.resolution === "approved" ? "Approved" : "Denied"}</strong> by {decision.resolution.resolved_by}
                </p>
              )}

              <div className="flex gap-2 mt-5">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => { onOpenChange(false); navigate(`/decisions/${decision.id}`); }}
                >
                  View full decision
                </Button>
                <Button variant="ghost" size="sm" onClick={resetForNextTest}>Test another</Button>
              </div>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
