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
    # Closeout pass, section 3: execution stage (what has been evidenced
    # about the attempt itself) and outcome certainty (what is known
    # about the destination outcome) are independent facts, not one
    # collapsed `state` string -- execution_stage=CLAIMED and
    # outcome_status=UNKNOWN is a valid, common, and meaningfully
    # different combination from execution_stage=DISPATCHED and
    # outcome_status=UNKNOWN. See Operation's own docstring
    # (app/db/models.py) for the full vocabulary.
    execution_stage: str
    outcome_status: str
    # Closeout pass, section 2: what KIND of evidence outcome_status
    # currently rests on -- NONE/REPORTED_UNVERIFIED/ADAPTER_REPORTED/
    # MANUAL_ADJUDICATED. An unsigned human relay alone can only ever
    # produce REPORTED_UNVERIFIED with outcome_status still UNKNOWN.
    evidence_assurance: str
    # Closeout pass, section 1: present only for a business-operation-
    # identity-covered Operation (None otherwise, exactly today's
    # default for a non-identity-covered one).
    business_operation_identity_id: UUID | None
    previous_attempt_operation_id: UUID | None
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


class RecordManualAdjudicationRequest(BaseModel):
    """Closeout pass, section 2: a governance override, never a report
    of an external fact -- always carries a rationale and at least one
    reference into this Operation's own evidence log. `adjudicated_by`
    is resolved server-side from the caller's own authenticated session
    (routers/operations.py's _reported_by), never accepted as a request
    field -- the same "actual authenticated reporter" discipline every
    other provenance field in this router already follows."""

    outcome_status: str
    rationale: str
    evidence_reference_ids: list[UUID]
