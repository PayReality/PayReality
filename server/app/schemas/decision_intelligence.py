"""HTTP request/response models for the Decision Intelligence module
(/v1/decision-intelligence/*). One shared schemas file across every DI
sub-resource router, matching this codebase's own convention of one
schemas module per feature regardless of how many router files/classes
implement it (see schemas/organization_structure.py, shared by three
router objects in routers/organization_structure.py)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.domain.decision_intelligence.rule_schema import RuleSchema

# --- Workflows --------------------------------------------------------


class CreateWorkflowRequest(BaseModel):
    name: str
    description: str | None = None
    business_context: str | None = None
    owner_user_id: UUID | None = None


class UpdateWorkflowRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    business_context: str | None = None
    owner_user_id: UUID | None = None
    status: str | None = None


class WorkflowResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    business_context: str | None
    status: str
    owner_user_id: UUID | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowResponse]
    total: int
    limit: int
    offset: int


class WorkflowOverviewResponse(BaseModel):
    workflow_id: UUID
    case_count: int
    unresolved_case_count: int
    pattern_count: int
    questions_by_status: dict[str, int]
    answers_awaiting_approval: int
    rules_validated: int
    replays_completed: int


# --- Cases --------------------------------------------------------------


class CreateCaseRequest(BaseModel):
    workflow_id: UUID
    facts: dict[str, Any] = {}
    external_ref: str | None = None
    evidence_refs: list[Any] | None = None
    ai_recommendation: dict[str, Any] | None = None
    human_decision: dict[str, Any] | None = None
    escalation_reason: str | None = None
    outcome: str | None = None
    outcome_evidence: str | None = None


class UpdateCaseRequest(BaseModel):
    facts: dict[str, Any] | None = None
    evidence_refs: list[Any] | None = None
    ai_recommendation: dict[str, Any] | None = None
    human_decision: dict[str, Any] | None = None
    escalation_reason: str | None = None
    outcome: str | None = None
    outcome_evidence: str | None = None
    status: str | None = None


class CaseResponse(BaseModel):
    id: UUID
    organization_id: UUID
    workflow_id: UUID
    external_ref: str | None
    facts: dict[str, Any]
    evidence_refs: list[Any] | None
    ai_recommendation: dict[str, Any] | None
    human_decision: dict[str, Any] | None
    escalation_reason: str | None
    outcome: str | None
    outcome_evidence: str | None
    status: str
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CaseListResponse(BaseModel):
    cases: list[CaseResponse]
    total: int
    limit: int
    offset: int


# --- Patterns -------------------------------------------------------------


class CreatePatternRequest(BaseModel):
    workflow_id: UUID
    name: str
    description: str
    category: str
    proposed_explanation: str
    alternative_explanations: list[Any] | None = None
    confidence: str | None = None


class UpdatePatternRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    proposed_explanation: str | None = None
    alternative_explanations: list[Any] | None = None
    confidence: str | None = None
    review_status: str | None = None


class PatternResponse(BaseModel):
    id: UUID
    organization_id: UUID
    workflow_id: UUID
    name: str
    description: str
    category: str
    proposed_explanation: str
    alternative_explanations: list[Any] | None
    confidence: str | None
    review_status: str
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PatternListResponse(BaseModel):
    patterns: list[PatternResponse]
    total: int
    limit: int
    offset: int


class LinkCaseRequest(BaseModel):
    """Shared by both patterns and questions -- "attach this case as
    supporting evidence" means the same thing on either resource."""

    case_id: UUID


# --- Questions --------------------------------------------------------


class CreateQuestionRequest(BaseModel):
    workflow_id: UUID
    title: str
    description: str | None = None
    owner_user_id: UUID | None = None


class UpdateQuestionRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    owner_user_id: UUID | None = None
    reach_score: float | None = None
    impact_score: float | None = None
    risk_score: float | None = None
    answerability_score: float | None = None
    decision_sensitivity_score: float | None = None


class QuestionResponse(BaseModel):
    id: UUID
    organization_id: UUID
    workflow_id: UUID
    title: str
    description: str | None
    status: str
    reach_score: float | None
    impact_score: float | None
    risk_score: float | None
    answerability_score: float | None
    decision_sensitivity_score: float | None
    priority_score: float | None
    scoring_version: str | None
    owner_user_id: UUID | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class QuestionListResponse(BaseModel):
    questions: list[QuestionResponse]
    total: int
    limit: int
    offset: int


class QuestionDetailResponse(BaseModel):
    """get (brief): "including linked patterns/cases and the evidence
    behind its score" -- the evidence behind priority_score is simply the
    five dimension scores already on QuestionResponse, made visible
    alongside what motivated the question (its linked Patterns/Cases)."""

    question: QuestionResponse
    patterns: list[PatternResponse]
    case_ids: list[UUID]


class LinkPatternRequest(BaseModel):
    pattern_id: UUID


# --- Answers --------------------------------------------------------------


class CreateAnswerRequest(BaseModel):
    content: str
    evidence_refs: list[Any] | None = None
    scope: str | None = None
    conditions_exceptions: str | None = None
    effective_date: datetime | None = None
    review_date: datetime | None = None


class SupersedeAnswerRequest(CreateAnswerRequest):
    pass


class RejectAnswerRequest(BaseModel):
    reason: str | None = None


class AnswerResponse(BaseModel):
    id: UUID
    question_id: UUID
    content: str
    evidence_refs: list[Any] | None
    scope: str | None
    conditions_exceptions: str | None
    effective_date: datetime | None
    review_date: datetime | None
    version: int
    previous_version_id: UUID | None
    author_user_id: UUID
    approver_user_id: UUID | None
    status: str
    submitted_at: datetime | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Decision Rules ---------------------------------------------------


class CreateRuleRequest(BaseModel):
    workflow_id: UUID
    name: str
    source_answer_id: UUID
    schema_json: RuleSchema


class CreateRuleVersionRequest(BaseModel):
    schema_json: RuleSchema
    scope: str | None = None


class RuleResponse(BaseModel):
    id: UUID
    organization_id: UUID
    workflow_id: UUID
    name: str
    source_answer_id: UUID
    current_version_id: UUID | None
    status: str
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RuleListResponse(BaseModel):
    rules: list[RuleResponse]
    total: int
    limit: int
    offset: int


class RuleVersionResponse(BaseModel):
    id: UUID
    rule_id: UUID
    version: int
    schema_json: dict[str, Any]
    scope: str | None
    created_by_user_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class TestRuleRequest(BaseModel):
    case_facts: dict[str, Any] | None = None
    case_id: UUID | None = None


# --- Replays ----------------------------------------------------------


class CreateReplayRequest(BaseModel):
    workflow_id: UUID
    rule_version_id: UUID
    case_ids: list[UUID] | None = None
    filter_status: str | None = None


class ReplayRunResponse(BaseModel):
    id: UUID
    organization_id: UUID
    workflow_id: UUID
    rule_version_id: UUID
    case_set_definition: dict[str, Any]
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    summary: dict[str, Any] | None
    created_by_user_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class ReplayRunListResponse(BaseModel):
    replay_runs: list[ReplayRunResponse]
    total: int
    limit: int
    offset: int


class ReplayCaseResultResponse(BaseModel):
    id: UUID
    replay_run_id: UUID
    case_id: UUID
    baseline_decision: dict[str, Any] | None
    proposed_decision: dict[str, Any] | None
    matched_conditions: list[Any] | None
    unmatched_conditions: list[Any] | None
    outcome_category: str
    notes: str | None

    model_config = {"from_attributes": True}


class ReplayCaseResultListResponse(BaseModel):
    results: list[ReplayCaseResultResponse]
    total: int
    limit: int
    offset: int
