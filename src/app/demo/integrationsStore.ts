import type {
  ActionMapping,
  AllowedAgent,
  IntegrationSystem,
  RuntimeConnection,
  TrustedConnection,
  TrustedConnectionCertificate,
} from "../integrations/types";
import {
  demoAllowedAgents,
  demoConnections,
  demoMappings,
  demoSystems,
  demoTrustedConnectionCertificates,
  demoTrustedConnections,
} from "./fixtures/integrations";

// Trusted Integration Architecture, Phase 4: the session-local mutable
// overlay for the demo's mock Integrations lifecycle -- same
// architectural shape as liveFeed.ts's own registeredAgents/
// registeredPrincipals overlay (seeded from the curated fixture set,
// then a visitor's own creates/edits/transitions get appended on top),
// kept in its own module since this is a genuinely separate domain
// from the live decision feed, not because the pattern differs.

let systems: IntegrationSystem[] = [...demoSystems];
let mappings: ActionMapping[] = [...demoMappings];
let trustedConnections: TrustedConnection[] = [...demoTrustedConnections];
let certificates: TrustedConnectionCertificate[] = [...demoTrustedConnectionCertificates];
let connections: RuntimeConnection[] = [...demoConnections];
const allowedAgentsByConnection: Record<string, AllowedAgent[]> = { ...demoAllowedAgents };

function id(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}
function now(): string {
  return new Date().toISOString();
}

// -- Systems -----------------------------------------------------------

export function listSystems(): IntegrationSystem[] {
  return systems;
}
export function getSystem(systemId: string): IntegrationSystem | undefined {
  return systems.find((s) => s.id === systemId);
}
export function createSystem(externalSystemLabel: string): IntegrationSystem {
  const system: IntegrationSystem = {
    id: id("system"), organization_id: "org-demo", external_system_label: externalSystemLabel,
    created_by: "you@example.com", created_at: now(),
  };
  systems = [system, ...systems];
  return system;
}

// -- Action mappings -----------------------------------------------------

export function listMappings(systemId: string): ActionMapping[] {
  return mappings.filter((m) => m.integration_id === systemId);
}
export function getMapping(mappingId: string): ActionMapping | undefined {
  return mappings.find((m) => m.id === mappingId);
}
export function createMapping(systemId: string, body: Partial<ActionMapping> & { source_operation: string; canonical_action: string }): ActionMapping {
  const siblingVersions = mappings.filter((m) => m.integration_id === systemId && m.source_operation === body.source_operation);
  const mapping: ActionMapping = {
    id: id("mapping"), integration_id: systemId, organization_id: "org-demo",
    source_operation: body.source_operation, version: siblingVersions.length + 1,
    canonical_action: body.canonical_action,
    resource_path: body.resource_path ?? null, fact_subject_path: body.fact_subject_path ?? null,
    amount_path: body.amount_path ?? null, currency_path: body.currency_path ?? null,
    context_bindings: body.context_bindings ?? {}, content_hash: null,
    source_schema_fingerprint: body.source_schema_fingerprint ?? null,
    status: "draft", created_by: "you@example.com", created_at: now(),
    validated_at: null, approved_by: null, approved_at: null, retired_at: null,
  };
  mappings = [mapping, ...mappings];
  return mapping;
}
export function editMapping(mappingId: string, patch: Partial<ActionMapping>): ActionMapping | undefined {
  const existing = getMapping(mappingId);
  if (!existing || existing.status !== "draft") return undefined;
  const updated = { ...existing, ...patch };
  mappings = mappings.map((m) => (m.id === mappingId ? updated : m));
  return updated;
}
export function validateMapping(mappingId: string): ActionMapping | undefined {
  const existing = getMapping(mappingId);
  if (!existing || existing.status !== "draft") return undefined;
  const updated: ActionMapping = { ...existing, status: "validated", validated_at: now(), content_hash: `sha256:demo-${mappingId.slice(-8)}` };
  mappings = mappings.map((m) => (m.id === mappingId ? updated : m));
  return updated;
}
export function approveMapping(mappingId: string, approver: string): ActionMapping | undefined {
  const existing = getMapping(mappingId);
  if (!existing || existing.status !== "validated") return undefined;
  const updated: ActionMapping = { ...existing, status: "approved", approved_by: approver, approved_at: now() };
  mappings = mappings.map((m) => (m.id === mappingId ? updated : m));
  return updated;
}
export function retireMapping(mappingId: string): ActionMapping | undefined {
  const existing = getMapping(mappingId);
  if (!existing || existing.status !== "approved") return undefined;
  if (connections.some((c) => c.integration_contract_version_id === mappingId && c.status === "active")) return undefined;
  const updated: ActionMapping = { ...existing, status: "retired", retired_at: now() };
  mappings = mappings.map((m) => (m.id === mappingId ? updated : m));
  return updated;
}

// -- Trusted connections --------------------------------------------------

export function listTrustedConnections(): TrustedConnection[] {
  return trustedConnections;
}
export function getTrustedConnection(identityId: string): TrustedConnection | undefined {
  return trustedConnections.find((t) => t.id === identityId);
}
export function listTrustedConnectionCertificates(identityId: string): TrustedConnectionCertificate[] {
  return certificates.filter((c) => c.integration_identity_id === identityId);
}
export function registerTrustedConnection(name: string): TrustedConnection {
  const identity: TrustedConnection = {
    id: id("trusted-connection"), organization_id: "org-demo", name, status: "registered",
    created_by: "you@example.com", created_at: now(),
  };
  trustedConnections = [identity, ...trustedConnections];
  certificates = [
    { id: id("certificate"), integration_identity_id: identity.id, status: "issued", issued_at: now(), activated_at: null, rotated_at: null, expires_at: null, revoked_at: null },
    ...certificates,
  ];
  return identity;
}
export function activateTrustedConnection(identityId: string): TrustedConnection | undefined {
  const existing = getTrustedConnection(identityId);
  if (!existing) return undefined;
  const updated: TrustedConnection = { ...existing, status: "active" };
  trustedConnections = trustedConnections.map((t) => (t.id === identityId ? updated : t));
  certificates = certificates.map((c) =>
    c.integration_identity_id === identityId && c.status === "issued" ? { ...c, status: "active", activated_at: now() } : c
  );
  return updated;
}
function transitionTrustedConnection(identityId: string, status: TrustedConnection["status"]): TrustedConnection | undefined {
  const existing = getTrustedConnection(identityId);
  if (!existing) return undefined;
  const updated: TrustedConnection = { ...existing, status };
  trustedConnections = trustedConnections.map((t) => (t.id === identityId ? updated : t));
  return updated;
}
export function suspendTrustedConnection(identityId: string) { return transitionTrustedConnection(identityId, "suspended"); }
export function revokeTrustedConnection(identityId: string) { return transitionTrustedConnection(identityId, "revoked"); }
export function retireTrustedConnection(identityId: string) { return transitionTrustedConnection(identityId, "retired"); }
export function rotateTrustedConnectionCredential(identityId: string): TrustedConnectionCertificate | undefined {
  if (!getTrustedConnection(identityId)) return undefined;
  certificates = certificates.map((c) =>
    c.integration_identity_id === identityId && c.status === "active" ? { ...c, status: "rotated", rotated_at: now() } : c
  );
  const fresh: TrustedConnectionCertificate = {
    id: id("certificate"), integration_identity_id: identityId, status: "active", issued_at: now(), activated_at: now(), rotated_at: null, expires_at: null, revoked_at: null,
  };
  certificates = [fresh, ...certificates];
  return fresh;
}

// -- Runtime connections ---------------------------------------------------

export function listConnections(): RuntimeConnection[] {
  return connections;
}
export function getConnection(connectionId: string): RuntimeConnection | undefined {
  return connections.find((c) => c.id === connectionId);
}
export function listAllowedAgents(connectionId: string): AllowedAgent[] {
  return allowedAgentsByConnection[connectionId] ?? [];
}
export function createDraftConnection(body: {
  integration_identity_id: string; integration_contract_version_id: string; environment: string; agent_ids?: string[];
  agentDirectory: AllowedAgent[];
}): RuntimeConnection | undefined {
  const mapping = getMapping(body.integration_contract_version_id);
  if (!mapping) return undefined;
  const connection: RuntimeConnection = {
    id: id("connection"), organization_id: "org-demo",
    integration_identity_id: body.integration_identity_id,
    integration_contract_version_id: body.integration_contract_version_id,
    integration_id: mapping.integration_id, source_operation: mapping.source_operation,
    environment: body.environment, status: "draft", created_by: "you@example.com",
    created_at: now(), activated_at: null, retired_at: null, allowed_agent_ids: body.agent_ids ?? [],
  };
  connections = [connection, ...connections];
  allowedAgentsByConnection[connection.id] = (body.agent_ids ?? [])
    .map((agentId) => body.agentDirectory.find((a) => a.id === agentId))
    .filter((a): a is AllowedAgent => !!a);
  return connection;
}
export function activateConnection(connectionId: string): RuntimeConnection | undefined {
  const existing = getConnection(connectionId);
  if (!existing || existing.status !== "draft") return undefined;
  if (existing.allowed_agent_ids.length === 0) return undefined;
  // Same real invariant the backend enforces: retire whichever binding
  // previously held this exact scope.
  connections = connections.map((c) => {
    if (
      c.id !== connectionId && c.status === "active" &&
      c.integration_identity_id === existing.integration_identity_id &&
      c.integration_id === existing.integration_id &&
      c.source_operation === existing.source_operation &&
      c.environment === existing.environment
    ) {
      return { ...c, status: "retired", retired_at: now() };
    }
    return c;
  });
  const updated: RuntimeConnection = { ...existing, status: "active", activated_at: now() };
  connections = connections.map((c) => (c.id === connectionId ? updated : c));
  return updated;
}
export function retireConnection(connectionId: string): RuntimeConnection | undefined {
  const existing = getConnection(connectionId);
  if (!existing || existing.status !== "active") return undefined;
  const updated: RuntimeConnection = { ...existing, status: "retired", retired_at: now() };
  connections = connections.map((c) => (c.id === connectionId ? updated : c));
  return updated;
}
