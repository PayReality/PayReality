import { apiClient } from "./apiClient";
import type { AuthorizationReceipt, DecisionHistoryFilters, DecisionHistoryResponse, LiveDecision } from "./types";

const BASE = "/v1/decisions";

// Same URLSearchParams-from-a-filter-object convention agents/api.ts's
// own query() already uses -- not a second pattern for the same thing.
function query(filters: DecisionHistoryFilters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

export const decisionsApi = {
  // Core Product Experience Redesign: the Decision Center's primary data
  // source. Filters are sent to the backend, never applied client-side
  // against an unbounded fetch-all.
  history: (filters: DecisionHistoryFilters = {}) =>
    apiClient.get<DecisionHistoryResponse>(`${BASE}/history${query(filters)}`),
  get: (decisionId: string) => apiClient.get<LiveDecision>(`${BASE}/${decisionId}`),
  // Issue #4 (Authorization Receipts): a stable, named, read-only
  // artifact assembling this decision's own Evidence + Historical
  // Policy Binding -- computed fresh on every request, never cached.
  getReceipt: (decisionId: string) => apiClient.get<AuthorizationReceipt>(`${BASE}/${decisionId}/receipt`),
};
