from datetime import datetime

from pydantic import BaseModel


class ExplainabilityFields(BaseModel):
    """Authority Intelligence Program, Phase 3 (EXPLAINABILITY_MODEL.md):
    the same four fields on every entity/relationship/threshold response
    below, via inheritance rather than repetition -- a reviewer should
    never find one category of finding missing its "why" while another
    has it."""

    clause_reference: str | None = None
    extraction_reasoning: str | None = None
    detected_assumptions: list[str] = []
    ambiguity_flags: list[str] = []


class ProviderStatusResponse(BaseModel):
    """Whether extraction is currently backed by a real LLM (Claude) or
    the deterministic fake provider, so the frontend can be honest about
    which one a given deployment is running."""

    ai_enabled: bool


class CorpusResponse(BaseModel):
    corpus_id: str
    name: str
    status: str
    error: str | None
    document_count: int
    created_at: datetime


class PrincipalResponse(ExplainabilityFields):
    id: str
    name: str
    role: str | None
    reports_to: str | None
    confidence: float
    source_excerpt: str | None
    source_location: str | None
    # Authority-as-a-continuous-object, Stage E: None until a reviewer
    # resolves this discovery to a real Principal (match or create).
    resolved_principal_id: str | None = None


class PrincipalCandidateResponse(BaseModel):
    """A real, existing Principal that might be the same person/role this
    discovery describes, offered as a suggestion only -- never applied
    without a reviewer explicitly confirming via ResolvePrincipalRequest."""

    id: str
    name: str
    role: str | None
    organization_id: str | None


class ResolvePrincipalRequest(BaseModel):
    """Stage E's reviewer workflow. `action="match"` requires
    `principal_id` (one of the candidates offered, or any other real
    Principal id the reviewer already knows); `action="create"` makes a
    new Principal from this discovery's own name/role, optionally
    overridden."""

    action: str  # "match" | "create"
    principal_id: str | None = None
    name: str | None = None
    role: str | None = None


class ResourceResponse(ExplainabilityFields):
    id: str
    name: str
    description: str | None
    confidence: float
    source_excerpt: str | None
    source_location: str | None


class OperationResponse(ExplainabilityFields):
    id: str
    name: str
    description: str | None
    confidence: float
    source_excerpt: str | None
    source_location: str | None


class RelationshipResponse(ExplainabilityFields):
    id: str
    kind: str
    from_principal: str
    to_principal: str
    description: str | None
    confidence: float
    source_excerpt: str | None
    source_location: str | None
    # Authority-as-a-continuous-object, Stage F: populated once resolution
    # finds a matching, already-resolved Principal on each side. status
    # stays "proposed" (the schema's own existing default) until a
    # reviewer explicitly activates it -- resolving the names into real
    # ids and deciding this delegation should actually govern live
    # enforcement are two different, deliberately separate steps.
    from_principal_id: str | None = None
    to_principal_id: str | None = None
    status: str = "proposed"


class ConflictResponse(BaseModel):
    id: str
    description: str
    reasoning: str | None
    confidence: float
    # Conflict Workspace (Phase 3): conflict_type is the model's own (or,
    # for circular_delegation, deterministic graph analysis's own)
    # classification; reviewer_recommendation is always computed in
    # Python from conflict_type/confidence, never asked of the model.
    conflict_type: str | None = None
    reviewer_recommendation: str | None = None


class CoverageResponse(BaseModel):
    """Coverage Analysis (Phase 3): every figure here is a deterministic
    parsing statistic aggregated from AuthorityCorpusDocument's own
    columns -- never an LLM's self-report."""

    documents_processed: int
    clauses_analysed: int
    clauses_ignored: int
    tables_extracted: int
    images_skipped: int
    sections_unsupported: int
    coverage_percent: float


class MissingInformationItem(BaseModel):
    category: str
    subject: str | None
    description: str


class GraphDiffAuthority(BaseModel):
    name: str
    role: str | None = None


class GraphDiffThreshold(BaseModel):
    principal: str
    action: str
    limit: float | None = None
    previous_limit: float | None = None
    new_limit: float | None = None


class GraphDiffReportingLine(BaseModel):
    name: str
    previous_reports_to: str | None
    new_reports_to: str | None


class GraphDiffResponsibility(BaseModel):
    name: str
    previous_role: str | None
    new_role: str | None


class GraphDiffResponse(BaseModel):
    """Task 7: this corpus's candidate graph vs. the Authority Graph
    already in force for the same organisation."""

    new_authorities: list[GraphDiffAuthority]
    removed_authorities: list[GraphDiffAuthority]
    new_thresholds: list[GraphDiffThreshold]
    changed_thresholds: list[GraphDiffThreshold]
    changed_reporting_lines: list[GraphDiffReportingLine]
    changed_responsibilities: list[GraphDiffResponsibility]


class ApproveGraphRequest(BaseModel):
    approval_reason: str | None = None


class GraphApprovalResponse(BaseModel):
    """Task 8: one immutable row per approval action. `reviewer` is
    whatever identity the request was authenticated as -- see the
    router's own get_current_organization/require_permission usage,
    unchanged by this endpoint."""

    id: str
    corpus_id: str
    reviewer: str
    version: int
    approval_reason: str | None
    graph_hash: str
    approved_at: datetime


class GapResponse(BaseModel):
    id: str
    description: str
    confidence: float
    source_excerpt: str | None
    source_location: str | None


class QuestionResponse(BaseModel):
    id: str
    question: str
    context: str | None
    answered: bool
    answer: str | None


class AnswerQuestionRequest(BaseModel):
    answer: str


class GraphSummaryResponse(BaseModel):
    """The headline counts (AI_AUTHORITY_BUILDER_ARCHITECTURE.md's own
    example: "237 Runtime Policies, 18 Principals..."), computed from the
    same per-category list endpoints, not a separately maintained
    number."""

    policy_count: int
    principal_count: int
    resource_count: int
    operation_count: int
    relationship_count: int
    conflict_count: int
    gap_count: int
    question_count: int
