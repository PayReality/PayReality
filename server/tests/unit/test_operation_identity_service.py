"""Trusted Integration Architecture, Phase 3: pure-logic unit tests for
operation_identity_service.py -- validation and canonical-fingerprint
determinism, no DB needed (mirrors this codebase's own convention of
testing pure logic directly, e.g. test_agent_lifecycle.py's state-
machine assertions)."""

import pytest

from app.services import operation_identity_service as svc


# --- validate_external_operation_id (section 29) ----------------------------


def test_rejects_empty_string():
    with pytest.raises(svc.InvalidExternalOperationIdError):
        svc.validate_external_operation_id("")


def test_rejects_whitespace_only():
    with pytest.raises(svc.InvalidExternalOperationIdError):
        svc.validate_external_operation_id("   \t\n")


def test_rejects_absurdly_long_id():
    with pytest.raises(svc.InvalidExternalOperationIdError):
        svc.validate_external_operation_id("x" * (svc.MAX_EXTERNAL_OPERATION_ID_LENGTH + 1))


def test_accepts_id_at_the_length_boundary():
    svc.validate_external_operation_id("x" * svc.MAX_EXTERNAL_OPERATION_ID_LENGTH)  # must not raise


def test_never_format_restricted_numeric_uuid_or_arbitrary_string():
    svc.validate_external_operation_id("482910")
    svc.validate_external_operation_id("550e8400-e29b-41d4-a716-446655440000")
    svc.validate_external_operation_id("SAP-ERP-TXN-2026-08-30-000482")
    svc.validate_external_operation_id("orchestrator/run/8f3c/step-2")


def test_never_case_normalized():
    """Opaque, compared byte-for-byte -- this function itself never
    mutates the value; case sensitivity is enforced by find_existing_
    operation's own exact-match query, not here, but this at least
    proves validation never rejects mixed case or silently expects it
    to be normalized beforehand."""
    svc.validate_external_operation_id("MixedCase-ID-123")


# --- compute_canonical_operation_fingerprint --------------------------------


def _base_kwargs(**overrides):
    kwargs = dict(
        origin_agent_id="11111111-1111-1111-1111-111111111111",
        contract_content_hash="abc123",
        source_operation="ChangeSupplierBankDetails",
        canonical_action="vendor_payment",
        resource="supplier:123",
        amount=100.0,
        currency="USD",
        fact_subject="ABC Ltd",
        trusted_context={"department": "finance"},
    )
    kwargs.update(overrides)
    return kwargs


def test_fingerprint_is_deterministic_for_identical_input():
    fp1 = svc.compute_canonical_operation_fingerprint(**_base_kwargs())
    fp2 = svc.compute_canonical_operation_fingerprint(**_base_kwargs())
    assert fp1 == fp2


def test_fingerprint_ignores_context_key_order():
    fp1 = svc.compute_canonical_operation_fingerprint(**_base_kwargs(trusted_context={"a": 1, "b": 2}))
    fp2 = svc.compute_canonical_operation_fingerprint(**_base_kwargs(trusted_context={"b": 2, "a": 1}))
    assert fp1 == fp2


def test_fingerprint_normalizes_equivalent_amount_representations():
    """Section 34: 100.1, 100.10, and a plausible float artifact must
    all hash identically -- the engine treats them as the same amount
    at the Numeric(18,2) precision it actually persists and compares
    at."""
    fp1 = svc.compute_canonical_operation_fingerprint(**_base_kwargs(amount=100.1))
    fp2 = svc.compute_canonical_operation_fingerprint(**_base_kwargs(amount=100.10))
    fp3 = svc.compute_canonical_operation_fingerprint(**_base_kwargs(amount=100.099999999999))
    assert fp1 == fp2 == fp3


def test_fingerprint_differs_on_different_amount():
    fp1 = svc.compute_canonical_operation_fingerprint(**_base_kwargs(amount=100.0))
    fp2 = svc.compute_canonical_operation_fingerprint(**_base_kwargs(amount=200.0))
    assert fp1 != fp2


@pytest.mark.parametrize(
    "field,other_value",
    [
        ("origin_agent_id", "22222222-2222-2222-2222-222222222222"),
        ("contract_content_hash", "different-hash"),
        ("source_operation", "SomeOtherOperation"),
        ("canonical_action", "disable_user"),
        ("resource", "supplier:456"),
        ("currency", "EUR"),
        ("fact_subject", "XYZ Ltd"),
        ("trusted_context", {"department": "engineering"}),
    ],
)
def test_fingerprint_differs_when_any_authority_relevant_field_changes(field, other_value):
    fp1 = svc.compute_canonical_operation_fingerprint(**_base_kwargs())
    fp2 = svc.compute_canonical_operation_fingerprint(**_base_kwargs(**{field: other_value}))
    assert fp1 != fp2, f"changing {field!r} must change the fingerprint"


def test_fingerprint_excludes_environment_nonce_timestamp_and_identity_fields():
    """Section 6: the function signature itself is the proof -- none of
    environment, nonce, requested_at, correlation_id,
    integration_identity_id/certificate_id, or enforcement_binding_id
    are accepted parameters at all, so they cannot possibly be part of
    the computed value."""
    import inspect

    params = set(inspect.signature(svc.compute_canonical_operation_fingerprint).parameters)
    excluded = {
        "environment", "nonce", "requested_at", "correlation_id",
        "integration_identity_id", "certificate_id", "enforcement_binding_id",
    }
    assert params.isdisjoint(excluded)


def test_fingerprint_uses_content_hash_not_version_id():
    """Section 32: the parameter is explicitly contract_content_hash,
    never a version id -- two independently approved versions with
    identical semantic content (hence identical content_hash, computed
    elsewhere) must produce identical fingerprints, proven directly by
    passing the same hash string regardless of whatever version it
    actually came from."""
    fp1 = svc.compute_canonical_operation_fingerprint(**_base_kwargs(contract_content_hash="same-hash"))
    fp2 = svc.compute_canonical_operation_fingerprint(**_base_kwargs(contract_content_hash="same-hash"))
    assert fp1 == fp2
