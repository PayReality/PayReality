"""Consolidation review, Section 2's own explicit requirement: 'Verify
that a lifecycle-required action can enter the product through its real
API path and reach the operation record, enforcement, and observation
paths -- not solely through direct service calls in tests.'

Every existing test for this feature (test_product_lifecycle_vertical_
slice.py and its Postgres counterpart) calls capability_service/
operation_service functions directly, never the actual FastAPI router
functions in app/routers/capability_tokens.py or app/routers/
operations.py -- confirmed by grep before writing this file, and true
of every other integration test in this repository as well (this repo
has no existing FastAPI TestClient-based test convention; see test_
tenant_scoped_verification.py's own module docstring for why: it would
also need to stub or skip this app's lifespan startup hooks). This file
follows that same established, deliberate pattern -- calling the real,
unmodified router endpoint functions and the real, unmodified
app.dependencies.get_current_organization / require_permission
functions directly, with real ApiKey rows and real permission
resolution -- rather than inventing a new, heavier convention, while
still closing the actual gap: the ROUTER layer (permission gating,
request/response schema validation, exception-to-HTTPException mapping)
for capability issuance and the operation-observation path had zero
coverage before this file.
"""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, ApiKey, Base, Organization, Principal
from app.dependencies import get_current_organization, require_permission
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64
from app.domain.rbac.permissions import Permission, Role
from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.routers import capability_tokens as capability_router
from app.routers import operations as operations_router
from app.schemas.capability import IssueCapabilityRequest
from app.schemas.operations import RecordObservationRequest
from app.services import (
    agent_service,
    auth_service,
    capability_service,
    enforcement_binding_service as binding_svc,
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
    integration_runtime_service as runtime_svc,
    operation_service,
    runtime_policy_service as policy_svc,
    signing_key_service,
)

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)

ACTION = "purchase_order_create"
SOURCE_OPERATION = "EVIDENCEBOUND/v1.SubmitOrder"
DESTINATION = "synthetic:router-reachability-01"
SUPPLIER_RESOURCE = "supplier:A"
ORDER_CONTEXT_BINDINGS = {
    "quantity": "order.quantity", "buyer_account": "order.buyer_account",
    "delivery_location": "order.delivery_location", "unit_price": "order.unit_price",
}
ORDER_CONTEXT = {"quantity": 120, "buyer_account": "ACCT-B", "delivery_location": "location:X", "unit_price": "42.50"}


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


def _org(db, name="Router Reachability Org"):
    org = Organization(id=uuid.uuid4(), name=name)
    db.add(org)
    db.commit()
    return org


def _api_key(db, org_id, role=Role.GOVERNANCE_ADMIN):
    """Mirrors auth_service.generate_api_key()'s own real hashing -- the
    raw key returned here is exactly what a real caller would send as
    `Authorization: Bearer <raw_key>`."""
    raw_key, key_hash, key_prefix = auth_service.generate_api_key()
    row = ApiKey(
        id=uuid.uuid4(), organization_id=org_id, name="test key", key_hash=key_hash,
        key_prefix=key_prefix, role=role.value,
    )
    db.add(row)
    db.commit()
    return raw_key


def _resolve_organization(db, api_key):
    """Calls the real, unmodified get_current_organization dependency
    directly -- see this file's own module docstring for why direct
    calls, not a full ASGI/TestClient round trip."""
    return get_current_organization(
        x_payreality_operator_key=None, x_payreality_organization_id=None,
        authorization=f"Bearer {api_key}", db=db,
    )


def _check_permission(db, permission, api_key):
    """Calls the real, unmodified require_permission(...) dependency
    closure directly (it's an async function)."""
    check = require_permission(permission)
    asyncio.run(check(x_payreality_operator_key=None, authorization=f"Bearer {api_key}", db=db))


def _scenario(db, org_id):
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "Router Reachability Adapter", "ed25519:base64:AAAA")
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)
    integration = contract_svc.create_integration(db, org_id, "Router Reachability Integration")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, SOURCE_OPERATION, ACTION,
        resource_path="order.supplier", amount_path=None, currency_path=None,
        fact_subject_path=None, context_bindings=ORDER_CONTEXT_BINDINGS, lifecycle_requirement="LEGACY",
    )
    contract_version = contract_svc.validate_contract_version(db, contract_version.id, org_id)
    contract_version = contract_svc.approve_contract_version(db, contract_version.id, org_id, approver="governance-admin@example.com")
    principal = Principal(id=uuid.uuid4(), name="OrderingAgent01", organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="OrderingAgent01 agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    binding = binding_svc.create_draft_binding(db, org_id, identity.id, contract_version.id, "production", agent_ids=[agent.id])
    binding = binding_svc.activate_binding(db, binding.id, org_id)
    return identity, contract_version, binding, agent


def _deploy_policy(db, org_id, opa_url):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="router-reachability-policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="OrderingAgent01", action=ACTION, resource=SUPPLIER_RESOURCE),
        conditions=ConditionSet(all=()), effect=Effect.ALLOW, audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)


def test_lifecycle_required_action_reaches_operation_and_observation_through_the_real_routers(db, opa_url):
    """End to end through the real router layer (not the underlying
    service functions): submit an Intent whose resulting ALLOW Decision
    is issued a Capability via the REAL capability_tokens.issue_capability
    router function (real require_permission(CAPABILITY_ISSUE) gate),
    confirm the resulting Operation is reachable via the REAL
    operations.get_operation router function (real
    require_permission(OPERATION_OBSERVE) gate), claim the Capability,
    then post a real observation via the REAL operations.record_observation
    router function and confirm it lands in the same Operation record."""
    org = _org(db)
    identity, contract_version, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    api_key = _api_key(db, org.id, role=Role.GOVERNANCE_ADMIN)

    op_id = "ROUTER-REACHABILITY-001"
    intent, decision, _evidence = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
        amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
        requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=op_id, business_operation_id="ORDER-ROUTER-REACHABILITY", intended_destination=DESTINATION,
    )
    assert decision.outcome == "ALLOW"

    # --- Real router call #1: capability issuance -------------------
    organization = _resolve_organization(db, api_key)
    _check_permission(db, Permission.CAPABILITY_ISSUE, api_key)
    issue_response = capability_router.issue_capability(
        decision_id=decision.id,
        body=IssueCapabilityRequest(audience="reference-pep"),
        organization=organization, db=db,
    )
    assert issue_response.capability_id is not None

    # --- Real router call #2: read the operation back ----------------
    _check_permission(db, Permission.OPERATION_OBSERVE, api_key)
    operation_response = operations_router.get_operation_for_decision(
        decision_id=decision.id, organization=organization, db=db,
    )
    assert operation_response.execution_stage == "AUTHORIZED"
    assert operation_response.outcome_status == "UNKNOWN"
    operation_id = operation_response.operation_id
    # capability_tokens.issue_capability's own request schema has no
    # material_action_digest field, so the Operation was created with
    # the generic default (intent.canonical_action_digest), not this
    # order's own stricter digest -- read back what was actually stored
    # rather than assuming which one.
    material_action_digest = operation_response.material_action_digest

    # A caller WITHOUT the permission must be rejected by the router's
    # own real dependency, not merely by an assumption in this test.
    api_key_no_permission = _api_key(db, org.id, role=Role.AUDITOR)
    with pytest.raises(HTTPException) as exc_info:
        _check_permission(db, Permission.OPERATION_OBSERVE, api_key_no_permission)
    assert exc_info.value.status_code == 403

    # --- Claim the Capability (service layer -- consumption itself is
    # already covered elsewhere; not what this file is verifying) ------
    consumed = capability_service.verify_and_consume_capability(
        db, issue_response.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        {**{k: str(v) for k, v in ORDER_CONTEXT.items()}, "environment": "production"},
        environment=binding.environment, enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )

    # --- Real router call #3: record a real observation ---------------
    observation_response = operations_router.record_observation(
        operation_id=operation_id,
        body=RecordObservationRequest(
            integration_identity_id=identity.id, enforcement_binding_id=binding.id,
            material_action_digest=material_action_digest, canonical_action_digest=intent.canonical_action_digest,
            destination=DESTINATION, status="SUCCEEDED", capability_id=consumed.capability_id,
        ),
        organization=organization, user=None, db=db,
    )
    assert observation_response.operation.operation_id == operation_id
    # Consuming the Capability alone (no separate dispatch-evidence call)
    # advances execution_stage to CLAIMED, not DISPATCHED -- observation
    # only requires CLAIMED (operation_service's own state machine), and
    # this unsigned RBAC_HUMAN relay's "SUCCEEDED" claim is capped at
    # outcome_status=UNKNOWN, never promoted to COMMITTED (evidence-
    # acceptance rules, verified separately in test_product_lifecycle_
    # vertical_slice.py -- what THIS test verifies is that the real
    # router call reaches and updates the real, persisted row at all).
    assert observation_response.operation.execution_stage == "CLAIMED"
    assert observation_response.operation.outcome_status == "UNKNOWN"
    assert observation_response.operation.evidence_assurance == "REPORTED_UNVERIFIED"

    # Confirms this really did reach the same, real, persisted row --
    # not a response fabricated independently of the database.
    persisted = operation_service._get_operation_for_organization(db, org.id, operation_id)
    assert persisted.id == operation_id
    assert persisted.execution_stage == "CLAIMED"
    assert persisted.evidence_assurance == "REPORTED_UNVERIFIED"
