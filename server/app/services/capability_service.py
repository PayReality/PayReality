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

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Agent, CapabilityToken, EnforcementBinding, Evidence, Intent, IntegrationIdentity
from app.domain.capability import token as capability_token
from app.services import intent_service, signing_key_service
from app.services.intent_service import CrossOrganizationAccessError, DecisionNotFoundError

logger = logging.getLogger("payreality.capability")


class DecisionNotAllowError(Exception):
    """A capability may only be issued for a Decision whose outcome is
    literally ALLOW -- issuing one for DENY or HUMAN_REVIEW would mint an
    executable authorization for an action Runtime Authority never
    actually permitted. No post-review issuance path exists today for
    either the Agent-direct or the Trusted-Adapter path: a Decision's
    `outcome` is immutable (resolve_decision never mutates it, by
    design -- see Decision's own docstring), so a HUMAN_REVIEW decision
    that a human later approves still has outcome == HUMAN_REVIEW
    forever, and this check still correctly rejects it. Building a
    distinct "issue a capability from an approved HUMAN_REVIEW
    resolution" path is a materially new capability, not an extension of
    this one -- deliberately out of this milestone's scope; see
    Trusted Integration Architecture, Phase 5's own audit notes."""


class IntegrationIdentityNotActiveError(Exception):
    """Trusted Integration Architecture, Phase 5 (fail-closed re-check at
    issuance time): the IntegrationIdentity that produced this Decision's
    Intent is no longer active. An Intent's provenance is immutable, but
    trust is not -- an identity can be suspended/revoked/retired at any
    point after the Intent that used it was accepted, and a Capability
    must never be mintable on behalf of trust that no longer holds *at
    the moment of issuance*, even for an already-decided Decision."""


class EnforcementBindingNotActiveError(Exception):
    """Trusted Integration Architecture, Phase 5 (fail-closed re-check at
    issuance time): the EnforcementBinding (Runtime Connection) this
    Decision's Intent was evaluated under is no longer active. Mirrors
    IntegrationIdentityNotActiveError's own reasoning exactly -- a
    Binding retired after the Intent was accepted must not silently keep
    minting Capabilities under its name."""


class OriginAgentNotActiveError(Exception):
    """Trusted Integration Architecture, Phase 5 (fail-closed re-check at
    issuance time, section 6/40's "wrong Agent"/"Agent removed from
    allowed list" coverage): a real gap this milestone's own hostile
    review found and closed, applying identically to the Agent-direct
    path as well, not only the Trusted-Adapter one -- neither path
    previously re-checked the origin Agent's own live status before
    minting a Capability from an already-decided ALLOW decision. An
    Agent can be suspended/revoked/retired at any point after its
    Intent was accepted (Phase 9, AGENT_LIFECYCLE.md); an EnforcementBinding's
    own allow-list membership is immutable once ACTIVE, so removing an
    Agent from it is not possible without retiring the whole Binding
    (already covered by EnforcementBindingNotActiveError above) -- this
    is the other, equally real half: the Agent's OWN eligibility,
    independent of any Binding."""


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

    # Trusted Integration Architecture, Phase 5 (fail-closed re-check,
    # section 6/40): applies to BOTH runtime paths, not only the
    # Adapter-mediated one -- the origin Agent's own eligibility can
    # change at any point after its Intent was accepted, independent of
    # any Binding.
    agent = db.get(Agent, intent.agent_id)
    if agent is None or agent.status != "active":
        logger.warning(
            "capability_issuance_result=REJECTED_AGENT_NOT_ACTIVE decision_id=%s agent_id=%s status=%s",
            decision_id, intent.agent_id, agent.status if agent else "not_found",
        )
        raise OriginAgentNotActiveError(
            f"decision {decision_id}: agent_id={intent.agent_id} status={agent.status if agent else 'not_found'!r}"
        )

    # Trusted Integration Architecture, Phase 5: the Phase-2 blanket
    # suppression (CapabilityNotAvailableForIntegrationIntentError) is
    # lifted here, but only after re-establishing, live, at the moment
    # of issuance -- never merely trusting the Intent's own historical
    # provenance -- that the trust chain this Capability would extend
    # still actually holds. An Intent's provenance columns are immutable
    # (section 6), but the IntegrationIdentity and EnforcementBinding
    # they name are not: either can be suspended/revoked/retired at any
    # point after the Intent was accepted, and this must fail closed on
    # that, not silently keep minting Capabilities under a trust
    # relationship that no longer exists (section 39).
    integration_identity_id: uuid.UUID | None = None
    enforcement_binding_id: uuid.UUID | None = None
    integration_contract_version_id: uuid.UUID | None = None
    environment: str | None = None
    external_operation_id: str | None = None

    if intent.integration_identity_id is not None:
        identity = db.get(IntegrationIdentity, intent.integration_identity_id)
        if identity is None or identity.status != "active":
            logger.warning(
                "capability_issuance_result=REJECTED_IDENTITY_NOT_ACTIVE decision_id=%s "
                "integration_identity_id=%s status=%s",
                decision_id, intent.integration_identity_id, identity.status if identity else "not_found",
            )
            raise IntegrationIdentityNotActiveError(
                f"decision {decision_id}: integration_identity_id={intent.integration_identity_id} "
                f"status={identity.status if identity else 'not_found'!r}"
            )
        binding = db.get(EnforcementBinding, intent.enforcement_binding_id)
        if binding is None or binding.status != "active":
            logger.warning(
                "capability_issuance_result=REJECTED_BINDING_NOT_ACTIVE decision_id=%s "
                "enforcement_binding_id=%s status=%s",
                decision_id, intent.enforcement_binding_id, binding.status if binding else "not_found",
            )
            raise EnforcementBindingNotActiveError(
                f"decision {decision_id}: enforcement_binding_id={intent.enforcement_binding_id} "
                f"status={binding.status if binding else 'not_found'!r}"
            )
        integration_identity_id = identity.id
        enforcement_binding_id = binding.id
        integration_contract_version_id = intent.integration_contract_version_id
        environment = intent.environment
        external_operation_id = intent.external_operation_id

    earliest_evidence = db.scalar(
        select(Evidence).where(Evidence.decision_id == decision.id).order_by(Evidence.created_at.asc()).limit(1)
    )
    payload = earliest_evidence.payload if earliest_evidence else {}
    principal_name = payload.get("principal_name") or ""
    # Domain Generalization Milestone: Intent.resource (db/models.py) is
    # now the real, generic identifier of "which real-world object this
    # action concerns" -- falling back to correlation_id, then the
    # Intent's own row id, only for an older/non-financial-unaware
    # caller that never supplied one, so the bound resource is always
    # concrete and specific either way, never a category.
    resource = intent.resource or intent.correlation_id or str(intent.id)
    # Domain Generalization Milestone: constraints bind whichever
    # execution parameters this decision actually carried, generically
    # -- amount/currency when the action was financial, plus the
    # Intent's own evaluated context (the exact parameters the decision
    # was checked against, so a replayed token can't be presented
    # against substituted parameters), rather than hardcoding amount/
    # currency onto every capability regardless of action. `metadata` is
    # excluded: it's the SDK's own free-form caller-supplied bag, not a
    # parameter Runtime Authority actually evaluated.
    constraints: dict[str, str] = {}
    if intent.amount is not None:
        constraints["amount"] = str(intent.amount)
    if intent.currency is not None:
        constraints["currency"] = intent.currency
    for key, value in (intent.context or {}).items():
        if key == "metadata":
            continue
        constraints[key] = str(value)
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
        integration_identity_id=integration_identity_id,
        enforcement_binding_id=enforcement_binding_id,
        integration_contract_version_id=integration_contract_version_id,
        environment=environment,
        external_operation_id=external_operation_id,
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
        integration_identity_id=integration_identity_id,
        enforcement_binding_id=enforcement_binding_id,
        integration_contract_version_id=integration_contract_version_id,
        environment=environment,
        external_operation_id=external_operation_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info(
        "capability_issuance_result=ISSUED decision_id=%s capability_id=%s audience=%s "
        "enforcement_binding_id=%s expires_at=%s",
        decision.id, row.id, audience, enforcement_binding_id, expires_at,
    )
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
    environment: str | None = None,
    enforcement_binding_id: uuid.UUID | None = None,
    principal: str | None = None,
) -> ConsumedCapability:
    """Online verify-and-consume (PAYREALITY_FUTURE_VISION.md Part C's
    own explicit scoping: this milestone is online verify-and-consume,
    not offline verification -- a future offline-verification design is
    a distinct, NOT-built-here architecture). Signature/expiry/audience/
    parameter checks happen inside domain/capability/token.py first;
    this function's own job is looking up the persisted row by the
    token's own hash and atomically marking it consumed, so two
    concurrent presentations of the same token cannot both succeed.

    Trusted Integration Architecture, Phase 5: `environment`/
    `enforcement_binding_id`/`principal` are all optional (sections 6/9)
    -- a PEP that knows which Runtime Connection, environment, or Agent
    it expects may pin any of them; a PEP that supplies none skips those
    checks entirely, exactly as every pre-Phase-5 Agent-direct verifier
    already does."""
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
        expected_environment=environment, expected_enforcement_binding_id=enforcement_binding_id,
        expected_principal=principal,
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
        # A second (or racing) presentation of an already-consumed
        # token -- exactly the replay/double-consumption signal
        # observability needs to distinguish from ordinary failed
        # verification. Never logs the token itself, only its
        # capability_id, which is not secret (the token_hash it's
        # looked up by is a one-way hash, never the bearer artifact).
        logger.warning("capability_consumption_result=ALREADY_CONSUMED capability_id=%s", row.id)
        raise CapabilityTokenAlreadyConsumedError(str(row.id))

    logger.info(
        "capability_consumption_result=CONSUMED capability_id=%s decision_id=%s audience=%s",
        row.id, verified.payload.decision_id, audience,
    )
    return ConsumedCapability(
        capability_id=row.id, decision_id=verified.payload.decision_id,
        resource=verified.payload.resource, constraints=verified.payload.constraints,
    )


def _extract_key_id(token: str) -> str:
    import base64
    import json

    envelope = json.loads(base64.b64decode(token))
    return envelope["key_id"]
