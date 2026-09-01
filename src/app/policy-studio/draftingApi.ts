// Product Experience V3.2, Part C ("Draft with AI"): a separate file from
// api.ts's own core RuntimePolicy CRUD, since these calls never save,
// publish, or approve anything -- they only ever return a proposal for
// the caller to review (see server/app/services/policy_drafting_service.py's
// own module docstring for the same distinction, stated once, at the
// source of truth).
import { apiClient } from "../live/apiClient";
import type { RuntimePolicyRequest } from "./types";

const BASE = "/v1/policy-drafting";

export interface UnknownEntity {
  field: string;
  value: string;
}

export interface DraftResponse {
  proposal: RuntimePolicyRequest | null;
  clarifying_question: string | null;
  unknown_entities: UnknownEntity[];
  requires_additional_policies: boolean;
  additional_policies_note: string | null;
  confidence: number | null;
  missing_fields: string[];
}

export const policyDraftingApi = {
  draft: (instruction: string, currentDraft: RuntimePolicyRequest | null) =>
    apiClient.post<DraftResponse>(`${BASE}/draft`, { instruction, current_draft: currentDraft }),
  explain: (currentDraft: RuntimePolicyRequest, deterministicSummary: string, question?: string) =>
    apiClient
      .post<{ explanation: string }>(`${BASE}/explain`, {
        current_draft: currentDraft,
        deterministic_summary: deterministicSummary,
        question,
      })
      .then((r) => r.explanation),
};
