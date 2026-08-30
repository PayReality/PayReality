import base64
import json

import nacl.signing
import pytest

from payreality import crypto
from payreality.exceptions import ConfigurationError
from payreality.integration import Adapter, ContractShape

PRIVATE_KEY = crypto.generate_keypair().private_key_b64


def _adapter(fake_http_client, contract_shape=None):
    adapter = Adapter(
        integration_identity_id="ii-1", certificate_id="cert-1", private_key=PRIVATE_KEY,
        contract_shape=contract_shape,
    )
    adapter._client = fake_http_client
    return adapter


def test_attest_signs_the_exact_bytes_sent(fake_http_client):
    adapter = _adapter(fake_http_client)
    fake_http_client.queue_response(
        {
            "decision": {"outcome": "ALLOW", "decision_id": "d-1", "reason": None, "evaluated_mandates": []},
            "evidence_id": "e-1",
            "status": "RESOLVED",
        }
    )

    adapter.attest(
        enforcement_binding_id="b-1", origin_agent_id="a-1", source_operation="ChangeSupplierBankDetails",
        action="vendor_payment", external_operation_id="OP-1", resource="supplier:123", amount=85000, currency="USD",
    )

    call = fake_http_client.calls[-1]
    assert call["path"] == "/v1/integration-runtime/intents"
    signature_b64 = call["headers"]["X-PayReality-Signature"]
    assert call["headers"]["X-PayReality-Key-Id"] == "cert-1"

    public_key_b64 = crypto.public_key_from_private(PRIVATE_KEY)
    verify_key = nacl.signing.VerifyKey(base64.b64decode(public_key_b64))
    verify_key.verify(call["signed_body"], base64.b64decode(signature_b64))  # raises if invalid


def test_attest_body_carries_every_binding_field(fake_http_client):
    adapter = _adapter(fake_http_client)
    fake_http_client.queue_response(
        {
            "decision": {"outcome": "ALLOW", "decision_id": "d-1", "reason": None, "evaluated_mandates": []},
            "evidence_id": "e-1",
            "status": "RESOLVED",
        }
    )

    adapter.attest(
        enforcement_binding_id="b-1", origin_agent_id="a-1", source_operation="ChangeSupplierBankDetails",
        action="vendor_payment", external_operation_id="OP-1", resource="supplier:123", amount=85000, currency="USD",
        counterparty="ABC Ltd", context={"department": "finance"}, correlation_id="JOB-1",
    )

    body = json.loads(fake_http_client.calls[-1]["signed_body"])
    assert body["integration_identity_id"] == "ii-1"
    assert body["enforcement_binding_id"] == "b-1"
    assert body["origin_agent_id"] == "a-1"
    assert body["source_operation"] == "ChangeSupplierBankDetails"
    assert body["action"] == "vendor_payment"
    assert body["external_operation_id"] == "OP-1"
    assert body["resource"] == "supplier:123"
    assert body["amount"] == 85000
    assert body["currency"] == "USD"
    assert body["counterparty"] == "ABC Ltd"
    assert body["context"] == {"department": "finance"}
    assert body["correlation_id"] == "JOB-1"
    assert "nonce" in body and body["nonce"]
    assert "requested_at" in body and body["requested_at"]


def test_attest_maps_every_outcome_to_a_decision(fake_http_client):
    adapter = _adapter(fake_http_client)
    fake_http_client.queue_response(
        {
            "decision": {"outcome": "HUMAN_REVIEW", "decision_id": "d-1", "reason": "needs review", "evaluated_mandates": ["m-1"]},
            "evidence_id": "e-1",
            "status": "PENDING",
        }
    )

    decision = adapter.attest(
        enforcement_binding_id="b-1", origin_agent_id="a-1", source_operation="ChangeSupplierBankDetails",
        action="vendor_payment", external_operation_id="OP-1", resource="supplier:123",
    )

    assert decision.outcome == "HUMAN_REVIEW"
    assert decision.status == "PENDING"
    assert decision.evidence_id == "e-1"
    assert decision.evaluated_mandates == ("m-1",)
    assert decision.requires_human_review


# --- ContractShape: the local, opt-in pre-flight check --------------------


def test_contract_shape_rejects_a_missing_declared_field(fake_http_client):
    shape = ContractShape(has_resource=True)
    adapter = _adapter(fake_http_client, contract_shape=shape)
    with pytest.raises(ConfigurationError):
        adapter.attest(
            enforcement_binding_id="b-1", origin_agent_id="a-1", source_operation="Op",
            action="vendor_payment", external_operation_id="OP-1", resource=None,
        )


def test_contract_shape_rejects_an_undeclared_field_supplied_anyway(fake_http_client):
    shape = ContractShape(has_resource=False)
    adapter = _adapter(fake_http_client, contract_shape=shape)
    with pytest.raises(ConfigurationError):
        adapter.attest(
            enforcement_binding_id="b-1", origin_agent_id="a-1", source_operation="Op",
            action="vendor_payment", external_operation_id="OP-1", resource="supplier:123",
        )


def test_contract_shape_rejects_an_unexpected_context_key(fake_http_client):
    shape = ContractShape(context_keys=frozenset({"department"}))
    adapter = _adapter(fake_http_client, contract_shape=shape)
    with pytest.raises(ConfigurationError):
        adapter.attest(
            enforcement_binding_id="b-1", origin_agent_id="a-1", source_operation="Op",
            action="vendor_payment", external_operation_id="OP-1", context={"not_declared": "value"},
        )


def test_contract_shape_rejects_a_missing_required_context_key(fake_http_client):
    shape = ContractShape(context_keys=frozenset({"department"}))
    adapter = _adapter(fake_http_client, contract_shape=shape)
    with pytest.raises(ConfigurationError):
        adapter.attest(
            enforcement_binding_id="b-1", origin_agent_id="a-1", source_operation="Op",
            action="vendor_payment", external_operation_id="OP-1", context={},
        )


def test_contract_shape_allows_a_fully_matching_call(fake_http_client):
    shape = ContractShape(has_resource=True, has_amount=True, has_currency=True, context_keys=frozenset({"department"}))
    adapter = _adapter(fake_http_client, contract_shape=shape)
    fake_http_client.queue_response(
        {
            "decision": {"outcome": "ALLOW", "decision_id": "d-1", "reason": None, "evaluated_mandates": []},
            "evidence_id": "e-1",
            "status": "RESOLVED",
        }
    )

    decision = adapter.attest(
        enforcement_binding_id="b-1", origin_agent_id="a-1", source_operation="Op",
        action="vendor_payment", external_operation_id="OP-1", resource="supplier:123", amount=100, currency="USD",
        context={"department": "finance"},
    )
    assert decision.outcome == "ALLOW"


def test_contract_shape_check_never_reaches_the_network_on_failure(fake_http_client):
    shape = ContractShape(has_resource=True)
    adapter = _adapter(fake_http_client, contract_shape=shape)
    with pytest.raises(ConfigurationError):
        adapter.attest(
            enforcement_binding_id="b-1", origin_agent_id="a-1", source_operation="Op",
            action="vendor_payment", external_operation_id="OP-1", resource=None,
        )
    assert fake_http_client.calls == []


# --- external_operation_id (Phase 3): required, client-validated -----------


def test_attest_requires_external_operation_id_as_a_real_keyword_argument():
    """Not merely documented as required -- omitting it is a TypeError
    at the call site, the same way Python enforces any other required
    keyword-only parameter (no silent default, no server round trip)."""
    import inspect

    signature = inspect.signature(Adapter.attest)
    assert signature.parameters["external_operation_id"].default is inspect.Parameter.empty


def test_attest_rejects_an_empty_external_operation_id(fake_http_client):
    adapter = _adapter(fake_http_client)
    with pytest.raises(ConfigurationError):
        adapter.attest(
            enforcement_binding_id="b-1", origin_agent_id="a-1", source_operation="Op",
            action="vendor_payment", external_operation_id="",
        )
    assert fake_http_client.calls == []


def test_attest_rejects_a_whitespace_only_external_operation_id(fake_http_client):
    adapter = _adapter(fake_http_client)
    with pytest.raises(ConfigurationError):
        adapter.attest(
            enforcement_binding_id="b-1", origin_agent_id="a-1", source_operation="Op",
            action="vendor_payment", external_operation_id="   ",
        )
    assert fake_http_client.calls == []


def test_attest_rejects_an_absurdly_long_external_operation_id(fake_http_client):
    adapter = _adapter(fake_http_client)
    with pytest.raises(ConfigurationError):
        adapter.attest(
            enforcement_binding_id="b-1", origin_agent_id="a-1", source_operation="Op",
            action="vendor_payment", external_operation_id="x" * 10_000,
        )
    assert fake_http_client.calls == []


def test_attest_accepts_a_non_uuid_non_numeric_external_operation_id(fake_http_client):
    """Section 29: never format-restricted -- enterprise systems use
    many identifier formats, not just UUIDs or numeric ids."""
    adapter = _adapter(fake_http_client)
    fake_http_client.queue_response(
        {
            "decision": {"outcome": "ALLOW", "decision_id": "d-1", "reason": None, "evaluated_mandates": []},
            "evidence_id": "e-1",
            "status": "RESOLVED",
        }
    )
    decision = adapter.attest(
        enforcement_binding_id="b-1", origin_agent_id="a-1", source_operation="Op",
        action="vendor_payment", external_operation_id="SAP-ERP-TXN-2026-08-30-000482",
    )
    assert decision.outcome == "ALLOW"
