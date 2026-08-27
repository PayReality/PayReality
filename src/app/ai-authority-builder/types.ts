export interface Corpus {
  corpus_id: string;
  name: string;
  status: "uploaded" | "extracted" | "failed";
  error: string | null;
  document_count: number;
  created_at: string;
}

// Explainability Model (Authority Intelligence Program, Phase 3,
// EXPLAINABILITY_MODEL.md): the same four fields on every entity/
// relationship/threshold below -- first-class, never buried inside a
// free-form LLM response.
export interface ExplainabilityFields {
  clause_reference: string | null;
  extraction_reasoning: string | null;
  detected_assumptions: string[];
  ambiguity_flags: string[];
}

export interface Principal extends ExplainabilityFields {
  id: string;
  name: string;
  role: string | null;
  reports_to: string | null;
  confidence: number;
  source_excerpt: string | null;
  source_location: string | null;
  // Authority-as-a-continuous-object, Stage E: null until a reviewer
  // resolves this discovery to a real Principal (match or create).
  resolved_principal_id: string | null;
}

// A real, existing Principal offered as a possible match for a
// discovery -- suggestion only, never applied without a reviewer
// explicitly confirming via ResolvePrincipalRequest.
export interface PrincipalCandidate {
  id: string;
  name: string;
  role: string | null;
  organization_id: string | null;
}

export interface ResolvePrincipalRequest {
  action: "match" | "create";
  principal_id?: string | null;
  name?: string | null;
  role?: string | null;
}

export interface Resource extends ExplainabilityFields {
  id: string;
  name: string;
  description: string | null;
  confidence: number;
  source_excerpt: string | null;
  source_location: string | null;
}

export interface Operation extends ExplainabilityFields {
  id: string;
  name: string;
  description: string | null;
  confidence: number;
  source_excerpt: string | null;
  source_location: string | null;
}

export interface Relationship extends ExplainabilityFields {
  id: string;
  kind: "delegation" | "escalation" | "inheritance";
  from_principal: string;
  to_principal: string;
  description: string | null;
  confidence: number;
  source_excerpt: string | null;
  source_location: string | null;
  // Authority-as-a-continuous-object, Stage F: populated once resolution
  // matches an already-resolved Principal on each side. status stays
  // "proposed" until a reviewer explicitly activates it -- resolving
  // names into real ids and deciding a delegation should actually govern
  // live enforcement are two different, deliberately separate steps.
  from_principal_id: string | null;
  to_principal_id: string | null;
  status: "proposed" | "active";
}

// Conflict Workspace (Phase 3): conflict_type is the model's own (or,
// for circular_delegation, deterministic graph analysis's own)
// classification; reviewer_recommendation is always computed
// server-side from conflict_type/confidence, never asked of the model.
export type ConflictType = "authority" | "threshold" | "role" | "policy" | "delegation" | "circular_delegation";

export interface Conflict {
  id: string;
  description: string;
  reasoning: string | null;
  confidence: number;
  conflict_type: ConflictType | null;
  reviewer_recommendation: string | null;
}

export interface Gap {
  id: string;
  description: string;
  confidence: number;
  source_excerpt: string | null;
  source_location: string | null;
}

export interface Question {
  id: string;
  question: string;
  context: string | null;
  answered: boolean;
  answer: string | null;
}

export interface GraphSummary {
  policy_count: number;
  principal_count: number;
  resource_count: number;
  operation_count: number;
  relationship_count: number;
  conflict_count: number;
  gap_count: number;
  question_count: number;
}

// Coverage Analysis (Phase 3): every figure here is a deterministic
// parsing statistic -- never an LLM's self-report of its own
// completeness. See EXPLAINABILITY_MODEL.md.
export interface Coverage {
  documents_processed: number;
  clauses_analysed: number;
  clauses_ignored: number;
  tables_extracted: number;
  images_skipped: number;
  sections_unsupported: number;
  coverage_percent: number;
}

// Missing Information Detection (Phase 3): a deterministic, code-computed
// backstop for the model's own self-reported Gaps/Questions.
export interface MissingInformationItem {
  category:
    | "unknown_reporting_line"
    | "unknown_spending_limit"
    | "missing_delegation"
    | "undefined_approver"
    | "missing_policy";
  subject: string | null;
  description: string;
}

// Graph Diff (Phase 3): this corpus's candidate Authority Graph vs. the
// Authority Graph already in force for the same organisation.
export interface GraphDiffAuthority {
  name: string;
  role: string | null;
}

export interface GraphDiffThreshold {
  principal: string;
  action: string;
  limit: number | null;
  previous_limit: number | null;
  new_limit: number | null;
}

export interface GraphDiffReportingLine {
  name: string;
  previous_reports_to: string | null;
  new_reports_to: string | null;
}

export interface GraphDiffResponsibility {
  name: string;
  previous_role: string | null;
  new_role: string | null;
}

export interface GraphDiff {
  new_authorities: GraphDiffAuthority[];
  removed_authorities: GraphDiffAuthority[];
  new_thresholds: GraphDiffThreshold[];
  changed_thresholds: GraphDiffThreshold[];
  changed_reporting_lines: GraphDiffReportingLine[];
  changed_responsibilities: GraphDiffResponsibility[];
}

// Approval Audit (Phase 3): one immutable row per "approve this
// corpus's Authority Graph" reviewer action.
//
// Authority Graph Lineage & Versioning (issue #5): predecessor_approval_id
// is a real, stored, immutable field. superseded_by_approval_id is the
// opposite direction, always derived server-side, never itself stored --
// both null is normal (first version / still-current version).
export interface GraphApproval {
  id: string;
  corpus_id: string;
  reviewer: string;
  version: number;
  approval_reason: string | null;
  graph_hash: string;
  approved_at: string;
  predecessor_approval_id: string | null;
  superseded_by_approval_id: string | null;
}

// Authority Graph Lineage & Versioning (issue #5): a deterministic,
// same-corpus comparison of two approved graph versions -- GET
// /corpora/{corpus_id}/approvals/{approval_id}/diff.
export interface GraphApprovalRef {
  id: string;
  version: number;
  approved_at: string;
}

export interface FieldChange {
  field: string;
  before: unknown;
  after: unknown;
}

export interface ChangedItem {
  id: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  changed_fields: FieldChange[];
}

export interface ItemDiff {
  added: Record<string, unknown>[];
  removed: Record<string, unknown>[];
  changed: ChangedItem[];
}

export interface CoverageDiff {
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  changed_fields: FieldChange[];
}

export interface GraphApprovalDiffSummary {
  principals_added: number;
  principals_removed: number;
  principals_changed: number;
  relationships_added: number;
  relationships_removed: number;
  relationships_changed: number;
  conflicts_added: number;
  conflicts_removed: number;
  conflicts_changed: number;
  gaps_added: number;
  gaps_removed: number;
  gaps_changed: number;
  coverage_changed: boolean;
}

export interface GraphApprovalDiff {
  from_approval: GraphApprovalRef;
  to_approval: GraphApprovalRef;
  summary: GraphApprovalDiffSummary;
  principals: ItemDiff;
  relationships: ItemDiff;
  conflicts: ItemDiff;
  gaps: ItemDiff;
  coverage: CoverageDiff;
}

// Authority Graph -> RuntimePolicy Compilation Gate (issue #6), reverse
// traceability: one RuntimePolicy version whose lineage originates at a
// specific approved graph version.
export interface CompiledPolicySummary {
  policy_key: string;
  version: number;
  name: string;
  status: string;
  created_at: string;
}
