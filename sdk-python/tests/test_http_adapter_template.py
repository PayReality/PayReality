"""Integration Kit v1, Part B: SDK-level tests for `HttpApiAdapterTemplate`
-- mirrors test_integration_adapter.py's own mocking convention
(`adapter._client = fake_http_client`), since this class is a thin,
configuration-driven wrapper over the already-tested `Adapter.attest()`.
These tests prove the template's OWN field-extraction/fail-closed logic;
they do not re-prove attest()'s own signing/idempotency behavior.
"""

import pytest

from payreality import crypto
from payreality.adapter_templates import AdapterFieldRules, HttpApiAdapterTemplate
from payreality.exceptions import ConfigurationError
from payreality.integration import ContractShape

PRIVATE_KEY = crypto.generate_keypair().private_key_b64

_DECISION_RESPONSE = {
    "decision": {"outcome": "ALLOW", "decision_id": "d-1", "reason": None, "evaluated_mandates": []},
    "evidence_id": "e-1",
    "status": "RESOLVED",
}


def _template(fake_http_client, fields, contract_shape=None):
    template = HttpApiAdapterTemplate(
        integration_identity_id="ii-1",
        certificate_id="cert-1",
        private_key=PRIVATE_KEY,
        enforcement_binding_id="binding-1",
        fields=fields,
        contract_shape=contract_shape,
    )
    template._adapter._client = fake_http_client
    return template


def _bank_details_fields(**overrides):
    defaults = dict(
        source_operation="ChangeSupplierBankDetails",
        action="supplier_bank_details_change",
        origin_agent_id_source="agent.id",
        external_operation_id_source="operation.id",
        resource_source="supplier.reference",
    )
    defaults.update(overrides)
    return AdapterFieldRules(**defaults)


def test_handle_extracts_configured_fields_and_calls_attest(fake_http_client):
    template = _template(fake_http_client, _bank_details_fields())
    fake_http_client.queue_response(_DECISION_RESPONSE)

    payload = {
        "agent": {"id": "agt_ap_invoice"},
        "operation": {"id": "erp-txn-9001"},
        "supplier": {"reference": "supplier:SUPPLIER_482"},
    }
    decision = template.handle(payload)

    call = fake_http_client.calls[-1]
    assert call["path"] == "/v1/integration-runtime/intents"
    assert decision.outcome == "ALLOW"
    assert decision.decision_id == "d-1"


def test_handle_never_lets_the_payload_choose_the_action(fake_http_client):
    """The fixed action/source_operation are always what's sent, no
    matter what the payload itself contains under similarly-named keys
    -- a payload cannot smuggle in a different canonical action."""
    template = _template(fake_http_client, _bank_details_fields())
    fake_http_client.queue_response(_DECISION_RESPONSE)

    payload = {
        "agent": {"id": "agt_ap_invoice"},
        "operation": {"id": "erp-txn-9001"},
        "supplier": {"reference": "supplier:SUPPLIER_482"},
        "action": "vendor_payment",  # attacker/bug-injected key, must be ignored
        "source_operation": "MakePayment",
    }
    template.handle(payload)

    import json
    sent_body = json.loads(fake_http_client.calls[-1]["signed_body"])
    assert sent_body["action"] == "supplier_bank_details_change"
    assert sent_body["source_operation"] == "ChangeSupplierBankDetails"


def test_handle_fails_closed_on_missing_external_operation_id(fake_http_client):
    template = _template(fake_http_client, _bank_details_fields())

    with pytest.raises(ConfigurationError):
        template.handle({"agent": {"id": "agt_1"}, "supplier": {"reference": "supplier:1"}})

    assert fake_http_client.calls == []  # never even attempted the network call


def test_handle_fails_closed_on_missing_origin_agent_id(fake_http_client):
    template = _template(fake_http_client, _bank_details_fields())

    with pytest.raises(ConfigurationError):
        template.handle({"operation": {"id": "op-1"}, "supplier": {"reference": "supplier:1"}})

    assert fake_http_client.calls == []


def test_handle_fails_closed_on_missing_required_context_field(fake_http_client):
    fields = _bank_details_fields(context_sources={"cost_center": "finance.cost_center"})
    template = _template(fake_http_client, fields)

    with pytest.raises(ConfigurationError):
        template.handle({
            "agent": {"id": "agt_1"}, "operation": {"id": "op-1"}, "supplier": {"reference": "supplier:1"},
        })

    assert fake_http_client.calls == []


def test_fixed_origin_agent_id_is_used_when_configured(fake_http_client):
    fields = AdapterFieldRules(
        source_operation="ChangeSupplierBankDetails", action="supplier_bank_details_change",
        origin_agent_id="agt_fixed", external_operation_id_source="operation.id",
    )
    template = _template(fake_http_client, fields)
    fake_http_client.queue_response(_DECISION_RESPONSE)

    template.handle({"operation": {"id": "op-1"}})

    import json
    sent_body = json.loads(fake_http_client.calls[-1]["signed_body"])
    assert sent_body["origin_agent_id"] == "agt_fixed"


def test_configuring_both_fixed_and_extracted_origin_agent_id_is_rejected():
    with pytest.raises(ConfigurationError):
        AdapterFieldRules(
            source_operation="X", action="y", origin_agent_id="fixed",
            origin_agent_id_source="agent.id", external_operation_id_source="op.id",
        )


def test_configuring_neither_origin_agent_id_option_is_rejected():
    with pytest.raises(ConfigurationError):
        AdapterFieldRules(source_operation="X", action="y", external_operation_id_source="op.id")


def test_contract_shape_still_applies_as_a_local_preflight_check(fake_http_client):
    """The template composes with the existing ContractShape mechanism
    unchanged -- it doesn't invent a second, parallel shape-checking
    system of its own."""
    shape = ContractShape(has_resource=True, has_amount=False, has_currency=False)
    fields = _bank_details_fields(amount_source="payment.amount")  # declares amount, shape doesn't
    template = _template(fake_http_client, fields, contract_shape=shape)

    with pytest.raises(ConfigurationError):
        template.handle({
            "agent": {"id": "agt_1"}, "operation": {"id": "op-1"},
            "supplier": {"reference": "supplier:1"}, "payment": {"amount": 500},
        })

    assert fake_http_client.calls == []


def test_callable_source_is_supported_alongside_dotted_paths(fake_http_client):
    fields = AdapterFieldRules(
        source_operation="ChangeSupplierBankDetails", action="supplier_bank_details_change",
        origin_agent_id="agt_1",
        external_operation_id_source=lambda p: f"synthetic-{p['raw_id']}",
    )
    template = _template(fake_http_client, fields)
    fake_http_client.queue_response(_DECISION_RESPONSE)

    template.handle({"raw_id": "9001"})

    import json
    sent_body = json.loads(fake_http_client.calls[-1]["signed_body"])
    assert sent_body["external_operation_id"] == "synthetic-9001"
