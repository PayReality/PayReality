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

// Phase 2B (PHASE_2B_LIVE_PER_CONDITION_EXPLAINABILITY_SUMMARY.md): the
// same shape GET /v1/runtime-policies/simulate already returns for each
// rule (server/app/schemas/policy_simulation.py's RuleEvaluationResponse/
// ConditionEvaluationResponse), reused verbatim rather than duplicated,
// for the explanatory (not authoritative) reconstruction of a decision.
export interface ConditionEvaluation {
  field: string;
  operator: string;
  expected_value: unknown;
  actual_value: unknown;
  passed: boolean;
}

export interface RuleEvaluation {
  policy_id: string;
  policy_name: string;
  principal: string;
  action: string;
  effect: string;
  scope_matched: boolean;
  conditions: ConditionEvaluation[];
  matched: boolean;
  summary: string;
}

// GET /v1/decisions/{id}/explanation. `available=false` is a real,
// distinct response (see `unavailable_reason`), not an error -- some
// historical decisions genuinely cannot be reconstructed.
export interface DecisionExplanation {
  decision_id: string;
  available: boolean;
  unavailable_reason: string | null;
  outcome: string | null;
  reason: string | null;
  policy_id: string | null;
  bundle_hash: string | null;
  bundle_version: number | null;
  compiled_at: string | null;
  activated_at: string | null;
  retired_at: string | null;
  evaluated_at: string | null;
  causal_policy_id: string | null;
  rules: RuleEvaluation[];
}

export interface LiveDecision {
  id: string;
  status: "PENDING" | "RESOLVED";
  outcome: DecisionOutcome;
  reason: string | null;
  agent_id: string;
  action: string;
  // Domain Generalization Milestone: optional -- a non-financial
  // decision (e.g. disable_user) genuinely has none of these three.
  resource: string | null;
  amount: number | null;
  currency: string | null;
  created_at: string;
  evaluated_mandates: string[];
  evaluated_mandate_ids: string[];
  enterprise_system_id: string | null;
  enterprise_system_name: string | null;
  // Runtime Decision Center V2, Phase 2A: read server-side off this
  // decision's own earliest Evidence record (GetDecisionResponse never
  // persists these on Decision itself). Null whenever no Evidence
  // record exists yet or no active policy was ever evaluated.
  policy_version: number | null;
  policy_bundle_hash: string | null;
  authority_version: string | null;
  resolution: LiveResolution | null;
  // Product Experience Remediation Milestone 1 (Decision Provenance +
  // Decision Detail contract): all additive, all None/null exactly when
  // GetDecisionResponse's own earliest-Evidence-record lookup finds
  // nothing -- the same optionality policy_version/policy_bundle_hash/
  // authority_version above already have, not a new failure mode.
  source: string | null;
  principal_name: string | null;
  evidence_id: string | null;
  facts_evaluated: Record<string, unknown>[] | null;
  matched_policy_freshness: PolicyFreshnessSummary | null;
  capability: CapabilitySummary | null;
  // Human Review Continuation (issue #10): trace/correlation metadata
  // only, echoed back exactly as the caller submitted it on the
  // originating Intent (or null if none was supplied) -- never an
  // authority signal, never used to select a policy.
  correlation_id: string | null;
}

// Issue #4 (Authorization Receipts), GET /v1/decisions/{id}/receipt: a
// stable, named projection assembling data that already exists
// (Decision/Intent/Evidence/Historical Policy Binding, + Trusted
// Enterprise Facts/human review/Capability Authorization where they
// apply) -- not a second Evidence system, not Capability Authorization
// itself (see AuthorizationReceiptPage.tsx for the distinction).
export interface ReceiptDecisionSummary {
  decision_id: string;
  outcome: DecisionOutcome;
  created_at: string;
  source: string | null;
}

export interface ReceiptActorSummary {
  agent_id: string;
  agent_name: string | null;
  principal_id: string | null;
  principal_name: string | null;
}

export interface ReceiptRequestSummary {
  action: string;
  resource: string | null;
  amount: number | null;
  currency: string | null;
  context: Record<string, unknown>;
  // Human Review Continuation (issue #10): the caller's own trace id,
  // kept on the receipt purely as historical metadata for an auditor to
  // cross-reference against their own system's logs -- not part of the
  // authorization decision itself.
  correlation_id: string | null;
}

export interface ReceiptPolicyManifestEntry {
  id: string;
  name: string;
  version: number;
  effect: string;
  scope: Record<string, unknown>;
}

export interface ReceiptAuthoritySummary {
  policy_id: string | null;
  bundle_hash: string | null;
  bundle_version: number | null;
  compiled_at: string | null;
  activated_at: string | null;
  retired_at: string | null;
  authority_version: string | null;
  policies: ReceiptPolicyManifestEntry[];
}

export interface ReceiptFactEntry {
  key: string;
  value: unknown;
  subject: string | null;
  source_id: string | null;
  observed_at: string | null;
  expires_at: string | null;
}

export interface ReceiptHumanReviewSummary {
  resolution: "approved" | "denied";
  resolved_by: string;
  reason: string | null;
  resolved_at: string;
}

export interface ReceiptEvidenceSummary {
  evidence_id: string;
  key_id: string;
  signature: string;
  previous_hash: string | null;
  payload_hash: string;
  status: "VERIFIED" | "PENDING" | "REJECTED";
  created_at: string;
}

export interface ReceiptVerification {
  signature_valid: boolean;
  key_id: string;
  algorithm: string;
  verified_at: string;
}

export interface AuthorizationReceipt {
  receipt_id: string;
  evidence_id: string;
  generated_at: string;
  decision: ReceiptDecisionSummary;
  actor: ReceiptActorSummary;
  request: ReceiptRequestSummary;
  authority: ReceiptAuthoritySummary;
  facts: ReceiptFactEntry[];
  human_review: ReceiptHumanReviewSummary | null;
  capability: CapabilitySummary | null;
  evidence: ReceiptEvidenceSummary;
  verification: ReceiptVerification;
}

// Pending Review queue (GET /v1/decisions): every HUMAN_REVIEW decision
// in this organization not yet resolved. Matches AgentListResponse's
// pagination envelope shape (schemas/agent.py), not a new convention.
export interface LiveDecisionListResponse {
  decisions: LiveDecision[];
  total: number;
  limit: number;
  offset: number;
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
  // Domain Generalization Milestone: all three now optional, and
  // included by the backend only when actually relevant to the action
  // -- a non-financial decision's Evidence carries no fabricated
  // amount, and currency is no longer silently dropped when present.
  resource?: string;
  amount?: string;
  currency?: string;
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

export interface SigningKeyHistoryEntry {
  key_id: string;
  algorithm: string;
  public_key_b64: string;
  created_at: string;
  retired_at: string | null;
  active: boolean;
}

export interface VerificationKeyHistoryResponse {
  keys: SigningKeyHistoryEntry[];
}

export interface ChainVerificationResponse {
  organization_id: string | null;
  total: number;
  intact: boolean;
  invalid_signatures: string[];
  broken_links: string[];
}

// Product Experience Remediation Milestone 1, Phase 6: GET
// /v1/assurance/summary's contract -- every field a real,
// organisation-scoped server aggregate, replacing the previous
// unbounded client-side scan over every Agent/Evidence record.
export interface AssuranceSummary {
  total_agents: number;
  active_agents: number;
  active_policies: number;
  policies_review_due: number;
  policies_authority_expired: number;
  allow_count: number;
  deny_count: number;
  human_review_count: number;
  pending_review_count: number;
  oldest_pending_review_at: string | null;
  resolved_review_count: number;
  evidence_total: number;
  evidence_verified: number;
  evidence_pending: number;
  evidence_rejected: number;
}

// Product Experience Remediation Milestone 1, Phase 4: the Decision
// Detail contract's additive fields (GetDecisionResponse).
export interface PolicyFreshnessSummary {
  policy_key: string;
  last_attested_at: string | null;
  next_review_at: string | null;
  authority_expires_at: string | null;
  status: "current" | "review_due" | "expired" | "unknown";
}

export interface CapabilitySummary {
  issued: boolean;
  audience: string | null;
  resource: string | null;
  action: string | null;
  expires_at: string | null;
  consumed_at: string | null;
}

// Core Product Experience Redesign: GET /v1/decisions/history's row shape
// (schemas/intent.py's DecisionHistoryItem) -- deliberately narrower than
// LiveDecision (no policy version/bundle hash/facts/capability/freshness
// detail; a caller wanting that opens the full Decision Detail page,
// GET /v1/decisions/{id}, instead). No amount/currency: contextual, not
// universal, and have no place in a summary row every action type shares.
export interface DecisionHistoryItem {
  id: string;
  created_at: string;
  agent_id: string;
  agent_name: string | null;
  principal_name: string | null;
  action: string;
  resource: string | null;
  outcome: DecisionOutcome;
  reason: string | null;
  matched_policy_name: string | null;
  source: string | null;
  has_evidence: boolean;
  human_review_state: "pending" | "resolved" | null;
  correlation_id: string | null;
}

export interface DecisionHistoryResponse {
  decisions: DecisionHistoryItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface DecisionHistoryFilters {
  limit?: number;
  offset?: number;
  outcome?: string;
  agent_id?: string;
  action?: string;
  resource?: string;
  source?: string;
}
