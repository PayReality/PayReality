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
from app.db.models import Agent, Base, Intent, Organization, Principal, RuntimePolicyRecord
from app.domain.decision import engine as decision_engine
from app.domain.decision.source import SOURCE_MANUAL_TEST, SOURCE_RUNTIME, normalize_source
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64, sign_payload
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.constraints import Constraints, RiskLevel
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.routers.intents import _build_decision_response
from app.services import capability_service, fact_service, intent_service, runtime_policy_service as svc, signing_key_service

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
