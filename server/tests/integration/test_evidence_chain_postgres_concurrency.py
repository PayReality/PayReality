"""PayReality 1.0 Audit finding G01 (verification-closure pass): the
real-PostgreSQL proof the original G01 milestone's own tests could not
provide. That milestone's test_evidence_chain_concurrency.py proved the
ALGORITHM is correct (given genuine mutual exclusion, the resulting
chain is provably linear) using a hand-rolled Python lock standing in
for the real `SELECT ... FOR UPDATE`, because SQLite cannot exercise
row-level locking at all. This file removes that stand-in entirely and
exercises the real thing: two genuinely separate PostgreSQL
connections, the real `intent_service._lock_chain_scope`
(`.with_for_update()`, unmodified), and direct observation of
`pg_stat_activity.wait_event_type` to prove the second transaction
actually blocks at the database level -- not merely "happens to finish
correctly," which could be true by luck even without a real lock.

Uses the project's own existing docker-compose Postgres service (see
tests/integration/conftest.py's postgres_url fixture) -- skips cleanly,
with the exact command to start it, when Postgres isn't reachable.
"""

import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Decision, Evidence, Intent, Organization, Principal
from app.domain.evidence.signing import payload_hash
from app.services import evidence_service, intent_service

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="


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
def raw_admin_conn(postgres_url):
    """A separate, autocommit raw connection used only to observe
    pg_stat_activity from the outside -- never to touch application
    tables, so it can never itself participate in (or be blocked by)
    the lock under test."""
    dsn = postgres_url.replace("postgresql+psycopg://", "postgresql://")
    conn = psycopg.connect(dsn, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


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


def _backend_pid(session) -> int:
    return session.execute(text("SELECT pg_backend_pid()")).scalar()


def _wait_event_type(raw_conn, pid: int) -> str | None:
    with raw_conn.cursor() as cur:
        cur.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", (pid,))
        row = cur.fetchone()
        return row[0] if row else None


def _poll_for_lock_wait(raw_conn, pid: int, timeout: float = 5.0) -> bool:
    """Polls pg_stat_activity until the given backend pid is observed
    genuinely waiting on a lock, or the timeout elapses. Returns True
    the moment a 'Lock' wait is seen -- this is the actual proof that
    PostgreSQL's row lock, not merely correct eventual output, is what
    serialized the second transaction."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _wait_event_type(raw_conn, pid) == "Lock":
            return True
        time.sleep(0.02)
    return False


def test_second_transaction_genuinely_blocks_on_postgres_row_lock(db, SessionLocal, raw_admin_conn):
    """The core Closure Target A proof: T1 acquires the real per-
    organization row lock and holds it (mid-transaction, uncommitted);
    while it holds the lock, T2's own attempt to acquire the SAME lock
    (for the same organization) is observed, from the outside, to
    genuinely enter PostgreSQL's own 'Lock' wait state -- not merely to
    take some incidental time. Only once that is directly observed is
    T1 allowed to proceed and commit; T2 then unblocks and the resulting
    chain is asserted to be a single linear sequence."""
    org, _, agent = _org_principal_agent(db, "Org A", "alice")
    org_id, agent_id = org.id, agent.id
    decision_1 = _intent_and_decision(db, agent_id)
    decision_2 = _intent_and_decision(db, agent_id)

    lock_acquired = threading.Event()
    release_t1 = threading.Event()
    real_next_seq = intent_service._next_chain_sequence

    def _pausing_next_chain_sequence(session, organization_id):
        # By the time this is reached, _lock_chain_scope's real
        # `SELECT ... FOR UPDATE` has already succeeded for T1 -- this is
        # simply the hold point, deliberately placed after lock
        # acquisition so a second, genuinely concurrent transaction
        # attempting the same lock has something real to block on.
        lock_acquired.set()
        assert release_t1.wait(timeout=30), "test held T1 open longer than expected"
        return real_next_seq(session, organization_id)

    real_lock_chain_scope = intent_service._lock_chain_scope
    t2_pid_holder: dict[str, int] = {}

    def _recording_lock_chain_scope(session, organization_id):
        # Only T2's call needs its pid recorded (T1's pause is what we
        # hold open); capture the backend pid for whichever session is
        # NOT already known to be T1's by checking lock_acquired: T1
        # always reaches this before T2 in this test's own sequencing
        # (T2's thread is only started after lock_acquired is set).
        pid = session.execute(text("SELECT pg_backend_pid()")).scalar()
        t2_pid_holder.setdefault("t2_pid", pid) if lock_acquired.is_set() else t2_pid_holder.setdefault("t1_pid", pid)
        return real_lock_chain_scope(session, organization_id)

    intent_service._next_chain_sequence = _pausing_next_chain_sequence
    intent_service._lock_chain_scope = _recording_lock_chain_scope

    results: list = []
    errors: list = []

    def worker(decision_id):
        session = SessionLocal()
        try:
            evidence = intent_service.append_evidence(
                session, decision_id, agent_id, "vendor_payment", 100.0, [], "ALLOW",
            )
            session.commit()
            results.append(evidence.id)
        except Exception as e:  # pragma: no cover -- surfaced via the assertion below
            errors.append(e)
        finally:
            session.close()

    try:
        t1 = threading.Thread(target=worker, args=(decision_1,))
        t1.start()
        assert lock_acquired.wait(timeout=10), "T1 never reached its held lock section"

        t2 = threading.Thread(target=worker, args=(decision_2,))
        t2.start()

        # The actual proof: observe T2 genuinely blocked on PostgreSQL's
        # own lock manager while T1 still holds the row lock open.
        deadline = time.monotonic() + 5.0
        t2_pid = None
        while time.monotonic() < deadline and t2_pid is None:
            t2_pid = t2_pid_holder.get("t2_pid")
            time.sleep(0.02)
        assert t2_pid is not None, "T2 never reached _lock_chain_scope in time"
        assert _poll_for_lock_wait(raw_admin_conn, t2_pid, timeout=5.0), (
            "T2 was never observed genuinely waiting on PostgreSQL's lock manager -- "
            "the row lock is not providing real mutual exclusion"
        )

        release_t1.set()
        t1.join(timeout=30)
        t2.join(timeout=30)
    finally:
        intent_service._next_chain_sequence = real_next_seq
        intent_service._lock_chain_scope = real_lock_chain_scope

    assert not errors, f"append_evidence raised under real Postgres concurrency: {errors}"
    assert len(results) == 2

    records = list(
        db.scalars(
            select(Evidence).where(Evidence.organization_id == org_id).order_by(Evidence.sequence)
        )
    )
    assert len(records) == 2
    assert [r.sequence for r in records] == [1, 2], "sequence must be unique and monotonic, not duplicated"
    assert records[0].payload.get("previous_hash") is None
    assert records[1].payload["previous_hash"] == payload_hash(records[0].payload), (
        "the two committed records must form one linear chain, never a fork"
    )

    result = evidence_service.verify_chain(db, org_id)
    assert result.broken_links == ()
    assert result.invalid_signatures == ()


def test_different_organizations_never_serialize_against_each_other_on_postgres(db, SessionLocal):
    """The row lock must be scoped per-organization, not global -- an
    org B append must complete while an org A append still holds its
    own lock open, proven the same way the pre-existing SQLite test
    proves it (B must finish strictly before A releases), now against
    a real Postgres row lock rather than a Python-level stand-in."""
    org_a, _, agent_a = _org_principal_agent(db, "Org A", "alice")
    org_b, _, agent_b = _org_principal_agent(db, "Org B", "bob")
    org_a_id, agent_a_id = org_a.id, agent_a.id
    org_b_id, agent_b_id = org_b.id, agent_b.id
    decision_a = _intent_and_decision(db, agent_a_id)
    decision_b = _intent_and_decision(db, agent_b_id)

    a_holds_lock = threading.Event()
    release_a = threading.Event()
    b_finished = threading.Event()
    real_next_seq = intent_service._next_chain_sequence

    def _pausing_next_chain_sequence(session, organization_id):
        if organization_id == org_a_id:
            a_holds_lock.set()
            assert b_finished.wait(timeout=30), "org B's call was blocked by org A's lock"
        return real_next_seq(session, organization_id)

    intent_service._next_chain_sequence = _pausing_next_chain_sequence

    results: list = []
    errors: list = []

    def worker(decision_id, agent_id):
        session = SessionLocal()
        try:
            evidence = intent_service.append_evidence(
                session, decision_id, agent_id, "vendor_payment", 100.0, [], "ALLOW",
            )
            session.commit()
            results.append(evidence.id)
        except Exception as e:  # pragma: no cover
            errors.append(e)
        finally:
            session.close()

    def worker_b():
        assert a_holds_lock.wait(timeout=30), "org A never reached its locked section"
        worker(decision_b, agent_b_id)
        b_finished.set()

    try:
        t_a = threading.Thread(target=worker, args=(decision_a, agent_a_id))
        t_b = threading.Thread(target=worker_b)
        t_a.start()
        t_b.start()
        t_b.join(timeout=30)  # B must finish on its own -- A is still paused, holding its lock
        t_a.join(timeout=30)
    finally:
        intent_service._next_chain_sequence = real_next_seq

    assert not errors, f"append_evidence raised unexpectedly: {errors}"
    assert len(results) == 2
    records_a = list(db.scalars(select(Evidence).where(Evidence.organization_id == org_a_id)))
    records_b = list(db.scalars(select(Evidence).where(Evidence.organization_id == org_b_id)))
    assert len(records_a) == 1
    assert len(records_b) == 1


# --- Legacy (pre-sequence) Evidence transition -------------------------------


def test_new_sequenced_evidence_correctly_attaches_to_the_legacy_null_sequence_tail(db):
    """Migration 741abf7b0146 leaves every historical Evidence row's
    `sequence` NULL, with no backfill. Simulates that real scenario
    directly: two legacy rows inserted with sequence=NULL (as they
    would be before this migration's Evidence ever started assigning
    one), a real chain between them via previous_hash exactly as the
    pre-sequence code always wrote it, then a real, current
    append_evidence call. Must correctly identify the legacy tail as
    its predecessor, and be assigned sequence=1 -- the first REAL
    sequenced write, `MAX(sequence)` over all-NULL legacy rows
    correctly ignoring them rather than colliding or erroring."""
    org, _, agent = _org_principal_agent(db, "Org Legacy", "carol")
    now = datetime.now(timezone.utc)
    legacy_decision_a = _intent_and_decision(db, agent.id)
    legacy_decision_b = _intent_and_decision(db, agent.id)

    legacy_a_payload = {"decision_id": str(legacy_decision_a), "outcome": "ALLOW", "previous_hash": None}
    legacy_a = Evidence(
        id=uuid.uuid4(), organization_id=org.id, decision_id=legacy_decision_a, payload=legacy_a_payload,
        key_id="legacy-key", signature="sig-legacy-a", created_at=now, sequence=None,
    )
    db.add(legacy_a)
    db.flush()

    legacy_b_payload = {
        "decision_id": str(legacy_decision_b), "outcome": "DENY", "previous_hash": payload_hash(legacy_a_payload),
    }
    legacy_b = Evidence(
        id=uuid.uuid4(), organization_id=org.id, decision_id=legacy_decision_b, payload=legacy_b_payload,
        key_id="legacy-key", signature="sig-legacy-b", created_at=now + timedelta(seconds=1), sequence=None,
    )
    db.add(legacy_b)
    db.commit()

    decision_id = _intent_and_decision(db, agent.id)
    new_evidence = intent_service.append_evidence(
        db, decision_id, agent.id, "vendor_payment", 100.0, [], "ALLOW",
    )
    db.commit()

    assert new_evidence.sequence == 1, "the first real sequenced write must get sequence=1, not collide with legacy NULLs"
    assert new_evidence.payload["previous_hash"] == payload_hash(legacy_b_payload), (
        "the new sequenced row must correctly identify the legacy tail (by created_at, its only "
        "ordering signal) as its predecessor"
    )

    result = evidence_service.verify_chain(db, org.id)
    assert result.broken_links == (), "verify_chain must remain deterministic and intact across the legacy/sequenced boundary"


def test_legacy_rows_sharing_an_identical_timestamp_are_a_disclosed_residual_ambiguity(db):
    """Honest characterization, not a claimed fix: two legacy
    (sequence=NULL) rows that happen to share the exact same
    `created_at` (a real possibility under coarse timestamp resolution,
    and the original defect this milestone's G01 fix targeted) have no
    reliable tiebreaker available to verify_chain -- `sequence` only
    protects writes made AFTER this fix, under the real lock; it cannot
    retroactively disambiguate historical rows that were never assigned
    one, and rewriting historical Evidence hashes/signatures is
    explicitly out of scope (locked product semantics: Evidence
    historical immutability).

    This deliberately constructs the adversarial case -- the row that
    is REALLY first is made to have a lexicographically LARGER id than
    the row that is really second -- so verify_chain's ascending
    (sequence, created_at, id) ordering is guaranteed to process them in
    the wrong order. The resulting false "broken chain" report is the
    concrete, disclosed shape of this residual gap, not a hypothetical."""
    org, _, agent = _org_principal_agent(db, "Org Legacy Tie", "dave")
    now = datetime.now(timezone.utc)
    decision_x = _intent_and_decision(db, agent.id)
    decision_y = _intent_and_decision(db, agent.id)

    id_x, id_y = uuid.uuid4(), uuid.uuid4()
    # Force `really_first` to sort AFTER `really_second` in ascending id
    # order, guaranteeing the adversarial interleaving regardless of
    # this run's actual random UUIDs.
    really_first_id, really_second_id = (id_x, id_y) if str(id_x) > str(id_y) else (id_y, id_x)

    really_first_payload = {"decision_id": str(decision_x), "outcome": "ALLOW", "previous_hash": None}
    really_first = Evidence(
        id=really_first_id, organization_id=org.id, decision_id=decision_x, payload=really_first_payload,
        key_id="legacy-key", signature="sig-x", created_at=now, sequence=None,
    )
    really_second_payload = {
        "decision_id": str(decision_y), "outcome": "DENY", "previous_hash": payload_hash(really_first_payload),
    }
    really_second = Evidence(
        id=really_second_id, organization_id=org.id, decision_id=decision_y, payload=really_second_payload,
        key_id="legacy-key", signature="sig-y", created_at=now, sequence=None,  # identical created_at -- the genuine ambiguity
    )
    db.add_all([really_first, really_second])
    db.commit()

    result = evidence_service.verify_chain(db, org.id)
    # The chain is, in reality, perfectly intact -- this assertion
    # documents that an identical-timestamp legacy pair can still
    # produce a FALSE broken-link report purely from id-tiebreak
    # ambiguity, which is the residual gap being disclosed, not fixed
    # (fixing it would require rewriting historical Evidence, which is
    # explicitly out of bounds). Both records end up flagged: processed
    # in the wrong order, record 1 (really_second) is checked against
    # "no predecessor" and fails since it genuinely has one; record 2
    # (really_first) is then checked against record 1's hash and fails
    # since it genuinely has none.
    assert set(result.broken_links) == {really_first.id, really_second.id}, (
        "expected the documented false-positive shape for this adversarial legacy tie; if this "
        "assertion fails, either the ordering logic changed (re-verify this is still a real gap) "
        "or it was fixed some other way (update this test's own claim accordingly)"
    )
