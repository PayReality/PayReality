"""Product Experience Remediation Milestone 1, Phase 6: regression
tests for the bounded, organisation-scoped Assurance summary
(assurance_service.get_summary / GET /v1/assurance/summary), replacing
the previous unbounded client-side scan. Real infrastructure
throughout.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Base, Organization, Principal, RuntimePolicyRecord
from app.domain.decision import engine as decision_engine
from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.constraints import Constraints, RiskLevel
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import assurance_service, intent_service, resolution_service, runtime_policy_service as svc

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


def _agent_for(db, principal, status="active"):
    agent = Agent(id=uuid.uuid4(), name="Test Agent", acting_for_principal_id=principal.id, status=status)
    db.add(agent)
    db.commit()
    return agent


def _deploy_policy(db, org_id, opa_url, scope, constraints=None):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="test policy", version=1, status=PolicyStatus.DRAFT,
        scope=scope, conditions=ConditionSet(all=()), effect=Effect.ALLOW,
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


def _submit(db, agent, action="disable_user", resource="account:USR-829"):
    return intent_service.submit_intent(
        db, agent=agent, action=action, amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex,
        correlation_id=None, resource=resource,
    )


def test_summary_is_organization_scoped(db, opa_url):
    org_a, principal_a = _org_and_principal(db, "Org A", "alice")
    org_b, principal_b = _org_and_principal(db, "Org B", "bob")
    _agent_for(db, principal_a)
    _agent_for(db, principal_b)
    _agent_for(db, principal_b)

    summary_a = assurance_service.get_summary(db, org_a.id)
    summary_b = assurance_service.get_summary(db, org_b.id)
    assert summary_a.total_agents == 1
    assert summary_b.total_agents == 2


def test_summary_counts_active_vs_total_agents(db, opa_url):
    org, principal = _org_and_principal(db)
    _agent_for(db, principal, status="active")
    _agent_for(db, principal, status="active")
    _agent_for(db, principal, status="suspended")

    summary = assurance_service.get_summary(db, org.id)
    assert summary.total_agents == 3
    assert summary.active_agents == 2


def test_summary_counts_outcomes(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    _submit(db, agent)
    _submit(db, agent)
    _submit(db, agent, action="genuinely_unrecognized_action")

    summary = assurance_service.get_summary(db, org.id)
    assert summary.allow_count == 2
    assert summary.human_review_count == 1
    assert summary.deny_count == 0


def test_summary_pending_and_resolved_review_counts(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _, decision_1, _ = _submit(db, agent, action="unrecognized_one")
    _, decision_2, _ = _submit(db, agent, action="unrecognized_two")
    assert decision_1.outcome == "HUMAN_REVIEW"
    assert decision_2.outcome == "HUMAN_REVIEW"

    resolution_service.resolve_decision(
        db, decision_id=decision_1.id, organization_id=org.id, resolution="approved",
        resolved_by="reviewer", reason=None,
    )

    summary = assurance_service.get_summary(db, org.id)
    assert summary.pending_review_count == 1
    assert summary.resolved_review_count == 1
    assert summary.oldest_pending_review_at is not None


def test_summary_policy_review_due_and_authority_expired_counts(db, opa_url):
    org, principal = _org_and_principal(db)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
        constraints=Constraints(risk_level=RiskLevel.LOW),
    )
    row = db.query(RuntimePolicyRecord).filter_by(organization_id=org.id).one()
    row.next_review_at = datetime.now(timezone.utc) - timedelta(days=1)
    row.authority_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()

    summary = assurance_service.get_summary(db, org.id)
    assert summary.active_policies == 1
    assert summary.policies_review_due == 1
    assert summary.policies_authority_expired == 1


def test_summary_evidence_status_breakdown(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    _submit(db, agent)
    _submit(db, agent)

    summary = assurance_service.get_summary(db, org.id)
    assert summary.evidence_total == 2
    assert summary.evidence_verified == 2
    assert summary.evidence_pending == 0
    assert summary.evidence_rejected == 0


def test_summary_has_no_invented_score_field():
    """Structural guarantee: no trust/safety/governance score field
    exists on this contract at all."""
    from app.schemas.assurance import AssuranceSummaryResponse

    fields = set(AssuranceSummaryResponse.model_fields.keys())
    for banned in ("score", "trust_score", "safety_score", "governance_score", "health_score"):
        assert banned not in fields
