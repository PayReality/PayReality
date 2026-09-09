"""Post-audit implementation, Priority 5: ingestion of a generic execution
receipt -- an authenticated trusted Adapter's own claim about the state of
one external operation it attempted after a Decision authorized it (and,
for a CAPABILITY_REQUIRED Binding, after its Capability was consumed).

Deliberately the smallest ingestion service that can enforce every trust
requirement the brief names, reusing existing primitives throughout rather
than re-deriving them: verify_integration_identity_signature (the same
Adapter-mediated authentication integration_runtime_service already uses),
organization_lifecycle_service.ensure_active (the same kill-switch check
Priority 1 added everywhere else), enforcement_binding_service.get_binding,
intent_service.get_decision_for_organization, and intent_service.
append_generic_evidence_event (the same organization-scoped Evidence hash
chain every other Evidence record in this codebase shares).

Trust claim, stated precisely (do not overclaim beyond this): this service
verifies that an authenticated IntegrationIdentity, still bound to the
EnforcementBinding it actually used for this Decision's own Intent, has
submitted a receipt whose canonical action, external operation, and (where
declared) Capability all match what was actually decided. It does NOT
verify that the receipt's own claimed status is true -- PayReality has no
independent channel to the external system, and never claims one (see
DECLARED_VS_OBSERVED_RECONCILIATION.md). A receipt is trusted provenance
about WHO is making WHICH claim about WHICH decided action; it is not
independent proof the claim itself is accurate.

Capability freshness, deliberately NOT re-checked here: unlike Capability
consumption (capability_service._check_consumption_freshness), a receipt
reports on an execution attempt that may genuinely happen well after a
short-lived Capability's own expiry -- the Capability already proved, at
consumption time, that the checkpoint gated on it; a receipt arriving
after that Capability has since expired does not retroactively invalidate
an execution that already, validly, happened. This service only checks
that the claimed Capability WAS consumed (capability.consumed_at is not
None) and belongs to this exact Decision/Binding -- never its current
expiry."""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import CapabilityToken, ExecutionReceiptRecord, IntegrationIdentity, Organization
from app.domain.execution_receipt import build_execution_receipt
from app.services import enforcement_binding_service, intent_service, organization_lifecycle_service
from app.services.enforcement_binding_service import EnforcementBindingNotFoundError
from app.services.intent_service import CrossOrganizationAccessError, DecisionNotFoundError

logger = logging.getLogger("payreality.execution_receipt")


class ExecutionReceiptRejectionError(Exception):
    """A pre-ingestion trust failure -- the receipt is untrustworthy
    before it is ever persisted. Mirrors integration_runtime_service.
    IntegrationRejectionError's own discipline exactly: never partially
    persisted, never a row an attacker's malformed submission could use
    to probe internal state."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class ExecutionReceiptConflictError(Exception):
    """A receipt already exists for this (integration, environment,
    external_operation_id, status) with DIFFERENT material fields -- a
    genuine conflicting claim, not a retry. Never overwrites the existing
    row; see ExecutionReceiptRecord's own docstring for why history here
    is append-only."""

    def __init__(self, external_operation_id: str, status: str):
        self.external_operation_id = external_operation_id
        self.status = status
        super().__init__(
            f"execution receipt already recorded for external_operation_id={external_operation_id!r} "
            f"status={status!r} with different material fields"
        )


def _resolve_owned_binding(db: Session, binding_id: uuid.UUID, organization_id: uuid.UUID, identity_id: uuid.UUID):
    """Mirrors integration_runtime_service._resolve_active_binding's own
    cross-tenant-looks-like-not-found convention, but deliberately does
    NOT require the binding to still be status=='active': a receipt can
    legitimately arrive after a Binding was retired (e.g. the Adapter
    rotated to a new Binding version while the original downstream
    operation was still in flight). What must hold is narrower and
    different from Capability-consumption freshness: that this identity
    genuinely owns this Binding, and (checked by the caller, against the
    Decision's own Intent) that this Binding is the SAME one actually used
    for the Decision this receipt reports on -- not that the Binding is
    still currently usable for new authorizations."""
    try:
        binding = enforcement_binding_service.get_binding(db, binding_id, organization_id)
    except EnforcementBindingNotFoundError:
        raise ExecutionReceiptRejectionError("enforcement_binding_not_found")
    if binding.integration_identity_id != identity_id:
        raise ExecutionReceiptRejectionError("enforcement_binding_not_found")
    return binding


def _resolve_capability_linkage(
    db: Session, binding, decision_id: uuid.UUID, enforcement_binding_id: uuid.UUID, capability_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if capability_id is None:
        if binding.enforcement_assurance == "CAPABILITY_REQUIRED":
            raise ExecutionReceiptRejectionError("capability_required_but_not_supplied")
        return None
    capability = db.get(CapabilityToken, capability_id)
    if capability is None or capability.decision_id != decision_id:
        raise ExecutionReceiptRejectionError("capability_not_found_for_decision")
    if capability.enforcement_binding_id != enforcement_binding_id:
        raise ExecutionReceiptRejectionError("capability_enforcement_binding_mismatch")
    if capability.consumed_at is None:
        raise ExecutionReceiptRejectionError("capability_not_consumed")
    return capability.id


def _check_destination_consistency(
    db: Session, integration_id: uuid.UUID, environment: str, external_operation_id: str, destination: str,
) -> None:
    """Section 5's "destination... linkage" requirement, drawn honestly:
    PayReality has no independently-registered destination to verify
    against (no such registry exists, and inventing one here would be
    exactly the speculative abstraction this milestone is told to avoid).
    What IS checkable, cheaply and honestly, is internal consistency: the
    destination this operation is reported against must not silently
    change between receipts for the same external_operation_id. The
    first-ever receipt for an operation establishes its destination; every
    later receipt for that same operation must agree with it."""
    prior = db.scalar(
        select(ExecutionReceiptRecord)
        .where(
            ExecutionReceiptRecord.integration_id == integration_id,
            ExecutionReceiptRecord.environment == environment,
            ExecutionReceiptRecord.external_operation_id == external_operation_id,
        )
        .order_by(ExecutionReceiptRecord.submitted_at.asc())
        .limit(1)
    )
    if prior is not None and prior.destination != destination:
        raise ExecutionReceiptRejectionError("destination_mismatch")


def _existing_receipt_or_none(
    db: Session, integration_id: uuid.UUID, environment: str, external_operation_id: str, status: str,
) -> ExecutionReceiptRecord | None:
    return db.scalar(
        select(ExecutionReceiptRecord).where(
            ExecutionReceiptRecord.integration_id == integration_id,
            ExecutionReceiptRecord.environment == environment,
            ExecutionReceiptRecord.external_operation_id == external_operation_id,
            ExecutionReceiptRecord.status == status,
        )
    )


def _resolve_existing_or_conflict(
    row: ExecutionReceiptRecord, digest: str, external_operation_id: str, status: str,
) -> ExecutionReceiptRecord:
    if row.receipt_digest == digest:
        logger.info(
            "execution_receipt_result=IDEMPOTENT_RETURN external_operation_id=%s status=%s",
            external_operation_id, status,
        )
        return row
    logger.warning(
        "execution_receipt_result=CONFLICT external_operation_id=%s status=%s",
        external_operation_id, status,
    )
    raise ExecutionReceiptConflictError(external_operation_id, status)


def submit_execution_receipt(
    db: Session,
    identity: IntegrationIdentity,
    *,
    enforcement_binding_id: uuid.UUID,
    decision_id: uuid.UUID,
    canonical_action_digest: str,
    external_operation_id: str,
    destination: str,
    status: str,
    capability_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
    detail: str | None = None,
) -> ExecutionReceiptRecord:
    if identity.status != "active":
        raise ExecutionReceiptRejectionError(f"integration_identity_not_active:{identity.status}")

    organization_id = identity.organization_id
    organization = db.get(Organization, organization_id)
    if organization is not None:
        try:
            organization_lifecycle_service.ensure_active(organization)
        except organization_lifecycle_service.OrganizationNotActiveError as e:
            raise ExecutionReceiptRejectionError(f"organization_not_active:{e.status}")

    binding = _resolve_owned_binding(db, enforcement_binding_id, organization_id, identity.id)

    try:
        decision = intent_service.get_decision_for_organization(db, decision_id, organization_id)
    except (DecisionNotFoundError, CrossOrganizationAccessError):
        raise ExecutionReceiptRejectionError("decision_not_found")

    intent = db.get(intent_service.Intent, decision.intent_id)

    # Linkage checks (section 5): the receipt must be reporting on the
    # exact same identity/binding/action/operation the Decision's own
    # Intent actually recorded -- never merely a plausible-looking set of
    # ids an attacker (or a confused Adapter) supplied independently.
    if intent.integration_identity_id != identity.id:
        raise ExecutionReceiptRejectionError("identity_not_bound_to_decision")
    if intent.enforcement_binding_id != enforcement_binding_id:
        raise ExecutionReceiptRejectionError("enforcement_binding_not_bound_to_decision")
    if intent.canonical_action_digest != canonical_action_digest:
        raise ExecutionReceiptRejectionError("canonical_action_digest_mismatch")
    if intent.external_operation_id != external_operation_id:
        raise ExecutionReceiptRejectionError("external_operation_id_mismatch")

    resolved_capability_id = _resolve_capability_linkage(
        db, binding, decision_id, enforcement_binding_id, capability_id,
    )

    integration_id = intent.integration_id
    environment = intent.environment
    _check_destination_consistency(db, integration_id, environment, external_operation_id, destination)

    submitted_at = datetime.now(timezone.utc)
    receipt = build_execution_receipt(
        organization_id=organization_id,
        integration_identity_id=identity.id,
        enforcement_binding_id=enforcement_binding_id,
        decision_id=decision_id,
        canonical_action_digest=canonical_action_digest,
        external_operation_id=external_operation_id,
        destination=destination,
        status=status,
        submitted_at=submitted_at,
        capability_id=resolved_capability_id,
        occurred_at=occurred_at,
        detail=detail,
    )
    digest = receipt.receipt_digest()

    existing = _existing_receipt_or_none(db, integration_id, environment, external_operation_id, status)
    if existing is not None:
        return _resolve_existing_or_conflict(existing, digest, external_operation_id, status)

    evidence = intent_service.append_generic_evidence_event(
        db, organization_id, decision_id, "EXECUTION_RECEIPT_ACCEPTED",
        {
            "integration_identity_id": str(identity.id),
            "enforcement_binding_id": str(enforcement_binding_id),
            "capability_id": str(resolved_capability_id) if resolved_capability_id else None,
            "canonical_action_digest": canonical_action_digest,
            "external_operation_id": external_operation_id,
            "destination": destination,
            "status": status,
            "receipt_digest": digest,
        },
    )

    row = ExecutionReceiptRecord(
        organization_id=organization_id,
        integration_identity_id=identity.id,
        enforcement_binding_id=enforcement_binding_id,
        integration_id=integration_id,
        environment=environment,
        decision_id=decision_id,
        capability_id=resolved_capability_id,
        canonical_action_digest=canonical_action_digest,
        external_operation_id=external_operation_id,
        destination=destination,
        status=status,
        receipt_digest=digest,
        occurred_at=occurred_at,
        detail=detail,
        submitted_at=submitted_at,
        evidence_id=evidence.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raced = _existing_receipt_or_none(db, integration_id, environment, external_operation_id, status)
        if raced is not None:
            return _resolve_existing_or_conflict(raced, digest, external_operation_id, status)
        raise  # pragma: no cover -- a UNIQUE violation with no row to explain it is unexpected
    db.refresh(row)
    logger.info(
        "execution_receipt_result=ACCEPTED external_operation_id=%s status=%s decision_id=%s",
        external_operation_id, status, decision_id,
    )
    return row
