"""Issue #4 (Authorization Receipts): assembles the AuthorizationReceipt
projection from already-persisted, already-tested records. No new
persistent storage; no new signing/verification mechanism. See
app/schemas/authorization_receipt.py's module docstring for the full
scope boundary (not RFC-001, not Capability Authorization).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import Agent, DecisionResolution, Intent, Policy
from app.domain.evidence.signing import payload_hash
from app.schemas.authorization_receipt import (
    AuthorizationReceiptResponse,
    ReceiptActorSummary,
    ReceiptAuthoritySummary,
    ReceiptDecisionSummary,
    ReceiptEvidenceSummary,
    ReceiptFactEntry,
    ReceiptHumanReviewSummary,
    ReceiptIntegrationSummary,
    ReceiptRequestSummary,
    ReceiptVerification,
)
from app.schemas.intent import CapabilitySummary, PolicyManifestEntry
from app.services import evidence_service, intent_service


class ReceiptNotAvailableError(Exception):
    """Raised when a Decision genuinely exists but has no Evidence record
    at all to build a receipt from -- every decision made through the
    real submit_intent path always has one (created in the same
    transaction), so this should only ever fire for a synthetic/test
    Decision row created without going through that path. A receipt is
    never fabricated to paper over this; the caller gets a clear error
    instead of a response with a hollow evidence/verification section."""


def get_authorization_receipt(
    db: Session, decision_id: uuid.UUID, organization_id: uuid.UUID | None
) -> AuthorizationReceiptResponse:
    """Org-scoped and 404-shaped identically to GET /v1/decisions/{id}:
    reuses get_decision_for_organization unchanged, so a decision
    belonging to a different organisation is indistinguishable from one
    that doesn't exist (intent_service.DecisionNotFoundError /
    CrossOrganizationAccessError propagate to the caller unchanged)."""
    decision = intent_service.get_decision_for_organization(db, decision_id, organization_id)
    intent = db.get(Intent, decision.intent_id)

    earliest_evidence = intent_service.get_earliest_evidence_for_decision(db, decision.id)
    if earliest_evidence is None:
        raise ReceiptNotAvailableError(str(decision_id))
    payload = earliest_evidence.payload or {}

    agent = db.get(Agent, intent.agent_id)

    # Historical Policy Binding, reused unmodified: decision.policy_id is
    # an immutable FK to a retired-not-deleted Policy row -- reading its
    # bundle_hash/version/compiled_at/activated_at/retired_at is reading
    # what actually governed this decision, not today's active policy.
    # Falls back to the Evidence-pinned values only for the rarer case
    # where no policy row can be resolved at all (no_active_policy,
    # opa_timeout) -- never fabricated either way.
    policy: Policy | None = db.get(Policy, decision.policy_id) if decision.policy_id else None
    if policy is not None:
        manifest = policy.bundle_manifest or {}
        authority = ReceiptAuthoritySummary(
            policy_id=policy.id,
            bundle_hash=policy.bundle_hash,
            bundle_version=policy.version,
            compiled_at=policy.compiled_at,
            activated_at=policy.activated_at,
            retired_at=policy.retired_at,
            authority_version=payload.get("authority_version"),
            policies=[PolicyManifestEntry(**p) for p in manifest.get("policies", [])],
        )
    else:
        authority = ReceiptAuthoritySummary(
            policy_id=None,
            bundle_hash=payload.get("policy_bundle_hash"),
            bundle_version=payload.get("policy_version"),
            compiled_at=None,
            activated_at=None,
            retired_at=None,
            authority_version=payload.get("authority_version"),
            policies=[],
        )

    resolution_row = db.query(DecisionResolution).filter_by(decision_id=decision.id).one_or_none()
    human_review = None
    if resolution_row is not None:
        human_review = ReceiptHumanReviewSummary(
            resolution=resolution_row.resolution,
            resolved_by=resolution_row.resolved_by,
            reason=resolution_row.reason,
            resolved_at=resolution_row.created_at,
        )

    capability_row = intent_service.get_latest_capability_for_decision(db, decision.id)
    capability = None
    if capability_row is not None:
        # Same construction as routers/intents.py's _build_decision_response
        # -- resource/action reflect this exact Intent, never a second,
        # independently-fabricated value. `consumed_at` records that the
        # token was presented and verified, never that the downstream
        # action actually executed (CapabilitySummary's own docstring).
        capability = CapabilitySummary(
            issued=True,
            audience=capability_row.audience,
            resource=intent.resource,
            action=intent.action,
            expires_at=capability_row.expires_at,
            consumed_at=capability_row.consumed_at,
        )

    # Trusted Integration Architecture, Phase 2: only present when the
    # underlying Evidence payload actually carries integration
    # provenance -- an Agent-direct decision's payload has none of
    # these keys, so `integration` stays None rather than a summary of
    # empty fields.
    integration = None
    if payload.get("integration_identity_id") is not None:
        integration = ReceiptIntegrationSummary(
            integration_identity_id=payload.get("integration_identity_id"),
            enforcement_binding_id=payload.get("enforcement_binding_id"),
            integration_contract_version_id=payload.get("integration_contract_version_id"),
            integration_contract_content_hash=payload.get("integration_contract_content_hash"),
            environment=payload.get("environment"),
            source_operation=payload.get("source_operation"),
        )

    valid, key_id = evidence_service.verify_evidence(db, earliest_evidence.id, organization_id)

    now = datetime.now(timezone.utc)
    return AuthorizationReceiptResponse(
        receipt_id=earliest_evidence.id,
        evidence_id=earliest_evidence.id,
        generated_at=now,
        decision=ReceiptDecisionSummary(
            decision_id=decision.id,
            outcome=decision.outcome,
            created_at=decision.created_at,
            source=intent.source,
        ),
        actor=ReceiptActorSummary(
            agent_id=intent.agent_id,
            agent_name=agent.name if agent is not None else None,
            principal_id=payload.get("principal_id"),
            principal_name=payload.get("principal_name"),
        ),
        request=ReceiptRequestSummary(
            action=intent.action,
            resource=intent.resource,
            amount=float(intent.amount) if intent.amount is not None else None,
            currency=intent.currency,
            context=intent.context or {},
            correlation_id=intent.correlation_id,
        ),
        authority=authority,
        facts=[ReceiptFactEntry(**f) for f in (payload.get("facts_evaluated") or [])],
        human_review=human_review,
        capability=capability,
        integration=integration,
        evidence=ReceiptEvidenceSummary(
            evidence_id=earliest_evidence.id,
            key_id=earliest_evidence.key_id,
            signature=earliest_evidence.signature,
            previous_hash=payload.get("previous_hash"),
            payload_hash=payload_hash(payload),
            status=earliest_evidence.status,
            created_at=earliest_evidence.created_at,
        ),
        verification=ReceiptVerification(
            signature_valid=valid,
            key_id=key_id,
            verified_at=now,
        ),
    )
