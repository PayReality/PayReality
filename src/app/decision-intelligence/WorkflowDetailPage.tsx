import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { FileCheck, HelpCircle, ListTree, Workflow as WorkflowIcon } from "lucide-react";
import { decisionIntelligenceApi } from "./api";
import { WorkflowStatusBadge } from "./components/StatusBadges";
import { describeApiError, formatStatus } from "../live/format";
import { useResourceSync } from "../services/resourceSync";
import type { Workflow, WorkflowOverview } from "./types";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { ConfirmButton } from "../components/ui/confirm-button";
import { PageHeader } from "../components/ui/page-header";
import { Skeleton } from "../components/ui/skeleton";

function MetricTile({ label, value }: { label: string; value: number | string }) {
  return (
    <div>
      <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>{label}</p>
      <p className="text-xl font-semibold" style={{ color: "var(--pr-text-primary)" }}>{value}</p>
    </div>
  );
}

export function WorkflowDetailPage() {
  const { workflowId } = useParams();
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [overview, setOverview] = useState<WorkflowOverview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  function load() {
    if (!workflowId) return;
    setLoadError(null);
    Promise.all([decisionIntelligenceApi.getWorkflow(workflowId), decisionIntelligenceApi.getWorkflowOverview(workflowId)])
      .then(([w, o]) => {
        setWorkflow(w);
        setOverview(o);
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading workflow")));
  }

  useEffect(load, [workflowId]);
  useResourceSync(["decision-intelligence"], load);

  async function toggleArchive() {
    if (!workflow) return;
    setPending(true);
    setMessage(null);
    try {
      const updated = await decisionIntelligenceApi.updateWorkflow(workflow.id, {
        status: workflow.status === "active" ? "archived" : "active",
      });
      setWorkflow(updated);
    } catch (e) {
      setMessage(describeApiError(e, "Update workflow"));
    } finally {
      setPending(false);
    }
  }

  if (!workflow && loadError) {
    return (
      <div className="p-8">
        <Alert severity="error" className="text-sm">
          <div className="flex items-center gap-3">
            <span>{loadError}</span>
            <Button variant="ghost" size="sm" onClick={load}>Retry</Button>
          </div>
        </Alert>
      </div>
    );
  }

  if (!workflow || !overview) {
    return (
      <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
        <Skeleton height={16} width={160} style={{ marginBottom: 24 }} />
        <Skeleton height={28} width="40%" style={{ marginBottom: 16 }} />
        <Skeleton height={100} style={{ marginBottom: 16 }} />
        <Skeleton height={160} />
      </div>
    );
  }

  return (
    <div className="p-8 max-w-5xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <Link to="/decision-intelligence" style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>&lt; All workflows</Link>

      <PageHeader
        title={workflow.name}
        status={<WorkflowStatusBadge status={workflow.status} />}
        description={workflow.description ?? undefined}
        secondaryAction={
          <ConfirmButton
            size="sm"
            variant={workflow.status === "active" ? "tint-danger" : "tint-success"}
            confirmLabel={workflow.status === "active" ? "Confirm archive" : "Confirm reactivate"}
            disabled={pending}
            onConfirm={toggleArchive}
          >
            {workflow.status === "active" ? "Archive workflow" : "Reactivate workflow"}
          </ConfirmButton>
        }
      />

      {message && <Alert severity="error" className="text-sm mb-4">{message}</Alert>}

      {workflow.business_context && (
        <Card className="mb-6">
          <h2 className="text-sm font-medium mb-1" style={{ color: "var(--pr-text-primary)" }}>Business context</h2>
          <p style={{ fontSize: 13, color: "var(--pr-text-secondary)" }}>{workflow.business_context}</p>
        </Card>
      )}

      <Card className="mb-6">
        <h2 className="text-sm font-medium mb-4" style={{ color: "var(--pr-text-primary)" }}>Overview</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-4">
          <MetricTile label="Cases" value={overview.case_count} />
          <MetricTile label="Unresolved cases" value={overview.unresolved_case_count} />
          <MetricTile label="Patterns" value={overview.pattern_count} />
          <MetricTile label="Answers awaiting approval" value={overview.answers_awaiting_approval} />
          <MetricTile label="Rules validated" value={overview.rules_validated} />
          <MetricTile label="Replays completed" value={overview.replays_completed} />
        </div>
        {Object.keys(overview.questions_by_status).length > 0 && (
          <div>
            <p className="text-xs font-medium mb-2" style={{ color: "var(--pr-text-muted)" }}>Priority questions by status</p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(overview.questions_by_status).map(([status, count]) => (
                <span
                  key={status}
                  className="text-xs px-2.5 py-1 rounded-full"
                  style={{ backgroundColor: "var(--pr-overlay-06)", color: "var(--pr-text-secondary)" }}
                >
                  {formatStatus(status)}: <strong>{count}</strong>
                </span>
              ))}
            </div>
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Link to={`/decision-intelligence/workflows/${workflow.id}/cases`}>
          <Card className="h-full transition-colors hover:border-opacity-50">
            <div className="flex items-center gap-2 mb-2">
              <FileCheck className="w-4 h-4" style={{ color: "var(--pr-authority-blue)" }} />
              <h3 className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>Cases</h3>
            </div>
            <p style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>
              Real business decision situations this workflow has handled -- the raw material patterns and questions are discovered from.
            </p>
          </Card>
        </Link>
        <Link to={`/decision-intelligence/workflows/${workflow.id}/patterns`}>
          <Card className="h-full transition-colors hover:border-opacity-50">
            <div className="flex items-center gap-2 mb-2">
              <ListTree className="w-4 h-4" style={{ color: "var(--pr-authority-blue)" }} />
              <h3 className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>Patterns</h3>
            </div>
            <p style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>
              Recurring uncertainty proposed from clusters of cases -- an expert's explanation for why they behave the way they do.
            </p>
          </Card>
        </Link>
        <Link to={`/decision-intelligence/workflows/${workflow.id}/questions`}>
          <Card className="h-full transition-colors hover:border-opacity-50">
            <div className="flex items-center gap-2 mb-2">
              <HelpCircle className="w-4 h-4" style={{ color: "var(--pr-authority-blue)" }} />
              <h3 className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>Priority questions</h3>
            </div>
            <p style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>
              Which question, if answered, resolves the most uncertainty -- ranked, scored, and tracked through to an operational rule.
            </p>
          </Card>
        </Link>
      </div>

      <div className="mt-4 flex items-center gap-2" style={{ fontSize: 12, color: "var(--pr-text-disabled)" }}>
        <WorkflowIcon className="w-3.5 h-3.5" />
        Created {new Date(workflow.created_at).toLocaleDateString()}
      </div>
    </div>
  );
}
