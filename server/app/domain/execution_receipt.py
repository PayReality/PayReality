"""Post-audit implementation, Priority 5: the generic execution-receipt
model -- the smallest structure that lets a trusted Adapter report what
actually happened when it attempted the external operation an Intent's
Capability (or, for an ADVISORY-assurance Binding, its Decision alone)
authorized.

Deliberately generic, not workflow-specific: no reconciliation rules live
here (that is Priority 6, app/services/execution_reconciliation_service.py),
and this module has no knowledge of what any specific canonical action
means. It only defines what a receipt IS and how two receipts are compared
for idempotency -- mirrors app/domain/canonical_action.py's own material/
non-material field split and canonical-JSON digest approach, reusing
app.domain.evidence.signing.canonicalize/payload_hash rather than
re-implementing canonicalization a second way.

Trust statement, unchanged (do not overclaim beyond this): a receipt is an
authenticated Adapter's own claim about what happened downstream.
PayReality did not independently observe the external system itself -- see
INTEGRATION_KIT.md's own Trust Statement and DECLARED_VS_OBSERVED_
RECONCILIATION.md for the single-attester limitation this receipt model
does not change or extend.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.domain.evidence.signing import payload_hash

EXECUTION_RECEIPT_SCHEMA_VERSION = 1
_SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

# Priority 5's own required state set -- exactly these five, no
# workflow-specific states (e.g. no "AWAITING_DOWNSTREAM_APPROVAL").
EXECUTION_RECEIPT_STATUSES = frozenset(
    {"ACCEPTED", "SUCCEEDED", "FAILED", "PARTIALLY_SUCCEEDED", "UNKNOWN"}
)


class UnsupportedExecutionReceiptSchemaVersionError(Exception):
    def __init__(self, schema_version: Any):
        self.schema_version = schema_version
        super().__init__(f"unsupported execution receipt schema_version={schema_version!r}")


class InvalidExecutionReceiptStatusError(Exception):
    def __init__(self, status: Any):
        self.status = status
        super().__init__(f"invalid execution receipt status={status!r}")


class MissingRequiredExecutionReceiptFieldError(Exception):
    def __init__(self, field_name: str):
        self.field_name = field_name
        super().__init__(f"missing required execution receipt field: {field_name}")


_REQUIRED_FIELDS = (
    "organization_id", "integration_identity_id", "enforcement_binding_id",
    "decision_id", "canonical_action_digest", "external_operation_id", "destination",
)


@dataclass(frozen=True)
class ExecutionReceipt:
    """One immutable claim: "as of occurred_at, this external operation was
    in this state." A state transition (e.g. ACCEPTED -> SUCCEEDED) is a
    SEPARATE ExecutionReceipt, never an edit of a prior one -- see this
    module's own docstring and execution_receipt_service.py's ingestion
    rules for why history here is append-only.

    Material fields (participate in receipt_digest(), material_fields()):
    everything that identifies WHICH claim this is -- organization,
    identity, binding, decision, capability (if any), canonical action,
    external operation, destination, status. `detail` (free-text, e.g. an
    error message) and `occurred_at` are deliberately excluded: two
    receipts reporting the same status for the same operation are the
    same claim even if their free-text detail differs slightly or their
    declared occurred_at timestamp has sub-second jitter -- see
    execution_receipt_service.py's own idempotency-vs-conflict reasoning
    for exactly how this digest is used."""

    schema_version: int
    organization_id: uuid.UUID
    integration_identity_id: uuid.UUID
    enforcement_binding_id: uuid.UUID
    decision_id: uuid.UUID
    canonical_action_digest: str
    external_operation_id: str
    destination: str
    status: str
    submitted_at: datetime
    capability_id: uuid.UUID | None = None
    occurred_at: datetime | None = None
    detail: str | None = None

    def material_fields(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "organization_id": str(self.organization_id),
            "integration_identity_id": str(self.integration_identity_id),
            "enforcement_binding_id": str(self.enforcement_binding_id),
            "decision_id": str(self.decision_id),
            "capability_id": str(self.capability_id) if self.capability_id else None,
            "canonical_action_digest": self.canonical_action_digest,
            "external_operation_id": self.external_operation_id,
            "destination": self.destination,
            "status": self.status,
        }

    def receipt_digest(self) -> str:
        """Deterministic canonical-JSON SHA-256 over material_fields(),
        reusing app.domain.evidence.signing's own canonicalize/hash
        approach so this repository has one canonicalization convention,
        not two. Two receipts with identical material fields always
        produce identical digests regardless of construction order or
        which non-material fields (occurred_at, detail) differ."""
        return payload_hash(self.material_fields())


def build_execution_receipt(
    *,
    organization_id: uuid.UUID,
    integration_identity_id: uuid.UUID,
    enforcement_binding_id: uuid.UUID,
    decision_id: uuid.UUID,
    canonical_action_digest: str,
    external_operation_id: str,
    destination: str,
    status: str,
    submitted_at: datetime,
    capability_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
    detail: str | None = None,
    schema_version: int = EXECUTION_RECEIPT_SCHEMA_VERSION,
) -> ExecutionReceipt:
    """The one constructor this module exposes -- fails closed on an
    unsupported schema_version, an unrecognized status, or a missing
    required field, rather than silently building a receipt whose digest
    can never be meaningfully compared against anything. Does not perform
    any DB-dependent trust check (identity/binding/tenant/capability/
    linkage) -- those live in execution_receipt_service.py, which is the
    only caller permitted to construct a receipt from untrusted input."""
    if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedExecutionReceiptSchemaVersionError(schema_version)
    if status not in EXECUTION_RECEIPT_STATUSES:
        raise InvalidExecutionReceiptStatusError(status)

    required = {
        "organization_id": organization_id,
        "integration_identity_id": integration_identity_id,
        "enforcement_binding_id": enforcement_binding_id,
        "decision_id": decision_id,
        "canonical_action_digest": canonical_action_digest,
        "external_operation_id": external_operation_id,
        "destination": destination,
    }
    for name, value in required.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            raise MissingRequiredExecutionReceiptFieldError(name)

    if submitted_at.tzinfo is None:
        submitted_at = submitted_at.replace(tzinfo=timezone.utc)
    if occurred_at is not None and occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)

    return ExecutionReceipt(
        schema_version=schema_version,
        organization_id=organization_id,
        integration_identity_id=integration_identity_id,
        enforcement_binding_id=enforcement_binding_id,
        decision_id=decision_id,
        capability_id=capability_id,
        canonical_action_digest=canonical_action_digest,
        external_operation_id=external_operation_id,
        destination=destination,
        status=status,
        submitted_at=submitted_at,
        occurred_at=occurred_at,
        detail=detail,
    )
