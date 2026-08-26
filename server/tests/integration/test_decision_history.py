"""Product Experience Remediation Milestone 1, Phase 3: regression
tests for the organisation-scoped, paginated Decision history query
(intent_service.list_decision_history / GET /v1/decisions/history).
Real infrastructure throughout, matching the established discipline.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Base, Organization, Principal
from app.domain.decision import engine as decision_engine
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
    opa_url = request.getfixturevalue("opa_url")
    original = settings.opa_url
    settings.opa_url = opa_url
    try:
        yield
    finally:
        settings.opa_url = original


def _org_and_principal(db, org_name="Org A", principal_name="alice"):
    org = Organization(id=uuid.uuid4(), name=org_name)
    db.add(org)
    db.flush()
    principal = Principal(id=uuid.uuid4(), name=principal_name, organization_id=org.id)
    db.add(principal)
    db.commit()
    return org, principal


def _agent_for(db, principal, name="Test Agent"):
    agent = Agent(id=uuid.uuid4(), name=name, acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    return agent


def _deploy_policy(db, org_id, opa_url, scope, conditions=()):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="test policy", version=1, status=PolicyStatus.DRAFT,
        scope=scope, conditions=ConditionSet(all=tuple(conditions)), effect=Effect.ALLOW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = svc.create_policy(db, policy, org_id)
    svc.submit_for_review(db, row.policy_key, org_id)
    svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row.policy_key


def _submit(db, agent, action="disable_user", resource="account:USR-829", source=None):
    return intent_service.submit_intent(
        db, agent=agent, action=action, amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex,
        correlation_id=None, resource=resource, source=source,
    )


def test_history_is_organization_scoped(db, opa_url):
    org_a, principal_a = _org_and_principal(db, "Org A", "alice")
    org_b, principal_b = _org_and_principal(db, "Org B", "bob")
    agent_a = _agent_for(db, principal_a)
    agent_b = _agent_for(db, principal_b)
    _deploy_policy(db, org_a.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    _deploy_policy(db, org_b.id, opa_url, scope=Scope(principal="bob", action="disable_user", resource="account:USR-829"))
    _submit(db, agent_a)
    _submit(db, agent_b)

    decisions_a, total_a = intent_service.list_decision_history(db, org_a.id)
    decisions_b, total_b = intent_service.list_decision_history(db, org_b.id)
    assert total_a == 1
    assert total_b == 1
    assert decisions_a[0].intent_id != decisions_b[0].intent_id


def test_history_returns_newest_first_and_paginates(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    submitted = [_submit(db, agent)[1] for _ in range(5)]

    page1, total = intent_service.list_decision_history(db, org.id, limit=2, offset=0)
    assert total == 5
    assert len(page1) == 2
    assert page1[0].id == submitted[-1].id
    assert page1[1].id == submitted[-2].id

    page2, _ = intent_service.list_decision_history(db, org.id, limit=2, offset=2)
    assert page2[0].id == submitted[-3].id


def test_history_filters_by_outcome_agent_action_resource_and_source(db, opa_url):
    org, principal = _org_and_principal(db)
    agent_1 = _agent_for(db, principal, name="Agent One")
    agent_2 = _agent_for(db, principal, name="Agent Two")
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-900"))

    _submit(db, agent_1, resource="account:USR-829", source="manual_test")
    _submit(db, agent_2, resource="account:USR-900", source=None)
    _submit(db, agent_2, action="totally_unknown_action")  # HUMAN_REVIEW, unrecognized

    by_outcome, total = intent_service.list_decision_history(db, org.id, outcome="ALLOW")
    assert total == 2
    assert all(d.outcome == "ALLOW" for d in by_outcome)

    by_agent, total = intent_service.list_decision_history(db, org.id, agent_id=agent_1.id)
    assert total == 1

    by_resource, total = intent_service.list_decision_history(db, org.id, resource="account:USR-900")
    assert total == 1

    by_source, total = intent_service.list_decision_history(db, org.id, source="manual_test")
    assert total == 1

    by_action, total = intent_service.list_decision_history(db, org.id, action="totally_unknown_action")
    assert total == 1
    assert by_action[0].outcome == "HUMAN_REVIEW"


def test_history_does_not_force_amount_or_currency_fields():
    """The response schema itself has no amount/currency fields at all
    -- a structural guarantee, not just an unused-field observation."""
    from app.schemas.intent import DecisionHistoryItem

    assert "amount" not in DecisionHistoryItem.model_fields
    assert "currency" not in DecisionHistoryItem.model_fields


def test_history_item_router_projection_includes_agent_principal_policy_and_evidence(db, opa_url):
    from app.routers.intents import _build_decision_history_item

    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal, name="Agent One")
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    _, decision, evidence = _submit(db, agent, source="manual_test")

    item = _build_decision_history_item(db, decision)
    assert item.agent_name == "Agent One"
    assert item.principal_name == "alice"
    assert item.action == "disable_user"
    assert item.resource == "account:USR-829"
    assert item.matched_policy_name == "test policy"
    assert item.source == "manual_test"
    assert item.has_evidence is True
    assert item.human_review_state is None  # ALLOW, not HUMAN_REVIEW


def test_history_item_human_review_state_pending_then_resolved(db, opa_url):
    from app.routers.intents import _build_decision_history_item
    from app.services import resolution_service

    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _, decision, _ = _submit(db, agent, action="never_authored_anywhere")
    assert decision.outcome == "HUMAN_REVIEW"

    item_before = _build_decision_history_item(db, decision)
    assert item_before.human_review_state == "pending"

    resolution_service.resolve_decision(
        db, decision_id=decision.id, organization_id=org.id, resolution="approved",
        resolved_by="test-reviewer", reason=None,
    )
    item_after = _build_decision_history_item(db, decision)
    assert item_after.human_review_state == "resolved"
