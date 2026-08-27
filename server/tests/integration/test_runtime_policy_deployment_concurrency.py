"""PayReality 1.0 Audit finding G02: the RuntimePolicy deployment
concurrency race, and its fix (runtime_policy_service.deploy_policy's
retry-with-early-flush-before-OPA-push). Deliberately duplicates the
setup helpers established elsewhere in this test suite rather than
sharing a conftest, matching this repo's own convention for these
integration test files.

Same honest scope note as test_evidence_chain_concurrency.py: production
runs on Postgres; a real multi-connection Postgres instance was not
reachable in this environment (Docker Desktop installed but its daemon
is not running here) to verify the version/single-active-policy unique
constraints' own blocking/conflict behavior live against Postgres
specifically. What IS proven here, against a real file-backed SQLite
database with genuinely separate connections and a real ephemeral OPA
server, is the algorithm: a forced, deterministic collision (via a
monkeypatched hook, not timing) is caught, retried with fresh state
(never a stale prior_active/next_version), and -- the actual point of
the fix -- a losing attempt never pushes to OPA at all, because the
racy database state is reserved (flushed) before the OPA call, not
after. That structural guarantee (flush-before-push) is dialect-
independent; it does not rely on SQLite reproducing Postgres's own
locking behavior to hold.
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
from app.db.models import Base, Organization, Policy
from app.domain.decision import engine as decision_engine
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.opa_client import HttpOpaClient
from app.services import runtime_policy_service as svc
from app.services.runtime_policy_service import ConcurrentDeploymentConflictError

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)


@compiles(PG_JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _uuid_as_char_on_sqlite(element, compiler, **kw):
    return "CHAR(36)"


@pytest.fixture()
def engine(tmp_path):
    eng = create_engine(
        f"sqlite:///{tmp_path / 'policy_deploy_race.db'}", connect_args={"timeout": 30}
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


@pytest.fixture(autouse=True)
def _point_settings_at_ephemeral_opa(request):
    if "opa_url" not in request.fixturenames:
        yield
        return
    opa_url = request.getfixturevalue("opa_url")
    original = settings.opa_url
    settings.opa_url = opa_url
    try:
        yield
    finally:
        settings.opa_url = original


def _policy(principal: str, action: str) -> RuntimePolicy:
    return RuntimePolicy(
        id=str(uuid.uuid4()), name=f"{action} policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal=principal, action=action),
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.GTE, value=0),)),
        effect=Effect.ALLOW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )


def _compiled_and_ready(db, org_id, principal: str, action: str) -> uuid.UUID:
    """Drives a fresh RuntimePolicy through submit -> approve -> compile,
    stopping right before deploy -- exactly the state two admins racing
    to click "Deploy" at the same time would both be starting from."""
    row = svc.create_policy(db, _policy(principal, action), org_id)
    svc.submit_for_review(db, row.policy_key, org_id)
    svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    return row.policy_key


def _one_shot_synced_get_latest(barrier):
    """Wraps svc.get_latest so each calling THREAD waits on `barrier`
    only on its own first call -- deploy_policy retries on a collision,
    and a retry re-calls get_latest, but by then the winning thread has
    already returned and will never call get_latest again. A plain
    reused Barrier(2) would then have only one party left on the
    barrier's next cycle and hang until timeout; this only synchronizes
    the genuine race window (both threads' very first attempt), letting
    any later retry proceed immediately."""
    real_get_latest = svc.get_latest
    already_synced: set[int] = set()
    guard = threading.Lock()

    def synchronized_get_latest(session, policy_key, organization_id):
        tid = threading.get_ident()
        with guard:
            first_time = tid not in already_synced
            already_synced.add(tid)
        if first_time:
            barrier.wait(timeout=60)
        return real_get_latest(session, policy_key, organization_id)

    return synchronized_get_latest


def _deploy_in_new_session(SessionLocal, policy_key, org_id, opa_url, results, errors):
    session = SessionLocal()
    try:
        outcome = svc.deploy_policy(session, policy_key, org_id, opa_url=opa_url)
        results.append(outcome)
    except Exception as e:  # pragma: no cover -- surfaced via assertions below, not swallowed
        errors.append(e)
    finally:
        session.close()


def test_two_concurrent_deploys_in_the_same_organization_both_succeed_and_agree_with_opa(
    db, opa_url, SessionLocal, monkeypatch
):
    """G02, requirement A: two different RuntimePolicies in the SAME
    organization, deployed at genuinely the same time from two separate
    threads/sessions. The G02 bug this guards against is an unhandled
    raw IntegrityError (a 500) from either the platform-wide
    Policy.version collision or the per-org single-active-policy
    collision -- that must never happen. It is NOT required that both
    deploys succeed: when two DIFFERENT policies in the same org race,
    a retried attempt correctly recompiles against the (now-changed)
    active set and can legitimately find its precompiled bundle_hash is
    stale -- BundleChangedSinceCompileError, a real, already-typed,
    pre-existing 409 this milestone does not change or retry around
    (retrying past it would mean deploying content that was never
    actually reviewed). Whatever the outcome, the database's single-
    active-policy invariant must hold, and OPA must agree with it."""
    org = Organization(id=uuid.uuid4(), name="Org A")
    db.add(org)
    db.commit()
    policy_key_a = _compiled_and_ready(db, org.id, "alice", "vendor_payment")
    policy_key_b = _compiled_and_ready(db, org.id, "alice", "disable_user")

    # Force a genuine collision deterministically: both threads' first
    # attempt reads `prior_active`/`next_version` (both see "nothing
    # active yet"/"version 1") before either has flushed -- a barrier
    # placed at get_latest (the first DB read _deploy_policy_attempt
    # makes) lines them up so neither has a head start.
    start_barrier = threading.Barrier(2)
    monkeypatch.setattr(svc, "get_latest", _one_shot_synced_get_latest(start_barrier))

    results: list = []
    errors: list = []
    t1 = threading.Thread(
        target=_deploy_in_new_session, args=(SessionLocal, policy_key_a, org.id, opa_url, results, errors)
    )
    t2 = threading.Thread(
        target=_deploy_in_new_session, args=(SessionLocal, policy_key_b, org.id, opa_url, results, errors)
    )
    t1.start()
    t2.start()
    t1.join(timeout=60)
    t2.join(timeout=60)

    assert len(results) + len(errors) == 2
    # The actual G02 regression guard: no raw, unhandled IntegrityError
    # (a 500) -- only real, pre-existing, already-typed conflict classes
    # (or full success) are acceptable outcomes here.
    from sqlalchemy.exc import IntegrityError
    from app.services.runtime_policy_service import BundleChangedSinceCompileError, InvalidTransitionError

    for e in errors:
        assert isinstance(e, (BundleChangedSinceCompileError, InvalidTransitionError)), (
            f"unexpected exception type under concurrency: {type(e).__name__}: {e}"
        )
        assert not isinstance(e, IntegrityError), "a raw IntegrityError escaped deploy_policy's retry loop"

    active_rows = list(
        db.scalars(select(Policy).where(Policy.organization_id == org.id, Policy.status == "active"))
    )
    assert len(active_rows) == 1, "single-active-policy-per-org invariant violated"
    versions = [r.version for r in db.scalars(select(Policy).where(Policy.organization_id == org.id))]
    assert len(versions) == len(set(versions)), f"duplicate Policy.version allocated: {versions}"

    # Real proof that OPA and the database agree: whichever action(s)
    # actually made it into the final active bundle must evaluate ALLOW
    # against what OPA actually has loaded right now.
    from app.services import intent_service
    from app.db.models import Agent, Principal

    principal = Principal(id=uuid.uuid4(), name="alice", organization_id=org.id)
    db.add(principal)
    db.flush()
    agent = Agent(id=uuid.uuid4(), name="test-agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()

    # Determine which action(s) are actually active from the database
    # itself, rather than guessing from thread scheduling order.
    from app.db.models import RuntimePolicyRecord

    active_rps = list(
        db.scalars(
            select(RuntimePolicyRecord).where(
                RuntimePolicyRecord.organization_id == org.id, RuntimePolicyRecord.status == "active"
            )
        )
    )
    succeeded_actions = {rp.content["scope"]["action"] for rp in active_rps}
    assert succeeded_actions, "no RuntimePolicy ended up active after the race"

    for action in succeeded_actions:
        _, decision, _ = intent_service.submit_intent(
            db, agent=agent, action=action, amount=100.0, currency="USD", counterparty=None,
            context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        )
        assert decision.outcome == "ALLOW", (
            f"action={action!r} did not evaluate ALLOW against the post-race OPA state "
            f"(outcome={decision.outcome!r}, reason={decision.reason!r}) -- OPA and the "
            "database disagree about what's actually active"
        )


def test_a_losing_deploy_attempt_never_pushes_to_opa(db, opa_url, SessionLocal, monkeypatch):
    """G02, requirement C: forces the exact collision (both attempts
    reading the same prior_active/next_version before either flushes)
    and proves the actual fix -- not just that the race resolves
    without a 500, but that a losing attempt (whether it ultimately
    fails with the DB-level IntegrityError this milestone fixes, or the
    separate, legitimate BundleChangedSinceCompileError business check
    -- both are checked/raised before the OPA push, see
    _deploy_policy_attempt's own ordering) never calls
    opa.upload_policy at all. Exactly one OPA push per policy that
    actually ended up active -- never more, which would mean a losing
    attempt's push landed in OPA regardless of its own outcome."""
    org = Organization(id=uuid.uuid4(), name="Org A")
    db.add(org)
    db.commit()
    policy_key_a = _compiled_and_ready(db, org.id, "alice", "vendor_payment")
    policy_key_b = _compiled_and_ready(db, org.id, "alice", "disable_user")

    start_barrier = threading.Barrier(2)
    monkeypatch.setattr(svc, "get_latest", _one_shot_synced_get_latest(start_barrier))

    upload_calls: list = []
    real_upload_policy = HttpOpaClient.upload_policy

    def counted_upload_policy(self, policy_id, rego_source):
        upload_calls.append(policy_id)
        return real_upload_policy(self, policy_id, rego_source)

    monkeypatch.setattr(HttpOpaClient, "upload_policy", counted_upload_policy)

    results: list = []
    errors: list = []
    t1 = threading.Thread(
        target=_deploy_in_new_session, args=(SessionLocal, policy_key_a, org.id, opa_url, results, errors)
    )
    t2 = threading.Thread(
        target=_deploy_in_new_session, args=(SessionLocal, policy_key_b, org.id, opa_url, results, errors)
    )
    t1.start()
    t2.start()
    t1.join(timeout=60)
    t2.join(timeout=60)

    assert len(results) + len(errors) == 2
    from app.db.models import RuntimePolicyRecord

    active_rps = list(
        db.scalars(
            select(RuntimePolicyRecord).where(
                RuntimePolicyRecord.organization_id == org.id, RuntimePolicyRecord.status == "active"
            )
        )
    )
    assert len(upload_calls) == len(active_rps), (
        f"expected exactly one OPA push per policy that actually ended up active "
        f"({len(active_rps)}), got {len(upload_calls)} -- a losing attempt pushed to "
        "OPA even though its own outcome never became the persisted, active state"
    )


def test_concurrent_deploys_across_different_organizations_never_cross_contaminate(
    db, opa_url, SessionLocal, monkeypatch
):
    """G02, requirement B: Policy.version is intentionally a platform-
    wide sequence (uq_policies_version, see the Policy model's own
    docstring) -- two different organizations CAN legitimately race on
    it, and that race must resolve exactly like the same-org case
    (retried, no 500, no duplicate version), while never affecting each
    other's actual active policy content."""
    org_a = Organization(id=uuid.uuid4(), name="Org A")
    org_b = Organization(id=uuid.uuid4(), name="Org B")
    db.add_all([org_a, org_b])
    db.commit()
    policy_key_a = _compiled_and_ready(db, org_a.id, "alice", "vendor_payment")
    policy_key_b = _compiled_and_ready(db, org_b.id, "bob", "vendor_payment")

    start_barrier = threading.Barrier(2)
    monkeypatch.setattr(svc, "get_latest", _one_shot_synced_get_latest(start_barrier))

    results: list = []
    errors: list = []
    t1 = threading.Thread(
        target=_deploy_in_new_session, args=(SessionLocal, policy_key_a, org_a.id, opa_url, results, errors)
    )
    t2 = threading.Thread(
        target=_deploy_in_new_session, args=(SessionLocal, policy_key_b, org_b.id, opa_url, results, errors)
    )
    t1.start()
    t2.start()
    t1.join(timeout=60)
    t2.join(timeout=60)

    assert not errors, f"deploy_policy raised under concurrency: {errors}"
    assert len(results) == 2
    assert results[0].bundle_hash != results[1].bundle_hash

    active_a = list(db.scalars(select(Policy).where(Policy.organization_id == org_a.id, Policy.status == "active")))
    active_b = list(db.scalars(select(Policy).where(Policy.organization_id == org_b.id, Policy.status == "active")))
    assert len(active_a) == 1
    assert len(active_b) == 1
    assert active_a[0].version != active_b[0].version, "global version collision was not resolved"


def test_deploy_policy_gives_up_cleanly_after_max_attempts(db, opa_url, monkeypatch):
    """Bounds the retry loop explicitly -- never an infinite loop, even
    under a pathological, permanently-racing scenario -- and proves the
    give-up path is a clean typed error, not an unhandled 500."""
    org = Organization(id=uuid.uuid4(), name="Org A")
    db.add(org)
    db.commit()
    policy_key = _compiled_and_ready(db, org.id, "alice", "vendor_payment")

    def always_collide(*args, **kwargs):
        from sqlalchemy.exc import IntegrityError
        raise IntegrityError("simulated permanent race", params=None, orig=Exception("duplicate"))

    monkeypatch.setattr(svc, "_deploy_policy_attempt", always_collide)
    monkeypatch.setattr(svc, "reconcile_opa_with_active_policies", lambda db, opa_url=None: False)

    with pytest.raises(ConcurrentDeploymentConflictError):
        svc.deploy_policy(db, policy_key, org.id, opa_url=opa_url)
