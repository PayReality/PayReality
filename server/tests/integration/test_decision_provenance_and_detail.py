"""Product Experience Remediation Milestone 1: regression tests for
Decision Provenance (Phase 2) and the Decision Detail contract (Phase
4). Real infrastructure throughout (real SQLite-backed models, real
ephemeral OPA), matching test_domain_generalization.py's own
discipline.
"""

import base64
import uuid
from datetime import datetime, timedelta, timezone

import nacl.signing
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Base, Decision, Intent, Organization, Principal, RuntimePolicyRecord
from app.domain.decision import engine as decision_engine
from app.domain.decision.source import SOURCE_MANUAL_TEST, SOURCE_RUNTIME, normalize_source
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64, sign_payload
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.constraints import Constraints, RiskLevel
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.routers.intents import _build_decision_response
from app.services import capability_service, fact_service, intent_service, resolution_service, runtime_policy_service as svc, signing_key_service

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


def _submit(db, agent, action="disable_user", resource="account:USR-829", context=None, source=None):
    return intent_service.submit_intent(
        db, agent=agent, action=action, amount=None, currency=None, counterparty=None,
        context=context or {}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex,
        correlation_id=None, resource=resource, source=source,
    )


# -- Phase 2: Decision Provenance ----------------------------------------


def test_normalize_source_defaults_unrecognized_and_none_to_runtime():
    assert normalize_source(None) == SOURCE_RUNTIME
    assert normalize_source("bogus") == SOURCE_RUNTIME
    assert normalize_source("runtime") == SOURCE_RUNTIME
    assert normalize_source("manual_test") == SOURCE_MANUAL_TEST


def test_submit_intent_defaults_to_runtime_when_source_omitted(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    intent, _, _ = _submit(db, agent, source=None)
    assert intent.source == "runtime"


def test_submit_intent_records_explicit_manual_test_source(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    intent, _, _ = _submit(db, agent, source="manual_test")
    assert intent.source == "manual_test"


def test_legacy_intent_with_no_source_is_never_fabricated_as_runtime(db, opa_url):
    """A row written before this column existed (or by any path that
    genuinely never set it) must surface as None -- the API layer must
    not backfill it to "runtime" just because that's the common case."""
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    intent, decision, _ = _submit(db, agent, source=None)
    # Simulate a legacy row by clearing the column directly, bypassing
    # the service layer's own default -- the one way a genuinely
    # provenance-unknown historical row could exist.
    db.execute(Intent.__table__.update().where(Intent.id == intent.id).values(source=None))
    db.commit()
    response = _build_decision_response(db, decision)
    assert response.source is None


# -- Phase 4: Decision Detail contract ------------------------------------


def test_decision_detail_exposes_source_and_principal_and_evidence_id(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    _, decision, evidence = _submit(db, agent, source="manual_test")
    response = _build_decision_response(db, decision)
    assert response.source == "manual_test"
    assert response.principal_name == "alice"
    assert response.evidence_id == evidence.id


class _SourceKeypair:
    """Same real-signature helper test_enterprise_facts.py already
    establishes -- ingest_fact requires a genuine Ed25519 signature
    verified against a registered FactSource's own public key; there is
    no unsigned/self-attested ingestion path."""

    def __init__(self):
        self.signing_key = nacl.signing.SigningKey.generate()

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(bytes(self.signing_key.verify_key)).decode("ascii")

    def sign(self, payload: dict) -> str:
        return sign_payload(payload, base64.b64encode(bytes(self.signing_key)).decode("ascii"), "test-source").value


def test_decision_detail_exposes_facts_evaluated(db, opa_url):
    org, principal = _org_and_principal(db, principal_name="bob")
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="bob", action="vendor_payment"),
        conditions=[Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True)],
    )
    keypair = _SourceKeypair()
    source = fact_service.register_fact_source(db, org.id, "ERP (reference)", keypair.public_key_b64)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    attestation = fact_service.CanonicalFactAttestation(
        organization_id=str(org.id), source_id=str(source.id), subject="vendor-1",
        key="supplier_approved", value=True, observed_at=now.isoformat(),
        expires_at=(now + timedelta(hours=1)).isoformat(), nonce=nonce,
    )
    signature = keypair.sign(attestation.to_dict())
    fact_service.ingest_fact(
        db, org.id, source.id, "vendor-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce, signature,
    )

    _, decision, _ = intent_service.submit_intent(
        db, agent=agent, action="vendor_payment", amount=None, currency=None, counterparty="vendor-1",
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
    )
    assert decision.outcome == "ALLOW"
    response = _build_decision_response(db, decision)
    assert response.facts_evaluated is not None
    assert response.facts_evaluated[0]["key"] == "supplier_approved"
    assert response.facts_evaluated[0]["value"] is True
    assert response.facts_evaluated[0]["subject"] == "vendor-1"


def test_decision_detail_facts_evaluated_absent_when_no_fact_needed(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    _, decision, _ = _submit(db, agent)
    response = _build_decision_response(db, decision)
    assert response.facts_evaluated is None


def test_decision_detail_matched_policy_freshness_reflects_expired_authority(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    policy_key = _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
        constraints=Constraints(risk_level=RiskLevel.LOW),
    )
    row = db.scalar(select(RuntimePolicyRecord).where(RuntimePolicyRecord.policy_key == policy_key))
    row.authority_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()

    _, decision, _ = _submit(db, agent)
    response = _build_decision_response(db, decision)
    assert response.matched_policy_freshness is not None
    assert response.matched_policy_freshness.status == "expired"


def test_decision_detail_matched_policy_freshness_current_when_no_dates_set(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    _, decision, _ = _submit(db, agent)
    response = _build_decision_response(db, decision)
    assert response.matched_policy_freshness is not None
    assert response.matched_policy_freshness.status == "unknown"


def test_decision_detail_capability_not_issued_by_default(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    _, decision, _ = _submit(db, agent)
    response = _build_decision_response(db, decision)
    assert response.capability is None


def test_decision_detail_capability_reflects_issuance_and_consumption(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    _, decision, _ = _submit(db, agent)
    assert decision.outcome == "ALLOW"

    issued = capability_service.issue_capability_for_decision(
        db, organization_id=org.id, decision_id=decision.id, audience="test-adapter",
    )
    response = _build_decision_response(db, decision)
    assert response.capability is not None
    assert response.capability.issued is True
    assert response.capability.audience == "test-adapter"
    assert response.capability.action == "disable_user"
    assert response.capability.resource == "account:USR-829"
    assert response.capability.consumed_at is None

    capability_service.verify_and_consume_capability(
        db, token=issued.token, audience="test-adapter", action="disable_user",
        resource="account:USR-829", constraints={},
    )
    response_after = _build_decision_response(db, decision)
    assert response_after.capability.consumed_at is not None
    # Capability consumption is never treated as proof the downstream
    # business action completed -- this contract has no such field.
    assert not hasattr(response_after.capability, "execution_completed")


# -- Human Review Continuation (issue #10) --------------------------------
#
# correlation_id is trace/correlation metadata only -- these tests prove
# it round-trips honestly (present when supplied, None when it wasn't)
# and never participates in the decision itself. The status/resolution
# tests prove the machine-continuation contract this milestone is
# actually about: Decision.outcome is never rewritten after a human
# resolves a HUMAN_REVIEW decision -- the resolution is a separate,
# derived fact a caller reads alongside the untouched original outcome.


def _submit_human_review(db, agent, correlation_id=None):
    return intent_service.submit_intent(
        db, agent=agent, action="disable_user", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex,
        correlation_id=correlation_id, resource="account:USR-829",
    )


def test_decision_detail_echoes_the_correlation_id_the_intent_was_submitted_with(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    _, decision, _ = intent_service.submit_intent(
        db, agent=agent, action="disable_user", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex,
        correlation_id="JOB-983421", resource="account:USR-829",
    )
    response = _build_decision_response(db, decision)
    assert response.correlation_id == "JOB-983421"


def test_decision_detail_correlation_id_is_honestly_none_when_never_supplied(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(db, org.id, opa_url, scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"))
    _, decision, _ = _submit(db, agent)
    response = _build_decision_response(db, decision)
    assert response.correlation_id is None


def test_decision_outcome_is_never_rewritten_after_human_resolution(db, opa_url):
    """The core lifecycle guarantee this milestone must not violate:
    Decision.outcome stays HUMAN_REVIEW forever, even after a human
    approves it -- resolution is recorded as a separate fact, never a
    mutation of the original automated outcome."""
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
        effect=Effect.REQUIRE_HUMAN_REVIEW,
    )
    _, decision, _ = _submit_human_review(db, agent)
    assert decision.outcome == "HUMAN_REVIEW"

    resolution_service.resolve_decision(
        db, decision_id=decision.id, organization_id=org.id,
        resolution="approved", resolved_by="Jane Smith",
    )

    db.expire_all()
    reloaded = db.get(Decision, decision.id)
    assert reloaded.outcome == "HUMAN_REVIEW"


def test_decision_detail_status_and_resolution_reflect_human_review_lifecycle(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
        effect=Effect.REQUIRE_HUMAN_REVIEW,
    )
    _, decision, _ = _submit_human_review(db, agent, correlation_id="JOB-983421")

    pending_response = _build_decision_response(db, decision)
    assert pending_response.status == "PENDING"
    assert pending_response.resolution is None
    assert pending_response.correlation_id == "JOB-983421"

    resolution_service.resolve_decision(
        db, decision_id=decision.id, organization_id=org.id,
        resolution="approved", resolved_by="Jane Smith", reason="looked fine",
    )

    resolved_response = _build_decision_response(db, decision)
    assert resolved_response.status == "RESOLVED"
    assert resolved_response.resolution is not None
    assert resolved_response.resolution.resolution == "approved"
    assert resolved_response.resolution.resolved_by == "Jane Smith"
    assert resolved_response.resolution.reason == "looked fine"
    assert resolved_response.resolution.created_at is not None
    # Untouched by the resolution -- the automated outcome and its
    # correlation metadata still read exactly as they did while pending.
    assert resolved_response.correlation_id == "JOB-983421"


def test_decision_detail_status_and_resolution_reflect_a_denial(db, opa_url):
    """Same lifecycle, the denial path: issue #10's acceptance criteria
    require this proven separately from approval -- nothing in the
    resolved response may imply the underlying action can proceed."""
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
        effect=Effect.REQUIRE_HUMAN_REVIEW,
    )
    _, decision, _ = _submit_human_review(db, agent)
    assert _build_decision_response(db, decision).status == "PENDING"

    resolution_service.resolve_decision(
        db, decision_id=decision.id, organization_id=org.id,
        resolution="denied", resolved_by="Jane Smith", reason="Budget exceeded.",
    )

    resolved_response = _build_decision_response(db, decision)
    assert resolved_response.status == "RESOLVED"
    assert resolved_response.resolution.resolution == "denied"
    assert resolved_response.resolution.resolved_by == "Jane Smith"
    assert resolved_response.resolution.reason == "Budget exceeded."
    # outcome is never rewritten to DENY -- it stays the original
    # HUMAN_REVIEW outcome; only resolution.resolution carries the
    # human's final answer, exactly as it does for an approval.
    assert decision.outcome == "HUMAN_REVIEW"


def test_resolve_decision_rejects_a_duplicate_resolution(db, opa_url):
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
        effect=Effect.REQUIRE_HUMAN_REVIEW,
    )
    _, decision, _ = _submit_human_review(db, agent)
    resolution_service.resolve_decision(
        db, decision_id=decision.id, organization_id=org.id,
        resolution="approved", resolved_by="Jane Smith",
    )

    with pytest.raises(resolution_service.DecisionAlreadyResolvedError):
        resolution_service.resolve_decision(
            db, decision_id=decision.id, organization_id=org.id,
            resolution="denied", resolved_by="A Second Reviewer",
        )


def test_resolve_decision_translates_a_racing_integrity_error_into_the_same_already_resolved_error(db, opa_url, monkeypatch):
    """The `decision_resolutions.decision_id` UNIQUE constraint, not the
    ORM-level pre-check, is what actually stops two humans from both
    resolving the same decision -- the pre-check has a SELECT-then-
    commit race window. This forces that race deterministically (by
    making the pre-check blind to a resolution that already committed)
    and proves the resulting IntegrityError is translated into the same
    DecisionAlreadyResolvedError (-> HTTP 409) a non-racing duplicate
    already gets, not an unhandled 500."""
    org, principal = _org_and_principal(db)
    agent = _agent_for(db, principal)
    _deploy_policy(
        db, org.id, opa_url,
        scope=Scope(principal="alice", action="disable_user", resource="account:USR-829"),
        effect=Effect.REQUIRE_HUMAN_REVIEW,
    )
    _, decision, _ = _submit_human_review(db, agent)

    from app.db.models import DecisionResolution

    resolution_service.resolve_decision(
        db, decision_id=decision.id, organization_id=org.id,
        resolution="approved", resolved_by="Jane Smith",
    )

    original_query = db.query

    def _blind_to_the_winning_resolution(model, *a, **kw):
        if model is DecisionResolution:
            class _NoneResult:
                def filter_by(self, **kw):
                    return self

                def one_or_none(self):
                    return None
            return _NoneResult()
        return original_query(model, *a, **kw)

    monkeypatch.setattr(db, "query", _blind_to_the_winning_resolution)

    with pytest.raises(resolution_service.DecisionAlreadyResolvedError):
        resolution_service.resolve_decision(
            db, decision_id=decision.id, organization_id=org.id,
            resolution="denied", resolved_by="A Second Reviewer",
        )

    monkeypatch.setattr(db, "query", original_query)
    rows = db.query(DecisionResolution).filter_by(decision_id=decision.id).all()
    assert len(rows) == 1
    assert rows[0].resolution == "approved"
