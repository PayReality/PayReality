from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IntegrationIdentity, Operation, Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, get_current_user_if_session, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.operations import (
    DuplicatePreventionGuaranteeResponse,
    OperationResponse,
    RecordDispatchEvidenceRequest,
    RecordDuplicatePreventionGuaranteeRequest,
    RecordManualAdjudicationRequest,
    RecordObservationRequest,
    RecordObservationResponse,
    ReplacementSafetyResponse,
)
from app.services import operation_service
from app.services.execution_receipt_service import ExecutionReceiptConflictError, ExecutionReceiptRejectionError

router = APIRouter(prefix="/v1", tags=["operations"])


def _reported_by(user, identity: IntegrationIdentity | None) -> str:
    """"Actual authenticated reporter" (section 5's own phrase): the
    real human's own identity when a session token was used (Authority-
    as-a-continuous-object, Stage D -- app.dependencies.
    get_current_user_if_session, the same established pattern this
    codebase already uses elsewhere for exactly this purpose), with an
    explicit free-text fallback naming the credential class when it
    wasn't (an API key or the platform Operator Key, neither of which
    resolves to one person) -- never silently attributed to the
    IntegrationIdentity being reported ABOUT, which is a different
    thing being claimed on, not the claimant."""
    if user is not None:
        return f"user:{user.email}"
    if identity is not None:
        return f"non-session-credential (on behalf of integration_identity={identity.id})"
    return "non-session-credential"


def _to_response(operation: Operation) -> OperationResponse:
    return OperationResponse(
        operation_id=operation.id, decision_id=operation.decision_id, capability_id=operation.capability_id,
        material_action_digest=operation.material_action_digest, destination=operation.destination,
        destination_operation_id=operation.destination_operation_id,
        execution_stage=operation.execution_stage, outcome_status=operation.outcome_status,
        evidence_assurance=operation.evidence_assurance,
        business_operation_identity_id=operation.business_operation_identity_id,
        previous_attempt_operation_id=operation.previous_attempt_operation_id,
        attempt_count=operation.attempt_count, created_at=operation.created_at, updated_at=operation.updated_at,
    )


@router.get(
    "/operations/{operation_id}", response_model=OperationResponse,
    dependencies=[Depends(require_permission(Permission.OPERATION_OBSERVE))],
)
def get_operation(
    operation_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Read-only. This route, and the ones below, are what makes
    reconciled operation state reachable through an authenticated API
    boundary at all -- previously, execution_reconciliation_service had
    zero router call sites anywhere in this codebase."""
    try:
        operation = operation_service._get_operation_for_organization(db, organization.id, operation_id)
    except operation_service.OperationNotFoundError:
        raise HTTPException(status_code=404, detail="operation_not_found")
    return _to_response(operation)


@router.get(
    "/decisions/{decision_id}/operation", response_model=OperationResponse,
    dependencies=[Depends(require_permission(Permission.OPERATION_OBSERVE))],
)
def get_operation_for_decision(
    decision_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Lookup convenience for a caller that has a decision_id (e.g. from
    the Runtime API's own POST /v1/intents response) but not yet the
    Operation's own id."""
    operation = db.scalar(select(Operation).where(Operation.decision_id == decision_id, Operation.organization_id == organization.id))
    if operation is None:
        raise HTTPException(status_code=404, detail="operation_not_found")
    return _to_response(operation)


@router.post(
    "/operations/{operation_id}/dispatch-evidence", response_model=OperationResponse,
    dependencies=[Depends(require_permission(Permission.OPERATION_OBSERVE))],
)
def record_dispatch_evidence(
    operation_id: UUID,
    body: RecordDispatchEvidenceRequest,
    organization: Organization = Depends(get_current_organization),
    user=Depends(get_current_user_if_session),
    db: Session = Depends(get_db),
):
    """The executor's own explicit report that it sent the destination
    request -- distinct from claiming the Capability (which only proves
    the attempt was authorized) and from an observation (what the
    destination said back, if anything). Same RBAC-human trust-boundary
    disclosure as the observations route below: this is an unsigned
    relay, gated by the caller's own session/API-key credential, not a
    verified signature from the named identity."""
    identity = None
    if body.integration_identity_id is not None:
        identity = db.get(IntegrationIdentity, body.integration_identity_id)
        if identity is None or identity.organization_id != organization.id:
            raise HTTPException(status_code=404, detail="integration_identity_not_found")
    try:
        operation = operation_service.record_dispatch_evidence(
            db, organization.id, operation_id,
            reporter_kind=operation_service.REPORTER_RBAC_HUMAN, signature_verified=False,
            reported_by=_reported_by(user, identity),
            integration_identity_id=body.integration_identity_id,
            destination=body.destination, destination_operation_id=body.destination_operation_id,
        )
    except operation_service.OperationNotFoundError:
        raise HTTPException(status_code=404, detail="operation_not_found")
    except operation_service.OperationNotClaimedError as e:
        raise HTTPException(status_code=409, detail=f"operation_not_claimed: execution_stage={e.execution_stage}")
    return _to_response(operation)


@router.post(
    "/operations/{operation_id}/observations", response_model=RecordObservationResponse,
    dependencies=[Depends(require_permission(Permission.OPERATION_OBSERVE))],
)
def record_observation(
    operation_id: UUID,
    body: RecordObservationRequest,
    organization: Organization = Depends(get_current_organization),
    user=Depends(get_current_user_if_session),
    db: Session = Depends(get_db),
):
    """The narrowly scoped observation path. Trust-boundary disclosure,
    stated here rather than left implicit: this route is gated by the
    CALLER's own RBAC credential (Permission.OPERATION_OBSERVE, held by
    Reviewer and Governance Administrator) -- unlike POST /v1/execution-
    receipts, it does NOT independently verify that the caller possesses
    the named integration_identity_id's own signing key. Every event
    this route writes is persisted with reporter_kind=RBAC_HUMAN and
    signature_verified=False, permanently and mechanically (operation_
    service._evidence_strength) -- an authenticated human may relay a
    report, but never inherits the Adapter's own signature assurance,
    and the record never lets a reader mistake one for the other. The
    identity named still has to be a real, currently-active
    IntegrationIdentity in THIS organization -- that check happens
    inside execution_receipt_service.submit_execution_receipt, unchanged,
    and is what actually enforces "if observation authority is revoked,
    this fails.\""""
    identity = db.get(IntegrationIdentity, body.integration_identity_id)
    if identity is None or identity.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="integration_identity_not_found")

    try:
        operation, receipt, result = operation_service.record_observation(
            db, organization.id, operation_id, identity,
            reporter_kind=operation_service.REPORTER_RBAC_HUMAN, signature_verified=False,
            reported_by=_reported_by(user, identity),
            enforcement_binding_id=body.enforcement_binding_id,
            material_action_digest=body.material_action_digest,
            canonical_action_digest=body.canonical_action_digest,
            destination=body.destination, status=body.status, capability_id=body.capability_id,
            occurred_at=body.occurred_at, detail=body.detail,
        )
    except operation_service.OperationNotFoundError:
        raise HTTPException(status_code=404, detail="operation_not_found")
    except operation_service.OperationNotClaimedError as e:
        raise HTTPException(status_code=409, detail=f"operation_not_claimed: execution_stage={e.execution_stage}")
    except operation_service.MaterialActionMismatchError as e:
        raise HTTPException(status_code=409, detail=f"material_action_mismatch: expected={e.expected} received={e.received}")
    except ExecutionReceiptRejectionError as e:
        raise HTTPException(status_code=422, detail=f"execution_receipt_rejection:{e}")
    except ExecutionReceiptConflictError:
        raise HTTPException(status_code=409, detail="execution_receipt_conflict")
    except operation_service.OperationRecordingFailedError as e:
        raise HTTPException(status_code=500, detail=f"operation_recording_failed: {e.reason}")

    return RecordObservationResponse(operation=_to_response(operation), receipt_id=receipt.id, reconciliation_outcome=result.outcome)


@router.get(
    "/operations/{operation_id}/replacement-safety", response_model=ReplacementSafetyResponse,
    dependencies=[Depends(require_permission(Permission.OPERATION_OBSERVE))],
)
def get_replacement_safety(
    operation_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Advisory only -- the real enforcement point is capability_service.
    issue_capability_for_decision's own optional replaces_operation_id
    parameter, which calls this same evaluate_replacement_safety and
    actually refuses issuance when the result isn't SAFE_*. This route
    exists so a caller can check before attempting, not because checking
    here does anything on its own. Answers SAFETY only -- never
    authority."""
    try:
        result = operation_service.evaluate_replacement_safety(db, organization.id, operation_id)
    except operation_service.OperationNotFoundError:
        raise HTTPException(status_code=404, detail="operation_not_found")
    return ReplacementSafetyResponse(safety=result.safety, reason=result.reason, requires_current_authorization=result.requires_current_authorization)


@router.post(
    "/operations/{operation_id}/duplicate-prevention-guarantees", response_model=DuplicatePreventionGuaranteeResponse,
    dependencies=[Depends(require_permission(Permission.OPERATION_SAFETY_APPROVE))],
)
def record_duplicate_prevention_guarantee(
    operation_id: UUID,
    body: RecordDuplicatePreventionGuaranteeRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Gated by Permission.OPERATION_SAFETY_APPROVE, deliberately NOT
    OPERATION_OBSERVE (section 4: "an observer cannot grant themselves
    replacement safety") -- Reviewer holds the latter and not the
    former; only Governance Administrator (and Owner) holds this one. A
    human-documented fact, never auto-inferred -- see operation_service.
    record_destination_duplicate_prevention_guarantee's own docstring
    and DestinationDuplicatePreventionGuarantee's model docstring
    (app/db/models.py) for why scope and retention are both required,
    non-optional inputs, and why restricted_to_* lets a guarantee bind
    to the exact identity/binding it actually protects."""
    try:
        guarantee = operation_service.record_destination_duplicate_prevention_guarantee(
            db, organization.id, operation_id, destination=body.destination,
            scope_description=body.scope_description, retention_until=body.retention_until,
            documented_by=body.documented_by,
            restricted_to_integration_identity_id=body.restricted_to_integration_identity_id,
            restricted_to_enforcement_binding_id=body.restricted_to_enforcement_binding_id,
        )
    except operation_service.OperationNotFoundError:
        raise HTTPException(status_code=404, detail="operation_not_found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return DuplicatePreventionGuaranteeResponse(
        operation_id=guarantee.operation_id, destination=guarantee.destination,
        scope_description=guarantee.scope_description, retention_until=guarantee.retention_until,
        documented_by=guarantee.documented_by, documented_at=guarantee.documented_at,
        restricted_to_integration_identity_id=guarantee.restricted_to_integration_identity_id,
        restricted_to_enforcement_binding_id=guarantee.restricted_to_enforcement_binding_id,
    )


@router.post(
    "/operations/{operation_id}/manual-adjudication", response_model=OperationResponse,
    dependencies=[Depends(require_permission(Permission.OPERATION_MANUAL_ADJUDICATE))],
)
def record_manual_adjudication(
    operation_id: UUID,
    body: RecordManualAdjudicationRequest,
    organization: Organization = Depends(get_current_organization),
    user=Depends(get_current_user_if_session),
    db: Session = Depends(get_db),
):
    """Closeout pass, section 2: gated by Permission.OPERATION_MANUAL_
    ADJUDICATE, a THIRD permission distinct from both OPERATION_OBSERVE
    (Reviewer) and OPERATION_SAFETY_APPROVE -- granted to Governance
    Administrator alone. This is the one path by which an unsigned
    RBAC_HUMAN relay's own claim can ever be turned into a terminal
    outcome_status -- and it never happens implicitly: it requires this
    separate credential, a non-empty rationale, and at least one real
    reference into this operation's own evidence log, all recorded
    permanently on the resulting event (operation_service.record_manual_
    adjudication)."""
    try:
        operation = operation_service.record_manual_adjudication(
            db, organization.id, operation_id,
            adjudicated_by=_reported_by(user, None), outcome_status=body.outcome_status,
            rationale=body.rationale, evidence_reference_ids=body.evidence_reference_ids,
        )
    except operation_service.OperationNotFoundError:
        raise HTTPException(status_code=404, detail="operation_not_found")
    except operation_service.InvalidManualAdjudicationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _to_response(operation)
