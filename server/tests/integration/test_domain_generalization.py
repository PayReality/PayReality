"""Domain Generalization Milestone: regression tests proving PayReality
can authorize a genuinely non-financial consequential action (here,
`disable_user`) end to end -- no fake amount, no fake currency, no
financial-only action allowlist -- while every existing financial flow
keeps working exactly as before.

Real infrastructure throughout (real SQLite-backed models, real
ephemeral OPA), matching test_scope_agent_authorization.py's own
discipline: the actual matching/recognition behavior is exercised
directly, not asserted against generated Rego or vocabulary objects in
isolation.
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
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.constraints import Constraints, RiskLevel
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import capability_service, intent_service, runtime_policy_service as svc, signing_key_service

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
    # signing_key_service.ensure_current_key_registered normally runs
    # once at app startup (main.py's lifespan) -- needed explicitly
    # here so capability-token verification can resolve
    # settings.evidence_signing_key_id back to a public key.
    signing_key_service.ensure_current_key_registered(
        session, settings.evidence_signing_key_id,
        public_key_b64_from_signing_key_b64(settings.evidence_signing_key_b64),
    )
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


def _agent_for(db, principal):
    agent = Agent(id=uuid.uuid4(), name="Test Agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    return agent


def _deploy_policy(db, org_id, opa_url, scope, conditions=(), effect=Effect.ALLOW, constraints=None):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="test policy", version=1, status=PolicyStatus.DRAFT,
        scope=scope, conditions=ConditionSet(all=tuple(conditions)), effect=effect,
        constraints=constraints or Constraints(),
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = svc.create_policy(db, policy, org_id)
    svc.submit_for_review(db, row.policy_key, org_id)
    svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row.policy_key


def _submit(db, agent, action="vendor_payment", amount=None, currency=None, resource=None, context=None):
    return intent_service.submit_intent(
        db, agent=agent, action=action, amount=amount, currency=currency, counterparty=None,
        context=context or {}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex,
        correlation_id=None, resource=resource,
    )


# -- Resource-scoping (P0 #5) -------------------------------------------


def test_resource_scoped_policy_matches_the_named_resource(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
    )
    _, decision, _ = _submit(db, agent, action="disable_user", resource="account:USR-829")
    assert decision.outcome == "ALLOW"


def test_resource_scoped_policy_does_not_match_a_different_resource(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
    )
    _, decision, _ = _submit(db, agent, action="disable_user", resource="account:OTHER-999")
    assert decision.outcome != "ALLOW"


def test_missing_resource_does_not_silently_allow_a_resource_scoped_policy(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
    )
    _, decision, _ = _submit(db, agent, action="disable_user", resource=None)
    assert decision.outcome != "ALLOW"


def test_existing_unscoped_financial_policy_still_matches_regardless_of_resource(db, opa_url):
    """A pre-existing, resource-agnostic financial policy (Scope.resource
    is None -- the shape every currently-deployed financial policy
    actually has) must keep matching exactly as before, whether or not
    a caller happens to also supply a resource."""
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="vendor_payment"),
        conditions=[Condition(field="amount", operator=Operator.LTE, value=50000)],
    )
    _, decision_no_resource, _ = _submit(db, agent, action="vendor_payment", amount=9800.0, currency="USD")
    _, decision_with_resource, _ = _submit(
        db, agent, action="vendor_payment", amount=9800.0, currency="USD", resource="invoice:INV-1"
    )
    assert decision_no_resource.outcome == "ALLOW"
    assert decision_with_resource.outcome == "ALLOW"


# -- Non-financial action end to end (Primary Goal, P0 #6/#7) -----------


def test_disable_user_is_unrecognized_until_a_real_active_policy_governs_it(db, opa_url):
    """Proves the dynamic half of the generalized action gate: a
    non-financial action is only submittable for an organization once
    that organization has actually authored and activated a real
    policy for it -- not merely because the platform globally knows
    the action type exists."""
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)

    _, decision_before, _ = _submit(db, agent, action="disable_user", resource="account:USR-829")
    assert decision_before.outcome == "HUMAN_REVIEW"
    assert decision_before.reason == "unrecognized_action"

    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
        conditions=[Condition(field="context.privileged_account", operator=Operator.EQ, value=True)],
        constraints=Constraints(risk_level=RiskLevel.HIGH),
    )
    _, decision_after, _ = _submit(
        db, agent, action="disable_user", resource="account:USR-829",
        context={"privileged_account": True, "environment": "production"},
    )
    assert decision_after.reason != "unrecognized_action"
    assert decision_after.outcome == "ALLOW"


def test_non_financial_decision_reaches_opa_without_amount_or_currency(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
        conditions=[Condition(field="context.privileged_account", operator=Operator.EQ, value=True)],
        constraints=Constraints(risk_level=RiskLevel.HIGH),
    )
    intent, decision, evidence = _submit(
        db, agent, action="disable_user", resource="account:USR-829",
        context={"privileged_account": True, "environment": "production"},
    )
    assert intent.amount is None
    assert intent.currency is None
    assert decision.outcome == "ALLOW"
    assert "amount" not in evidence.payload
    assert "currency" not in evidence.payload
    assert evidence.payload["resource"] == "account:USR-829"


def test_generic_context_conditions_evaluate_for_a_non_financial_action(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
        conditions=[Condition(field="context.environment", operator=Operator.EQ, value="production")],
    )
    _, allow_decision, _ = _submit(
        db, agent, action="disable_user", resource="account:USR-829", context={"environment": "production"},
    )
    _, non_match_decision, _ = _submit(
        db, agent, action="disable_user", resource="account:USR-829", context={"environment": "staging"},
    )
    assert allow_decision.outcome == "ALLOW"
    assert non_match_decision.outcome != "ALLOW"


def test_risk_classification_uses_explicit_policy_risk_level_not_low(db, opa_url):
    """The audit's own concern: a non-financial action must never be
    silently classified LOW purely because it has no amount. Here the
    matched policy explicitly authors risk_level=HIGH."""
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
        constraints=Constraints(risk_level=RiskLevel.HIGH),
    )
    _, decision, evidence = _submit(db, agent, action="disable_user", resource="account:USR-829")
    assert decision.outcome == "ALLOW"
    assert evidence.payload["risk_classification"] == "HIGH"


def test_risk_classification_defaults_to_medium_not_low_with_no_signal_at_all(db, opa_url):
    """No amount, and the matched policy declares no risk_level either
    -- the conservative default must be MEDIUM, never LOW."""
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
    )
    _, decision, evidence = _submit(db, agent, action="disable_user", resource="account:USR-829")
    assert decision.outcome == "ALLOW"
    assert evidence.payload["risk_classification"] == "MEDIUM"


def test_financial_risk_classification_is_unchanged_by_amount_thresholds(db, opa_url):
    """No matched-policy risk_level declared here (matching every
    currently-deployed demo financial policy's own shape for this
    specific check) -- the pre-existing amount-threshold heuristic must
    still govern unchanged."""
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="vendor_payment"),
        conditions=[Condition(field="amount", operator=Operator.LTE, value=1_000_000)],
    )
    _, decision, evidence = _submit(db, agent, action="vendor_payment", amount=120_000.0, currency="USD")
    assert decision.outcome == "ALLOW"
    assert evidence.payload["risk_classification"] == "HIGH"  # >= 100_000 threshold, unchanged


# -- Capability Authorization (P1 #9) ------------------------------------


def test_capability_binds_generic_constraints_for_a_non_financial_decision(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
        constraints=Constraints(risk_level=RiskLevel.HIGH),
    )
    _, decision, _ = _submit(
        db, agent, action="disable_user", resource="account:USR-829",
        context={"environment": "production", "privileged_account": True},
    )
    assert decision.outcome == "ALLOW"

    issued = capability_service.issue_capability_for_decision(
        db, organization_id=org.id, decision_id=decision.id, audience="test-adapter",
    )
    from app.db.models import CapabilityToken

    token_row = db.query(CapabilityToken).filter_by(id=issued.capability_id).one()
    # The capability's own signed payload constraints are only visible
    # via verify_and_consume; what we can assert directly here is that
    # issuance succeeded with no amount/currency anywhere to fabricate,
    # and a real, distinct token was minted for a genuinely non-
    # financial ALLOW decision.
    assert token_row.decision_id == decision.id

    consumed = capability_service.verify_and_consume_capability(
        db, token=issued.token, audience="test-adapter", action="disable_user",
        resource="account:USR-829",
        constraints={"environment": "production", "privileged_account": "True"},
    )
    assert consumed.resource == "account:USR-829"
    assert "amount" not in consumed.constraints
    assert "currency" not in consumed.constraints
    assert consumed.constraints["environment"] == "production"


def test_capability_still_binds_amount_and_currency_for_a_financial_decision(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="vendor_payment"),
        conditions=[Condition(field="amount", operator=Operator.LTE, value=50000)],
    )
    _, decision, _ = _submit(db, agent, action="vendor_payment", amount=9800.0, currency="USD")
    assert decision.outcome == "ALLOW"

    issued = capability_service.issue_capability_for_decision(
        db, organization_id=org.id, decision_id=decision.id, audience="test-adapter",
    )
    consumed = capability_service.verify_and_consume_capability(
        db, token=issued.token, audience="test-adapter", action="vendor_payment",
        resource=consumed_resource_fallback(db, decision),
        # Numeric(18, 2) round-trips through SQLite/Postgres as "9800.00",
        # not the Python float literal's own repr -- str(intent.amount)
        # is what capability_service actually binds.
        constraints={"amount": "9800.00", "currency": "USD"},
    )
    assert consumed.constraints["amount"] == "9800.00"
    assert consumed.constraints["currency"] == "USD"


def consumed_resource_fallback(db, decision):
    """The financial policy above authored no Scope.resource and the
    intent supplied none either, so capability_service falls back to
    correlation_id, then the Intent's own row id -- read back the same
    way to construct a valid verify() call, not a second resolution
    mechanism."""
    from app.db.models import Intent

    intent = db.get(Intent, decision.intent_id)
    return intent.resource or intent.correlation_id or str(intent.id)


# -- Fail-closed invariants (Security) ------------------------------------


def test_unrecognized_action_never_silently_allows(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _, decision, _ = _submit(db, agent, action="totally_unknown_action_xyz")
    assert decision.outcome == "HUMAN_REVIEW"
    assert decision.reason == "unrecognized_action"


def test_cross_tenant_active_policy_does_not_leak_action_recognition(db, opa_url):
    """Org B must not become able to submit `disable_user` merely
    because Org A activated a policy for it -- list_active_scope_actions
    is organization-scoped, not global."""
    org_a, principal_a = _org_and_principal(db, "Org A", "alice")
    org_b, principal_b = _org_and_principal(db, "Org B", "bob")
    agent_b = _agent_for(db, principal_b)

    _deploy_policy(
        db, org_a.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
    )
    _, decision, _ = _submit(db, agent_b, action="disable_user", resource="account:USR-829")
    assert decision.outcome == "HUMAN_REVIEW"
    assert decision.reason == "unrecognized_action"
