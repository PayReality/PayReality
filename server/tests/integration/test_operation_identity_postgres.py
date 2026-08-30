"""Trusted Integration Architecture, Phase 3: real-PostgreSQL proof of
business-operation identity -- both the ordinary, single-threaded
scenarios that genuinely require a real partial-unique index (Binding
replacement, certificate rotation, semantically-identical Contract
replacement -- see test_operation_identity.py's own notes for why these
cannot run on SQLite), and the actual concurrency invariants sections
18-20/41 require: concurrent identical requests produce exactly one
Decision, concurrent conflicting requests produce one Decision plus one
typed conflict, and different external_operation_id values under the
same Integration never serialize against each other.

Uses the project's own existing docker-compose Postgres service via the
`postgres_url` fixture and this repo's established "force the exact
interleaving deterministically, via a threading.Barrier, never rely on
timing" convention (test_integration_contract_concurrency.py,
test_enforcement_binding_concurrency.py).
"""

import threading
import time
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Decision, Evidence, Intent, Organization, Principal
from app.domain.decision import engine as decision_engine
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
)
from app.services.integration_runtime_service import ExternalOperationConflictError

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)


@pytest.fixture()
def engine(postgres_url):
    return create_engine(postgres_url)


@pytest.fixture()
def SessionLocal(engine):
    return sessionmaker(bind=engine)


@pytest.fixture()
def db(SessionLocal):
    session = SessionLocal()
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


def _deploy_policy(db, org_id, opa_url, effect=Effect.ALLOW, action="vendor_payment",
                    resource="supplier:123", principal="alice"):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="test policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal=principal, action=action, resource=resource),
        conditions=ConditionSet(all=()), effect=effect,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row.policy_key


def _setup(db, org_id, resource_path="supplier.id", environment="production", integration=None, extra_agent=False):
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "Reference SAP Adapter", "ed25519:base64:AAAA")
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)

    if integration is None:
        integration = contract_svc.create_integration(db, org_id, "SAP S/4HANA (reference)")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, "ChangeSupplierBankDetails", "vendor_payment", resource_path=resource_path,
    )
    contract_version = contract_svc.validate_contract_version(db, contract_version.id, org_id)
    contract_version = contract_svc.approve_contract_version(db, contract_version.id, org_id, approver="governance-admin@example.com")

    principal = Principal(id=uuid.uuid4(), name="alice", organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="AP Invoice Agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    agent_ids = [agent.id]
    second_agent = None
    if extra_agent:
        second_agent = Agent(id=uuid.uuid4(), name="Second Allowed Agent", acting_for_principal_id=principal.id, status="active")
        db.add(second_agent)
        db.commit()
        agent_ids.append(second_agent.id)

    binding = binding_svc.create_draft_binding(db, org_id, identity.id, contract_version.id, environment, agent_ids=agent_ids)
    binding = binding_svc.activate_binding(db, binding.id, org_id)
    return identity, integration, contract_version, binding, agent, second_agent


def _attest(db, identity, binding, agent, *, resource="supplier:123", external_operation_id="OP-1", nonce=None):
    return runtime_svc.submit_attested_intent(
        db, identity,
        enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation="ChangeSupplierBankDetails", action="vendor_payment", resource=resource,
        amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc),
        nonce=nonce or uuid.uuid4().hex, correlation_id=None,
        external_operation_id=external_operation_id,
    )


# --- Single-threaded scenarios that require a real partial-unique index ---


def test_certificate_rotation_does_not_reset_idempotency(db, opa_url):
    org = Organization(id=uuid.uuid4(), name="Org Cert Rotation")
    db.add(org)
    db.commit()
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    _intent1, decision1, _e1 = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    identity_svc.rotate_certificate(db, identity.id, org.id, "ed25519:base64:BBBB")

    _intent2, decision2, _e2 = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    assert decision2.id == decision1.id


def test_same_id_under_replacement_binding_still_dedupes(db, opa_url):
    org = Organization(id=uuid.uuid4(), name="Org Binding Replacement")
    db.add(org)
    db.commit()
    identity, _integ, cv, binding1, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    _intent1, decision1, _e1 = _attest(db, identity, binding1, agent, external_operation_id="OP-1")

    binding_svc.retire_binding(db, binding1.id, org.id)
    binding2 = binding_svc.create_draft_binding(db, org.id, identity.id, cv.id, "production", agent_ids=[agent.id])
    binding2 = binding_svc.activate_binding(db, binding2.id, org.id)

    _intent2, decision2, _e2 = _attest(db, identity, binding2, agent, external_operation_id="OP-1")
    assert decision2.id == decision1.id


def test_matching_retry_after_semantically_identical_contract_replacement_returns_original(db, opa_url):
    org = Organization(id=uuid.uuid4(), name="Org Semantic Replacement")
    db.add(org)
    db.commit()
    identity, integration, cv1, binding1, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    _intent1, decision1, _e1 = _attest(db, identity, binding1, agent, external_operation_id="OP-1")

    cv2 = contract_svc.create_contract_version(
        db, integration.id, org.id, "ChangeSupplierBankDetails", "vendor_payment", resource_path="supplier.id",
    )
    cv2 = contract_svc.validate_contract_version(db, cv2.id, org.id)
    cv2 = contract_svc.approve_contract_version(db, cv2.id, org.id, approver="governance-admin@example.com")
    assert cv2.content_hash == cv1.content_hash
    assert cv2.id != cv1.id

    binding_svc.retire_binding(db, binding1.id, org.id)
    binding2 = binding_svc.create_draft_binding(db, org.id, identity.id, cv2.id, "production", agent_ids=[agent.id])
    binding2 = binding_svc.activate_binding(db, binding2.id, org.id)

    _intent2, decision2, _e2 = _attest(db, identity, binding2, agent, external_operation_id="OP-1")
    assert decision2.id == decision1.id


def test_changed_contract_meaning_conflicts_across_a_replacement_binding(db, opa_url):
    org = Organization(id=uuid.uuid4(), name="Org Changed Meaning")
    db.add(org)
    db.commit()
    identity, integration, cv1, binding1, agent, _ = _setup(db, org.id, resource_path="supplier.id")
    _deploy_policy(db, org.id, opa_url)
    _attest(db, identity, binding1, agent, resource="supplier:123", external_operation_id="OP-1")

    cv2 = contract_svc.create_contract_version(
        db, integration.id, org.id, "ChangeSupplierBankDetails", "vendor_payment", resource_path=None,
    )
    cv2 = contract_svc.validate_contract_version(db, cv2.id, org.id)
    cv2 = contract_svc.approve_contract_version(db, cv2.id, org.id, approver="governance-admin@example.com")
    assert cv2.content_hash != cv1.content_hash

    binding_svc.retire_binding(db, binding1.id, org.id)
    binding2 = binding_svc.create_draft_binding(db, org.id, identity.id, cv2.id, "production", agent_ids=[agent.id])
    binding2 = binding_svc.activate_binding(db, binding2.id, org.id)

    with pytest.raises(ExternalOperationConflictError):
        _attest(db, identity, binding2, agent, resource=None, external_operation_id="OP-1")


# --- Concurrency (sections 18-20, 41) ---------------------------------------


def _attest_in_new_session(SessionLocal, identity_id, org_id, binding_id, agent_id, external_operation_id, results, errors):
    session = SessionLocal()
    try:
        identity = identity_svc.get_integration_identity(session, identity_id, org_id)
        binding = binding_svc.get_binding(session, binding_id, org_id)
        agent = session.get(Agent, agent_id)
        intent, decision, _evidence = runtime_svc.submit_attested_intent(
            session, identity,
            enforcement_binding_id=binding.id, origin_agent_id=agent.id,
            source_operation="ChangeSupplierBankDetails", action="vendor_payment", resource="supplier:123",
            amount=None, currency=None, counterparty=None,
            context={}, requested_at=datetime.now(timezone.utc),
            nonce=uuid.uuid4().hex, correlation_id=None,
            external_operation_id=external_operation_id,
        )
        results.append((intent.id, decision.id))
    except Exception as e:  # pragma: no cover -- surfaced via the assertion below, never swallowed
        errors.append(e)
    finally:
        session.close()


def test_two_concurrent_identical_requests_produce_exactly_one_decision(db, SessionLocal, opa_url):
    """Section 18: same scope, same external_operation_id, same
    canonical fingerprint, genuinely simultaneous. Exactly one real
    Runtime Authority evaluation must occur; the other request must
    reference (not duplicate) that one Decision."""
    org = Organization(id=uuid.uuid4(), name="Org Concurrent Identical")
    db.add(org)
    db.commit()
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    barrier = threading.Barrier(2)
    real_submit = runtime_svc.submit_attested_intent

    def synchronized_submit(*args, **kwargs):
        tid = threading.get_ident()
        if tid not in synchronized_submit._synced:
            synchronized_submit._synced.add(tid)
            barrier.wait(timeout=30)
        return real_submit(*args, **kwargs)

    synchronized_submit._synced = set()
    runtime_svc.submit_attested_intent = synchronized_submit

    results: list = []
    errors: list = []
    try:
        threads = [
            threading.Thread(
                target=_attest_in_new_session,
                args=(SessionLocal, identity.id, org.id, binding.id, agent.id, "OP-CONCURRENT-1", results, errors),
            )
            for _ in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
    finally:
        runtime_svc.submit_attested_intent = real_submit

    assert not errors, f"submit_attested_intent raised under concurrency: {errors}"
    assert len(results) == 2
    decision_ids = {d for _i, d in results}
    intent_ids = {i for i, _d in results}
    assert len(decision_ids) == 1, f"expected exactly one Decision, got {decision_ids}"
    assert len(intent_ids) == 1, f"expected exactly one Intent, got {intent_ids}"

    db_intents = list(db.scalars(select(Intent).where(Intent.external_operation_id == "OP-CONCURRENT-1")))
    db_decisions = list(db.scalars(select(Decision).where(Decision.intent_id.in_([i.id for i in db_intents]))))
    assert len(db_intents) == 1
    assert len(db_decisions) == 1
    evidence_rows = list(db.scalars(select(Evidence).where(Evidence.decision_id == db_decisions[0].id)))
    assert len(evidence_rows) == 1, "no double Evidence-chain append for the same Decision"


def test_two_concurrent_conflicting_requests_produce_one_decision_and_one_conflict(db, SessionLocal, opa_url):
    """Section 19: same scope, same external_operation_id, DIFFERENT
    canonical fingerprint (different resource), genuinely simultaneous.
    Exactly one may establish the operation; the other must receive the
    typed conflict -- never a second Decision, never a raw 500."""
    org = Organization(id=uuid.uuid4(), name="Org Concurrent Conflict")
    db.add(org)
    db.commit()
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url, resource="supplier:123")
    _deploy_policy(db, org.id, opa_url, resource="supplier:999")

    barrier = threading.Barrier(2)
    real_submit = runtime_svc.submit_attested_intent

    def synchronized_submit(*args, **kwargs):
        tid = threading.get_ident()
        if tid not in synchronized_submit._synced:
            synchronized_submit._synced.add(tid)
            barrier.wait(timeout=30)
        return real_submit(*args, **kwargs)

    synchronized_submit._synced = set()
    runtime_svc.submit_attested_intent = synchronized_submit

    def _attest_with_resource(SessionLocal, resource, results, errors):
        session = SessionLocal()
        try:
            identity_row = identity_svc.get_integration_identity(session, identity.id, org.id)
            binding_row = binding_svc.get_binding(session, binding.id, org.id)
            agent_row = session.get(Agent, agent.id)
            intent, decision, _evidence = runtime_svc.submit_attested_intent(
                session, identity_row,
                enforcement_binding_id=binding_row.id, origin_agent_id=agent_row.id,
                source_operation="ChangeSupplierBankDetails", action="vendor_payment", resource=resource,
                amount=None, currency=None, counterparty=None,
                context={}, requested_at=datetime.now(timezone.utc),
                nonce=uuid.uuid4().hex, correlation_id=None,
                external_operation_id="OP-CONFLICT-1",
            )
            results.append((intent.id, decision.id))
        except Exception as e:
            errors.append(e)
        finally:
            session.close()

    results: list = []
    errors: list = []
    try:
        t1 = threading.Thread(target=_attest_with_resource, args=(SessionLocal, "supplier:123", results, errors))
        t2 = threading.Thread(target=_attest_with_resource, args=(SessionLocal, "supplier:999", results, errors))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)
    finally:
        runtime_svc.submit_attested_intent = real_submit

    assert len(results) + len(errors) == 2
    assert len(results) == 1, f"exactly one request must establish the operation, got {len(results)} successes"
    assert len(errors) == 1, f"exactly one request must conflict, got {len(errors)} errors"
    assert isinstance(errors[0], ExternalOperationConflictError), (
        f"the losing request's failure must be the typed conflict, never a raw error, got: {errors[0]!r}"
    )

    db_intents = list(db.scalars(select(Intent).where(Intent.external_operation_id == "OP-CONFLICT-1")))
    assert len(db_intents) == 1, "no second Intent may be committed for the conflicting request"
    db_decisions = list(db.scalars(select(Decision).where(Decision.intent_id.in_([i.id for i in db_intents]))))
    assert len(db_decisions) == 1


def test_different_operation_ids_do_not_serialize(db, SessionLocal, opa_url):
    """Section 20: two different external_operation_id values under the
    same Integration must proceed independently -- no shared lock forces
    them to serialize. Proven the same way test_integration_contract_
    concurrency.py already proves the analogous claim for different
    source_operation tuples: N genuinely simultaneous, genuinely
    different-scope racers should all land on their own operation on the
    very first attempt, with no contention-driven retry needed."""
    org = Organization(id=uuid.uuid4(), name="Org No False Serialization")
    db.add(org)
    db.commit()
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    operation_ids = [f"OP-INDEPENDENT-{i}" for i in range(4)]
    barrier = threading.Barrier(len(operation_ids))

    def _attest_independent(SessionLocal, external_operation_id, results, errors):
        tid = threading.get_ident()
        if tid not in _attest_independent._synced:
            _attest_independent._synced.add(tid)
            barrier.wait(timeout=30)
        _attest_in_new_session(SessionLocal, identity.id, org.id, binding.id, agent.id, external_operation_id, results, errors)

    _attest_independent._synced = set()

    results: list = []
    errors: list = []
    start = time.monotonic()
    threads = [
        threading.Thread(target=_attest_independent, args=(SessionLocal, op_id, results, errors))
        for op_id in operation_ids
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    elapsed = time.monotonic() - start

    assert not errors, f"independent external_operation_id values must never conflict: {errors}"
    assert len(results) == len(operation_ids)
    decision_ids = {d for _i, d in results}
    assert len(decision_ids) == len(operation_ids), "each independent operation must get its own Decision"
    assert elapsed < 10, f"unexpectedly slow ({elapsed:.2f}s) -- possible unwanted cross-operation serialization"
