"""Post-audit implementation, Priority 3: app/domain/canonical_action.py
is a pure domain module (no DB, no signing key) -- exactly the kind of
thing this codebase's own convention tests directly, without a fake
session or a real database. The through-the-real-path proof (a real
Adapter-mediated Intent actually persisting a canonical_action_digest,
and an idempotent retry reusing the same one) lives in
tests/integration/test_canonical_action_runtime.py instead, matching this
codebase's own "unit-test the pure logic, integration-test the wiring"
split.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app.domain.canonical_action import (
    CANONICAL_ACTION_SCHEMA_VERSION,
    MissingRequiredCanonicalActionFieldError,
    UnsupportedCanonicalActionSchemaVersionError,
    build_canonical_action,
)

ORG = uuid.uuid4()
AGENT = uuid.uuid4()
IDENTITY = uuid.uuid4()
CONTRACT_VERSION = uuid.uuid4()


def _build(**overrides):
    defaults = dict(
        organization_id=ORG,
        agent_id=AGENT,
        action="wire_transfer",
        integration_identity_id=IDENTITY,
        integration_contract_version_id=CONTRACT_VERSION,
        contract_content_hash="hash-abc",
        environment="production",
        external_operation_id="ext-op-1",
        observed_at=datetime.now(timezone.utc),
        resource="account:OPS-001",
        amount=100.10,
        currency="USD",
    )
    defaults.update(overrides)
    return build_canonical_action(**defaults)


# === Deterministic canonicalisation =========================================


def test_canonical_digest_is_deterministic_for_the_same_inputs():
    a = _build()
    b = _build()
    assert a.canonical_digest() == b.canonical_digest()


def test_same_semantic_action_produces_the_same_digest_regardless_of_non_material_fields():
    a = _build(observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    b = _build(
        observed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        source_request_digest="sha256:raw-payload-hash",
        declared_task_reference="agent-declared-task-42",
    )
    assert a.canonical_digest() == b.canonical_digest(), (
        "observed_at, source_request_digest, and declared_task_reference are non-material"
    )


# === Material-field changes produce a different digest ======================


@pytest.mark.parametrize(
    "field,value",
    [
        ("organization_id", uuid.uuid4()),
        ("agent_id", uuid.uuid4()),
        ("action", "different_action"),
        ("integration_identity_id", uuid.uuid4()),
        ("integration_contract_version_id", uuid.uuid4()),
        ("contract_content_hash", "hash-different"),
        ("environment", "sandbox"),
        ("external_operation_id", "ext-op-2"),
        ("resource", "account:OPS-002"),
        ("amount", 200.00),
        ("currency", "ZAR"),
        ("principal", "a-different-principal"),
    ],
)
def test_a_material_field_change_produces_a_different_digest(field, value):
    baseline = _build()
    changed = _build(**{field: value})
    assert baseline.canonical_digest() != changed.canonical_digest()


def test_tenant_mismatch_produces_a_different_digest():
    """Two organisations submitting otherwise byte-for-byte identical
    canonical actions must never collide -- organization_id is itself a
    material field precisely so a cross-tenant digest can never match."""
    org_a_action = _build(organization_id=uuid.uuid4())
    org_b_action = _build(organization_id=uuid.uuid4())
    assert org_a_action.canonical_digest() != org_b_action.canonical_digest()


def test_wrong_integration_identity_produces_a_different_digest():
    identity_a = _build(integration_identity_id=uuid.uuid4())
    identity_b = _build(integration_identity_id=uuid.uuid4())
    assert identity_a.canonical_digest() != identity_b.canonical_digest()


# === Monetary normalisation: no floating-point ambiguity =====================


@pytest.mark.parametrize("amount", [100.1, 100.10, 100.099999999999])
def test_monetary_normalization_treats_equivalent_amounts_identically(amount):
    baseline = _build(amount=100.10)
    variant = _build(amount=amount)
    assert baseline.canonical_digest() == variant.canonical_digest()


def test_monetary_normalization_still_distinguishes_a_real_difference():
    cheap = _build(amount=100.10)
    expensive = _build(amount=100.11)
    assert cheap.canonical_digest() != expensive.canonical_digest()


def test_none_amount_is_distinct_from_any_real_amount():
    no_amount = _build(amount=None)
    with_amount = _build(amount=0.0)
    assert no_amount.canonical_digest() != with_amount.canonical_digest()


# === Timestamp normalisation ==================================================


def test_naive_observed_at_is_normalized_to_utc_without_raising():
    """observed_at is non-material (never hashed), but must still be
    handled without crashing for a naive datetime -- the same defensive
    normalization already established elsewhere in this codebase
    (capability_service.py's own expires_at comparison)."""
    action = _build(observed_at=datetime(2026, 1, 1))  # naive, no tzinfo
    assert action.observed_at.tzinfo is not None


# === Schema version ============================================================


def test_default_schema_version_is_the_current_supported_version():
    action = _build()
    assert action.schema_version == CANONICAL_ACTION_SCHEMA_VERSION


def test_unsupported_schema_version_is_rejected():
    with pytest.raises(UnsupportedCanonicalActionSchemaVersionError) as excinfo:
        _build(schema_version=999)
    assert excinfo.value.schema_version == 999


# === Missing required fields ===================================================


@pytest.mark.parametrize(
    "field",
    [
        "organization_id", "agent_id", "action", "integration_identity_id",
        "integration_contract_version_id", "contract_content_hash", "environment",
        "external_operation_id",
    ],
)
def test_missing_required_field_is_rejected(field):
    with pytest.raises(MissingRequiredCanonicalActionFieldError) as excinfo:
        _build(**{field: None})
    assert excinfo.value.field_name == field


def test_blank_string_required_field_is_rejected():
    with pytest.raises(MissingRequiredCanonicalActionFieldError):
        _build(action="   ")
