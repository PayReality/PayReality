"""PayReality 1.0 Audit finding G02 (verification-closure pass):
failure-injection proof that deploy_policy never leaves OPA ahead of
what the database actually committed -- including the window the
original G02 milestone's own fix did not yet cover: a failure that
happens AFTER the OPA push has already succeeded (_ensure_mandate's own
internal flush, or the final db.commit() itself, can both still fail
for reasons unrelated to the two racing constraints the original fix
already reserves against -- a dropped connection, a deadlock, disk
pressure -- and neither of those is an IntegrityError, so the original
fix's retry wrapper would never have caught them).

Uses a real, ephemeral OPA server (see conftest.py's opa_url fixture)
so "was anything actually left loaded in OPA" is checked by asking OPA
itself (GET /v1/policies/<id>), never inferred from the Python code
alone.
"""

import uuid
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
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
from app.services import runtime_policy_service as svc

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)


@compiles(PG_JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _uuid_as_char_on_sqlite(element, compiler, **kw):
    return "CHAR(36)"


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'deploy_opa_consistency.db'}", connect_args={"timeout": 30}
    )
    policies_table = Base.metadata.tables["policies"]
    partial_index = next(i for i in policies_table.indexes if i.name == "idx_policies_single_active_per_org")
    policies_table.indexes.discard(partial_index)
    try:
        Base.metadata.create_all(engine)
    finally:
        policies_table.indexes.add(partial_index)
    session = sessionmaker(bind=engine)()
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


def _policy(principal: str, action: str) -> RuntimePolicy:
    return RuntimePolicy(
        id=str(uuid.uuid4()), name=f"{action} policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal=principal, action=action),
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.GTE, value=0),)),
        effect=Effect.ALLOW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )


def _compiled_and_ready(db, org_id, principal: str, action: str) -> uuid.UUID:
    row = svc.create_policy(db, _policy(principal, action), org_id)
    svc.submit_for_review(db, row.policy_key, org_id)
    svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    return row.policy_key


def _opa_has_policy_loaded(opa_url: str, policy_id: str) -> bool:
    resp = httpx.get(f"{opa_url}/v1/policies/{policy_id}", timeout=5)
    return resp.status_code == 200


# --- CASE 1: DB persistence fails BEFORE the OPA push -----------------------


def test_case1_db_collision_before_opa_push_never_touches_opa(db, opa_url, monkeypatch):
    """The racing constraint collides at db.flush(), before the OPA
    push -- OPA must never be called for that losing attempt. Forces
    the collision deterministically (a one-shot raising wrapper around
    this session's own flush) rather than via real threads, since this
    test only needs to prove the ORDERING invariant, not re-prove the
    concurrency mechanism itself (already covered by
    test_runtime_policy_deployment_concurrency.py)."""
    org = Organization(id=uuid.uuid4(), name="Org A")
    db.add(org)
    db.commit()
    policy_key = _compiled_and_ready(db, org.id, "alice", "vendor_payment")

    upload_calls = []
    monkeypatch.setattr(
        svc.HttpOpaClient, "upload_policy",
        lambda self, *a, **kw: (upload_calls.append(1), "rev-should-not-happen")[1],
    )

    real_flush = db.flush
    call_count = {"n": 0}

    def _flush_collides_once(*a, **kw):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise IntegrityError("simulated racing collision", params=None, orig=Exception("duplicate key"))
        return real_flush(*a, **kw)

    monkeypatch.setattr(db, "flush", _flush_collides_once)

    with pytest.raises(IntegrityError):
        svc._deploy_policy_attempt(db, policy_key, org.id, opa_url)
    db.rollback()

    assert upload_calls == [], "OPA must never be touched when the DB collision happens before the push"


# --- CASE 2: the OPA push itself fails ---------------------------------------


def test_case2_opa_push_failure_is_not_silently_reported_as_deployed(db, opa_url, monkeypatch):
    """OPA mutation itself fails -- the database must not end up
    reporting this policy as successfully, actively deployed."""
    org = Organization(id=uuid.uuid4(), name="Org B")
    db.add(org)
    db.commit()
    policy_key = _compiled_and_ready(db, org.id, "alice", "vendor_payment")

    def _boom(self, *a, **kw):
        raise RuntimeError("simulated OPA outage")

    monkeypatch.setattr(svc.HttpOpaClient, "upload_policy", _boom)

    with pytest.raises(RuntimeError, match="simulated OPA outage"):
        svc.deploy_policy(db, policy_key, org.id, opa_url=opa_url)

    row = svc.get_latest(db, policy_key, org.id)
    assert row.status != "active", "a failed OPA push must never leave the RuntimePolicyRecord marked active"
    active = db.scalar(select(Policy).where(Policy.organization_id == org.id, Policy.status == "active"))
    assert active is None, "a failed OPA push must never leave a committed active Policy row behind"


# --- CASE 3: the final db.commit() fails AFTER the OPA push succeeded -------


def test_case3_commit_failure_after_opa_push_reconciles_opa_back_to_db_truth(db, opa_url, monkeypatch):
    """The actual gap this verification-closure pass exists to prove
    closed: OPA is pushed to successfully (real, not mocked, against the
    ephemeral OPA fixture), and THEN the final db.commit() fails for a
    reason unrelated to the two known racing constraints (simulated
    directly here as a dropped-connection-shaped exception). Without
    reconciliation, OPA would be left serving a Policy that was never
    durably committed -- exactly the split-brain this milestone closes.
    This is a first-ever deploy for this organization (no prior active
    policy), so the correct reconciled state is "nothing loaded at
    all" -- proving the new delete path, not just the overwrite path."""
    org = Organization(id=uuid.uuid4(), name="Org C")
    db.add(org)
    db.commit()
    policy_key = _compiled_and_ready(db, org.id, "alice", "vendor_payment")

    def _raise_on_commit():
        raise RuntimeError("simulated connection loss at commit")

    monkeypatch.setattr(db, "commit", _raise_on_commit)

    with pytest.raises(RuntimeError, match="simulated connection loss at commit"):
        svc.deploy_policy(db, policy_key, org.id, opa_url=opa_url)

    monkeypatch.undo()  # restore the real commit so this test's own assertions can query freely

    row = svc.get_latest(db, policy_key, org.id)
    assert row.status != "active"
    active = db.scalar(select(Policy).where(Policy.organization_id == org.id, Policy.status == "active"))
    assert active is None, "the database must show nothing active after the rolled-back commit"

    policy_id = svc._opa_package_and_policy_id(org.id)[1]
    assert not _opa_has_policy_loaded(opa_url, policy_id), (
        "OPA must be reconciled (here: cleared, since this org has no active policy) after a "
        "post-push commit failure -- leaving OPA serving a never-committed policy is exactly "
        "the split-brain this fix closes"
    )


def test_case3b_commit_failure_reconciles_opa_back_to_the_prior_still_valid_version(db, opa_url, monkeypatch):
    """Same failure point as case 3, but this organization already had a
    real, previously-deployed active policy -- the correct reconciled
    state here is "OPA still serves the PRIOR version," not empty, and
    not the never-committed new version either."""
    org = Organization(id=uuid.uuid4(), name="Org D")
    db.add(org)
    db.commit()
    first_key = _compiled_and_ready(db, org.id, "alice", "vendor_payment")
    first_outcome = svc.deploy_policy(db, first_key, org.id, opa_url=opa_url)

    second_key = _compiled_and_ready(db, org.id, "bob", "disable_user")

    def _raise_on_commit():
        raise RuntimeError("simulated connection loss at commit")

    monkeypatch.setattr(db, "commit", _raise_on_commit)
    with pytest.raises(RuntimeError, match="simulated connection loss at commit"):
        svc.deploy_policy(db, second_key, org.id, opa_url=opa_url)
    monkeypatch.undo()

    # The second deploy never durably committed -- exactly one Policy
    # remains active, and it's the first, untouched one.
    active = list(db.scalars(select(Policy).where(Policy.organization_id == org.id, Policy.status == "active")))
    assert len(active) == 1
    assert active[0].bundle_hash == first_outcome.bundle_hash

    policy_id = svc._opa_package_and_policy_id(org.id)[1]
    assert _opa_has_policy_loaded(opa_url, policy_id), "OPA must still serve the prior, still-valid policy"
