import { useEffect, useId, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ArrowLeft, Check, Copy, Send } from "lucide-react";
import { integrationsApi } from "./api";
import { agentsApi } from "../agents/api";
import { apiClient } from "../live/apiClient";
import { generateKeyPair, signBody } from "../live/crypto";
import { describeApiError, describeReason, formatStatus } from "../live/format";
import { useAuth } from "../auth/AuthContext";
import { humanizeAction } from "./helpers";
import { Alert } from "../components/ui/alert";
import { Button } from "../components/ui/button";
import { Card } from "../components/ui/card";
import { Select } from "../components/ui/select";
import { SkeletonRows } from "../components/ui/skeleton";
import type { LiveAgent } from "../live/types";
import type { ActionMapping, IntegrationSystem, TrustedConnection } from "./types";

const ENVIRONMENT_OPTIONS = ["production", "staging", "development"];

type SetupStage = "trusted_connection" | "mapping" | "environment" | "agents" | "review";

interface FreshCredential {
  identity: TrustedConnection;
  certificateId: string;
  privateKeyB64: string;
}

interface TestFormState {
  originAgentId: string;
  resource: string;
  amount: string;
  currency: string;
  counterparty: string;
  context: Record<string, string>;
}

interface TestOutcome {
  outcome: string;
  reason: string | null;
  decisionId: string;
}

function StepDot({ done }: { done: boolean }) {
  return (
    <span
      className="inline-flex items-center justify-center rounded-full flex-shrink-0"
      style={{
        width: 18, height: 18, fontSize: 10, fontWeight: 700,
        backgroundColor: done ? "rgba(34,197,94,0.15)" : "var(--pr-overlay-06)",
        color: done ? "var(--pr-trust-green)" : "var(--pr-text-disabled)",
      }}
    >
      {done ? <Check className="w-3 h-3" /> : ""}
    </span>
  );
}

export function ConnectionSetupPage() {
  const { systemId } = useParams();
  const navigate = useNavigate();
  const formId = useId();
  const { user, hasPermission } = useAuth();
  const canManage = !user || hasPermission("integration_contract.manage");
  const canPublish = !user || hasPermission("integration_contract.publish");

  const [system, setSystem] = useState<IntegrationSystem | null>(null);
  const [approvedMappings, setApprovedMappings] = useState<ActionMapping[]>([]);
  const [trustedConnections, setTrustedConnections] = useState<TrustedConnection[]>([]);
  const [agents, setAgents] = useState<LiveAgent[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Trusted connection: reuse an existing active one, or register a new one.
  const [mode, setMode] = useState<"existing" | "new">("existing");
  const [existingConnectionId, setExistingConnectionId] = useState("");
  const [newConnectionName, setNewConnectionName] = useState("");
  const [registering, setRegistering] = useState(false);
  const [freshCredential, setFreshCredential] = useState<FreshCredential | null>(null);
  const [copied, setCopied] = useState(false);
  const [registerError, setRegisterError] = useState<string | null>(null);

  const [mappingId, setMappingId] = useState("");
  const [environment, setEnvironment] = useState("production");
  const [customEnvironment, setCustomEnvironment] = useState(false);
  const [selectedAgentIds, setSelectedAgentIds] = useState<Set<string>>(new Set());

  const [creatingDraft, setCreatingDraft] = useState(false);
  const [draftId, setDraftId] = useState<string | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [activating, setActivating] = useState(false);
  const [activateError, setActivateError] = useState<string | null>(null);
  const [activated, setActivated] = useState(false);

  const [testForm, setTestForm] = useState<TestFormState>({ originAgentId: "", resource: "", amount: "", currency: "", counterparty: "", context: {} });
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<TestOutcome | null>(null);

  function load() {
    if (!systemId) return;
    setLoadError(null);
    Promise.all([
      integrationsApi.getSystem(systemId),
      integrationsApi.listMappings(systemId),
      integrationsApi.listTrustedConnections(),
      agentsApi.list({ status: "active", limit: 500 }),
    ])
      .then(([sys, maps, identities, agentPage]) => {
        setSystem(sys);
        setApprovedMappings(maps.filter((m) => m.status === "approved"));
        setTrustedConnections(identities.filter((t) => t.status === "active"));
        setAgents(agentPage.agents);
      })
      .catch((e) => setLoadError(describeApiError(e, "Loading setup")));
  }

  useEffect(load, [systemId]);

  const selectedMapping = approvedMappings.find((m) => m.id === mappingId) ?? null;
  const selectedIdentityId = mode === "existing" ? existingConnectionId : freshCredential?.identity.id ?? "";

  async function handleRegisterTrustedConnection() {
    if (!newConnectionName.trim()) return;
    setRegistering(true);
    setRegisterError(null);
    try {
      const { publicKeyB64, privateKeyB64 } = generateKeyPair();
      const identity = await integrationsApi.registerTrustedConnection(newConnectionName.trim(), `ed25519:base64:${publicKeyB64}`);
      const activated_ = await integrationsApi.activateTrustedConnection(identity.id);
      const certs = await integrationsApi.listTrustedConnectionCertificates(identity.id);
      const activeCert = certs.find((c) => c.status === "active");
      if (!activeCert) throw new Error("no_active_certificate");
      setFreshCredential({ identity: activated_, certificateId: activeCert.id, privateKeyB64 });
    } catch (e) {
      setRegisterError(describeApiError(e, "Register trusted connection"));
    } finally {
      setRegistering(false);
    }
  }

  function copyPrivateKey() {
    if (!freshCredential) return;
    navigator.clipboard?.writeText(freshCredential.privateKeyB64).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2500);
    });
  }

  function toggleAgent(agentId: string) {
    setSelectedAgentIds((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) next.delete(agentId);
      else next.add(agentId);
      return next;
    });
  }

  async function handleCreateDraft() {
    if (!selectedIdentityId || !mappingId || selectedAgentIds.size === 0) return;
    setCreatingDraft(true);
    setDraftError(null);
    try {
      const binding = await integrationsApi.createDraftConnection({
        integration_identity_id: selectedIdentityId,
        integration_contract_version_id: mappingId,
        environment,
        agent_ids: Array.from(selectedAgentIds),
      });
      setDraftId(binding.id);
      const firstAgent = Array.from(selectedAgentIds)[0];
      setTestForm((f) => ({ ...f, originAgentId: firstAgent }));
    } catch (e) {
      setDraftError(describeApiError(e, "Create connection setup"));
    } finally {
      setCreatingDraft(false);
    }
  }

  async function handleActivate() {
    if (!draftId) return;
    setActivating(true);
    setActivateError(null);
    try {
      await integrationsApi.activateConnection(draftId);
      setActivated(true);
    } catch (e) {
      setActivateError(describeApiError(e, "Activate connection"));
    } finally {
      setActivating(false);
    }
  }

  async function handleSendTest() {
    if (!draftId || !freshCredential || !selectedMapping || !testForm.originAgentId) return;
    setTesting(true);
    setTestError(null);
    setTestResult(null);
    try {
      const body = {
        integration_identity_id: freshCredential.identity.id,
        enforcement_binding_id: draftId,
        origin_agent_id: testForm.originAgentId,
        source_operation: selectedMapping.source_operation,
        action: selectedMapping.canonical_action,
        resource: selectedMapping.resource_path ? testForm.resource.trim() || null : null,
        amount: selectedMapping.amount_path && testForm.amount.trim() ? Number(testForm.amount) : null,
        currency: selectedMapping.currency_path ? testForm.currency.trim() || null : null,
        counterparty: selectedMapping.fact_subject_path ? testForm.counterparty.trim() || null : null,
        context: Object.fromEntries(Object.entries(selectedMapping.context_bindings).map(([key]) => [key, testForm.context[key] ?? ""])),
        requested_at: new Date().toISOString(),
        nonce: crypto.randomUUID(),
        external_operation_id: `test-${crypto.randomUUID()}`,
      };
      const rawBody = JSON.stringify(body);
      const signature = signBody(new TextEncoder().encode(rawBody), freshCredential.privateKeyB64);
      const result = await apiClient.postSigned<{ decision: { outcome: string; decision_id: string; reason: string | null } }>(
        "/v1/integration-runtime/intents", rawBody,
        { "X-PayReality-Key-Id": freshCredential.certificateId, "X-PayReality-Signature": signature },
      );
      setTestResult({ outcome: result.decision.outcome, reason: result.decision.reason, decisionId: result.decision.decision_id });
    } catch (e) {
      setTestError(describeApiError(e, "Send test decision"));
    } finally {
      setTesting(false);
    }
  }

  if (loadError) {
    return (
      <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
        <Alert severity="warning">
          <div className="flex items-center gap-3"><span>{loadError}</span><Button variant="ghost" size="sm" onClick={load}>Retry</Button></div>
        </Alert>
      </div>
    );
  }

  if (!system) {
    return <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}><SkeletonRows count={6} height={20} /></div>;
  }

  if (!canManage) {
    return (
      <div className="p-8" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
        <Alert severity="warning">Your role doesn't have permission to set up connections for this system.</Alert>
      </div>
    );
  }

  const trustedConnectionReady = Boolean(selectedIdentityId);
  const testAvailable = Boolean(freshCredential) && Boolean(draftId) && !activated;

  return (
    <div className="p-8 max-w-2xl" style={{ backgroundColor: "var(--pr-bg-primary)", minHeight: "100vh" }}>
      <Link to={`/organization/integrations/${system.id}`} className="text-sm inline-flex items-center gap-1.5 mb-4" style={{ color: "var(--pr-text-muted)" }}>
        <ArrowLeft className="w-3.5 h-3.5" /> {system.external_system_label}
      </Link>
      <h1 className="mb-2" style={{ color: "var(--pr-text-primary)" }}>Set up a runtime connection</h1>
      <p style={{ color: "var(--pr-text-muted)", fontSize: 13, marginBottom: 24 }}>
        A runtime connection is what actually makes an approved action mapping usable: a trusted
        connection, one approved mapping, one environment, and the exact agents allowed to use it.
        Nothing here affects production until you activate it.
      </p>

      {!draftId && (
        <>
          <Card padding={20} style={{ marginBottom: 16 }}>
            <div className="flex items-center gap-2 mb-3">
              <StepDot done={trustedConnectionReady} />
              <h2 className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)" }}>Trusted connection</h2>
            </div>
            <p className="text-xs mb-3" style={{ color: "var(--pr-text-muted)" }}>
              This identifies the company-controlled software that will report {system.external_system_label}'s
              real actions to PayReality. It attests what it observed -- it doesn't prove the action
              itself objectively happened.
            </p>
            <div className="flex gap-2 mb-3">
              <button
                type="button"
                onClick={() => setMode("existing")}
                className="text-xs px-3 py-1.5 rounded-lg"
                style={{ backgroundColor: mode === "existing" ? "var(--pr-authority-blue)" : "var(--pr-overlay-06)", color: mode === "existing" ? "#fff" : "var(--pr-text-secondary)" }}
              >
                Use an existing connection
              </button>
              <button
                type="button"
                onClick={() => setMode("new")}
                className="text-xs px-3 py-1.5 rounded-lg"
                style={{ backgroundColor: mode === "new" ? "var(--pr-authority-blue)" : "var(--pr-overlay-06)", color: mode === "new" ? "#fff" : "var(--pr-text-secondary)" }}
              >
                Register a new one
              </button>
            </div>

            {mode === "existing" && (
              trustedConnections.length === 0 ? (
                <p className="text-xs" style={{ color: "var(--pr-text-disabled)" }}>No active trusted connections yet -- register a new one.</p>
              ) : (
                <Select
                  value={existingConnectionId}
                  onChange={(e) => setExistingConnectionId(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border text-sm"
                  containerClassName="block w-full"
                  style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                >
                  <option value="">Select a trusted connection...</option>
                  {trustedConnections.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </Select>
              )
            )}

            {mode === "new" && !freshCredential && (
              <div>
                <label htmlFor={`${formId}-conn-name`} className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>
                  Connection name
                </label>
                <input
                  id={`${formId}-conn-name`}
                  value={newConnectionName}
                  onChange={(e) => setNewConnectionName(e.target.value)}
                  placeholder="e.g. SAP Procurement Adapter"
                  className="w-full px-3 py-2 rounded-lg border text-sm mb-3"
                  style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                />
                <Button onClick={handleRegisterTrustedConnection} disabled={!newConnectionName.trim() || registering}>
                  {registering ? "Generating credentials..." : "Generate credentials"}
                </Button>
                {registerError && <Alert severity="error" className="text-sm mt-3">{registerError}</Alert>}
              </div>
            )}

            {mode === "new" && freshCredential && (
              <div>
                <Alert severity="warning" className="text-sm mb-3">
                  This is the only time PayReality will show this credential. Copy it into your Adapter's
                  configuration now -- it is not stored anywhere, and cannot be recovered later. If you
                  lose it, rotate the connection's credential instead.
                </Alert>
                <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--pr-text-muted)" }}>Private key (one-time)</label>
                <div className="flex gap-2 mb-1">
                  <code
                    className="flex-1 px-3 py-2 rounded-lg border text-xs overflow-x-auto"
                    style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)", wordBreak: "break-all" }}
                  >
                    {freshCredential.privateKeyB64}
                  </code>
                  <Button variant="ghost" size="sm" onClick={copyPrivateKey} aria-label="Copy private key">
                    {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                  </Button>
                </div>
                <p className="text-xs" style={{ color: "var(--pr-trust-green)" }}>"{freshCredential.identity.name}" is now active.</p>
              </div>
            )}
          </Card>

          <Card padding={20} style={{ marginBottom: 16, opacity: trustedConnectionReady ? 1 : 0.5 }}>
            <div className="flex items-center gap-2 mb-3">
              <StepDot done={!!mappingId} />
              <h2 className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)" }}>Action mapping</h2>
            </div>
            {approvedMappings.length === 0 ? (
              <p className="text-xs" style={{ color: "var(--pr-text-disabled)" }}>No approved mappings yet for this system.</p>
            ) : (
              <Select
                value={mappingId}
                onChange={(e) => setMappingId(e.target.value)}
                disabled={!trustedConnectionReady}
                className="w-full px-3 py-2 rounded-lg border text-sm"
                containerClassName="block w-full"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              >
                <option value="">Select an approved mapping...</option>
                {approvedMappings.map((m) => (
                  <option key={m.id} value={m.id}>{m.source_operation} v{m.version} &rarr; {humanizeAction(m.canonical_action)}</option>
                ))}
              </Select>
            )}
          </Card>

          <Card padding={20} style={{ marginBottom: 16, opacity: mappingId ? 1 : 0.5 }}>
            <div className="flex items-center gap-2 mb-3">
              <StepDot done={!!environment} />
              <h2 className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)" }}>Environment</h2>
            </div>
            <p className="text-xs mb-3" style={{ color: "var(--pr-text-muted)" }}>
              Production and staging are separate trusted paths -- an operation id used in one never
              collides with the other.
            </p>
            {!customEnvironment ? (
              <Select
                value={environment}
                onChange={(e) => { if (e.target.value === "__custom__") { setCustomEnvironment(true); setEnvironment(""); } else setEnvironment(e.target.value); }}
                disabled={!mappingId}
                className="w-full px-3 py-2 rounded-lg border text-sm"
                containerClassName="block w-full"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              >
                {ENVIRONMENT_OPTIONS.map((e) => <option key={e} value={e}>{formatStatus(e)}</option>)}
                <option value="__custom__">Custom...</option>
              </Select>
            ) : (
              <input
                value={environment}
                onChange={(e) => setEnvironment(e.target.value)}
                placeholder="e.g. sandbox"
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
              />
            )}
          </Card>

          <Card padding={20} style={{ marginBottom: 16, opacity: environment ? 1 : 0.5 }}>
            <div className="flex items-center gap-2 mb-3">
              <StepDot done={selectedAgentIds.size > 0} />
              <h2 className="text-sm font-semibold" style={{ color: "var(--pr-text-primary)" }}>Which AI agents can use this connection?</h2>
            </div>
            <p className="text-xs mb-3" style={{ color: "var(--pr-text-muted)" }}>
              Every agent must be chosen explicitly -- there's no "all current and future agents" option.
            </p>
            {agents.length === 0 ? (
              <p className="text-xs" style={{ color: "var(--pr-text-disabled)" }}>No active agents available. Activate an agent first.</p>
            ) : (
              <div className="space-y-1.5 max-h-56 overflow-y-auto">
                {agents.map((a) => (
                  <label key={a.id} className="flex items-center gap-2 text-sm" style={{ color: "var(--pr-text-primary)" }}>
                    <input type="checkbox" checked={selectedAgentIds.has(a.id)} onChange={() => toggleAgent(a.id)} disabled={!environment} />
                    {a.name}
                  </label>
                ))}
              </div>
            )}
          </Card>

          {draftError && <Alert severity="error" className="text-sm mb-3">{draftError}</Alert>}
          <Button
            onClick={handleCreateDraft}
            disabled={!trustedConnectionReady || !mappingId || !environment || selectedAgentIds.size === 0 || creatingDraft}
          >
            {creatingDraft ? "Creating..." : "Create connection setup"}
          </Button>
        </>
      )}

      {draftId && (
        <Card padding={20} style={{ marginBottom: 16 }}>
          <p className="text-sm font-semibold mb-3" style={{ color: "var(--pr-text-primary)" }}>Ready to review</p>
          <dl className="grid grid-cols-1 gap-y-2 text-sm mb-4">
            <div className="flex justify-between"><dt style={{ color: "var(--pr-text-muted)" }}>System</dt><dd>{system.external_system_label}</dd></div>
            <div className="flex justify-between"><dt style={{ color: "var(--pr-text-muted)" }}>Action mapping</dt><dd>{selectedMapping ? `${selectedMapping.source_operation} v${selectedMapping.version}` : "-"}</dd></div>
            <div className="flex justify-between"><dt style={{ color: "var(--pr-text-muted)" }}>PayReality action</dt><dd>{selectedMapping ? humanizeAction(selectedMapping.canonical_action) : "-"}</dd></div>
            <div className="flex justify-between"><dt style={{ color: "var(--pr-text-muted)" }}>Trusted connection</dt><dd>{freshCredential?.identity.name ?? trustedConnections.find((t) => t.id === existingConnectionId)?.name}</dd></div>
            <div className="flex justify-between"><dt style={{ color: "var(--pr-text-muted)" }}>Environment</dt><dd>{formatStatus(environment)}</dd></div>
            <div className="flex justify-between"><dt style={{ color: "var(--pr-text-muted)" }}>Allowed agents</dt><dd>{selectedAgentIds.size}</dd></div>
          </dl>

          {testAvailable && (
            <div className="mb-4 pt-4" style={{ borderTop: "1px solid var(--pr-overlay-05)" }}>
              <p className="text-sm font-semibold mb-1" style={{ color: "var(--pr-text-primary)" }}>Test this connection</p>
              <p className="text-xs mb-3" style={{ color: "var(--pr-text-muted)" }}>
                This sends a real, signed attested operation and creates a genuine PayReality Decision --
                not a hypothetical simulation. Available now because this connection's credential is
                still in this browser's memory; it won't be after you leave this page.
              </p>
              <div className="grid grid-cols-1 gap-2 mb-3">
                <Select
                  value={testForm.originAgentId}
                  onChange={(e) => setTestForm((f) => ({ ...f, originAgentId: e.target.value }))}
                  className="w-full px-3 py-2 rounded-lg border text-sm"
                  containerClassName="block w-full"
                  style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                >
                  {Array.from(selectedAgentIds).map((id) => (
                    <option key={id} value={id}>{agents.find((a) => a.id === id)?.name ?? id}</option>
                  ))}
                </Select>
                {selectedMapping?.resource_path && (
                  <input value={testForm.resource} onChange={(e) => setTestForm((f) => ({ ...f, resource: e.target.value }))} placeholder="Resource (e.g. supplier:123)" className="w-full px-3 py-2 rounded-lg border text-sm" style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }} />
                )}
                {selectedMapping?.amount_path && (
                  <input type="number" value={testForm.amount} onChange={(e) => setTestForm((f) => ({ ...f, amount: e.target.value }))} placeholder="Amount" className="w-full px-3 py-2 rounded-lg border text-sm" style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }} />
                )}
                {selectedMapping?.currency_path && (
                  <input value={testForm.currency} onChange={(e) => setTestForm((f) => ({ ...f, currency: e.target.value }))} placeholder="Currency (e.g. USD)" className="w-full px-3 py-2 rounded-lg border text-sm" style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }} />
                )}
                {selectedMapping?.fact_subject_path && (
                  <input value={testForm.counterparty} onChange={(e) => setTestForm((f) => ({ ...f, counterparty: e.target.value }))} placeholder="Who/what this is about" className="w-full px-3 py-2 rounded-lg border text-sm" style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }} />
                )}
                {selectedMapping && Object.keys(selectedMapping.context_bindings).map((key) => (
                  <input
                    key={key}
                    value={testForm.context[key] ?? ""}
                    onChange={(e) => setTestForm((f) => ({ ...f, context: { ...f.context, [key]: e.target.value } }))}
                    placeholder={key}
                    className="w-full px-3 py-2 rounded-lg border text-sm"
                    style={{ backgroundColor: "var(--pr-bg-hover)", borderColor: "var(--pr-overlay-10)", color: "var(--pr-text-primary)" }}
                  />
                ))}
              </div>
              <Button variant="ghost" size="sm" onClick={handleSendTest} disabled={testing || !testForm.originAgentId}>
                <Send className="w-3.5 h-3.5 mr-1.5 inline" /> {testing ? "Sending..." : "Send test decision"}
              </Button>
              {testError && <Alert severity="error" className="text-sm mt-3">{testError}</Alert>}
              {testResult && (
                <Alert severity={testResult.outcome === "ALLOW" ? "success" : testResult.outcome === "DENY" ? "error" : "warning"} className="text-sm mt-3">
                  <p className="font-semibold">
                    {testResult.outcome === "ALLOW" ? "Allowed" : testResult.outcome === "DENY" ? "Not allowed" : "Needs human approval"}
                  </p>
                  <p>{describeReason(testResult.reason) ?? "No specific reason recorded."}</p>
                  <Link to={`/decisions/${testResult.decisionId}`} style={{ color: "var(--pr-authority-blue)" }}>View full decision &rarr;</Link>
                </Alert>
              )}
            </div>
          )}

          {!activated ? (
            <>
              <p className="text-xs mb-3" style={{ color: "var(--pr-text-muted)" }}>
                Activating makes this the connection your Adapter actually uses for {formatStatus(environment)}.
                If another connection is already active for this exact system, environment, and trusted
                connection, it will be retired automatically.
              </p>
              {canPublish ? (
                <Button onClick={handleActivate} disabled={activating}>{activating ? "Activating..." : "Activate connection"}</Button>
              ) : (
                <p className="text-xs" style={{ color: "var(--pr-warning-amber)" }}>Your role can prepare this connection but not activate it -- ask someone with connection-activation permission.</p>
              )}
              {activateError && <Alert severity="error" className="text-sm mt-3">{activateError}</Alert>}
            </>
          ) : (
            <div>
              <p className="text-sm font-semibold mb-3" style={{ color: "var(--pr-trust-green)" }}>Connection active.</p>
              <Button onClick={() => navigate(`/organization/integrations/${system.id}`)}>Back to {system.external_system_label}</Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
