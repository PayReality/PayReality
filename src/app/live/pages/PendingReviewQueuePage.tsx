import { useEffect, useState } from "react";
import { Link } from "react-router";
import { apiClient } from "../apiClient";
import { describeApiError, describeReason, formatStatus } from "../format";
import { useAuth } from "../../auth/AuthContext";
import { ROLE_LABELS } from "../../auth/types";
import { Card } from "../../components/ui/card";
import { Alert } from "../../components/ui/alert";
import { Button } from "../../components/ui/button";
import { Skeleton } from "../../components/ui/skeleton";
import { PageHeader } from "../../components/ui/page-header";
import { EmptyState } from "../../components/ui/empty-state";
import { AgentIdentity } from "../../components/ui/agent-identity";
import { ShieldAlert } from "lucide-react";
import { notifyResourceChanged, useResourceSync } from "../../services/resourceSync";
import { track, trackError } from "../../services/analytics";
import type { LiveAgent, LiveDecision, LiveDecisionListResponse } from "../types";

// The Pending Review queue: before this page existed, a Reviewer had no
// way to discover a HUMAN_REVIEW decision at all except already knowing
// its exact id (GET /v1/decisions/{id}) or looking at one agent's last
// 20 decisions (Agent Detail Page) -- there was no cross-agent,
// org-wide list. Modeled directly on ReviewQueuePage.tsx (the Authority
// Graph review queue): a Card-per-row list, resolved directly from the
// row rather than a separate detail page, buttons disabled (not the
// page hidden) once a real signed-in user is positively known to lack
// the permission.
const RESOLVE_ROLE_LABEL = "Reviewer, Governance Administrator, or Organisation Owner";

export function PendingReviewQueuePage() {
  const { user, hasPermission } = useAuth();
  const [decisions, setDecisions] = useState<LiveDecision[] | null>(null);
  const [total, setTotal] = useState(0);
  const [agentNames, setAgentNames] = useState<Record<string, string>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [resolverName, setResolverName] = useState("");
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});

  // Only disable once we positively know the signed-in user lacks the
  // permission -- with no session (Operator Key bypass still active),
  // stay permissive rather than guessing (same rule ReviewQueuePage and
  // DecisionDetailPage already follow). A load failure from GET /v1/decisions
  // itself (403 for a role without decisions.view, e.g. Agent Admin or
  // Executive) surfaces through loadError below, not a separate check
  // here -- the real permission gate is server-side either way.
  const lacksResolvePermission = !!user && !hasPermission("decisions.resolve");

  function load() {
    setLoadError(null);
    apiClient
      .get<LiveDecisionListResponse>("/v1/decisions?limit=100")
      .then((r) => {
        setDecisions(r.decisions);
        setTotal(r.total);
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading the review queue")));
    // Best-effort name lookup only -- the queue still functions (showing
    // a raw agent id) if this fails, since it's not the primary content.
    apiClient
      .get<{ agents: LiveAgent[] }>("/v1/agents")
      .then((r) => setAgentNames(Object.fromEntries(r.agents.map((a) => [a.id, a.name]))))
      .catch(() => {});
  }

  useEffect(load, []);
  // Milestone 13 Phase 6A (cross-page state synchronization): another
  // tab (or this one, left open) resolving a decision or registering an
  // agent should refresh this queue too, not just whichever page did it.
  useResourceSync(["decisions", "agents"], load);

  // Session identity replaces free-text reviewer entry (Stage I.6),
  // same as DecisionDetailPage/ManualDecisionSheet and ReviewQueuePage.
  useEffect(() => {
    if (user) setResolverName(user.name);
  }, [user]);

  async function handleResolve(decision: LiveDecision, resolution: "approved" | "denied") {
    setResolvingId(decision.id);
    setRowErrors((prev) => {
      const next = { ...prev };
      delete next[decision.id];
      return next;
    });
    const startedAt = Date.now();
    try {
      // Same endpoint/payload/notify-and-reload shape as
      // DecisionDetailPage.tsx's handleResolve -- not reimplemented
      // differently for this second entry point to the same action.
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
      setRowErrors((prev) => ({ ...prev, [decision.id]: describeApiError(e, "Resolution") }));
      trackError("Runtime Decision Failed", {
        error_type: e instanceof Error ? e.name : "unknown_error",
        component: "decision_resolution",
        duration_ms: Date.now() - startedAt,
      });
    } finally {
      setResolvingId(null);
    }
  }

  return (
    <div className="p-8 max-w-2xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <PageHeader
        title="Pending Review"
        description={`Every decision in your organization still waiting on a human, across every agent.${decisions ? ` ${total} pending.` : ""}`}
        secondaryAction={
          <Link to="/decisions" style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>
            &lt; All decisions
          </Link>
        }
      />
      <p style={{ color: "var(--pr-text-disabled)", fontSize: 12, marginBottom: 16, marginTop: -12 }}>
        Resolving requires: {RESOLVE_ROLE_LABEL}.
        {lacksResolvePermission && (
          <span style={{ color: "var(--pr-warning-amber)" }}>
            {" "}Your role ({user ? ROLE_LABELS[user.role] ?? user.role : ""}) doesn't include this permission.
          </span>
        )}
      </p>

      {user && (
        <>
          <label htmlFor="reviewer-name" className="sr-only">
            Reviewer (you)
          </label>
          <input
            id="reviewer-name"
            value={resolverName}
            readOnly
            style={{
              backgroundColor: "var(--pr-bg-primary)",
              border: "1px solid var(--pr-overlay-10)",
              color: "var(--pr-text-muted)",
              borderRadius: 6,
              padding: "6px 8px",
              fontSize: 13,
              marginBottom: 16,
              width: 260,
            }}
          />
        </>
      )}

      {loadError && (
        <Alert severity="warning" style={{ marginBottom: 12 }}>
          <div className="flex items-center gap-3">
            <span>{loadError}</span>
            <Button variant="ghost" size="sm" onClick={load}>Retry</Button>
          </div>
        </Alert>
      )}

      {!decisions && !loadError && (
        <div className="space-y-3">
          <Skeleton height={90} radius={12} />
          <Skeleton height={90} radius={12} />
        </div>
      )}

      {decisions?.length === 0 && (
        <Card padding={0}>
          <EmptyState icon={ShieldAlert} title="Nothing pending review" description="Every decision requiring human review has been resolved." />
        </Card>
      )}

      {decisions?.map((d) => (
        <Card key={d.id} padding={16} style={{ marginBottom: 12 }}>
          <div className="flex items-center justify-between gap-3 mb-2">
            <span className="flex items-center gap-2" style={{ color: "var(--pr-text-primary)", fontSize: 14, fontWeight: 500 }}>
              <AgentIdentity name={agentNames[d.agent_id] ?? d.agent_id} size="sm" />
              {agentNames[d.agent_id] ?? d.agent_id} &middot; {formatStatus(d.action)}
            </span>
            {/* Domain Generalization Milestone: Resource is the
                domain-agnostic secondary detail; Amount/Currency only
                render when the decision actually had them (a
                non-financial action, e.g. disable_user, has neither). */}
            {d.resource ? (
              <span style={{ color: "var(--pr-text-muted)", fontSize: 12, flexShrink: 0 }}>{d.resource}</span>
            ) : d.amount != null ? (
              <span style={{ color: "var(--pr-text-muted)", fontSize: 12, flexShrink: 0 }}>
                {d.amount.toLocaleString("en-US")} {d.currency}
              </span>
            ) : null}
          </div>
          <p style={{ color: "var(--pr-text-secondary)", fontSize: 13, marginBottom: 4 }}>
            {describeReason(d.reason) ?? "Sent to a human to decide."}
          </p>
          <p style={{ color: "var(--pr-text-disabled)", fontSize: 11, marginBottom: 10 }}>
            Submitted {new Date(d.created_at).toLocaleString()} &middot;{" "}
            <Link to={`/decisions/${d.id}`} style={{ color: "var(--pr-authority-blue)" }}>Full decision detail</Link>
          </p>

          {rowErrors[d.id] && (
            <p role="alert" style={{ color: "var(--pr-warning-amber)", fontSize: 12, marginBottom: 8 }}>
              {rowErrors[d.id]}
            </p>
          )}

          <div className="flex gap-2">
            <Button
              variant="tint-success"
              size="sm"
              disabled={lacksResolvePermission || resolvingId === d.id}
              pending={resolvingId === d.id}
              title={lacksResolvePermission ? `Requires ${RESOLVE_ROLE_LABEL}` : undefined}
              onClick={() => handleResolve(d, "approved")}
            >
              Approve
            </Button>
            <Button
              variant="tint-danger"
              size="sm"
              disabled={lacksResolvePermission || resolvingId === d.id}
              pending={resolvingId === d.id}
              title={lacksResolvePermission ? `Requires ${RESOLVE_ROLE_LABEL}` : undefined}
              onClick={() => handleResolve(d, "denied")}
            >
              Deny
            </Button>
          </div>
        </Card>
      ))}
    </div>
  );
}
