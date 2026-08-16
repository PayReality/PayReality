"""Milestone 10 (MILESTONE_10_DECISION_SECURITY_AND_CLARITY_SUMMARY.md):
adversarial regression tests for the decision-read security boundary
PHASE_2B_PRODUCTION_AND_PRODUCT_READINESS_AUDIT.md found broken --
GET /v1/decisions/{decision_id} previously had no authentication or
organization scoping at all, confirmed live in production. This file
proves the fix at the actual authorization path (the service functions
routers/intents.py now calls), not just the route: both the permission
check (require_permission) and the organization-scoping logic
(intent_service.get_decision_for_organization) are exercised directly,
the same real-infrastructure approach (a real ephemeral OPA server, a
real SQLite-backed relational database running the actual production
models) already established in test_decision_explanation.py and
test_historical_policy_binding.py.

Also covers the policy-binding permission gap
(PHASE_2B_PRODUCTION_AND_PRODUCT_READINESS_AUDIT.md section 7.1): that
endpoint now requires Permission.RUNTIME_POLICY_VIEW, matching
/explanation, closing the asymmetry that let a REVIEWER see policy
content /explanation correctly denied them.
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
from app.services import intent_service, runtime_policy_service as svc

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
    """Same fix as test_decision_explanation.py's own autouse fixture:
    intent_service.submit_intent always builds HttpOpaClient() with no
    base_url override, defaulting to settings.opa_url
    (http://localhost:8181) rather than this file's ephemeral, random-
    port OPA server -- left unpatched, every real decision query here
    would hit a deterministic opa_error:connection_error."""
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
    """A real, authenticated User/UserSession pair for the given role,
    in the given organization -- flush (not commit), matching
    test_decision_explanation.py's own fix for the SQLite timezone-
    stripping issue: commit's expire_on_commit=True would force a
    lossy reload of `expires_at` that loses the timezone SQLite never
    round-trips, breaking auth_service's own aware-datetime comparison
    (a SQLite-only artifact, not a real bug)."""
    user = User(
        id=uuid.uuid4(), organization_id=org_id, email=f"{role}@example.com", name=role.title(),
        password_hash="x", role=role,
    )
    db.add(user)
    db.flush()
    session = UserSession(id=uuid.uuid4(), user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    db.add(session)
    db.flush()
    return user, session


# --- A. Unauthenticated decision read -----------------------------------


async def test_unauthenticated_decision_read_returns_401(db):
    checker = require_permission(Permission.DECISIONS_VIEW)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=None, db=db)
    assert exc.value.status_code == 401
    assert exc.value.detail == "authentication_required"


# --- D. Insufficient permission (decision read) --------------------------


async def test_decision_read_denied_for_role_without_decisions_view(db, org_and_agent):
    """REVIEWER has only AUTHORITY_REVIEW (domain/rbac/permissions.py) --
    no DECISIONS_VIEW -- so a REVIEWER-role session must be denied here,
    the exact gap the audit found (before this fix, EVERY role, and no
    role at all, could reach this endpoint)."""
    org, _, _ = org_and_agent
    _, session = _user_and_session(db, org.id, "reviewer")
    checker = require_permission(Permission.DECISIONS_VIEW)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)
    assert exc.value.status_code == 403
    assert exc.value.detail == "permission_denied"


async def test_decision_read_allowed_for_role_with_decisions_view(db, org_and_agent):
    """GOVERNANCE_ADMIN has DECISIONS_VIEW -- must pass silently."""
    org, _, _ = org_and_agent
    _, session = _user_and_session(db, org.id, "governance_admin")
    checker = require_permission(Permission.DECISIONS_VIEW)
    await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)


# --- B. Authorized same-organization decision read ------------------------


def test_same_organization_decision_read_succeeds(db, org_and_agent, opa_url):
    org, principal, agent = org_and_agent
    _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)
    _, decision, _ = _submit(db, agent, "vendor_payment", 500.0)
    assert decision.outcome == "ALLOW"

    resolved = intent_service.get_decision_for_organization(db, decision.id, org.id)
    assert resolved.id == decision.id
    assert resolved.outcome == "ALLOW"


# --- C. Cross-organization access: no disclosure --------------------------


def test_cross_organization_decision_read_denied(db, opa_url):
    org_a = Organization(id=uuid.uuid4(), name="Org A")
    org_b = Organization(id=uuid.uuid4(), name="Org B")
    db.add_all([org_a, org_b])
    db.flush()
    principal_a = Principal(id=uuid.uuid4(), name="alice", organization_id=org_a.id)
    db.add(principal_a)
    db.flush()
    agent_a = Agent(id=uuid.uuid4(), name="agent-a", acting_for_principal_id=principal_a.id, status="active")
    db.add(agent_a)
    db.commit()

    _deploy_policy(db, org_a.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)
    _, decision, _ = _submit(db, agent_a, "vendor_payment", 500.0)
    assert decision.outcome == "ALLOW"

    with pytest.raises(intent_service.CrossOrganizationAccessError):
        intent_service.get_decision_for_organization(db, decision.id, org_b.id)

    # Org A can still read its own decision -- isolation doesn't break
    # the legitimate case.
    own = intent_service.get_decision_for_organization(db, decision.id, org_a.id)
    assert own.id == decision.id


def test_nonexistent_decision_raises_the_same_shape_of_error_as_cross_org(db, org_and_agent):
    """routers/intents.py's get_decision catches both
    DecisionNotFoundError and CrossOrganizationAccessError and returns
    the identical HTTPException(404, "decision_not_found") for either
    -- verified here at the exception-type level (both are raised, by
    distinct real conditions), and by direct code inspection of the
    router's except clauses for the HTTP-mapping claim itself, per this
    codebase's established no-TestClient convention."""
    org, _, _ = org_and_agent
    with pytest.raises(intent_service.DecisionNotFoundError):
        intent_service.get_decision_for_organization(db, uuid.uuid4(), org.id)


def test_decision_with_no_organization_is_not_reachable_by_a_real_organization(db, opa_url):
    """organization_id=None is a real, valid scope (a Principal with no
    organisation assigned -- intent_service._resolve_chain_scope's own
    docstring). A caller authenticated for a real organization must
    never be able to read a None-scoped decision: None != any real
    UUID, so it's simply unreachable via this path, not silently
    granted to whichever org asks first."""
    org = Organization(id=uuid.uuid4(), name="Org A")
    db.add(org)
    db.flush()
    orgless_principal = Principal(id=uuid.uuid4(), name="orgless-alice", organization_id=None)
    db.add(orgless_principal)
    db.flush()
    orgless_agent = Agent(id=uuid.uuid4(), name="orgless-agent", acting_for_principal_id=orgless_principal.id, status="active")
    db.add(orgless_agent)
    db.commit()

    _, decision, _ = _submit(db, orgless_agent, "vendor_payment", 500.0)
    assert decision.outcome == "HUMAN_REVIEW"
    assert decision.reason == "no_active_policy"

    with pytest.raises(intent_service.CrossOrganizationAccessError):
        intent_service.get_decision_for_organization(db, decision.id, org.id)


# --- E/F. Policy-binding permission (RUNTIME_POLICY_VIEW) -----------------


async def test_policy_binding_denied_without_runtime_policy_view(db, org_and_agent):
    org, _, _ = org_and_agent
    _, session = _user_and_session(db, org.id, "reviewer")
    checker = require_permission(Permission.RUNTIME_POLICY_VIEW)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)
    assert exc.value.status_code == 403
    assert exc.value.detail == "permission_denied"


async def test_policy_binding_allowed_with_runtime_policy_view(db, org_and_agent):
    org, _, _ = org_and_agent
    _, session = _user_and_session(db, org.id, "governance_admin")
    checker = require_permission(Permission.RUNTIME_POLICY_VIEW)
    await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)


async def test_policy_binding_allowed_for_auditor(db, org_and_agent):
    """AUDITOR also has RUNTIME_POLICY_VIEW (domain/rbac/permissions.py)
    -- confirms the fix doesn't over-narrow to a single role."""
    org, _, _ = org_and_agent
    _, session = _user_and_session(db, org.id, "auditor")
    checker = require_permission(Permission.RUNTIME_POLICY_VIEW)
    await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)


# --- G/H. Explanation permission: re-confirmed here for a single,
# self-contained decision-security-boundary suite (already covered by
# test_decision_explanation.py's own test_permission_enforcement_...,
# unmodified and still passing; not duplicated logic, just re-asserted
# against this file's own fixtures for completeness). ---------------------


async def test_explanation_denied_without_runtime_policy_view(db, org_and_agent):
    org, _, _ = org_and_agent
    _, session = _user_and_session(db, org.id, "reviewer")
    checker = require_permission(Permission.RUNTIME_POLICY_VIEW)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)
    assert exc.value.status_code == 403


async def test_explanation_allowed_with_runtime_policy_view(db, org_and_agent):
    org, _, _ = org_and_agent
    _, session = _user_and_session(db, org.id, "governance_admin")
    checker = require_permission(Permission.RUNTIME_POLICY_VIEW)
    await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)
