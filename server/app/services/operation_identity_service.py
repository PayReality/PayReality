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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Intent

MAX_EXTERNAL_OPERATION_ID_LENGTH = 256


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
