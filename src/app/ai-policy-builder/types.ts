// AI Policy Builder-specific types. Candidate content reuses Policy
// Studio's own RuntimePolicyRequest shape by import (RUNTIME_POLICY_MAPPING.md):
// a candidate's content is literally what a human would post to
// POST /v1/runtime-policies, so editing it can reuse Policy Studio's own
// ConditionRow/ScopeFields components unmodified.

import type { RuntimePolicyRequest } from "../policy-studio/types";

export type UploadFormat = "pdf" | "docx" | "xlsx" | "csv" | "text";
export type UploadStatus = "uploaded" | "extracted" | "failed";
export type CandidateStatus = "pending_review" | "promoted" | "dismissed";

export interface Upload {
  upload_id: string;
  filename: string;
  format: UploadFormat;
  status: UploadStatus;
  error: string | null;
  uploaded_at: string;
}

// Authority Graph -> RuntimePolicy Compilation Gate (issue #6): one
// structured reason promotion would be (or was) blocked -- mirrors
// domain/authority_graph/compilation_gate.GraphGateError exactly.
export interface GraphGateError {
  code: string;
  message: string;
  path: string | null;
}

// A read-only preview of whether promoting this candidate would
// succeed against its corpus's latest approved Authority Graph version
// -- undefined/null for a standalone (non-corpus) candidate, which has
// no graph to be ready or not ready against.
export interface GraphReadiness {
  ready: boolean;
  errors: GraphGateError[];
}

export interface Candidate {
  candidate_id: string;
  upload_id: string;
  corpus_id?: string | null;
  content: RuntimePolicyRequest;
  confidence: number;
  missing_fields: string[];
  source_excerpt: string | null;
  source_location: string | null;
  status: CandidateStatus;
  promoted_policy_key: string | null;
  created_at: string;
  graph_readiness?: GraphReadiness | null;
}

export interface ValidationErrorItem {
  field: string;
  code: string;
  message: string;
}

export interface PromoteResult {
  policy_key: string;
  version: number;
  status: string;
  // Authority-as-a-continuous-object, Stage I.4: non-null only when
  // promotion actually created a real Authority row for this candidate.
  authority_id: string | null;
  // Authority Graph -> RuntimePolicy Compilation Gate (issue #6):
  // non-null only when this promotion was gated on, and succeeded
  // against, a specific approved Authority Graph version.
  source_graph_approval_id?: string | null;
  source_graph_version?: number | null;
}
