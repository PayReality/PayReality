export interface LivePrincipal {
  id: string;
  name: string;
  created_at: string;
  // Authority-as-a-continuous-object, Stage I.9: additive. Already
  // returned by GET /v1/principals (Stage B), just not read until now.
  role?: string | null;
}

// Phase 9 (AGENT_LIFECYCLE.md): status gained 'registered' (exists, not
// yet operational) and 'retired' (terminal, permanently removed from
// operational use) alongside the original three.
export type AgentStatus = "registered" | "active" | "suspended" | "revoked" | "retired";
export type AgentHealth = "healthy" | "warning" | "offline" | "unknown";

export interface LiveAgent {
  id: string;
  certificate_id: string | null;
  certificate_status: string | null;
  name: string;
  acting_for_principal_id: string;
  status: AgentStatus;
  owner: string | null;
  business_unit: string | null;
  environment: string | null;
  tags: string[];
  description: string | null;
  purpose: string | null;
  model: string | null;
  version: string | null;
  runtime: string | null;
  platform: string | null;
  labels: string[];
  sdk_version: string | null;
  last_seen_at: string | null;
  health: AgentHealth;
  rotation_requested_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface LiveDocument {
  document_id: string;
  name: string;
  status: "extraction_pending" | "extracted" | "extraction_failed";
  uploaded_at: string;
}

export interface LiveAuthority {
  authority_id: string;
  document_id: string;
  principal_id: string;
  scope: string;
  limit_amount: number | null;
  currency: string | null;
  conditions: unknown[];
  source_excerpt: string | null;
  source_page: number | null;
  status: "pending_review" | "approved" | "rejected";
  reviewer_id: string | null;
  rejection_reason: string | null;
  validation_flags: string[];
}

export interface LivePolicy {
  policy_id: string;
  version: number;
  status: "draft" | "compiled" | "active" | "retired";
  bundle_hash: string;
  compiled_at: string | null;
  activated_at: string | null;
  retired_at: string | null;
}

export type DecisionOutcome = "ALLOW" | "DENY" | "HUMAN_REVIEW";

export interface LiveDecisionSummary {
  outcome: DecisionOutcome;
  decision_id: string;
  evaluated_mandates: string[];
  // Authority-as-a-continuous-object, Stage H: real Mandate row ids,
  // additive alongside the legacy policy-key list above. Empty whenever
  // none of the matched policies have a Stage-G-created Mandate yet.
  evaluated_mandate_ids: string[];
  // Phase 5, Release 2 (Enterprise System binding): both null whenever
  // no matched policy configured, or still references, a real
  // EnterpriseSystem row -- never fabricated.
  enterprise_system_id: string | null;
  enterprise_system_name: string | null;
  reason: string | null;
}

export interface SubmitIntentResult {
  intent_id: string;
  decision: LiveDecisionSummary;
  evidence_id: string;
  status: "PENDING" | "RESOLVED";
}

export interface LiveResolution {
  resolution: "approved" | "denied";
  resolved_by: string;
  reason: string | null;
  created_at: string;
}

export interface LiveDecision {
  id: string;
  status: "PENDING" | "RESOLVED";
  outcome: DecisionOutcome;
  reason: string | null;
  agent_id: string;
  action: string;
  amount: number;
  currency: string;
  evaluated_mandates: string[];
  evaluated_mandate_ids: string[];
  enterprise_system_id: string | null;
  enterprise_system_name: string | null;
  resolution: LiveResolution | null;
}

// Runtime Authority Context (PHASE_2_RUNTIME_CONTEXT.md), as assembled by
// authority_context_service.resolve_runtime_authority_context and carried
// into Evidence unchanged (Stage C). Every field is additive: a Principal
// with none of these resolved yet produces a context of mostly-null
// fields, never an error.
export interface AuthorityContext {
  organization: string | null;
  business_unit: string | null;
  department: string | null;
  team: string | null;
  role: string | null;
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  delegations: DelegationEdge[];
}

export interface DelegationEdge {
  id: string;
  from_principal_id: string | null;
  resource_id: string | null;
  operation: string | null;
}

// GET /v1/principals/{id}/authority-context (Stage I.9): the same
// resolution AuthorityContext above carries, exposed standalone and
// identity-only -- no risk_level, since that's an Intent-time concept,
// not a Principal identity one.
export interface PrincipalAuthorityContext {
  organization: string | null;
  business_unit: string | null;
  department: string | null;
  team: string | null;
  role: string | null;
  delegations: DelegationEdge[];
}

// Evidence.payload's signed JSON shape (intent_service._build_evidence_payload).
// Every field from principal_id onward is optional/additive (Stage C/H):
// absent on records predating that work, or whenever the acting
// Principal or its authority chain never resolved -- absence here is
// never rendered as a claim that no authority applied.
export interface EvidencePayload {
  payload_version: number;
  decision_id: string;
  agent_id: string;
  action: string;
  amount: string;
  matched_mandate_ids: string[];
  authority_outcome: DecisionOutcome;
  approval_outcome: string | null;
  risk_classification: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  approver: string | null;
  recorded_at: string;
  previous_hash: string | null;
  principal_id?: string;
  // Runtime Governance Architecture, Phase 4: the resolved principal name
  // pinned at evaluation time (server/app/services/intent_service.py's
  // _build_evidence_payload) -- already written by the backend today,
  // just not previously declared on this frontend type.
  principal_name?: string;
  authority_context?: AuthorityContext;
  delegation_chain?: DelegationEdge[];
  evaluated_mandate_ids?: string[];
  authority_ids?: string[];
  // Runtime Governance Architecture, Phase 1: version-pins this record's
  // Decision Evidence to the exact engine/policy state it was evaluated
  // against. Present whenever a matched active policy existed at
  // evaluation time; already real and written by the backend, just not
  // previously declared here.
  authority_version?: string;
  policy_version?: number;
  policy_bundle_hash?: string;
  // Written only by resolution_service.resolve_decision, on the second,
  // separate Evidence record a HUMAN_REVIEW resolution appends -- absent
  // on every record created at submission time.
  resolved_by?: string;
  responsible_party?: string;
  reviewer?: string;
  review_outcome?: string;
  // Phase 5, Release 2 (Enterprise System binding): present only when
  // resolve_enterprise_system found a matched policy configured with,
  // and still referencing, a real EnterpriseSystem row.
  enterprise_system_id?: string;
  enterprise_system_name?: string;
}

export interface LiveEvidence {
  evidence_id: string;
  decision_id: string;
  payload: EvidencePayload;
  key_id: string;
  signature: string;
  status: "VERIFIED" | "PENDING" | "REJECTED";
  created_at: string;
}
