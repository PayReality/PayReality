from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SubmitIntentRequest(BaseModel):
    """spec 19.5, extended with `nonce` (required by spec 9.3/21.2's replay
    protection, present in the field table but omitted from the section
    19.5 example) and `correlation_id` (spec 9.3, optional)."""

    agent_id: UUID
    action: str
    amount: float
    currency: str
    counterparty: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    requested_at: datetime
    nonce: str
    correlation_id: str | None = None


class DecisionSummary(BaseModel):
    outcome: str
    decision_id: UUID
    evaluated_mandates: list[str]
    # Authority-as-a-continuous-object, Stage H: real Mandate row ids,
    # additive alongside the legacy `evaluated_mandates` policy_key list
    # above -- empty whenever none of the matched policies have a
    # Stage-G-created Mandate yet.
    evaluated_mandate_ids: list[str] = []
    # Phase 5, Release 2 (Enterprise System binding): both additive, both
    # None whenever no matched policy configured, or still references, a
    # real EnterpriseSystem row -- never fabricated.
    enterprise_system_id: UUID | None = None
    enterprise_system_name: str | None = None
    reason: str | None = None


class SubmitIntentResponse(BaseModel):
    intent_id: UUID
    decision: DecisionSummary
    evidence_id: UUID
    status: str  # "PENDING" | "RESOLVED"


class ResolutionSummary(BaseModel):
    resolution: str
    resolved_by: str
    reason: str | None = None
    created_at: datetime


class ResolveDecisionRequest(BaseModel):
    """The Phase 1 addition (see plan) that resolves a HUMAN_REVIEW decision
    without mutating the immutable Decision row."""

    resolution: str  # "approved" | "denied"
    resolved_by: str
    reason: str | None = None


class ResolveDecisionResponse(BaseModel):
    decision_id: UUID
    resolution: ResolutionSummary
    evidence_id: UUID


class GetDecisionResponse(BaseModel):
    """New (not in spec 19's literal API): the polling endpoint the
    HUMAN_REVIEW-resolution addition needs (see plan)."""

    id: UUID
    status: str  # "PENDING" | "RESOLVED"
    outcome: str
    reason: str | None
    agent_id: UUID
    action: str
    amount: float
    currency: str
    evaluated_mandates: list[str]
    evaluated_mandate_ids: list[str] = []
    enterprise_system_id: UUID | None = None
    enterprise_system_name: str | None = None
    resolution: ResolutionSummary | None = None
