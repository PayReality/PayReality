"""Post-audit implementation, Priority 5: app/domain/execution_receipt.py
is a pure domain module (no DB) -- unit-tested directly here, matching
test_canonical_action.py's own "unit-test the pure logic, integration-test
the wiring" split. The through-the-real-path proof (a real receipt actually
persisted, trust checks enforced, idempotency/conflict resolved against a
real DB) lives in tests/integration/test_execution_receipts.py instead.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.domain.execution_receipt import (
    EXECUTION_RECEIPT_SCHEMA_VERSION,
    InvalidExecutionReceiptStatusError,
    MissingRequiredExecutionReceiptFieldError,
    UnsupportedExecutionReceiptSchemaVersionError,
    build_execution_receipt,
)

ORG = uuid.uuid4()
IDENTITY = uuid.uuid4()
BINDING = uuid.uuid4()
DECISION = uuid.uuid4()


def _build(**overrides):
    defaults = dict(
        organization_id=ORG,
        integration_identity_id=IDENTITY,
        enforcement_binding_id=BINDING,
        decision_id=DECISION,
        canonical_action_digest="digest-abc",
        external_operation_id="ext-op-1",
        destination="erp:vendor_master",
        status="ACCEPTED",
        submitted_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return build_execution_receipt(**defaults)


# === Deterministic digest ====================================================


def test_receipt_digest_is_deterministic_for_the_same_inputs():
    a = _build()
    b = _build()
    assert a.receipt_digest() == b.receipt_digest()


def test_same_claim_produces_the_same_digest_regardless_of_non_material_fields():
    a = _build(occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc), detail=None)
    b = _build(
        occurred_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        detail="settled in batch run #482",
    )
    assert a.receipt_digest() == b.receipt_digest(), "occurred_at and detail are non-material"


# === Material-field changes produce a different digest ======================


@pytest.mark.parametrize(
    "field,value",
    [
        ("organization_id", uuid.uuid4()),
        ("integration_identity_id", uuid.uuid4()),
        ("enforcement_binding_id", uuid.uuid4()),
        ("decision_id", uuid.uuid4()),
        ("canonical_action_digest", "digest-xyz"),
        ("external_operation_id", "ext-op-2"),
        ("destination", "erp:general_ledger"),
        ("status", "SUCCEEDED"),
        ("capability_id", uuid.uuid4()),
    ],
)
def test_changing_a_material_field_changes_the_digest(field, value):
    a = _build()
    b = _build(**{field: value})
    assert a.receipt_digest() != b.receipt_digest()


# === Status validation ========================================================


@pytest.mark.parametrize("status", ["ACCEPTED", "SUCCEEDED", "FAILED", "PARTIALLY_SUCCEEDED", "UNKNOWN"])
def test_every_defined_status_is_accepted(status):
    receipt = _build(status=status)
    assert receipt.status == status


def test_an_undefined_status_is_rejected():
    with pytest.raises(InvalidExecutionReceiptStatusError):
        _build(status="AWAITING_DOWNSTREAM_APPROVAL")


# === Schema version ===========================================================


def test_default_schema_version_matches_the_module_constant():
    assert _build().schema_version == EXECUTION_RECEIPT_SCHEMA_VERSION


def test_an_unsupported_schema_version_is_rejected():
    with pytest.raises(UnsupportedExecutionReceiptSchemaVersionError):
        _build(schema_version=999)


# === Required-field validation =================================================


@pytest.mark.parametrize(
    "field",
    [
        "organization_id", "integration_identity_id", "enforcement_binding_id",
        "decision_id", "canonical_action_digest", "external_operation_id", "destination",
    ],
)
def test_a_missing_required_field_is_rejected(field):
    with pytest.raises(MissingRequiredExecutionReceiptFieldError):
        _build(**{field: None})


def test_an_empty_string_required_field_is_rejected():
    with pytest.raises(MissingRequiredExecutionReceiptFieldError):
        _build(destination="   ")


# === Naive datetime normalization =============================================


def test_naive_submitted_at_is_normalized_to_utc():
    receipt = _build(submitted_at=datetime(2026, 1, 1, 12, 0, 0))
    assert receipt.submitted_at.tzinfo is not None


def test_naive_occurred_at_is_normalized_to_utc():
    receipt = _build(occurred_at=datetime(2026, 1, 1, 12, 0, 0))
    assert receipt.occurred_at.tzinfo is not None


def test_capability_id_is_optional():
    receipt = _build(capability_id=None)
    assert receipt.capability_id is None
    assert receipt.material_fields()["capability_id"] is None
