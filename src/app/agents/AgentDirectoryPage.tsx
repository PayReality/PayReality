import { useEffect, useId, useState } from "react";
import { Link } from "react-router";
import { Plus } from "lucide-react";
import { agentsApi } from "./api";
import { AgentStatusBadge } from "./components/AgentStatusBadge";
import { HealthDot } from "./components/HealthDot";
import { generateKeyPair } from "../live/crypto";
import { saveAgentKeyPair } from "../live/agentKeyStore";
import { describeApiError } from "../live/format";
import { NextStepGuidance } from "../help/NextStepGuidance";
import type { LiveAgent, LivePrincipal } from "../live/types";
import { useResourceSync } from "../services/resourceSync";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { SkeletonRows } from "../components/ui/skeleton";
import { useToast } from "../components/ui/toast";

const BULK_ACTION_LABEL: Record<"suspend" | "activate" | "retire" | "rotate", string> = {
  suspend: "suspend",
  activate: "activate",
  retire: "retire",
  rotate: "request rotation for",
};

const PAGE_SIZE = 25;

export function AgentDirectoryPage() {
  const formId = useId();
  const { notify } = useToast();
  const [agents, setAgents] = useState<LiveAgent[] | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [principals, setPrincipals] = useState<LivePrincipal[]>([]);
  const [principalById, setPrincipalById] = useState<Record<string, string>>({});

  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [environmentFilter, setEnvironmentFilter] = useState("");

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmingBulkAction, setConfirmingBulkAction] = useState<"suspend" | "activate" | "retire" | "rotate" | null>(null);

  const [name, setName] = useState("");
  const [principalId, setPrincipalId] = useState("");
  const [newPrincipalName, setNewPrincipalName] = useState("");
  const [registerMessage, setRegisterMessage] = useState<string | null>(null);
  const [registering, setRegistering] = useState(false);
  const [justActivatedName, setJustActivatedName] = useState<string | null>(null);

  function loadPrincipals() {
    agentsApi.listPrincipals().then((ps) => {
      setPrincipals(ps);
      setPrincipalById(Object.fromEntries(ps.map((p) => [p.id, p.name])));
    });
  }

  function loadAgents() {
    agentsApi
      .list({ q: q || undefined, status: statusFilter || undefined, environment: environmentFilter || undefined, limit: PAGE_SIZE, offset })
      .then((page) => {
        setAgents(page.agents);
        setTotal(page.total);
      });
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

  async function handleCreatePrincipal() {
    if (!newPrincipalName.trim()) return;
    const principal = await agentsApi.createPrincipal(newPrincipalName);
    setPrincipals((prev) => [...prev, principal]);
    setPrincipalById((prev) => ({ ...prev, [principal.id]: principal.name }));
    setPrincipalId(principal.id);
    setNewPrincipalName("");
  }

  async function handleRegister() {
    if (!name.trim() || !principalId) {
      setRegisterMessage("Name and Principal are both required.");
      return;
    }
    setRegistering(true);
    setRegisterMessage(null);
    try {
      const { publicKeyB64, privateKeyB64 } = generateKeyPair();
      const agent = await agentsApi.register({
        name,
        acting_for_principal_id: principalId,
        public_key: `ed25519:base64:${publicKeyB64}`,
      });
      saveAgentKeyPair(agent.id, privateKeyB64, publicKeyB64);
      setName("");
      setRegisterMessage(
        `Registered "${agent.name}". It's in "Registered" status, not yet operational: activate it below before it can sign Intents.`
      );
      loadAgents();
    } catch (e) {
      setRegisterMessage(describeApiError(e, "Registration"));
    } finally {
      setRegistering(false);
    }
  }

  async function runRowAction(action: "activate" | "suspend" | "retire", agentId: string) {
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
      <div className="mb-6">
        <h1 className="mb-2" style={{ color: "var(--pr-text-primary)" }}>Agents</h1>
        <p style={{ color: "var(--pr-text-muted)", fontSize: 13, maxWidth: 640 }}>
          Every AI worker operating under this platform, managed the same way an enterprise manages
          a human workforce identity and delegates authority to it: registered, activated,
          suspended, rotated, retired, or revoked, with a signed audit trail for every change.
        </p>
      </div>

      <Card style={{ marginBottom: 24 }}>
        <h2 className="text-sm font-medium mb-4" style={{ color: "var(--pr-text-primary)" }}>Register a new agent</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
          <div>
            <label htmlFor={`${formId}-name`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
              Agent name
            </label>
            <input
              id={`${formId}-name`}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="AP-Automation-Agent"
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            />
          </div>
          <div>
            <label htmlFor={`${formId}-principal`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
              Acting for principal <span style={{ fontWeight: 400, color: "var(--pr-text-disabled)" }}>(whose delegated authority it acts under)</span>
            </label>
            <select
              id={`${formId}-principal`}
              value={principalId}
              onChange={(e) => setPrincipalId(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            >
              <option value="">Select a principal...</option>
              {principals.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex items-end gap-2 mb-4">
          <div className="flex-1">
            <label htmlFor={`${formId}-new-principal`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
              Or create a new principal
            </label>
            <input
              id={`${formId}-new-principal`}
              value={newPrincipalName}
              onChange={(e) => setNewPrincipalName(e.target.value)}
              placeholder="Regional Controller (EMEA)"
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
            />
          </div>
          <button
            onClick={handleCreatePrincipal}
            className="px-4 py-2 rounded-lg text-sm border"
            style={{ borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-secondary)" }}
          >
            Create
          </button>
        </div>

        <button
          onClick={handleRegister}
          disabled={registering}
          className="px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 disabled:opacity-40"
          style={{ backgroundColor: "var(--pr-authority-blue)", color: "#fff" }}
        >
          <Plus className="w-4 h-4" /> Register agent
        </button>

        {registerMessage && (
          <Alert severity="neutral" className="text-sm mt-4">{registerMessage}</Alert>
        )}
      </Card>

      {justActivatedName && (
        <NextStepGuidance
          message={`"${justActivatedName}" is now active and can sign real Intents. Try a test decision to see it get checked against your rules.`}
          actionLabel="Submit Test Decision"
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
        <select
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
        </select>
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

      <Card padding={0} style={{ overflow: "hidden" }}>
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
                    <Link to={`/agents/${a.id}`} style={{ color: "var(--pr-authority-blue)" }}>{a.name}</Link>
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
                    {rowAction && (
                      <button
                        onClick={() => runRowAction(rowAction.action, a.id)}
                        className="text-xs px-2.5 py-1 rounded-md"
                        style={{ backgroundColor: "var(--pr-overlay-06)", color: "var(--pr-text-secondary)" }}
                      >
                        {rowAction.label}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {agents?.length === 0 && (
              <tr>
                <td colSpan={9} className="p-6 text-center" style={{ color: "var(--pr-text-muted)" }}>No agents match these filters.</td>
              </tr>
            )}
          </tbody>
        </table>
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
