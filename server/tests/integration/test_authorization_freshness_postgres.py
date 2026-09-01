"""Trusted Integration Phase 6.1: real-PostgreSQL proof that the new
freshness check (Part A) added inside `verify_and_consume_capability`,
directly ahead of the atomic single-use UPDATE, does not weaken the
database-level single-use guarantee under genuine multi-connection
concurrency, and that tenant scoping (Part B) holds the same way -- the
correct-tenant consumer wins a real race, the wrong-tenant one never
marks the token consumed, even when both attempts land on the database
at the same instant from separate connections.

SQLite cannot exercise this: it serializes writers at the process level,
so a SQLite-only test proves the Python code is well-ordered, never that
the database itself enforces the guarantee under real concurrent access.
`server/tests/integration/test_capability_tokens.py` already covers the
sequential (SQLite) shape of every one of these scenarios; this file
adds only what genuine concurrency requires, following the same
threading.Barrier + separate-session-per-thread pattern already
established in `test_capability_issuance_idempotency_postgres.py` for
the analogous Phase 5.1 issuance race.

Uses the project's own existing docker-compose Postgres service via the
`postgres_url` fixture (tests/integration/conftest.py) -- skips cleanly
if Postgres isn't reachable.
"""

import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, CapabilityToken, Organization, Principal
from app.domain.capability import token as capability_token
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import capability_service, intent_service, runtime_policy_service as policy_svc, signing_key_service

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
    signing_key_service.ensure_current_key_registered(
        session, settings.evidence_signing_key_id,
        public_key_b64_from_signing_key_b64(settings.evidence_signing_key_b64),
    )
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def org(db):
    org = Organization(id=uuid.uuid4(), name="Org Freshness Postgres")
    db.add(org)
    db.commit()
    return org


def _allow_decision(db, org_id, opa_url, action="vendor_payment", resource="invoice-123", amount=48000.0):
    principal = Principal(id=uuid.uuid4(), name="alice", organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="AP Invoice Agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()

    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="test policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="alice", action=action),
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value=50000),)),
        effect=Effect.ALLOW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)

    _intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action=action, amount=amount, currency="USD", counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=resource,
        resource=resource,
    )
    assert decision.outcome == "ALLOW"
    return decision


# --- Consumption race, with the new freshness check now in the path ------


def _consume_in_new_session(SessionLocal, token, org_id, results, errors, barrier):
    session = SessionLocal()
    try:
        barrier.wait(timeout=30)
        consumed = capability_service.verify_and_consume_capability(
            session, token, "sap-reference-adapter", "vendor_payment", "invoice-123",
            {"amount": "48000.00", "currency": "USD"}, expected_organization_id=org_id,
        )
        results.append(consumed.capability_id)
    except Exception as e:  # pragma: no cover -- surfaced via the assertions below, never swallowed
        errors.append(e)
    finally:
        session.close()


def test_two_concurrent_consumption_attempts_for_the_same_capability_never_both_succeed(db, SessionLocal, org, opa_url):
    """The real regression test for section 8 of this milestone's own
    brief: with `_check_consumption_freshness` now running inside
    `verify_and_consume_capability` immediately ahead of the atomic
    single-use UPDATE, two genuinely concurrent presentations of the
    SAME token, started at the same instant from two separate
    connections, must still never both succeed. The freshness check
    itself is a plain SELECT against Agent/Organization (no locking) --
    this test proves that adding it did not reopen the double-spend
    window the UPDATE ... WHERE consumed_at IS NULL pattern closes."""
    decision = _allow_decision(db, org.id, opa_url)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="sap-reference-adapter")

    barrier = threading.Barrier(2)
    results: list = []
    errors: list = []

    t1 = threading.Thread(target=_consume_in_new_session, args=(SessionLocal, issued.token, org.id, results, errors, barrier))
    t2 = threading.Thread(target=_consume_in_new_session, args=(SessionLocal, issued.token, org.id, results, errors, barrier))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert len(results) == 1, f"expected exactly one successful consumption, got {len(results)}: {results}"
    assert len(errors) == 1, f"expected exactly one rejected consumption, got {len(errors)}: {errors}"
    assert isinstance(errors[0], capability_service.CapabilityTokenAlreadyConsumedError), (
        f"the loser must fail with the replay error, not: {errors[0]!r}"
    )

    row = db.scalar(select(CapabilityToken).where(CapabilityToken.id == results[0]))
    assert row is not None and row.consumed_at is not None


# --- Cross-tenant race: the wrong tenant never wins, even racing the right one --


def _verify_as_tenant_in_new_session(SessionLocal, token, org_id, label, results, errors, barrier):
    session = SessionLocal()
    try:
        barrier.wait(timeout=30)
        consumed = capability_service.verify_and_consume_capability(
            session, token, "sap-reference-adapter", "vendor_payment", "invoice-123",
            {"amount": "48000.00", "currency": "USD"}, expected_organization_id=org_id,
        )
        results.append((label, consumed.capability_id))
    except Exception as e:  # pragma: no cover -- surfaced via the assertions below, never swallowed
        errors.append((label, e))
    finally:
        session.close()


def test_wrong_tenant_verifier_never_wins_a_real_race_against_the_correct_tenant(db, SessionLocal, org, opa_url):
    """Section 12's cross-tenant hostile case, exercised under genuine
    concurrency rather than sequential ordering: Org B's verifier and
    Org A's (the Capability's real owner) verifier both present the
    same token at the same instant from separate connections. Org B
    must never succeed regardless of which thread the database happens
    to schedule first, and the token must end up consumed by Org A,
    never left unconsumed and never double-consumed."""
    other_org = Organization(id=uuid.uuid4(), name="Org Freshness Postgres B")
    db.add(other_org)
    db.commit()

    decision = _allow_decision(db, org.id, opa_url)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="sap-reference-adapter")

    barrier = threading.Barrier(2)
    results: list = []
    errors: list = []

    t_correct = threading.Thread(
        target=_verify_as_tenant_in_new_session,
        args=(SessionLocal, issued.token, org.id, "correct-tenant", results, errors, barrier),
    )
    t_wrong = threading.Thread(
        target=_verify_as_tenant_in_new_session,
        args=(SessionLocal, issued.token, other_org.id, "wrong-tenant", results, errors, barrier),
    )
    t_correct.start()
    t_wrong.start()
    t_correct.join(timeout=30)
    t_wrong.join(timeout=30)

    assert len(results) == 1 and results[0][0] == "correct-tenant", (
        f"only the correct tenant may ever succeed, got results={results}"
    )
    assert len(errors) == 1 and errors[0][0] == "wrong-tenant", f"expected the wrong tenant to fail, got errors={errors}"
    assert isinstance(errors[0][1], capability_token.CapabilityTenantMismatchError), (
        f"the wrong tenant must fail with the tenant-mismatch error specifically, not: {errors[0][1]!r}"
    )

    row = db.scalar(select(CapabilityToken).where(CapabilityToken.id == results[0][1]))
    assert row is not None and row.consumed_at is not None, "the correct tenant's consumption must have actually landed"
