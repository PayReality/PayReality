import { useEffect, useId, useState } from "react";
import { Link } from "react-router";
import { Compass, Plus } from "lucide-react";
import { decisionIntelligenceApi } from "./api";
import { WorkflowStatusBadge } from "./components/StatusBadges";
import { describeApiError } from "../live/format";
import { useResourceSync } from "../services/resourceSync";
import type { Workflow } from "./types";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Select } from "../components/ui/select";
import { SkeletonRows } from "../components/ui/skeleton";
import { PageHeader } from "../components/ui/page-header";
import { EmptyState } from "../components/ui/empty-state";
import { Table, TableHead, TableBody, TableRow, TableHeaderCell, TableCell } from "../components/ui/table";

// This is the Decision Intelligence nav's landing page. The backend has
// no cross-workflow aggregate report endpoint (only GET .../workflows/
// {id}/overview, per-workflow -- see workflows.py) -- so this page is a
// workflow picker/list, not an aggregate dashboard across every
// workflow. Selecting a workflow is what reaches the real overview
// metrics, on WorkflowDetailPage.
export function WorkflowsListPage() {
  const formId = useId();
  const [workflows, setWorkflows] = useState<Workflow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);

  function load() {
    setLoadError(null);
    decisionIntelligenceApi
      .listWorkflows({ status: statusFilter || undefined, limit: 100 })
      .then((page) => {
        setWorkflows(page.workflows);
        setTotal(page.total);
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading workflows")));
  }

  useEffect(load, [statusFilter]);
  useResourceSync(["decision-intelligence"], load);

  async function handleCreate() {
    if (!newName.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      await decisionIntelligenceApi.createWorkflow({ name: newName, description: newDescription || undefined });
      setNewName("");
      setNewDescription("");
      setShowCreateForm(false);
      load();
    } catch (e) {
      setCreateError(describeApiError(e, "Create workflow"));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <PageHeader
        title="Decision Intelligence"
        description="Discover the smallest, highest-value set of questions a workflow needs answered to resolve recurring uncertainty: real cases surface patterns, patterns motivate priority questions, an approved answer becomes an inspectable decision rule, and a replay shows how that rule would have agreed or disagreed with real past decisions."
        primaryAction={
          <Button onClick={() => setShowCreateForm((s) => !s)}>
            <Plus className="w-4 h-4 mr-1.5 inline" /> New workflow
          </Button>
        }
      />

      {showCreateForm && (
        <Card padding={20} className="mb-6">
          <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>New workflow</h2>
          <div className="grid grid-cols-1 gap-3 mb-3">
            <div>
              <label htmlFor={`${formId}-name`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                Name
              </label>
              <input
                id={`${formId}-name`}
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Refund approvals"
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
            </div>
            <div>
              <label htmlFor={`${formId}-description`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                Description <span style={{ fontWeight: 400, color: "var(--pr-text-disabled)" }}>(optional)</span>
              </label>
              <input
                id={`${formId}-description`}
                value={newDescription}
                onChange={(e) => setNewDescription(e.target.value)}
                placeholder="The recurring business decision this workflow is about"
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={handleCreate} disabled={creating || !newName.trim()} pending={creating}>
              {creating ? "Creating..." : "Create workflow"}
            </Button>
            <Button variant="ghost" onClick={() => setShowCreateForm(false)}>Cancel</Button>
          </div>
          {createError && <Alert severity="error" className="text-sm mt-3">{createError}</Alert>}
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-3 mb-3">
        <Select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Filter by status"
          className="px-3 py-2 rounded-lg border text-sm"
          style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="archived">Archived</option>
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
                <TableHeaderCell>Description</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell>Created</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {!workflows && (
                <TableRow>
                  <TableCell colSpan={4} truncate={false}>
                    <SkeletonRows count={4} height={20} />
                  </TableCell>
                </TableRow>
              )}
              {workflows?.map((w) => (
                <TableRow
                  key={w.id}
                  className="transition-colors"
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--pr-bg-hover)")}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                >
                  <TableCell truncate={false}>
                    <Link to={`/decision-intelligence/workflows/${w.id}`} style={{ color: "var(--pr-authority-blue)" }}>
                      {w.name}
                    </Link>
                  </TableCell>
                  <TableCell style={{ color: "var(--pr-text-muted)" }}>{w.description || "-"}</TableCell>
                  <TableCell truncate={false}><WorkflowStatusBadge status={w.status} /></TableCell>
                  <TableCell style={{ color: "var(--pr-text-muted)" }} truncate={false}>
                    {new Date(w.created_at).toLocaleDateString()}
                  </TableCell>
                </TableRow>
              ))}
              {workflows?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} truncate={false}>
                    <EmptyState
                      icon={Compass}
                      title={statusFilter ? "No workflows match this filter" : "No workflows yet"}
                      description={
                        statusFilter
                          ? "Try a different status."
                          : "Create the first workflow for a recurring business decision you want to systematically understand."
                      }
                      action={
                        !statusFilter ? (
                          <button onClick={() => setShowCreateForm(true)} style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>
                            New workflow &rarr;
                          </button>
                        ) : undefined
                      }
                    />
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </Card>

      <div className="mt-3" style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>
        {total} workflow{total === 1 ? "" : "s"} total
      </div>
    </div>
  );
}
