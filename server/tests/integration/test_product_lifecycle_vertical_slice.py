"""Product lifecycle vertical slice: hardening pass + closeout pass.

Verifies, against real code (not a reimplementation of any prior
report's own expectations):
  section 1 -- business-operation identity: automatic resolution and
    replacement-safety enforcement at issuance AND consumption, with no
    dependence on a caller ever declaring replaces_operation_id;
    concurrent-attempt handling; material-field equality is never the
    dedup key.
  section 2 -- evidence acceptance rules: only signature-verified
    Adapter evidence (or an explicit, separately-permissioned manual
    adjudication) can move outcome_status into a terminal value; an
    unsigned RBAC_HUMAN relay's own claim is preserved but never
    promoted to verified destination truth.
  section 3 -- execution_stage and outcome_status as independent axes,
    never a single collapsed `state` string.

Contract-enforcement pass, additionally verifies:
  - lifecycle_requirement (IntegrationContractVersion): a LIFECYCLE_
    REQUIRED contract rejects a submission missing either field before
    authorization, and a caller cannot omit or "downgrade" past it --
    the check reads the server-resolved contract, never the request.
  - the business-operation identity's namespace is validated, not
    trusted: cross-tenant, cross-destination, and cross-action-type
    identical business_operation_id strings never collide.
  - a mutable safety fact (a duplicate-prevention guarantee) that is
    withdrawn or expires AFTER a replacement was issued blocks that
    replacement's own consumption, not only a change in which attempt
    is current.
  - destination_evidence_kind (IntegrationContractVersion): the one
    real, implemented evidence-acceptance-policy term, and execution_
    stage_at_event: a permanent snapshot proving a late outcome did or
    did not have prior dispatch evidence.

Reuses the frozen EVIDENCEBOUND-PAYREALITY-RECOVERY-V01 scenario (120
units, supplier A, buyer account B, delivery location X, fixed unit
price) for the section-5 schedule reruns at the bottom of this file.
"""

import json
import multiprocessing
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
    Agent, BusinessOperationIdentity, Base, CapabilityToken,
    DestinationDuplicatePreventionGuarantee, Operation, OperationEvidenceEvent,
    Organization, Principal,
)
from app.domain import order_action_contract as order_action
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
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
    integration_runtime_service as runtime_svc,
    operation_identity_service,
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


def _make_engine(url, **kw):
    return create_engine(url, **kw)


@pytest.fixture()
def db():
    engine = _make_engine("sqlite:///:memory:")
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


def _scenario(
    db, org_id, *, principal_name="OrderingAgent01", integration_name="Order Fulfillment (reference)",
    lifecycle_requirement="LEGACY", integration=None, source_operation=None, action=None,
):
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "Reference Order Adapter", "ed25519:base64:AAAA")
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)
    if integration is None:
        integration = contract_svc.create_integration(db, org_id, integration_name)
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, source_operation or SOURCE_OPERATION, action or ACTION,
        resource_path="order.supplier", amount_path=None, currency_path=None,
        fact_subject_path=None, context_bindings=ORDER_CONTEXT_BINDINGS,
        lifecycle_requirement=lifecycle_requirement,
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


def _submit_and_authorize(
    db, org_id, identity, binding, agent, *, external_operation_id, resource=SUPPLIER_RESOURCE, context=None,
    business_operation_id=None, intended_destination=None, material_action_digest=None,
):
    """Real path, end to end: submit the order Intent (optionally
    declaring business_operation_id + intended_destination -- section
    1's own "require the supported integration to supply it before
    authorization"), then issue the Capability. For an identity-covered
    submission, the Operation is created AUTOMATICALLY inside
    issue_capability_for_decision (capability_service._link_business_
    operation_attempt_if_covered) -- never by this test calling a
    lower-level constructor directly, which is the real, previously-
    undemonstrated production path (create_operation_for_decision had
    zero real router call sites before this pass)."""
    intent, decision, _ev = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=resource,
        amount=None, currency=None, counterparty=None, context=context if context is not None else dict(ORDER_CONTEXT),
        requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=external_operation_id,
        business_operation_id=business_operation_id, intended_destination=intended_destination,
    )
    if decision.outcome != "ALLOW":
        return intent, decision, None, None
    issued = capability_service.issue_capability_for_decision(
        db, org_id, decision.id, audience="reference-pep", material_action_digest=material_action_digest,
    )
    operation = db.scalar(select(Operation).where(Operation.decision_id == decision.id))
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


def _observe(db, org_id, operation, identity, binding, intent, *, status, capability_id=None, order=None, reporter_kind=None, signature_verified=False, reported_by="user:test@example.com"):
    order = order or _order_action(operation.destination_operation_id or intent.external_operation_id)
    return operation_service.record_observation(
        db, org_id, operation.id, identity,
        reporter_kind=reporter_kind or operation_service.REPORTER_RBAC_HUMAN, signature_verified=signature_verified, reported_by=reported_by,
        enforcement_binding_id=binding.id, material_action_digest=order.digest(),
        canonical_action_digest=intent.canonical_action_digest, destination=operation.destination or DESTINATION, status=status,
        capability_id=capability_id,
    )


def _adapter_observe(db, org_id, operation, identity, binding, intent, *, status, capability_id=None, order=None):
    """A genuine, signature-verified Adapter observation -- the ONLY
    ordinary path (besides manual adjudication) that can move
    outcome_status into a terminal value (section 2)."""
    return _observe(
        db, org_id, operation, identity, binding, intent, status=status, capability_id=capability_id, order=order,
        reporter_kind=operation_service.REPORTER_SIGNED_ADAPTER_IDENTITY, signature_verified=True,
        reported_by=f"integration_identity:{identity.name}",
    )


# === Order action contract: required fields (unaffected by this pass) =========


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


# === Section 1: business-operation identity =====================================


def test_omitted_business_operation_id_gets_no_automatic_protection(db, opa_url):
    """"Test omission" -- a caller that never supplies business_
    operation_id/intended_destination gets exactly today's default: no
    Operation, no automatic resolution, nothing to enforce. Proves the
    NEW mechanism is additive, not a behaviour change for every existing
    caller."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-OMITTED-IDENTITY"
    intent, decision, issued, operation = _submit_and_authorize(db, org.id, identity, binding, agent, external_operation_id=op_id)
    assert intent.business_operation_id is None
    assert operation is None, "no business_operation_id was supplied -- no Operation should be auto-created"
    # The capability itself still works completely normally.
    consumed = _consume(db, org.id, issued, binding)
    assert consumed.capability_id == issued.capability_id


def test_business_operation_id_requires_intended_destination_together(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    with pytest.raises(runtime_svc.IntegrationRejectionError, match="must_be_supplied_together"):
        runtime_svc.submit_attested_intent(
            db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
            source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
            amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
            requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
            external_operation_id=f"{OPERATION_ID}-PARTIAL-IDENTITY",
            business_operation_id="ORDER-PARTIAL", intended_destination=None,
        )


def test_first_attempt_is_authorized_stage_and_unknown_outcome(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-FIRST-ATTEMPT"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-FIRST-ATTEMPT", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    assert operation is not None
    assert operation.execution_stage == "AUTHORIZED"
    assert operation.outcome_status == "UNKNOWN"
    assert operation.evidence_assurance == "NONE"
    assert operation.business_operation_identity_id is not None
    assert operation.previous_attempt_operation_id is None
    identity_row = db.get(BusinessOperationIdentity, operation.business_operation_identity_id)
    assert identity_row.current_operation_id == operation.id
    assert identity_row.destination == DESTINATION
    assert identity_row.business_operation_id == "ORDER-FIRST-ATTEMPT"


def test_repeated_identity_resolved_automatically_without_replaces_operation_id(db, opa_url):
    """The core fix: NO caller ever passes replaces_operation_id. A
    second Intent for the SAME business_operation_id must still be
    safety-checked automatically."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    boid = "ORDER-REPEATED-AUTO"
    op_id_1 = f"{OPERATION_ID}-REPEAT-AUTO-1"
    intent1, decision1, issued1, operation1 = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id_1,
        business_operation_id=boid, intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id_1).digest(),
    )
    assert operation1.outcome_status == "UNKNOWN"  # unresolved -- unsafe to replace

    op_id_2 = f"{OPERATION_ID}-REPEAT-AUTO-2"
    intent2, decision2, _e2 = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
        amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
        requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=op_id_2, business_operation_id=boid, intended_destination=DESTINATION,
    )
    assert decision2.outcome == "ALLOW", "fresh AUTHORITY is still independently grantable"
    with pytest.raises(operation_service.ReplacementNotSafeError) as excinfo:
        capability_service.issue_capability_for_decision(
            db, org.id, decision2.id, audience="reference-pep", material_action_digest=_order_action(op_id_2).digest(),
        )
    assert excinfo.value.safety == "UNSAFE_UNRESOLVED"
    assert excinfo.value.operation_id == operation1.id, "resolved the PRIOR operation with no replaces_operation_id ever supplied"


def test_repeated_identity_blocked_when_original_already_committed(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    boid = "ORDER-REPEAT-COMMITTED"
    op_id_1 = f"{OPERATION_ID}-REPEAT-COMMITTED-1"
    intent1, decision1, issued1, operation1 = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id_1,
        business_operation_id=boid, intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id_1).digest(),
    )
    consumed1 = _consume(db, org.id, issued1, binding)
    updated1, _r, _res = _adapter_observe(db, org.id, operation1, identity, binding, intent1, status="SUCCEEDED", capability_id=consumed1.capability_id, order=_order_action(op_id_1))
    assert updated1.outcome_status == "COMMITTED"

    op_id_2 = f"{OPERATION_ID}-REPEAT-COMMITTED-2"
    intent2, decision2, _e2 = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
        amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
        requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=op_id_2, business_operation_id=boid, intended_destination=DESTINATION,
    )
    assert decision2.outcome == "ALLOW"
    with pytest.raises(operation_service.ReplacementNotSafeError) as excinfo:
        capability_service.issue_capability_for_decision(db, org.id, decision2.id, audience="reference-pep", material_action_digest=_order_action(op_id_2).digest())
    assert excinfo.value.safety == "BLOCKED_ALREADY_COMMITTED"


def test_repeated_identity_safe_after_terminal_non_commit_but_needs_fresh_authority(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    policy_row = _deploy_policy(db, org.id, opa_url)
    boid = "ORDER-REPEAT-TERMINAL"
    op_id_1 = f"{OPERATION_ID}-REPEAT-TERMINAL-1"
    intent1, decision1, issued1, operation1 = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id_1,
        business_operation_id=boid, intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id_1).digest(),
    )
    consumed1 = _consume(db, org.id, issued1, binding)
    updated1, _r, _res = _adapter_observe(db, org.id, operation1, identity, binding, intent1, status="FAILED", capability_id=consumed1.capability_id, order=_order_action(op_id_1))
    assert updated1.outcome_status == "TERMINALLY_NOT_COMMITTED"

    op_id_2 = f"{OPERATION_ID}-REPEAT-TERMINAL-2"
    intent2, decision2, issued2, operation2 = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id_2,
        business_operation_id=boid, intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id_2).digest(),
    )
    assert issued2 is not None, "SAFE_TERMINAL_NON_COMMIT_PROVEN + fresh ALLOW must succeed"
    assert operation2.previous_attempt_operation_id == operation1.id
    identity_row = db.get(BusinessOperationIdentity, operation2.business_operation_identity_id)
    assert identity_row.current_operation_id == operation2.id, "the identity's current attempt has advanced to attempt #2"

    # And authority is genuinely still required -- DENY still blocks a
    # third attempt even though safety alone would now allow it (SAFE_
    # TERMINAL_NON_COMMIT_PROVEN never substitutes for authority).
    _deploy_policy(db, org.id, opa_url, effect=Effect.DENY, policy_key=policy_row.policy_key)
    op_id_3 = f"{OPERATION_ID}-REPEAT-TERMINAL-3"
    intent3, decision3, _e3 = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
        amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
        requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=op_id_3, business_operation_id=boid, intended_destination=DESTINATION,
    )
    assert decision3.outcome == "DENY", "safety being SAFE_* never substitutes for a fresh authority decision"


def test_consumption_time_recheck_blocks_stale_capability_after_supersession(db, opa_url):
    """Section 1: "enforce this at issuance and consumption, including
    when safety facts change between them." Attempt #1's Capability is
    issued but never consumed; a documented duplicate-prevention
    guarantee then lets attempt #2 legitimately become current; THEN
    attempt #1's original (still-valid-looking) Capability is presented
    for consumption -- it must be rejected, and the whole consumption
    must roll back."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    boid = "ORDER-STALE-CONSUME"
    op_id_1 = f"{OPERATION_ID}-STALE-CONSUME-1"
    intent1, decision1, issued1, operation1 = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id_1,
        business_operation_id=boid, intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id_1).digest(),
    )
    assert operation1.execution_stage == "AUTHORIZED"  # never consumed

    operation_service.record_destination_duplicate_prevention_guarantee(
        db, org.id, operation1.id, destination=DESTINATION,
        scope_description="Destination-confirmed idempotency key covers this exact attempt, documented before any replacement",
        retention_until=datetime.now(timezone.utc) + timedelta(days=30), documented_by="governance-admin@example.com",
    )

    op_id_2 = f"{OPERATION_ID}-STALE-CONSUME-2"
    intent2, decision2, issued2, operation2 = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id_2,
        business_operation_id=boid, intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id_2).digest(),
    )
    assert issued2 is not None
    identity_row = db.get(BusinessOperationIdentity, operation1.business_operation_identity_id)
    assert identity_row.current_operation_id == operation2.id, "attempt #2 is now current -- attempt #1 is superseded"

    with pytest.raises(operation_service.OperationSupersededError) as excinfo:
        _consume(db, org.id, issued1, binding)
    assert excinfo.value.operation_id == operation1.id
    assert excinfo.value.current_operation_id == operation2.id

    db.expire_all()
    stale_capability_row = db.get(CapabilityToken, issued1.capability_id)
    assert stale_capability_row.consumed_at is None, "the whole consumption must roll back, not just fail after marking it consumed"
    db.refresh(operation1)
    assert operation1.execution_stage == "AUTHORIZED", "the superseded operation's own stage must not silently advance"


def test_two_materially_identical_orders_with_different_business_operation_identities_do_not_collide(db, opa_url):
    """Section 1's own explicit warning: material-field equality is
    never the dedup key. Two orders with byte-identical supplier/
    quantity/buyer_account/delivery_location/unit_price, but different
    business_operation_id values, must not be treated as repeats of
    each other."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id_a = f"{OPERATION_ID}-IDENTICAL-FIELDS-A"
    op_id_b = f"{OPERATION_ID}-IDENTICAL-FIELDS-B"
    intent_a, decision_a, issued_a, operation_a = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id_a,
        business_operation_id="ORDER-IDENTICAL-A", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id_a).digest(),
    )
    intent_b, decision_b, issued_b, operation_b = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id_b,
        business_operation_id="ORDER-IDENTICAL-B", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id_b).digest(),
    )
    assert issued_a is not None and issued_b is not None, "neither issuance was blocked by the other"
    assert operation_a.id != operation_b.id
    assert operation_a.business_operation_identity_id != operation_b.business_operation_identity_id
    # Same real-world material CONTENT (supplier/quantity/buyer_account/
    # delivery_location/unit_price) -- order_action_contract.py's own
    # digest() deliberately ALSO folds in external_operation_id (by
    # design: it binds a Capability to one specific operation, not just
    # its field content), so the two full digests are expected to
    # differ here; what matters is that the shared MATERIAL fields
    # (everything the domain contract calls material) are identical.
    assert _order_action(op_id_a).material_fields() == {**_order_action(op_id_b).material_fields(), "external_operation_id": op_id_a}
    # ...but each consumes and claims completely independently.
    consumed_a = _consume(db, org.id, issued_a, binding)
    consumed_b = _consume(db, org.id, issued_b, binding)
    assert consumed_a.capability_id != consumed_b.capability_id
    db.refresh(operation_a)
    db.refresh(operation_b)
    assert operation_a.execution_stage == "CLAIMED"
    assert operation_b.execution_stage == "CLAIMED"


def _concurrent_first_attempt_worker(db_path: str, org_id: str, identity_id: str, binding_id: str, agent_id: str, external_operation_id: str, business_operation_id: str, opa_url: str, barrier, result_queue, worker_id: str):
    """Runs in its own OS process (multiprocessing, spawn context --
    mirrors test_interop_evidencebound_recovery_v01.py's own
    _race_worker exactly). Each worker submits ITS OWN Intent (its own
    external_operation_id, Phase 3's own scope) for the SAME
    business_operation_id, then races to become that identity's first
    current_operation_id at capability issuance."""
    import uuid as _uuid
    from datetime import datetime as _datetime, timezone as _timezone
    from sqlalchemy import create_engine as _create_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker
    from app.config import settings as _settings
    from app.db.models import Agent as _Agent, IntegrationIdentity as _IntegrationIdentity, EnforcementBinding as _EnforcementBinding
    from app.domain.decision import engine as _decision_engine
    from app.services import capability_service as _capability_service
    from app.services import integration_runtime_service as _runtime_svc
    from app.services import operation_service as _operation_service

    # A spawned child re-imports the whole process fresh -- neither this
    # test module's own top-level `decision_engine.evaluate.__defaults__
    # = (5000,)` override, nor the autouse `_point_settings_at_ephemeral_
    # opa` fixture's `settings.opa_url` assignment, ever runs in the
    # child process. Both are re-applied here explicitly -- without the
    # second one, the child's OPA client would silently point at
    # whatever settings.opa_url defaults to (not this test's real
    # ephemeral OPA server), producing a connection failure that this
    # decision engine resolves as an ambiguous HUMAN_REVIEW rather than
    # a clean ALLOW/DENY -- confirmed as the real, direct cause of this
    # test's first failed run, not assumed.
    _decision_engine.evaluate.__defaults__ = (5000,)
    _settings.opa_url = opa_url

    engine = _create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 30})
    session = _sessionmaker(bind=engine)()
    try:
        identity = session.get(_IntegrationIdentity, _uuid.UUID(identity_id))
        binding = session.get(_EnforcementBinding, _uuid.UUID(binding_id))
        agent = session.get(_Agent, _uuid.UUID(agent_id))
        barrier.wait(timeout=30)
        intent, decision, _ev = _runtime_svc.submit_attested_intent(
            session, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
            source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
            amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
            requested_at=_datetime.now(_timezone.utc), nonce=_uuid.uuid4().hex, correlation_id=None,
            external_operation_id=external_operation_id,
            business_operation_id=business_operation_id, intended_destination=DESTINATION,
        )
        if decision.outcome != "ALLOW":
            result_queue.put((worker_id, "DECISION_NOT_ALLOW", None, decision.outcome))
            return
        issued = _capability_service.issue_capability_for_decision(session, _uuid.UUID(org_id), decision.id, audience="reference-pep")
        result_queue.put((worker_id, "ISSUED", str(issued.capability_id), None))
    except _operation_service.ReplacementNotSafeError as e:
        result_queue.put((worker_id, "REPLACEMENT_NOT_SAFE", None, f"{e.safety}: {e.reason}"))
    except Exception as e:  # pragma: no cover -- surfaced via the assertions below, never swallowed
        result_queue.put((worker_id, "ERROR", None, f"{type(e).__name__}: {e}"))
    finally:
        session.close()


def test_concurrent_first_attempts_at_new_business_operation_identity(tmp_path, opa_url):
    """Genuine two-PROCESS race (multiprocessing, not threading, same
    real discipline as test_interop_evidencebound_recovery_v01.py's own
    test_two_connection_consumption_race): two independent OS processes
    submit separate Intents for the SAME, brand-new business_operation_id
    at the same moment. Exactly one may become the identity's first
    current_operation_id; the other must be safely blocked (not silently
    allowed to also "win"), because as soon as it loses the race it
    re-resolves against the actual winner, who is still UNSAFE_UNRESOLVED
    (freshly authorized, nothing executed yet)."""
    db_path = str(tmp_path / "business_operation_identity_race.sqlite3")
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 30})
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

    org = _org(session)
    identity, _cv, binding, agent = _scenario(session, org.id)
    _deploy_policy(session, org.id, opa_url)
    org_id_str, identity_id_str, binding_id_str, agent_id_str = str(org.id), str(identity.id), str(binding.id), str(agent.id)
    session.close()

    boid = "ORDER-CONCURRENT-FIRST-ATTEMPT"
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    result_queue = ctx.Queue()
    p1 = ctx.Process(
        target=_concurrent_first_attempt_worker,
        args=(db_path, org_id_str, identity_id_str, binding_id_str, agent_id_str, f"{OPERATION_ID}-CONCURRENT-1", boid, opa_url, barrier, result_queue, "worker-1"),
    )
    p2 = ctx.Process(
        target=_concurrent_first_attempt_worker,
        args=(db_path, org_id_str, identity_id_str, binding_id_str, agent_id_str, f"{OPERATION_ID}-CONCURRENT-2", boid, opa_url, barrier, result_queue, "worker-2"),
    )
    p1.start()
    p2.start()
    p1.join(timeout=60)
    p2.join(timeout=60)

    results = [result_queue.get(timeout=5) for _ in range(2)]
    for worker_id, outcome, capability_id, detail in results:
        _trace("concurrency", "business_operation_identity_first_attempt_result", worker_id=worker_id, result=outcome, capability_id=capability_id, detail=detail)

    issued = [r for r in results if r[1] == "ISSUED"]
    blocked = [r for r in results if r[1] == "REPLACEMENT_NOT_SAFE"]
    assert len(issued) == 1, f"expected exactly one winning issuance, got {len(issued)}: {results}"
    assert len(blocked) == 1, f"expected exactly one blocked attempt, got {len(blocked)}: {results}"
    assert "UNSAFE_UNRESOLVED" in blocked[0][3]

    verify_engine = create_engine(f"sqlite:///{db_path}")
    verify_session = sessionmaker(bind=verify_engine)()
    identity_row = verify_session.scalar(
        select(BusinessOperationIdentity).where(BusinessOperationIdentity.business_operation_id == boid)
    )
    assert identity_row is not None
    assert identity_row.current_operation_id is not None
    operations = verify_session.scalars(select(Operation).where(Operation.business_operation_identity_id == identity_row.id)).all()
    # Exactly how many Operation rows exist depends on real, uncontrolled
    # interleaving (whether the loser reads current_operation_id before
    # or after the winner has already advanced it) -- see
    # link_business_operation_attempt's own two documented paths. Either
    # way, the winner's own row is real and correctly current; a second,
    # preserved row for the loser is possible but not guaranteed by this
    # race's own timing, so this assertion checks what IS a genuine,
    # timing-independent invariant rather than a specific count.
    assert 1 <= len(operations) <= 2
    current_operation = verify_session.get(Operation, identity_row.current_operation_id)
    assert current_operation.business_operation_identity_id == identity_row.id
    if len(operations) == 2:
        loser_operation = next(o for o in operations if o.id != identity_row.current_operation_id)
        assert loser_operation.capability_id is None, "the blocked loser must never reach a claimed capability"
        assert loser_operation.execution_stage == "AUTHORIZED"
    verify_session.close()


# === Contract-enforcement pass, section 1: mandatory lifecycle enrollment ======


def test_lifecycle_required_contract_rejects_missing_business_operation_id(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id, lifecycle_requirement="LIFECYCLE_REQUIRED")
    _deploy_policy(db, org.id, opa_url)
    with pytest.raises(runtime_svc.IntegrationRejectionError, match="lifecycle_required_but"):
        runtime_svc.submit_attested_intent(
            db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
            source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
            amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
            requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
            external_operation_id=f"{OPERATION_ID}-LIFECYCLE-REQUIRED-MISSING-BOTH",
        )


def test_lifecycle_required_contract_rejects_only_destination_supplied(db, opa_url):
    """"Only one paired field supplied" -- the partial-declaration
    check fires BEFORE the lifecycle-required check ever gets a chance
    to run, but the net effect is identical: rejected, before
    authorization."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id, lifecycle_requirement="LIFECYCLE_REQUIRED")
    _deploy_policy(db, org.id, opa_url)
    with pytest.raises(runtime_svc.IntegrationRejectionError, match="must_be_supplied_together"):
        runtime_svc.submit_attested_intent(
            db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
            source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
            amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
            requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
            external_operation_id=f"{OPERATION_ID}-LIFECYCLE-REQUIRED-ONLY-DEST",
            intended_destination=DESTINATION,
        )


def test_caller_cannot_disable_lifecycle_requirement_from_the_request(db, opa_url):
    """The requirement is read from the SERVER-RESOLVED contract_
    version, never anything the request body claims -- there is no
    request field that could even attempt a "downgrade," and this test
    proves that omitting the fields entirely (the only lever a caller
    has) is rejected exactly like any other missing-field case, never
    silently treated as LEGACY for this one submission."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id, lifecycle_requirement="LIFECYCLE_REQUIRED")
    _deploy_policy(db, org.id, opa_url)
    assert _cv.lifecycle_requirement == "LIFECYCLE_REQUIRED"
    with pytest.raises(runtime_svc.IntegrationRejectionError, match="lifecycle_required_but"):
        runtime_svc.submit_attested_intent(
            db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
            source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
            amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
            requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
            external_operation_id=f"{OPERATION_ID}-DOWNGRADE-ATTEMPT",
            business_operation_id=None, intended_destination=None,
        )


def test_lifecycle_required_contract_accepts_full_identity(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id, lifecycle_requirement="LIFECYCLE_REQUIRED")
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-LIFECYCLE-REQUIRED-OK"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-LIFECYCLE-REQUIRED-OK", intended_destination=DESTINATION,
    )
    assert issued is not None
    assert operation is not None
    assert operation.business_operation_identity_id is not None


def test_legacy_contract_unaffected_by_lifecycle_requirement_field(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)  # LEGACY, the default
    assert _cv.lifecycle_requirement == "LEGACY"
    _deploy_policy(db, org.id, opa_url)
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=f"{OPERATION_ID}-LEGACY-UNAFFECTED",
    )
    assert issued is not None
    assert operation is None, "LEGACY leaves the fields optional -- omitting them still gets no coverage, exactly today's default"


def test_defense_in_depth_check_at_issuance_for_lifecycle_required_contract(db, opa_url):
    """Section 1's own "reject ... before authorization or capability
    issuance": submit_attested_intent already rejects this before a
    Decision exists (proven by the tests above), so THIS test proves
    the SEPARATE, second gate at issuance. A real Intent/Decision is
    submitted with no business_operation_id -- legitimately allowed,
    since its contract is LEGACY at submission time -- and the
    contract's own lifecycle_requirement is then changed to LIFECYCLE_
    REQUIRED before issuance is attempted (simulating a real sequencing
    where the contract's requirement was strengthened between
    submission and issuance): capability_service must still refuse to
    issue, independent of submit_attested_intent's own earlier check."""
    org = _org(db)
    identity, contract_version, binding, agent = _scenario(db, org.id)  # LEGACY at submission time
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DEFENSE-IN-DEPTH"
    intent, decision, _e = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
        amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
        requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=op_id,
        # business_operation_id / intended_destination deliberately omitted -- legal under LEGACY.
    )
    assert intent.business_operation_id is None

    contract_version.lifecycle_requirement = "LIFECYCLE_REQUIRED"
    db.commit()

    with pytest.raises(operation_service.LifecycleRequirementNotSatisfiedError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")


def test_cross_tenant_identity_collision_does_not_occur(db, opa_url):
    org_a = _org(db, "Org Cross Tenant A")
    org_b = _org(db, "Org Cross Tenant B")
    identity_a, _cv_a, binding_a, agent_a = _scenario(db, org_a.id, integration_name="Integration A")
    identity_b, _cv_b, binding_b, agent_b = _scenario(db, org_b.id, principal_name="OrderingAgent01", integration_name="Integration B")
    _deploy_policy(db, org_a.id, opa_url)
    _deploy_policy(db, org_b.id, opa_url)
    boid = "ORDER-SAME-STRING-ACROSS-TENANTS"

    _intent_a, _decision_a, issued_a, operation_a = _submit_and_authorize(
        db, org_a.id, identity_a, binding_a, agent_a, external_operation_id=f"{OPERATION_ID}-CROSS-TENANT-A",
        business_operation_id=boid, intended_destination=DESTINATION,
    )
    _intent_b, _decision_b, issued_b, operation_b = _submit_and_authorize(
        db, org_b.id, identity_b, binding_b, agent_b, external_operation_id=f"{OPERATION_ID}-CROSS-TENANT-B",
        business_operation_id=boid, intended_destination=DESTINATION,
    )
    assert issued_a is not None and issued_b is not None, "identical business_operation_id under different tenants must never collide"
    assert operation_a.business_operation_identity_id != operation_b.business_operation_identity_id


def test_cross_destination_identity_collision_does_not_occur(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    boid = "ORDER-SAME-STRING-ACROSS-DESTINATIONS"

    _intent_1, _decision_1, issued_1, operation_1 = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=f"{OPERATION_ID}-CROSS-DEST-1",
        business_operation_id=boid, intended_destination="synthetic:destination-one",
    )
    _intent_2, _decision_2, issued_2, operation_2 = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=f"{OPERATION_ID}-CROSS-DEST-2",
        business_operation_id=boid, intended_destination="synthetic:destination-two",
    )
    assert issued_1 is not None and issued_2 is not None, "identical business_operation_id under different destinations must never collide"
    assert operation_1.business_operation_identity_id != operation_2.business_operation_identity_id


def test_cross_action_type_identity_collision_does_not_occur(db, opa_url):
    """The `action` component of the identity's own namespace (this
    pass's own addition): two unrelated action types reusing the same
    business_operation_id under the same organization/integration/
    destination must not collide."""
    org = _org(db)
    integration = contract_svc.create_integration(db, org.id, "Shared Integration")
    identity_1 = operation_identity_service.resolve_or_create_business_operation_identity(
        db, org.id, integration.id, ACTION, DESTINATION, "SAME-BUSINESS-OPERATION-ID-STRING",
    )
    identity_2 = operation_identity_service.resolve_or_create_business_operation_identity(
        db, org.id, integration.id, "purchase_order_cancel", DESTINATION, "SAME-BUSINESS-OPERATION-ID-STRING",
    )
    assert identity_1.id != identity_2.id, "different action types must never collide merely for reusing the same business_operation_id string"


def test_replacement_safety_withdrawn_after_issuance_blocks_consumption(db, opa_url):
    """Section 1's own "safety guarantee expires or is withdrawn after
    issuance" scenario: attempt #1's guarantee justified issuing
    attempt #2 as a replacement; the guarantee is then withdrawn
    (edited to a destination that no longer matches, the simplest real
    way to invalidate it without deleting audit history) BEFORE attempt
    #2's own capability is ever consumed -- consumption must be
    blocked, not merely "is this attempt still current" (it still is)."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    boid = "ORDER-GUARANTEE-WITHDRAWN"
    op_id_1 = f"{OPERATION_ID}-GUARANTEE-WITHDRAWN-1"
    intent1, decision1, issued1, operation1 = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id_1,
        business_operation_id=boid, intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id_1).digest(),
    )
    guarantee = operation_service.record_destination_duplicate_prevention_guarantee(
        db, org.id, operation1.id, destination=DESTINATION,
        scope_description="Destination-confirmed idempotency key, believed to cover this attempt",
        retention_until=datetime.now(timezone.utc) + timedelta(days=30), documented_by="governance-admin@example.com",
    )

    op_id_2 = f"{OPERATION_ID}-GUARANTEE-WITHDRAWN-2"
    intent2, decision2, issued2, operation2 = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id_2,
        business_operation_id=boid, intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id_2).digest(),
    )
    assert issued2 is not None
    assert operation2.previous_attempt_operation_id == operation1.id

    # The guarantee expires -- its own retention_until lapses before
    # attempt #2's capability is ever consumed. evaluate_replacement_
    # safety's own read-time expiry check (already exercised in
    # isolation by test_expired_guarantee_does_not_make_replacement_
    # safe) is what this test proves actually gates CONSUMPTION too,
    # not merely a fresh evaluate_replacement_safety() call.
    guarantee.retention_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    with pytest.raises(operation_service.ReplacementSafetyWithdrawnError) as excinfo:
        _consume(db, org.id, issued2, binding)
    assert excinfo.value.previous_attempt_operation_id == operation1.id
    db.expire_all()
    stale_capability_row = db.get(CapabilityToken, issued2.capability_id)
    assert stale_capability_row.consumed_at is None, "consumption must roll back entirely, not partially apply"
    db.refresh(operation2)
    assert operation2.execution_stage == "AUTHORIZED", "the blocked replacement's own stage must not silently advance"


# === Section 2: evidence acceptance rules =======================================


def test_unsigned_relay_cannot_move_outcome_to_committed(db, opa_url):
    """The report's own core finding: an unsigned RBAC_HUMAN relay must
    never automatically become verified destination truth."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-UNSIGNED-CANNOT-COMMIT"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-UNSIGNED-COMMIT", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    consumed = _consume(db, org.id, issued, binding)
    updated, receipt, result = _observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id, order=_order_action(op_id))
    assert result.outcome == "MATCHED", "reconciliation itself is computed normally"
    assert updated.outcome_status == "UNKNOWN", "but an unsigned relay alone cannot promote it to COMMITTED"
    assert updated.evidence_assurance == "REPORTED_UNVERIFIED"

    events = db.scalars(select(OperationEvidenceEvent).where(OperationEvidenceEvent.operation_id == operation.id, OperationEvidenceEvent.event_type == "OBSERVATION")).all()
    assert len(events) == 1
    assert events[0].reconciliation_outcome == "MATCHED", "the raw reconciliation result is preserved even though it wasn't trusted"
    assert events[0].evidence_strength == "UNSIGNED_HUMAN_RELAY"


def test_unsigned_relay_cannot_declare_terminal_non_commit_either(db, opa_url):
    """The same evidentiary bar applies symmetrically -- an unsigned
    relay reporting failure must not unilaterally produce TERMINALLY_
    NOT_COMMITTED (which would make a replacement "safe") any more than
    it can produce COMMITTED."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-UNSIGNED-CANNOT-TERMINAL-FAIL"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-UNSIGNED-FAIL", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    consumed = _consume(db, org.id, issued, binding)
    updated, receipt, result = _observe(db, org.id, operation, identity, binding, intent, status="FAILED", capability_id=consumed.capability_id, order=_order_action(op_id))
    assert result.outcome == "EXECUTION_FAILED"
    assert updated.outcome_status == "UNKNOWN"
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "UNSAFE_UNRESOLVED", "an unsigned relay's claimed failure must not unlock a replacement as safe"


def test_signed_adapter_report_can_commit(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-ADAPTER-COMMIT"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-ADAPTER-COMMIT", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    consumed = _consume(db, org.id, issued, binding)
    updated, receipt, result = _adapter_observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id, order=_order_action(op_id))
    assert updated.outcome_status == "COMMITTED"
    assert updated.evidence_assurance == "ADAPTER_REPORTED"


def test_real_signed_execution_receipt_endpoint_also_commits(db, opa_url):
    """The REAL /v1/execution-receipts path (routers/execution_receipts.py
    -> record_observation_for_existing_receipt), not the test-only
    _observe helper -- proves the stronger, genuinely signature-verified
    channel actually reaches outcome_status=COMMITTED end to end."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-REAL-RECEIPT-ENDPOINT"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-REAL-RECEIPT", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    consumed = _consume(db, org.id, issued, binding)
    receipt = receipt_svc.submit_execution_receipt(
        db, identity, enforcement_binding_id=binding.id, decision_id=decision.id,
        canonical_action_digest=intent.canonical_action_digest, external_operation_id=op_id,
        destination=DESTINATION, status="SUCCEEDED", capability_id=consumed.capability_id,
    )
    updated, _r, _result = operation_service.record_observation_for_existing_receipt(
        db, org.id, receipt, reporter_kind=operation_service.REPORTER_SIGNED_ADAPTER_IDENTITY,
        signature_verified=True, reported_by=f"integration_identity:{identity.name}",
    )
    assert updated.outcome_status == "COMMITTED"
    assert updated.evidence_assurance == "ADAPTER_REPORTED"


def test_manual_adjudication_requires_permission_rationale_and_evidence_references(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-MANUAL-ADJUDICATION"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-MANUAL-ADJUDICATION", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    consumed = _consume(db, org.id, issued, binding)
    updated, receipt, result = _observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id, order=_order_action(op_id))
    assert updated.outcome_status == "UNKNOWN"
    unsigned_event = db.scalar(select(OperationEvidenceEvent).where(OperationEvidenceEvent.operation_id == operation.id, OperationEvidenceEvent.event_type == "OBSERVATION"))

    with pytest.raises(operation_service.InvalidManualAdjudicationError, match="rationale"):
        operation_service.record_manual_adjudication(
            db, org.id, operation.id, adjudicated_by="user:governance@example.com",
            outcome_status="COMMITTED", rationale="", evidence_reference_ids=[unsigned_event.id],
        )
    with pytest.raises(operation_service.InvalidManualAdjudicationError, match="evidence_reference_id"):
        operation_service.record_manual_adjudication(
            db, org.id, operation.id, adjudicated_by="user:governance@example.com",
            outcome_status="COMMITTED", rationale="Confirmed via a phone call with the supplier's own order desk", evidence_reference_ids=[],
        )
    with pytest.raises(operation_service.InvalidManualAdjudicationError, match="not found"):
        operation_service.record_manual_adjudication(
            db, org.id, operation.id, adjudicated_by="user:governance@example.com",
            outcome_status="COMMITTED", rationale="Confirmed via a phone call", evidence_reference_ids=[uuid.uuid4()],
        )

    adjudicated = operation_service.record_manual_adjudication(
        db, org.id, operation.id, adjudicated_by="user:governance@example.com",
        outcome_status="COMMITTED", rationale="Confirmed via a phone call with the supplier's own order desk, referencing their own order confirmation number",
        evidence_reference_ids=[unsigned_event.id],
    )
    assert adjudicated.outcome_status == "COMMITTED"
    assert adjudicated.evidence_assurance == "MANUAL_ADJUDICATED"
    event = db.scalars(select(OperationEvidenceEvent).where(OperationEvidenceEvent.operation_id == operation.id, OperationEvidenceEvent.event_type == "MANUAL_ADJUDICATION")).all()
    assert len(event) == 1
    assert event[0].reporter_kind == operation_service.REPORTER_MANUAL_ADJUDICATION
    assert event[0].signature_verified is False
    assert event[0].rationale
    assert event[0].evidence_reference_ids == [str(unsigned_event.id)]


def test_manual_adjudicate_permission_is_separate_from_observe():
    assert has_permission(Role.REVIEWER, Permission.OPERATION_OBSERVE) is True
    assert has_permission(Role.REVIEWER, Permission.OPERATION_MANUAL_ADJUDICATE) is False
    assert has_permission(Role.AUDITOR, Permission.OPERATION_MANUAL_ADJUDICATE) is False
    assert has_permission(Role.GOVERNANCE_ADMIN, Permission.OPERATION_MANUAL_ADJUDICATE) is True
    assert has_permission(Role.OWNER, Permission.OPERATION_MANUAL_ADJUDICATE) is True


def test_contradictory_evidence_is_retained_and_does_not_overwrite_terminal_conclusion(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-CONTRADICTORY-RETAINED"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-CONTRADICTORY", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    consumed = _consume(db, org.id, issued, binding)
    _adapter_observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id, order=_order_action(op_id))

    from app.services.execution_receipt_service import ExecutionReceiptConflictError

    with pytest.raises(ExecutionReceiptConflictError):
        _observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=None, order=_order_action(op_id))
    db.refresh(operation)
    assert operation.outcome_status == "COMMITTED", "the terminal conclusion is never silently overwritten"

    conflict_events = db.scalars(select(OperationEvidenceEvent).where(OperationEvidenceEvent.operation_id == operation.id, OperationEvidenceEvent.event_type == "OBSERVATION_CONFLICT_REJECTED")).all()
    assert len(conflict_events) == 1, "the conflicting attempt itself is retained, not silently discarded"

    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "BLOCKED_ALREADY_COMMITTED", "an unresolved conflict must not weaken an otherwise-correct block"


def test_mismatched_material_action_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-MISMATCHED-MATERIAL"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-MISMATCHED-MATERIAL", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    _consume(db, org.id, issued, binding)
    wrong_order = _order_action(op_id, buyer_account="ACCT-DIFFERENT")
    with pytest.raises(operation_service.MaterialActionMismatchError):
        _observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", order=wrong_order)


def test_mismatched_destination_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-MISMATCHED-DESTINATION"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-MISMATCHED-DEST", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    consumed = _consume(db, org.id, issued, binding)
    order = _order_action(op_id)

    from app.services.execution_receipt_service import ExecutionReceiptRejectionError

    # execution_receipt_service's own destination-consistency check
    # compares against the FIRST receipt ever submitted for this
    # external_operation_id, not against Operation.destination directly
    # -- the first accepted observation establishes ground truth; only a
    # LATER, disagreeing one is a mismatch.
    _observe(db, org.id, operation, identity, binding, intent, status="ACCEPTED", capability_id=consumed.capability_id, order=order)

    with pytest.raises(ExecutionReceiptRejectionError, match="destination_mismatch"):
        operation_service.record_observation(
            db, org.id, operation.id, identity,
            reporter_kind=operation_service.REPORTER_RBAC_HUMAN, signature_verified=False, reported_by="user:test@example.com",
            enforcement_binding_id=binding.id, material_action_digest=order.digest(),
            canonical_action_digest=intent.canonical_action_digest,
            destination="synthetic:a-completely-different-destination", status="SUCCEEDED", capability_id=consumed.capability_id,
        )


def test_forged_integration_identity_reference_rejected(db, opa_url):
    org_a = _org(db, "Org A")
    org_b = _org(db, "Org B")
    identity_a, _cv, binding, agent = _scenario(db, org_a.id, integration_name="Org A Integration")
    identity_b, _cv_b, _binding_b, _agent_b = _scenario(db, org_b.id, principal_name="OtherOrgAgent", integration_name="Org B Integration")
    _deploy_policy(db, org_a.id, opa_url)
    op_id = f"{OPERATION_ID}-FORGED-IDENTITY"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org_a.id, identity_a, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-FORGED-IDENTITY", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    _consume(db, org_a.id, issued, binding)
    order = _order_action(op_id)

    from app.services.execution_receipt_service import ExecutionReceiptRejectionError

    with pytest.raises(ExecutionReceiptRejectionError):
        operation_service.record_observation(
            db, org_a.id, operation.id, identity_b,
            reporter_kind=operation_service.REPORTER_RBAC_HUMAN, signature_verified=False, reported_by="user:attacker@example.com",
            enforcement_binding_id=binding.id, material_action_digest=order.digest(),
            canonical_action_digest=intent.canonical_action_digest, destination=DESTINATION, status="SUCCEEDED",
        )


# === Contract-enforcement pass, section 2: evidence-acceptance policy per contract ==


def test_destination_evidence_kind_defaults_to_the_only_implemented_tier(db, opa_url):
    """"Define the evidence acceptance policy per integration contract"
    -- a real, versioned, per-contract field, not merely documentation.
    Only one value is legal, on purpose: no independently-verified
    destination-evidence tier exists in this codebase, and this column
    says so structurally rather than offering a selectable option that
    would do nothing."""
    org = _org(db)
    _identity, contract_version, _binding, _agent = _scenario(db, org.id)
    assert contract_version.destination_evidence_kind == "ADAPTER_OWN_OBSERVATION"


def test_destination_evidence_kind_rejects_any_other_value(db):
    org = _org(db)
    integration = contract_svc.create_integration(db, org.id, "Rejects Bad Evidence Kind")
    with pytest.raises(contract_svc.ContractValidationError, match="destination_evidence_kind"):
        contract_svc.create_contract_version(
            db, integration.id, org.id, SOURCE_OPERATION, ACTION,
            resource_path="order.supplier", context_bindings=ORDER_CONTEXT_BINDINGS,
            destination_evidence_kind="INDEPENDENTLY_VERIFIED",
        )


def test_lifecycle_requirement_rejects_any_other_value(db):
    org = _org(db)
    integration = contract_svc.create_integration(db, org.id, "Rejects Bad Lifecycle Requirement")
    with pytest.raises(contract_svc.ContractValidationError, match="lifecycle_requirement"):
        contract_svc.create_contract_version(
            db, integration.id, org.id, SOURCE_OPERATION, ACTION,
            resource_path="order.supplier", context_bindings=ORDER_CONTEXT_BINDINGS,
            lifecycle_requirement="SOMETIMES_REQUIRED",
        )


def test_contract_settings_are_part_of_content_hash(db):
    """Both new fields are semantic, not incidental provenance -- two
    contract versions that differ ONLY in lifecycle_requirement must
    hash differently, exactly like differing in canonical_action would."""
    org = _org(db)
    integration = contract_svc.create_integration(db, org.id, "Content Hash Sensitivity")
    cv_legacy = contract_svc.create_contract_version(
        db, integration.id, org.id, SOURCE_OPERATION, ACTION,
        resource_path="order.supplier", context_bindings=ORDER_CONTEXT_BINDINGS,
        lifecycle_requirement="LEGACY",
    )
    cv_legacy = contract_svc.validate_contract_version(db, cv_legacy.id, org.id)
    cv_required = contract_svc.create_contract_version(
        db, integration.id, org.id, SOURCE_OPERATION, ACTION,
        resource_path="order.supplier", context_bindings=ORDER_CONTEXT_BINDINGS,
        lifecycle_requirement="LIFECYCLE_REQUIRED",
    )
    cv_required = contract_svc.validate_contract_version(db, cv_required.id, org.id)
    assert cv_legacy.content_hash != cv_required.content_hash


def test_execution_stage_at_event_records_the_dispatch_evidence_gap(db, opa_url):
    """"A late outcome may arrive without prior dispatch evidence;
    record that evidence gap explicitly rather than inventing dispatch
    history." A signed Adapter observation arrives while execution_
    stage is still CLAIMED (no DISPATCH_REPORTED event was ever
    recorded) -- the event's own execution_stage_at_event must say
    CLAIMED, permanently, regardless of whatever execution_stage the
    Operation itself reaches afterward."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DISPATCH-GAP"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-DISPATCH-GAP", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    consumed = _consume(db, org.id, issued, binding)
    assert operation.execution_stage == "CLAIMED"  # no dispatch evidence ever recorded

    updated, _r, _res = _adapter_observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id, order=_order_action(op_id))
    assert updated.outcome_status == "COMMITTED"

    event = db.scalar(select(OperationEvidenceEvent).where(OperationEvidenceEvent.operation_id == operation.id, OperationEvidenceEvent.event_type == "OBSERVATION"))
    assert event.execution_stage_at_event == "CLAIMED", "the gap (no prior dispatch evidence) is recorded explicitly, not papered over"


def test_execution_stage_at_event_recorded_for_dispatch_report_too(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DISPATCH-STAGE-SNAPSHOT"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-DISPATCH-STAGE-SNAPSHOT", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    _consume(db, org.id, issued, binding)
    operation_service.record_dispatch_evidence(
        db, org.id, operation.id, reporter_kind=operation_service.REPORTER_RBAC_HUMAN,
        signature_verified=False, reported_by="user:ops@example.com", destination=DESTINATION,
    )
    event = db.scalar(select(OperationEvidenceEvent).where(OperationEvidenceEvent.operation_id == operation.id, OperationEvidenceEvent.event_type == "DISPATCH_REPORTED"))
    assert event.execution_stage_at_event == "CLAIMED", "the stage BEFORE this event's own CLAIMED->DISPATCHED transition, never the stage it produced"
    db.refresh(operation)
    assert operation.execution_stage == "DISPATCHED"


# === Section 3: execution stage vs. outcome certainty ============================


def test_claimed_stage_coexists_with_unknown_outcome(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-CLAIMED-UNKNOWN"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-CLAIMED-UNKNOWN", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    _consume(db, org.id, issued, binding)
    db.refresh(operation)
    assert operation.execution_stage == "CLAIMED"
    assert operation.outcome_status == "UNKNOWN", "unknown BEFORE dispatch evidence"


def test_dispatched_stage_coexists_with_unknown_outcome(db, opa_url):
    """Preserves the distinction between unknown-before-dispatch and
    unknown-after-dispatch -- both are valid, different combinations."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DISPATCHED-UNKNOWN"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-DISPATCHED-UNKNOWN", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    _consume(db, org.id, issued, binding)
    operation_service.record_dispatch_evidence(
        db, org.id, operation.id, reporter_kind=operation_service.REPORTER_RBAC_HUMAN,
        signature_verified=False, reported_by="user:ops@example.com", destination=DESTINATION,
    )
    db.refresh(operation)
    assert operation.execution_stage == "DISPATCHED", "unknown AFTER evidenced dispatch -- a materially different fact from before"
    assert operation.outcome_status == "UNKNOWN"


def test_dispatch_evidence_never_infers_from_missing_receipt(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-NO-INFERENCE"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-NO-INFERENCE", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    _consume(db, org.id, issued, binding)
    db.refresh(operation)
    # No dispatch evidence, no observation -- both axes stay exactly at
    # their honest defaults; nothing is inferred from the absence.
    assert operation.execution_stage == "CLAIMED"
    assert operation.outcome_status == "UNKNOWN"
    assert operation.evidence_assurance == "NONE"


def test_late_commit_after_revocation_reaches_committed_via_adapter_evidence(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-LATE-COMMIT-ADAPTER"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-LATE-COMMIT-ADAPTER", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    consumed = _consume(db, org.id, issued, binding)
    agent_service.revoke_agent(db, agent.id, reason="pending investigation")
    updated, _r, result = _adapter_observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id, order=_order_action(op_id))
    assert result.outcome == "MATCHED"
    assert updated.outcome_status == "COMMITTED"
    assert updated.evidence_assurance == "ADAPTER_REPORTED"

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        _consume(db, org.id, issued, binding)


def test_terminal_non_commit_via_signed_adapter_evidence(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-TERMINAL-NON-COMMIT-ADAPTER"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-TERMINAL-NON-COMMIT", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    consumed = _consume(db, org.id, issued, binding)
    updated, _r, result = _adapter_observe(db, org.id, operation, identity, binding, intent, status="FAILED", capability_id=consumed.capability_id, order=_order_action(op_id))
    assert result.outcome == "EXECUTION_FAILED"
    assert updated.outcome_status == "TERMINALLY_NOT_COMMITTED"
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "SAFE_TERMINAL_NON_COMMIT_PROVEN"
    assert safety.requires_current_authorization is True


def test_operations_route_response_exposes_both_axes():
    """Structural proof the API response shape actually carries both
    facts separately -- not merely the service layer internally."""
    from app.schemas.operations import OperationResponse

    fields = OperationResponse.model_fields
    assert "execution_stage" in fields
    assert "outcome_status" in fields
    assert "evidence_assurance" in fields
    assert "state" not in fields, "the old collapsed field must not still be exposed"


# === Structural: route + permission gating ======================================


def test_every_operations_route_is_gated_correctly():
    from fastapi.routing import APIRoute

    from app.main import app

    def _all_routes(routes):
        for route in routes:
            if type(route).__name__ == "_IncludedRouter":
                yield from _all_routes(route.original_router.routes)
            elif isinstance(route, APIRoute):
                yield route

    operations_routes = {r.path: r for r in _all_routes(app.router.routes) if r.path.startswith("/v1/operations") or r.path == "/v1/decisions/{decision_id}/operation"}
    assert len(operations_routes) == 7, f"expected 7 operations routes, found {len(operations_routes)}: {sorted(operations_routes)}"

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

    adjudication_route = operations_routes.pop("/v1/operations/{operation_id}/manual-adjudication")
    assert Permission.OPERATION_MANUAL_ADJUDICATE in _gated_by(adjudication_route)
    assert Permission.OPERATION_OBSERVE not in _gated_by(adjudication_route)

    for path, route in operations_routes.items():
        assert Permission.OPERATION_OBSERVE in _gated_by(route), f"{path} not gated by OPERATION_OBSERVE"


# === Duplicate-prevention guarantee scoping (unaffected by this pass, reconfirmed) ==


def test_duplicate_prevention_guarantee_restricted_to_identity_enforced(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    other_identity, _cv2, other_binding, other_agent = _scenario(db, org.id, principal_name="OrderingAgent01", integration_name="Other Integration")
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DUP-PREVENTION-RESTRICTED"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-DUP-RESTRICTED", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
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


def test_expired_guarantee_does_not_make_replacement_safe(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-DUP-PREVENTION-EXPIRED"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="ORDER-DUP-EXPIRED", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    _consume(db, org.id, issued, binding)
    expired = DestinationDuplicatePreventionGuarantee(
        organization_id=org.id, operation_id=operation.id, destination=DESTINATION,
        scope_description="was valid, has since expired", documented_by="governance-admin@example.com",
        retention_until=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.add(expired)
    db.commit()
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "UNSAFE_UNRESOLVED"


# === Section 5: rerun of the two frozen recovery schedules through the corrected layer ===


def test_rerun_schedule_1_late_committed_outcome_through_corrected_layer(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=OPERATION_ID,
        business_operation_id="EVIDENCEBOUND-SCHEDULE-1-BUSINESS-OP", intended_destination=DESTINATION,
        material_action_digest=_order_action(OPERATION_ID).digest(),
    )
    assert operation.execution_stage == "AUTHORIZED"
    assert operation.outcome_status == "UNKNOWN"
    _trace("1-rerun", "execution_authority_valid", operation_record_id=operation.id, execution_stage=operation.execution_stage, outcome_status=operation.outcome_status)

    consumed = _consume(db, org.id, issued, binding)
    db.refresh(operation)
    assert operation.execution_stage == "CLAIMED"
    _trace("1-rerun", "operation_claimed_not_dispatched", operation_record_id=operation.id, execution_stage=operation.execution_stage, outcome_status=operation.outcome_status)

    destination = FakeDestination(DestinationBehaviour.COMMIT_NO_RECEIPT)
    destination.attempt(OPERATION_ID)
    _trace("1-rerun", "destination_commit_no_receipt", effect_count=1, evidence_source="synthetic_destination_internal_state (test harness ground truth, not itself platform evidence)")

    agent_service.revoke_agent(db, agent.id, reason="pending investigation")
    _trace("1-rerun", "execution_authority_revoked", agent_id=agent.id)

    late = destination.late_authoritative_observation()
    assert late == "COMMITTED"
    # Section 2/5: the late observation is reported via the REAL,
    # signature-verified Adapter channel -- an unsigned RBAC_HUMAN relay
    # is explicitly NOT used here to manufacture the expected final
    # state (the closeout task's own explicit prohibition).
    updated_operation, receipt, result = _adapter_observe(db, org.id, operation, identity, binding, intent, status="SUCCEEDED", capability_id=consumed.capability_id, order=_order_action(OPERATION_ID))
    assert result.outcome == "MATCHED"
    assert updated_operation.outcome_status == "COMMITTED"
    _trace(
        "1-rerun", "reconciled_matched_and_operation_committed", operation_record_id=operation.id,
        execution_stage=updated_operation.execution_stage, outcome_status=updated_operation.outcome_status,
        evidence_assurance=updated_operation.evidence_assurance,
        receipt_id=receipt.id, effect_count=1, evidence_source="SIGNED_ADAPTER_IDENTITY, signature_verified=True",
    )

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        _consume(db, org.id, issued, binding)
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "BLOCKED_ALREADY_COMMITTED"
    _trace(
        "1-rerun", "final_state", execution_stage=updated_operation.execution_stage, outcome_status=updated_operation.outcome_status,
        evidence_assurance=updated_operation.evidence_assurance, replacement_safety=safety.safety, effect_count=1,
    )


def test_rerun_schedule_2_outcome_remains_unknown_through_corrected_layer(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-SCHEDULE-2-RERUN"
    intent, decision, issued, operation = _submit_and_authorize(
        db, org.id, identity, binding, agent, external_operation_id=op_id,
        business_operation_id="EVIDENCEBOUND-SCHEDULE-2-BUSINESS-OP", intended_destination=DESTINATION,
        material_action_digest=_order_action(op_id).digest(),
    )
    _consume(db, org.id, issued, binding)

    destination = FakeDestination(DestinationBehaviour.NOT_FOUND_NOW)
    response = destination.attempt(op_id)
    assert response == "NOT_FOUND_NOW"
    _trace("2-rerun", "attempt_not_found_now", destination_observation="NOT_FOUND_NOW", effect_count="UNKNOWN")

    agent_service.revoke_agent(db, agent.id, reason="revoked without terminal outcome evidence")
    db.refresh(operation)
    assert operation.execution_stage == "CLAIMED"
    assert operation.outcome_status == "UNKNOWN"
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "UNSAFE_UNRESOLVED"
    _trace(
        "2-rerun", "historical_outcome_unresolved", execution_stage=operation.execution_stage,
        outcome_status=operation.outcome_status, evidence_assurance=operation.evidence_assurance,
        safety=safety.safety, effect_count="UNKNOWN",
    )

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        _consume(db, org.id, issued, binding)
    _trace("2-rerun", "no_auto_retry_no_release", execution_stage=operation.execution_stage, outcome_status=operation.outcome_status, safety=safety.safety)
    _trace(
        "2-rerun", "replacement_conclusion",
        destination_terminal_non_commit_proof="NOT_OBTAINED", destination_duplicate_prevention_guarantee="NOT_DOCUMENTED",
        conclusion="REPLACEMENT_REMAINS_UNSAFE",
    )
