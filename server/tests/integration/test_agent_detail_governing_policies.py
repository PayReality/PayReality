"""Product Experience Remediation Milestone 1, Phase 5: regression
tests for the Agent Detail governing-policy scope bug (list_policies_
for_principal previously matched on Scope.principal alone, ignoring
Scope.agent narrowing -- so a policy authored for one specific agent
appeared to "govern" every sibling agent sharing the same principal),
plus the action/resource projection onto LinkedPolicySummary and
DecisionSummary. Real infrastructure throughout.
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
from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.routers.agents import _build_agent_detail
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


def _org_principal_and_two_agents(db):
    org = Organization(id=uuid.uuid4(), name="Org A")
    db.add(org)
    db.flush()
    principal = Principal(id=uuid.uuid4(), name="alice", organization_id=org.id)
    db.add(principal)
    db.flush()
    agent_a = Agent(id=uuid.uuid4(), name="Agent A", acting_for_principal_id=principal.id, status="active")
    agent_b = Agent(id=uuid.uuid4(), name="Agent B", acting_for_principal_id=principal.id, status="active")
    db.add_all([agent_a, agent_b])
    db.commit()
    return org, principal, agent_a, agent_b


def _deploy_policy(db, org_id, opa_url, name, scope):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name=name, version=1, status=PolicyStatus.DRAFT,
        scope=scope, conditions=ConditionSet(all=()), effect=Effect.ALLOW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = svc.create_policy(db, policy, org_id)
    svc.submit_for_review(db, row.policy_key, org_id)
    svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row.policy_key


def test_agent_scoped_policy_only_governs_the_named_agent(db, opa_url):
    org, principal, agent_a, agent_b = _org_principal_and_two_agents(db)
    _deploy_policy(
        db, org.id, opa_url, "Agent A only",
        Scope(principal="alice", action="disable_user", agent=str(agent_a.id), resource="account:USR-829"),
    )

    rows_for_a = svc.list_policies_for_principal(db, org.id, "alice", agent_id=agent_a.id)
    rows_for_b = svc.list_policies_for_principal(db, org.id, "alice", agent_id=agent_b.id)

    assert [r.content["name"] for r in rows_for_a] == ["Agent A only"]
    # The bug this fixes: previously Agent B would also see this policy
    # listed as "governing" it, despite Scope.agent narrowing it away.
    assert rows_for_b == []


def test_unscoped_policy_still_governs_every_agent_under_the_principal(db, opa_url):
    org, principal, agent_a, agent_b = _org_principal_and_two_agents(db)
    _deploy_policy(db, org.id, opa_url, "Applies to anyone", Scope(principal="alice", action="disable_user"))

    rows_for_a = svc.list_policies_for_principal(db, org.id, "alice", agent_id=agent_a.id)
    rows_for_b = svc.list_policies_for_principal(db, org.id, "alice", agent_id=agent_b.id)
    assert [r.content["name"] for r in rows_for_a] == ["Applies to anyone"]
    assert [r.content["name"] for r in rows_for_b] == ["Applies to anyone"]


def test_list_policies_for_principal_with_no_agent_id_preserves_old_principal_only_behavior(db, opa_url):
    """agent_id=None (the default) must not exclude an agent-scoped
    policy -- the one other conceptual caller (a "policies for this
    principal generally" query with no specific agent in hand) keeps
    exactly its previous, permissive behavior."""
    org, principal, agent_a, _ = _org_principal_and_two_agents(db)
    _deploy_policy(
        db, org.id, opa_url, "Agent A only",
        Scope(principal="alice", action="disable_user", agent=str(agent_a.id)),
    )
    rows = svc.list_policies_for_principal(db, org.id, "alice")
    assert [r.content["name"] for r in rows] == ["Agent A only"]


def test_agent_detail_linked_policy_summary_exposes_action_and_resource(db, opa_url):
    org, principal, agent_a, _ = _org_principal_and_two_agents(db)
    _deploy_policy(
        db, org.id, opa_url, "Disable privileged accounts",
        Scope(principal="alice", action="disable_user", resource="account:USR-829"),
    )
    detail = _build_agent_detail(db, agent_a, None, [])
    assert len(detail.policies) == 1
    assert detail.policies[0].action == "disable_user"
    assert detail.policies[0].resource == "account:USR-829"


def test_agent_detail_recent_decisions_expose_action_and_resource(db, opa_url):
    org, principal, agent_a, _ = _org_principal_and_two_agents(db)
    _deploy_policy(
        db, org.id, opa_url, "Disable privileged accounts",
        Scope(principal="alice", action="disable_user", resource="account:USR-829"),
    )
    intent_service.submit_intent(
        db, agent=agent_a, action="disable_user", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex,
        correlation_id=None, resource="account:USR-829",
    )
    detail = _build_agent_detail(db, agent_a, None, [])
    assert len(detail.recent_decisions) == 1
    assert detail.recent_decisions[0].action == "disable_user"
    assert detail.recent_decisions[0].resource == "account:USR-829"
    # No amount/currency fields on this contract at all -- structural.
    assert "amount" not in type(detail.recent_decisions[0]).model_fields
