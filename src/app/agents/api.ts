import { apiClient } from "../live/apiClient";
import type { LiveAgent, LivePrincipal, PrincipalAuthorityContext } from "../live/types";
import { notifyResourceChanged } from "../services/resourceSync";
import type {
  AgentDetail,
  AgentListPage,
  AuditEvent,
  BulkActionResult,
  Certificate,
} from "./types";

const BASE = "/v1/agents";

export interface AgentFilters {
  status?: string;
  environment?: string;
  owner?: string;
  principal_id?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

function query(filters: AgentFilters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

// Milestone 13 Phase 6A (cross-page state synchronization): every
// mutation below already goes through this one module, so this is the
// single place to signal "agents changed" (and, where relevant,
// "certificates changed") once a mutation actually succeeds -- other
// already-mounted pages/tabs subscribed via useResourceSync pick this
// up; a page that mounts fresh (the common case, since routes are
// lazy-loaded and remount on navigation) already gets current data
// without needing this signal at all. Chained with `.then()` so the
// return value/type callers already depend on is unchanged.
export const agentsApi = {
  list: (filters: AgentFilters = {}) => apiClient.get<AgentListPage>(`${BASE}${query(filters)}`),
  listPrincipals: () => apiClient.get<LivePrincipal[]>("/v1/principals"),
  createPrincipal: (name: string) => apiClient.post<LivePrincipal>("/v1/principals", { name }),
  getPrincipalAuthorityContext: (principalId: string) =>
    apiClient.get<PrincipalAuthorityContext>(`/v1/principals/${principalId}/authority-context`),
  register: (body: { name: string; acting_for_principal_id: string; public_key: string; owner?: string; description?: string }) =>
    apiClient.post<LiveAgent>(BASE, body).then((r) => { notifyResourceChanged("agents"); return r; }),
  getDetail: (agentId: string) => apiClient.get<AgentDetail>(`${BASE}/${agentId}`),
  update: (agentId: string, body: Partial<{
    description: string; purpose: string; model: string; version: string;
    runtime: string; platform: string; environment: string; tags: string[]; labels: string[];
  }>) => apiClient.patch<LiveAgent>(`${BASE}/${agentId}`, body).then((r) => { notifyResourceChanged("agents"); return r; }),
  activate: (agentId: string, reason?: string) =>
    apiClient.post<LiveAgent>(`${BASE}/${agentId}/activate`, { reason }).then((r) => { notifyResourceChanged("agents"); return r; }),
  suspend: (agentId: string, reason?: string) =>
    apiClient.post<LiveAgent>(`${BASE}/${agentId}/suspend`, { reason }).then((r) => { notifyResourceChanged("agents"); return r; }),
  retire: (agentId: string, reason?: string) =>
    apiClient.post<LiveAgent>(`${BASE}/${agentId}/retire`, { reason }).then((r) => { notifyResourceChanged("agents"); return r; }),
  revoke: (agentId: string, reason?: string) =>
    apiClient.post<LiveAgent>(`${BASE}/${agentId}/revoke`, { reason }).then((r) => {
      notifyResourceChanged("agents");
      notifyResourceChanged("certificates");
      return r;
    }),
  rotate: (agentId: string, newPublicKey: string) =>
    apiClient.post<Certificate>(`${BASE}/${agentId}/rotate`, { new_public_key: newPublicKey }).then((r) => {
      notifyResourceChanged("certificates");
      return r;
    }),
  transfer: (agentId: string, newOwner: string, newBusinessUnit?: string) =>
    apiClient.post<LiveAgent>(`${BASE}/${agentId}/transfer`, {
      new_owner: newOwner, new_business_unit: newBusinessUnit,
    }).then((r) => { notifyResourceChanged("agents"); return r; }),
  listCertificates: (agentId: string) => apiClient.get<Certificate[]>(`${BASE}/${agentId}/certificates`),
  listAuditEvents: (agentId: string) => apiClient.get<AuditEvent[]>(`${BASE}/${agentId}/audit`),
  verifyAuditEvent: (agentId: string, eventId: string) =>
    apiClient.post<{ valid: boolean }>(`${BASE}/${agentId}/audit/${eventId}/verify`),
  bulkSuspend: (agentIds: string[], reason?: string) =>
    apiClient.post<BulkActionResult>(`${BASE}/bulk/suspend`, { agent_ids: agentIds, reason }).then((r) => { notifyResourceChanged("agents"); return r; }),
  bulkActivate: (agentIds: string[]) =>
    apiClient.post<BulkActionResult>(`${BASE}/bulk/activate`, { agent_ids: agentIds }).then((r) => { notifyResourceChanged("agents"); return r; }),
  bulkRetire: (agentIds: string[], reason?: string) =>
    apiClient.post<BulkActionResult>(`${BASE}/bulk/retire`, { agent_ids: agentIds, reason }).then((r) => { notifyResourceChanged("agents"); return r; }),
  bulkRequestRotation: (agentIds: string[]) =>
    apiClient.post<BulkActionResult>(`${BASE}/bulk/rotate`, { agent_ids: agentIds }).then((r) => {
      notifyResourceChanged("certificates");
      return r;
    }),
};
