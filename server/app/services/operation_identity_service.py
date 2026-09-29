"""Trusted Integration Architecture, Phase 3: business-operation identity
for the trusted-Adapter runtime path only (Agent-direct is untouched --
see section 23 of the brief). Answers a question Phase 2's nonce
replay protection never could: "have I already made a Runtime Authority
decision for this real-world operation?", not merely "have I already
received this exact authenticated request?".

Scope (section 4): organization + integration + environment +
external_operation_id. Organization scoping is implicit, not a separate
stored column -- `integration_id` is a UUID primary key belonging to
exactly one Integration row, which belongs to exactly one organization
(Integration.organization_id), so a partial-unique index on
(integration_id, environment, external_operation_id) is already
correctly organization-scoped without a redundant column.

Deliberately NOT scoped by enforcement_binding_id (Bindings are
replaceable configuration, section 10) or integration_identity_id
(Adapter identity rotation must not reset idempotency, section 11).

Canonical fingerprint (section 6): the authority-relevant MEANING of
the operation, computed server-side from the live runtime input, never
from anything the Adapter could game by resubmitting the same
external_operation_id with different authority-relevant values.
Includes the origin Agent's identity (section 5's mandatory
correction -- Agent A and Agent B may share an Adapter and Binding but
hold different organizational authority; a fingerprint mismatch on
Agent alone must conflict, never silently return Agent A's Decision
for Agent B). Uses the Integration Contract's deterministic
content_hash, never IntegrationContractVersion.id (section 32) -- two
independently approved versions with identical semantic content must
not manufacture a false conflict. Excludes environment (already the
uniqueness scope, section 6's own parenthetical), nonce, timestamp,
correlation_id, IntegrationIdentity/certificate id, and
EnforcementBinding id -- none of those are part of what the operation
MEANS.
"""

import decimal
import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import BusinessOperationIdentity, Intent

MAX_EXTERNAL_OPERATION_ID_LENGTH = 256
MAX_CONCURRENT_ATTEMPT_RETRIES = 3


class InvalidExternalOperationIdError(Exception):
    """section 29: empty, whitespace-only, or absurdly large. Deliberately
    does not restrict format to numeric/UUID -- enterprise systems use
    many identifier formats -- and never normalizes case: an identifier
    is opaque, compared byte-for-byte, exactly as the Adapter supplied
    it."""


def validate_external_operation_id(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InvalidExternalOperationIdError("external_operation_id must be a non-empty, non-whitespace string")
    if len(value) > MAX_EXTERNAL_OPERATION_ID_LENGTH:
        raise InvalidExternalOperationIdError(
            f"external_operation_id exceeds the maximum length of {MAX_EXTERNAL_OPERATION_ID_LENGTH} characters"
        )


def _normalize_amount(amount: float | None) -> str | None:
    """Section 34: fingerprint the actual authority semantics, not
    incidental JSON/float serialization. Intent.amount is persisted as
    Numeric(18,2) and Runtime Authority's own threshold conditions
    operate at that same precision -- quantizing here to 2 decimal
    places via Decimal (never via float rounding, which would
    reintroduce the exact binary-imprecision this is trying to avoid)
    means 100.1, 100.10, and 100.099999999999 (a plausible float
    artifact) all normalize identically, matching what the engine
    actually treats as equivalent."""
    if amount is None:
        return None
    return str(decimal.Decimal(str(amount)).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_HALF_UP))


def compute_canonical_operation_fingerprint(
    *,
    origin_agent_id: uuid.UUID,
    contract_content_hash: str,
    source_operation: str,
    canonical_action: str,
    resource: str | None,
    amount: float | None,
    currency: str | None,
    fact_subject: str | None,
    trusted_context: dict[str, Any],
) -> str:
    """Deterministic canonical JSON (sorted keys, recursing into nested
    values -- section 33's own guidance: this codebase's Contract-bound
    context today only ever carries whatever JSON-serializable value
    the Adapter attested per declared key, so `sort_keys=True`'s
    existing recursive behavior is already sufficient; nothing generic
    was invented beyond it), then SHA-256 -- the same "hash the
    canonical serialization" shape Phase 1's own content_hash already
    established (integration_contract_service._compute_content_hash)."""
    semantic = {
        "origin_agent_id": str(origin_agent_id),
        "contract_content_hash": contract_content_hash,
        "source_operation": source_operation,
        "canonical_action": canonical_action,
        "resource": resource,
        "amount": _normalize_amount(amount),
        "currency": currency,
        "fact_subject": fact_subject,
        "trusted_context": trusted_context,
    }
    canonical = json.dumps(semantic, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def find_existing_operation(
    db: Session, integration_id: uuid.UUID, environment: str, external_operation_id: str,
) -> Intent | None:
    """The read side of the idempotency scope -- a fast, non-authoritative
    check before ever constructing a new Intent (avoids wasted
    evaluation work on the common repeat-retry path), and the
    authoritative re-check performed after a racing IntegrityError on
    the real DB-enforced partial unique index
    (idx_intents_external_operation_scope) -- see
    integration_runtime_service.submit_attested_intent for how both call
    sites use this identically."""
    return db.scalar(
        select(Intent).where(
            Intent.integration_id == integration_id,
            Intent.environment == environment,
            Intent.external_operation_id == external_operation_id,
        )
    )


# === Closeout pass, section 1: business-operation identity ===============
#
# DISTINCT from everything above. `find_existing_operation` (and the
# whole external_operation_id scope) answers "have I already made a
# Decision for this exact SUBMISSION" -- its own DB constraint
# (idx_intents_external_operation_scope) forbids a second Intent from
# ever sharing an external_operation_id, so it cannot represent "the
# same real-world operation, attempted again." The functions below
# answer that different question, for callers that opt in by supplying
# BOTH business_operation_id and an intended destination at submission
# time (schemas/integration_runtime.py AttestedIntentRequest).


class ConcurrentBusinessOperationAttemptError(Exception):
    """Raised when advance_current_attempt could not win the atomic
    conditional UPDATE after MAX_CONCURRENT_ATTEMPT_RETRIES real
    attempts -- a sustained, repeated concurrent racer, not a single
    transient collision (a single collision is retried transparently;
    see that function's own docstring). The caller should treat this the
    same as any other "try again" signal, never as a permanent
    rejection."""

    def __init__(self, business_operation_identity_id: uuid.UUID):
        self.business_operation_identity_id = business_operation_identity_id
        super().__init__(
            f"business_operation_identity {business_operation_identity_id}: "
            f"could not win the current-attempt update after {MAX_CONCURRENT_ATTEMPT_RETRIES} retries"
        )


def resolve_or_create_business_operation_identity(
    db: Session, organization_id: uuid.UUID, integration_id: uuid.UUID, action: str,
    destination: str, business_operation_id: str,
) -> BusinessOperationIdentity:
    """The read-then-insert-then-catch-IntegrityError-then-requery shape
    Phase 3 already established for Intent's own idempotency scope
    (integration_runtime_service.submit_attested_intent), applied here
    to the SAME real concurrency hazard: two genuinely concurrent first
    attempts at the same business identity must not both succeed in
    creating a row -- the DB's own unique constraint
    (uq_business_operation_identity) is the actual guarantee; this
    function's own read-first and except-IntegrityError-then-requery are
    the fast path and the correctness fallback, not the guarantee
    itself.

    `action` (contract-enforcement pass): the canonical action type --
    part of the identity's own namespace alongside integration_id and
    destination, so two unrelated action types under the same
    integration/destination can never collide merely for reusing the
    same business_operation_id string."""
    existing = db.scalar(
        select(BusinessOperationIdentity).where(
            BusinessOperationIdentity.organization_id == organization_id,
            BusinessOperationIdentity.integration_id == integration_id,
            BusinessOperationIdentity.action == action,
            BusinessOperationIdentity.destination == destination,
            BusinessOperationIdentity.business_operation_id == business_operation_id,
        )
    )
    if existing is not None:
        return existing

    identity = BusinessOperationIdentity(
        organization_id=organization_id, integration_id=integration_id, action=action,
        destination=destination, business_operation_id=business_operation_id,
    )
    db.add(identity)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(BusinessOperationIdentity).where(
                BusinessOperationIdentity.organization_id == organization_id,
                BusinessOperationIdentity.integration_id == integration_id,
                BusinessOperationIdentity.action == action,
                BusinessOperationIdentity.destination == destination,
                BusinessOperationIdentity.business_operation_id == business_operation_id,
            )
        )
        if existing is None:
            # The unique constraint fired but a requery finds nothing --
            # not the concurrent-creation race this except clause exists
            # for; re-raising rather than silently returning None keeps
            # this function's contract honest (it always returns a real,
            # persisted row, or raises).
            raise
        return existing
    return identity


def advance_current_attempt(
    db: Session, identity: BusinessOperationIdentity, *, expected_current_operation_id: uuid.UUID | None, new_operation_id: uuid.UUID,
) -> bool:
    """The atomic conditional UPDATE -- `WHERE current_operation_id IS
    [NOT DISTINCT FROM / =] expected` -- mirroring the exact shape
    capability_service.verify_and_consume_capability's own
    `UPDATE ... WHERE consumed_at IS NULL` already established for a
    different resource's single-writer-wins race. Returns True if THIS
    call won (rowcount == 1); False means a concurrent attempt already
    advanced current_operation_id to something else since it was read --
    the caller (operation_service's issuance-time orchestration) is
    responsible for re-reading, re-evaluating replacement safety against
    whatever actually won, and retrying, exactly how a losing capability-
    consume attempt is handled -- never for silently forcing its own
    value in on top."""
    if expected_current_operation_id is None:
        condition = BusinessOperationIdentity.current_operation_id.is_(None)
    else:
        condition = BusinessOperationIdentity.current_operation_id == expected_current_operation_id
    result = db.execute(
        update(BusinessOperationIdentity)
        .where(BusinessOperationIdentity.id == identity.id, condition)
        .values(current_operation_id=new_operation_id)
    )
    return result.rowcount == 1
