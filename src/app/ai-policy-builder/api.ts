import { apiClient } from "../live/apiClient";
import { notifyResourceChanged } from "../services/resourceSync";
import type { RuntimePolicyRequest } from "../policy-studio/types";
import type { Candidate, PromoteResult, Upload } from "./types";

const BASE = "/v1/ai-policy-builder";

export const aiPolicyBuilderApi = {
  getStatus: () => apiClient.get<{ ai_enabled: boolean }>(`${BASE}/status`),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiClient.post<Upload>(`${BASE}/uploads`, form);
  },
  listUploads: () => apiClient.get<Upload[]>(`${BASE}/uploads`),
  getUpload: (uploadId: string) => apiClient.get<Upload>(`${BASE}/uploads/${uploadId}`),
  listCandidatesForUpload: (uploadId: string) =>
    apiClient.get<Candidate[]>(`${BASE}/uploads/${uploadId}/candidates`),
  listCandidatesForCorpus: (corpusId: string) =>
    apiClient.get<Candidate[]>(`${BASE}/candidates?corpus_id=${encodeURIComponent(corpusId)}`),
  listCandidates: (status?: string) =>
    apiClient.get<Candidate[]>(`${BASE}/candidates${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  editCandidate: (candidateId: string, content: RuntimePolicyRequest) =>
    apiClient.put<Candidate>(`${BASE}/candidates/${candidateId}`, { content }),
  dismissCandidate: (candidateId: string) =>
    apiClient.post<Candidate>(`${BASE}/candidates/${candidateId}/dismiss`),
  // Milestone 14: promotion creates a real new draft policy server-side,
  // exactly like every other policy-creating action in policy-studio/api.ts
  // -- PolicyListPage/RuntimePolicyDashboardPage need this signal to stay
  // fresh if left open in another tab while a candidate is promoted here.
  promoteCandidate: (candidateId: string) =>
    apiClient
      .post<PromoteResult>(`${BASE}/candidates/${candidateId}/promote`)
      .then((r) => { notifyResourceChanged("policies"); return r; }),
};
