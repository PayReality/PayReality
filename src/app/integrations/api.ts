import { apiClient } from "../live/apiClient";
import { notifyResourceChanged } from "../services/resourceSync";
import type {
  ActionMapping,
  AllowedAgent,
  IntegrationSystem,
  RuntimeConnection,
  TrustedConnection,
  TrustedConnectionCertificate,
} from "./types";

const SYSTEMS_BASE = "/v1/integrations";
const CONNECTIONS_BASE = "/v1/enforcement-bindings";
const TRUSTED_CONNECTIONS_BASE = "/v1/integration-identities";

export interface CreateMappingBody {
  source_operation: string;
  canonical_action: string;
  resource_path?: string | null;
  fact_subject_path?: string | null;
  amount_path?: string | null;
  currency_path?: string | null;
  context_bindings?: Record<string, string>;
  source_schema_fingerprint?: string | null;
}

export type EditMappingBody = Partial<CreateMappingBody>;

// Trusted Integration Architecture, Phase 4: the primary product-facing
// client for Settings -> Integrations. Mirrors agentsApi.ts's own shape
// (a plain object of thin apiClient calls, mutations chained through
// notifyResourceChanged so other mounted pages/tabs refresh) -- the
// resource kind is "integrations" throughout, covering all four
// backend resources this feature spans (System, Action Mapping,
// Trusted Connection, Runtime Connection), since they're always viewed
// and edited together on the same screens.
export const integrationsApi = {
  // -- Systems (Integration) ------------------------------------------
  listSystems: () => apiClient.get<IntegrationSystem[]>(SYSTEMS_BASE),
  getSystem: (systemId: string) => apiClient.get<IntegrationSystem>(`${SYSTEMS_BASE}/${systemId}`),
  createSystem: (externalSystemLabel: string) =>
    apiClient.post<IntegrationSystem>(SYSTEMS_BASE, { external_system_label: externalSystemLabel })
      .then((r) => { notifyResourceChanged("integrations"); return r; }),

  // -- Action mappings (IntegrationContractVersion) --------------------
  listMappings: (systemId: string) =>
    apiClient.get<ActionMapping[]>(`${SYSTEMS_BASE}/${systemId}/contract-versions`),
  getMapping: (systemId: string, mappingId: string) =>
    apiClient.get<ActionMapping>(`${SYSTEMS_BASE}/${systemId}/contract-versions/${mappingId}`),
  createMapping: (systemId: string, body: CreateMappingBody) =>
    apiClient.post<ActionMapping>(`${SYSTEMS_BASE}/${systemId}/contract-versions`, body)
      .then((r) => { notifyResourceChanged("integrations"); return r; }),
  editMapping: (systemId: string, mappingId: string, body: EditMappingBody) =>
    apiClient.patch<ActionMapping>(`${SYSTEMS_BASE}/${systemId}/contract-versions/${mappingId}`, body)
      .then((r) => { notifyResourceChanged("integrations"); return r; }),
  validateMapping: (systemId: string, mappingId: string) =>
    apiClient.post<ActionMapping>(`${SYSTEMS_BASE}/${systemId}/contract-versions/${mappingId}/validate`)
      .then((r) => { notifyResourceChanged("integrations"); return r; }),
  approveMapping: (systemId: string, mappingId: string, approver: string) =>
    apiClient.post<ActionMapping>(`${SYSTEMS_BASE}/${systemId}/contract-versions/${mappingId}/approve`, { approver })
      .then((r) => { notifyResourceChanged("integrations"); return r; }),
  retireMapping: (systemId: string, mappingId: string) =>
    apiClient.post<ActionMapping>(`${SYSTEMS_BASE}/${systemId}/contract-versions/${mappingId}/retire`)
      .then((r) => { notifyResourceChanged("integrations"); return r; }),

  // -- Trusted connections (IntegrationIdentity) -----------------------
  listTrustedConnections: () => apiClient.get<TrustedConnection[]>(TRUSTED_CONNECTIONS_BASE),
  getTrustedConnection: (id: string) => apiClient.get<TrustedConnection>(`${TRUSTED_CONNECTIONS_BASE}/${id}`),
  listTrustedConnectionCertificates: (id: string) =>
    apiClient.get<TrustedConnectionCertificate[]>(`${TRUSTED_CONNECTIONS_BASE}/${id}/certificates`),
  registerTrustedConnection: (name: string, publicKey: string) =>
    apiClient.post<TrustedConnection>(TRUSTED_CONNECTIONS_BASE, { name, public_key: publicKey })
      .then((r) => { notifyResourceChanged("integrations"); return r; }),
  activateTrustedConnection: (id: string) =>
    apiClient.post<TrustedConnection>(`${TRUSTED_CONNECTIONS_BASE}/${id}/activate`)
      .then((r) => { notifyResourceChanged("integrations"); return r; }),
  suspendTrustedConnection: (id: string) =>
    apiClient.post<TrustedConnection>(`${TRUSTED_CONNECTIONS_BASE}/${id}/suspend`)
      .then((r) => { notifyResourceChanged("integrations"); return r; }),
  revokeTrustedConnection: (id: string) =>
    apiClient.post<TrustedConnection>(`${TRUSTED_CONNECTIONS_BASE}/${id}/revoke`)
      .then((r) => { notifyResourceChanged("integrations"); return r; }),
  retireTrustedConnection: (id: string) =>
    apiClient.post<TrustedConnection>(`${TRUSTED_CONNECTIONS_BASE}/${id}/retire`)
      .then((r) => { notifyResourceChanged("integrations"); return r; }),
  rotateTrustedConnectionCredential: (id: string, newPublicKey: string) =>
    apiClient.post<TrustedConnectionCertificate>(`${TRUSTED_CONNECTIONS_BASE}/${id}/rotate`, { new_public_key: newPublicKey })
      .then((r) => { notifyResourceChanged("integrations"); return r; }),

  // -- Runtime connections (EnforcementBinding) -------------------------
  listConnections: () => apiClient.get<RuntimeConnection[]>(CONNECTIONS_BASE),
  getConnection: (id: string) => apiClient.get<RuntimeConnection>(`${CONNECTIONS_BASE}/${id}`),
  createDraftConnection: (body: {
    integration_identity_id: string; integration_contract_version_id: string; environment: string; agent_ids?: string[];
  }) => apiClient.post<RuntimeConnection>(CONNECTIONS_BASE, body).then((r) => { notifyResourceChanged("integrations"); return r; }),
  editDraftConnection: (id: string, body: Partial<{
    integration_identity_id: string; integration_contract_version_id: string; environment: string;
  }>) => apiClient.patch<RuntimeConnection>(`${CONNECTIONS_BASE}/${id}`, body).then((r) => { notifyResourceChanged("integrations"); return r; }),
  addAllowedAgent: (connectionId: string, agentId: string) =>
    apiClient.post<RuntimeConnection>(`${CONNECTIONS_BASE}/${connectionId}/allowed-agents`, { agent_id: agentId })
      .then((r) => { notifyResourceChanged("integrations"); return r; }),
  removeAllowedAgent: (connectionId: string, agentId: string) =>
    apiClient.delete<RuntimeConnection>(`${CONNECTIONS_BASE}/${connectionId}/allowed-agents/${agentId}`)
      .then((r) => { notifyResourceChanged("integrations"); return r; }),
  listAllowedAgents: (connectionId: string) =>
    apiClient.get<AllowedAgent[]>(`${CONNECTIONS_BASE}/${connectionId}/allowed-agents`),
  activateConnection: (id: string) =>
    apiClient.post<RuntimeConnection>(`${CONNECTIONS_BASE}/${id}/activate`)
      .then((r) => { notifyResourceChanged("integrations"); return r; }),
  retireConnection: (id: string) =>
    apiClient.post<RuntimeConnection>(`${CONNECTIONS_BASE}/${id}/retire`)
      .then((r) => { notifyResourceChanged("integrations"); return r; }),
};
