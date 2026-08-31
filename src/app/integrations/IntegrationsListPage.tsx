import { useEffect, useId, useState } from "react";
import { Link } from "react-router";
import { Plug, Plus } from "lucide-react";
import { integrationsApi } from "./api";
import { describeApiError } from "../live/format";
import { useAuth } from "../auth/AuthContext";
import { useResourceSync } from "../services/resourceSync";
import { Card } from "../components/ui/card";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { SkeletonRows } from "../components/ui/skeleton";
import { PageHeader } from "../components/ui/page-header";
import { EmptyState } from "../components/ui/empty-state";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetFooter } from "../components/ui/sheet";
import { SETUP_STATE_COLOR, SETUP_STATE_LABEL, summarizeSystem, type SystemSummary } from "./helpers";
import type { ActionMapping, IntegrationSystem, RuntimeConnection } from "./types";

interface Row {
  system: IntegrationSystem;
  summary: SystemSummary;
}

function ConnectSystemSheet({ open, onOpenChange, onCreated }: {
  open: boolean; onOpenChange: (open: boolean) => void; onCreated: (system: IntegrationSystem) => void;
}) {
  const formId = useId();
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate() {
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const system = await integrationsApi.createSystem(name.trim());
      setName("");
      onOpenChange(false);
      onCreated(system);
    } catch (e) {
      setError(describeApiError(e, "Connect system"));
    } finally {
      setCreating(false);
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md" style={{ backgroundColor: "var(--pr-bg-card)" }}>
        <SheetHeader>
          <SheetTitle>Connect a system</SheetTitle>
          <SheetDescription>
            What system does your AI agents' work run through? SAP, Salesforce, ServiceNow, an
            internal payments API, a procurement platform -- any name you'll recognize later works.
          </SheetDescription>
        </SheetHeader>
        <div className="p-4">
          <label htmlFor={formId} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
            System name
          </label>
          <input
            id={formId}
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleCreate(); }}
            placeholder="e.g. SAP S/4HANA"
            className="w-full px-3 py-2 rounded-lg border text-sm"
            style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
          />
          <p className="text-xs mt-2" style={{ color: "var(--pr-text-disabled)" }}>
            This just creates a place to describe the system. Nothing becomes active yet -- you'll
            define what its actions mean, connect it, and choose which agents can use it next.
          </p>
          {error && <Alert severity="error" className="text-sm mt-3">{error}</Alert>}
        </div>
        <SheetFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleCreate} disabled={!name.trim() || creating}>
            {creating ? "Connecting..." : "Connect system"}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function SystemCard({ row }: { row: Row }) {
  const { system, summary } = row;
  return (
    <Link to={`/organization/integrations/${system.id}`} style={{ textDecoration: "none" }}>
      <Card padding={20} style={{ height: "100%" }} className="hover:opacity-90 transition-opacity">
        <div className="flex items-start justify-between gap-2 mb-3">
          <h3 className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)", wordBreak: "break-word" }}>
            {system.external_system_label}
          </h3>
          <span
            className="text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full flex-shrink-0"
            style={{ color: SETUP_STATE_COLOR[summary.setupState], backgroundColor: "var(--pr-overlay-05)" }}
          >
            {SETUP_STATE_LABEL[summary.setupState]}
          </span>
        </div>
        <dl className="grid grid-cols-2 gap-y-2 text-xs" style={{ color: "var(--pr-text-muted)" }}>
          <dt>Mapped actions</dt>
          <dd style={{ color: "var(--pr-text-primary)", textAlign: "right" }}>{summary.mappedActionsCount}</dd>
          <dt>Approved mappings</dt>
          <dd style={{ color: "var(--pr-text-primary)", textAlign: "right" }}>{summary.approvedMappingsCount}</dd>
          <dt>Environments connected</dt>
          <dd style={{ color: "var(--pr-text-primary)", textAlign: "right" }}>
            {summary.environments.length > 0 ? summary.environments.join(", ") : "Not configured"}
          </dd>
          <dt>Active agents</dt>
          <dd style={{ color: "var(--pr-text-primary)", textAlign: "right" }}>{summary.activeAgentIds.length}</dd>
        </dl>
      </Card>
    </Link>
  );
}

export function IntegrationsListPage() {
  const { user, hasPermission } = useAuth();
  const canManage = !user || hasPermission("integration_contract.manage");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  function load() {
    setLoadError(null);
    integrationsApi.listSystems()
      .then(async (systems) => {
        const connections = await integrationsApi.listConnections().catch(() => [] as RuntimeConnection[]);
        const withMappings = await Promise.all(
          systems.map(async (system) => {
            const mappings = await integrationsApi.listMappings(system.id).catch(() => [] as ActionMapping[]);
            const systemConnections = connections.filter((c) => c.integration_id === system.id);
            return { system, summary: summarizeSystem(mappings, systemConnections) };
          })
        );
        setRows(withMappings);
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading integrations")));
  }

  useEffect(load, []);
  useResourceSync(["integrations"], load);

  return (
    <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <PageHeader
        title="Integrations"
        description="The enterprise systems your AI agents act through: what their actions mean to PayReality, which agents may use each connection, and whether it's live."
        primaryAction={
          canManage && rows && rows.length > 0 ? (
            <Button onClick={() => setSheetOpen(true)} className="flex-shrink-0">
              <Plus className="w-4 h-4 mr-1.5 inline" /> Connect a system
            </Button>
          ) : undefined
        }
      />

      {loadError && (
        <Alert severity="warning" style={{ marginBottom: 16 }}>
          <div className="flex items-center gap-3">
            <span>{loadError}</span>
            <Button variant="ghost" size="sm" onClick={load}>Retry</Button>
          </div>
        </Alert>
      )}

      {!rows && !loadError && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <Card key={i} padding={20}><SkeletonRows count={4} height={16} /></Card>
          ))}
        </div>
      )}

      {rows && rows.length === 0 && (
        <Card padding={0}>
          <EmptyState
            icon={Plug}
            title="No systems connected yet"
            description="This is a guided setup, not a one-click connector: you'll describe what one action means, approve it, and choose which agents can use it."
            action={
              canManage ? (
                <Button onClick={() => setSheetOpen(true)}>
                  <Plus className="w-4 h-4 mr-1.5 inline" /> Connect a system
                </Button>
              ) : undefined
            }
          />
        </Card>
      )}

      {rows && rows.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {rows.map((row) => <SystemCard key={row.system.id} row={row} />)}
        </div>
      )}

      <ConnectSystemSheet open={sheetOpen} onOpenChange={setSheetOpen} onCreated={load} />
    </div>
  );
}
