import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Bot, Plus } from "lucide-react";
import { agentsApi } from "./api";
import { AgentStatusBadge } from "./components/AgentStatusBadge";
import { HealthDot } from "./components/HealthDot";
import { describeApiError } from "../live/format";
import { NextStepGuidance } from "../help/NextStepGuidance";
import type { LiveAgent } from "../live/types";
import { useResourceSync } from "../services/resourceSync";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Select } from "../components/ui/select";
import { SkeletonRows } from "../components/ui/skeleton";
import { useToast } from "../components/ui/toast";
import { ConfirmButton } from "../components/ui/confirm-button";
import { PageHeader } from "../components/ui/page-header";
import { EmptyState } from "../components/ui/empty-state";
import { AgentIdentity } from "../components/ui/agent-identity";

const BULK_ACTION_LABEL: Record<"suspend" | "activate" | "retire" | "rotate", string> = {
  suspend: "suspend",
  activate: "activate",
  retire: "retire",
  rotate: "request rotation for",
};

const PAGE_SIZE = 25;

export function AgentDirectoryPage() {
  const { notify } = useToast();
  const [agents, setAgents] = useState<LiveAgent[] | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [principalById, setPrincipalById] = useState<Record<string, string>>({});

  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [environmentFilter, setEnvironmentFilter] = useState("");

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmingBulkAction, setConfirmingBulkAction] = useState<"suspend" | "activate" | "retire" | "rotate" | null>(null);
  const [pendingRowId, setPendingRowId] = useState<string | null>(null);

  const [justActivatedName, setJustActivatedName] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  function loadPrincipals() {
    agentsApi
      .listPrincipals()
      .then((ps) => setPrincipalById(Object.fromEntries(ps.map((p) => [p.id, p.name]))))
      .catch(() => {});
  }

  function loadAgents() {
    setLoadError(null);
    agentsApi
      .list({ q: q || undefined, status: statusFilter || undefined, environment: environmentFilter || undefined, limit: PAGE_SIZE, offset })
      .then((page) => {
        setAgents(page.agents);
        setTotal(page.total);
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading agents")));
  }

  useEffect(loadPrincipals, []);
  useEffect(loadAgents, [q, statusFilter, environmentFilter, offset]);
  // Milestone 13 Phase 6A: this page's own filters already refetch on
  // change; this additionally catches an agent mutated from a
  // different tab (e.g. AgentDetailPage open elsewhere) or this tab
  // having been left open and revisited.
  useResourceSync(["agents", "certificates"], loadAgents);

  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function runRowAction(action: "activate" | "suspend" | "retire", agentId: string) {
    setPendingRowId(agentId);
    try {
      if (action === "activate") {
        await agentsApi.activate(agentId);
        setJustActivatedName(agents?.find((a) => a.id === agentId)?.name ?? "Agent");
      }
      if (action === "suspend") await agentsApi.suspend(agentId);
      if (action === "retire") await agentsApi.retire(agentId);
      loadAgents();
    } catch (e) {
      notify(describeApiError(e, "Action"), "error");
    } finally {
      setPendingRowId(null);
    }
  }

  async function runBulkAction(action: "suspend" | "activate" | "retire" | "rotate") {
    const ids = Array.from(selected);
    if (ids.length === 0) return;
    try {
      const result =
        action === "suspend" ? await agentsApi.bulkSuspend(ids)
        : action === "activate" ? await agentsApi.bulkActivate(ids)
        : action === "retire" ? await agentsApi.bulkRetire(ids)
        : await agentsApi.bulkRequestRotation(ids);
      notify(
        `${result.succeeded} succeeded, ${result.failed} failed.`,
        result.failed > 0 ? "warning" : "success"
      );
      setSelected(new Set());
      loadAgents();
    } catch (e) {
      notify(describeApiError(e, "Bulk action"), "error");
    } finally {
      setConfirmingBulkAction(null);
    }
  }

  function toggleSelectAll() {
    setSelected((prev) => {
      if (agents && agents.every((a) => prev.has(a.id))) return new Set();
      return new Set(agents?.map((a) => a.id) ?? []);
    });
  }

  const rowActionFor = (agent: LiveAgent): { label: string; action: "activate" | "suspend" | "retire" } | null => {
    if (agent.status === "registered" || agent.status === "suspended") return { label: "Activate", action: "activate" };
    if (agent.status === "active") return { label: "Suspend", action: "suspend" };
    return null;
  };

  return (
    <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <PageHeader
        title="Agents"
        description="Every AI worker operating under this platform, managed the same way an enterprise manages a human workforce identity and delegates authority to it: registered, activated, suspended, rotated, retired, or revoked, with a signed audit trail for every change."
        primaryAction={
          <Link
            to="/agents/register"
            className="px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 flex-shrink-0"
            style={{ backgroundColor: "var(--pr-authority-blue)", color: "#fff" }}
          >
            <Plus className="w-4 h-4" /> Register agent
          </Link>
        }
      />

      {justActivatedName && (
        <NextStepGuidance
          message={`"${justActivatedName}" is now active and can sign real Intents. Try Test Runtime Authority to see it get checked against your rules.`}
          actionLabel="Go to Decisions"
          actionPath="/decisions"
        />
      )}

      <div className="flex flex-wrap items-center gap-3 mb-3">
        <input
          value={q}
          onChange={(e) => { setOffset(0); setQ(e.target.value); }}
          placeholder="Search by name..."
          aria-label="Search agents by name"
          className="px-3 py-2 rounded-lg border text-sm"
          style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)", minWidth: 220 }}
        />
        <Select
          value={statusFilter}
          onChange={(e) => { setOffset(0); setStatusFilter(e.target.value); }}
          aria-label="Filter by status"
          className="px-3 py-2 rounded-lg border text-sm"
          style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
        >
          <option value="">All statuses</option>
          <option value="registered">Registered</option>
          <option value="active">Active</option>
          <option value="suspended">Suspended</option>
          <option value="revoked">Revoked</option>
          <option value="retired">Retired</option>
        </Select>
        <input
          value={environmentFilter}
          onChange={(e) => { setOffset(0); setEnvironmentFilter(e.target.value); }}
          placeholder="Environment (e.g. production)"
          aria-label="Filter by environment"
          className="px-3 py-2 rounded-lg border text-sm"
          style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)", minWidth: 200 }}
        />

        {selected.size > 0 && (
          <div className="flex items-center gap-2 ml-auto">
            <span style={{ fontSize: 12, color: "var(--pr-text-muted)" }}>{selected.size} selected</span>
            {confirmingBulkAction ? (
              <span className="flex items-center gap-2">
                <span style={{ fontSize: 12, color: "var(--pr-warning-amber)" }}>
                  {BULK_ACTION_LABEL[confirmingBulkAction]} {selected.size} agent{selected.size === 1 ? "" : "s"}?
                </span>
                <Button variant="danger" size="sm" onClick={() => runBulkAction(confirmingBulkAction)}>Confirm</Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirmingBulkAction(null)}>Cancel</Button>
              </span>
            ) : (
              <>
                <Button variant="tint-success" size="sm" onClick={() => setConfirmingBulkAction("activate")}>Activate many</Button>
                <button onClick={() => setConfirmingBulkAction("suspend")} className="px-3 py-1.5 rounded-lg text-xs" style={{ backgroundColor: "rgba(245,158,11,0.1)", color: "var(--pr-warning-amber)" }}>Suspend many</button>
                <button onClick={() => setConfirmingBulkAction("retire")} className="px-3 py-1.5 rounded-lg text-xs" style={{ backgroundColor: "var(--pr-overlay-06)", color: "var(--pr-text-secondary)" }}>Retire many</button>
                <button onClick={() => setConfirmingBulkAction("rotate")} className="px-3 py-1.5 rounded-lg text-xs" style={{ backgroundColor: "rgba(77,124,254,0.1)", color: "var(--pr-authority-blue)" }}>Request rotation</button>
              </>
            )}
          </div>
        )}
      </div>

      {loadError && (
        <Alert severity="warning" style={{ marginBottom: 16 }}>
          <div className="flex items-center gap-3">
            <span>{loadError}</span>
            <Button variant="ghost" size="sm" onClick={loadAgents}>Retry</Button>
          </div>
        </Alert>
      )}

      <Card padding={0} style={{ overflow: "hidden" }}>
        <div className="overflow-x-auto">
        <table className="w-full text-sm" style={{ color: "var(--pr-text-primary)" }}>
          <thead>
            <tr style={{ color: "var(--pr-text-muted)", textAlign: "left", fontSize: 12, borderBottom: "1px solid var(--pr-overlay-05)" }}>
              <th className="p-3" style={{ width: 32 }}>
                {agents && agents.length > 0 && (
                  <input
                    type="checkbox"
                    checked={agents.every((a) => selected.has(a.id))}
                    onChange={toggleSelectAll}
                    aria-label="Select all agents on this page"
                  />
                )}
              </th>
              <th className="p-3">Name</th>
              <th className="p-3">Principal</th>
              <th className="p-3">Owner</th>
              <th className="p-3">Environment</th>
              <th className="p-3">Status</th>
              <th className="p-3">Certificate</th>
              <th className="p-3">Last seen</th>
              <th className="p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {!agents && (
              <tr>
                <td colSpan={9} className="p-3">
                  <SkeletonRows count={5} height={20} />
                </td>
              </tr>
            )}
            {agents?.map((a) => {
              const rowAction = rowActionFor(a);
              return (
                <tr
                  key={a.id}
                  className="transition-colors"
                  style={{ borderTop: "1px solid var(--pr-overlay-05)" }}
                  onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = "var(--pr-bg-hover)")}
                  onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = "transparent")}
                >
                  <td className="p-3">
                    <input
                      type="checkbox"
                      checked={selected.has(a.id)}
                      onChange={() => toggleSelected(a.id)}
                      aria-label={`Select ${a.name}`}
                    />
                  </td>
                  <td className="p-3">
                    <Link to={`/agents/${a.id}`} className="flex items-center gap-2" style={{ color: "var(--pr-authority-blue)" }}>
                      <AgentIdentity name={a.name} status={a.status} size="sm" />
                      {a.name}
                    </Link>
                  </td>
                  <td className="p-3" style={{ color: "var(--pr-text-muted)" }}>{principalById[a.acting_for_principal_id] ?? "-"}</td>
                  <td className="p-3" style={{ color: "var(--pr-text-muted)" }}>{a.owner ?? "-"}</td>
                  <td className="p-3" style={{ color: "var(--pr-text-muted)" }}>{a.environment ?? "-"}</td>
                  <td className="p-3"><AgentStatusBadge status={a.status} /></td>
                  <td className="p-3" style={{ color: "var(--pr-text-muted)", fontSize: 12, fontFamily: "monospace" }}>
                    {a.certificate_status ?? "none"}
                  </td>
                  <td className="p-3"><HealthDot health={a.health} /></td>
                  <td className="p-3">
                    {rowAction && rowAction.action === "suspend" ? (
                      <ConfirmButton
                        size="sm"
                        confirmLabel="Confirm"
                        disabled={!!pendingRowId}
                        className="text-xs px-2.5 py-1 rounded-md"
                        style={{ backgroundColor: "var(--pr-overlay-06)", color: "var(--pr-text-secondary)" }}
                        onConfirm={() => runRowAction(rowAction.action, a.id)}
                      >
                        {rowAction.label}
                      </ConfirmButton>
                    ) : rowAction && (
                      <button
                        onClick={() => runRowAction(rowAction.action, a.id)}
                        disabled={!!pendingRowId}
                        className="text-xs px-2.5 py-1 rounded-md disabled:opacity-40"
                        style={{ backgroundColor: "var(--pr-overlay-06)", color: "var(--pr-text-secondary)" }}
                      >
                        {pendingRowId === a.id ? "Working..." : rowAction.label}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {agents?.length === 0 && (() => {
              // Visual Experience V2 (found via browser QA): `total` is
              // the server-side count for the CURRENT filtered query,
              // not the organisation's real agent count -- filtering to
              // zero matches used to render "No agents yet, register
              // the first one" even when real agents existed, exactly
              // the "0 vs no results" conflation section 14 warns
              // against. Whether a filter is actually active is the
              // real signal, not whether this query's own total is 0.
              const filtersActive = !!(q || statusFilter || environmentFilter);
              return (
                <tr>
                  <td colSpan={9}>
                    <EmptyState
                      icon={Bot}
                      title={filtersActive ? "No agents match these filters" : "No agents yet"}
                      description={
                        filtersActive
                          ? "Try a different search, status, or environment."
                          : "Register the first AI agent operating in your enterprise."
                      }
                      action={
                        !filtersActive ? (
                          <Link to="/agents/register" style={{ color: "var(--pr-authority-blue)", fontSize: 13 }}>
                            Register an agent &rarr;
                          </Link>
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
        <span>{total} agent{total === 1 ? "" : "s"} total</span>
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
