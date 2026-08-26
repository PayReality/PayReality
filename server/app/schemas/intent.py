from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.policy_simulation import RuleEvaluationResponse


class SubmitIntentRequest(BaseModel):
    """spec 19.5, extended with `nonce` (required by spec 9.3/21.2's replay
    protection, present in the field table but omitted from the section
    19.5 example) and `correlation_id` (spec 9.3, optional)."""

    agent_id: UUID
    action: str
    # Domain Generalization Milestone: universal fields are agent_id,
    # action, resource, and context. amount/currency are optional,
    # domain-specific attributes -- required only for actions that
    # actually have a monetary dimension (spec 19.5's original
    # payments-only shape required both; a non-financial action like
    # `disable_user` supplies neither).
    resource: str | None = None
    amount: float | None = None
    currency: str | None = None
    counterparty: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    requested_at: datetime
    nonce: str
    correlation_id: str | None = None
    # Product Experience Remediation Milestone 1 (Decision Provenance):
    # self-declared, see domain/decision/source.py's own docstring for
    # the honest limits of that. Omit entirely for a real integration;
    # the manual Test Decision UI is the one caller that sends
    # "manual_test" explicitly.
    source: str | None = None


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


class PolicyFreshnessSummary(BaseModel):
    """The GOVERNING policy's freshness state as of now, read live off
    RuntimePolicyRecord -- not a historical reconstruction of what it
    was at decision time (Historical Policy Binding already exists as
    a separate, distinct concern for that). `status` is exactly the
    same current/review_due/expired vocabulary Governance and Assurance
    use elsewhere, computed the same way, so it reads consistently
    wherever it appears."""

    policy_key: str
    last_attested_at: datetime | None
    next_review_at: datetime | None
    authority_expires_at: datetime | None
    status: str  # "current" | "review_due" | "expired" | "unknown"


class CapabilitySummary(BaseModel):
    """Whether a Capability Authorization was ever issued for this
    decision, and its real state -- issuance and consumption are two
    separate, independently-true facts, neither of which is proof the
    downstream business action actually completed (domain/capability/
    token.py's own module docstring states this explicitly; this
    schema only ever reports what's actually recorded, never implies
    more)."""

    issued: bool
    audience: str | None = None
    resource: str | None = None
    action: str | None = None
    expires_at: datetime | None = None
    consumed_at: datetime | None = None


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
    # Domain Generalization Milestone: optional, matching
    # SubmitIntentRequest -- a non-financial decision (e.g.
    # `disable_user`) genuinely has neither.
    resource: str | None = None
    amount: float | None = None
    currency: str | None = None
    created_at: datetime
    evaluated_mandates: list[str]
    evaluated_mandate_ids: list[str] = []
    enterprise_system_id: UUID | None = None
    enterprise_system_name: str | None = None
    policy_version: int | None = None
    policy_bundle_hash: str | None = None
    authority_version: str | None = None
    resolution: ResolutionSummary | None = None
    # Product Experience Remediation Milestone 1 (Decision Detail
    # contract): all additive, all read off the same earliest-Evidence-
    # record lookup this response already performs for policy_version/
    # policy_bundle_hash/authority_version above -- no new query shape,
    # only wider projection of data already fetched. Every field is
    # None exactly when that Evidence lookup itself finds nothing (a
    # suspended/retired agent, an unrecognized action) -- the same
    # optionality those three fields already have, not a new failure
    # mode.
    source: str | None = None
    principal_name: str | None = None
    evidence_id: UUID | None = None
    # Trusted Enterprise Facts actually evaluated for this decision --
    # the exact list Evidence's own payload already carries
    # (key/value/subject/source_id/observed_at/expires_at), never
    # recomputed. None (not an empty list) when no fact was evaluated,
    # matching Evidence's own convention for this field.
    facts_evaluated: list[dict] | None = None
    matched_policy_freshness: PolicyFreshnessSummary | None = None
    capability: CapabilitySummary | None = None


class DecisionListResponse(BaseModel):
    """Pagination envelope for GET /v1/decisions (the Pending Review
    queue), matching AgentListResponse's established shape
    (schemas/agent.py) rather than inventing a new one."""

    decisions: list[GetDecisionResponse]
    total: int
    limit: int
    offset: int


class DecisionHistoryItem(BaseModel):
    """Product Experience Remediation Milestone 1 (Phase 3): the
    lightweight, list-row shape for GET /v1/decisions/history --
    deliberately narrower than GetDecisionResponse (no policy version/
    bundle hash/facts/capability/freshness detail; a caller wanting that
    already has GET /v1/decisions/{id}). No amount/currency: those are
    contextual, not universal, and have no place in a summary row every
    action type shares."""

    id: UUID
    created_at: datetime
    agent_id: UUID
    agent_name: str | None = None
    principal_name: str | None = None
    action: str
    resource: str | None = None
    outcome: str
    reason: str | None = None
    matched_policy_name: str | None = None
    source: str | None = None
    has_evidence: bool
    # None when the outcome was never HUMAN_REVIEW at all; "pending" or
    # "resolved" otherwise -- the same distinction the Pending Review
    # queue already makes, just carried onto every row here too.
    human_review_state: str | None = None


class DecisionHistoryResponse(BaseModel):
    decisions: list[DecisionHistoryItem]
    total: int
    limit: int
    offset: int


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


class DecisionExplanationResponse(BaseModel):
    """Phase 2B: the explanatory path, kept strictly separate from the
    authoritative one (server/app/services/decision_explanation_service.py).
    Reconstructed entirely from Historical Policy Binding
    (Policy.bundle_manifest) plus Decision/Evidence/Intent, using the
    existing, unmodified Runtime Policy Simulator explainer
    (domain/policy_simulation/explainer.build_rule_evaluations) -- never
    an LLM, never a second decision, never a mutation of anything.

    `available=False` (with `unavailable_reason` set, every other field
    left at its default) is a real, distinct response, not an error:
    some historical decisions genuinely cannot be reconstructed (no
    policy was ever evaluated, the bundle predates
    Policy.bundle_manifest, OPA itself never completed the evaluation),
    and this says so explicitly rather than fabricating a plausible-
    looking explanation.

    `rules` reuses RuleEvaluationResponse/ConditionEvaluationResponse
    unchanged, the same schema the Runtime Policy Simulator's own API
    already returns -- not a second, parallel definition of the same
    shape. `causal_policy_id` is the one rule (if any) whose match
    actually produced this outcome; null when no rule matched (the
    default-deny/undetermined fallback path, or a decision made before
    any policy existed)."""

    decision_id: UUID
    available: bool
    unavailable_reason: str | None = None
    outcome: str | None = None
    reason: str | None = None
    policy_id: UUID | None = None
    bundle_hash: str | None = None
    bundle_version: int | None = None
    compiled_at: datetime | None = None
    activated_at: datetime | None = None
    retired_at: datetime | None = None
    evaluated_at: datetime | None = None
    causal_policy_id: str | None = None
    rules: list[RuleEvaluationResponse] = []
