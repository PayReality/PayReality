"""Authority Freshness (PAYREALITY_FUTURE_VISION.md Part B): real-
infrastructure tests, matching test_decision_security_boundary.py's own
discipline. REVIEW DUE (next_review_at) and AUTHORITY EXPIRED
(authority_expires_at) are deliberately different concepts, tested
separately below -- see runtime_policy_lifecycle_service.attest_policy's
own docstring for why they must never be conflated.
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
from app.domain.runtime_policy.constraints import Constraints, RiskLevel
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import intent_service, runtime_policy_lifecycle_service as lsvc
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


def _policy(principal, action, condition, effect, risk_level=None):
    return RuntimePolicy(
        id=str(uuid.uuid4()), name=f"{action} policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal=principal, action=action), conditions=ConditionSet(all=(condition,)),
        effect=effect, audit=AuditTrail(created=datetime.now(timezone.utc)),
        constraints=Constraints(risk_level=RiskLevel(risk_level) if risk_level else None),
    )


def _deploy_policy(db, org_id, policy, opa_url):
    row = svc.create_policy(db, policy, org_id)
    svc.submit_for_review(db, row.policy_key, org_id)
    svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row.policy_key


@pytest.fixture()
def org_and_agent(db):
    org = Organization(id=uuid.uuid4(), name="Org A")
    db.add(org)
    db.flush()
    principal = Principal(id=uuid.uuid4(), name="alice", organization_id=org.id)
    db.add(principal)
    db.flush()
    agent = Agent(id=uuid.uuid4(), name="test-agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    return org, principal, agent


def _submit(db, agent, action, amount):
    intent, decision, evidence = intent_service.submit_intent(
        db, agent=agent, action=action, amount=amount, currency="USD", counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
    )
    return intent, decision, evidence


def _user_and_session(db, org_id, role):
    user = User(id=uuid.uuid4(), organization_id=org_id, email=f"{role}@example.com", name=role.title(), password_hash="x", role=role)
    db.add(user)
    db.flush()
    session = UserSession(id=uuid.uuid4(), user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    db.add(session)
    db.flush()
    return user, session


# --- Attestation itself -----------------------------------------------------


def test_attestation_updates_timestamps(db, org_and_agent, opa_url):
    org, _, _ = org_and_agent
    policy_key = _deploy_policy(
        db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url,
    )
    row = lsvc.attest_policy(db, policy_key, org.id, actor="governance-admin", review_cadence_days=30)
    assert row.last_attested_at is not None
    assert row.next_review_at is not None
    assert (row.next_review_at - row.last_attested_at) == timedelta(days=30)


def test_next_review_uses_default_cadence_when_unspecified(db, org_and_agent, opa_url):
    org, _, _ = org_and_agent
    policy_key = _deploy_policy(
        db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url,
    )
    row = lsvc.attest_policy(db, policy_key, org.id, actor="governance-admin")
    assert (row.next_review_at - row.last_attested_at) == timedelta(days=lsvc._DEFAULT_REVIEW_CADENCE_DAYS)


def test_review_due_and_authority_expired_are_independent(db, org_and_agent, opa_url):
    """A policy overdue for re-attestation, with no authority_expires_at
    set at all, must still ALLOW normally -- review-due is a visibility
    reminder, never an enforcement mechanism on its own."""
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW, risk_level="critical"),
        opa_url,
    )
    row = svc.get_latest(db, policy_key, org.id)
    row.next_review_at = datetime.now(timezone.utc) - timedelta(days=1)  # overdue for review
    db.commit()

    due = lsvc.list_due_for_reattestation(db, org.id)
    assert any(r.policy_key == policy_key for r in due)

    _, decision, _ = _submit(db, agent, "vendor_payment", 9800.0)
    assert decision.outcome == "ALLOW"  # review-due alone never blocks anything


def test_expired_high_risk_authority_fails_closed(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW, risk_level="high"),
        opa_url,
    )
    row = svc.get_latest(db, policy_key, org.id)
    row.authority_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()

    _, decision, _ = _submit(db, agent, "vendor_payment", 9800.0)
    assert decision.outcome == "HUMAN_REVIEW"
    assert decision.reason == "authority_review_overdue"


def test_expired_low_risk_authority_still_allows(db, org_and_agent, opa_url):
    """A disclosed, accepted trade-off (PAYREALITY_FUTURE_VISION.md Part
    B): only high/critical-risk expired authority fails closed."""
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW, risk_level="low"),
        opa_url,
    )
    row = svc.get_latest(db, policy_key, org.id)
    row.authority_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()

    _, decision, _ = _submit(db, agent, "vendor_payment", 9800.0)
    assert decision.outcome == "ALLOW"


def test_wrong_tenant_cannot_attest(db, org_and_agent, opa_url):
    org, _, _ = org_and_agent
    other_org = Organization(id=uuid.uuid4(), name="Org B")
    db.add(other_org)
    db.commit()
    policy_key = _deploy_policy(
        db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url,
    )
    with pytest.raises(svc.RuntimePolicyNotFoundError):
        lsvc.attest_policy(db, policy_key, other_org.id, actor="attacker")


async def test_unauthorized_role_cannot_attest(db, org_and_agent):
    """AGENT_ADMIN has neither AUTHORITY_REVIEW; REVIEWER has it (Reviewer
    is the intended audience for re-attestation, same as decisions)."""
    org, _, _ = org_and_agent
    _, session = _user_and_session(db, org.id, "agent_admin")
    checker = require_permission(Permission.AUTHORITY_REVIEW)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)
    assert exc.value.status_code == 403


async def test_reviewer_role_can_attest(db, org_and_agent):
    org, _, _ = org_and_agent
    _, session = _user_and_session(db, org.id, "reviewer")
    checker = require_permission(Permission.AUTHORITY_REVIEW)
    await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)
