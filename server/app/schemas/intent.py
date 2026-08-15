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
    HUMAN_REVIEW-resolution addition needs (see plan).

    Runtime Decision Center V2, Phase 2A: `created_at` is a real,
    previously-unexposed column already on the Decision row --
    just added to the response. `policy_version`/`policy_bundle_hash`/
    `authority_version` are not persisted on Decision at all (only ever
    computed transiently in decision_engine.Decision, see that module's
    own docstring); the router reads them off this decision's own
    earliest Evidence record, the same real values Evidence has already
    carried since Phase 1, rather than recomputing or inventing
    anything. All three are None whenever no Evidence record exists yet
    or no active policy was ever evaluated (a suspended/retired agent,
    an unrecognized action) -- exactly Evidence's own existing
    optionality, not a new failure mode."""

    id: UUID
    status: str  # "PENDING" | "RESOLVED"
    outcome: str
    reason: str | None
    agent_id: UUID
    action: str
    amount: float
    currency: str
    created_at: datetime
    evaluated_mandates: list[str]
    evaluated_mandate_ids: list[str] = []
    enterprise_system_id: UUID | None = None
    enterprise_system_name: str | None = None
    policy_version: int | None = None
    policy_bundle_hash: str | None = None
    authority_version: str | None = None
    resolution: ResolutionSummary | None = None


class PolicyManifestEntry(BaseModel):
    """One RuntimePolicy as it was actually compiled into this bundle,
    read from Policy.bundle_manifest (Historical Policy Binding). `id`
    is the policy_key (stable across that policy's own version
    history); `version` pins exactly which of its immutable
    RuntimePolicyRecord rows was included."""

    id: str
    name: str
    version: int
    effect: str
    scope: dict[str, Any]


class DecisionPolicyBindingResponse(BaseModel):
    """Answers 'exactly which policy state evaluated this decision?'
    without touching whatever policy happens to be active today.
    Policy.id/bundle_hash/version/compiled_at/activated_at/retired_at
    are the same immutable bundle row Decision.policy_id has always
    pointed to; `policies` is that bundle's manifest, if it was deployed
    after Policy.bundle_manifest existed. `policies` is empty (not an
    error) for a bundle deployed before this column existed -- see the
    migration's own docstring for why no backfill is possible."""

    decision_id: UUID
    policy_id: UUID
    bundle_hash: str
    bundle_version: int
    compiled_at: datetime | None
    activated_at: datetime | None
    retired_at: datetime | None
    policies: list[PolicyManifestEntry]
