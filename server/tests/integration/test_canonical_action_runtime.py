"""Post-audit implementation, Priority 3: proves the canonical action
contract (app/domain/canonical_action.py) actually reaches a real,
persisted Intent and its Evidence record through the real Adapter-mediated
runtime path (integration_runtime_service.submit_attested_intent), not
just as a unit-tested pure function. Real SQLite + real ephemeral OPA,
mirroring test_reference_enforcement_demonstration.py's own fixtures.

Deliberately does not re-test integration_runtime_service's own existing,
already-covered mechanics (contract mismatch, structural field checks,
duplicate-external-operation conflict, replay) -- those remain proven in
test_integration_contract_lifecycle.py / test_adapter_capability_
authorization.py / test_reference_enforcement_demonstration.py. This file
is scoped to what's new: the canonical_action_digest/schema_version this
milestone adds.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Base, Evidence, Organization, Principal
from app.domain.canonical_action import CANONICAL_ACTION_SCHEMA_VERSION
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64
from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import (
    enforcement_binding_service as binding_svc,
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
    integration_runtime_service as runtime_svc,
    runtime_policy_service as policy_svc,
    signing_key_service,
)

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)

ACTION = "supplier_bank_details_change"
RESOURCE = "supplier:SUPPLIER_482"
SOURCE_OPERATION = "ChangeSupplierBankDetails"


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


def _org(db, name="Org Canonical"):
    org = Organization(id=uuid.uuid4(), name=name)
    db.add(org)
    db.commit()
    return org


def _deploy_allow_policy(db, org_id, opa_url):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="allow policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="FinanceAgent01", action=ACTION, resource=RESOURCE),
        conditions=ConditionSet(all=()), effect=Effect.ALLOW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)


def _scenario(db, org_id):
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "Reference Adapter", "ed25519:base64:AAAA")
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)
    integration = contract_svc.create_integration(db, org_id, "Reference System")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, SOURCE_OPERATION, ACTION,
        resource_path="supplier.id", amount_path=None, currency_path=None,
        fact_subject_path=None, context_bindings={},
    )
    contract_version = contract_svc.validate_contract_version(db, contract_version.id, org_id)
    contract_version = contract_svc.approve_contract_version(db, contract_version.id, org_id, approver="governance-admin@example.com")

    principal = Principal(id=uuid.uuid4(), name="FinanceAgent01", organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="Finance Agent 01", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()

    binding = binding_svc.create_draft_binding(db, org_id, identity.id, contract_version.id, "demo", agent_ids=[agent.id])
    binding = binding_svc.activate_binding(db, binding.id, org_id)
    return identity, contract_version, binding, agent


def _submit(db, identity, binding, agent, external_operation_id):
    return runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=RESOURCE,
        amount=None, currency=None, counterparty=None, context={}, requested_at=datetime.now(timezone.utc),
        nonce=uuid.uuid4().hex, correlation_id=None, external_operation_id=external_operation_id,
    )


def test_canonical_action_digest_is_persisted_on_the_intent(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)

    intent, decision, _evidence = _submit(db, identity, binding, agent, uuid.uuid4().hex)
    assert decision.outcome == "ALLOW"
    assert intent.canonical_action_schema_version == CANONICAL_ACTION_SCHEMA_VERSION
    assert intent.canonical_action_digest is not None
    assert len(intent.canonical_action_digest) == 64  # sha256 hex digest


def test_canonical_action_digest_is_recorded_in_evidence(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)

    intent, decision, evidence = _submit(db, identity, binding, agent, uuid.uuid4().hex)
    row = db.get(Evidence, evidence.id)
    assert row.payload["canonical_action_digest"] == intent.canonical_action_digest
    assert row.payload["canonical_action_schema_version"] == CANONICAL_ACTION_SCHEMA_VERSION


def test_agent_direct_intents_leave_the_canonical_action_digest_null(db, opa_url):
    """The canonical action contract is specific to the Adapter-mediated
    path (a trusted adapter attesting under an approved contract) -- an
    Agent-direct Intent has no Adapter, no Contract, no attested
    canonical action, so it must not get a fabricated digest."""
    from app.db.models import Intent
    from app.services import intent_service

    org = _org(db)
    principal = Principal(id=uuid.uuid4(), name="alice", organization_id=org.id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="alice agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()

    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="allow", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="alice", action="vendor_payment", resource="supplier:1"),
        conditions=ConditionSet(all=()), effect=Effect.ALLOW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org.id)
    policy_svc.submit_for_review(db, row.policy_key, org.id)
    policy_svc.approve(db, row.policy_key, org.id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org.id)
    assert result.ok
    policy_svc.deploy_policy(db, row.policy_key, org.id, opa_url=None)

    intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action="vendor_payment", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="supplier:1",
    )
    assert intent.canonical_action_digest is None
    assert intent.canonical_action_schema_version is None


def test_idempotent_retry_of_the_same_external_operation_reuses_the_original_digest(db, opa_url):
    """A genuine retry (same external_operation_id, same everything)
    returns the original Intent unchanged -- including its original
    canonical_action_digest, never a freshly recomputed one."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)

    external_op = uuid.uuid4().hex
    first_intent, _decision, _evidence = _submit(db, identity, binding, agent, external_op)
    second_intent, _decision2, _evidence2 = _submit(db, identity, binding, agent, external_op)

    assert second_intent.id == first_intent.id
    assert second_intent.canonical_action_digest == first_intent.canonical_action_digest
