import { useEffect, useId, useState } from "react";
import { Link, useParams } from "react-router";
import { FileCheck, Plus } from "lucide-react";
import { decisionIntelligenceApi } from "./api";
import { CaseStatusBadge } from "./components/StatusBadges";
import { describeApiError } from "../live/format";
import { useResourceSync } from "../services/resourceSync";
import type { Case } from "./types";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Select } from "../components/ui/select";
import { SkeletonRows } from "../components/ui/skeleton";
import { PageHeader } from "../components/ui/page-header";
import { EmptyState } from "../components/ui/empty-state";
import { Table, TableHead, TableBody, TableRow, TableHeaderCell, TableCell } from "../components/ui/table";

const PAGE_SIZE = 25;

export function CasesPage() {
  const formId = useId();
  const { workflowId } = useParams();
  const [cases, setCases] = useState<Case[] | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [q, setQ] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);

  const [showCreateForm, setShowCreateForm] = useState(false);
  const [externalRef, setExternalRef] = useState("");
  const [factsJson, setFactsJson] = useState("{}");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  function load() {
    if (!workflowId) return;
    setLoadError(null);
    decisionIntelligenceApi
      .listCases({ workflow_id: workflowId, status: statusFilter || undefined, limit: PAGE_SIZE, offset })
      .then((page) => {
        setCases(page.cases);
        setTotal(page.total);
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading cases")));
  }

  useEffect(load, [workflowId, statusFilter, offset]);
  useResourceSync(["decision-intelligence"], load);

  async function handleCreate() {
    if (!workflowId) return;
    let facts: Record<string, unknown>;
    try {
      facts = factsJson.trim() ? JSON.parse(factsJson) : {};
    } catch {
      setCreateError("Facts must be valid JSON (e.g. {\"amount\": 1200}).");
      return;
    }
    setCreating(true);
    setCreateError(null);
    try {
      await decisionIntelligenceApi.createCase({ workflow_id: workflowId, external_ref: externalRef || undefined, facts });
      setExternalRef("");
      setFactsJson("{}");
      setShowCreateForm(false);
      load();
    } catch (e) {
      setCreateError(describeApiError(e, "Create case"));
    } finally {
      setCreating(false);
    }
  }

  // The backend's list endpoint (cases.py) filters by workflow_id/status
  // only -- there is no server-side free-text search over `facts`/
  // `external_ref`. This filters the currently-loaded page client-side,
  // a real (if page-scoped) search rather than a fake no-op input.
  const visibleCases = cases?.filter((c) => {
    if (!q.trim()) return true;
    const needle = q.toLowerCase();
    return (
      (c.external_ref ?? "").toLowerCase().includes(needle) ||
      JSON.stringify(c.facts).toLowerCase().includes(needle)
    );
  });

  return (
    <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <Link to={`/decision-intelligence/workflows/${workflowId}`} style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
        &lt; Back to workflow
      </Link>
      <PageHeader
        title="Cases"
        description="Real instances of this workflow's recurring decision -- the raw material patterns and priority questions are discovered from."
        primaryAction={
          <Button onClick={() => setShowCreateForm((s) => !s)}>
            <Plus className="w-4 h-4 mr-1.5 inline" /> New case
          </Button>
        }
      />

      {showCreateForm && (
        <Card padding={20} className="mb-6">
          <h2 className="text-sm font-medium mb-3" style={{ color: "var(--pr-text-primary)" }}>New case</h2>
          <div className="grid grid-cols-1 gap-3 mb-3">
            <div>
              <label htmlFor={`${formId}-ref`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                External reference <span style={{ fontWeight: 400, color: "var(--pr-text-disabled)" }}>(optional)</span>
              </label>
              <input
                id={`${formId}-ref`}
                value={externalRef}
                onChange={(e) => setExternalRef(e.target.value)}
                placeholder="REQ-2026-0417"
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
            </div>
            <div>
              <label htmlFor={`${formId}-facts`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                Facts <span style={{ fontWeight: 400, color: "var(--pr-text-disabled)" }}>(JSON -- this workflow has no fixed case schema)</span>
              </label>
              <textarea
                id={`${formId}-facts`}
                value={factsJson}
                onChange={(e) => setFactsJson(e.target.value)}
                rows={3}
                className="w-full px-3 py-2 rounded-lg border text-sm font-mono"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={handleCreate} disabled={creating} pending={creating}>
              {creating ? "Creating..." : "Create case"}
            </Button>
            <Button variant="ghost" onClick={() => setShowCreateForm(false)}>Cancel</Button>
          </div>
          {createError && <Alert severity="error" className="text-sm mt-3">{createError}</Alert>}
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-3 mb-3">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search this page (reference or facts)..."
          aria-label="Search cases on this page"
          className="px-3 py-2 rounded-lg border text-sm"
          style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)", minWidth: 260 }}
        />
        <Select
          value={statusFilter}
          onChange={(e) => { setOffset(0); setStatusFilter(e.target.value); }}
          aria-label="Filter by status"
          className="px-3 py-2 rounded-lg border text-sm"
          style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
        >
          <option value="">All statuses</option>
          <option value="open">Open</option>
          <option value="resolved">Resolved</option>
          <option value="escalated">Escalated</option>
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
                <TableHeaderCell>Reference</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell>Outcome</TableHeaderCell>
                <TableHeaderCell>Escalated</TableHeaderCell>
                <TableHeaderCell>Created</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {!cases && (
                <TableRow>
                  <TableCell colSpan={5} truncate={false}><SkeletonRows count={5} height={20} /></TableCell>
                </TableRow>
              )}
              {visibleCases?.map((c) => (
                <TableRow
                  key={c.id}
                  className="transition-colors"
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--pr-bg-hover)")}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                >
                  <TableCell truncate={false}>
                    <Link to={`/decision-intelligence/workflows/${workflowId}/cases/${c.id}`} style={{ color: "var(--pr-authority-blue)" }}>
                      {c.external_ref || c.id.slice(0, 8)}
                    </Link>
                  </TableCell>
                  <TableCell truncate={false}><CaseStatusBadge status={c.status} /></TableCell>
                  <TableCell style={{ color: "var(--pr-text-muted)" }}>{c.outcome || "-"}</TableCell>
                  <TableCell style={{ color: "var(--pr-text-muted)" }}>{c.escalation_reason ? "Yes" : "No"}</TableCell>
                  <TableCell style={{ color: "var(--pr-text-muted)" }} truncate={false}>{new Date(c.created_at).toLocaleDateString()}</TableCell>
                </TableRow>
              ))}
              {visibleCases?.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} truncate={false}>
                    <EmptyState
                      icon={FileCheck}
                      title={q || statusFilter ? "No cases match" : "No cases yet"}
                      description={q || statusFilter ? "Try a different search or status." : "Record the first real case for this workflow."}
                    />
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </Card>

      <div className="flex items-center justify-between mt-3" style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>
        <span>{total} case{total === 1 ? "" : "s"} total</span>
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
    </div>
  );
}
