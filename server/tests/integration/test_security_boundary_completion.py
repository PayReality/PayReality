"""Milestone 11 (MILESTONE_11_SECURITY_BOUNDARY_COMPLETION_SUMMARY.md):
adversarial regression tests for the three findings inherited from
Milestone 10's repo-wide sweep --

1. GET /v1/evidence/chain/verify: previously took organization_id as a
   plain, unauthenticated, caller-supplied query parameter (CRITICAL).
2. GET /v1/agents (list): had authentication and organisation-scoping
   but no permission gate.
3. POST /v1/decisions/{id}/resolve: a write path with no
   organisation-ownership check at all.

Same real-infrastructure discipline as every prior milestone's test
suite in this engagement: a real ephemeral OPA server, a real
SQLite-backed database running the actual production models. Tests the
actual authorization path (the service functions routers call), not
just the route, per this codebase's established no-TestClient
convention.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Base, Organization, Principal, User, UserSession
from app.dependencies import require_permission
from app.domain.decision import engine as decision_engine
from app.domain.rbac.permissions import Permission
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import agent_service, evidence_service, intent_service, resolution_service
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


def _policy(principal: str, action: str, condition: Condition, effect: Effect) -> RuntimePolicy:
    return RuntimePolicy(
        id=str(uuid.uuid4()),
        name=f"{action} policy",
        version=1,
        status=PolicyStatus.DRAFT,
        scope=Scope(principal=principal, action=action),
        conditions=ConditionSet(all=(condition,)),
        effect=effect,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )


def _deploy_policy(db, org_id, policy: RuntimePolicy, opa_url) -> uuid.UUID:
    row = svc.create_policy(db, policy, org_id)
    svc.submit_for_review(db, row.policy_key, org_id)
    svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row.policy_key


def _org_with_agent(db, name="Org A"):
    org = Organization(id=uuid.uuid4(), name=name)
    db.add(org)
    db.flush()
    principal = Principal(id=uuid.uuid4(), name=f"alice-{name}", organization_id=org.id)
    db.add(principal)
    db.flush()
    agent = Agent(id=uuid.uuid4(), name=f"agent-{name}", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    return org, principal, agent


@pytest.fixture()
def org_and_agent(db):
    return _org_with_agent(db)


def _submit(db, agent, action, amount):
    import time

    intent = decision = evidence = None
    for _attempt in range(6):
        intent, decision, evidence = intent_service.submit_intent(
            db, agent=agent, action=action, amount=amount, currency="USD", counterparty=None,
            context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        )
        transient = decision.reason == "opa_timeout" or (decision.reason or "").startswith("opa_error:")
        if not transient:
            return intent, decision, evidence
        time.sleep(0.5)
    return intent, decision, evidence


def _user_and_session(db, org_id, role: str):
    user = User(
        id=uuid.uuid4(), organization_id=org_id, email=f"{role}-{uuid.uuid4().hex[:6]}@example.com",
        name=role.title(), password_hash="x", role=role,
    )
    db.add(user)
    db.flush()
    session = UserSession(id=uuid.uuid4(), user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    db.add(session)
    db.flush()
    return user, session


# =========================================================================
# 1. GET /v1/evidence/chain/verify
# =========================================================================


async def test_verify_chain_unauthenticated_returns_401(db):
    checker = require_permission(Permission.EVIDENCE_VIEW)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=None, db=db)
    assert exc.value.status_code == 401


async def test_verify_chain_denied_without_evidence_view(db, org_and_agent):
    """AGENT_ADMIN has AGENT_VIEW/AGENT_* but not EVIDENCE_VIEW
    (domain/rbac/permissions.py) -- must be denied."""
    org, _, _ = org_and_agent
    _, session = _user_and_session(db, org.id, "agent_admin")
    checker = require_permission(Permission.EVIDENCE_VIEW)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)
    assert exc.value.status_code == 403
    assert exc.value.detail == "permission_denied"


async def test_verify_chain_allowed_with_evidence_view(db, org_and_agent):
    org, _, _ = org_and_agent
    _, session = _user_and_session(db, org.id, "auditor")
    checker = require_permission(Permission.EVIDENCE_VIEW)
    await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)


def test_verify_chain_isolates_organizations(db, opa_url):
    """The core of the fix: organization_id is no longer accepted from
    the caller at all (routers/evidence.py's verify_chain now takes it
    only from Depends(get_current_organization)); this proves the
    underlying query itself, given two real organisations' worth of
    real Evidence, never mixes one org's records into the other's
    chain-verification result.

    Does not assert `.intact`: verify_chain's own preceding-record
    seeding query (evidence_service.py's `Evidence.created_at <
    records[0].created_at`) was found, while writing this test, to
    spuriously match a record against itself on this test's SQLite
    engine -- Evidence.created_at is written via the raw SQL
    `server_default=func.now()` (no fractional seconds), while
    SQLAlchemy's own SQLite DateTime type formats a bound Python
    datetime parameter as `%Y-%m-%d %H:%M:%S.000000`, so SQLite's
    string comparison treats the (shorter) stored value as "less than"
    the (longer, zero-padded) bound value for the *same* instant,
    tripping `broken_links` on the very first record of a chain that
    was never broken. Reproduced directly and confirmed real (not this
    test's own mistake) before writing this comment; documented in
    MILESTONE_11_SECURITY_BOUNDARY_COMPLETION_SUMMARY.md as an
    out-of-scope, likely SQLite-only correctness edge case in the
    evidence-chaining subsystem, unrelated to authorization (the only
    pre-existing test exercising verify_chain,
    tests/unit/test_evidence_chain_verification.py, uses a fully fake
    Session and never touches a real database, so nothing had exercised
    this path before). `total` alone is the property this test is
    actually about: organisation isolation."""
    org_a, _, agent_a = _org_with_agent(db, "Org A")
    org_b, _, agent_b = _org_with_agent(db, "Org B")
    _deploy_policy(db, org_a.id, _policy("alice-Org A", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)
    _deploy_policy(db, org_b.id, _policy("alice-Org B", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)

    _submit(db, agent_a, "vendor_payment", 100.0)
    _submit(db, agent_a, "vendor_payment", 200.0)
    _submit(db, agent_b, "vendor_payment", 300.0)

    result_a = evidence_service.verify_chain(db, org_a.id)
    result_b = evidence_service.verify_chain(db, org_b.id)

    assert result_a.total == 2
    assert result_b.total == 1
    assert result_a.invalid_signatures == ()
    assert result_b.invalid_signatures == ()


# =========================================================================
# 2. GET /v1/agents (list)
# =========================================================================


async def test_list_agents_unauthenticated_returns_401(db):
    checker = require_permission(Permission.AGENT_VIEW)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=None, db=db)
    assert exc.value.status_code == 401


async def test_list_agents_denied_without_agent_view(db, org_and_agent):
    """REVIEWER has only AUTHORITY_REVIEW -- must be denied."""
    org, _, _ = org_and_agent
    _, session = _user_and_session(db, org.id, "reviewer")
    checker = require_permission(Permission.AGENT_VIEW)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)
    assert exc.value.status_code == 403


async def test_list_agents_allowed_for_agent_admin(db, org_and_agent):
    org, _, _ = org_and_agent
    _, session = _user_and_session(db, org.id, "agent_admin")
    checker = require_permission(Permission.AGENT_VIEW)
    await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)


def test_list_agents_isolates_organizations(db):
    org_a, principal_a, agent_a = _org_with_agent(db, "Org A")
    org_b, principal_b, agent_b = _org_with_agent(db, "Org B")

    pairs_a, total_a = agent_service.list_agents(db, org_a.id)
    pairs_b, total_b = agent_service.list_agents(db, org_b.id)

    assert total_a == 1 and pairs_a[0][0].id == agent_a.id
    assert total_b == 1 and pairs_b[0][0].id == agent_b.id


# =========================================================================
# 3. POST /v1/decisions/{id}/resolve
# =========================================================================


def _submit_human_review(db, org_id, agent, opa_url):
    _deploy_policy(
        db, org_id,
        _policy(agent.name.replace("agent-", "alice-"), "wire_transfer", Condition(field="amount", operator=Operator.GTE, value=10000), Effect.REQUIRE_HUMAN_REVIEW),
        opa_url,
    )
    _, decision, _ = _submit(db, agent, "wire_transfer", 20000.0)
    assert decision.outcome == "HUMAN_REVIEW"
    return decision


async def test_resolve_decision_unauthenticated_returns_401(db):
    checker = require_permission(Permission.DECISIONS_RESOLVE)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=None, db=db)
    assert exc.value.status_code == 401


async def test_resolve_decision_denied_without_decisions_resolve(db, org_and_agent):
    """REVIEWER has only AUTHORITY_REVIEW, not DECISIONS_RESOLVE -- must
    be denied (a pre-existing, unrelated fact about this role's scope,
    reconfirmed here since it's directly relevant to this endpoint)."""
    org, _, _ = org_and_agent
    _, session = _user_and_session(db, org.id, "reviewer")
    checker = require_permission(Permission.DECISIONS_RESOLVE)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)
    assert exc.value.status_code == 403


def test_resolve_decision_same_org_succeeds(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    decision = _submit_human_review(db, org.id, agent, opa_url)

    resolution_row = resolution_service.resolve_decision(
        db, decision_id=decision.id, organization_id=org.id,
        resolution="approved", resolved_by="test-reviewer",
    )
    assert resolution_row.resolution == "approved"
    assert resolution_row.decision_id == decision.id


def test_resolve_decision_cross_org_fails(db, opa_url):
    org_a, _, agent_a = _org_with_agent(db, "Org A")
    org_b, _, _ = _org_with_agent(db, "Org B")
    decision = _submit_human_review(db, org_a.id, agent_a, opa_url)

    with pytest.raises(resolution_service.DecisionNotFoundError):
        resolution_service.resolve_decision(
            db, decision_id=decision.id, organization_id=org_b.id,
            resolution="approved", resolved_by="attacker",
        )

    # Org A can still resolve its own decision -- isolation doesn't
    # break the legitimate case.
    resolution_row = resolution_service.resolve_decision(
        db, decision_id=decision.id, organization_id=org_a.id,
        resolution="approved", resolved_by="test-reviewer",
    )
    assert resolution_row.resolution == "approved"


def test_resolve_decision_already_resolved_behavior_unchanged(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    decision = _submit_human_review(db, org.id, agent, opa_url)

    resolution_service.resolve_decision(
        db, decision_id=decision.id, organization_id=org.id,
        resolution="approved", resolved_by="first-reviewer",
    )
    with pytest.raises(resolution_service.DecisionAlreadyResolvedError):
        resolution_service.resolve_decision(
            db, decision_id=decision.id, organization_id=org.id,
            resolution="denied", resolved_by="second-reviewer",
        )


def test_resolve_decision_nonexistent_decision_raises_not_found(db, org_and_agent):
    org, _, _ = org_and_agent
    with pytest.raises(resolution_service.DecisionNotFoundError):
        resolution_service.resolve_decision(
            db, decision_id=uuid.uuid4(), organization_id=org.id,
            resolution="approved", resolved_by="test-reviewer",
        )
