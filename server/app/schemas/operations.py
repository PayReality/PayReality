from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class OperationResponse(BaseModel):
    operation_id: UUID
    decision_id: UUID
    capability_id: UUID | None
    material_action_digest: str
    destination: str | None
    destination_operation_id: str | None
    state: str
    attempt_count: int
    created_at: datetime
    updated_at: datetime


class RecordDispatchEvidenceRequest(BaseModel):
    """The executor's own report that it sent the destination request --
    distinct from an observation (what the destination said back)."""

    integration_identity_id: UUID | None = None
    destination: str | None = None
    destination_operation_id: str | None = None


class RecordObservationRequest(BaseModel):
    """The narrowly scoped observation path's own request shape.
    `integration_identity_id` names which already-registered Trusted
    Adapter identity this observation is reported on behalf of -- the
    caller's own RBAC permission (Permission.OPERATION_OBSERVE) gates
    WHO may relay an observation; that identity's own active status
    (checked by execution_receipt_service, unchanged) gates whether the
    observation itself is still recordable at all, exactly the same
    "observation authority" check every other receipt path already
    uses, not a second, separate one."""

    integration_identity_id: UUID
    enforcement_binding_id: UUID
    material_action_digest: str
    canonical_action_digest: str
    destination: str
    status: str
    capability_id: UUID | None = None
    occurred_at: datetime | None = None
    detail: str | None = None


class RecordObservationResponse(BaseModel):
    operation: OperationResponse
    receipt_id: UUID
    reconciliation_outcome: str


class ReplacementSafetyResponse(BaseModel):
    safety: str
    reason: str
    requires_current_authorization: bool


class RecordDuplicatePreventionGuaranteeRequest(BaseModel):
    destination: str
    scope_description: str
    retention_until: datetime
    documented_by: str
    restricted_to_integration_identity_id: UUID | None = None
    restricted_to_enforcement_binding_id: UUID | None = None


class DuplicatePreventionGuaranteeResponse(BaseModel):
    operation_id: UUID
    destination: str
    scope_description: str
    retention_until: datetime
    documented_by: str
    documented_at: datetime
    restricted_to_integration_identity_id: UUID | None
    restricted_to_enforcement_binding_id: UUID | None
