import { useEffect, useId, useState } from "react";
import { Link, useParams } from "react-router";
import { ListTree, Plus } from "lucide-react";
import { decisionIntelligenceApi } from "./api";
import { PatternReviewStatusBadge } from "./components/StatusBadges";
import { describeApiError, formatStatus } from "../live/format";
import { useResourceSync } from "../services/resourceSync";
import type { Pattern } from "./types";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Select } from "../components/ui/select";
import { SkeletonRows } from "../components/ui/skeleton";
import { PageHeader } from "../components/ui/page-header";
import { EmptyState } from "../components/ui/empty-state";
import { Table, TableHead, TableBody, TableRow, TableHeaderCell, TableCell } from "../components/ui/table";

const CATEGORIES = [
  "missing_facts",
  "unclear_policy",
  "conflicting_rules",
  "authority_gap",
  "context_interpretation",
  "human_judgement",
  "other",
];

export function PatternsPage() {
  const formId = useId();
  const { workflowId } = useParams();
  const [patterns, setPatterns] = useState<Pattern[] | null>(null);
  const [total, setTotal] = useState(0);
  const [reviewStatusFilter, setReviewStatusFilter] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("missing_facts");
  const [proposedExplanation, setProposedExplanation] = useState("");
  const [confidence, setConfidence] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  function load() {
    if (!workflowId) return;
    setLoadError(null);
    decisionIntelligenceApi
      .listPatterns({ workflow_id: workflowId, review_status: reviewStatusFilter || undefined, limit: 100 })
      .then((page) => {
        setPatterns(page.patterns);
        setTotal(page.total);
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading patterns")));
  }

  useEffect(load, [workflowId, reviewStatusFilter]);
  useResourceSync(["decision-intelligence"], load);

  async function handleCreate() {
    if (!workflowId || !name.trim() || !description.trim() || !proposedExplanation.trim()) {
      setCreateError("Name, description, and a proposed explanation are all required.");
      return;
    }
    setCreating(true);
    setCreateError(null);
    try {
      await decisionIntelligenceApi.createPattern({
        workflow_id: workflowId,
        name,
        description,
        category,
        proposed_explanation: proposedExplanation,
        confidence: confidence || undefined,
      });
      setName("");
      setDescription("");
      setProposedExplanation("");
      setConfidence("");
      setShowCreateForm(false);
      load();
    } catch (e) {
      setCreateError(describeApiError(e, "Create pattern"));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <Link to={`/decision-intelligence/workflows/${workflowId}`} style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
        &lt; Back to workflow
      </Link>
      <PageHeader
        title="Patterns"
        description="An expert-proposed explanation for why a cluster of cases behaves the way it does -- confidence is a manual judgement label, never a fabricated statistic."
        primaryAction={
          <Button onClick={() => setShowCreateForm((s) => !s)}>
            <Plus className="w-4 h-4 mr-1.5 inline" /> New pattern
          </Button>
        }
      />

      {showCreateForm && (
        <Card padding={20} className="mb-6">
          <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>New pattern</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
            <div>
              <label htmlFor={`${formId}-name`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Name</label>
              <input
                id={`${formId}-name`}
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
            </div>
            <div>
              <label htmlFor={`${formId}-category`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Category</label>
              <Select
                id={`${formId}-category`}
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              >
                {CATEGORIES.map((c) => <option key={c} value={c}>{formatStatus(c)}</option>)}
              </Select>
            </div>
            <div className="sm:col-span-2">
              <label htmlFor={`${formId}-description`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Description</label>
              <textarea
                id={`${formId}-description`}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
            </div>
            <div className="sm:col-span-2">
              <label htmlFor={`${formId}-explanation`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Proposed explanation</label>
              <textarea
                id={`${formId}-explanation`}
                value={proposedExplanation}
                onChange={(e) => setProposedExplanation(e.target.value)}
                rows={2}
                placeholder="Why do these cases behave this way?"
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
            </div>
            <div>
              <label htmlFor={`${formId}-confidence`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                Confidence <span style={{ fontWeight: 400, color: "var(--pr-text-disabled)" }}>(optional, a judgement label)</span>
              </label>
              <Select
                id={`${formId}-confidence`}
                value={confidence}
                onChange={(e) => setConfidence(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              >
                <option value="">Not set</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </Select>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={handleCreate} disabled={creating} pending={creating}>{creating ? "Creating..." : "Create pattern"}</Button>
            <Button variant="ghost" onClick={() => setShowCreateForm(false)}>Cancel</Button>
          </div>
          {createError && <Alert severity="error" className="text-sm mt-3">{createError}</Alert>}
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-3 mb-3">
        <Select
          value={reviewStatusFilter}
          onChange={(e) => setReviewStatusFilter(e.target.value)}
          aria-label="Filter by review status"
          className="px-3 py-2 rounded-lg border text-sm"
          style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
        >
          <option value="">All review statuses</option>
          <option value="proposed">Proposed</option>
          <option value="reviewed">Reviewed</option>
          <option value="confirmed">Confirmed</option>
          <option value="rejected">Rejected</option>
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
          <Table>
            <TableHead>
              <TableRow style={{ color: "var(--pr-text-muted)", textAlign: "left", fontSize: 12, borderTop: "none", borderBottom: "1px solid var(--pr-overlay-05)" }}>
                <TableHeaderCell>Name</TableHeaderCell>
                <TableHeaderCell>Category</TableHeaderCell>
                <TableHeaderCell>Confidence</TableHeaderCell>
                <TableHeaderCell>Review status</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {!patterns && (
                <TableRow>
                  <TableCell colSpan={4} truncate={false}><SkeletonRows count={4} height={20} /></TableCell>
                </TableRow>
              )}
              {patterns?.map((p) => (
                <TableRow
                  key={p.id}
                  className="transition-colors"
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--pr-bg-hover)")}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                >
                  <TableCell truncate={false}>
                    <Link to={`/decision-intelligence/workflows/${workflowId}/patterns/${p.id}`} style={{ color: "var(--pr-authority-blue)" }}>
                      {p.name}
                    </Link>
                  </TableCell>
                  <TableCell truncate={false}>
                    <span
                      className="text-xs px-2 py-0.5 rounded-full"
                      style={{ backgroundColor: "var(--pr-overlay-06)", color: "var(--pr-text-secondary)" }}
                    >
                      {formatStatus(p.category)}
                    </span>
                  </TableCell>
                  <TableCell style={{ color: p.confidence ? "var(--pr-text-secondary)" : "var(--pr-text-disabled)", fontStyle: p.confidence ? "normal" : "italic" }}>
                    {p.confidence ? formatStatus(p.confidence) : "Not set"}
                  </TableCell>
                  <TableCell truncate={false}><PatternReviewStatusBadge status={p.review_status} /></TableCell>
                </TableRow>
              ))}
              {patterns?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} truncate={false}>
                    <EmptyState
                      icon={ListTree}
                      title={reviewStatusFilter ? "No patterns match this filter" : "No patterns yet"}
                      description={reviewStatusFilter ? "Try a different review status." : "Propose the first explanation for a cluster of cases."}
                    />
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </Card>

      <div className="mt-3" style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>
        {total} pattern{total === 1 ? "" : "s"} total
      </div>
    </div>
  );
}
