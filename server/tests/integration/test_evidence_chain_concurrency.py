"""PayReality 1.0 Audit finding G01: the Evidence hash-chain concurrency
race, and its fix (intent_service._lock_chain_scope). Deliberately
duplicates the setup helpers established elsewhere in this test suite
rather than sharing a conftest, matching this repo's own convention for
these integration test files.

Tests call intent_service.append_evidence directly (not the full
submit_intent pipeline) -- append_evidence is the single choke point
every Evidence-creating code path in this codebase actually goes
through (submit_intent's three outcome branches, and
resolution_service.resolve_decision), so exercising it directly both
proves the fix at its real root and avoids dragging in an unrelated
OPA/policy-compilation dependency this narrow correctness fix has
nothing to do with.

Both tests below use a real file-backed SQLite database (not
`sqlite:///:memory:`) so two genuinely separate connections/sessions --
one per worker thread -- interleave for real, plus a real SQLite
busy_timeout (so a write-lock collision blocks briefly rather than
raising `database is locked` immediately) and a `threading.Barrier` to
force the exact interleaving deterministically rather than relying on
timing (`time.sleep`) to get lucky.

Honest scope note: production runs on Postgres, and the fix's actual
serialization primitive is a real `SELECT ... FOR UPDATE` row lock,
whose blocking guarantee is standard, extremely well-established
Postgres/SQL semantics -- not something these tests re-derive from
scratch. SQLite provides no row-level locking at all (confirmed
separately: adding `.with_for_update()` to a SQLite query is silently
compiled away, not an error) and serializes writes at the whole-
database level, coarser than and different from Postgres MVCC -- so it
cannot be used to prove that a real database row lock blocks a second
transaction's read. What CAN be proven here, and is proven below, is
that the surrounding algorithm is correct: `_lock_chain_scope` is
called before `_previous_chain_hash` (never after), and -- given that a
lock at that point genuinely provides mutual exclusion held until the
enclosing transaction finishes (exactly what Postgres's FOR UPDATE
guarantees) -- the resulting committed chain is provably linear, never
forked. A real multi-connection Postgres instance was not reachable in
this environment (Docker Desktop is installed but its daemon is not
running here) to additionally verify the row lock's own blocking
behavior live against Postgres specifically; that verification is
disclosed as outstanding, not silently assumed.
"""

import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Base, Decision, Evidence, Intent, Organization, Principal
from app.domain.evidence.signing import payload_hash
from app.services import evidence_service, intent_service

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="


@compiles(PG_JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _uuid_as_char_on_sqlite(element, compiler, **kw):
    return "CHAR(36)"


@pytest.fixture()
def engine(tmp_path):
    """A real file-backed SQLite database -- deliberately not
    `:memory:` -- so two independently-created sessions (one per worker
    thread below) are genuinely separate connections able to interleave,
    not a single shared in-process object graph. A generous busy_timeout
    means a real write-lock collision between the two connections blocks
    briefly rather than raising `database is locked` immediately --
    matching what the test wants to observe (whether a fork happens),
    not an artifact of SQLite's own unrelated whole-database write
    serialization."""
    eng = create_engine(
        f"sqlite:///{tmp_path / 'evidence_chain_race.db'}", connect_args={"timeout": 30}
    )
    policies_table = Base.metadata.tables["policies"]
    partial_index = next(i for i in policies_table.indexes if i.name == "idx_policies_single_active_per_org")
    policies_table.indexes.discard(partial_index)
    try:
        Base.metadata.create_all(eng)
    finally:
        policies_table.indexes.add(partial_index)
    return eng


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


def _org_principal_agent(db, org_name="Org A", principal_name="alice"):
    org = Organization(id=uuid.uuid4(), name=org_name)
    db.add(org)
    db.flush()
    principal = Principal(id=uuid.uuid4(), name=principal_name, organization_id=org.id)
    db.add(principal)
    db.flush()
    agent = Agent(id=uuid.uuid4(), name=f"{principal_name}-agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    return org, principal, agent


def _intent_and_decision(db, agent_id) -> uuid.UUID:
    """The minimal, valid prerequisite state append_evidence itself
    requires (a real Decision row to attach to) -- no OPA, no
    RuntimePolicy, no compiled bundle needed, since this test exercises
    append_evidence directly, not the full submit_intent pipeline."""
    intent = Intent(
        id=uuid.uuid4(), agent_id=agent_id, action="vendor_payment", amount=100.0, currency="USD",
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex,
    )
    db.add(intent)
    db.flush()
    decision = Decision(intent_id=intent.id, outcome="ALLOW", reason=None, evaluated_mandates=[], evaluated_mandate_ids=[])
    db.add(decision)
    db.commit()
    return decision.id


@pytest.fixture()
def org_and_agent(db):
    return _org_principal_agent(db)


class _FakeRowLock:
    """Stands in for the real Postgres `SELECT ... FOR UPDATE` row lock
    that intent_service._lock_chain_scope takes in production -- see
    this module's own docstring for why SQLite cannot be used to
    reproduce that mechanism directly. This fake gives the exact same
    guarantee production relies on: mutual exclusion per organization_id,
    acquired at the same point _lock_chain_scope is called and held
    until the enclosing transaction has fully finished (its own
    db.commit()) -- not just until _lock_chain_scope itself returns."""

    def __init__(self):
        self._locks: dict[uuid.UUID, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock_for(self, organization_id: uuid.UUID) -> threading.Lock:
        with self._guard:
            if organization_id not in self._locks:
                self._locks[organization_id] = threading.Lock()
            return self._locks[organization_id]

    def acquire(self, organization_id: uuid.UUID) -> None:
        self._lock_for(organization_id).acquire()

    def release(self, organization_id: uuid.UUID) -> None:
        self._lock_for(organization_id).release()


def _append_and_commit_in_new_session(SessionLocal, decision_id, agent_id, results, errors):
    session = SessionLocal()
    try:
        evidence = intent_service.append_evidence(
            session, decision_id, agent_id, "vendor_payment", 100.0, [], "ALLOW",
        )
        session.commit()
        results.append(evidence.id)
    except Exception as e:  # pragma: no cover -- surfaced via the assertion below, not swallowed
        errors.append(e)
    finally:
        session.close()


def test_concurrent_evidence_appends_for_the_same_org_never_fork_the_chain(
    db, org_and_agent, SessionLocal, monkeypatch
):
    """G01, the actual regression test: two append_evidence calls for
    the SAME organization, started at genuinely the same time from two
    separate threads/sessions, racing to append Evidence. With the real
    _lock_chain_scope call point wrapped in a lock that's held from
    "before re-reading the latest Evidence" through "after this
    transaction commits" (exactly what a real Postgres row lock
    provides), the result must be exactly one linear chain -- never two
    records both claiming no predecessor."""
    org, principal, agent = org_and_agent
    # Captured as plain values *in the main thread* before any worker
    # thread starts -- the ORM objects above belong to the main thread's
    # own session and must never be touched from another thread (an
    # expired-attribute reload from the wrong thread against a SQLite
    # connection it doesn't own is exactly what corrupted an earlier
    # version of this test with a low-level driver error).
    org_id, agent_id = org.id, agent.id
    decision_1 = _intent_and_decision(db, agent_id)
    decision_2 = _intent_and_decision(db, agent_id)

    fake_lock = _FakeRowLock()
    real_lock_chain_scope = intent_service._lock_chain_scope
    start_barrier = threading.Barrier(2)

    def synchronized_lock_chain_scope(session, organization_id):
        # Both threads arrive here at essentially the same instant --
        # whichever the fake lock lets through first genuinely blocks
        # the other until it releases (i.e. until that thread's whole
        # append_evidence + commit has finished).
        start_barrier.wait(timeout=30)
        fake_lock.acquire(organization_id)
        real_lock_chain_scope(session, organization_id)

    monkeypatch.setattr(intent_service, "_lock_chain_scope", synchronized_lock_chain_scope)

    results: list = []
    errors: list = []

    def worker(decision_id):
        try:
            _append_and_commit_in_new_session(SessionLocal, decision_id, agent_id, results, errors)
        finally:
            fake_lock.release(org_id)

    t1 = threading.Thread(target=worker, args=(decision_1,))
    t2 = threading.Thread(target=worker, args=(decision_2,))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert not errors, f"append_evidence raised under concurrency: {errors}"
    assert len(results) == 2

    records = list(
        db.scalars(
            select(Evidence)
            .where(Evidence.organization_id == org_id)
            .order_by(Evidence.created_at, Evidence.id)
        )
    )
    assert len(records) == 2

    previous_hashes = [r.payload.get("previous_hash") for r in records]
    # Exactly one record has no predecessor (the genuine first link);
    # the other's previous_hash must equal the first record's own
    # payload hash -- a real, single, linear chain, not two records
    # both claiming to be first (a fork).
    assert previous_hashes.count(None) == 1, (
        f"chain forked: {previous_hashes.count(None)} records claim no predecessor (expected exactly 1)"
    )
    first, second = (records if previous_hashes[0] is None else records[::-1])
    assert second.payload["previous_hash"] == payload_hash(first.payload)

    result = evidence_service.verify_chain(db, org_id)
    assert result.broken_links == ()
    assert result.invalid_signatures == ()


def test_without_the_lock_concurrent_evidence_appends_can_fork_the_chain(
    db, org_and_agent, SessionLocal, monkeypatch
):
    """Negative control proving G01 was a real, reproducible bug, not a
    hypothetical: with _lock_chain_scope bypassed entirely and a barrier
    forcing both threads to call _previous_chain_hash (read "the current
    latest Evidence") before either has committed -- the exact
    interleaving the original bug depended on -- the chain genuinely
    forks. This is the same test as above with only the fix disabled,
    so a regression that silently reintroduces the race would fail
    here by *passing* when it should fork, or fail the positive test
    above by forking when it shouldn't."""
    org, principal, agent = org_and_agent
    org_id, agent_id = org.id, agent.id
    decision_1 = _intent_and_decision(db, agent_id)
    decision_2 = _intent_and_decision(db, agent_id)

    monkeypatch.setattr(intent_service, "_lock_chain_scope", lambda session, organization_id: None)

    barrier = threading.Barrier(2)
    real_previous_chain_hash = intent_service._previous_chain_hash

    def synchronized_previous_chain_hash(session, organization_id):
        barrier.wait(timeout=30)
        return real_previous_chain_hash(session, organization_id)

    monkeypatch.setattr(intent_service, "_previous_chain_hash", synchronized_previous_chain_hash)

    results: list = []
    errors: list = []

    def worker(decision_id):
        _append_and_commit_in_new_session(SessionLocal, decision_id, agent_id, results, errors)

    t1 = threading.Thread(target=worker, args=(decision_1,))
    t2 = threading.Thread(target=worker, args=(decision_2,))
    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    assert not errors, f"append_evidence raised unexpectedly: {errors}"
    assert len(results) == 2

    records = list(
        db.scalars(
            select(Evidence)
            .where(Evidence.organization_id == org_id)
            .order_by(Evidence.created_at, Evidence.id)
        )
    )
    assert len(records) == 2
    previous_hashes = [r.payload.get("previous_hash") for r in records]
    assert previous_hashes.count(None) == 2, (
        "expected the unfixed code path to fork the chain (both records claiming no "
        f"predecessor) -- got {previous_hashes}. If this assertion fails, either the "
        "monkeypatched bypass above is no longer effective, or intent_service's real "
        "chain-scope logic changed shape enough that this reproduction needs updating."
    )


def test_locking_two_different_organizations_does_not_block_each_other(db, SessionLocal, monkeypatch):
    """Different organizations must never serialize against each other
    -- each locks only its own row. Proven by having thread A hold org
    A's lock for the whole duration of its append_evidence call while
    thread B, for an entirely different org B, is required to finish
    strictly before A releases -- which is only possible if B's call
    was never blocked by A's lock at all."""
    org_a, _, agent_a = _org_principal_agent(db, "Org A", "alice")
    org_b, _, agent_b = _org_principal_agent(db, "Org B", "bob")
    # Captured as plain values in the main thread -- see the earlier
    # test's own comment on why ORM objects must never be touched from
    # a worker thread.
    org_a_id, agent_a_id = org_a.id, agent_a.id
    org_b_id, agent_b_id = org_b.id, agent_b.id
    decision_a = _intent_and_decision(db, agent_a_id)
    decision_b = _intent_and_decision(db, agent_b_id)

    fake_lock = _FakeRowLock()
    real_lock_chain_scope = intent_service._lock_chain_scope
    a_holds_lock = threading.Event()
    b_finished = threading.Event()

    def patched_lock_chain_scope(session, organization_id):
        fake_lock.acquire(organization_id)
        real_lock_chain_scope(session, organization_id)
        if organization_id == org_a_id:
            a_holds_lock.set()
            # Hold org A's lock until B has already finished -- if B's
            # call were (incorrectly) serialized behind A's lock too,
            # this would time out instead of B completing first.
            assert b_finished.wait(timeout=30), "org B's call was blocked by org A's lock"

    monkeypatch.setattr(intent_service, "_lock_chain_scope", patched_lock_chain_scope)

    results: list = []
    errors: list = []

    def worker_a():
        try:
            _append_and_commit_in_new_session(SessionLocal, decision_a, agent_a_id, results, errors)
        finally:
            fake_lock.release(org_a_id)

    def worker_b():
        assert a_holds_lock.wait(timeout=30), "org A never reached its locked section"
        _append_and_commit_in_new_session(SessionLocal, decision_b, agent_b_id, results, errors)
        b_finished.set()

    t_a = threading.Thread(target=worker_a)
    t_b = threading.Thread(target=worker_b)
    t_a.start()
    t_b.start()
    t_a.join(timeout=30)
    t_b.join(timeout=30)

    assert not errors, f"append_evidence raised unexpectedly: {errors}"
    assert len(results) == 2

    records_a = list(db.scalars(select(Evidence).where(Evidence.organization_id == org_a_id)))
    records_b = list(db.scalars(select(Evidence).where(Evidence.organization_id == org_b_id)))
    assert len(records_a) == 1
    assert len(records_b) == 1
