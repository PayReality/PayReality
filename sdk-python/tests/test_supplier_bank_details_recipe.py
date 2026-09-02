"""Integration Kit v1: the "Supplier bank details change" recipe,
proving the new Adapter template and enforcement middleware actually
compose end to end -- something neither this milestone's other new test
files nor the platform's own pre-existing
test_reference_enforcement_demonstration.py exercise together, since
that file predates both new SDK classes. The underlying Trusted-Adapter
and Capability mechanics themselves are NOT re-proven here (they're
already exhaustively covered server-side); this is specifically the
composition proof: template output feeds a real capability-issuance
step, and the resulting token feeds the middleware, including the
required replay-rejection demonstration.
"""

import json

from payreality import crypto
from payreality.adapter_templates import AdapterFieldRules, HttpApiAdapterTemplate
from payreality.agent import Agent
from payreality.enforcement import CapabilityEnforcer
from payreality.exceptions import CapabilityAlreadyConsumedError
from payreality.client import HttpClient
from payreality.configuration import Configuration

PRIVATE_KEY = crypto.generate_keypair().private_key_b64


def test_supplier_bank_details_recipe_end_to_end(fake_http_client, credentials_path, fake_session):
    # --- Step 1-4: Trusted Adapter observes the real operation --------
    fields = AdapterFieldRules(
        source_operation="ChangeSupplierBankDetails",
        action="supplier_bank_details_change",
        origin_agent_id_source="agent.id",
        external_operation_id_source="operation.id",
        resource_source="supplier.reference",
    )
    template = HttpApiAdapterTemplate(
        integration_identity_id="ii-1", certificate_id="cert-1", private_key=PRIVATE_KEY,
        enforcement_binding_id="binding-1", fields=fields,
    )
    template._adapter._client = fake_http_client
    fake_http_client.queue_response(
        {
            "decision": {"outcome": "HUMAN_REVIEW", "decision_id": "dec-1", "reason": "requires_dual_approval", "evaluated_mandates": []},
            "evidence_id": "ev-1",
            "status": "PENDING",
        }
    )

    decision = template.handle({
        "agent": {"id": "agt_ap_invoice"},
        "operation": {"id": "erp-txn-recipe-001"},
        "supplier": {"reference": "supplier:SUPPLIER_482"},
    })
    assert decision.outcome == "HUMAN_REVIEW"

    # --- Step 5-6: reviewer approves, Capability issued from the review ---
    review_agent = Agent(bearer_token="reviewer-key", credentials_path=credentials_path)
    review_agent._client = fake_http_client
    fake_http_client.queue_response({"token": "tok-recipe-001", "capability_id": "cap-1", "expires_at": "2026-09-01T00:05:00Z"})

    capability = review_agent.request_capability_from_review(decision.decision_id, audience="my-service")
    assert capability.token == "tok-recipe-001"

    # --- Step 7: enforce through the middleware -------------------------
    verifier_agent = Agent(bearer_token="verifier-key", credentials_path=credentials_path)
    verifier_agent._client = HttpClient(Configuration(bearer_token="verifier-key"), session=fake_session)
    enforcer = CapabilityEnforcer(agent=verifier_agent, audience="my-service", environment="production")

    fake_session.queue_response(
        200, {"capability_id": "cap-1", "decision_id": "dec-1", "resource": "supplier:SUPPLIER_482", "constraints": {}}
    )
    downstream_calls = []

    result = enforcer.enforce(
        capability.token, action="supplier_bank_details_change", resource="supplier:SUPPLIER_482",
        constraints={}, downstream=lambda consumed: downstream_calls.append(consumed) or "executed",
    )
    assert result == "executed"
    assert len(downstream_calls) == 1
    assert downstream_calls[0].capability_id == "cap-1"

    # --- Step 8: replay rejected, downstream never called again ---------
    fake_session.queue_response(409, {"detail": "capability_token_already_consumed"})
    try:
        enforcer.enforce(
            capability.token, action="supplier_bank_details_change", resource="supplier:SUPPLIER_482",
            constraints={}, downstream=lambda consumed: downstream_calls.append(consumed),
        )
        assert False, "expected CapabilityAlreadyConsumedError"
    except CapabilityAlreadyConsumedError:
        pass
    assert len(downstream_calls) == 1  # unchanged -- the replay never reached downstream
