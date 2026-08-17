import { apiClient } from "../live/apiClient";
import type { LivePrincipal } from "../live/types";
import { notifyResourceChanged } from "../services/resourceSync";
import type {
  CompileResult,
  DeployResult,
  DryRunResult,
  PolicyDiff,
  RuntimePolicy,
  RuntimePolicyRequest,
} from "./types";

const BASE = "/v1/runtime-policies";

// Milestone 13 Phase 6A: every state-changing authoring action below
// signals "policies changed" once it succeeds, so an already-open
// policy list/dashboard/Simulator page (in this tab or another) can
// pick up the new state without needing a manual reload. `dryRun` is
// deliberately excluded -- it's a simulation, it changes nothing.
export const policyStudioApi = {
  getVocabulary: () => apiClient.get<{ actions: string[] }>(`${BASE}/vocabulary`),
  // A rule's Scope.principal used to be a free-text field the author had
  // to type an exact ID into by hand (PAYREALITY_UX_REVIEW.md, usability
  // problem #6). Reuses the same /v1/principals list the Agent Directory
  // already shows, so the picker always reflects real principals.
  listPrincipals: () => apiClient.get<LivePrincipal[]>("/v1/principals"),
  list: (status?: string) =>
    apiClient.get<RuntimePolicy[]>(`${BASE}${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  get: (policyKey: string) => apiClient.get<RuntimePolicy>(`${BASE}/${policyKey}`),
  getVersions: (policyKey: string) => apiClient.get<RuntimePolicy[]>(`${BASE}/${policyKey}/versions`),
  getVersion: (policyKey: string, version: number) =>
    apiClient.get<RuntimePolicy>(`${BASE}/${policyKey}/versions/${version}`),
  create: (body: RuntimePolicyRequest) =>
    apiClient.post<RuntimePolicy>(BASE, body).then((r) => { notifyResourceChanged("policies"); return r; }),
  edit: (policyKey: string, body: RuntimePolicyRequest) =>
    apiClient.put<RuntimePolicy>(`${BASE}/${policyKey}`, body).then((r) => { notifyResourceChanged("policies"); return r; }),
  submitForReview: (policyKey: string) =>
    apiClient.post<RuntimePolicy>(`${BASE}/${policyKey}/submit-for-review`).then((r) => { notifyResourceChanged("policies"); return r; }),
  approve: (policyKey: string, approver: string) =>
    apiClient.post<RuntimePolicy>(`${BASE}/${policyKey}/approve`, { approver }).then((r) => { notifyResourceChanged("policies"); return r; }),
  reject: (policyKey: string, reviewer: string, reason: string) =>
    apiClient.post<RuntimePolicy>(`${BASE}/${policyKey}/reject`, { reviewer, reason }).then((r) => { notifyResourceChanged("policies"); return r; }),
  compile: (policyKey: string) =>
    apiClient.post<CompileResult>(`${BASE}/${policyKey}/compile`).then((r) => { notifyResourceChanged("policies"); return r; }),
  dryRun: (
    policyKey: string,
    body: { principal: string; action: string; resource?: string; context: Record<string, unknown> }
  ) => apiClient.post<DryRunResult>(`${BASE}/${policyKey}/dry-run`, body),
  deploy: (policyKey: string) =>
    apiClient.post<DeployResult>(`${BASE}/${policyKey}/deploy`).then((r) => { notifyResourceChanged("policies"); return r; }),
  diff: (policyKey: string, fromVersion: number, toVersion: number) =>
    apiClient.get<PolicyDiff>(`${BASE}/${policyKey}/diff?from_version=${fromVersion}&to_version=${toVersion}`),
};
