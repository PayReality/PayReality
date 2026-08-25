"""Capability Authorization Protocol (PAYREALITY_FUTURE_VISION.md Part
C): issues and verifies short-lived, signed capabilities bound to one
ALLOW decision. Reuses this platform's existing Ed25519 signing-key
registry (signing_key_service.py) unchanged -- a capability token is
signed with the exact same active evidence-signing key as any other
signed record here, verified via the exact same historical key lookup
Evidence verification already relies on, so key rotation never breaks
an already-issued (but not yet expired) token any more than it breaks
old Evidence.

Explicitly a demonstration protocol, not enforcement infrastructure --
see domain/capability/token.py's own module docstring for the full,
deliberately unsoftened statement of what this does and does not prove."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import CapabilityToken, Evidence, Intent
from app.domain.capability import token as capability_token
from app.services import intent_service, signing_key_service
from app.services.intent_service import CrossOrganizationAccessError, DecisionNotFoundError


class DecisionNotAllowError(Exception):
    """A capability may only be issued for an ALLOW decision -- issuing
    one for a DENY or HUMAN_REVIEW decision would mint an executable
    authorization for an action Runtime Authority never actually
    permitted."""


class CapabilityTokenNotFoundError(Exception):
    pass


class CapabilityTokenAlreadyConsumedError(Exception):
    pass


DEFAULT_CAPABILITY_TOKEN_TTL_SECONDS = 300


@dataclass(frozen=True)
class IssuedCapability:
    token: str
    capability_id: uuid.UUID
    expires_at: datetime


def issue_capability_for_decision(
    db: Session,
    organization_id: uuid.UUID,
    decision_id: uuid.UUID,
    audience: str,
    issued_by: str | None = None,
    ttl_seconds: int = DEFAULT_CAPABILITY_TOKEN_TTL_SECONDS,
) -> IssuedCapability:
    # Reuses intent_service's own org-scoped decision lookup unchanged
    # (the exact function GET /v1/decisions/{id} is built on) rather
    # than re-deriving organization scoping here a second way.
    decision = intent_service.get_decision_for_organization(db, decision_id, organization_id)
    if decision.outcome != "ALLOW":
        raise DecisionNotAllowError(f"decision {decision_id} outcome={decision.outcome!r}")

    intent = db.get(Intent, decision.intent_id)
    earliest_evidence = db.scalar(
        select(Evidence).where(Evidence.decision_id == decision.id).order_by(Evidence.created_at.asc()).limit(1)
    )
    payload = earliest_evidence.payload if earliest_evidence else {}
    principal_name = payload.get("principal_name") or ""
    # Intent has no dedicated `resource` column (Scope.resource is a
    # RuntimePolicy authoring concept, not something an Intent carries
    # today) -- the correlation_id, when the caller supplied one, is the
    # closest real, caller-specified identifier of "which real-world
    # object this action concerns"; falling back to the Intent's own row
    # id keeps the bound resource concrete and specific either way,
    # never a category.
    resource = intent.correlation_id or str(intent.id)
    constraints = {"amount": str(intent.amount), "currency": intent.currency}
    fact_hashes = [
        capability_token.token_hash(str(f)) for f in payload.get("facts_evaluated", [])
    ]

    issued = capability_token.issue_capability_token(
        decision_id=decision.id,
        organization_id=organization_id,
        principal=principal_name,
        action=intent.action,
        resource=resource,
        constraints=constraints,
        policy_version=payload.get("policy_version"),
        fact_hashes=fact_hashes,
        audience=audience,
        ttl_seconds=ttl_seconds,
        signing_key_b64=settings.evidence_signing_key_b64,
        key_id=settings.evidence_signing_key_id,
    )

    expires_at = datetime.fromisoformat(issued.payload.expires_at)
    row = CapabilityToken(
        organization_id=organization_id,
        decision_id=decision.id,
        audience=audience,
        nonce=issued.payload.nonce,
        token_hash=issued.token_hash,
        expires_at=expires_at,
        issued_by=issued_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return IssuedCapability(token=issued.token, capability_id=row.id, expires_at=expires_at)


@dataclass(frozen=True)
class ConsumedCapability:
    capability_id: uuid.UUID
    decision_id: uuid.UUID
    resource: str
    constraints: dict


def verify_and_consume_capability(
    db: Session,
    token: str,
    audience: str,
    action: str,
    resource: str,
    constraints: dict,
) -> ConsumedCapability:
    """Online verify-and-consume (PAYREALITY_FUTURE_VISION.md Part C's
    own explicit scoping: this milestone is online verify-and-consume,
    not offline verification -- a future offline-verification design is
    a distinct, NOT-built-here architecture). Signature/expiry/audience/
    parameter checks happen inside domain/capability/token.py first;
    this function's own job is looking up the persisted row by the
    token's own hash and atomically marking it consumed, so two
    concurrent presentations of the same token cannot both succeed."""
    envelope_hash = capability_token.token_hash(token)
    row = db.scalar(select(CapabilityToken).where(CapabilityToken.token_hash == envelope_hash))
    if row is None:
        raise CapabilityTokenNotFoundError("no matching issued capability")

    key_id = _extract_key_id(token)
    public_key = signing_key_service.get_public_key_for_key_id(db, key_id)
    if public_key is None:
        raise capability_token.InvalidCapabilityTokenError(f"unknown signing key_id={key_id!r}")

    verified = capability_token.verify_capability_token(
        token, public_key_b64=public_key, expected_audience=audience, expected_action=action,
        expected_resource=resource, expected_constraints=constraints,
    )

    # Atomic single-use consumption: an UPDATE ... WHERE consumed_at IS
    # NULL affects exactly one row the first time and zero rows on any
    # concurrent or later attempt, so two simultaneous requests can never
    # both observe success -- the same guarantee Intent's own
    # UNIQUE(agent_id, nonce) constraint gives for replay, expressed as a
    # conditional update instead of an insert-conflict.
    from sqlalchemy import update

    result = db.execute(
        update(CapabilityToken)
        .where(CapabilityToken.id == row.id, CapabilityToken.consumed_at.is_(None))
        .values(consumed_at=datetime.now(timezone.utc))
    )
    db.commit()
    if result.rowcount == 0:
        raise CapabilityTokenAlreadyConsumedError(str(row.id))

    return ConsumedCapability(
        capability_id=row.id, decision_id=verified.payload.decision_id,
        resource=verified.payload.resource, constraints=verified.payload.constraints,
    )


def _extract_key_id(token: str) -> str:
    import base64
    import json

    envelope = json.loads(base64.b64decode(token))
    return envelope["key_id"]
