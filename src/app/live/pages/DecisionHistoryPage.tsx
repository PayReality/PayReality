import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { FlaskConical, History } from "lucide-react";
import { decisionsApi } from "../decisionsApi";
import { agentsApi } from "../../agents/api";
import { policyStudioApi } from "../../policy-studio/api";
import { describeApiError, describeReason, formatStatus } from "../format";
import { describeSource, describeSourceCompact } from "../components/decisionDisplay";
import { ManualDecisionSheet } from "../components/ManualDecisionSheet";
import { HelpIcon } from "../../help/HelpIcon";
import { Card } from "../../components/ui/card";
import { Alert } from "../../components/ui/alert";
import { Button } from "../../components/ui/button";
import { Select } from "../../components/ui/select";
import { SkeletonRows } from "../../components/ui/skeleton";
import { useResourceSync } from "../../services/resourceSync";
import { PageHeader } from "../../components/ui/page-header";
import { EmptyState } from "../../components/ui/empty-state";
import { DecisionOutcomeBadge } from "../../components/ui/decision-outcome-badge";
import { AgentIdentity } from "../../components/ui/agent-identity";
import type { DecisionHistoryItem, LiveAgent } from "../types";

const PAGE_SIZE = 25;

// Core Product Experience Redesign, section 4: "THIS IS THE MOST
// IMPORTANT REDESIGN." Replaces LiveTestIntent.tsx as the /decisions
// landing surface -- previously a manual-submission form with a single
// decision's detail bolted underneath, conceptually still a test
// harness. This page is operational history first
// (GET /v1/decisions/history), with manual testing demoted to an
// explicitly-labeled secondary action (section 4B) and a dedicated
// causal-narrative Decision Detail page (section 4C, DecisionDetailPage.tsx)
// for any one row.
export function DecisionHistoryPage() {
  const navigate = useNavigate();

  const [decisions, setDecisions] = useState<DecisionHistoryItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [outcomeFilter, setOutcomeFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [agentFilter, setAgentFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [resourceFilter, setResourceFilter] = useState("");

  const [agents, setAgents] = useState<LiveAgent[]>([]);
  const [actions, setActions] = useState<string[]>([]);

  const [sheetOpen, setSheetOpen] = useState(false);
  const testTriggerRef = useRef<HTMLButtonElement>(null);

  function load() {
    setLoadError(null);
    decisionsApi
      .history({
        limit: PAGE_SIZE,
        offset,
        outcome: outcomeFilter || undefined,
        source: sourceFilter || undefined,
        agent_id: agentFilter || undefined,
        action: actionFilter || undefined,
        resource: resourceFilter.trim() || undefined,
      })
      .then((r) => {
        setDecisions(r.decisions);
        setTotal(r.total);
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading decisions")));
  }

  useEffect(load, [offset, outcomeFilter, sourceFilter, agentFilter, actionFilter, resourceFilter]);
  // Milestone 13 Phase 6A: a decision resolved elsewhere (Pending
  // Review, another tab) or a new manual test submitted from this
  // page's own drawer should refresh this list.
  useResourceSync(["decisions", "agents"], load);

  useEffect(() => {
    agentsApi.list({ limit: 200 }).then((p) => setAgents(p.agents)).catch(() => {});
    policyStudioApi.getVocabulary().then((v) => setActions(v.actions)).catch(() => {});
  }, []);

  function resetOffsetAnd<T>(setter: (v: T) => void) {
    return (v: T) => { setOffset(0); setter(v); };
  }

  return (
    <div className="p-8 max-w-6xl mx-auto" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <PageHeader
        title="Decisions"
        description="Every request an AI agent has made to act, and what your rules decided: approved, blocked, or sent to a human, each with the evidence it produced."
        status={<HelpIcon articleId="runtime_decision" />}
        secondaryAction={
          <Link to="/decisions/queue" style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>
            Pending review
          </Link>
        }
        primaryAction={
          <Button ref={testTriggerRef} variant="ghost" size="sm" onClick={() => setSheetOpen(true)}>
            <span className="flex items-center gap-1.5"><FlaskConical className="w-3.5 h-3.5" /> Test Runtime Authority</span>
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <Select
          value={outcomeFilter}
          onChange={(e) => resetOffsetAnd(setOutcomeFilter)(e.target.value)}
          aria-label="Filter by outcome"
          className="px-3 py-2 rounded-lg border text-sm"
          style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
        >
          <option value="">All outcomes</option>
          <option value="ALLOW">Allow</option>
          <option value="DENY">Deny</option>
          <option value="HUMAN_REVIEW">Human review</option>
        </Select>
        <Select
          value={agentFilter}
          onChange={(e) => resetOffsetAnd(setAgentFilter)(e.target.value)}
          aria-label="Filter by agent"
          className="px-3 py-2 rounded-lg border text-sm"
          style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
        >
          <option value="">All agents</option>
          {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </Select>
        <Select
          value={actionFilter}
          onChange={(e) => resetOffsetAnd(setActionFilter)(e.target.value)}
          aria-label="Filter by action"
          className="px-3 py-2 rounded-lg border text-sm"
          style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
        >
          <option value="">All actions</option>
          {actions.map((a) => <option key={a} value={a}>{formatStatus(a)}</option>)}
        </Select>
        <input
          value={resourceFilter}
          onChange={(e) => resetOffsetAnd(setResourceFilter)(e.target.value)}
          placeholder="Resource contains..."
          aria-label="Filter by resource"
          className="px-3 py-2 rounded-lg border text-sm"
          style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)", minWidth: 180 }}
        />
        <Select
          value={sourceFilter}
          onChange={(e) => resetOffsetAnd(setSourceFilter)(e.target.value)}
          aria-label="Filter by source"
          className="px-3 py-2 rounded-lg border text-sm"
          style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
        >
          <option value="">All sources</option>
          <option value="runtime">Runtime</option>
          <option value="manual_test">Manual test</option>
        </Select>
      </div>

      {loadError && (
        <Alert severity="warning" style={{ marginBottom: 16 }}>
          <div className="flex items-center gap-3">
            <span>{loadError}</span>
            <Button variant="ghost" size="sm" onClick={load}>Retry</Button>
          </div>
        </Alert>
      )}

      <Card padding={0} style={{ overflow: "hidden" }}>
        <div className="overflow-x-auto">
        <table className="w-full text-sm" style={{ color: "var(--pr-text-primary)" }}>
          <thead>
            <tr style={{ color: "var(--pr-text-muted)", textAlign: "left", fontSize: 12, borderBottom: "1px solid var(--pr-overlay-05)" }}>
              <th className="p-3">Time</th>
              <th className="p-3">Agent</th>
              <th className="p-3">Action</th>
              <th className="p-3">Resource</th>
              <th className="p-3">Outcome</th>
              <th className="p-3">Policy</th>
              <th className="p-3">Source</th>
            </tr>
          </thead>
          <tbody>
            {!decisions && (
              <tr><td colSpan={7} className="p-3"><SkeletonRows count={6} height={20} /></td></tr>
            )}
            {decisions?.map((d) => (
              <tr
                key={d.id}
                tabIndex={0}
                role="button"
                aria-label={`View decision: ${formatStatus(d.action)}, ${formatStatus(d.outcome)}`}
                className="transition-colors cursor-pointer"
                style={{ borderTop: "1px solid var(--pr-overlay-05)" }}
                onClick={() => navigate(`/decisions/${d.id}`)}
                onKeyDown={(e) => { if (e.key === "Enter") navigate(`/decisions/${d.id}`); }}
                onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--pr-bg-hover)")}
                onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
              >
                <td className="p-3" style={{ color: "var(--pr-text-muted)", fontSize: 12, whiteSpace: "nowrap" }}>
                  {new Date(d.created_at).toLocaleString()}
                </td>
                <td className="p-3">
                  <span className="flex items-center gap-2">
                    <AgentIdentity name={d.agent_name ?? d.agent_id} size="sm" />
                    {d.agent_name ?? d.agent_id}
                  </span>
                </td>
                <td className="p-3">{formatStatus(d.action)}</td>
                <td className="p-3" style={{ color: "var(--pr-text-muted)" }}>{d.resource ?? "-"}</td>
                <td className="p-3">
                  <DecisionOutcomeBadge outcome={d.outcome} size="sm" />
                  {d.human_review_state === "pending" && (
                    <span className="ml-2 text-[10px] font-semibold uppercase tracking-wide" style={{ color: "var(--pr-warning-amber)" }}>
                      Awaiting review
                    </span>
                  )}
                </td>
                <td className="p-3" style={{ color: "var(--pr-text-muted)", fontSize: 12 }}>
                  {d.matched_policy_name ?? (describeReason(d.reason) ? describeReason(d.reason) : "-")}
                </td>
                <td className="p-3" style={{ color: "var(--pr-text-disabled)", fontSize: 12, whiteSpace: "nowrap" }} title={describeSource(d.source)}>
                  {describeSourceCompact(d.source)}
                </td>
              </tr>
            ))}
            {decisions?.length === 0 && (() => {
              const noFilters = !outcomeFilter && !sourceFilter && !agentFilter && !actionFilter && !resourceFilter;
              return (
                <tr>
                  <td colSpan={7}>
                    <EmptyState
                      icon={History}
                      title={total === 0 && noFilters ? "No decisions yet" : "No decisions match these filters"}
                      description={
                        total === 0 && noFilters
                          ? "Once an agent requests to act, it'll show up here."
                          : "Try different filters."
                      }
                      action={
                        total === 0 && noFilters ? (
                          <button onClick={() => setSheetOpen(true)} style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>
                            Test Runtime Authority to see one now &rarr;
                          </button>
                        ) : undefined
                      }
                    />
                  </td>
                </tr>
              );
            })()}
          </tbody>
        </table>
        </div>
      </Card>

      <div className="flex items-center justify-between mt-3" style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>
        <span>{total} decision{total === 1 ? "" : "s"} total</span>
        <div className="flex gap-2">
          <button
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            disabled={offset === 0}
            className="px-3 py-1.5 rounded-lg disabled:opacity-30"
            style={{ backgroundColor: "var(--pr-overlay-05)", color: "var(--pr-text-secondary)" }}
          >
            Previous
          </button>
          <button
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
            disabled={offset + PAGE_SIZE >= total}
            className="px-3 py-1.5 rounded-lg disabled:opacity-30"
            style={{ backgroundColor: "var(--pr-overlay-05)", color: "var(--pr-text-secondary)" }}
          >
            Next
          </button>
        </div>
      </div>

      <ManualDecisionSheet open={sheetOpen} onOpenChange={setSheetOpen} onSettled={load} triggerRef={testTriggerRef} />
    </div>
  );
}
