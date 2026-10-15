// Hand-written interfaces matching the real backend response shapes in
// server/app/schemas/decision_intelligence.py and the rule/evaluator
// domain models (server/app/domain/decision_intelligence/rule_schema.py,
// rule_evaluator.py). Status vocabularies below are copied verbatim from
// the CheckConstraints on each table in server/app/db/models.py -- every
// one of these is a hard product/database contract, not a UI
// convenience, so the exact string values must never drift from the
// backend's own.

// --- Workflows --------------------------------------------------------

export type WorkflowStatus = "active" | "archived";

export interface Workflow {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  business_context: string | null;
  status: WorkflowStatus;
  owner_user_id: string | null;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
}

export interface WorkflowListPage {
  workflows: Workflow[];
  total: number;
  limit: number;
  offset: number;
}

export interface WorkflowOverview {
  workflow_id: string;
  case_count: number;
  unresolved_case_count: number;
  pattern_count: number;
  questions_by_status: Record<string, number>;
  answers_awaiting_approval: number;
  rules_validated: number;
  replays_completed: number;
}

// --- Cases --------------------------------------------------------------

export type CaseStatus = "open" | "resolved" | "escalated";

export interface Case {
  id: string;
  organization_id: string;
  workflow_id: string;
  external_ref: string | null;
  facts: Record<string, unknown>;
  evidence_refs: unknown[] | null;
  ai_recommendation: Record<string, unknown> | null;
  human_decision: Record<string, unknown> | null;
  escalation_reason: string | null;
  outcome: string | null;
  outcome_evidence: string | null;
  status: CaseStatus;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
}

export interface CaseListPage {
  cases: Case[];
  total: number;
  limit: number;
  offset: number;
}

// --- Patterns -------------------------------------------------------------

export type PatternCategory =
  | "missing_facts"
  | "unclear_policy"
  | "conflicting_rules"
  | "authority_gap"
  | "context_interpretation"
  | "human_judgement"
  | "other";

export type PatternConfidence = "low" | "medium" | "high";
export type PatternReviewStatus = "proposed" | "reviewed" | "confirmed" | "rejected";

export interface Pattern {
  id: string;
  organization_id: string;
  workflow_id: string;
  name: string;
  description: string;
  category: PatternCategory;
  proposed_explanation: string;
  alternative_explanations: unknown[] | null;
  confidence: PatternConfidence | null;
  review_status: PatternReviewStatus;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
}

export interface PatternListPage {
  patterns: Pattern[];
  total: number;
  limit: number;
  offset: number;
}

// --- Questions --------------------------------------------------------

// The question's full lifecycle (scoring.py / di_question_service.py's
// own docstring). Only the first and last two steps are human-invoked
// directly; everything in between advances as a side effect of the
// answer/rule/replay lifecycle.
export type QuestionStatus =
  | "proposed"
  | "in_analysis"
  | "awaiting_answer"
  | "answer_submitted"
  | "approved"
  | "logic_drafted"
  | "logic_validated"
  | "replay_completed"
  | "ready_for_review"
  | "approved_for_operational_use";

export const QUESTION_STATUS_ORDER: QuestionStatus[] = [
  "proposed",
  "in_analysis",
  "awaiting_answer",
  "answer_submitted",
  "approved",
  "logic_drafted",
  "logic_validated",
  "replay_completed",
  "ready_for_review",
  "approved_for_operational_use",
];

export const QUESTION_STATUS_LABELS: Record<QuestionStatus, string> = {
  proposed: "Proposed",
  in_analysis: "In analysis",
  awaiting_answer: "Awaiting answer",
  answer_submitted: "Answer submitted",
  approved: "Answer approved",
  logic_drafted: "Logic drafted",
  logic_validated: "Logic validated",
  replay_completed: "Replay completed",
  ready_for_review: "Ready for review",
  approved_for_operational_use: "Approved for operational use",
};

export interface Question {
  id: string;
  organization_id: string;
  workflow_id: string;
  title: string;
  description: string | null;
  status: QuestionStatus;
  // Hard contract (scoring.py): each dimension score is null until a
  // human has actually judged it -- never silently defaulted to 0.
  reach_score: number | null;
  impact_score: number | null;
  risk_score: number | null;
  answerability_score: number | null;
  decision_sensitivity_score: number | null;
  // Null whenever ANY dimension above is null -- never a fabricated number.
  priority_score: number | null;
  scoring_version: string | null;
  owner_user_id: string | null;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
}

export interface QuestionListPage {
  questions: Question[];
  total: number;
  limit: number;
  offset: number;
}

export interface QuestionDetail {
  question: Question;
  patterns: Pattern[];
  case_ids: string[];
}

// --- Answers --------------------------------------------------------------

export type AnswerStatus = "draft" | "submitted" | "under_review" | "approved" | "rejected" | "superseded";

export interface Answer {
  id: string;
  question_id: string;
  content: string;
  evidence_refs: unknown[] | null;
  scope: string | null;
  conditions_exceptions: string | null;
  effective_date: string | null;
  review_date: string | null;
  version: number;
  previous_version_id: string | null;
  author_user_id: string;
  approver_user_id: string | null;
  status: AnswerStatus;
  submitted_at: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
}

// --- Decision Rules (rule_schema.py's own typed condition language) -------

export type ConditionOperator =
  | "eq"
  | "neq"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "in"
  | "not_in"
  | "contains"
  | "is_missing";

export interface Condition {
  field: string;
  operator: ConditionOperator;
  value?: unknown;
}

export interface CompositeCondition {
  combinator: "AND" | "OR";
  conditions: ConditionNode[];
}

export type ConditionNode = Condition | CompositeCondition;

export function isCompositeCondition(node: ConditionNode): node is CompositeCondition {
  return (node as CompositeCondition).combinator !== undefined;
}

export interface RuleAction {
  decision: string;
  human_review_required: boolean;
}

export type MissingDataBehavior = "route_to_human" | "fail" | "treat_as_false";

export interface RuleSchema {
  root_condition: ConditionNode;
  action: RuleAction;
  exceptions: ConditionNode[];
  missing_data_behavior: MissingDataBehavior;
}

export type RuleStatus = "draft" | "validated";

export interface DecisionRule {
  id: string;
  organization_id: string;
  workflow_id: string;
  name: string;
  source_answer_id: string;
  current_version_id: string | null;
  status: RuleStatus;
  created_by_user_id: string;
  created_at: string;
  updated_at: string;
}

export interface RuleListPage {
  rules: DecisionRule[];
  total: number;
  limit: number;
  offset: number;
}

export interface RuleVersion {
  id: string;
  rule_id: string;
  version: number;
  schema_json: RuleSchema;
  scope: string | null;
  created_by_user_id: string;
  created_at: string;
}

// rule_evaluator.py's EvaluationResult, returned verbatim by both
// POST /rules/{id}/test and each DIReplayCaseResult's own evaluation.
export interface EvaluationResult {
  matched: boolean;
  decision: string | null;
  human_review_required: boolean;
  matched_conditions: string[];
  unmatched_conditions: string[];
  missing_fields: string[];
}

// --- Replays ----------------------------------------------------------

export type ReplayRunStatus = "pending" | "running" | "completed" | "failed";

export interface ReplayRun {
  id: string;
  organization_id: string;
  workflow_id: string;
  rule_version_id: string;
  case_set_definition: Record<string, unknown>;
  status: ReplayRunStatus;
  started_at: string | null;
  completed_at: string | null;
  // Real shape returned by di_replay_service.py:
  // `{"total_cases": N, "counts": {category: count}}`.
  summary: { total_cases: number; counts: Record<string, number> } | null;
  created_by_user_id: string;
  created_at: string;
}

export interface ReplayRunListPage {
  replay_runs: ReplayRun[];
  total: number;
  limit: number;
  offset: number;
}

// Critical naming/semantics discipline (replay_executor.py's own brief):
// an outcome_category measures AGREEMENT with a historical human
// decision, never CORRECTNESS of either the historical decision or the
// candidate rule. Nothing in this app's copy may read as a correctness
// claim.
export type OutcomeCategory =
  | "agrees_with_baseline"
  | "disagrees_with_baseline"
  | "resolved_automatically"
  | "requires_human_review"
  | "missing_data"
  | "error";

export const OUTCOME_CATEGORIES: OutcomeCategory[] = [
  "agrees_with_baseline",
  "disagrees_with_baseline",
  "resolved_automatically",
  "requires_human_review",
  "missing_data",
  "error",
];

export const OUTCOME_CATEGORY_LABELS: Record<OutcomeCategory, string> = {
  agrees_with_baseline: "Agrees with baseline",
  disagrees_with_baseline: "Disagrees with baseline",
  resolved_automatically: "Resolved automatically",
  requires_human_review: "Requires human review",
  missing_data: "Missing data",
  error: "Error",
};

export interface ReplayCaseResult {
  id: string;
  replay_run_id: string;
  case_id: string;
  baseline_decision: Record<string, unknown> | null;
  proposed_decision: Record<string, unknown> | null;
  matched_conditions: unknown[] | null;
  unmatched_conditions: unknown[] | null;
  outcome_category: OutcomeCategory;
  notes: string | null;
}

export interface ReplayCaseResultListPage {
  results: ReplayCaseResult[];
  total: number;
  limit: number;
  offset: number;
}

// --- CSV case import (DIImportJob) -------------------------------------

// Carries the full pending/validating/completed/failed vocabulary a
// future async worker would need (di_import_service.py's own docstring),
// even though today's synchronous import only ever actually returns
// "completed".
export type ImportJobStatus = "pending" | "validating" | "completed" | "failed";

// `column_mapping`'s real backend shape: {csv_header: target}, target one
// of these five DICase fields or the literal "exclude" (csv_import.py).
// Any header left unmapped defaults to "facts" server-side; this UI always
// sends an explicit target per header instead of relying on that default.
export type ColumnMappingTarget = "external_ref" | "facts" | "human_decision" | "escalation_reason" | "outcome" | "exclude";

export interface ImportRowError {
  row_number: number;
  errors: string[];
}

export interface ImportJob {
  id: string;
  organization_id: string;
  workflow_id: string;
  status: ImportJobStatus;
  filename: string;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  row_errors: ImportRowError[] | null;
  created_by_user_id: string;
  created_at: string;
  completed_at: string | null;
}

export interface ImportJobListPage {
  import_jobs: ImportJob[];
  total: number;
  limit: number;
  offset: number;
}

// --- Cross-workflow organization overview (reports/exports) ------------

export interface WorkflowBreakdown {
  workflow_id: string;
  workflow_name: string;
  case_count: number;
  pattern_count: number;
  question_count: number;
  answer_count: number;
  rule_count: number;
  replay_count: number;
}

export interface OrganizationOverview {
  organization_id: string;
  workflow_count: number;
  total_cases: number;
  total_patterns: number;
  total_questions: number;
  total_answers: number;
  total_rules: number;
  total_replays: number;
  by_workflow: WorkflowBreakdown[];
}

// --- Settings: configurable scoring weights -----------------------------

// Mirrors scoring.py's DEFAULT_WEIGHTS exactly -- the client-side sum
// validation below is a convenience that must never drift from the
// backend's own (scoring.validate_weights, 0.001 tolerance).
export const DEFAULT_SCORING_WEIGHTS: ScoringWeights = {
  reach: 0.3,
  impact: 0.3,
  risk: 0.2,
  answerability: 0.1,
  decision_sensitivity: 0.1,
};

export const SCORING_WEIGHT_SUM_TOLERANCE = 0.001;

export interface ScoringWeights {
  reach: number;
  impact: number;
  risk: number;
  answerability: number;
  decision_sensitivity: number;
}

export interface ScoringConfig {
  organization_id: string;
  weights: ScoringWeights;
  scoring_version: string;
  is_default: boolean;
  updated_at: string | null;
}

// --- AI-assisted discovery (DIDiscoveryRun / DIDiscoverySuggestion) -----

export type DiscoveryRunStatus = "pending" | "running" | "completed" | "failed";

export interface DiscoveryRun {
  id: string;
  organization_id: string;
  workflow_id: string;
  provider_used: string;
  status: DiscoveryRunStatus;
  cases_analyzed_count: number;
  error_message: string | null;
  created_by_user_id: string;
  created_at: string;
  completed_at: string | null;
}

export interface DiscoveryRunListPage {
  discovery_runs: DiscoveryRun[];
  total: number;
  limit: number;
  offset: number;
}

export type DiscoverySuggestionKind = "pattern" | "question";
// "suggested" is the only status a reviewer can still act on (accept/
// dismiss); "accepted"/"dismissed" are both final (di_discovery_service.py).
export type DiscoverySuggestionStatus = "suggested" | "accepted" | "dismissed";

export interface DiscoverySuggestion {
  id: string;
  discovery_run_id: string;
  kind: DiscoverySuggestionKind;
  title: string;
  description: string;
  supporting_case_ids: string[];
  rationale: string;
  confidence: PatternConfidence | null;
  category: PatternCategory | null;
  linked_pattern_id: string | null;
  status: DiscoverySuggestionStatus;
  reviewed_by_user_id: string | null;
  reviewed_at: string | null;
  created_at: string;
}

export interface DiscoveryRunDetail {
  discovery_run: DiscoveryRun;
  suggestions: DiscoverySuggestion[];
}

export interface AcceptSuggestionResult {
  entity_type: "pattern" | "question";
  pattern: Pattern | null;
  question: Question | null;
}
