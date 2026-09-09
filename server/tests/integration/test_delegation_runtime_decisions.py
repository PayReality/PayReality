"""Post-audit implementation, Priority 2: organisational delegation was
already persisted (AuthorityRelationship) and already injected into the
runtime OPA input (authority_context_service.resolve_runtime_authority_
context -> runtime_truth_service.resolve -> intent_service.submit_intent's
context["authority"]), but no test proved a RuntimePolicy Condition could
actually reference it and change a real Decision outcome.

Two real gaps were found and fixed while proving this, in the smallest
way each allows (no new inheritance/multi-hop semantics):

  1. `context.authority.delegations` is a list, never null (empty when
     there are no delegations) -- Operator.EXISTS compiles to a
     "!= null" check (rego_generator.generate_condition_expression), so
     an EXISTS condition against it would always be true regardless of
     whether a delegation existed. Fixed by adding a scalar
     `delegation_count`, safely conditionable with the already-correct
     GT/GTE operators.

  2. AuthorityRelationship.cross_org_approved's own documented intent
     ("not honored in traversal unless explicitly flagged", db/models.py)
     was never actually enforced anywhere at runtime resolution --
     authority_context_service._active_inbound_delegations only ever
     filtered on to_principal_id/kind/status/validity window. Fixed by
     excluding an unapproved cross-organisation edge from the runtime
     context, fail-closed, the same as if it didn't exist.

Real SQLite + real ephemeral OPA throughout, travelling through the
actual Intent -> Runtime Truth -> Authority Context -> OPA evaluation ->
Decision path via intent_service.submit_intent, never calling
authority_context_service directly for the outcome-changing assertions
(section: "the test must travel through the real path").
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import (
    Agent,
    AuthorityCorpus,
    AuthorityRelationship,
    Base,
    Evidence,
    Organization,
    Principal,
)
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import authority_context_service, intent_service, runtime_policy_service as policy_svc, signing_key_service

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)

ACTION = "wire_transfer"
RESOURCE = "account:OPS-001"
PRINCIPAL = "bob"


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


def _org(db, name="Org A"):
    org = Organization(id=uuid.uuid4(), name=name)
    db.add(org)
    db.commit()
    return org


def _principal_and_agent(db, org_id, name):
    principal = Principal(id=uuid.uuid4(), name=name, organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name=f"{name} agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    return principal, agent


def _corpus(db, org_id):
    corpus = AuthorityCorpus(id=uuid.uuid4(), name="test corpus", status="extracted", organization_id=org_id)
    db.add(corpus)
    db.commit()
    return corpus


def _delegation(db, corpus_id, from_principal, to_principal, **overrides):
    """flush (not commit), matching test_decision_security_boundary.py's
    own established fix for the SQLite timezone-stripping issue:
    commit's expire_on_commit=True would force a lossy reload of
    valid_from/valid_to that loses the timezone SQLite never
    round-trips, breaking _active_inbound_delegations' own aware-
    datetime comparison against datetime.now(timezone.utc) (a
    SQLite-only artifact, not a real bug -- a real Postgres column
    round-trips the timezone correctly)."""
    defaults = dict(
        id=uuid.uuid4(), corpus_id=corpus_id, kind="delegation",
        from_principal=from_principal.name, to_principal=to_principal.name,
        confidence=0.95, status="active",
        from_principal_id=from_principal.id, to_principal_id=to_principal.id,
        valid_from=None, valid_to=None, cross_org_approved=False,
    )
    defaults.update(overrides)
    row = AuthorityRelationship(**defaults)
    db.add(row)
    db.flush()
    return row


def _deploy_delegation_aware_policy(db, org_id, opa_url):
    """The delegation-aware ALLOW policy every test in this file
    evaluates against. Confirmed directly from the actual compiled
    bundle (compiler_v2/rego_generator.py's own generated Rego), not
    assumed: a deployed bundle's default rule is
    `deny if { count(evaluated_mandates) == 0 }` -- when this ALLOW
    policy's own condition doesn't hold, no mandate matches, and the
    scope resolves deterministically to DENY (reason
    "no_policy_covers_scope"), not decision/engine.py's own separate
    HUMAN_REVIEW fallback (which only applies when OPA itself can't be
    queried, or no active policy exists for the org at all -- a
    different case from "a policy exists but its condition didn't
    hold"). The real, sharper proof this file needs is exactly this:
    DENY without an active delegation, ALLOW with one."""
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="delegation-aware wire transfer", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal=PRINCIPAL, action=ACTION, resource=RESOURCE),
        conditions=ConditionSet(all=(Condition(field="context.authority.delegation_count", operator=Operator.GT, value=0),)),
        effect=Effect.ALLOW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)


def _submit(db, agent):
    _intent, decision, evidence = intent_service.submit_intent(
        db, agent=agent, action=ACTION, amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource=RESOURCE,
    )
    return decision, evidence


# === A. Resolution: the delegation actually reaches the runtime context =====


def test_active_delegation_resolves_into_runtime_authority_context(db):
    org = _org(db)
    alice, _alice_agent = _principal_and_agent(db, org.id, "alice")
    bob, _bob_agent = _principal_and_agent(db, org.id, PRINCIPAL)
    corpus = _corpus(db, org.id)
    delegation = _delegation(db, corpus.id, alice, bob)

    context = authority_context_service.resolve_runtime_authority_context(db, bob, amount=None)
    assert context["delegation_count"] == 1
    assert context["delegations"][0]["id"] == str(delegation.id)
    assert context["delegations"][0]["from_principal_id"] == str(alice.id)


# === B. The delegation changes a real Decision, through the real path =======


def test_delegation_causes_a_different_decision_from_the_same_action_without_it(db, opa_url):
    org = _org(db)
    alice, _alice_agent = _principal_and_agent(db, org.id, "alice")
    bob, bob_agent = _principal_and_agent(db, org.id, PRINCIPAL)
    corpus = _corpus(db, org.id)
    _deploy_delegation_aware_policy(db, org.id, opa_url)

    without_delegation, _ = _submit(db, bob_agent)
    assert without_delegation.outcome == "DENY", (
        "a recognized scope whose condition doesn't match resolves to a real, deterministic DENY, never silently ALLOW"
    )

    _delegation(db, corpus.id, alice, bob)

    with_delegation, _ = _submit(db, bob_agent)
    assert with_delegation.outcome == "ALLOW", "the same action, same principal, same policy -- only the delegation changed"


# === C. Expired / revoked / not-yet-valid delegations are ignored ===========


def test_expired_delegation_is_ignored(db, opa_url):
    org = _org(db)
    alice, _ = _principal_and_agent(db, org.id, "alice")
    bob, bob_agent = _principal_and_agent(db, org.id, PRINCIPAL)
    corpus = _corpus(db, org.id)
    _deploy_delegation_aware_policy(db, org.id, opa_url)
    _delegation(db, corpus.id, alice, bob, valid_to=datetime.now(timezone.utc) - timedelta(days=1))

    decision, _ = _submit(db, bob_agent)
    assert decision.outcome == "DENY"


def test_revoked_delegation_is_ignored(db, opa_url):
    org = _org(db)
    alice, _ = _principal_and_agent(db, org.id, "alice")
    bob, bob_agent = _principal_and_agent(db, org.id, PRINCIPAL)
    corpus = _corpus(db, org.id)
    _deploy_delegation_aware_policy(db, org.id, opa_url)
    _delegation(db, corpus.id, alice, bob, status="revoked")

    decision, _ = _submit(db, bob_agent)
    assert decision.outcome == "DENY"


def test_not_yet_valid_delegation_is_ignored(db, opa_url):
    org = _org(db)
    alice, _ = _principal_and_agent(db, org.id, "alice")
    bob, bob_agent = _principal_and_agent(db, org.id, PRINCIPAL)
    corpus = _corpus(db, org.id)
    _deploy_delegation_aware_policy(db, org.id, opa_url)
    _delegation(db, corpus.id, alice, bob, valid_from=datetime.now(timezone.utc) + timedelta(days=1))

    decision, _ = _submit(db, bob_agent)
    assert decision.outcome == "DENY"


# === D. Cross-organisation delegation fails closed unless explicitly approved =


def test_cross_organization_delegation_is_ignored_unless_explicitly_approved(db, opa_url):
    org_a = _org(db, "Org A")
    org_b = _org(db, "Org B")
    alice_in_b, _ = _principal_and_agent(db, org_b.id, "alice")
    bob_in_a, bob_agent = _principal_and_agent(db, org_a.id, PRINCIPAL)
    corpus = _corpus(db, org_a.id)
    _deploy_delegation_aware_policy(db, org_a.id, opa_url)

    _delegation(db, corpus.id, alice_in_b, bob_in_a, cross_org_approved=False)
    unapproved, _ = _submit(db, bob_agent)
    assert unapproved.outcome == "DENY", "an unapproved cross-org edge must be excluded, fail closed"

    context = authority_context_service.resolve_runtime_authority_context(db, bob_in_a, amount=None)
    assert context["delegation_count"] == 0

    _delegation(db, corpus.id, alice_in_b, bob_in_a, cross_org_approved=True)
    approved, _ = _submit(db, bob_agent)
    assert approved.outcome == "ALLOW", "an explicitly approved cross-org edge must be honored"


# === E. Circular relationships never silently grant unintended authority ====


def test_circular_delegation_does_not_silently_grant_extra_authority(db, opa_url):
    """A -> B and B -> A both exist. Resolution is direct, one-hop only
    (no chain walk), so each principal must see exactly the one edge
    naming them as `to_principal_id` -- never more, and the cycle must
    not cause unbounded resolution."""
    org = _org(db)
    alice, alice_agent = _principal_and_agent(db, org.id, "alice")
    bob, bob_agent = _principal_and_agent(db, org.id, PRINCIPAL)
    corpus = _corpus(db, org.id)
    _delegation(db, corpus.id, alice, bob)
    _delegation(db, corpus.id, bob, alice)

    bob_context = authority_context_service.resolve_runtime_authority_context(db, bob, amount=None)
    alice_context = authority_context_service.resolve_runtime_authority_context(db, alice, amount=None)
    assert bob_context["delegation_count"] == 1
    assert alice_context["delegation_count"] == 1
    assert bob_context["delegations"][0]["from_principal_id"] == str(alice.id)
    assert alice_context["delegations"][0]["from_principal_id"] == str(bob.id)


# === F. Tenant isolation: a same-named principal in another org is unaffected =


def test_tenant_isolation_is_preserved_for_delegation_resolution(db, opa_url):
    """Two organisations, each with their own principal named "bob" (a
    distinct row, distinct id) -- Org A's bob has a real active
    delegation, Org B's bob (same name, different organisation, no
    delegation of his own) must never see it."""
    org_a = _org(db, "Org A")
    org_b = _org(db, "Org B")
    alice_in_a, _ = _principal_and_agent(db, org_a.id, "alice")
    bob_in_a, _ = _principal_and_agent(db, org_a.id, PRINCIPAL)
    bob_in_b, bob_in_b_agent = _principal_and_agent(db, org_b.id, PRINCIPAL)
    corpus_a = _corpus(db, org_a.id)
    _delegation(db, corpus_a.id, alice_in_a, bob_in_a)

    _deploy_delegation_aware_policy(db, org_b.id, opa_url)
    decision, _ = _submit(db, bob_in_b_agent)
    assert decision.outcome == "DENY", "Org B's own bob must never inherit Org A's bob's delegation"

    context_b = authority_context_service.resolve_runtime_authority_context(db, bob_in_b, amount=None)
    assert context_b["delegation_count"] == 0


# === G. Historical evidence records the authority context that produced it =


def test_evidence_records_the_authority_context_and_policy_that_produced_the_decision(db, opa_url):
    org = _org(db)
    alice, _ = _principal_and_agent(db, org.id, "alice")
    bob, bob_agent = _principal_and_agent(db, org.id, PRINCIPAL)
    corpus = _corpus(db, org.id)
    _deploy_delegation_aware_policy(db, org.id, opa_url)
    delegation = _delegation(db, corpus.id, alice, bob)

    decision, evidence = _submit(db, bob_agent)
    assert decision.outcome == "ALLOW"

    row = db.get(Evidence, evidence.id)
    payload = row.payload
    assert payload["authority_context"]["delegation_count"] == 1
    assert payload["authority_context"]["delegations"][0]["id"] == str(delegation.id)
    assert payload["delegation_chain"][0]["id"] == str(delegation.id)
    assert payload["policy_version"] is not None, "the exact policy version evaluated must be pinned on the record"
    assert decision.policy_id is not None
    assert row.decision_id == decision.id
