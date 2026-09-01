"""Trusted Integration Architecture, Phase 5.1: real-PostgreSQL proof
that `capability_tokens.decision_id`'s new UNIQUE constraint (migration
d4e8b1a6f2c9) actually provides the concurrency guarantee
capability_service.py's own docstring claims, plus a real upgrade/
downgrade/re-upgrade round trip exercising the migration's dedup logic
against genuine pre-existing duplicate rows -- something SQLite's own
ALTER-TABLE limitations make impractical to reproduce (this repo has no
existing precedent for running incremental Alembic migrations against
SQLite; every other migration-adjacent test here uses this same
postgres_url fixture instead, or verifies final model state only).

Uses the project's own existing docker-compose Postgres service via the
`postgres_url` fixture (tests/integration/conftest.py) -- skips cleanly
if Postgres isn't reachable. `postgres_url` itself already runs
`alembic upgrade head` before yielding, so every test below implicitly
also proves the migration applies cleanly to a fresh database before
doing anything else.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.db.models import Agent, CapabilityToken, Organization, Principal
from app.domain.decision import engine as decision_engine
from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import capability_service, intent_service, runtime_policy_service as policy_svc

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


@pytest.fixture()
def org(db):
    org = Organization(id=uuid.uuid4(), name="Org Capability Idempotency Postgres")
    db.add(org)
    db.commit()
    return org


def _allow_decision(db, org_id, opa_url, resource="supplier:123"):
    principal = Principal(id=uuid.uuid4(), name="alice", organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="AP Invoice Agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()

    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="test policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="alice", action="vendor_payment", resource=resource),
        conditions=ConditionSet(all=()), effect=Effect.ALLOW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)

    _intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action="vendor_payment", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource=resource,
    )
    assert decision.outcome == "ALLOW"
    return decision


# --- Real concurrency: the UNIQUE constraint, not app logic, is the guarantee ----


def _issue_in_new_session(SessionLocal, org_id, decision_id, results, errors, barrier):
    session = SessionLocal()
    try:
        barrier.wait(timeout=30)
        issued = capability_service.issue_capability_for_decision(
            session, org_id, decision_id, audience="reference-adapter",
        )
        results.append(issued.capability_id)
    except Exception as e:  # pragma: no cover -- surfaced via the assertions below, never swallowed
        errors.append(e)
    finally:
        session.close()


def test_two_concurrent_issuance_requests_for_the_same_decision_never_both_succeed(db, SessionLocal, org, opa_url):
    """The real regression test for section 1/2/7 of this milestone's
    own brief: two genuinely concurrent requests to issue a Capability
    for the SAME ALLOW Decision, started at the same instant from two
    separate sessions/connections. Before this phase, both succeeded,
    minting two independently valid, independently consumable
    Capabilities -- confirmed as the actual pre-existing behavior before
    writing this fix (see this milestone's own final report, section A).
    After the fix, exactly one must succeed; the other must fail with
    one of the three typed "already exists" errors, never a raw
    IntegrityError and never a second successful issuance."""
    decision = _allow_decision(db, org.id, opa_url)
    decision_id = decision.id

    barrier = threading.Barrier(2)
    results: list = []
    errors: list = []

    t1 = threading.Thread(target=_issue_in_new_session, args=(SessionLocal, org.id, decision_id, results, errors, barrier))
    t2 = threading.Thread(target=_issue_in_new_session, args=(SessionLocal, org.id, decision_id, results, errors, barrier))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert len(results) == 1, f"expected exactly one successful issuance, got {len(results)}: {results}"
    assert len(errors) == 1, f"expected exactly one rejected issuance, got {len(errors)}: {errors}"
    assert isinstance(
        errors[0],
        (
            capability_service.CapabilityAlreadyIssuedError,
            capability_service.CapabilityAlreadyConsumedForDecisionError,
            capability_service.CapabilityExpiredNotRenewedError,
        ),
    ), f"the loser must fail with one of the three typed errors, not: {errors[0]!r}"

    rows = list(db.scalars(select(CapabilityToken).where(CapabilityToken.decision_id == decision_id)))
    assert len(rows) == 1, f"the UNIQUE constraint must leave exactly one row, found {len(rows)}"
    assert rows[0].id == results[0]


# --- Migration round trip: downgrade, seed real duplicates, re-upgrade -----------


def test_migration_downgrade_and_reupgrade_deduplicates_real_pre_existing_rows(db, engine, org, opa_url):
    """Runs the actual migration script (not a reimplementation) against
    a real Postgres database: downgrades one revision (removing the
    UNIQUE constraint this phase adds), inserts two genuine duplicate
    capability_tokens rows for the same decision_id directly via raw SQL
    -- the exact pre-existing-data shape the migration's own upgrade()
    docstring describes -- then upgrades back to head and confirms
    exactly one row survives (the consumed one) and the constraint is
    back in place."""
    from alembic import command
    from alembic.config import Config

    decision = _allow_decision(db, org.id, opa_url)
    decision_id = decision.id

    server_dir = str(list(__import__("pathlib").Path(__file__).resolve().parents)[2])
    cfg = Config(f"{server_dir}/alembic.ini")
    cfg.set_main_option("sqlalchemy.url", str(engine.url))

    command.downgrade(cfg, "-1")

    consumed_id = uuid.uuid4()
    unconsumed_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        for row_id, consumed_at, issued_at in (
            (consumed_id, now - timedelta(minutes=5), now - timedelta(minutes=20)),
            (unconsumed_id, None, now - timedelta(minutes=1)),
        ):
            conn.execute(
                text(
                    "INSERT INTO capability_tokens "
                    "(id, organization_id, decision_id, audience, nonce, token_hash, "
                    " issued_at, expires_at, consumed_at) "
                    "VALUES (:id, :org_id, :decision_id, 'reference-adapter', :nonce, :hash, "
                    " :issued_at, :expires_at, :consumed_at)"
                ),
                {
                    "id": row_id, "org_id": org.id, "decision_id": decision_id,
                    "nonce": uuid.uuid4().hex, "hash": uuid.uuid4().hex,
                    "issued_at": issued_at, "expires_at": now + timedelta(minutes=5),
                    "consumed_at": consumed_at,
                },
            )

    duplicate_count = list(engine.connect().execute(
        text("SELECT count(*) FROM capability_tokens WHERE decision_id = :d"), {"d": decision_id}
    ))[0][0]
    assert duplicate_count == 2, "setup sanity check: two duplicate rows must exist before the re-upgrade"

    command.upgrade(cfg, "head")

    remaining = list(db.scalars(select(CapabilityToken).where(CapabilityToken.decision_id == decision_id)))
    assert len(remaining) == 1, f"expected the migration to deduplicate down to one row, found {len(remaining)}"
    assert remaining[0].id == consumed_id, "the consumed row must be the one preserved, not the unconsumed one"

    with pytest.raises(Exception):
        # The constraint must be back: a second row for the same
        # decision_id is rejected at the database level again.
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO capability_tokens "
                    "(id, organization_id, decision_id, audience, nonce, token_hash, issued_at, expires_at) "
                    "VALUES (:id, :org_id, :decision_id, 'reference-adapter', :nonce, :hash, now(), now())"
                ),
                {"id": uuid.uuid4(), "org_id": org.id, "decision_id": decision_id, "nonce": uuid.uuid4().hex, "hash": uuid.uuid4().hex},
            )
