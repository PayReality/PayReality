"""Issue #4 (Authorization Receipts): a stable, named, read-only
projection assembling data that already exists -- Decision, Intent,
Evidence, the immutable Policy bundle a decision was actually evaluated
against, and (where they apply) DecisionResolution and CapabilityToken
-- into one auditor-facing artifact.

Deliberately narrow. This is NOT RFC-001 (SPECIFICATION/RFC_001_
AUTHORIZATION_RECEIPTS.md): no Merkle transparency log, no portable/
offline archive, no new cryptographic protocol, no second Evidence
system. Every field here maps to a row that already exists or a
deterministic read of an immutable historical record (Decision.policy_id
always points at a retired-not-deleted Policy row -- reading it is not
"today's state," it is the frozen state that governed this decision,
which is exactly Historical Policy Binding's own existing guarantee).

Also NOT Capability Authorization. A capability token is forward-looking,
ALLOW-only, short-lived, and single-use -- a permission slip a downstream
system may check before executing. A receipt is backward-looking,
permanent, and re-verifiable regardless of outcome -- proof that a
decision was made, and what governed it. `ReceiptCapabilitySummary`
reuses `CapabilitySummary`'s own explicit stance: consumption is a
recorded fact, never proof the downstream action actually executed.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.schemas.intent import CapabilitySummary, PolicyManifestEntry, ReceiptIntegrationSummary


class ReceiptDecisionSummary(BaseModel):
    decision_id: UUID
    outcome: str  # "ALLOW" | "DENY" | "HUMAN_REVIEW"
    created_at: datetime
    # Decision Provenance: self-declared at submission time ("runtime" |
    # "manual_test" | None for a record predating provenance tracking).
    # See app/domain/decision/source.py for the honest limits of this.
    source: str | None = None


class ReceiptActorSummary(BaseModel):
    agent_id: UUID
    # Live read of Agent.name (mirrors routers/intents.py's own
    # _build_decision_history_item precedent) -- an identity's current
    # display name, not a claim about what it was called at decision
    # time. principal_name below is the one that matters for historical
    # correctness, and IS pinned atomically (read from Evidence.payload).
    agent_name: str | None = None
    principal_id: str | None = None
    principal_name: str | None = None


class ReceiptRequestSummary(BaseModel):
    action: str
    resource: str | None = None
    amount: float | None = None
    currency: str | None = None
    # Intent rows are never mutated after creation, so this is a safe,
    # genuinely historical read -- not a live projection.
    context: dict[str, Any] = {}
    # Human Review Continuation (issue #10): genuinely useful historical
    # trace metadata -- lets an auditor cross-reference this receipt
    # against the caller's own external workflow/job id. Trace metadata
    # only; carries no cryptographic or authorization weight of its own.
    correlation_id: str | None = None


class ReceiptAuthoritySummary(BaseModel):
    """What governed this decision, reconstructed the same way
    DecisionPolicyBindingResponse already does (routers/intents.py's
    get_decision_policy_binding) -- Decision.policy_id is an immutable
    FK to a retired-not-deleted Policy bundle row, so bundle_hash/
    bundle_version/compiled_at/activated_at/retired_at are frozen facts
    about that exact bundle, unaffected by whatever the organization has
    deployed since. `policies` reuses PolicyManifestEntry unchanged --
    the same shape the policy-binding endpoint already returns, not a
    second definition. None throughout when no policy was ever
    evaluated (no_active_policy, opa_timeout) -- never fabricated."""

    policy_id: UUID | None = None
    bundle_hash: str | None = None
    bundle_version: int | None = None
    compiled_at: datetime | None = None
    activated_at: datetime | None = None
    retired_at: datetime | None = None
    # The evaluation engine's own version, pinned atomically in Evidence
    # at decision time (decision_engine.DECISION_ENGINE_VERSION then).
    authority_version: str | None = None
    policies: list[PolicyManifestEntry] = []


class ReceiptFactEntry(BaseModel):
    """One Trusted Enterprise Fact exactly as evaluated -- the same
    key/value/subject/source_id/observed_at/expires_at shape Evidence.
    payload["facts_evaluated"] already carries (intent_service.py's
    submit_intent), never recomputed against the fact's current (and
    possibly since-changed or since-expired) state."""

    key: str
    value: Any
    subject: str | None = None
    source_id: str | None = None
    observed_at: str | None = None
    expires_at: str | None = None


class ReceiptHumanReviewSummary(BaseModel):
    """Present only when a DecisionResolution row exists. Reuses
    ResolutionSummary's own field set (resolution/resolved_by/reason/
    created_at) -- the resolution object, never a rewrite of the
    original Decision (spec 8.2's immutability guarantee; see
    resolution_service.resolve_decision's own docstring)."""

    resolution: str  # "approved" | "denied"
    resolved_by: str
    reason: str | None = None
    resolved_at: datetime


class ReceiptEvidenceSummary(BaseModel):
    evidence_id: UUID
    key_id: str
    signature: str
    previous_hash: str | None = None
    # SHA-256 of this record's own canonical payload (domain/evidence/
    # signing.payload_hash) -- what the NEXT record in this
    # organisation's chain would reference as its previous_hash. Lets a
    # reviewer confirm chain continuity without a second API call.
    payload_hash: str
    status: str  # "VERIFIED" | "PENDING" | "REJECTED"
    created_at: datetime


class ReceiptVerification(BaseModel):
    """Computed live, on every request, never cached or stored --
    reuses evidence_service.verify_evidence unchanged (the exact
    signing-key-registry lookup that already makes Evidence verifiable
    across a key rotation, see EVIDENCE_KEY_ROTATION.md)."""

    signature_valid: bool
    key_id: str
    algorithm: str = "ed25519"
    verified_at: datetime


class AuthorizationReceiptResponse(BaseModel):
    """The stable, named artifact issue #4 asks for. `receipt_id` is
    deliberately the same value as `evidence_id`: this record's identity
    IS the underlying Evidence row's identity -- no second, independent
    id space is minted, and no new persistent storage exists for this
    response at all. `generated_at` is this request's own timestamp
    (when the projection was assembled), never persisted -- verifying
    the same decision again next year assembles a fresh receipt from the
    same immutable underlying records and must report the same
    decision/actor/request/authority/facts/evidence content."""

    receipt_id: UUID
    evidence_id: UUID
    generated_at: datetime
    decision: ReceiptDecisionSummary
    actor: ReceiptActorSummary
    request: ReceiptRequestSummary
    authority: ReceiptAuthoritySummary
    facts: list[ReceiptFactEntry] = []
    human_review: ReceiptHumanReviewSummary | None = None
    capability: CapabilitySummary | None = None
    integration: ReceiptIntegrationSummary | None = None
    evidence: ReceiptEvidenceSummary
    verification: ReceiptVerification
