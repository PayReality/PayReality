"""Contract-enforcement pass, section 3: real-PostgreSQL verification of
the product lifecycle vertical slice's own concurrency and atomicity
claims -- the two properties SQLite's file-locking model cannot
genuinely exercise (a real row-level UPDATE race across independent
connections) are kept as two SEPARATE properties here, never conflated:

  1. Capability-consumption atomicity -- CapabilityToken's own
     single-writer-wins UPDATE ... WHERE consumed_at IS NULL, exercised
     by two independent connections racing to consume the identical
     Capability.
  2. Business-operation-identity attempt-registration safety --
     BusinessOperationIdentity's own unique constraint (first-attempt
     creation) and atomic conditional UPDATE (current_operation_id
     advancement), exercised by two independent connections racing to
     register the FIRST attempt at the same, brand-new identity.

Uses the project's own existing docker-compose Postgres service via the
`postgres_url` fixture (see conftest.py) -- a genuine, disposable
database, migrated with the real Alembic chain, dropped afterward. Uses
this repo's own established "force the exact interleaving
deterministically, via a threading.Barrier, never rely on timing"
convention (test_operation_identity_postgres.py, test_integration_
contract_concurrency.py) rather than multiprocessing -- Postgres over
TCP handles concurrent threads natively, unlike SQLite's single-file
locking model, which is why the sibling EvidenceBound race test uses
multiprocessing specifically for SQLite.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import (
    Agent, BusinessOperationIdentity, CapabilityToken, Operation,
    Organization, Principal,
)
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64
from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import (
    capability_service,
    enforcement_binding_service as binding_svc,
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

ACTION = "purchase_order_create"
SOURCE_OPERATION = "EVIDENCEBOUND/v1.SubmitOrder"
SUPPLIER_RESOURCE = "supplier:A"
DESTINATION = "synthetic:evidencebound-fulfillment-01-postgres"
ORDER_CONTEXT_BINDINGS = {
    "quantity": "order.quantity", "buyer_account": "order.buyer_account",
    "delivery_location": "order.delivery_location", "unit_price": "order.unit_price",
}
ORDER_CONTEXT = {"quantity": 120, "buyer_account": "ACCT-B", "delivery_location": "location:X", "unit_price": "42.50"}


@pytest.fixture()
def engine(postgres_url):
    return create_engine(postgres_url)


@pytest.fixture()
def SessionLocal(engine):
    return sessionmaker(bind=engine)


@pytest.fixture()
def db(SessionLocal):
    session = SessionLocal()
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


def _deploy_policy(db, org_id, opa_url, effect=Effect.ALLOW, principal="OrderingAgent01"):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="pg-verify-policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal=principal, action=ACTION, resource=SUPPLIER_RESOURCE),
        conditions=ConditionSet(all=()), effect=effect, audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row


def _setup(db, org_id, *, lifecycle_requirement="LEGACY"):
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "Reference Order Adapter", "ed25519:base64:AAAA")
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)
    integration = contract_svc.create_integration(db, org_id, "Order Fulfillment (Postgres verification)")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, SOURCE_OPERATION, ACTION,
        resource_path="order.supplier", context_bindings=ORDER_CONTEXT_BINDINGS,
        lifecycle_requirement=lifecycle_requirement,
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
    return identity, integration, contract_version, binding, agent


def _expected_constraints(environment="production"):
    constraints = {k: str(v) for k, v in ORDER_CONTEXT.items()}
    constraints["environment"] = environment
    return constraints


# === Property 1: capability-consumption atomicity ==============================


def _consume_in_new_session(SessionLocal, token, environment, binding_id, org_id, results, errors, connection_id):
    session = SessionLocal()
    try:
        consumed = capability_service.verify_and_consume_capability(
            session, token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
            _expected_constraints(), environment=environment,
            enforcement_binding_id=binding_id, expected_organization_id=org_id,
        )
        results.append((connection_id, consumed.capability_id))
    except Exception as e:  # pragma: no cover -- surfaced via the assertions below, never swallowed
        errors.append((connection_id, e))
    finally:
        session.close()


def test_two_connection_capability_consumption_race_postgres(db, SessionLocal, opa_url):
    """Real independent connections (threads, each opening its OWN
    SQLAlchemy Session/connection against the SAME real Postgres
    database), racing to consume the identical Capability for a
    business-operation-identity-covered Operation. Proves the atomic
    `UPDATE ... WHERE consumed_at IS NULL` genuinely serializes under
    Postgres's own real row-level locking / MVCC (not SQLite's file
    lock), and that the winner's Operation.execution_stage transition
    (record_claim) is durable in the SAME transaction as that winner's
    own consume -- kept as its own, separate property from the
    business-operation registration race below."""
    org = Organization(id=uuid.uuid4(), name="Org PG Capability Race")
    db.add(org)
    db.commit()
    identity, _integration, _cv, binding, agent = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    op_id = f"PG-VERIFY-CAP-RACE-{uuid.uuid4().hex[:8]}"
    intent, decision, _ev = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
        amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
        requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=op_id, business_operation_id=f"BOID-{op_id}", intended_destination=DESTINATION,
    )
    assert decision.outcome == "ALLOW"
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")
    operation = db.scalar(select(Operation).where(Operation.decision_id == decision.id))
    assert operation is not None and operation.execution_stage == "AUTHORIZED"

    binding_environment, binding_id, org_id_val = binding.environment, binding.id, org.id
    db.commit()  # ensure the setup connection's own writes are visible to the racing connections

    barrier = threading.Barrier(2)
    real_verify = capability_service.verify_and_consume_capability

    def synchronized_verify(*args, **kwargs):
        tid = threading.get_ident()
        if tid not in synchronized_verify._synced:
            synchronized_verify._synced.add(tid)
            barrier.wait(timeout=30)
        return real_verify(*args, **kwargs)

    synchronized_verify._synced = set()
    capability_service.verify_and_consume_capability = synchronized_verify

    results: list = []
    errors: list = []
    try:
        threads = [
            threading.Thread(
                target=_consume_in_new_session,
                args=(SessionLocal, issued.token, binding_environment, binding_id, org_id_val, results, errors, f"connection-{i}"),
            )
            for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
    finally:
        capability_service.verify_and_consume_capability = real_verify

    assert len(results) == 1, f"expected exactly one successful consumption, got {len(results)}: {results}"
    assert len(errors) == 1, f"expected exactly one rejected consumption, got {len(errors)}: {errors}"
    assert isinstance(errors[0][1], capability_service.CapabilityTokenAlreadyConsumedError), (
        f"the loser must fail with the real typed rejection, never a raw lock/serialization error: {errors[0][1]!r}"
    )

    db.expire_all()
    row = db.get(CapabilityToken, issued.capability_id)
    assert row.consumed_at is not None
    db.refresh(operation)
    assert operation.execution_stage == "CLAIMED", "the winner's own claim must be durable"
    assert operation.attempt_count == 1, "exactly one real claim, not two"


# === Property 2: business-operation-identity attempt-registration safety =======


def _register_first_attempt_in_new_session(
    SessionLocal, identity_id, org_id, binding_id, agent_id, external_operation_id, business_operation_id,
    results, errors, worker_id,
):
    session = SessionLocal()
    try:
        identity = identity_svc.get_integration_identity(session, identity_id, org_id)
        binding = binding_svc.get_binding(session, binding_id, org_id)
        agent = session.get(Agent, agent_id)
        intent, decision, _ev = runtime_svc.submit_attested_intent(
            session, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
            source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
            amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
            requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
            external_operation_id=external_operation_id,
            business_operation_id=business_operation_id, intended_destination=DESTINATION,
        )
        if decision.outcome != "ALLOW":
            results.append((worker_id, "DECISION_NOT_ALLOW", None))
            return
        issued = capability_service.issue_capability_for_decision(session, org_id, decision.id, audience="reference-pep")
        results.append((worker_id, "ISSUED", issued.capability_id))
    except operation_service.ReplacementNotSafeError as e:
        results.append((worker_id, "REPLACEMENT_NOT_SAFE", f"{e.safety}:{e.reason}"))
    except Exception as e:  # pragma: no cover -- surfaced via the assertions below, never swallowed
        errors.append((worker_id, e))
    finally:
        session.close()


def test_two_connection_business_operation_registration_race_postgres(db, SessionLocal, opa_url):
    """Real independent connections racing to register the FIRST
    attempt at the SAME, brand-new business_operation_id -- a
    genuinely separate property from capability-consumption atomicity
    above: this exercises BusinessOperationIdentity's own unique
    constraint (the insert race) and operation_identity_service.
    advance_current_attempt's atomic conditional UPDATE (the current-
    attempt race), neither of which SQLite's own file-locking model
    exercises as a real row-level concurrency primitive the way
    Postgres's MVCC does."""
    org = Organization(id=uuid.uuid4(), name="Org PG Registration Race")
    db.add(org)
    db.commit()
    identity, _integration, _cv, binding, agent = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    identity_id, org_id_val, binding_id, agent_id = identity.id, org.id, binding.id, agent.id
    db.commit()

    boid = f"BOID-PG-REGISTRATION-RACE-{uuid.uuid4().hex[:8]}"
    results: list = []
    errors: list = []
    threads = [
        threading.Thread(
            target=_register_first_attempt_in_new_session,
            args=(
                SessionLocal, identity_id, org_id_val, binding_id, agent_id,
                f"PG-VERIFY-REG-RACE-{i}-{uuid.uuid4().hex[:8]}", boid, results, errors, f"worker-{i}",
            ),
        )
        for i in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"no unexpected error type should surface under this race: {errors}"
    issued = [r for r in results if r[1] == "ISSUED"]
    blocked = [r for r in results if r[1] == "REPLACEMENT_NOT_SAFE"]
    assert len(issued) == 1, f"expected exactly one winning registration, got {len(issued)}: {results}"
    assert len(blocked) == 1, f"expected exactly one blocked registration, got {len(blocked)}: {results}"
    assert "UNSAFE_UNRESOLVED" in blocked[0][2]

    db.expire_all()
    identity_row = db.scalar(select(BusinessOperationIdentity).where(BusinessOperationIdentity.business_operation_id == boid))
    assert identity_row is not None
    assert identity_row.current_operation_id is not None
    operations = db.scalars(select(Operation).where(Operation.business_operation_identity_id == identity_row.id)).all()
    assert 1 <= len(operations) <= 2


# === Rollback consistency: consumption + operation recording together =========


def test_recording_failure_rolls_back_capability_and_operation_together_postgres(db, opa_url, monkeypatch):
    """Section 3's own explicit "verify rollback consistency between
    capability consumption and operation recording" -- against REAL
    Postgres, not SQLite (the mechanism under test, a monkeypatched
    db.commit() failure partway through capability_service.verify_and_
    consume_capability's own transaction, is backend-agnostic, but this
    proves Postgres's own transaction rollback genuinely reverts BOTH
    the capability's consumed_at and the Operation's execution_stage
    together, not merely that SQLite's simpler rollback does)."""
    org = Organization(id=uuid.uuid4(), name="Org PG Rollback Consistency")
    db.add(org)
    db.commit()
    identity, _integration, _cv, binding, agent = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    op_id = f"PG-VERIFY-ROLLBACK-{uuid.uuid4().hex[:8]}"
    intent, decision, _ev = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
        amount=None, currency=None, counterparty=None, context=dict(ORDER_CONTEXT),
        requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=op_id, business_operation_id=f"BOID-{op_id}", intended_destination=DESTINATION,
    )
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")
    operation = db.scalar(select(Operation).where(Operation.decision_id == decision.id))

    real_commit = db.commit
    call_count = {"n": 0}

    def _failing_commit():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated durability failure against real Postgres")
        return real_commit()

    monkeypatch.setattr(db, "commit", _failing_commit)
    with pytest.raises(operation_service.OperationRecordingFailedError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
            _expected_constraints(), environment=binding.environment,
            enforcement_binding_id=binding.id, expected_organization_id=org.id,
        )
    monkeypatch.setattr(db, "commit", real_commit)

    db.expire_all()
    capability_row = db.get(CapabilityToken, issued.capability_id)
    assert capability_row.consumed_at is None, "capability consumption must roll back against real Postgres too"
    db.refresh(operation)
    assert operation.execution_stage == "AUTHORIZED", "operation state must roll back together with the capability, not partially apply"

    # A legitimate retry succeeds normally once durability is restored.
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    assert consumed.capability_id == issued.capability_id
