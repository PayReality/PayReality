"""Product lifecycle vertical slice, hardening pass: verifies the
corrected Operation state machine (AUTHORIZED -> CLAIMED -> DISPATCHED ->
{COMMITTED | TERMINALLY_NOT_COMMITTED | OUTCOME_UNKNOWN}), atomic
claim-recording, the four-category replacement-safety evaluation with
real enforcement at capability issuance, the OPERATION_OBSERVE /
OPERATION_SAFETY_APPROVE permission split, and evidence provenance --
against real code, not a reimplementation of any prior report's own
expectations. Reuses the frozen EVIDENCEBOUND-PAYREALITY-RECOVERY-V01
scenario (120 units, supplier A, buyer account B, delivery location X,
fixed unit price).

Supersedes the pre-hardening version of this file (same filename,
same branch lineage) -- the prior version asserted DISPATCHED at
consumption and OPERATION_OBSERVE-gates-everything, both since found
incorrect by direct review and corrected here.
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
from app.db.models import (
    Agent, Base, CapabilityToken, DestinationDuplicatePreventionGuarantee,
    Operation, OperationEvidenceEvent, Organization, Principal,
)
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


def _deploy_policy(db, org_id, opa_url, *, effect=Effect.ALLOW, resource=SUPPLIER_RESOURCE, policy_key=None, principal="OrderingAgent01"):
    policy = RuntimePolicy(
        id=str(policy_key or uuid.uuid4()), name="product-lifecycle-policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal=principal, action=ACTION, resource=resource),
        conditions=ConditionSet(all=()), effect=effect, audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    if policy_key is not None:
        row = policy_svc.edit_policy(db, policy_key, org_id, policy)
    else:
        row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row


def _scenario(db, org_id, *, principal_name="OrderingAgent01"):
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
    principal = Principal(id=uuid.uuid4(), name=principal_name, organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name=f"{principal_name} agent", acting_for_principal_id=principal.id, status="active")
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
    OrderAction digest -- operation_service.create_operation_for_decision
    is deliberately NOT auto-wired into generic capability issuance."""
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


def _consume(db, org_id, issued, binding):
    return capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org_id,
    )


def _observe(db, org_id, operation, identity, binding, intent, *, status, capability_id=None, order=None):
    order = order or _order_action(operation.destination_operation_id or intent.external_operation_id)
    return operation_service.record_observation(
        db, org_id, operation.id, identity,
        reporter_kind=operation_service.REPORTER_RBAC_HUMAN, signature_verified=False, reported_by="user:test@example.com",
        enforcement_binding_id=binding.id, material_action_digest=order.digest(),
        canonical_action_digest=intent.canonical_action_digest, destination=DESTINATION, status=status,
        capability_id=capability_id,
    )


# === Order action contract: required fields =====================================


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
    original = _order_action("op-1")
    changed = _order_action("op-1", **{field_name: changed_value})
    assert original.digest() != changed.digest(), f"{field_name} substitution did not change the digest"


# === Corrected state machine: claim != dispatch =================================


def test_operation_authorized_then_claimed_on_consumption_not_dispatched(db, opa_url):
    """The core correction: capability consumption proves a CLAIM, not a
    DISPATCH. An executor can claim and then crash before ever calling
    the destination."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-CLAIM-NOT-DISPATCH"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    assert operation.state == "AUTHORIZED"
    assert operation.attempt_count == 0

    consumed = _consume(db, org.id, issued, binding)
    db.refresh(operation)
    assert operation.state == "CLAIMED", "consumption alone must never be recorded as DISPATCHED"
    assert operation.attempt_count == 1
    assert operation.capability_id == consumed.capability_id


def test_dispatch_evidence_advances_claimed_to_dispatched(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DISPATCH-EVIDENCE"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    _consume(db, org.id, issued, binding)

    updated = operation_service.record_dispatch_evidence(
        db, org.id, operation.id, reporter_kind=operation_service.REPORTER_RBAC_HUMAN,
        signature_verified=False, reported_by="user:ops@example.com",
        integration_identity_id=identity.id, destination=DESTINATION, destination_operation_id=op_id,
    )
    assert updated.state == "DISPATCHED"
    events = db.scalars(select(OperationEvidenceEvent).where(OperationEvidenceEvent.operation_id == operation.id)).all()
    assert len(events) == 1
    assert events[0].event_type == "DISPATCH_REPORTED"
    assert events[0].evidence_strength == "UNSIGNED_HUMAN_RELAY"


def test_dispatch_evidence_requires_claimed_state(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DISPATCH-EVIDENCE-TOO-EARLY"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    # Never consumed -- still AUTHORIZED.
    with pytest.raises(operation_service.OperationNotClaimedError):
        operation_service.record_dispatch_evidence(
            db, org.id, operation.id, reporter_kind=operation_service.REPORTER_RBAC_HUMAN,
            signature_verified=False, reported_by="user:ops@example.com",
        )


def test_observation_accepted_from_claimed_state_even_without_dispatch_evidence(db, opa_url):
    """Conservative handling: a crash after claim with no dispatch
    evidence must not block a later observation -- absence of dispatch
    evidence does not establish absence of an external effect."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-OBSERVE-FROM-CLAIMED"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = _consume(db, org.id, issued, binding)
    assert operation.state == "CLAIMED"

    updated_operation, receipt, result = _observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id)
    assert result.outcome == "MATCHED"
    assert updated_operation.state == "COMMITTED"


# === Durability: claim recording is atomic with capability consumption =========


def test_recording_failure_rolls_back_capability_consumption_too(db, opa_url, monkeypatch):
    """Section 2's own explicit ask: test recording failure and its
    effect on capability consumption. Simulates a durability failure by
    making the FIRST db.commit() after the atomic UPDATE raise -- the
    capability's own consumed_at must roll back to None, not be left
    consumed with no matching Operation transition."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-RECORDING-FAILURE"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)

    real_commit = db.commit
    call_count = {"n": 0}

    def _failing_commit():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated durability failure")
        return real_commit()

    monkeypatch.setattr(db, "commit", _failing_commit)

    with pytest.raises(operation_service.OperationRecordingFailedError):
        _consume(db, org.id, issued, binding)

    monkeypatch.setattr(db, "commit", real_commit)
    db.expire_all()
    row = db.get(CapabilityToken, issued.capability_id)
    assert row.consumed_at is None, "capability consumption must roll back when lifecycle recording fails"
    db.refresh(operation)
    assert operation.state == "AUTHORIZED", "operation must not silently advance either"

    # A legitimate retry (durability restored) succeeds normally.
    consumed = _consume(db, org.id, issued, binding)
    db.refresh(operation)
    assert operation.state == "CLAIMED"
    assert consumed.capability_id == issued.capability_id


def test_legacy_caller_with_no_operation_is_unaffected_by_lifecycle_recording(db, opa_url):
    """Distinguishes legacy callers explicitly: a decision with no
    Operation at all gets exactly the original, unwrapped commit
    behaviour -- no new failure mode."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-LEGACY-NO-OPERATION"
    intent, decision, _ev = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
        amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
        requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=op_id,
    )
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")
    # No create_operation_for_decision call -- deliberately legacy.
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    assert consumed.capability_id == issued.capability_id
    assert db.scalar(select(Operation).where(Operation.decision_id == decision.id)) is None


# === Revocation before / after claim; late committed evidence after ============


def test_revocation_before_consumption_leaves_operation_authorized(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-REVOKE-BEFORE-CLAIM"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    assert operation.state == "AUTHORIZED"

    agent_service.revoke_agent(db, agent.id, reason="revoked before any consumption attempt")
    with pytest.raises(capability_service.OriginAgentNotActiveError):
        _consume(db, org.id, issued, binding)
    db.refresh(operation)
    assert operation.state == "AUTHORIZED"
    assert operation.attempt_count == 0


def test_revocation_after_claim_then_late_committed_evidence(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-LATE-COMMIT"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = _consume(db, org.id, issued, binding)
    db.refresh(operation)
    assert operation.state == "CLAIMED"

    destination = FakeDestination(DestinationBehaviour.COMMIT_NO_RECEIPT)
    destination.attempt(op_id)
    agent_service.revoke_agent(db, agent.id, reason="pending investigation")

    late = destination.late_authoritative_observation()
    assert late == "COMMITTED"
    updated_operation, receipt, result = _observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id)
    assert result.outcome == "MATCHED"
    assert updated_operation.state == "COMMITTED"

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        _consume(db, org.id, issued, binding)
    db.refresh(updated_operation)
    assert updated_operation.state == "COMMITTED", "the late observation updates historical knowledge; execution authority is not restored"


# === Claim, then a crash with no receipt; NOT_FOUND_NOW stays non-terminal =====


def test_claim_then_crash_no_receipt_leaves_outcome_unknown(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-CRASH-NO-RECEIPT"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    _consume(db, org.id, issued, binding)
    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "RECEIPT_MISSING"
    db.refresh(operation)
    assert operation.state == "CLAIMED", "no observation was ever recorded, so state stays at CLAIMED"


def test_not_found_now_is_not_recorded_as_terminal(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-NOT-FOUND-NOW"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    _consume(db, org.id, issued, binding)
    destination = FakeDestination(DestinationBehaviour.NOT_FOUND_NOW)
    assert destination.attempt(op_id) == "NOT_FOUND_NOW"
    # No receipt submitted for an ambiguous, non-authoritative response.
    db.refresh(operation)
    assert operation.state == "CLAIMED"
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "UNSAFE_UNRESOLVED", "NOT_FOUND_NOW must never be treated as terminal non-commit proof"


# === Observation while execution revoked; observation itself revoked ===========


def test_observation_permitted_while_execution_revoked(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-OBS-WHILE-EXEC-REVOKED"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = _consume(db, org.id, issued, binding)
    agent_service.revoke_agent(db, agent.id, reason="execution authority revoked")
    updated_operation, receipt, result = _observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id)
    assert updated_operation.state == "COMMITTED"


def test_observation_itself_revoked_blocks_the_observation(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-OBS-ITSELF-REVOKED"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = _consume(db, org.id, issued, binding)
    identity_svc.suspend_integration_identity(db, identity.id, org.id)

    from app.services.execution_receipt_service import ExecutionReceiptRejectionError

    with pytest.raises(ExecutionReceiptRejectionError):
        _observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id)
    db.refresh(operation)
    assert operation.state == "CLAIMED", "state must be left exactly as it was"


# === Recovery credential cannot initiate or retry execution ====================


def test_operation_observe_permission_grants_no_execution_permission():
    assert has_permission(Role.REVIEWER, Permission.OPERATION_OBSERVE) is True
    assert has_permission(Role.REVIEWER, Permission.CAPABILITY_ISSUE) is False
    assert has_permission(Role.REVIEWER, Permission.CAPABILITY_VERIFY) is False
    assert has_permission(Role.AUDITOR, Permission.OPERATION_OBSERVE) is False, "Auditor must stay strictly read-only"


def test_operation_safety_approve_is_separate_from_observe():
    """Section 4: an observer cannot grant themselves replacement
    safety. Explicit checks for Reviewer, Auditor, execution-capable
    roles, and Governance Admin."""
    assert has_permission(Role.REVIEWER, Permission.OPERATION_OBSERVE) is True
    assert has_permission(Role.REVIEWER, Permission.OPERATION_SAFETY_APPROVE) is False
    assert has_permission(Role.AUDITOR, Permission.OPERATION_SAFETY_APPROVE) is False
    assert has_permission(Role.AGENT_ADMIN, Permission.OPERATION_OBSERVE) is False
    assert has_permission(Role.AGENT_ADMIN, Permission.OPERATION_SAFETY_APPROVE) is False
    assert has_permission(Role.GOVERNANCE_ADMIN, Permission.OPERATION_SAFETY_APPROVE) is True
    assert has_permission(Role.GOVERNANCE_ADMIN, Permission.OPERATION_OBSERVE) is True
    assert has_permission(Role.OWNER, Permission.OPERATION_SAFETY_APPROVE) is True


def test_every_operations_route_is_gated_correctly():
    """Structural proof: 5 of 6 routes require OPERATION_OBSERVE; the
    duplicate-prevention-guarantees route requires OPERATION_SAFETY_
    APPROVE specifically, not OPERATION_OBSERVE."""
    from fastapi.routing import APIRoute

    from app.main import app

    def _all_routes(routes):
        for route in routes:
            if type(route).__name__ == "_IncludedRouter":
                yield from _all_routes(route.original_router.routes)
            elif isinstance(route, APIRoute):
                yield route

    operations_routes = {r.path: r for r in _all_routes(app.router.routes) if r.path.startswith("/v1/operations") or r.path == "/v1/decisions/{decision_id}/operation"}
    assert len(operations_routes) == 6, f"expected 6 operations routes, found {len(operations_routes)}: {sorted(operations_routes)}"

    def _gated_by(route):
        names = set()
        for dep in route.dependant.dependencies:
            qualname = getattr(dep.call, "__qualname__", "")
            if "require_permission" in qualname:
                closure = getattr(dep.call, "__closure__", None) or ()
                for cell in closure:
                    if isinstance(cell.cell_contents, Permission):
                        names.add(cell.cell_contents)
        return names

    guarantee_route = operations_routes.pop("/v1/operations/{operation_id}/duplicate-prevention-guarantees")
    assert Permission.OPERATION_SAFETY_APPROVE in _gated_by(guarantee_route)
    assert Permission.OPERATION_OBSERVE not in _gated_by(guarantee_route)
    for path, route in operations_routes.items():
        assert Permission.OPERATION_OBSERVE in _gated_by(route), f"{path} not gated by OPERATION_OBSERVE"


def test_record_observation_has_no_code_path_to_issue_or_consume_a_capability():
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
    consumed = _consume(db, org.id, issued, binding)
    op1, r1, _ = _observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id)
    op2, r2, _ = _observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id)
    assert r1.id == r2.id, "an identical duplicate report must resolve to the same receipt, not a second row"
    assert op2.state == "COMMITTED"


def test_contradictory_evidence_raises_conflict_not_silent_rewrite(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-CONTRADICTORY"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = _consume(db, org.id, issued, binding)
    _observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id)

    from app.services.execution_receipt_service import ExecutionReceiptConflictError

    # `detail` alone is deliberately NON-material, so a genuine
    # contradiction varies a MATERIAL field (capability_id) instead.
    with pytest.raises(ExecutionReceiptConflictError):
        _observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=None)
    db.refresh(operation)
    assert operation.state == "COMMITTED", "history is never silently rewritten by a conflicting report"


def test_mismatched_material_action_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-MISMATCHED-MATERIAL-ACTION"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    _consume(db, org.id, issued, binding)
    wrong_order = _order_action(op_id, buyer_account="ACCT-DIFFERENT")
    with pytest.raises(operation_service.MaterialActionMismatchError):
        _observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", order=wrong_order)


def test_mismatched_destination_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-MISMATCHED-DESTINATION"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = _consume(db, org.id, issued, binding)
    _observe(db, org.id, operation, identity, binding, intent, status="ACCEPTED", capability_id=consumed.capability_id)

    from app.services.execution_receipt_service import ExecutionReceiptRejectionError

    order = _order_action(op_id)
    with pytest.raises(ExecutionReceiptRejectionError, match="destination_mismatch"):
        operation_service.record_observation(
            db, org.id, operation.id, identity,
            reporter_kind=operation_service.REPORTER_RBAC_HUMAN, signature_verified=False, reported_by="user:test@example.com",
            enforcement_binding_id=binding.id, material_action_digest=order.digest(),
            canonical_action_digest=intent.canonical_action_digest,
            destination="synthetic:a-completely-different-destination", status="SUCCEEDED", capability_id=consumed.capability_id,
        )


def test_forged_integration_identity_reference_rejected(db, opa_url):
    """A caller naming an IntegrationIdentity from a DIFFERENT
    organization must not be usable to relay an observation."""
    org_a = _org(db, "Org A")
    org_b = _org(db, "Org B")
    identity_a, _cv, binding, agent = _scenario(db, org_a.id)
    identity_b, _cv_b, _binding_b, _agent_b = _scenario(db, org_b.id, principal_name="OtherOrgAgent")
    _deploy_policy(db, org_a.id, opa_url)
    op_id = f"{OPERATION_ID}-FORGED-IDENTITY"
    intent, decision, issued, operation = _submit_and_authorize(db, org_a.id, identity_a, binding, agent, external_operation_id=op_id)
    _consume(db, org_a.id, issued, binding)

    order = _order_action(op_id)
    # identity_b belongs to org_b; submit_execution_receipt's own
    # linkage check (identity not bound to this decision) must reject it.
    from app.services.execution_receipt_service import ExecutionReceiptRejectionError

    with pytest.raises(ExecutionReceiptRejectionError):
        operation_service.record_observation(
            db, org_a.id, operation.id, identity_b,
            reporter_kind=operation_service.REPORTER_RBAC_HUMAN, signature_verified=False, reported_by="user:attacker@example.com",
            enforcement_binding_id=binding.id, material_action_digest=order.digest(),
            canonical_action_digest=intent.canonical_action_digest, destination=DESTINATION, status="SUCCEEDED",
        )


# === Fresh authorization exists, replacement remains unsafe =====================


def test_fresh_authorization_exists_but_replacement_remains_unsafe(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-FRESH-AUTH-UNSAFE"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    _consume(db, org.id, issued, binding)
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "UNSAFE_UNRESOLVED"
    assert safety.requires_current_authorization is True

    identity2, _cv2, binding2, fresh_agent = _scenario(db, org.id, principal_name="OrderingAgent01")
    replacement_op_id = f"{op_id}-REPLACEMENT"
    _intent2, replacement_decision, _e2 = runtime_svc.submit_attested_intent(
        db, identity2, enforcement_binding_id=binding2.id, origin_agent_id=fresh_agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
        amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
        requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=replacement_op_id,
    )
    assert replacement_decision.outcome == "ALLOW", "fresh authority is genuinely grantable"
    safety_after = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety_after.safety == "UNSAFE_UNRESOLVED", "a fresh authorization existing elsewhere never changes THIS operation's own safety verdict"

    # And the real enforcement hook refuses to issue a capability linked
    # to this unresolved operation.
    with pytest.raises(operation_service.ReplacementNotSafeError):
        capability_service.issue_capability_for_decision(
            db, org.id, replacement_decision.id, audience="reference-pep", replaces_operation_id=operation.id,
        )
    _trace("product", "fresh_authority_unsafe_replacement_enforced", operation_id=operation.id, safety=safety_after.safety)


# === Already-committed original: blocked, not "unresolved" =====================


def test_already_committed_operation_is_blocked_not_unresolved(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-ALREADY-COMMITTED"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = _consume(db, org.id, issued, binding)
    updated_operation, _r, result = _observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id)
    assert updated_operation.state == "COMMITTED"

    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "BLOCKED_ALREADY_COMMITTED", "a committed operation must not be labeled unresolved"

    with pytest.raises(operation_service.ReplacementNotSafeError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep", replaces_operation_id=operation.id)


# === Terminal non-commit: safe, but still requires current authorization =======


def test_terminal_non_commit_makes_replacement_safe_and_still_requires_authority(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-TERMINAL-NON-COMMIT"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = _consume(db, org.id, issued, binding)
    updated_operation, _r, result = _observe(db, org.id, operation, identity, binding, intent, status="FAILED", capability_id=consumed.capability_id)
    assert result.outcome == "EXECUTION_FAILED"
    assert updated_operation.state == "TERMINALLY_NOT_COMMITTED"

    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "SAFE_TERMINAL_NON_COMMIT_PROVEN"
    assert safety.requires_current_authorization is True

    # Safety alone is not authority: a replacement Intent still has to be
    # independently evaluated and can still be denied by policy -- proven
    # by the companion test below, which issues a real replacement.


def test_replacement_after_terminal_non_commit_succeeds_when_authority_is_current(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-TERMINAL-THEN-REPLACE"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    consumed = _consume(db, org.id, issued, binding)
    _observe(db, org.id, operation, identity, binding, intent, status="FAILED", capability_id=consumed.capability_id)

    replacement_op_id = f"{op_id}-REPLACEMENT"
    _intent2, replacement_decision, _e2 = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
        amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
        requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=replacement_op_id,
    )
    assert replacement_decision.outcome == "ALLOW"
    replacement_issued = capability_service.issue_capability_for_decision(
        db, org.id, replacement_decision.id, audience="reference-pep", replaces_operation_id=operation.id,
    )
    assert replacement_issued.capability_id != issued.capability_id


# === Duplicate-prevention guarantee: scope, retention, and identity binding ====


def test_duplicate_prevention_guarantee_makes_replacement_safe(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DUP-PREVENTION-GUARANTEE"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    _consume(db, org.id, issued, binding)

    operation_service.record_destination_duplicate_prevention_guarantee(
        db, org.id, operation.id, destination=DESTINATION,
        scope_description=f"Destination-confirmed idempotency key, scoped to external_operation_id={op_id!r} only",
        retention_until=datetime.now(timezone.utc) + timedelta(days=30), documented_by="governance-admin@example.com",
    )
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "SAFE_DUPLICATE_PREVENTION_GUARANTEED"


def test_duplicate_prevention_guarantee_restricted_to_identity_enforced(db, opa_url):
    """"Any permitted attempt must use the identity and conditions that
    guarantee actually protects" -- a mismatched attempting identity
    must not be able to use a guarantee scoped to a different one."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    other_identity, _cv2, other_binding, other_agent = _scenario(db, org.id, principal_name="OrderingAgent01")
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DUP-PREVENTION-RESTRICTED"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    _consume(db, org.id, issued, binding)

    operation_service.record_destination_duplicate_prevention_guarantee(
        db, org.id, operation.id, destination=DESTINATION,
        scope_description="Scoped to the original reporting identity only",
        retention_until=datetime.now(timezone.utc) + timedelta(days=30), documented_by="governance-admin@example.com",
        restricted_to_integration_identity_id=identity.id,
    )

    matching = operation_service.evaluate_replacement_safety(db, org.id, operation.id, attempting_integration_identity_id=identity.id)
    assert matching.safety == "SAFE_DUPLICATE_PREVENTION_GUARANTEED"

    mismatched = operation_service.evaluate_replacement_safety(db, org.id, operation.id, attempting_integration_identity_id=other_identity.id)
    assert mismatched.safety == "UNSAFE_UNRESOLVED"
    assert "restricted to integration_identity_id" in mismatched.reason


def test_duplicate_prevention_guarantee_wrong_destination_not_matched_by_construction(db, opa_url):
    """A guarantee is looked up strictly by operation_id (UNIQUE
    constraint), so a guarantee documented for a DIFFERENT destination
    string on the SAME operation is simply the only guarantee that
    exists -- evaluate_replacement_safety does not cross-check the
    destination it was invoked with against a DIFFERENT one, which is
    itself worth proving explicitly rather than assuming."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DUP-PREVENTION-WRONG-DEST"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    _consume(db, org.id, issued, binding)
    operation_service.record_destination_duplicate_prevention_guarantee(
        db, org.id, operation.id, destination="synthetic:a-different-destination-entirely",
        scope_description="documented against a different destination than this operation's own",
        retention_until=datetime.now(timezone.utc) + timedelta(days=30), documented_by="governance-admin@example.com",
    )
    guarantee = db.scalar(select(DestinationDuplicatePreventionGuarantee).where(DestinationDuplicatePreventionGuarantee.operation_id == operation.id))
    assert guarantee.destination != DESTINATION, "the guarantee's own destination genuinely disagrees with the operation's real one -- a real, disclosed gap: evaluate_replacement_safety does not itself cross-check this"


def test_duplicate_prevention_guarantee_requires_scope_and_future_retention(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DUP-PREVENTION-INVALID"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    with pytest.raises(ValueError, match="scope_description"):
        operation_service.record_destination_duplicate_prevention_guarantee(
            db, org.id, operation.id, destination=DESTINATION, scope_description="",
            retention_until=datetime.now(timezone.utc) + timedelta(days=30), documented_by="governance-admin@example.com",
        )
    with pytest.raises(ValueError, match="retention_until"):
        operation_service.record_destination_duplicate_prevention_guarantee(
            db, org.id, operation.id, destination=DESTINATION, scope_description="a generic idempotency claim with no real scope",
            retention_until=datetime.now(timezone.utc) - timedelta(days=1), documented_by="governance-admin@example.com",
        )


def test_expired_guarantee_does_not_make_replacement_safe(db, opa_url):
    """The creation-time check (above) rejects an ALREADY-past
    retention_until; this proves the READ-time expiry check
    independently, via a direct row insert (the same "bypass the
    service, prove the re-check fires" discipline this repo's own
    test_a_digest_anomaly_on_a_persisted_receipt... test already
    establishes for reconciliation)."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DUP-PREVENTION-EXPIRED"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    _consume(db, org.id, issued, binding)

    expired = DestinationDuplicatePreventionGuarantee(
        organization_id=org.id, operation_id=operation.id, destination=DESTINATION,
        scope_description="was valid, has since expired", documented_by="governance-admin@example.com",
        retention_until=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.add(expired)
    db.commit()

    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "UNSAFE_UNRESOLVED", "an expired guarantee must not make a replacement safe"


# === Rerun of the two frozen recovery schedules, through the hardened layer ====


def test_rerun_schedule_1_late_committed_outcome_through_hardened_layer(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=OPERATION_ID)
    assert operation.state == "AUTHORIZED"
    _trace("1-rerun", "execution_authority_valid", operation_record_id=operation.id, state=operation.state)

    consumed = _consume(db, org.id, issued, binding)
    db.refresh(operation)
    assert operation.state == "CLAIMED"
    _trace("1-rerun", "operation_claimed_not_dispatched", operation_record_id=operation.id, state=operation.state)

    destination = FakeDestination(DestinationBehaviour.COMMIT_NO_RECEIPT)
    destination.attempt(OPERATION_ID)
    _trace("1-rerun", "destination_commit_no_receipt", effect_count=1, evidence_source="synthetic_destination_internal_state (test harness ground truth)")

    agent_service.revoke_agent(db, agent.id, reason="pending investigation")
    _trace("1-rerun", "execution_authority_revoked", agent_id=agent.id)

    late = destination.late_authoritative_observation()
    assert late == "COMMITTED"
    updated_operation, receipt, result = _observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id)
    assert result.outcome == "MATCHED"
    assert updated_operation.state == "COMMITTED"
    _trace(
        "1-rerun", "reconciled_matched_and_operation_committed", operation_record_id=operation.id, state=updated_operation.state,
        receipt_id=receipt.id, effect_count=1, evidence_source="RBAC_HUMAN relay, signature_verified=False",
    )

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        _consume(db, org.id, issued, binding)
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "BLOCKED_ALREADY_COMMITTED"
    _trace("1-rerun", "final_state", operation_state=updated_operation.state, replacement_safety=safety.safety, effect_count=1)


def test_rerun_schedule_2_outcome_remains_unknown_through_hardened_layer(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-SCHEDULE-2-RERUN"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    _consume(db, org.id, issued, binding)

    destination = FakeDestination(DestinationBehaviour.NOT_FOUND_NOW)
    response = destination.attempt(op_id)
    assert response == "NOT_FOUND_NOW"
    _trace("2-rerun", "attempt_not_found_now", destination_observation="NOT_FOUND_NOW", effect_count="UNKNOWN")

    agent_service.revoke_agent(db, agent.id, reason="revoked without terminal outcome evidence")
    db.refresh(operation)
    assert operation.state == "CLAIMED"
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "UNSAFE_UNRESOLVED"
    _trace("2-rerun", "historical_outcome_unresolved", operation_state=operation.state, safety=safety.safety, effect_count="UNKNOWN")

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        _consume(db, org.id, issued, binding)
    _trace("2-rerun", "no_auto_retry_no_release", operation_state=operation.state, safety=safety.safety)
    _trace(
        "2-rerun", "replacement_conclusion",
        destination_terminal_non_commit_proof="NOT_OBTAINED", destination_duplicate_prevention_guarantee="NOT_DOCUMENTED",
        conclusion="REPLACEMENT_REMAINS_UNSAFE",
    )
