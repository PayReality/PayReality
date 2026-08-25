"""Trusted Enterprise Facts (PAYREALITY_FUTURE_VISION.md Part A):
real-infrastructure tests (real SQLite-backed models, real ephemeral
OPA), matching the established discipline in
test_decision_security_boundary.py -- the actual authorization/trust
boundary is exercised directly, not mocked.
"""

import base64
import uuid
from datetime import datetime, timedelta, timezone

import nacl.signing
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Base, EnterpriseFact, FactSource, Organization, Principal
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import sign_payload
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import fact_service, intent_service, runtime_policy_service as svc

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
        id=str(uuid.uuid4()), name=f"{action} policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal=principal, action=action), conditions=ConditionSet(all=(condition,)),
        effect=effect, audit=AuditTrail(created=datetime.now(timezone.utc)),
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


def _submit(db, agent, action, amount, counterparty=None):
    intent, decision, evidence = intent_service.submit_intent(
        db, agent=agent, action=action, amount=amount, currency="USD", counterparty=counterparty,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
    )
    return intent, decision, evidence


class _SourceKeypair:
    def __init__(self):
        self.signing_key = nacl.signing.SigningKey.generate()

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(bytes(self.signing_key.verify_key)).decode("ascii")

    def sign(self, payload: dict) -> str:
        return sign_payload(payload, base64.b64encode(bytes(self.signing_key)).decode("ascii"), "test-source").value


def _register_source(db, org_id) -> tuple[FactSource, _SourceKeypair]:
    keypair = _SourceKeypair()
    source = fact_service.register_fact_source(db, org_id, "SAP S/4HANA (reference)", keypair.public_key_b64)
    return source, keypair


def _sign_attestation(keypair, org_id, source_id, subject, key, value, observed_at, expires_at, nonce) -> str:
    attestation = fact_service.CanonicalFactAttestation(
        organization_id=str(org_id), source_id=str(source_id), subject=subject, key=key, value=value,
        observed_at=observed_at.isoformat(), expires_at=expires_at.isoformat(), nonce=nonce,
    )
    return keypair.sign(attestation.to_dict())


# --- Ingestion: signature verification -------------------------------------


def test_valid_signed_fact_is_ingested(db, org_and_agent):
    org, _, _ = org_and_agent
    source, keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    signature = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce)

    fact = fact_service.ingest_fact(
        db, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce, signature,
    )
    assert fact.value is True
    assert fact.attestation_type == "signed"


def test_invalid_signature_is_rejected(db, org_and_agent):
    org, _, _ = org_and_agent
    source, _keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    with pytest.raises(fact_service.InvalidFactSignatureError):
        fact_service.ingest_fact(
            db, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1),
            uuid.uuid4().hex, base64.b64encode(b"not a real signature bytes!!!!!!").decode("ascii"),
        )


def test_tampered_value_after_signing_is_rejected(db, org_and_agent):
    org, _, _ = org_and_agent
    source, keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    signature = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce)
    with pytest.raises(fact_service.InvalidFactSignatureError):
        fact_service.ingest_fact(
            db, org.id, source.id, "supplier-1", "supplier_approved", False,  # tampered: True -> False
            now, now + timedelta(hours=1), nonce, signature,
        )


def test_tampered_subject_after_signing_is_rejected(db, org_and_agent):
    org, _, _ = org_and_agent
    source, keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    signature = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce)
    with pytest.raises(fact_service.InvalidFactSignatureError):
        fact_service.ingest_fact(
            db, org.id, source.id, "supplier-2",  # tampered
            "supplier_approved", True, now, now + timedelta(hours=1), nonce, signature,
        )


def test_tampered_organization_after_signing_is_rejected(db, org_and_agent):
    org, _, _ = org_and_agent
    other_org = Organization(id=uuid.uuid4(), name="Org B")
    db.add(other_org)
    db.commit()
    source, keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    signature = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce)
    with pytest.raises(fact_service.FactSourceNotFoundError):
        fact_service.ingest_fact(
            db, other_org.id,  # tampered: claims a different org than the source belongs to
            source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce, signature,
        )


def test_tampered_expiry_after_signing_is_rejected(db, org_and_agent):
    org, _, _ = org_and_agent
    source, keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    real_expiry = now + timedelta(hours=1)
    signature = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now, real_expiry, nonce)
    with pytest.raises(fact_service.InvalidFactSignatureError):
        fact_service.ingest_fact(
            db, org.id, source.id, "supplier-1", "supplier_approved", True, now,
            now + timedelta(days=365),  # tampered: extend the expiry far beyond what was signed
            nonce, signature,
        )


def test_replayed_attestation_is_rejected(db, org_and_agent):
    org, _, _ = org_and_agent
    source, keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    signature = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce)
    fact_service.ingest_fact(db, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce, signature)

    with pytest.raises(fact_service.FactReplayError):
        fact_service.ingest_fact(db, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce, signature)


def test_revoked_source_cannot_ingest(db, org_and_agent):
    org, _, _ = org_and_agent
    source, keypair = _register_source(db, org.id)
    fact_service.revoke_fact_source(db, org.id, source.id)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    signature = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce)
    with pytest.raises(fact_service.FactSourceRevokedError):
        fact_service.ingest_fact(db, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce, signature)


# --- Resolution: trust rules -------------------------------------------------


def test_missing_fact_resolves_to_nothing(db, org_and_agent):
    org, _, _ = org_and_agent
    resolved = fact_service.resolve_facts(db, org.id, [("supplier-1", "supplier_approved")])
    assert resolved == []


def test_expired_fact_is_not_resolved(db, org_and_agent):
    org, _, _ = org_and_agent
    source, keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    already_expired = now - timedelta(minutes=1)
    nonce = uuid.uuid4().hex
    signature = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now - timedelta(hours=1), already_expired, nonce)
    fact_service.ingest_fact(db, org.id, source.id, "supplier-1", "supplier_approved", True, now - timedelta(hours=1), already_expired, nonce, signature)

    resolved = fact_service.resolve_facts(db, org.id, [("supplier-1", "supplier_approved")], now=now)
    assert resolved == []


def test_conflicting_current_facts_raise_rather_than_pick_one(db, org_and_agent):
    org, _, _ = org_and_agent
    source_a, keypair_a = _register_source(db, org.id)
    source_b, keypair_b = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=1)

    nonce_a = uuid.uuid4().hex
    sig_a = _sign_attestation(keypair_a, org.id, source_a.id, "supplier-1", "supplier_approved", True, now, expires, nonce_a)
    fact_service.ingest_fact(db, org.id, source_a.id, "supplier-1", "supplier_approved", True, now, expires, nonce_a, sig_a)

    nonce_b = uuid.uuid4().hex
    sig_b = _sign_attestation(keypair_b, org.id, source_b.id, "supplier-1", "supplier_approved", False, now, expires, nonce_b)
    fact_service.ingest_fact(db, org.id, source_b.id, "supplier-1", "supplier_approved", False, now, expires, nonce_b, sig_b)

    with pytest.raises(fact_service.FactConflictError):
        fact_service.resolve_facts(db, org.id, [("supplier-1", "supplier_approved")], now=now)


def test_cross_tenant_fact_is_never_resolved(db, org_and_agent):
    org, _, _ = org_and_agent
    other_org = Organization(id=uuid.uuid4(), name="Org B")
    db.add(other_org)
    db.commit()
    source, keypair = _register_source(db, other_org.id)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    signature = _sign_attestation(keypair, other_org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce)
    fact_service.ingest_fact(db, other_org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce, signature)

    resolved = fact_service.resolve_facts(db, org.id, [("supplier-1", "supplier_approved")], now=now)
    assert resolved == []


# --- Runtime integration: fail-closed, and real Evidence binding -----------


def test_correct_fact_reaches_policy_evaluation_and_allows(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True), Effect.ALLOW),
        opa_url,
    )
    source, keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    signature = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce)
    fact_service.ingest_fact(db, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce, signature)

    _, decision, evidence = _submit(db, agent, "vendor_payment", 9800.0, counterparty="supplier-1")
    assert decision.outcome == "ALLOW"
    assert evidence.payload["facts_evaluated"][0]["key"] == "supplier_approved"
    assert evidence.payload["facts_evaluated"][0]["value"] is True
    assert evidence.payload["facts_evaluated"][0]["subject"] == "supplier-1"
    assert evidence.payload["facts_evaluated"][0]["source_id"] == str(source.id)


def test_missing_fact_fails_closed_non_permissively(db, org_and_agent, opa_url):
    """A real, worth-documenting finding, not a defect: with only a
    single authored ALLOW policy for this scope, an unresolved
    (missing/expired/unattested) fact means its condition is never
    satisfied, so the compiled rule simply doesn't match -- and this
    platform's EXISTING, unmodified compiled-bundle default (bundle_
    builder.py/rego_generator.py, untouched by this milestone) resolves
    an unmatched scope to DENY, not HUMAN_REVIEW. Both are genuinely
    fail-closed (never a default ALLOW), but they are not the same
    outcome. An organization that specifically wants HUMAN_REVIEW for an
    unresolved fact must author a second, explicit require_human_review
    policy for the same scope -- exactly the existing authoring pattern
    already used for amount-threshold escalation
    (POLICY_INVOICE_REVIEW_OVER_50K alongside POLICY_PAY_INVOICE_UNDER_50K
    in the demo fixtures)."""
    org, _, agent = org_and_agent
    _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True), Effect.ALLOW),
        opa_url,
    )
    # No fact ever ingested for supplier-1 -- the condition can never be
    # satisfied.
    _, decision, _ = _submit(db, agent, "vendor_payment", 9800.0, counterparty="supplier-1")
    assert decision.outcome == "DENY"


def test_expired_fact_fails_closed_even_though_it_was_once_true(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True), Effect.ALLOW),
        opa_url,
    )
    source, keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    already_expired = now - timedelta(minutes=1)
    nonce = uuid.uuid4().hex
    signature = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now - timedelta(hours=1), already_expired, nonce)
    fact_service.ingest_fact(db, org.id, source.id, "supplier-1", "supplier_approved", True, now - timedelta(hours=1), already_expired, nonce, signature)

    # Same non-permissive-but-not-literally-HUMAN_REVIEW finding as
    # test_missing_fact_fails_closed_non_permissively above -- an
    # expired fact behaves identically to a never-ingested one, exactly
    # as intended (resolve_facts filters expiry at the SQL level, so
    # this decision never even sees the stale row).
    _, decision, _ = _submit(db, agent, "vendor_payment", 9800.0, counterparty="supplier-1")
    assert decision.outcome == "DENY"
