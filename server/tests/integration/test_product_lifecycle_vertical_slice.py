"""Product lifecycle vertical slice: verifies the new Operation state
machine, order_action_contract.py, and the narrowly scoped observation/
replacement-safety surface against real code -- not a reimplementation
of EVIDENCEBOUND-PAYREALITY-RECOVERY-V01's own expectations, a real
extension of it. Reuses that report's exact frozen scenario (120 units,
supplier A, buyer account B, delivery location X) with one addition this
milestone requires: a fixed unit_price, now declared material.

Mirrors test_interop_evidencebound_recovery_v01.py's own fixture
conventions (same `db`/`opa_url` pattern, same FakeDestination shape) on
purpose -- this file extends that baseline, it does not replace it; the
original file is left untouched as the historical record of the gaps
this milestone closes.
"""

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Base, CapabilityToken, Operation, Organization, Principal
from app.domain import order_action_contract as order_action
from app.domain.capability import token as capability_token
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64
from app.domain.rbac.permissions import Permission, Role, has_permission
from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import (
    agent_service,
    capability_service,
    enforcement_binding_service as binding_svc,
    execution_receipt_service as receipt_svc,
    execution_reconciliation_service as reconciliation_svc,
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
    integration_runtime_service as runtime_svc,
    operation_service,
    runtime_policy_service as policy_svc,
    signing_key_service,
)

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)

INTEROP_ID = "EVIDENCEBOUND-PAYREALITY-RECOVERY-V01"
OPERATION_ID = "EVIDENCEBOUND-PAYREALITY-RECOVERY-V01-OP-001"
ACTION = "purchase_order_create"
SOURCE_OPERATION = "EVIDENCEBOUND/v1.SubmitOrder"
DESTINATION = "synthetic:evidencebound-fulfillment-01"
SUPPLIER_RESOURCE = "supplier:A"
FIXED_UNIT_PRICE = "42.50"
ORDER_CONTEXT_BINDINGS = {
    "quantity": "order.quantity", "buyer_account": "order.buyer_account",
    "delivery_location": "order.delivery_location", "unit_price": "order.unit_price",
}
ORDER_CONTEXT = {"quantity": 120, "buyer_account": "ACCT-B", "delivery_location": "location:X", "unit_price": FIXED_UNIT_PRICE}

_TRACE_PATH = os.path.join(os.path.dirname(__file__), "_product_lifecycle_output", "traces.jsonl")


@compiles(PG_JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _uuid_as_char_on_sqlite(element, compiler, **kw):
    return "CHAR(36)"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    policies_table = Base.metadata.tables["policies"]
    partial_index = next(i for i in policies_table.indexes if i.name == "idx_policies_single_active_per_org")
    policies_table.indexes.discard(partial_index)
    try:
        Base.metadata.create_all(engine)
    finally:
        policies_table.indexes.add(partial_index)
    session = sessionmaker(bind=engine)()
    signing_key_service.ensure_current_key_registered(
        session, settings.evidence_signing_key_id,
        public_key_b64_from_signing_key_b64(settings.evidence_signing_key_b64),
    )
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _point_settings_at_ephemeral_opa(request):
    opa_url = request.getfixturevalue("opa_url")
    original = settings.opa_url
    settings.opa_url = opa_url
    try:
        yield
    finally:
        settings.opa_url = original


@pytest.fixture(scope="session", autouse=True)
def _clear_trace_output():
    os.makedirs(os.path.dirname(_TRACE_PATH), exist_ok=True)
    with open(_TRACE_PATH, "w", encoding="utf-8"):
        pass
    yield


def _trace(schedule: str, event: str, **fields) -> None:
    record = {"interop_id": INTEROP_ID, "operation_id": OPERATION_ID, "schedule": schedule, "event": event, "timestamp": datetime.now(timezone.utc).isoformat()}
    for k, v in fields.items():
        record[k] = str(v) if isinstance(v, uuid.UUID) else v
    with open(_TRACE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


class DestinationBehaviour(Enum):
    COMMIT_NO_RECEIPT = "commit_no_receipt"
    NOT_FOUND_NOW = "not_found_now"


@dataclass
class FakeDestination:
    behaviour: DestinationBehaviour
    internal_committed_state: bool = field(init=False, default=False)

    def attempt(self, operation_id: str) -> str:
        if self.behaviour == DestinationBehaviour.COMMIT_NO_RECEIPT:
            self.internal_committed_state = True
            return "COMMITTED_INTERNALLY_NO_RECEIPT_ISSUED"
        return "NOT_FOUND_NOW"

    def late_authoritative_observation(self) -> str:
        return "COMMITTED" if self.behaviour == DestinationBehaviour.COMMIT_NO_RECEIPT else "NOT_FOUND_NOW"


def _org(db, name="Org Product Lifecycle"):
    org = Organization(id=uuid.uuid4(), name=name)
    db.add(org)
    db.commit()
    return org


def _deploy_policy(db, org_id, opa_url, *, effect=Effect.ALLOW, resource=SUPPLIER_RESOURCE):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="product-lifecycle-policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="OrderingAgent01", action=ACTION, resource=resource),
        conditions=ConditionSet(all=()), effect=effect, audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row


def _scenario(db, org_id):
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "Reference Order Adapter", "ed25519:base64:AAAA")
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)
    integration = contract_svc.create_integration(db, org_id, "Order Fulfillment (reference)")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, SOURCE_OPERATION, ACTION,
        resource_path="order.supplier", amount_path=None, currency_path=None,
        fact_subject_path=None, context_bindings=ORDER_CONTEXT_BINDINGS,
    )
    contract_version = contract_svc.validate_contract_version(db, contract_version.id, org_id)
    contract_version = contract_svc.approve_contract_version(db, contract_version.id, org_id, approver="governance-admin@example.com")
    principal = Principal(id=uuid.uuid4(), name="OrderingAgent01", organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="Ordering Agent 01", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    binding = binding_svc.create_draft_binding(db, org_id, identity.id, contract_version.id, "production", agent_ids=[agent.id])
    binding = binding_svc.activate_binding(db, binding.id, org_id)
    return identity, contract_version, binding, agent


def _order_action(external_operation_id, **overrides):
    fields = {
        "external_operation_id": external_operation_id, "supplier": "A", "quantity": 120,
        "buyer_account": "ACCT-B", "delivery_location": "location:X", "unit_price": FIXED_UNIT_PRICE,
    }
    fields.update(overrides)
    return order_action.build_order_action(**fields)


def _submit_and_authorize(db, org_id, identity, binding, agent, *, external_operation_id, resource=SUPPLIER_RESOURCE, context=None):
    """Real path: submit the order Intent, issue the Capability, then
    create the Operation record bound to this order's real, computed
    OrderAction digest -- exactly the sequence a real order-submission
    flow composes (operation_service.create_operation_for_decision is
    deliberately NOT auto-wired into generic capability issuance; see
    that function's own docstring for why)."""
    intent, decision, _ev = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=resource,
        amount=None, currency=None, counterparty=None, context=context if context is not None else dict(ORDER_CONTEXT),
        requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=external_operation_id,
    )
    if decision.outcome != "ALLOW":
        return intent, decision, None, None
    issued = capability_service.issue_capability_for_decision(db, org_id, decision.id, audience="reference-pep")
    order = _order_action(external_operation_id)
    operation = operation_service.create_operation_for_decision(db, org_id, decision.id, order.digest())
    return intent, decision, issued, operation


def _expected_constraints(context=None, environment="production"):
    constraints = {k: str(v) for k, v in (context if context is not None else ORDER_CONTEXT).items()}
    constraints["environment"] = environment
    return constraints


# === Order action contract: required fields ====================================


@pytest.mark.parametrize("field_name", order_action.REQUIRED_MATERIAL_FIELDS)
def test_order_action_rejects_missing_required_field(field_name):
    kwargs = {
        "external_operation_id": "op-1", "supplier": "A", "quantity": 120,
        "buyer_account": "ACCT-B", "delivery_location": "location:X", "unit_price": FIXED_UNIT_PRICE,
    }
    kwargs[field_name] = None if field_name in ("quantity", "unit_price") else ""
    with pytest.raises(order_action.MissingRequiredOrderActionFieldError) as excinfo:
        order_action.build_order_action(**kwargs)
    assert excinfo.value.field_name == field_name


@pytest.mark.parametrize("field_name,changed_value", [
    ("supplier", "B"), ("quantity", 121), ("buyer_account", "ACCT-B-PRIME"),
    ("delivery_location", "location:Y"), ("unit_price", "99.99"),
])
def test_order_action_digest_changes_on_any_material_field_substitution(field_name, changed_value):
    """Every one of the five required fields is material to the digest
    -- a substitution in any one of them must never leave the digest
    identical, which would mean it wasn't actually bound."""
    original = _order_action("op-1")
    changed = _order_action("op-1", **{field_name: changed_value})
    assert original.digest() != changed.digest(), f"{field_name} substitution did not change the digest"


# === Operation created at issuance, dispatched at consumption ==================


def test_operation_created_authorized_then_dispatched_on_consumption(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-LIFECYCLE"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    assert operation.state == "AUTHORIZED"
    assert operation.attempt_count == 0

    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    db.refresh(operation)
    assert operation.state == "DISPATCHED"
    assert operation.attempt_count == 1
    assert operation.capability_id == consumed.capability_id


# === Revocation before / after dispatch; late committed evidence after =========


def test_revocation_before_consumption_leaves_operation_authorized_and_blocks_dispatch(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-REVOKE-BEFORE-DISPATCH"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    assert operation.state == "AUTHORIZED"

    agent_service.revoke_agent(db, agent.id, reason="revoked before any consumption attempt")
    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
            _expected_constraints(), environment=binding.environment,
            enforcement_binding_id=binding.id, expected_organization_id=org.id,
        )
    db.refresh(operation)
    assert operation.state == "AUTHORIZED", "a blocked consumption attempt must never dispatch the operation"
    assert operation.attempt_count == 0
    _trace("product", "revocation_before_consumption", operation_record_id=operation.id, state=operation.state)


def test_revocation_after_dispatch_then_late_committed_evidence_via_observation_endpoint_path(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-LATE-COMMIT"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    db.refresh(operation)
    assert operation.state == "DISPATCHED"

    destination = FakeDestination(DestinationBehaviour.COMMIT_NO_RECEIPT)
    destination.attempt(op_id)
    agent_service.revoke_agent(db, agent.id, reason="pending investigation")

    late = destination.late_authoritative_observation()
    assert late == "COMMITTED"
    order = _order_action(op_id)
    updated_operation, receipt, result = operation_service.record_observation(
        db, org.id, operation.id, identity, enforcement_binding_id=binding.id,
        material_action_digest=order.digest(), canonical_action_digest=intent.canonical_action_digest,
        destination=DESTINATION, status="SUCCEEDED", capability_id=consumed.capability_id,
    )
    assert result.outcome == "MATCHED"
    assert updated_operation.state == "COMMITTED"
    _trace("product", "late_committed_after_revocation", operation_record_id=operation.id, state=updated_operation.state)

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
            _expected_constraints(), environment=binding.environment,
            enforcement_binding_id=binding.id, expected_organization_id=org.id,
        )
    db.refresh(updated_operation)
    assert updated_operation.state == "COMMITTED", "the late observation updates historical knowledge; execution authority is not restored"


# === Claim/dispatch, then a crash with no receipt; NOT_FOUND_NOW stays non-terminal ==


def test_dispatch_then_crash_no_receipt_leaves_outcome_unknown(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-CRASH-NO-RECEIPT"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    # No receipt is ever submitted: nothing true to report.
    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "RECEIPT_MISSING"
    db.refresh(operation)
    assert operation.state == "DISPATCHED", "no observation was ever recorded, so state stays at DISPATCHED, not silently promoted"


def test_not_found_now_is_not_recorded_as_terminal(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-NOT-FOUND-NOW"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    destination = FakeDestination(DestinationBehaviour.NOT_FOUND_NOW)
    response = destination.attempt(op_id)
    assert response == "NOT_FOUND_NOW"
    # No receipt submitted for an ambiguous, non-authoritative response.
    db.refresh(operation)
    assert operation.state == "DISPATCHED"
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "UNSAFE_UNRESOLVED", "NOT_FOUND_NOW must never be treated as terminal non-commit proof"


# === Observation while execution revoked; observation itself revoked ===========


def test_observation_permitted_while_execution_revoked(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-OBS-WHILE-EXEC-REVOKED"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    agent_service.revoke_agent(db, agent.id, reason="execution authority revoked")
    order = _order_action(op_id)
    updated_operation, receipt, result = operation_service.record_observation(
        db, org.id, operation.id, identity, enforcement_binding_id=binding.id,
        material_action_digest=order.digest(), canonical_action_digest=intent.canonical_action_digest,
        destination=DESTINATION, status="SUCCEEDED", capability_id=consumed.capability_id,
    )
    assert updated_operation.state == "COMMITTED"


def test_observation_itself_revoked_blocks_the_observation(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-OBS-ITSELF-REVOKED"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    identity_svc.suspend_integration_identity(db, identity.id, org.id)
    order = _order_action(op_id)

    from app.services.execution_receipt_service import ExecutionReceiptRejectionError

    with pytest.raises(ExecutionReceiptRejectionError):
        operation_service.record_observation(
            db, org.id, operation.id, identity, enforcement_binding_id=binding.id,
            material_action_digest=order.digest(), canonical_action_digest=intent.canonical_action_digest,
            destination=DESTINATION, status="SUCCEEDED", capability_id=consumed.capability_id,
        )
    db.refresh(operation)
    assert operation.state == "DISPATCHED", "state must be left exactly as it was -- never silently updated"


# === Recovery credential cannot initiate or retry execution ====================


def test_operation_observe_permission_grants_no_execution_permission():
    """The real, testable proof: Reviewer holds Permission.OPERATION_
    OBSERVE and holds neither CAPABILITY_ISSUE nor CAPABILITY_VERIFY --
    observation and execution are genuinely separate credentials, not
    the same one renamed. Deliberately Reviewer, not Auditor: granting
    OPERATION_OBSERVE to Auditor was tried first and reverted after it
    broke that role's own pre-existing, separately tested invariant
    (test_auditor_is_strictly_read_only in test_rbac_permissions.py) --
    recording an observation is a write, which a strictly-read-only role
    must never be able to do, regardless of how narrow that write is."""
    assert has_permission(Role.REVIEWER, Permission.OPERATION_OBSERVE) is True
    assert has_permission(Role.REVIEWER, Permission.CAPABILITY_ISSUE) is False
    assert has_permission(Role.REVIEWER, Permission.CAPABILITY_VERIFY) is False
    assert has_permission(Role.AUDITOR, Permission.OPERATION_OBSERVE) is False, "Auditor must stay strictly read-only"


def test_every_operations_route_is_gated_by_operation_observe_specifically():
    """Structural proof, not merely a convention: every route this
    milestone added is gated by require_permission(Permission.
    OPERATION_OBSERVE), introspected directly off the real FastAPI route
    table (mirrors tests/unit/test_route_permission_gates.py's own
    _all_api_routes/_is_gated helpers)."""
    from fastapi.routing import APIRoute

    from app.main import app

    def _all_routes(routes):
        for route in routes:
            if type(route).__name__ == "_IncludedRouter":
                yield from _all_routes(route.original_router.routes)
            elif isinstance(route, APIRoute):
                yield route

    operations_routes = [r for r in _all_routes(app.router.routes) if r.path.startswith("/v1/operations") or r.path == "/v1/decisions/{decision_id}/operation"]
    assert len(operations_routes) == 5, f"expected 5 operations routes, found {len(operations_routes)}: {[r.path for r in operations_routes]}"
    for route in operations_routes:
        gated_by_operation_observe = any(
            "require_permission" in getattr(dep.call, "__qualname__", "") for dep in route.dependant.dependencies
        )
        assert gated_by_operation_observe, f"{route.path} is not gated by require_permission"


def test_record_observation_has_no_code_path_to_issue_or_consume_a_capability():
    """Structural, not behavioural: operation_service.py's own module
    namespace never imports capability_service at all -- there is no
    name in scope record_observation could call to issue, verify, or
    consume a Capability, dispatch, or retry, even if its own logic were
    buggy in some other way."""
    import app.services.operation_service as op_svc_module

    assert "capability_service" not in vars(op_svc_module)
    assert "issue_capability_for_decision" not in vars(op_svc_module)
    assert "verify_and_consume_capability" not in vars(op_svc_module)


# === Duplicate, delayed, mismatched, and contradictory evidence ================


def test_duplicate_observation_is_idempotent(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DUPLICATE"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    order = _order_action(op_id)
    kwargs = dict(
        enforcement_binding_id=binding.id, material_action_digest=order.digest(),
        canonical_action_digest=intent.canonical_action_digest, destination=DESTINATION,
        status="SUCCEEDED", capability_id=consumed.capability_id,
    )
    op1, r1, _ = operation_service.record_observation(db, org.id, operation.id, identity, **kwargs)
    op2, r2, _ = operation_service.record_observation(db, org.id, operation.id, identity, **kwargs)
    assert r1.id == r2.id, "an identical duplicate report must resolve to the same receipt, not a second row"
    assert op2.state == "COMMITTED"


def test_contradictory_evidence_raises_conflict_not_silent_rewrite(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-CONTRADICTORY"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    order = _order_action(op_id)
    operation_service.record_observation(
        db, org.id, operation.id, identity, enforcement_binding_id=binding.id,
        material_action_digest=order.digest(), canonical_action_digest=intent.canonical_action_digest,
        destination=DESTINATION, status="SUCCEEDED", capability_id=consumed.capability_id, detail="first report",
    )
    from app.services.execution_receipt_service import ExecutionReceiptConflictError

    # `detail` alone is deliberately NON-material (ExecutionReceipt's own
    # docstring), so two reports differing only in free text are a
    # legitimate duplicate, not a contradiction -- confirmed by hitting
    # IDEMPOTENT_RETURN before this fix. A genuine contradiction varies a
    # MATERIAL field (capability_id) while keeping status identical, so
    # the same (integration, environment, external_operation_id, status)
    # lookup key finds the prior row and its digest now disagrees.
    with pytest.raises(ExecutionReceiptConflictError):
        operation_service.record_observation(
            db, org.id, operation.id, identity, enforcement_binding_id=binding.id,
            material_action_digest=order.digest(), canonical_action_digest=intent.canonical_action_digest,
            destination=DESTINATION, status="SUCCEEDED", capability_id=None, detail="CONTRADICTS the first report",
        )
    db.refresh(operation)
    assert operation.state == "COMMITTED", "history is never silently rewritten by a conflicting report"


def test_mismatched_material_action_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-MISMATCHED-MATERIAL-ACTION"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    wrong_order = _order_action(op_id, buyer_account="ACCT-DIFFERENT")
    with pytest.raises(operation_service.MaterialActionMismatchError):
        operation_service.record_observation(
            db, org.id, operation.id, identity, enforcement_binding_id=binding.id,
            material_action_digest=wrong_order.digest(), canonical_action_digest=intent.canonical_action_digest,
            destination=DESTINATION, status="SUCCEEDED",
        )


def test_mismatched_destination_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-MISMATCHED-DESTINATION"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    order = _order_action(op_id)
    operation_service.record_observation(
        db, org.id, operation.id, identity, enforcement_binding_id=binding.id,
        material_action_digest=order.digest(), canonical_action_digest=intent.canonical_action_digest,
        destination=DESTINATION, status="ACCEPTED", capability_id=consumed.capability_id,
    )
    from app.services.execution_receipt_service import ExecutionReceiptRejectionError

    with pytest.raises(ExecutionReceiptRejectionError, match="destination_mismatch"):
        operation_service.record_observation(
            db, org.id, operation.id, identity, enforcement_binding_id=binding.id,
            material_action_digest=order.digest(), canonical_action_digest=intent.canonical_action_digest,
            destination="synthetic:a-completely-different-destination", status="SUCCEEDED", capability_id=consumed.capability_id,
        )


# === Fresh authorization exists, replacement remains unsafe =====================


def test_fresh_authorization_exists_but_replacement_remains_unsafe(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-FRESH-AUTH-UNSAFE"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    # Outcome never resolved -- no observation ever recorded.
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "UNSAFE_UNRESOLVED"

    # AUTHORITY for a genuinely new attempt exists (a different, fresh
    # agent, current policy unchanged) -- proven separately, and does
    # NOT change the safety verdict above.
    identity2, _cv2, binding2, fresh_agent = _scenario(db, org.id)
    replacement_op_id = f"{op_id}-REPLACEMENT"
    _intent2, replacement_decision, _e2 = runtime_svc.submit_attested_intent(
        db, identity2, enforcement_binding_id=binding2.id, origin_agent_id=fresh_agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
        amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
        requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=replacement_op_id,
    )
    assert replacement_decision.outcome == "ALLOW", "fresh authority is genuinely grantable"
    safety_after_fresh_authority = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety_after_fresh_authority.safety == "UNSAFE_UNRESOLVED", "a fresh authorization existing elsewhere never changes THIS operation's own safety verdict"
    _trace("product", "fresh_authority_unsafe_replacement", operation_record_id=operation.id, replacement_decision_outcome=replacement_decision.outcome, safety=safety_after_fresh_authority.safety)


# === Terminal non-commit and duplicate-prevention guarantee: the two paths to SAFE ==


def test_terminal_non_commit_makes_replacement_safe(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-TERMINAL-NON-COMMIT"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    order = _order_action(op_id)
    updated_operation, _receipt, result = operation_service.record_observation(
        db, org.id, operation.id, identity, enforcement_binding_id=binding.id,
        material_action_digest=order.digest(), canonical_action_digest=intent.canonical_action_digest,
        destination=DESTINATION, status="FAILED", capability_id=consumed.capability_id,
    )
    assert result.outcome == "EXECUTION_FAILED"
    assert updated_operation.state == "TERMINALLY_NOT_COMMITTED"
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "SAFE_TERMINAL_NON_COMMIT_PROVEN"


def test_duplicate_prevention_guarantee_makes_replacement_safe(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DUP-PREVENTION-GUARANTEE"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    # Outcome unresolved -- yet a HUMAN-documented, scoped, time-bound
    # guarantee is recorded (never auto-inferred).
    operation_service.record_destination_duplicate_prevention_guarantee(
        db, org.id, operation.id, destination=DESTINATION,
        scope_description=f"Destination-confirmed idempotency key, scoped to external_operation_id={op_id!r} only, per vendor support ticket #4471",
        retention_until=datetime.now(timezone.utc) + timedelta(days=30), documented_by="ops-team@example.com",
    )
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "SAFE_DUPLICATE_PREVENTION_GUARANTEED"


def test_duplicate_prevention_guarantee_requires_scope_and_future_retention(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DUP-PREVENTION-INVALID"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    with pytest.raises(ValueError, match="scope_description"):
        operation_service.record_destination_duplicate_prevention_guarantee(
            db, org.id, operation.id, destination=DESTINATION, scope_description="",
            retention_until=datetime.now(timezone.utc) + timedelta(days=30), documented_by="ops-team@example.com",
        )
    with pytest.raises(ValueError, match="retention_until"):
        operation_service.record_destination_duplicate_prevention_guarantee(
            db, org.id, operation.id, destination=DESTINATION, scope_description="a generic idempotency claim with no real scope",
            retention_until=datetime.now(timezone.utc) - timedelta(days=1), documented_by="ops-team@example.com",
        )


# === Rerun of the two frozen recovery schedules, through the new product layer ==


def test_rerun_schedule_1_late_committed_outcome_through_new_product_layer(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=OPERATION_ID)
    assert operation.state == "AUTHORIZED"
    _trace("1-rerun", "execution_authority_valid", operation_record_id=operation.id, state=operation.state)

    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    db.refresh(operation)
    assert operation.state == "DISPATCHED"
    _trace("1-rerun", "operation_attempted", operation_record_id=operation.id, state=operation.state)

    destination = FakeDestination(DestinationBehaviour.COMMIT_NO_RECEIPT)
    destination.attempt(OPERATION_ID)
    _trace("1-rerun", "destination_commit_no_receipt", effect_count=1, evidence_source="synthetic_destination_internal_state (test harness ground truth)")

    agent_service.revoke_agent(db, agent.id, reason="pending investigation")
    _trace("1-rerun", "execution_authority_revoked", agent_id=agent.id)

    late = destination.late_authoritative_observation()
    assert late == "COMMITTED"
    order = _order_action(OPERATION_ID)
    updated_operation, receipt, result = operation_service.record_observation(
        db, org.id, operation.id, identity, enforcement_binding_id=binding.id,
        material_action_digest=order.digest(), canonical_action_digest=intent.canonical_action_digest,
        destination=DESTINATION, status="SUCCEEDED", capability_id=consumed.capability_id,
    )
    assert result.outcome == "MATCHED"
    assert updated_operation.state == "COMMITTED"
    _trace("1-rerun", "reconciled_matched_and_operation_committed", operation_record_id=operation.id, state=updated_operation.state, receipt_id=receipt.id, effect_count=1)

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
            _expected_constraints(), environment=binding.environment,
            enforcement_binding_id=binding.id, expected_organization_id=org.id,
        )
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    _trace("1-rerun", "final_state", operation_state=updated_operation.state, replacement_safety=safety.safety, effect_count=1)


def test_rerun_schedule_2_outcome_remains_unknown_through_new_product_layer(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-SCHEDULE-2-RERUN"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )

    destination = FakeDestination(DestinationBehaviour.NOT_FOUND_NOW)
    response = destination.attempt(op_id)
    assert response == "NOT_FOUND_NOW"
    _trace("2-rerun", "attempt_not_found_now", destination_observation="NOT_FOUND_NOW", effect_count="UNKNOWN")

    agent_service.revoke_agent(db, agent.id, reason="revoked without terminal outcome evidence")
    db.refresh(operation)
    assert operation.state == "DISPATCHED"
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "UNSAFE_UNRESOLVED"
    _trace("2-rerun", "historical_outcome_unresolved", operation_state=operation.state, safety=safety.safety, effect_count="UNKNOWN")

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
            _expected_constraints(), environment=binding.environment,
            enforcement_binding_id=binding.id, expected_organization_id=org.id,
        )
    _trace("2-rerun", "no_auto_retry_no_release", operation_state=operation.state, safety=safety.safety)
    _trace(
        "2-rerun", "replacement_conclusion", destination_terminal_non_commit_proof="NOT_OBTAINED",
        destination_duplicate_prevention_guarantee="NOT_DOCUMENTED", conclusion="REPLACEMENT_REMAINS_UNSAFE",
    )
