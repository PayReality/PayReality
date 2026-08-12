import { apiClient } from "../live/apiClient";
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

export const policyLifecycleApi = {
  activationPreview: (policyKey: string) =>
    apiClient.get<ActivationImpactPreview>(`${BASE}/${policyKey}/lifecycle/activation-preview`),
  activate: (policyKey: string, actor: string, reason?: string) =>
    apiClient.post<PolicyLifecycleSummary>(`${BASE}/${policyKey}/lifecycle/activate`, { actor, reason }),
  scheduleActivation: (policyKey: string, effectiveAt: string, actor: string, reason?: string) =>
    apiClient.post<ActivationSchedule>(`${BASE}/${policyKey}/lifecycle/schedule-activation`, {
      effective_at: effectiveAt, actor, reason,
    }),
  scheduleRetirement: (policyKey: string, effectiveAt: string, actor: string, reason?: string) =>
    apiClient.post<ActivationSchedule>(`${BASE}/${policyKey}/lifecycle/schedule-retirement`, {
      effective_at: effectiveAt, actor, reason,
    }),
  cancelSchedule: (policyKey: string, scheduleId: string, actor: string, reason?: string) =>
    apiClient.post<ActivationSchedule>(`${BASE}/${policyKey}/lifecycle/schedules/${scheduleId}/cancel`, { actor, reason }),
  retire: (policyKey: string, actor: string, reason?: string) =>
    apiClient.post<PolicyLifecycleSummary>(`${BASE}/${policyKey}/lifecycle/retire`, { actor, reason }),
  deprecate: (policyKey: string, actor: string, reason?: string) =>
    apiClient.post<PolicyLifecycleSummary>(`${BASE}/${policyKey}/lifecycle/deprecate`, { actor, reason }),
  archive: (policyKey: string, actor: string, reason?: string) =>
    apiClient.post<PolicyLifecycleSummary>(`${BASE}/${policyKey}/lifecycle/archive`, { actor, reason }),
  rollback: (policyKey: string, targetVersion: number, actor: string, reason?: string) =>
    apiClient.post<PolicyLifecycleSummary>(`${BASE}/${policyKey}/lifecycle/rollback`, {
      target_version: targetVersion, actor, reason,
    }),
  timeline: (policyKey: string) => apiClient.get<PolicyTimeline>(`${BASE}/${policyKey}/lifecycle/timeline`),
  schedules: (policyKey: string, status?: string) =>
    apiClient.get<ActivationSchedule[]>(`${BASE}/${policyKey}/lifecycle/schedules${qs({ status })}`),
  dashboard: () => apiClient.get<LifecycleDashboard>(`${CROSS}/dashboard`),
  search: (params: PolicySearchParams) =>
    apiClient.get<{ results: PolicyLifecycleSummary[] }>(`${CROSS}/search${qs(params)}`),
};
