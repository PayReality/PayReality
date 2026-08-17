import { apiClient } from "../live/apiClient";
import { notifyResourceChanged } from "../services/resourceSync";
import type {
  ActivationImpactPreview,
  ActivationSchedule,
  LifecycleDashboard,
  PolicyLifecycleSummary,
  PolicySearchParams,
  PolicyTimeline,
} from "./types";

const BASE = "/v1/runtime-policies";
const CROSS = "/v1/runtime-policy-lifecycle";

function qs(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== "");
  if (entries.length === 0) return "";
  return `?${entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&")}`;
}

// Milestone 13 Phase 6A: every lifecycle transition below changes what
// a policy-dependent page (the Policy Engine dashboard, the Simulator,
// the Decision Center's policy display) should show -- signal it once
// the transition actually succeeds.
export const policyLifecycleApi = {
  activationPreview: (policyKey: string) =>
    apiClient.get<ActivationImpactPreview>(`${BASE}/${policyKey}/lifecycle/activation-preview`),
  activate: (policyKey: string, actor: string, reason?: string) =>
    apiClient.post<PolicyLifecycleSummary>(`${BASE}/${policyKey}/lifecycle/activate`, { actor, reason }).then((r) => { notifyResourceChanged("policies"); return r; }),
  scheduleActivation: (policyKey: string, effectiveAt: string, actor: string, reason?: string) =>
    apiClient.post<ActivationSchedule>(`${BASE}/${policyKey}/lifecycle/schedule-activation`, {
      effective_at: effectiveAt, actor, reason,
    }).then((r) => { notifyResourceChanged("policies"); return r; }),
  scheduleRetirement: (policyKey: string, effectiveAt: string, actor: string, reason?: string) =>
    apiClient.post<ActivationSchedule>(`${BASE}/${policyKey}/lifecycle/schedule-retirement`, {
      effective_at: effectiveAt, actor, reason,
    }).then((r) => { notifyResourceChanged("policies"); return r; }),
  cancelSchedule: (policyKey: string, scheduleId: string, actor: string, reason?: string) =>
    apiClient.post<ActivationSchedule>(`${BASE}/${policyKey}/lifecycle/schedules/${scheduleId}/cancel`, { actor, reason }).then((r) => { notifyResourceChanged("policies"); return r; }),
  retire: (policyKey: string, actor: string, reason?: string) =>
    apiClient.post<PolicyLifecycleSummary>(`${BASE}/${policyKey}/lifecycle/retire`, { actor, reason }).then((r) => { notifyResourceChanged("policies"); return r; }),
  deprecate: (policyKey: string, actor: string, reason?: string) =>
    apiClient.post<PolicyLifecycleSummary>(`${BASE}/${policyKey}/lifecycle/deprecate`, { actor, reason }).then((r) => { notifyResourceChanged("policies"); return r; }),
  archive: (policyKey: string, actor: string, reason?: string) =>
    apiClient.post<PolicyLifecycleSummary>(`${BASE}/${policyKey}/lifecycle/archive`, { actor, reason }).then((r) => { notifyResourceChanged("policies"); return r; }),
  rollback: (policyKey: string, targetVersion: number, actor: string, reason?: string) =>
    apiClient.post<PolicyLifecycleSummary>(`${BASE}/${policyKey}/lifecycle/rollback`, {
      target_version: targetVersion, actor, reason,
    }).then((r) => { notifyResourceChanged("policies"); return r; }),
  timeline: (policyKey: string) => apiClient.get<PolicyTimeline>(`${BASE}/${policyKey}/lifecycle/timeline`),
  schedules: (policyKey: string, status?: string) =>
    apiClient.get<ActivationSchedule[]>(`${BASE}/${policyKey}/lifecycle/schedules${qs({ status })}`),
  dashboard: () => apiClient.get<LifecycleDashboard>(`${CROSS}/dashboard`),
  search: (params: PolicySearchParams) =>
    apiClient.get<{ results: PolicyLifecycleSummary[] }>(`${CROSS}/search${qs(params)}`),
};
