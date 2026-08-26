"""Issue #4 (Authorization Receipts): real-infrastructure tests (real
ephemeral OPA, real SQLite-backed models) for
authorization_receipt_service.get_authorization_receipt, matching the
established discipline in test_decision_explanation.py /
test_enterprise_facts.py / test_capability_tokens.py -- deliberately
duplicates those files' setup helpers rather than sharing a conftest, to
keep this new test file from risking their already-verified coverage
through a shared-fixture refactor.
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
from app.db.models import Agent, Base, FactSource, Organization, Principal
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64, sign_payload
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.schemas.authorization_receipt import AuthorizationReceiptResponse
from app.schemas.intent import CapabilitySummary
from app.services import (
    authorization_receipt_service as svc_receipt,
    capability_service,
    fact_service,
    intent_service,
    resolution_service,
    runtime_policy_service as svc,
    signing_key_service,
)

KEY_A_B64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
settings.evidence_signing_key_b64 = KEY_A_B64
settings.evidence_signing_key_id = "key-a"
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


@pytest.fixture(autouse=True)
def _reset_signing_key():
    """Several tests in this file rotate the active signing key -- reset
    to the module-default afterward so key rotation in one test can
    never leak into another test's expectations."""
    original_b64, original_id = settings.evidence_signing_key_b64, settings.evidence_signing_key_id
    yield
    settings.evidence_signing_key_b64, settings.evidence_signing_key_id = original_b64, original_id


def _policy(principal: str, action: str, condition: Condition, effect: Effect, policy_id: str | None = None) -> RuntimePolicy:
    return RuntimePolicy(
        id=policy_id or str(uuid.uuid4()), name=f"{action} policy", version=1, status=PolicyStatus.DRAFT,
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
    agent = Agent(id=uuid.uuid4(), name="AP-Invoice-Agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    return org, principal, agent


def _submit(db, agent, action, amount=None, currency=None, resource=None, counterparty=None, context=None):
    import time

    intent = decision = evidence = None
    for _attempt in range(6):
        intent, decision, evidence = intent_service.submit_intent(
            db, agent=agent, action=action, amount=amount, currency=currency, counterparty=counterparty,
            context=context or {}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex,
            correlation_id=None, resource=resource,
        )
        transient = decision.reason == "opa_timeout" or (decision.reason or "").startswith("opa_error:")
        if not transient:
            return intent, decision, evidence
        time.sleep(0.5)
    return intent, decision, evidence


def _receipt(db, decision_id, org_id) -> AuthorizationReceiptResponse:
    return svc_receipt.get_authorization_receipt(db, decision_id, org_id)


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


# --- 1/2. Field mapping + ALLOW ---------------------------------------------


def test_allow_receipt_field_mapping(db, org_and_agent, opa_url):
    """Everything the receipt claims must be traceable to a real record."""
    org, principal, agent = org_and_agent
    _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)
    intent, decision, evidence = _submit(db, agent, "vendor_payment", amount=9800.0, currency="USD", resource="invoice:INV-4821")
    assert decision.outcome == "ALLOW"

    receipt = _receipt(db, decision.id, org.id)

    assert receipt.receipt_id == evidence.id
    assert receipt.evidence_id == evidence.id
    assert receipt.decision.decision_id == decision.id
    assert receipt.decision.outcome == "ALLOW"
    assert receipt.decision.created_at == decision.created_at
    assert receipt.decision.source == intent.source

    assert receipt.actor.agent_id == agent.id
    assert receipt.actor.agent_name == "AP-Invoice-Agent"
    assert receipt.actor.principal_name == "alice"

    assert receipt.request.action == "vendor_payment"
    assert receipt.request.resource == "invoice:INV-4821"
    assert receipt.request.amount == 9800.0
    assert receipt.request.currency == "USD"

    assert receipt.authority.policy_id == decision.policy_id
    assert receipt.authority.bundle_hash == evidence.payload["policy_bundle_hash"]
    assert receipt.authority.bundle_version == evidence.payload["policy_version"]
    assert receipt.authority.authority_version == evidence.payload["authority_version"]

    assert receipt.evidence.evidence_id == evidence.id
    assert receipt.evidence.key_id == evidence.key_id
    assert receipt.evidence.signature == evidence.signature
    assert receipt.evidence.status == evidence.status

    assert receipt.verification.signature_valid is True
    assert receipt.verification.key_id == evidence.key_id

    assert receipt.facts == []
    assert receipt.human_review is None
    assert receipt.capability is None


# --- 3/4/5. DENY, HUMAN_REVIEW (pending + resolved) -------------------------


def test_deny_receipt(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)
    _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.GT, value=50000), Effect.DENY), opa_url)
    _, decision, evidence = _submit(db, agent, "vendor_payment", amount=75000.0, currency="USD")
    assert decision.outcome == "DENY"

    receipt = _receipt(db, decision.id, org.id)
    assert receipt.decision.outcome == "DENY"
    assert receipt.verification.signature_valid is True
    assert receipt.human_review is None


def test_human_review_receipt_pending(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    _deploy_policy(db, org.id, _policy("alice", "wire_transfer", Condition(field="amount", operator=Operator.GTE, value=10000), Effect.REQUIRE_HUMAN_REVIEW), opa_url)
    _, decision, _ = _submit(db, agent, "wire_transfer", amount=20000.0, currency="USD")
    assert decision.outcome == "HUMAN_REVIEW"

    receipt = _receipt(db, decision.id, org.id)
    assert receipt.decision.outcome == "HUMAN_REVIEW"
    assert receipt.human_review is None, "not yet resolved -- must not fabricate a resolution"


def test_human_review_receipt_resolved(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    _deploy_policy(db, org.id, _policy("alice", "wire_transfer", Condition(field="amount", operator=Operator.GTE, value=10000), Effect.REQUIRE_HUMAN_REVIEW), opa_url)
    _, decision, _ = _submit(db, agent, "wire_transfer", amount=20000.0, currency="USD")
    assert decision.outcome == "HUMAN_REVIEW"

    resolution_service.resolve_decision(
        db, decision_id=decision.id, organization_id=org.id, resolution="approved",
        resolved_by="Priya Chandrasekaran", reason="Confirmed with treasury.",
    )

    receipt = _receipt(db, decision.id, org.id)
    # The original Decision.outcome stays HUMAN_REVIEW historically --
    # the resolution lives in its own, separate object.
    assert receipt.decision.outcome == "HUMAN_REVIEW"
    assert receipt.human_review is not None
    assert receipt.human_review.resolution == "approved"
    assert receipt.human_review.resolved_by == "Priya Chandrasekaran"
    assert receipt.human_review.reason == "Confirmed with treasury."


def test_human_review_receipt_denied(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    _deploy_policy(db, org.id, _policy("alice", "wire_transfer", Condition(field="amount", operator=Operator.GTE, value=10000), Effect.REQUIRE_HUMAN_REVIEW), opa_url)
    _, decision, _ = _submit(db, agent, "wire_transfer", amount=20000.0, currency="USD")

    resolution_service.resolve_decision(
        db, decision_id=decision.id, organization_id=org.id, resolution="denied",
        resolved_by="Priya Chandrasekaran", reason="Outside delegated limit.",
    )

    receipt = _receipt(db, decision.id, org.id)
    assert receipt.human_review.resolution == "denied"


# --- 6. Historical policy version survives later deployments ---------------


def test_receipt_authority_survives_two_subsequent_redeploys(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=100000), Effect.ALLOW, policy_id=str(uuid.uuid4())), opa_url)
    _, decision, _ = _submit(db, agent, "vendor_payment", amount=500.0, currency="USD")
    assert decision.outcome == "ALLOW"

    original = _receipt(db, decision.id, org.id)
    assert original.authority.bundle_version == 1

    _redeploy_policy(db, org.id, policy_key, Condition(field="amount", operator=Operator.LTE, value=50000), opa_url)
    after_v2 = _receipt(db, decision.id, org.id)
    assert after_v2.authority.bundle_hash == original.authority.bundle_hash, "must still reference V1's bundle"
    assert after_v2.authority.policy_id == original.authority.policy_id
    assert after_v2.verification.signature_valid is True

    _redeploy_policy(db, org.id, policy_key, Condition(field="amount", operator=Operator.LTE, value=1), opa_url)
    after_v3 = _receipt(db, decision.id, org.id)
    assert after_v3.authority.bundle_hash == original.authority.bundle_hash, "must still reference V1's bundle, not V3's"
    assert after_v3.authority.policy_id == original.authority.policy_id
    assert after_v3.decision.outcome == "ALLOW", "the original decision's own outcome is untouched by later redeploys"


# --- 7/8. Trusted Enterprise Facts ------------------------------------------


def test_facts_appear_exactly_as_evaluated(db, org_and_agent, opa_url):
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

    _, decision, _ = _submit(db, agent, "vendor_payment", amount=9800.0, currency="USD", counterparty="supplier-1")
    assert decision.outcome == "ALLOW"

    receipt = _receipt(db, decision.id, org.id)
    assert len(receipt.facts) == 1
    fact = receipt.facts[0]
    assert fact.key == "supplier_approved"
    assert fact.value is True
    assert fact.subject == "supplier-1"
    assert fact.source_id == str(source.id)


def test_no_facts_evaluated_is_an_honest_empty_list(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)
    _, decision, _ = _submit(db, agent, "vendor_payment", amount=500.0, currency="USD")

    receipt = _receipt(db, decision.id, org.id)
    assert receipt.facts == [], "no fact was evaluated -- an honest empty list, never fabricated content"


# --- 9/10. Verification: tampering + key rotation ---------------------------


def test_tampered_evidence_fails_verification(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)
    _, decision, evidence = _submit(db, agent, "vendor_payment", amount=500.0, currency="USD")

    receipt_before = _receipt(db, decision.id, org.id)
    assert receipt_before.verification.signature_valid is True

    evidence.payload = {**evidence.payload, "amount": "999999.00"}
    db.add(evidence)
    db.commit()

    receipt_after = _receipt(db, decision.id, org.id)
    assert receipt_after.verification.signature_valid is False


def test_historical_signing_key_still_verifies_after_rotation(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    key_a_public = public_key_b64_from_signing_key_b64(KEY_A_B64)
    signing_key_service.ensure_current_key_registered(db, "key-a", key_a_public)

    _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)
    _, decision, evidence = _submit(db, agent, "vendor_payment", amount=500.0, currency="USD")
    assert evidence.key_id == "key-a"

    receipt_before_rotation = _receipt(db, decision.id, org.id)
    assert receipt_before_rotation.verification.signature_valid is True

    # Rotate: a brand-new keypair becomes the active signing key.
    key_b_signing = nacl.signing.SigningKey.generate()
    key_b_b64 = base64.b64encode(bytes(key_b_signing)).decode("ascii")
    key_b_public = base64.b64encode(bytes(key_b_signing.verify_key)).decode("ascii")
    settings.evidence_signing_key_b64 = key_b_b64
    settings.evidence_signing_key_id = "key-b"
    signing_key_service.ensure_current_key_registered(db, "key-b", key_b_public)

    receipt_after_rotation = _receipt(db, decision.id, org.id)
    assert receipt_after_rotation.verification.signature_valid is True, "rotation must not invalidate a historically-correct signature"
    assert receipt_after_rotation.verification.key_id == "key-a", "still verified against the key that actually signed it, not the now-active one"


# --- 11/12/13. Organisation isolation ---------------------------------------


def test_nonexistent_decision_raises(db, org_and_agent):
    org, _, _ = org_and_agent
    with pytest.raises(intent_service.DecisionNotFoundError):
        _receipt(db, uuid.uuid4(), org.id)


def test_receipt_cannot_expose_another_organisations_decision(db, opa_url):
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
    _, decision, _ = _submit(db, agent_a, "vendor_payment", amount=500.0, currency="USD")
    assert decision.outcome == "ALLOW"

    # Org A's own organisation can retrieve it.
    assert _receipt(db, decision.id, org_a.id).decision.decision_id == decision.id

    # Org B must see exactly the same failure a nonexistent decision
    # would produce -- never a signal that this decision exists at all.
    with pytest.raises(intent_service.CrossOrganizationAccessError):
        _receipt(db, decision.id, org_b.id)


# --- 14/15. Non-financial actions -------------------------------------------


def test_non_financial_action_receipt_has_no_amount_or_currency(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    _deploy_policy(db, org.id, _policy("alice", "disable_user", Condition(field="resource", operator=Operator.EQ, value="user:829"), Effect.ALLOW), opa_url)
    _, decision, _ = _submit(db, agent, "disable_user", amount=None, currency=None, resource="user:829")
    assert decision.outcome == "ALLOW"

    receipt = _receipt(db, decision.id, org.id)
    assert receipt.request.amount is None
    assert receipt.request.currency is None
    assert receipt.request.action == "disable_user"
    assert receipt.request.resource == "user:829"


# --- 16. Capability consumption is never rendered as execution -------------


def test_capability_consumption_never_renders_as_execution(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    signing_key_service.ensure_current_key_registered(db, "key-a", public_key_b64_from_signing_key_b64(KEY_A_B64))
    _deploy_policy(db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url)
    _, decision, _ = _submit(db, agent, "vendor_payment", amount=48000.0, currency="USD")
    assert decision.outcome == "ALLOW"

    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="sap-reference-adapter", issued_by="test")

    receipt_before_consume = _receipt(db, decision.id, org.id)
    assert receipt_before_consume.capability.issued is True
    assert receipt_before_consume.capability.consumed_at is None

    capability_service.verify_and_consume_capability(
        db, issued.token, "sap-reference-adapter", "vendor_payment", str(decision.intent_id),
        {"amount": "48000.00", "currency": "USD"},
    )

    receipt_after_consume = _receipt(db, decision.id, org.id)
    assert receipt_after_consume.capability.consumed_at is not None, "consumption is a recorded fact"

    # Structural guarantee, not just a naming convention: no field on the
    # receipt or its capability section claims execution happened.
    forbidden_substrings = ("executed", "execution")
    for field_name in AuthorizationReceiptResponse.model_fields:
        assert not any(s in field_name.lower() for s in forbidden_substrings), field_name
    for field_name in CapabilitySummary.model_fields:
        assert not any(s in field_name.lower() for s in forbidden_substrings), field_name
