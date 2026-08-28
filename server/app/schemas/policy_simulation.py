from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SimulationInputRequest(BaseModel):
    """The hypothetical Intent under simulation -- same vocabulary as
    the existing DryRunRequest (schemas/runtime_policy.py): `principal`
    is who the action is performed AS. `context` additionally lets a
    simulation populate Runtime Authority Context fields (department,
    region, and so on) the simple existing dry-run tool has no
    equivalent for."""

    principal: str
    action: str
    resource: str | None = None
    amount: float | None = None
    currency: str | None = None
    agent_name: str = "Simulated Agent"
    context: dict[str, Any] = {}
    counterparty: str | None = None


class ConditionEvaluationResponse(BaseModel):
    field: str
    operator: str
    expected_value: Any
    actual_value: Any
    passed: bool


class RuleEvaluationResponse(BaseModel):
    policy_id: str
    policy_name: str
    principal: str
    action: str
    effect: str
    scope_matched: bool
    conditions: list[ConditionEvaluationResponse]
    matched: bool
    summary: str


class AuthorityTraceStepResponse(BaseModel):
    label: str
    detail: str | None


class EvidencePreviewResponse(BaseModel):
    """Never persisted, never signed with the real Evidence key -- see
    services/policy_simulation_service.EvidencePreview's own docstring
    for why. `preview` is always true, so a client can never mistake
    this for (or accidentally render it identically to) real Evidence."""

    decision: str
    policy_version: int
    policy_bundle_hash: str
    principal: str
    action: str
    resource: str | None
    evaluated_at: str
    receipt_hash: str
    preview: bool = True


class SimulationResponse(BaseModel):
    decision: str
    policy_key: str
    policy_name: str
    policy_version: int
    policy_bundle_hash: str
    generated_at: str
    review_reason: str | None
    deny_reason: str | None
    rules: list[RuleEvaluationResponse]
    authority_trace: list[AuthorityTraceStepResponse]
    evidence_preview: EvidencePreviewResponse
    facts_evaluated: dict[str, Any] = {}
    warnings: list[str] = []


class CreateScenarioRequest(BaseModel):
    name: str
    input: SimulationInputRequest
    expected_outcome: str  # "ALLOW" | "DENY" | "HUMAN_REVIEW"


class ScenarioResponse(BaseModel):
    id: str
    policy_key: str
    name: str
    input: SimulationInputRequest
    expected_outcome: str
    created_by: str | None
    created_at: datetime


class ScenarioRunResponse(BaseModel):
    scenario_id: str
    scenario_name: str
    expected_outcome: str
    actual_outcome: str
    passed: bool
    result: SimulationResponse


class BatchRowResponse(BaseModel):
    row_number: int
    principal: str
    action: str
    decision: str | None
    error: str | None
    limitation: str | None = None


class BatchSimulationResponse(BaseModel):
    total: int
    allowed: int
    denied: int
    escalated: int
    errors: int
    cannot_simulate: int = 0
    sample_rows: list[BatchRowResponse]
    sample_truncated: bool
    policy_version: int
    policy_bundle_hash: str
