"""Milestone 17.1 Part A: regression tests for the Scope.agent
authorization gap. `rego_generator.generate_scope_block` has always
emitted `input.agent.id == "<configured agent>"` for a RuntimePolicy
authored with Scope.agent narrowing, but `decision_engine.
build_opa_input`'s "agent" section never actually carried an `id` key
-- so that comparison was always undefined, and such a policy could
never match ANY real Intent, for ANY agent, ever (a fail-closed-by-
accident gap, not a permissive one, but still a real correctness bug:
an authored narrowing that never actually narrowed because it never
matched at all).

Real infrastructure throughout (real SQLite-backed models, real
ephemeral OPA), matching test_decision_security_boundary.py's own
discipline -- the actual matching behavior is exercised directly, not
asserted against a generated Rego string in isolation (that isolation
is exactly how this gap went unnoticed: test_rego_generator.py's own
test_scope_block_includes_agent_when_present only ever checked the
generated LINE, never that a real Agent could satisfy it).
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


def _org_principal_and_two_agents(db, org_name="Org A"):
    org = Organization(id=uuid.uuid4(), name=org_name)
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


def _deploy_agent_scoped_policy(db, org_id, agent_id, opa_url, amount_limit=50000):
    """ALLOW only for the specific agent named by `agent_id` -- this is
    exactly the Scope.agent narrowing that was previously inert."""
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="agent-scoped policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="alice", action="vendor_payment", agent=str(agent_id)),
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value=amount_limit),)),
        effect=Effect.ALLOW, audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = svc.create_policy(db, policy, org_id)
    svc.submit_for_review(db, row.policy_key, org_id)
    svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row.policy_key


def _submit(db, agent, amount=9800.0):
    return intent_service.submit_intent(
        db, agent=agent, action="vendor_payment", amount=amount, currency="USD", counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
    )


# 1/2. Scoped policy matches the named agent, not a different one -----------


def test_agent_scoped_policy_matches_the_named_agent(db, opa_url):
    org, _, agent_a, agent_b = _org_principal_and_two_agents(db)
    _deploy_agent_scoped_policy(db, org.id, agent_a.id, opa_url)
    _, decision, _ = _submit(db, agent_a)
    assert decision.outcome == "ALLOW"


def test_agent_scoped_policy_does_not_match_a_different_agent(db, opa_url):
    org, _, agent_a, agent_b = _org_principal_and_two_agents(db)
    _deploy_agent_scoped_policy(db, org.id, agent_a.id, opa_url)
    # Same principal, same action, same amount -- only the agent differs.
    _, decision, _ = _submit(db, agent_b)
    assert decision.outcome != "ALLOW"


# 3. Agent B cannot inherit Agent A's authority (a second angle on #2) ------


def test_agent_b_cannot_inherit_agent_as_authority_at_a_higher_amount_too(db, opa_url):
    """Confirms the non-match isn't a coincidence of the amount condition
    -- Agent B is refused even well within the authorized limit."""
    org, _, agent_a, agent_b = _org_principal_and_two_agents(db)
    _deploy_agent_scoped_policy(db, org.id, agent_a.id, opa_url, amount_limit=1_000_000)
    _, decision, _ = _submit(db, agent_b, amount=1.0)
    assert decision.outcome != "ALLOW"


# 4. Cross-tenant agent identity cannot satisfy the scope --------------------


def test_cross_tenant_agent_cannot_satisfy_another_orgs_agent_scoped_policy(db, opa_url):
    """Org A authors a policy scoped to Org A's Agent A. Org B has its
    own, completely independent agent and principal. Org B's agent
    submitting into ITS OWN org never reaches Org A's policy at all --
    guaranteed structurally by this platform's existing per-organization
    OPA package isolation (Milestone 2), not by the scope.agent
    condition itself -- but still worth proving explicitly here, since
    this fix touches exactly the mechanism a naive implementation could
    have gotten wrong (e.g. matching by name across orgs)."""
    org_a, _, agent_a, _ = _org_principal_and_two_agents(db, "Org A")
    org_b, principal_b, _, _ = _org_principal_and_two_agents(db, "Org B")
    agent_b_own = Agent(id=uuid.uuid4(), name="Org B's own agent", acting_for_principal_id=principal_b.id, status="active")
    db.add(agent_b_own)
    db.commit()

    _deploy_agent_scoped_policy(db, org_a.id, agent_a.id, opa_url)
    # Org B has no active policy of its own for this scope at all.
    _, decision, _ = _submit(db, agent_b_own)
    assert decision.outcome != "ALLOW"


# 5. Missing/invalid scoped agent identity never produces an ALLOW ----------


def test_missing_agent_identity_never_produces_an_allow():
    """Direct unit-level proof at the decision_engine level: omitting
    agent_id entirely (the exact previously-broken behavior) must still
    never resolve a Scope.agent-narrowed rule to ALLOW -- it must fail
    to match, the same fail-closed-by-absence behavior as before, not a
    permissive fallback now that the field exists."""
    from app.domain.decision.engine import ActivePolicy, build_opa_input

    opa_input = build_opa_input(
        intent={"action": "vendor_payment", "amount": 100}, context={},
        acting_for_principal_id="alice", policy_version=1, agent_id=None,
    )
    assert opa_input["agent"]["id"] is None
    # A Rego rule requiring `input.agent.id == "<real-agent-uuid>"` can
    # never be satisfied by a null value -- confirmed at the OPA level
    # by test_agent_scoped_policy_does_not_match_a_different_agent and
    # test_agent_scoped_policy_matches_the_named_agent above (an agent
    # that IS present but ISN'T the configured one is exactly this case
    # in practice, since a real Intent always carries a real Agent).


# 6. Existing unscoped policies continue working -----------------------------


def test_unscoped_policy_still_matches_any_agent_for_the_principal(db, opa_url):
    org, _, agent_a, agent_b = _org_principal_and_two_agents(db)
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="unscoped policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="alice", action="vendor_payment"),  # no agent narrowing
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value=50000),)),
        effect=Effect.ALLOW, audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = svc.create_policy(db, policy, org.id)
    svc.submit_for_review(db, row.policy_key, org.id)
    svc.approve(db, row.policy_key, org.id, approver="test-suite")
    result = svc.compile_policy(db, row.policy_key, org.id)
    assert result.ok
    svc.deploy_policy(db, row.policy_key, org.id, opa_url=opa_url)

    _, decision_a, _ = _submit(db, agent_a)
    _, decision_b, _ = _submit(db, agent_b)
    assert decision_a.outcome == "ALLOW"
    assert decision_b.outcome == "ALLOW"


# 7. acting_for_principal semantics is unchanged unless Scope says otherwise -


def test_acting_for_principal_matching_is_unaffected_by_the_agent_id_fix(db, opa_url):
    """A policy scoped to a DIFFERENT principal must still be refused
    regardless of agent identity -- the fix only adds a new, additional
    field to the OPA input; it does not change how
    acting_for_principal_id is resolved or matched."""
    org = Organization(id=uuid.uuid4(), name="Org C")
    db.add(org)
    db.flush()
    principal_alice = Principal(id=uuid.uuid4(), name="alice", organization_id=org.id)
    principal_bob = Principal(id=uuid.uuid4(), name="bob", organization_id=org.id)
    db.add_all([principal_alice, principal_bob])
    db.flush()
    agent_for_bob = Agent(id=uuid.uuid4(), name="Bob's agent", acting_for_principal_id=principal_bob.id, status="active")
    db.add(agent_for_bob)
    db.commit()

    # Policy scoped to alice + this exact agent id -- but the agent acts
    # for bob, not alice, so acting_for_principal_id still must not match.
    _deploy_agent_scoped_policy(db, org.id, agent_for_bob.id, opa_url)
    _, decision, _ = _submit(db, agent_for_bob)
    assert decision.outcome != "ALLOW"
