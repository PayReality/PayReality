import { apiClient } from "../live/apiClient";
import type {
  Conflict,
  Corpus,
  Coverage,
  Gap,
  GraphApproval,
  GraphDiff,
  GraphSummary,
  MissingInformationItem,
  Operation,
  Principal,
  PrincipalCandidate,
  Question,
  Relationship,
  ResolvePrincipalRequest,
  Resource,
} from "./types";

const BASE = "/v1/ai-authority-builder";

export const aiAuthorityBuilderApi = {
  getStatus: () => apiClient.get<{ ai_enabled: boolean }>(`${BASE}/status`),
  createCorpus: (name: string, files: File[]) => {
    const form = new FormData();
    form.append("name", name);
    for (const file of files) form.append("files", file);
    return apiClient.post<Corpus>(`${BASE}/corpora`, form);
  },
  listCorpora: () => apiClient.get<Corpus[]>(`${BASE}/corpora`),
  getCorpus: (corpusId: string) => apiClient.get<Corpus>(`${BASE}/corpora/${corpusId}`),
  getSummary: (corpusId: string) => apiClient.get<GraphSummary>(`${BASE}/corpora/${corpusId}/summary`),
  getPrincipals: (corpusId: string) => apiClient.get<Principal[]>(`${BASE}/corpora/${corpusId}/principals`),
  getResources: (corpusId: string) => apiClient.get<Resource[]>(`${BASE}/corpora/${corpusId}/resources`),
  getOperations: (corpusId: string) => apiClient.get<Operation[]>(`${BASE}/corpora/${corpusId}/operations`),
  getRelationships: (corpusId: string) => apiClient.get<Relationship[]>(`${BASE}/corpora/${corpusId}/relationships`),
  getConflicts: (corpusId: string) => apiClient.get<Conflict[]>(`${BASE}/corpora/${corpusId}/conflicts`),
  getGaps: (corpusId: string) => apiClient.get<Gap[]>(`${BASE}/corpora/${corpusId}/gaps`),
  getQuestions: (corpusId: string) => apiClient.get<Question[]>(`${BASE}/corpora/${corpusId}/questions`),
  answerQuestion: (questionId: string, answer: string) =>
    apiClient.post<Question>(`${BASE}/questions/${questionId}/answer`, { answer }),

  // Authority-as-a-continuous-object, Stage E/F reviewer workflow.
  getPrincipalCandidates: (authorityPrincipalId: string) =>
    apiClient.get<PrincipalCandidate[]>(`${BASE}/principals/${authorityPrincipalId}/candidates`),
  resolvePrincipal: (authorityPrincipalId: string, body: ResolvePrincipalRequest) =>
    apiClient.post<Principal>(`${BASE}/principals/${authorityPrincipalId}/resolve`, body),
  resolveRelationship: (relationshipId: string) =>
    apiClient.post<Relationship>(`${BASE}/relationships/${relationshipId}/resolve`),
  activateRelationship: (relationshipId: string) =>
    apiClient.post<Relationship>(`${BASE}/relationships/${relationshipId}/activate`),

  // Authority Intelligence Program, Phase 3: Explainability & Human Review.
  getCoverage: (corpusId: string) => apiClient.get<Coverage>(`${BASE}/corpora/${corpusId}/coverage`),
  getMissingInformation: (corpusId: string) =>
    apiClient.get<MissingInformationItem[]>(`${BASE}/corpora/${corpusId}/missing-information`),
  getDiff: (corpusId: string) => apiClient.get<GraphDiff>(`${BASE}/corpora/${corpusId}/diff`),
  approveGraph: (corpusId: string, approvalReason?: string) =>
    apiClient.post<GraphApproval>(`${BASE}/corpora/${corpusId}/approve`, { approval_reason: approvalReason ?? null }),
  getApprovals: (corpusId: string) => apiClient.get<GraphApproval[]>(`${BASE}/corpora/${corpusId}/approvals`),
};
