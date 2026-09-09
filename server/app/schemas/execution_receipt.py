from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SubmitExecutionReceiptRequest(BaseModel):
    """Post-audit implementation, Priority 5: the Adapter-signed request
    shape for reporting the outcome of one previously-decided, previously
    (if CAPABILITY_REQUIRED) Capability-consumed action. Every field here
    is bound by the same signature that authenticates this request --
    the whole raw body is what verify_integration_identity_signature
    verifies, not a reconstructed subset of it."""

    enforcement_binding_id: UUID
    decision_id: UUID
    canonical_action_digest: str
    external_operation_id: str
    destination: str
    status: str
    capability_id: UUID | None = None
    occurred_at: datetime | None = None
    detail: str | None = None


class ExecutionReceiptResponse(BaseModel):
    receipt_id: UUID
    decision_id: UUID
    external_operation_id: str
    status: str
    submitted_at: datetime
    evidence_id: UUID | None = None
