"""Trusted Integration Architecture, Phase 1: real-PostgreSQL proof
that concurrent IntegrationContractVersion creation for the same
(integration_id, source_operation) is safe -- no raw IntegrityError
ever escapes to the caller, version assignment is deterministic (no
duplicates, no gaps, no lost rows), and different tuples never
unnecessarily serialize against each other.

Uses the project's own existing docker-compose Postgres service via
the `postgres_url` fixture (tests/integration/conftest.py, established
during the P0 verification-closure milestone) -- skips cleanly with
the exact start command if Postgres isn't reachable. Real, separate
psycopg connections/sessions per thread, a `threading.Barrier` to force
genuinely simultaneous first attempts (this repo's own established
"force the exact interleaving deterministically, never rely on timing"
convention), not SQLite: the version-allocation race depends on a real
UNIQUE constraint violation under real concurrent transactions, which
SQLite's own whole-database write lock would mask rather than exercise.
"""

import threading
import time
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Organization, IntegrationContractVersion
from app.services import integration_contract_service as svc
from app.services.integration_contract_service import ConcurrentVersionConflictError


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
    org = Organization(id=uuid.uuid4(), name="Org Integration Contract Concurrency")
    db.add(org)
    db.commit()
    return org


def _create_version_in_new_session(SessionLocal, integration_id, org_id, source_operation, results, errors):
    session = SessionLocal()
    try:
        row = svc.create_contract_version(session, integration_id, org_id, source_operation, "vendor_payment")
        results.append((row.version, row.id))
    except Exception as e:  # pragma: no cover -- surfaced via the assertion below, never swallowed
        errors.append(e)
    finally:
        session.close()


def test_two_concurrent_version_creations_for_the_same_operation_both_succeed_with_distinct_versions(
    db, SessionLocal, org,
):
    integration = svc.create_integration(db, org.id, "SAP S/4HANA (reference)")
    integration_id = integration.id

    barrier = threading.Barrier(2)
    real_attempt = svc._create_contract_version_attempt

    def synchronized_attempt(*args, **kwargs):
        # Both threads' very first attempt arrives at genuinely the same
        # instant; a retry (a second call from the same thread after a
        # collision) proceeds immediately -- mirrors this repo's own
        # one-shot-per-thread barrier convention (see
        # test_runtime_policy_deployment_concurrency.py) since a plain
        # reused Barrier(2) would hang a retrying thread with no second
        # party left to meet it.
        tid = threading.get_ident()
        if tid not in synchronized_attempt._synced:
            synchronized_attempt._synced.add(tid)
            barrier.wait(timeout=30)
        return real_attempt(*args, **kwargs)

    synchronized_attempt._synced = set()
    svc._create_contract_version_attempt = synchronized_attempt

    results: list = []
    errors: list = []
    try:
        t1 = threading.Thread(
            target=_create_version_in_new_session,
            args=(SessionLocal, integration_id, org.id, "ChangeSupplierBankDetails", results, errors),
        )
        t2 = threading.Thread(
            target=_create_version_in_new_session,
            args=(SessionLocal, integration_id, org.id, "ChangeSupplierBankDetails", results, errors),
        )
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)
    finally:
        svc._create_contract_version_attempt = real_attempt

    assert not errors, f"create_contract_version raised under concurrency: {errors}"
    assert len(results) == 2
    versions = sorted(v for v, _id in results)
    assert versions == [1, 2], "expected exactly one version 1 and one version 2, no duplicate, no gap"


def test_concurrent_creation_across_four_racers_produces_no_duplicate_or_lost_version(db, SessionLocal, org):
    """Four genuinely simultaneous racers exceeds MAX_VERSION_CREATE_
    ATTEMPTS' own bounded budget (3, matching deploy_policy's own
    established precedent) closely enough that a losing racer can
    legitimately exhaust its retries -- exactly the same class of
    outcome test_deploy_policy_gives_up_cleanly_after_max_attempts
    already established as correct, not a bug, for the identical
    bounded-retry pattern. What must hold regardless: no raw
    IntegrityError/500 ever escapes (only the typed
    ConcurrentVersionConflictError is an acceptable failure), every
    successful result gets a genuinely unique version, and the
    database's own committed rows agree with the successful results --
    never a duplicate, never a silently lost row."""
    integration = svc.create_integration(db, org.id, "SAP S/4HANA (reference)")
    integration_id = integration.id

    barrier = threading.Barrier(4)
    real_attempt = svc._create_contract_version_attempt

    def synchronized_attempt(*args, **kwargs):
        tid = threading.get_ident()
        if tid not in synchronized_attempt._synced:
            synchronized_attempt._synced.add(tid)
            barrier.wait(timeout=30)
        return real_attempt(*args, **kwargs)

    synchronized_attempt._synced = set()
    svc._create_contract_version_attempt = synchronized_attempt

    results: list = []
    errors: list = []
    try:
        threads = [
            threading.Thread(
                target=_create_version_in_new_session,
                args=(SessionLocal, integration_id, org.id, "ChangeSupplierBankDetails", results, errors),
            )
            for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
    finally:
        svc._create_contract_version_attempt = real_attempt

    assert len(results) + len(errors) == 4
    for e in errors:
        assert isinstance(e, ConcurrentVersionConflictError), (
            f"only the typed give-up error is an acceptable failure under extreme contention, got: {e!r}"
        )

    versions = sorted(v for v, _id in results)
    assert len(versions) == len(set(versions)), f"no version may be assigned twice, got {versions}"
    assert versions == list(range(1, len(versions) + 1)), f"no gap may exist among successful versions, got {versions}"

    # Cross-checked directly against the database, not just the in-memory
    # results list -- no successful row was lost even if it raced past
    # its own thread's local bookkeeping.
    db_rows = list(
        db.scalars(
            select(IntegrationContractVersion).where(IntegrationContractVersion.integration_id == integration_id)
        )
    )
    assert sorted(r.version for r in db_rows) == versions


def test_concurrent_creation_across_different_operations_does_not_serialize(db, SessionLocal, org):
    """No explicit lock exists anywhere in create_contract_version --
    only a UNIQUE(integration_id, source_operation, version) constraint
    and a bounded retry on collision. Different tuples should never
    contend for the same constraint at all, so N genuinely different
    operations racing concurrently should all land on version=1 on
    their very first attempt, with no retry ever needed."""
    integration = svc.create_integration(db, org.id, "SAP S/4HANA (reference)")
    integration_id = integration.id

    operations = [f"Operation{i}" for i in range(4)]
    barrier = threading.Barrier(len(operations))
    real_attempt = svc._create_contract_version_attempt
    attempt_counts: dict[str, int] = {op: 0 for op in operations}
    lock = threading.Lock()

    def counting_attempt(db_session, integration_id_arg, organization_id, source_operation, *rest, **kwargs):
        with lock:
            attempt_counts[source_operation] += 1
        return real_attempt(db_session, integration_id_arg, organization_id, source_operation, *rest, **kwargs)

    def synchronized_attempt(*args, **kwargs):
        tid = threading.get_ident()
        if tid not in synchronized_attempt._synced:
            synchronized_attempt._synced.add(tid)
            barrier.wait(timeout=30)
        return counting_attempt(*args, **kwargs)

    synchronized_attempt._synced = set()
    svc._create_contract_version_attempt = synchronized_attempt

    results: list = []
    errors: list = []
    try:
        start = time.monotonic()
        threads = [
            threading.Thread(
                target=_create_version_in_new_session,
                args=(SessionLocal, integration_id, org.id, op, results, errors),
            )
            for op in operations
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        elapsed = time.monotonic() - start
    finally:
        svc._create_contract_version_attempt = real_attempt

    assert not errors, f"create_contract_version raised unexpectedly: {errors}"
    assert len(results) == len(operations)
    assert all(v == 1 for v, _id in results), "each distinct operation should land on version 1 on its first try"
    assert all(count == 1 for count in attempt_counts.values()), (
        f"a retry means two different operations contended for the same slot, which should never happen: {attempt_counts}"
    )
    assert elapsed < 10, f"unexpectedly slow ({elapsed:.2f}s) -- possible unwanted cross-tuple serialization"
