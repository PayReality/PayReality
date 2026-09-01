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
    # Human Review Continuation (issue #10): the caller's own external
    # workflow/job/request identifier, echoed back exactly as submitted
    # (Intent.correlation_id) so a caller can map their own id to this
    # decision_id without having to keep a side-table. Trace/correlation
    # metadata only -- never consulted by policy matching or any
    # authorization decision.
    correlation_id: str | None = None


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
    # Trusted Integration Architecture, Phase 5: the Runtime Connection
    # (enforcement_binding_id) and environment this Capability was bound
    # to -- None for every Agent-direct Capability, and for any
    # Capability issued before this field existed.
    environment: str | None = None
    enforcement_binding_id: str | None = None


class ReceiptIntegrationSummary(BaseModel):
    """Trusted Integration Architecture, Phase 2: present only when this
    decision's Intent actually carries integration provenance (an
    Adapter-mediated request) -- read from the same Evidence payload
    keys intent_service._build_evidence_payload additively wrote at
    decision time, never recomputed from a possibly-since-changed live
    row. Reporting this provenance is not a claim that the external
    operation the Adapter attested to actually executed, or that no
    other path to the same effect exists -- see
    integration_runtime_service's own module docstring for the trust
    claim this is allowed to make.

    Lives here (not in authorization_receipt.py, despite the name) so
    both AuthorizationReceiptResponse and GetDecisionResponse (Phase 4)
    can share one definition without a circular import between the two
    schema modules -- authorization_receipt.py already imports from
    this module for CapabilitySummary/PolicyManifestEntry, so this is
    the existing import direction, not a new one."""

    integration_identity_id: str | None = None
    enforcement_binding_id: str | None = None
    integration_contract_version_id: str | None = None
    integration_contract_content_hash: str | None = None
    # Trusted Integration Architecture, Phase 4: additive -- lets a
    # reader resolve the owning Integration (system name, other mapping
    # versions) directly, without first resolving
    # integration_contract_version_id -> IntegrationContractVersion.
    integration_id: str | None = None
    environment: str | None = None
    source_operation: str | None = None
    # Trusted Integration Architecture, Phase 3: the external, business-
    # meaningful operation identifier this Decision belongs to -- present
    # only for a trusted-Adapter-mediated Decision that actually carries
    # one (every Agent-direct Decision, and every Adapter-mediated one
    # predating Phase 3, leaves this None). Deliberately does NOT expose
    # the internal canonical-operation fingerprint here (section 25: no
    # strong debugging/audit reason to -- Evidence's own signed payload
    # already carries it for cryptographic historical proof, see
    # ReceiptEvidenceSummary/intent_service._build_evidence_payload).
    external_operation_id: str | None = None


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
    # Human Review Continuation (issue #10): the same external
    # correlation id the caller submitted on the original Intent --
    # read directly off that Intent row, not recomputed. None for any
    # historical decision predating this field, an honest null, never
    # backfilled.
    correlation_id: str | None = None
    # Trusted Enterprise Facts actually evaluated for this decision --
    # the exact list Evidence's own payload already carries
    # (key/value/subject/source_id/observed_at/expires_at), never
    # recomputed. None (not an empty list) when no fact was evaluated,
    # matching Evidence's own convention for this field.
    facts_evaluated: list[dict] | None = None
    matched_policy_freshness: PolicyFreshnessSummary | None = None
    capability: CapabilitySummary | None = None
    # Trusted Integration Architecture, Phase 4: reuses
    # ReceiptIntegrationSummary (below) unchanged -- the exact same
    # "present only when this decision's Intent actually carries
    # integration provenance" read, off the same earliest-Evidence-record
    # lookup this response already performs for policy_version/
    # policy_bundle_hash/authority_version above, never a new query.
    integration: ReceiptIntegrationSummary | None = None


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
    # Human Review Continuation (issue #10): cheap enough to include in
    # a list row (it's already on the joined Intent), and exactly what a
    # caller scanning their own history to find "my decision" needs.
    correlation_id: str | None = None


class DecisionHistoryResponse(BaseModel):
    decisions: list[DecisionHistoryItem]
    total: int
    limit: int
    offset: int


class PolicyManifestEntrySource(BaseModel):
    """Authority Graph -> RuntimePolicy Compilation Gate (issue #6):
    present only for a graph-derived policy -- see
    domain/compiler_v2/bundle_builder.py's manifest construction. This
    is what makes the source graph version survive into a historical
    Decision's bound Policy row and, unchanged, into the Authorization
    Receipt's `authority.policies` list."""

    type: str
    corpus_id: str
    graph_approval_id: str
    graph_version: int
    candidate_id: str


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
    source: PolicyManifestEntrySource | None = None


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
