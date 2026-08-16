"""Phase 2B (PHASE_2B_LIVE_PER_CONDITION_EXPLAINABILITY_SUMMARY.md): real,
non-mocked regression tests for the explanatory path
(decision_explanation_service.get_decision_explanation). Same real-
infrastructure approach as test_historical_policy_binding.py: a real
ephemeral OPA server (the existing `opa_url` fixture) and a real
relational database (SQLite in-memory, via the same JSONB/UUID
dialect-compile shims, for the same disclosed reason: no Postgres/
Docker was available in this environment). Deliberately duplicates
that file's setup helpers rather than sharing a conftest, to keep this
new, less-proven test file from risking the already-verified
historical-binding tests through a shared-fixture refactor.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Base, Organization, Policy, Principal, User, UserSession
from app.domain.decision import engine as decision_engine
from app.domain.rbac.permissions import Permission
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.dependencies import require_permission
from app.services import decision_explanation_service as svc_explain
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
    """intent_service.submit_intent (app/services/intent_service.py:502)
    always constructs `HttpOpaClient()` with no base_url override, which
    falls back to `settings.opa_url` (default http://localhost:8181) --
    a completely different address from the ephemeral, random-port OPA
    server `deploy_policy(..., opa_url=opa_url)` actually pushes bundles
    to in these tests. Left unpatched, every real decision query in this
    file hits a genuine (not flaky) `opa_error:connection_error`, 100%
    of the time, since nothing listens on 8181 during a test run.
    Deliberately test-only, mirroring the existing `evidence_signing_key_b64`
    module-level test override above: production's real settings.opa_url
    is never touched by this."""
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


def _policy(principal: str, action: str, condition: Condition, effect: Effect, policy_id: str | None = None) -> RuntimePolicy:
    return RuntimePolicy(
        id=policy_id or str(uuid.uuid4()),
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


def _redeploy_policy(db, org_id, policy_key, condition: Condition, opa_url):
    latest = svc.get_latest(db, policy_key, org_id)
    current = svc._row_to_policy(latest)
    updated = RuntimePolicy(
        id=current.id, name=current.name, version=current.version, status=current.status,
        scope=current.scope, conditions=ConditionSet(all=(condition,)), effect=current.effect,
        audit=current.audit,
    )
    svc.edit_policy(db, policy_key, org_id, updated)
    svc.submit_for_review(db, policy_key, org_id)
    svc.approve(db, policy_key, org_id, approver="test-suite")
    result = svc.compile_policy(db, policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    svc.deploy_policy(db, policy_key, org_id, opa_url=opa_url)


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
    """Real transient OPA failures (a freshly-started or just-redeployed-
    to ephemeral server occasionally answering 'opa_timeout' or
    'opa_error:connection_error', both confirmed by reading
    domain/decision/engine.py's own exception handling to only ever be
    raised from a genuine network failure) are retried with a real
    backoff, exactly as test_historical_policy_binding.py's own
    `_submit` does, for the same disclosed reason."""
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


def _explain(db, decision_id, org_id):
    return svc_explain.get_decision_explanation(db, decision_id, org_id)


# --- Outcomes ---------------------------------------------------------


def test_outcome_allow(db, org_and_agent, opa_url):
    org, principal, agent = org_and_agent
    _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)
    _, decision, _ = _submit(db, agent, "vendor_payment", 500.0)
    assert decision.outcome == "ALLOW"

    result = _explain(db, decision.id, org.id)
    assert isinstance(result, svc_explain.DecisionExplanation)
    assert result.outcome == "ALLOW"
    assert len(result.rules) == 1
    rule = result.rules[0]
    assert rule.scope_matched is True
    assert rule.matched is True
    assert rule.conditions[0].passed is True
    assert result.causal_policy_id == rule.policy_id


def test_outcome_deny(db, org_and_agent, opa_url):
    org, principal, agent = org_and_agent
    _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)
    _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.GT, value=50000), Effect.DENY), opa_url)
    _, decision, _ = _submit(db, agent, "vendor_payment", 75000.0)
    assert decision.outcome == "DENY"

    result = _explain(db, decision.id, org.id)
    assert isinstance(result, svc_explain.DecisionExplanation)
    assert result.outcome == "DENY"
    assert len(result.rules) == 2
    allow_rule = next(r for r in result.rules if r.effect == "allow")
    deny_rule = next(r for r in result.rules if r.effect == "deny")
    assert allow_rule.matched is False
    assert allow_rule.conditions[0].passed is False, "75000 does not satisfy <= 50000"
    assert deny_rule.matched is True
    assert deny_rule.conditions[0].passed is True, "75000 satisfies > 50000"
    assert result.causal_policy_id == deny_rule.policy_id


def test_outcome_escalate(db, org_and_agent, opa_url):
    org, principal, agent = org_and_agent
    _deploy_policy(db, org.id, _policy("alice", "wire_transfer", Condition(field="amount", operator=Operator.GTE, value=10000), Effect.REQUIRE_HUMAN_REVIEW), opa_url)
    _, decision, _ = _submit(db, agent, "wire_transfer", 20000.0)
    assert decision.outcome == "HUMAN_REVIEW"

    result = _explain(db, decision.id, org.id)
    assert isinstance(result, svc_explain.DecisionExplanation)
    assert result.outcome == "HUMAN_REVIEW"
    rule = result.rules[0]
    assert rule.matched is True
    assert rule.effect == "require_human_review"
    assert result.causal_policy_id == rule.policy_id


# --- Condition evaluation classifications ------------------------------


def test_mixed_conditions_passing_failing_and_irrelevant(db, org_and_agent, opa_url):
    """One rule that matches (passing condition), one relevant rule that
    doesn't (failing condition), and one rule scoped to a different
    principal entirely (not applicable/not relevant to this decision)."""
    org, principal, agent = org_and_agent
    _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)
    _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.GT, value=50000), Effect.DENY), opa_url)
    _deploy_policy(db, org.id, _policy("bob", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=999999), Effect.ALLOW), opa_url)

    _, decision, _ = _submit(db, agent, "vendor_payment", 500.0)
    assert decision.outcome == "ALLOW"

    result = _explain(db, decision.id, org.id)
    assert isinstance(result, svc_explain.DecisionExplanation)
    assert len(result.rules) == 3

    alice_allow = next(r for r in result.rules if r.principal == "alice" and r.effect == "allow")
    alice_deny = next(r for r in result.rules if r.principal == "alice" and r.effect == "deny")
    bob_rule = next(r for r in result.rules if r.principal == "bob")

    assert alice_allow.scope_matched is True and alice_allow.matched is True
    assert alice_allow.conditions[0].passed is True

    assert alice_deny.scope_matched is True and alice_deny.matched is False
    assert alice_deny.conditions[0].passed is False, "500 does not satisfy > 50000"

    assert bob_rule.scope_matched is False, "scoped to a different principal -- not applicable to this decision"
    assert bob_rule.matched is False


# --- Historical correctness ---------------------------------------------


def test_explanation_survives_two_subsequent_redeploys(db, org_and_agent, opa_url):
    org, principal, agent = org_and_agent
    policy_key = _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=100000), Effect.ALLOW, policy_id=str(uuid.uuid4())), opa_url)
    _, decision, _ = _submit(db, agent, "vendor_payment", 500.0)
    assert decision.outcome == "ALLOW"

    original = _explain(db, decision.id, org.id)
    assert isinstance(original, svc_explain.DecisionExplanation)
    assert original.rules[0].conditions[0].expected_value == 100000

    _redeploy_policy(db, org.id, policy_key, Condition(field="amount", operator=Operator.LTE, value=50000), opa_url)
    after_v2 = _explain(db, decision.id, org.id)
    assert isinstance(after_v2, svc_explain.DecisionExplanation)
    assert after_v2.rules[0].conditions[0].expected_value == 100000, "must still reflect V1, not V2's new $50,000 threshold"
    assert after_v2.bundle_hash == original.bundle_hash

    _redeploy_policy(db, org.id, policy_key, Condition(field="amount", operator=Operator.LTE, value=1), opa_url)
    after_v3 = _explain(db, decision.id, org.id)
    assert isinstance(after_v3, svc_explain.DecisionExplanation)
    assert after_v3.rules[0].conditions[0].expected_value == 100000, "must still reflect V1, not V3's new $1 threshold"
    assert after_v3.bundle_hash == original.bundle_hash
    assert after_v3.policy_id == original.policy_id


# --- Tenant isolation -----------------------------------------------------


def test_tenant_isolation_org_a_decision_not_resolvable_by_org_b(db, opa_url):
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

    with pytest.raises(svc_explain.CrossOrganizationAccessError):
        _explain(db, decision.id, org_b.id)

    # Org A can still resolve its own decision -- the isolation check
    # itself doesn't break the legitimate case.
    own = _explain(db, decision.id, org_a.id)
    assert isinstance(own, svc_explain.DecisionExplanation)


# --- Determinism ------------------------------------------------------


def test_determinism_identical_inputs_produce_identical_explanation(db, org_and_agent, opa_url):
    org, principal, agent = org_and_agent
    _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)
    _, decision, _ = _submit(db, agent, "vendor_payment", 500.0)

    first = _explain(db, decision.id, org.id)
    second = _explain(db, decision.id, org.id)
    assert first == second, "identical historical decision/policy/context must produce a byte-identical explanation"


# --- No mutation --------------------------------------------------------


def test_explanation_does_not_mutate_anything(db, org_and_agent, opa_url):
    from app.db.models import Evidence, Decision as DecisionRow

    org, principal, agent = org_and_agent
    policy_key = _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)
    _, decision, _ = _submit(db, agent, "vendor_payment", 500.0)

    policy_before = db.get(Policy, decision.policy_id)
    decision_snapshot = (decision.outcome, decision.reason, tuple(decision.evaluated_mandates), decision.policy_id)
    policy_snapshot = (policy_before.status, policy_before.bundle_hash, policy_before.bundle_manifest)
    evidence_count_before = db.query(Evidence).filter_by(decision_id=decision.id).count()

    _explain(db, decision.id, org.id)
    _explain(db, decision.id, org.id)

    db.expire_all()
    decision_after = db.get(DecisionRow, decision.id)
    policy_after = db.get(Policy, decision.policy_id)
    assert (decision_after.outcome, decision_after.reason, tuple(decision_after.evaluated_mandates), decision_after.policy_id) == decision_snapshot
    assert (policy_after.status, policy_after.bundle_hash, policy_after.bundle_manifest) == policy_snapshot
    assert db.query(Evidence).filter_by(decision_id=decision.id).count() == evidence_count_before


# --- Failure handling: explicit unavailable, never fabricated -----------


def test_unavailable_when_no_policy_was_ever_evaluated(db, org_and_agent, opa_url):
    """No policy deployed at all -- decision_engine.evaluate's own
    NoActivePolicyError branch, Decision.policy_id stays None."""
    org, principal, agent = org_and_agent
    _, decision, _ = _submit(db, agent, "vendor_payment", 500.0)
    assert decision.outcome == "HUMAN_REVIEW"
    assert decision.reason == "no_active_policy"
    assert decision.policy_id is None

    result = _explain(db, decision.id, org.id)
    assert isinstance(result, svc_explain.ExplanationUnavailable)
    assert result.reason == "no_policy_evaluated"


def test_unavailable_when_bundle_predates_manifest(db, org_and_agent, opa_url):
    """A real bundle with no bundle_manifest at all -- simulates a
    Policy row deployed before Historical Policy Binding existed. No
    backfill is possible for these; the explanation must say so
    explicitly, never silently reconstruct from nothing."""
    org, principal, agent = org_and_agent
    _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)
    _, decision, _ = _submit(db, agent, "vendor_payment", 500.0)
    assert decision.outcome == "ALLOW"

    policy = db.get(Policy, decision.policy_id)
    policy.bundle_manifest = None
    db.commit()

    result = _explain(db, decision.id, org.id)
    assert isinstance(result, svc_explain.ExplanationUnavailable)
    assert result.reason == "bundle_manifest_not_available"


def test_unavailable_when_decision_not_found(db, org_and_agent):
    org, principal, agent = org_and_agent
    with pytest.raises(svc_explain.DecisionNotFoundError):
        _explain(db, uuid.uuid4(), org.id)


# --- Permission enforcement ----------------------------------------------


async def test_permission_enforcement_unauthenticated_unauthorized_authorized(db):
    """Calling require_permission's own inner check function directly,
    the same pattern this codebase's own architectural-boundary tests
    already use for router-level checks (no existing TestClient/HTTP
    pattern in this codebase, confirmed before writing this) rather
    than standing up a full authenticated HTTP round trip."""
    org = Organization(id=uuid.uuid4(), name="Org")
    db.add(org)
    db.flush()

    unauthorized_user = User(
        id=uuid.uuid4(), organization_id=org.id, email="reviewer@example.com", name="Reviewer",
        password_hash="x", role="reviewer",
    )
    authorized_user = User(
        id=uuid.uuid4(), organization_id=org.id, email="admin@example.com", name="Governance Admin",
        password_hash="x", role="governance_admin",
    )
    db.add_all([unauthorized_user, authorized_user])
    db.flush()
    now = datetime.now(timezone.utc)
    unauthorized_session = UserSession(id=uuid.uuid4(), user_id=unauthorized_user.id, expires_at=now + timedelta(hours=1))
    authorized_session = UserSession(id=uuid.uuid4(), user_id=authorized_user.id, expires_at=now + timedelta(hours=1))
    db.add_all([unauthorized_session, authorized_session])
    # flush (not commit): resolve_user_for_session_token's `session.expires_at
    # <= now` compares against a timezone-AWARE `now`, which only works if
    # `expires_at` round-trips as aware too. SQLite's DATETIME type silently
    # strips tzinfo on reload regardless of `timezone=True` on the column (a
    # well-known SQLAlchemy+SQLite limitation, not a real bug in
    # auth_service.py, which is written for Postgres's real
    # TIMESTAMP WITH TIME ZONE behavior). `db.commit()`'s default
    # expire_on_commit=True would force exactly that lossy reload before
    # `require_permission` ever runs; flush() makes the rows visible to the
    # same session's subsequent query without expiring the in-memory
    # objects, so the original aware datetimes survive.
    db.flush()

    checker = require_permission(Permission.RUNTIME_POLICY_VIEW)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=None, db=db)
    assert exc.value.status_code == 401
    assert exc.value.detail == "authentication_required"

    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=f"Bearer {unauthorized_session.id}", db=db)
    assert exc.value.status_code == 403
    assert exc.value.detail == "permission_denied"

    # No exception raised: an authorized caller passes silently.
    await checker(x_payreality_operator_key=None, authorization=f"Bearer {authorized_session.id}", db=db)
