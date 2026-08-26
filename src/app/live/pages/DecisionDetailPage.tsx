import { useEffect, useState, type CSSProperties } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { CheckCircle2, XCircle, ShieldOff } from "lucide-react";
import { apiClient } from "../apiClient";
import { decisionsApi } from "../decisionsApi";
import { agentsApi } from "../../agents/api";
import {
  describeApiError,
  describeExplanationUnavailable,
  describeReason,
  formatStatus,
} from "../format";
import {
  ContextRow,
  DelegationRow,
  EvidenceRecordCard,
  OUTCOME_STYLE,
  RuleEvaluationCard,
  describeFreshnessStatus,
  describeSource,
} from "../components/decisionDisplay";
import { useAuth } from "../../auth/AuthContext";
import { Card } from "../../components/ui/card";
import { Alert } from "../../components/ui/alert";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { notifyResourceChanged, useResourceSync } from "../../services/resourceSync";
import { track, trackError } from "../../services/analytics";
import type {
  AuthorityContext,
  DecisionExplanation,
  DelegationEdge,
  LiveDecision,
  LiveEvidence,
  PrincipalAuthorityContext,
} from "../types";
import type { AgentDetail } from "../../agents/types";

// theme.css's --pr-enter-delay custom property, typed: CSSProperties
// doesn't model arbitrary `--*` keys, so every staggered .pr-enter
// usage below goes through this one small helper rather than an
// inline `as CSSProperties` cast repeated at each call site.
function enterDelay(ms: number): CSSProperties {
  return { "--pr-enter-delay": `${ms}ms` } as CSSProperties;
}

// Core Product Experience Redesign, section 4C: one causal narrative
// answering "why did PayReality reach this decision," not fourteen
// unrelated cards. Section order is deliberate -- conclusion first
// (what happened, and whether it still needs a human), then the chain
// of "why" evidence supporting it (actor/authority/policy/facts/
// freshness/capability/evidence record), inverted-pyramid style.
export function DecisionDetailPage() {
  const { decisionId } = useParams();
  const navigate = useNavigate();
  const { user, hasPermission } = useAuth();
  const lacksResolvePermission = !!user && !hasPermission("decisions.resolve");

  const [decision, setDecision] = useState<LiveDecision | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [agent, setAgent] = useState<AgentDetail | null>(null);

  const [evidenceRecords, setEvidenceRecords] = useState<LiveEvidence[]>([]);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);

  const [explanationExpanded, setExplanationExpanded] = useState(false);
  const [explanation, setExplanation] = useState<DecisionExplanation | null>(null);
  const [explanationLoading, setExplanationLoading] = useState(false);
  const [explanationError, setExplanationError] = useState<string | null>(null);

  const [resolving, setResolving] = useState(false);
  const [resolverName, setResolverName] = useState("");
  const [resolveError, setResolveError] = useState<string | null>(null);

  function load() {
    if (!decisionId) return;
    setLoadError(null);
    decisionsApi
      .get(decisionId)
      .then((d) => {
        setDecision(d);
        agentsApi.getDetail(d.agent_id).then(setAgent).catch(() => setAgent(null));
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading this decision")));
  }

  function loadEvidence(id: string) {
    setEvidenceLoading(true);
    setEvidenceError(null);
    apiClient
      .get<LiveEvidence[]>(`/v1/evidence?decision_id=${id}`)
      .then((records) => setEvidenceRecords([...records].sort((a, b) => a.created_at.localeCompare(b.created_at))))
      .catch((e) => setEvidenceError(describeApiError(e, "Loading evidence")))
      .finally(() => setEvidenceLoading(false));
  }

  useEffect(load, [decisionId]);
  useEffect(() => {
    if (decision) loadEvidence(decision.id);
  }, [decision?.id]);
  // Milestone 13 Phase 6A: a resolution or new evidence record from
  // another tab (e.g. the Pending Review queue) should reach this page
  // too, not just whichever tab performed it.
  useResourceSync(["decisions", "evidence"], load);

  useEffect(() => {
    if (user) setResolverName(user.name);
  }, [user]);

  function loadExplanation(id: string) {
    setExplanationLoading(true);
    setExplanationError(null);
    apiClient
      .get<DecisionExplanation>(`/v1/decisions/${id}/explanation`)
      .then(setExplanation)
      .catch((e) => setExplanationError(describeApiError(e, "Loading policy evaluation")))
      .finally(() => setExplanationLoading(false));
  }

  function handleToggleExplanation() {
    const next = !explanationExpanded;
    setExplanationExpanded(next);
    if (next && decision && explanation === null && !explanationLoading) {
      loadExplanation(decision.id);
    }
  }

  async function handleResolve(resolution: "approved" | "denied") {
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
      notifyResourceChanged("decisions");
      notifyResourceChanged("evidence");
      track("Human Review Completed", { decision_id: decision.id, decision_result: resolution });
      load();
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
  }

  if (loadError) {
    return (
      <div className="p-8 max-w-4xl mx-auto">
        <Link to="/decisions" style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>&lt; Back to Decisions</Link>
        <Alert severity="error" className="text-sm mt-4">
          <div className="flex items-center gap-3">
            <span>{loadError}</span>
            <Button variant="ghost" size="sm" onClick={load}>Retry</Button>
          </div>
        </Alert>
      </div>
    );
  }

  if (!decision) {
    return (
      <div className="p-8 max-w-4xl mx-auto">
        <Skeleton height={16} width={140} style={{ marginBottom: 24 }} />
        <Skeleton height={28} width="60%" style={{ marginBottom: 12 }} />
        <Skeleton height={90} style={{ marginBottom: 16 }} />
        <Skeleton height={140} style={{ marginBottom: 16 }} />
        <Skeleton height={140} />
      </div>
    );
  }

  const style = OUTCOME_STYLE[decision.outcome];
  const originalEvidence = evidenceRecords[0] ?? null;
  const resolutionEvidence = evidenceRecords.length > 1 ? evidenceRecords[evidenceRecords.length - 1] : null;
  const authorityCtx: AuthorityContext | PrincipalAuthorityContext | null = originalEvidence?.payload.authority_context ?? null;
  const delegations: DelegationEdge[] = originalEvidence?.payload.delegation_chain ?? [];
  const facts = decision.facts_evaluated;

  return (
    <div className="p-8 max-w-4xl mx-auto" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <div className="flex items-center justify-between gap-3 mb-4">
        <Link to="/decisions" style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>&lt; Back to Decisions</Link>
        <div className="flex items-center gap-3">
          {/* Issue #4 (Authorization Receipts): the stable, named
              artifact assembling this decision's own evidence + policy
              binding for an auditor -- a separate page, not more detail
              crammed into this one. */}
          <Link to={`/decisions/${decision.id}/receipt`} style={{ color: "var(--pr-authority-blue)", fontSize: 13, fontWeight: 500 }}>
            View Authorization Receipt &rarr;
          </Link>
          <span style={{ fontSize: 11, color: "var(--pr-text-disabled)", fontFamily: "monospace" }}>{decision.id}</span>
        </div>
      </div>

      {/* DECISION: the conclusion, first. */}
      {/* Visual Experience V2, section 10A: a small staggered entrance
          across the four narrative groups below -- communicates
          causality (this followed from that) the same moment the data
          itself resolves, not a decorative effect on every re-render:
          DecisionDetailPage's own loading branch returns early above,
          so this only ever mounts once, when `decision` first becomes
          real. */}
      <Card padding={24} className="mb-4 pr-enter" role="status">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0" style={{ backgroundColor: style.bg }}>
            <style.icon className="w-5 h-5" style={{ color: style.fg }} />
          </div>
          <div>
            {decision.outcome === "HUMAN_REVIEW" && (
              <p className="text-xs font-medium uppercase tracking-wide" style={{ color: "var(--pr-text-disabled)" }}>Runtime Authority</p>
            )}
            <p className="font-semibold text-lg" style={{ color: style.fg }}>{formatStatus(decision.outcome)}</p>
            <p className="text-sm" style={{ color: "var(--pr-text-muted)" }}>{describeReason(decision.reason)}</p>
          </div>
        </div>
        <p className="text-sm" style={{ color: "var(--pr-text-secondary)" }}>
          {agent?.agent.name ?? "This agent"} attempted to <strong>{formatStatus(decision.action)}</strong>
          {decision.resource ? <> on <strong>{decision.resource}</strong></> : null}
          {decision.principal_name ? <>, acting for <strong>{decision.principal_name}</strong></> : null}.
        </p>
        <p className="text-xs mt-1" style={{ color: "var(--pr-text-disabled)" }}>
          {new Date(decision.created_at).toLocaleString()} &middot; Source: {describeSource(decision.source)}
          {decision.correlation_id ? <> &middot; Correlation ID: <span style={{ fontFamily: "monospace" }}>{decision.correlation_id}</span></> : null}
        </p>

        {decision.outcome === "HUMAN_REVIEW" && decision.status === "PENDING" && (
          <div className="mt-4 pt-4" style={{ borderTop: "1px solid var(--pr-overlay-05)" }}>
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
                maxWidth: 320,
              }}
            />
            <div className="flex gap-3">
              <button
                onClick={() => handleResolve("approved")}
                disabled={resolving || lacksResolvePermission}
                className="px-4 py-2 rounded-lg text-sm flex items-center justify-center gap-2 disabled:opacity-40"
                style={{ backgroundColor: "rgba(34,197,94,0.1)", color: "var(--pr-trust-green)" }}
              >
                <CheckCircle2 className="w-4 h-4" /> Approve
              </button>
              <button
                onClick={() => handleResolve("denied")}
                disabled={resolving || lacksResolvePermission}
                className="px-4 py-2 rounded-lg text-sm flex items-center justify-center gap-2 disabled:opacity-40"
                style={{ backgroundColor: "rgba(239,68,68,0.1)", color: "var(--pr-critical-red)" }}
              >
                <XCircle className="w-4 h-4" /> Deny
              </button>
            </div>
            {lacksResolvePermission && (
              <p className="text-xs mt-2" style={{ color: "var(--pr-text-muted)" }}>
                Your role can view this decision but not resolve it.
              </p>
            )}
            {resolveError && <Alert severity="error" className="text-sm mt-3">{resolveError}</Alert>}
          </div>
        )}

        {decision.resolution && (
          <p className="text-sm mt-3 pt-3" style={{ color: "var(--pr-text-primary)", borderTop: "1px solid var(--pr-overlay-05)" }}>
            Human resolution: <strong>{decision.resolution.resolution === "approved" ? "Approved" : "Denied"}</strong> by {decision.resolution.resolved_by} at {new Date(decision.resolution.created_at).toLocaleString()}
            {decision.resolution.reason ? ` -- ${decision.resolution.reason}` : ""}
          </p>
        )}
      </Card>

      {/* AUTHORITY + POLICY */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4 pr-enter" style={enterDelay(40)}>
        <Card padding={20}>
          <p className="text-sm font-semibold mb-3" style={{ color: "var(--pr-text-primary)" }}>Authority</p>
          {decision.principal_name ? (
            <div className="flex items-center gap-2 text-sm mb-2" style={{ color: "var(--pr-text-primary)" }}>
              <span className="px-2 py-1 rounded" style={{ backgroundColor: "var(--pr-overlay-06)" }}>{decision.principal_name}</span>
              <span style={{ color: "var(--pr-text-disabled)" }}>&rarr;</span>
              {agent ? (
                <Link to={`/agents/${agent.agent.id}`} className="px-2 py-1 rounded" style={{ backgroundColor: "rgba(77,124,254,0.12)", color: "var(--pr-authority-blue)" }}>
                  {agent.agent.name}
                </Link>
              ) : (
                <span className="px-2 py-1 rounded" style={{ backgroundColor: "rgba(77,124,254,0.12)", color: "var(--pr-authority-blue)" }}>Agent</span>
              )}
            </div>
          ) : (
            <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>No principal resolved for this agent.</p>
          )}
          {authorityCtx && (
            <div className="mt-2">
              <ContextRow label="Department" value={authorityCtx.department ?? "Not set"} muted={!authorityCtx.department} />
              <ContextRow label="Business unit" value={authorityCtx.business_unit ?? "Not set"} muted={!authorityCtx.business_unit} />
            </div>
          )}
          {delegations.length > 0 && (
            <div className="mt-2">
              <p className="text-xs mb-1" style={{ color: "var(--pr-text-muted)" }}>Active delegations</p>
              {delegations.map((d) => <DelegationRow key={d.id} delegation={d} />)}
            </div>
          )}
          <p className="text-[11px] mt-3 pt-3" style={{ color: "var(--pr-text-disabled)", borderTop: "1px solid var(--pr-overlay-05)" }}>
            Authority chain shown is one hop (principal to agent); deeper delegation chains aren't resolved today.
          </p>
        </Card>

        <Card padding={20}>
          <button
            onClick={handleToggleExplanation}
            className="w-full flex items-center justify-between gap-3 text-left"
            aria-expanded={explanationExpanded}
          >
            <div>
              <p className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)" }}>Policy</p>
              <p className="text-xs mt-0.5" style={{ color: "var(--pr-text-muted)" }}>
                {decision.evaluated_mandates.length === 0
                  ? (describeReason(decision.reason) ?? "No policy matched.")
                  : `${decision.evaluated_mandates.length} polic${decision.evaluated_mandates.length === 1 ? "y" : "ies"} evaluated.`}
              </p>
            </div>
            <span className="text-xs font-medium flex-shrink-0" style={{ color: "var(--pr-authority-blue)" }}>
              {explanationExpanded ? "Hide detail" : "Show detail"}
            </span>
          </button>

          {explanationExpanded && (
            <div className="mt-3 pt-3" style={{ borderTop: "1px solid var(--pr-overlay-05)" }}>
              {explanationLoading && (
                <div className="flex flex-col gap-2">
                  <Skeleton height={14} width="80%" />
                  <Skeleton height={14} width="60%" />
                </div>
              )}
              {!explanationLoading && explanationError && (
                <Alert severity="warning" className="text-sm">
                  <div className="flex items-center gap-3">
                    <span>{explanationError}</span>
                    <Button variant="ghost" size="sm" onClick={() => loadExplanation(decision.id)}>Retry</Button>
                  </div>
                </Alert>
              )}
              {!explanationLoading && !explanationError && explanation && (
                <>
                  {!explanation.available && (
                    <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>
                      {describeExplanationUnavailable(explanation.unavailable_reason)}
                    </p>
                  )}
                  {explanation.available && explanation.rules.length === 0 && (
                    <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>
                      No policy conditions were recorded for this decision.
                    </p>
                  )}
                  {explanation.available && explanation.rules.length > 0 && (
                    <>
                      {explanation.rules.map((r) => (
                        <RuleEvaluationCard key={r.policy_id} rule={r} isCausal={r.policy_id === explanation.causal_policy_id} />
                      ))}
                      <p className="text-xs mt-1" style={{ color: "var(--pr-text-disabled)" }}>
                        Evaluated against policy version {explanation.bundle_version}
                        {explanation.bundle_hash ? ` (bundle ${explanation.bundle_hash.slice(0, 12)}...)` : ""}
                        {explanation.evaluated_at ? `, ${new Date(explanation.evaluated_at).toLocaleString()}` : ""}.
                      </p>
                    </>
                  )}
                </>
              )}
            </div>
          )}
        </Card>
      </div>

      {/* TRUSTED FACTS + AUTHORITY FRESHNESS + CAPABILITY */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4 pr-enter" style={enterDelay(80)}>
        <Card padding={20}>
          <p className="text-sm font-semibold mb-2" style={{ color: "var(--pr-text-primary)" }}>Trusted enterprise facts</p>
          {facts && facts.length > 0 ? (
            facts.map((f, i) => (
              <ContextRow
                key={i}
                label={String((f as { key?: unknown }).key ?? `Fact ${i + 1}`)}
                value={String((f as { value?: unknown }).value ?? "")}
              />
            ))
          ) : (
            <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>No external facts were evaluated for this decision.</p>
          )}
        </Card>

        <Card padding={20}>
          <p className="text-sm font-semibold mb-2" style={{ color: "var(--pr-text-primary)" }}>Authority freshness</p>
          {decision.matched_policy_freshness ? (
            <>
              <ContextRow
                label="Status"
                value={describeFreshnessStatus(decision.matched_policy_freshness.status)}
                muted={decision.matched_policy_freshness.status === "unknown"}
              />
              <ContextRow
                label="Last attested"
                value={decision.matched_policy_freshness.last_attested_at ? new Date(decision.matched_policy_freshness.last_attested_at).toLocaleDateString() : "Never"}
                muted={!decision.matched_policy_freshness.last_attested_at}
              />
              <ContextRow
                label="Next review due"
                value={decision.matched_policy_freshness.next_review_at ? new Date(decision.matched_policy_freshness.next_review_at).toLocaleDateString() : "Not set"}
                muted={!decision.matched_policy_freshness.next_review_at}
              />
              <p className="text-[11px] mt-2 pt-2" style={{ color: "var(--pr-text-disabled)", borderTop: "1px solid var(--pr-overlay-05)" }}>
                Reflects the matched policy's current state, not a historical reconstruction as of this decision.
              </p>
            </>
          ) : (
            <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>No matched policy to report freshness for.</p>
          )}
        </Card>

        <Card padding={20}>
          <p className="text-sm font-semibold mb-2" style={{ color: "var(--pr-text-primary)" }}>Capability authorization</p>
          {decision.capability?.issued ? (
            <>
              <ContextRow label="Audience" value={decision.capability.audience ?? "Not set"} muted={!decision.capability.audience} />
              <ContextRow label="Expires" value={decision.capability.expires_at ? new Date(decision.capability.expires_at).toLocaleString() : "Not set"} />
              <ContextRow
                label="Consumed"
                value={decision.capability.consumed_at ? new Date(decision.capability.consumed_at).toLocaleString() : "Not yet"}
                muted={!decision.capability.consumed_at}
              />
              <p className="text-[11px] mt-2 pt-2" style={{ color: "var(--pr-text-disabled)", borderTop: "1px solid var(--pr-overlay-05)" }}>
                Consumption means the token was redeemed, not that the downstream business action completed.
              </p>
            </>
          ) : (
            <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>No capability token was issued for this decision.</p>
          )}
        </Card>
      </div>

      {/* EVIDENCE */}
      <div className="mb-4 pr-enter" style={enterDelay(120)}>
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
            <div className="flex items-center gap-3">
              <ShieldOff className="w-4 h-4" style={{ color: "var(--pr-text-disabled)" }} />
              <p className="text-sm" style={{ color: "var(--pr-text-muted)" }}>No evidence record found for this decision.</p>
            </div>
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

      <Button variant="ghost" size="sm" onClick={() => navigate("/decisions")}>Back to Decisions</Button>
    </div>
  );
}
