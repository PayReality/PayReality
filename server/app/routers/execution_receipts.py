from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import IntegrationIdentity
from app.db.session import get_db
from app.dependencies import verify_integration_identity_signature
from app.schemas.execution_receipt import ExecutionReceiptResponse, SubmitExecutionReceiptRequest
from app.services import execution_receipt_service
from app.services.execution_receipt_service import (
    ExecutionReceiptConflictError,
    ExecutionReceiptRejectionError,
)

router = APIRouter(prefix="/v1", tags=["execution-receipts"])


@router.post("/execution-receipts", response_model=ExecutionReceiptResponse)
def submit_execution_receipt(
    body: SubmitExecutionReceiptRequest,
    identity: IntegrationIdentity = Depends(verify_integration_identity_signature),
    db: Session = Depends(get_db),
):
    """Post-audit implementation, Priority 5: the trusted-Adapter-only
    execution-receipt ingestion endpoint. Authenticated exactly like
    POST /v1/integration-runtime/intents (an active IntegrationIdentity
    certificate signing the raw request body) -- no separate credential
    type, no Operator Key, no session/API-key path accepted here."""
    try:
        row = execution_receipt_service.submit_execution_receipt(
            db,
            identity,
            enforcement_binding_id=body.enforcement_binding_id,
            decision_id=body.decision_id,
            canonical_action_digest=body.canonical_action_digest,
            external_operation_id=body.external_operation_id,
            destination=body.destination,
            status=body.status,
            capability_id=body.capability_id,
            occurred_at=body.occurred_at,
            detail=body.detail,
        )
    except ExecutionReceiptRejectionError as e:
        raise HTTPException(status_code=422, detail=f"execution_receipt_rejection:{e.reason}")
    except ExecutionReceiptConflictError:
        raise HTTPException(status_code=409, detail="execution_receipt_conflict")

    return ExecutionReceiptResponse(
        receipt_id=row.id,
        decision_id=row.decision_id,
        external_operation_id=row.external_operation_id,
        status=row.status,
        submitted_at=row.submitted_at,
        evidence_id=row.evidence_id,
    )
