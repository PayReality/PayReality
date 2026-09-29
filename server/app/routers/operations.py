from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IntegrationIdentity, Operation, Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.operations import (
    DuplicatePreventionGuaranteeResponse,
    OperationResponse,
    RecordDuplicatePreventionGuaranteeRequest,
    RecordObservationRequest,
    RecordObservationResponse,
    ReplacementSafetyResponse,
)
from app.services import operation_service
from app.services.execution_receipt_service import ExecutionReceiptConflictError, ExecutionReceiptRejectionError

router = APIRouter(prefix="/v1", tags=["operations"])


def _to_response(operation: Operation) -> OperationResponse:
    return OperationResponse(
        operation_id=operation.id, decision_id=operation.decision_id, capability_id=operation.capability_id,
        material_action_digest=operation.material_action_digest, destination=operation.destination,
        destination_operation_id=operation.destination_operation_id, state=operation.state,
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
    zero router call sites anywhere in this codebase (re-confirmed
    directly before writing this file, not assumed)."""
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
    "/operations/{operation_id}/observations", response_model=RecordObservationResponse,
    dependencies=[Depends(require_permission(Permission.OPERATION_OBSERVE))],
)
def record_observation(
    operation_id: UUID,
    body: RecordObservationRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """The narrowly scoped observation path (section 7 of the product
    contract this route implements). Trust-boundary disclosure, stated
    here rather than left implicit: this route is gated by the CALLER's
    own RBAC credential (Permission.OPERATION_OBSERVE, e.g. an Auditor's
    session or API key) -- unlike POST /v1/execution-receipts, it does
    NOT independently verify that the caller possesses the named
    integration_identity_id's own signing key. This is a deliberately
    different, weaker-on-that-one-axis trust model for a human recovery
    path relaying an observation obtained out-of-band, not the
    Adapter's own automated, signature-authenticated channel (which
    remains POST /v1/execution-receipts, unchanged, and is the stronger
    path a real integration should prefer whenever the Adapter itself
    can report directly). The identity named still has to be a real,
    currently-active IntegrationIdentity in THIS organization -- that
    check happens inside execution_receipt_service.submit_execution_
    receipt, unchanged, and is what actually enforces "if observation
    authority is revoked, this fails" (see that check's own precedence:
    it is the very first thing checked, before anything else)."""
    identity = db.get(IntegrationIdentity, body.integration_identity_id)
    if identity is None or identity.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="integration_identity_not_found")

    try:
        operation, receipt, result = operation_service.record_observation(
            db, organization.id, operation_id, identity,
            enforcement_binding_id=body.enforcement_binding_id,
            material_action_digest=body.material_action_digest,
            canonical_action_digest=body.canonical_action_digest,
            destination=body.destination, status=body.status, capability_id=body.capability_id,
            occurred_at=body.occurred_at, detail=body.detail,
        )
    except operation_service.OperationNotFoundError:
        raise HTTPException(status_code=404, detail="operation_not_found")
    except operation_service.MaterialActionMismatchError as e:
        raise HTTPException(status_code=409, detail=f"material_action_mismatch: expected={e.expected} received={e.received}")
    except ExecutionReceiptRejectionError as e:
        raise HTTPException(status_code=422, detail=f"execution_receipt_rejection:{e}")
    except ExecutionReceiptConflictError:
        raise HTTPException(status_code=409, detail="execution_receipt_conflict")

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
    """Answers SAFETY only -- never authority. See operation_service.
    evaluate_replacement_safety's own docstring: authority to attempt a
    replacement is answered by submitting a new Intent and seeing
    whether it evaluates to ALLOW, a wholly separate call this route
    never makes."""
    try:
        result = operation_service.evaluate_replacement_safety(db, organization.id, operation_id)
    except operation_service.OperationNotFoundError:
        raise HTTPException(status_code=404, detail="operation_not_found")
    return ReplacementSafetyResponse(safety=result.safety, reason=result.reason)


@router.post(
    "/operations/{operation_id}/duplicate-prevention-guarantees", response_model=DuplicatePreventionGuaranteeResponse,
    dependencies=[Depends(require_permission(Permission.OPERATION_OBSERVE))],
)
def record_duplicate_prevention_guarantee(
    operation_id: UUID,
    body: RecordDuplicatePreventionGuaranteeRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """A human-documented fact, never auto-inferred -- see
    operation_service.record_destination_duplicate_prevention_guarantee's
    own docstring and DestinationDuplicatePreventionGuarantee's model
    docstring (app/db/models.py) for why scope and retention are both
    required, non-optional inputs here."""
    try:
        guarantee = operation_service.record_destination_duplicate_prevention_guarantee(
            db, organization.id, operation_id, destination=body.destination,
            scope_description=body.scope_description, retention_until=body.retention_until,
            documented_by=body.documented_by,
        )
    except operation_service.OperationNotFoundError:
        raise HTTPException(status_code=404, detail="operation_not_found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return DuplicatePreventionGuaranteeResponse(
        operation_id=guarantee.operation_id, destination=guarantee.destination,
        scope_description=guarantee.scope_description, retention_until=guarantee.retention_until,
        documented_by=guarantee.documented_by, documented_at=guarantee.documented_at,
    )
