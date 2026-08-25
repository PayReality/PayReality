// Mirrors server/app/schemas/runtime_policy.py exactly. Kept in sync by
// hand since this app has no codegen step; if these drift from the
// backend, the symptom is a runtime shape mismatch, not a compile error,
// the same tradeoff every other page in src/app/live/ already accepts.

export type PolicyStatus =
  | "draft"
  | "pending_review"
  | "approved"
  | "rejected"
  | "compiled"
  | "active"
  | "retired"
  | "archived";

// Runtime Policy Lifecycle (Phase 5): "superseded" is never a stored
// status (see server/app/domain/runtime_policy/runtime_policy.py's
// PolicyStatus.ARCHIVED docstring) -- it's a read-side label the backend
// computes for a "retired" row that has a newer active sibling. Mirrored
// here as its own type so the frontend can render it distinctly from a
// row that's simply "retired" with nothing replacing it.
export type EffectiveStatus = PolicyStatus | "superseded";

export type Effect = "allow" | "deny" | "require_human_review";

export interface Scope {
  principal: string;
  action: string;
  agent: string | null;
  resource: string | null;
}

export interface Condition {
  field: string;
  operator: string;
  value: string | number | boolean | (string | number)[];
}

export interface Constraints {
  delegated_by: string | null;
  expires: string | null;
  evidence_required: boolean;
  risk_level: string | null;
  // Authority-as-a-continuous-object, Stage G: system-set at promotion
  // (authority_id) and deploy (mandate_id), never client-editable. Null
  // whenever this policy has no resolved Authority Builder principal
  // behind it -- delegated_by above remains the fallback in that case.
  authority_id: string | null;
  mandate_id: string | null;
  // Phase 5, Release 2 (Enterprise System binding): client-editable --
  // a reviewer declares which registered EnterpriseSystem this policy's
  // allowed action reaches. Null means none configured.
  enterprise_system_id: string | null;
}

export interface Metadata {
  owner: string | null;
  created_by: string | null;
  tags: string[];
}

export interface RuntimePolicy {
  policy_key: string;
  version: number;
  status: PolicyStatus;
  name: string;
  description: string | null;
  scope: Scope;
  conditions: Condition[];
  effect: Effect;
  constraints: Constraints;
  metadata: Metadata;
  audit: Record<string, unknown> | null;
  bundle_id: string | null;
  bundle_hash: string | null;
  created_at: string;
}

export interface RuntimePolicyRequest {
  name: string;
  description?: string | null;
  scope: Scope;
  conditions: Condition[];
  effect: Effect;
  constraints: Constraints;
  metadata: Metadata;
}

export interface CompilerError {
  code: string;
  message: string;
  policy_id: string | null;
  path: string | null;
}

export interface CompileResult {
  ok: boolean;
  errors: CompilerError[];
  bundle_id: string | null;
  bundle_hash: string | null;
}

export interface DryRunResult {
  decision: "ALLOW" | "DENY" | "HUMAN_REVIEW";
  allow: boolean;
  deny: boolean;
  requires_review: boolean;
  evaluated_mandates: string[];
  review_reason: string | null;
  deny_reason: string | null;
  evidence_required: boolean;
}

export interface DeployResult {
  bundle_id: string;
  bundle_hash: string;
  deployed_at: string;
  // Authority-as-a-continuous-object, Stage I.5: additive. Null whenever
  // this policy has no resolved Authority behind it.
  authority_id: string | null;
  mandate_id: string | null;
}

export interface ConditionDiffEntry {
  kind: "added" | "removed" | "modified" | "unchanged";
  field: string;
  operator: string;
  old_value: unknown;
  new_value: unknown;
}

export interface AffectedAgent {
  id: string;
  name: string;
}

export interface AffectedPolicy {
  policy_key: string;
  name: string;
  version: number;
  status: string;
  same_action: boolean;
}

export interface PolicyDiff {
  conditions: ConditionDiffEntry[];
  scope_changed: boolean;
  effect_changed: boolean;
  constraints_changed: boolean;
  affected_agents: AffectedAgent[];
  affected_policies: AffectedPolicy[];
  risk_impact: "increased" | "decreased" | "mixed" | "unchanged";
  risk_reason: string;
}

export const KNOWN_OPERATORS = ["<=", ">=", "==", "!=", "<", ">", "in", "contains", "exists"] as const;

// --- Runtime Policy Lifecycle (Phase 5) -------------------------------------
// Mirrors server/app/schemas/runtime_policy_lifecycle.py exactly, the
// same hand-synced convention as everything above.

export interface SafetyViolation {
  check: string;
  message: string;
  details: Record<string, unknown>;
}

export interface SafetyCheckResult {
  ok: boolean;
  violations: SafetyViolation[];
}

export interface ActivationImpactPreview {
  policy_key: string;
  candidate_version: number;
  current_active_version: number | null;
  diff: PolicyDiff | null;
  safety: SafetyCheckResult;
}

export interface LifecycleEvent {
  id: string;
  policy_key: string;
  version: number;
  event_type: string;
  actor: string | null;
  reason: string | null;
  payload: Record<string, unknown>;
  event_hash: string;
  occurred_at: string;
}

export interface PolicyTimeline {
  policy_key: string;
  events: LifecycleEvent[];
}

export type ScheduleAction = "activate" | "retire";
export type ScheduleStatus = "pending" | "executed" | "failed" | "cancelled";

export interface ActivationSchedule {
  id: string;
  policy_key: string;
  version: number;
  action: ScheduleAction;
  effective_at: string;
  reason: string | null;
  status: ScheduleStatus;
  created_by: string | null;
  created_at: string;
  executed_at: string | null;
  execution_error: string | null;
}

export interface PolicyLifecycleSummary {
  policy_key: string;
  version: number;
  name: string;
  status: PolicyStatus;
  effective_status: EffectiveStatus;
  scope: Scope;
  created_at: string;
  activated_by: string | null;
  activated_at: string | null;
  activation_reason: string | null;
  effective_from: string | null;
  effective_until: string | null;
  deprecated_at: string | null;
  deprecation_reason: string | null;
  rollback_of_version: number | null;
  // Authority Freshness (Milestone 17, Part B): last_attested_at/
  // next_review_at are a re-attestation REMINDER, never an enforcement
  // mechanism -- review-due alone never disables anything. authority_
  // expires_at is a materially different, separate concept: an explicit
  // hard expiry, checked at decision time for high/critical-risk
  // policies specifically. The UI must never conflate the two.
  last_attested_at: string | null;
  next_review_at: string | null;
  review_cadence_days: number | null;
  authority_expires_at: string | null;
}

export interface ConflictAlert {
  policy_key: string;
  version: number;
  violations: SafetyViolation[];
}

export interface LifecycleDashboard {
  counts_by_state: Record<string, number>;
  pending_approvals: PolicyLifecycleSummary[];
  upcoming_activations: ActivationSchedule[];
  upcoming_expirations: PolicyLifecycleSummary[];
  upcoming_retirements: ActivationSchedule[];
  recently_activated: PolicyLifecycleSummary[];
  deprecated_policies: PolicyLifecycleSummary[];
  rollback_history: PolicyLifecycleSummary[];
  conflict_alerts: ConflictAlert[];
  // Authority Freshness (Milestone 17, Part B): deliberately separate
  // from upcoming_expirations above -- that field is an ACTIVE row's
  // own effective_until date (a scheduled deactivation), an unrelated,
  // pre-existing concept. This is a review-due REMINDER only.
  due_for_reattestation: PolicyLifecycleSummary[];
}

export interface PolicySearchParams {
  principal?: string;
  resource?: string;
  action?: string;
  state?: string;
  version?: number;
  reviewer?: string;
  created_after?: string;
  created_before?: string;
}
