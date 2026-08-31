import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ArrowLeft, ChevronDown, ChevronRight, Plus } from "lucide-react";
import { integrationsApi } from "./api";
import { agentsApi } from "../agents/api";
import { describeApiError, formatStatus } from "../live/format";
import { useAuth } from "../auth/AuthContext";
import { useResourceSync } from "../services/resourceSync";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { ConfirmButton } from "../components/ui/confirm-button";
import { SkeletonRows } from "../components/ui/skeleton";
import { MappingStatusBadge, ConnectionStatusBadge, TrustedConnectionStatusBadge } from "./components/StatusBadges";
import { MappingFormSheet } from "./components/MappingFormSheet";
import { describeMapping, humanizeAction, summarizeSystem, SETUP_STATE_LABEL, SETUP_STATE_COLOR } from "./helpers";
import type { ActionMapping, IntegrationSystem, RuntimeConnection, TrustedConnection } from "./types";

function MappingRow({ mapping, systemId, systemLabel, canManage, canPublish, onChanged }: {
  mapping: ActionMapping; systemId: string; systemLabel: string; canManage: boolean; canPublish: boolean;
  onChanged: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(describeApiError(e, "Update mapping"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ borderTop: "1px solid var(--pr-overlay-05)" }}>
      <div className="flex flex-wrap items-center gap-3 p-3">
        <button
          onClick={() => setExpanded((e) => !e)}
          aria-expanded={expanded}
          aria-label={expanded ? "Collapse details" : "Expand details"}
          className="flex-shrink-0"
          style={{ color: "var(--pr-text-muted)" }}
        >
          {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </button>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium" style={{ color: "var(--pr-text-primary)", wordBreak: "break-word" }}>
            {mapping.source_operation} <span style={{ color: "var(--pr-text-disabled)", fontWeight: 400 }}>v{mapping.version}</span>
          </p>
          <p className="text-xs mt-0.5" style={{ color: "var(--pr-text-muted)", wordBreak: "break-word" }}>
            {describeMapping(mapping)}
          </p>
        </div>
        <MappingStatusBadge status={mapping.status} />
        <div className="flex gap-2 flex-shrink-0">
          {mapping.status === "draft" && canManage && (
            <>
              <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>Edit</Button>
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => run(() => integrationsApi.validateMapping(systemId, mapping.id))}>
                {busy ? "Working..." : "Validate mapping"}
              </Button>
            </>
          )}
          {mapping.status === "validated" && canPublish && (
            <Button
              variant="tint-success"
              size="sm"
              disabled={busy}
              onClick={() => run(() => integrationsApi.approveMapping(systemId, mapping.id, "Approved via Settings > Integrations"))}
            >
              {busy ? "Working..." : "Approve mapping"}
            </Button>
          )}
          {mapping.status === "approved" && canPublish && (
            <ConfirmButton
              size="sm"
              confirmLabel="Confirm retire"
              disabled={busy}
              variant="tint-danger"
              onConfirm={() => run(() => integrationsApi.retireMapping(systemId, mapping.id))}
            >
              Retire
            </ConfirmButton>
          )}
        </div>
      </div>

      {error && <Alert severity="error" className="text-sm mx-3 mb-3">{error}</Alert>}

      {expanded && (
        <div className="px-3 pb-3 pl-10 text-xs" style={{ color: "var(--pr-text-muted)" }}>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1.5">
            <dt>Resource location</dt><dd style={{ color: "var(--pr-text-primary)" }}>{mapping.resource_path ?? "Not mapped"}</dd>
            <dt>Fact subject location</dt><dd style={{ color: "var(--pr-text-primary)" }}>{mapping.fact_subject_path ?? "Not mapped"}</dd>
            <dt>Amount location</dt><dd style={{ color: "var(--pr-text-primary)" }}>{mapping.amount_path ?? "Not mapped"}</dd>
            <dt>Currency location</dt><dd style={{ color: "var(--pr-text-primary)" }}>{mapping.currency_path ?? "Not mapped"}</dd>
            <dt>Trusted context fields</dt>
            <dd style={{ color: "var(--pr-text-primary)" }}>
              {Object.keys(mapping.context_bindings).length > 0 ? Object.keys(mapping.context_bindings).join(", ") : "None"}
            </dd>
            <dt>Created</dt><dd style={{ color: "var(--pr-text-primary)" }}>{new Date(mapping.created_at).toLocaleString()}</dd>
            <dt>Validated</dt><dd style={{ color: "var(--pr-text-primary)" }}>{mapping.validated_at ? new Date(mapping.validated_at).toLocaleString() : "Not yet"}</dd>
            <dt>Approved</dt>
            <dd style={{ color: "var(--pr-text-primary)" }}>
              {mapping.approved_at ? `${new Date(mapping.approved_at).toLocaleString()} by ${mapping.approved_by}` : "Not yet"}
            </dd>
            <dt>Retired</dt><dd style={{ color: "var(--pr-text-primary)" }}>{mapping.retired_at ? new Date(mapping.retired_at).toLocaleString() : "-"}</dd>
          </dl>
          <p className="mt-3" style={{ color: "var(--pr-text-disabled)" }}>
            Content hash (for audit/proof, not something you need to act on): <span style={{ fontFamily: "monospace" }}>{mapping.content_hash ?? "not computed yet"}</span>
          </p>
        </div>
      )}

      <MappingFormSheet
        open={editing}
        onOpenChange={setEditing}
        systemId={systemId}
        systemLabel={systemLabel}
        editingMapping={mapping}
        onSaved={onChanged}
      />
    </div>
  );
}

function ConnectionRow({ connection, mappingLabel, trustedConnectionName, agentNameById, canPublish, onChanged }: {
  connection: RuntimeConnection;
  mappingLabel: string;
  trustedConnectionName: string;
  agentNameById: Record<string, string>;
  canPublish: boolean;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(describeApiError(e, "Update connection"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-3" style={{ borderTop: "1px solid var(--pr-overlay-05)" }}>
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium" style={{ color: "var(--pr-text-primary)" }}>
            {formatStatus(connection.environment)} <span style={{ color: "var(--pr-text-disabled)", fontWeight: 400 }}>via {trustedConnectionName}</span>
          </p>
          <p className="text-xs mt-0.5" style={{ color: "var(--pr-text-muted)" }}>
            Mapping: {mappingLabel} &middot; {connection.allowed_agent_ids.length} agent{connection.allowed_agent_ids.length === 1 ? "" : "s"} allowed
          </p>
          {connection.allowed_agent_ids.length > 0 && (
            <p className="text-[11px] mt-0.5" style={{ color: "var(--pr-text-disabled)" }}>
              {connection.allowed_agent_ids.map((id) => agentNameById[id] ?? id).join(", ")}
            </p>
          )}
        </div>
        <ConnectionStatusBadge status={connection.status} />
        {connection.status === "draft" && canPublish && (
          <Button variant="tint-success" size="sm" disabled={busy} onClick={() => run(() => integrationsApi.activateConnection(connection.id))}>
            {busy ? "Working..." : "Activate"}
          </Button>
        )}
        {connection.status === "active" && canPublish && (
          <ConfirmButton size="sm" confirmLabel="Confirm retire" disabled={busy} variant="tint-danger" onConfirm={() => run(() => integrationsApi.retireConnection(connection.id))}>
            Retire
          </ConfirmButton>
        )}
      </div>
      {error && <Alert severity="error" className="text-sm mt-2">{error}</Alert>}
    </div>
  );
}

export function IntegrationDetailPage() {
  const { systemId } = useParams();
  const navigate = useNavigate();
  const { user, hasPermission } = useAuth();
  const canManage = !user || hasPermission("integration_contract.manage");
  const canPublish = !user || hasPermission("integration_contract.publish");

  const [system, setSystem] = useState<IntegrationSystem | null>(null);
  const [mappings, setMappings] = useState<ActionMapping[] | null>(null);
  const [connections, setConnections] = useState<RuntimeConnection[]>([]);
  const [trustedConnections, setTrustedConnections] = useState<TrustedConnection[]>([]);
  const [agentNameById, setAgentNameById] = useState<Record<string, string>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [mappingSheetOpen, setMappingSheetOpen] = useState(false);

  function load() {
    if (!systemId) return;
    setLoadError(null);
    Promise.all([
      integrationsApi.getSystem(systemId),
      integrationsApi.listMappings(systemId),
      integrationsApi.listConnections(),
      integrationsApi.listTrustedConnections(),
      agentsApi.list({ limit: 500 }).catch(() => ({ agents: [], total: 0, limit: 0, offset: 0 })),
    ])
      .then(([sys, maps, allConnections, identities, agentPage]) => {
        setSystem(sys);
        setMappings(maps);
        setConnections(allConnections.filter((c) => c.integration_id === systemId));
        setTrustedConnections(identities);
        setAgentNameById(Object.fromEntries(agentPage.agents.map((a) => [a.id, a.name])));
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading system")));
  }

  useEffect(load, [systemId]);
  useResourceSync(["integrations"], load);

  if (loadError) {
    return (
      <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
        <Alert severity="warning">
          <div className="flex items-center gap-3">
            <span>{loadError}</span>
            <Button variant="ghost" size="sm" onClick={load}>Retry</Button>
          </div>
        </Alert>
      </div>
    );
  }

  if (!system || !mappings) {
    return (
      <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
        <SkeletonRows count={6} height={20} />
      </div>
    );
  }

  const summary = summarizeSystem(mappings, connections);
  const mappingLabel = (mappingId: string) => {
    const m = mappings.find((mm) => mm.id === mappingId);
    return m ? `${m.source_operation} v${m.version} (${humanizeAction(m.canonical_action)})` : "Unknown mapping";
  };
  const trustedConnectionLabel = (id: string) => trustedConnections.find((t) => t.id === id)?.name ?? "Unknown connection";
  const approvedMappings = mappings.filter((m) => m.status === "approved");

  return (
    <div className="p-8 max-w-4xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <Link to="/organization/integrations" className="text-sm inline-flex items-center gap-1.5 mb-4" style={{ color: "var(--pr-text-muted)" }}>
        <ArrowLeft className="w-3.5 h-3.5" /> Integrations
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3 mb-6">
        <div>
          <h1 className="mb-2" style={{ color: "var(--pr-text-primary)" }}>{system.external_system_label}</h1>
          <p style={{ color: "var(--pr-text-muted)", fontSize: 13 }}>
            <span style={{ color: SETUP_STATE_COLOR[summary.setupState] }}>{SETUP_STATE_LABEL[summary.setupState]}</span>
            {" -- "}
            {summary.mappedActionsCount} action{summary.mappedActionsCount === 1 ? "" : "s"} mapped,{" "}
            {summary.approvedMappingsCount} approved
          </p>
        </div>
      </div>

      <section className="mb-8">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)" }}>Action mappings</h2>
            <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>What each action in this system means to PayReality.</p>
          </div>
          {canManage && (
            <Button size="sm" onClick={() => setMappingSheetOpen(true)}>
              <Plus className="w-3.5 h-3.5 mr-1 inline" /> New mapping
            </Button>
          )}
        </div>
        <Card padding={0}>
          {mappings.length === 0 ? (
            <p className="text-sm p-6 text-center" style={{ color: "var(--pr-text-muted)" }}>
              No action mappings yet. Add one to tell PayReality what an action in this system means.
            </p>
          ) : (
            mappings
              .slice()
              .sort((a, b) => a.source_operation.localeCompare(b.source_operation) || b.version - a.version)
              .map((m) => (
                <MappingRow
                  key={m.id}
                  mapping={m}
                  systemId={system.id}
                  systemLabel={system.external_system_label}
                  canManage={canManage}
                  canPublish={canPublish}
                  onChanged={load}
                />
              ))
          )}
        </Card>
      </section>

      <section>
        <div className="flex items-center justify-between mb-3">
          <div>
            <h2 className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)" }}>Runtime connections</h2>
            <p className="text-xs" style={{ color: "var(--pr-text-muted)" }}>
              Which trusted connection, environment, and agents can actually use an approved mapping.
            </p>
          </div>
          {canManage && (
            approvedMappings.length > 0 ? (
              <Button size="sm" onClick={() => navigate(`/organization/integrations/${system.id}/connect`)}>
                <Plus className="w-3.5 h-3.5 mr-1 inline" /> Set up connection
              </Button>
            ) : (
              <span className="text-xs" style={{ color: "var(--pr-text-disabled)" }}>Approve a mapping first</span>
            )
          )}
        </div>
        <Card padding={0}>
          {connections.length === 0 ? (
            <p className="text-sm p-6 text-center" style={{ color: "var(--pr-text-muted)" }}>
              No runtime connections yet. Once a mapping is approved, set up a connection to make it
              usable by your agents.
            </p>
          ) : (
            connections.map((c) => (
              <ConnectionRow
                key={c.id}
                connection={c}
                mappingLabel={mappingLabel(c.integration_contract_version_id)}
                trustedConnectionName={trustedConnectionLabel(c.integration_identity_id)}
                agentNameById={agentNameById}
                canPublish={canPublish}
                onChanged={load}
              />
            ))
          )}
        </Card>
      </section>

      <MappingFormSheet
        open={mappingSheetOpen}
        onOpenChange={setMappingSheetOpen}
        systemId={system.id}
        systemLabel={system.external_system_label}
        onSaved={load}
      />
    </div>
  );
}
