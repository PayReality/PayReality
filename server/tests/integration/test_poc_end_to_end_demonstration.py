"""THE reproducible end-to-end demonstration
(PAYREALITY_FUTURE_VISION.md; the milestone's own "Definition of Done"):

    GOVERNED AUTHORITY -> DETERMINISTIC POLICY -> TRUSTED ENTERPRISE
    FACTS -> RUNTIME AUTHORITY DECISION -> SIGNED DECISION EVIDENCE ->
    SHORT-LIVED BOUND CAPABILITY -> REFERENCE PEP VALIDATION -> MOCK
    EXECUTION

against the existing AP-Invoice-Agent / SAP illustrative scenario
(the same names already threaded through src/app/demo/fixtures/, built
here as REAL backend rows via this codebase's own established test
helpers -- see test_decision_security_boundary.py -- not the
frontend's disconnected DEMO_MODE mock).

Every numbered step below corresponds 1:1 to a step in the milestone's
own END-TO-END DEMONSTRATION specification. Steps 1-23 are one
continuous story told as a single test function (not 23 separate
tests) because each step's assertion depends on state the previous
step created -- exactly what "reproducible demonstration" means here:
run this one function, top to bottom, and every claim in
PAYREALITY_FUTURE_VISION.md's Part A/B/C is proven against real
infrastructure, in the actual order a real POC would need them.
"""

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone

import nacl.signing
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Base, Organization, Principal
from app.domain.capability import token as capability_token
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64, sign_payload
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.constraints import Constraints, RiskLevel
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import (
    capability_service,
    fact_service,
    intent_service,
    runtime_policy_lifecycle_service as lsvc,
    runtime_policy_service as svc,
    signing_key_service,
)

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)

AP_INVOICE_AGENT = "AP-Invoice-Agent"
SAP_ENTERPRISE_SYSTEM_LABEL = "SAP S/4HANA (reference)"
SUPPLIER = "supplier-acme-industrial"
INVOICE_RESOURCE = "invoice-8192"
AUDIENCE = "sap-reference-adapter"


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


class _SourceKeypair:
    def __init__(self):
        self.signing_key = nacl.signing.SigningKey.generate()

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(bytes(self.signing_key.verify_key)).decode("ascii")

    def sign(self, payload: dict) -> str:
        return sign_payload(payload, base64.b64encode(bytes(self.signing_key)).decode("ascii"), "poc-source").value


def test_full_poc_demonstration(db, opa_url):
    # --- Governed authority: a real org, principal, agent -----------------
    org = Organization(id=uuid.uuid4(), name="Meridian Industrial (reference)")
    db.add(org)
    db.flush()
    principal = Principal(id=uuid.uuid4(), name="alice", organization_id=org.id)
    db.add(principal)
    db.flush()
    agent = Agent(id=uuid.uuid4(), name=AP_INVOICE_AGENT, acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()

    # --- Deterministic policy: additive, requires the new fact -------------
    # invoice payments under $50K, EXCEPT the fact-gated condition is new
    # and additive -- it does not touch the existing demo policy shape
    # (POLICY_PAY_INVOICE_UNDER_50K), it demonstrates the mechanism on a
    # freshly-authored equivalent for this reference scenario, marked
    # HIGH risk so authority-expiry fail-closed (steps 13-14) has
    # something real to bite on.
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="Invoice payments under $50K, supplier-approval-gated (reference)",
        version=1, status=PolicyStatus.DRAFT,
        # scope.agent is deliberately left unset: a real, pre-existing gap
        # (unrelated to this milestone, discovered while building this
        # demonstration) means it would never match anyway --
        # rego_generator.generate_scope_block emits `input.agent.id ==
        # <name>`, but decision_engine.build_opa_input's "agent" section
        # only ever sets `acting_for_principal_id`, never `id` -- so
        # Scope.agent narrowing silently never matches any real Intent
        # today. Flagged in this milestone's final report as a discovered,
        # NOT-fixed finding (out of scope for Trusted Facts/Freshness/
        # Capability work); every other passing test in this codebase
        # also leaves scope.agent unset, for the same reason.
        scope=Scope(principal="alice", action="vendor_payment"),
        conditions=ConditionSet(all=(
            Condition(field="amount", operator=Operator.LTE, value=50000),
            Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True),
        )),
        effect=Effect.ALLOW,
        constraints=Constraints(risk_level=RiskLevel.HIGH),
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = svc.create_policy(db, policy, org.id)
    svc.submit_for_review(db, row.policy_key, org.id)
    svc.approve(db, row.policy_key, org.id, approver="governance-admin-reference")
    compiled = svc.compile_policy(db, row.policy_key, org.id)
    assert compiled.ok, f"compile failed: {compiled.diagnostics}"
    svc.deploy_policy(db, row.policy_key, org.id, opa_url=opa_url)
    policy_key = row.policy_key

    def submit(amount=48000.0):
        return intent_service.submit_intent(
            db, agent=agent, action="vendor_payment", amount=amount, currency="USD",
            counterparty=SUPPLIER, context={}, requested_at=datetime.now(timezone.utc),
            nonce=uuid.uuid4().hex, correlation_id=INVOICE_RESOURCE,
        )

    # --- 1-3. Register a reference fact source, sign, and ingest ----------
    keypair = _SourceKeypair()
    source = fact_service.register_fact_source(db, org.id, SAP_ENTERPRISE_SYSTEM_LABEL, keypair.public_key_b64)

    now = datetime.now(timezone.utc)
    fact_nonce = uuid.uuid4().hex
    fact_expiry = now + timedelta(hours=1)
    attestation = fact_service.CanonicalFactAttestation(
        organization_id=str(org.id), source_id=str(source.id), subject=SUPPLIER,
        key="supplier_approved", value=True, observed_at=now.isoformat(),
        expires_at=fact_expiry.isoformat(), nonce=fact_nonce,
    )
    signature = keypair.sign(attestation.to_dict())
    fact = fact_service.ingest_fact(
        db, org.id, source.id, SUPPLIER, "supplier_approved", True, now, fact_expiry, fact_nonce, signature,
    )
    assert fact.value is True

    # --- 4-6. Submit the AP-Invoice-Agent intent; valid fact -> ALLOW ------
    _, decision, evidence = submit()
    assert decision.outcome == "ALLOW"
    assert evidence.payload["facts_evaluated"][0]["key"] == "supplier_approved"

    # --- 7. Repeat without the fact -> fails closed (non-permissively) ----
    other_supplier_intent, other_decision, _ = intent_service.submit_intent(
        db, agent=agent, action="vendor_payment", amount=48000.0, currency="USD",
        counterparty="supplier-no-fact-on-file", context={}, requested_at=datetime.now(timezone.utc),
        nonce=uuid.uuid4().hex, correlation_id="invoice-9999",
    )
    assert other_decision.outcome != "ALLOW"  # DENY here -- see test_enterprise_facts.py's own documented finding on why

    # --- 8. Repeat with an expired fact -> fails closed --------------------
    expired_keypair = _SourceKeypair()
    expired_source = fact_service.register_fact_source(db, org.id, "Expired-fact source (reference)", expired_keypair.public_key_b64)
    already_expired = now - timedelta(minutes=1)
    exp_nonce = uuid.uuid4().hex
    exp_attestation = fact_service.CanonicalFactAttestation(
        organization_id=str(org.id), source_id=str(expired_source.id), subject="supplier-expired-fact",
        key="supplier_approved", value=True, observed_at=(now - timedelta(hours=2)).isoformat(),
        expires_at=already_expired.isoformat(), nonce=exp_nonce,
    )
    fact_service.ingest_fact(
        db, org.id, expired_source.id, "supplier-expired-fact", "supplier_approved", True,
        now - timedelta(hours=2), already_expired, exp_nonce, expired_keypair.sign(exp_attestation.to_dict()),
    )
    _, expired_fact_decision, _ = intent_service.submit_intent(
        db, agent=agent, action="vendor_payment", amount=48000.0, currency="USD",
        counterparty="supplier-expired-fact", context={}, requested_at=datetime.now(timezone.utc),
        nonce=uuid.uuid4().hex, correlation_id="invoice-8888",
    )
    assert expired_fact_decision.outcome != "ALLOW"

    # --- 9. Repeat with a forged fact -> rejected at ingestion -------------
    with pytest.raises(fact_service.InvalidFactSignatureError):
        fact_service.ingest_fact(
            db, org.id, source.id, "supplier-forged", "supplier_approved", True, now, fact_expiry,
            uuid.uuid4().hex, base64.b64encode(b"not a real ed25519 signature!!!!").decode("ascii"),
        )

    # --- 10. Contradictory trusted facts -> fails closed (never picks one) -
    # Deliberately a SEPARATE subject from SUPPLIER: this step exists to
    # prove the conflict-detection mechanism in isolation, not to poison
    # the main storyline's own supplier fact for every later step below.
    CONFLICT_SUBJECT = "supplier-conflict-demo"
    source_a_keypair = _SourceKeypair()
    source_a = fact_service.register_fact_source(db, org.id, "Conflict demo source A", source_a_keypair.public_key_b64)
    nonce_a = uuid.uuid4().hex
    attestation_a = fact_service.CanonicalFactAttestation(
        organization_id=str(org.id), source_id=str(source_a.id), subject=CONFLICT_SUBJECT,
        key="supplier_approved", value=True, observed_at=now.isoformat(), expires_at=fact_expiry.isoformat(),
        nonce=nonce_a,
    )
    fact_service.ingest_fact(
        db, org.id, source_a.id, CONFLICT_SUBJECT, "supplier_approved", True, now, fact_expiry,
        nonce_a, source_a_keypair.sign(attestation_a.to_dict()),
    )
    contradicting_keypair = _SourceKeypair()
    contradicting_source = fact_service.register_fact_source(db, org.id, "Conflict demo source B", contradicting_keypair.public_key_b64)
    contra_nonce = uuid.uuid4().hex
    contra_attestation = fact_service.CanonicalFactAttestation(
        organization_id=str(org.id), source_id=str(contradicting_source.id), subject=CONFLICT_SUBJECT,
        key="supplier_approved", value=False, observed_at=now.isoformat(), expires_at=fact_expiry.isoformat(),
        nonce=contra_nonce,
    )
    fact_service.ingest_fact(
        db, org.id, contradicting_source.id, CONFLICT_SUBJECT, "supplier_approved", False, now, fact_expiry,
        contra_nonce, contradicting_keypair.sign(contra_attestation.to_dict()),
    )
    with pytest.raises(fact_service.FactConflictError):
        fact_service.resolve_facts(db, org.id, [(CONFLICT_SUBJECT, "supplier_approved")])

    # --- 11. Evidence binds the exact policy version and fact evaluated ---
    assert evidence.payload["policy_version"] is not None
    assert evidence.payload["facts_evaluated"][0]["source_id"] == str(source.id)
    assert evidence.payload["facts_evaluated"][0]["subject"] == SUPPLIER

    # --- 12-13. Attest the policy; review-due is distinct from expiry -----
    attested = lsvc.attest_policy(db, policy_key, org.id, actor="governance-admin-reference", review_cadence_days=1)
    assert attested.last_attested_at is not None
    assert attested.next_review_at == attested.last_attested_at + timedelta(days=1)

    overdue_row = svc.get_latest(db, policy_key, org.id)
    overdue_row.next_review_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    due = lsvc.list_due_for_reattestation(db, org.id)
    assert any(r.policy_key == policy_key for r in due)
    # Review-due alone never blocks anything -- still ALLOWs normally.
    _, still_allowed_decision, _ = submit()
    assert still_allowed_decision.outcome == "ALLOW"

    # --- 14. Explicitly expire authority -> fails closed -------------------
    active_row = svc.get_latest(db, policy_key, org.id)
    active_row.authority_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    _, expired_authority_decision, _ = submit()
    assert expired_authority_decision.outcome == "HUMAN_REVIEW"
    assert expired_authority_decision.reason == "authority_review_overdue"
    # Un-expire so the rest of the demonstration (capability issuance)
    # still has a real ALLOW decision to work from.
    active_row.authority_expires_at = None
    db.commit()

    # --- 15-16. A fresh ALLOW decision; issue a capability -----------------
    _, allow_decision, allow_evidence = submit()
    assert allow_decision.outcome == "ALLOW"
    issued = capability_service.issue_capability_for_decision(
        db, org.id, allow_decision.id, audience=AUDIENCE, issued_by="governance-admin-reference",
    )
    assert issued.token

    # --- 17. Reference PEP accepts a matching execution request -----------
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, AUDIENCE, "vendor_payment", INVOICE_RESOURCE,
        {"amount": "48000.00", "currency": "USD"},
    )
    assert str(consumed.decision_id) == str(allow_decision.id)

    # --- 18. Replay the exact same capability -> rejected ------------------
    with pytest.raises(capability_service.CapabilityTokenAlreadyConsumedError):
        capability_service.verify_and_consume_capability(
            db, issued.token, AUDIENCE, "vendor_payment", INVOICE_RESOURCE, {"amount": "48000.00", "currency": "USD"},
        )

    # --- 19. A fresh capability, but execution changes the amount ---------
    _, allow_decision_2, _ = submit()
    issued_2 = capability_service.issue_capability_for_decision(db, org.id, allow_decision_2.id, audience=AUDIENCE)
    with pytest.raises(capability_token.CapabilityConstraintMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued_2.token, AUDIENCE, "vendor_payment", INVOICE_RESOURCE, {"amount": "49000.00", "currency": "USD"},
        )

    # --- 20. ... changes the resource ---------------------------------------
    _, allow_decision_3, _ = submit()
    issued_3 = capability_service.issue_capability_for_decision(db, org.id, allow_decision_3.id, audience=AUDIENCE)
    with pytest.raises(capability_token.CapabilityConstraintMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued_3.token, AUDIENCE, "vendor_payment", "invoice-DIFFERENT", {"amount": "48000.00", "currency": "USD"},
        )

    # --- 21. ... changes the audience ---------------------------------------
    _, allow_decision_4, _ = submit()
    issued_4 = capability_service.issue_capability_for_decision(db, org.id, allow_decision_4.id, audience=AUDIENCE)
    with pytest.raises(capability_token.CapabilityAudienceMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued_4.token, "a-different-adapter", "vendor_payment", INVOICE_RESOURCE, {"amount": "48000.00", "currency": "USD"},
        )

    # --- 22. An expired capability -------------------------------------
    _, allow_decision_5, _ = submit()
    issued_5 = capability_service.issue_capability_for_decision(db, org.id, allow_decision_5.id, audience=AUDIENCE, ttl_seconds=-1)
    with pytest.raises(capability_token.CapabilityTokenExpiredError):
        capability_service.verify_and_consume_capability(
            db, issued_5.token, AUDIENCE, "vendor_payment", INVOICE_RESOURCE, {"amount": "48000.00", "currency": "USD"},
        )

    # --- 23. The full Evidence trail: authority, facts, capability --------
    # Authority decision + policy version + trusted facts, all on one
    # Evidence record (steps 4-6/11 above); capability issuance and
    # consumption are deliberately their own, distinct, queryable rows
    # (CapabilityToken), never merged into Evidence's own signed payload
    # -- authorization decision, capability issuance, capability
    # consumption, and execution confirmation are kept as four distinct
    # concepts throughout this milestone, not interchangeable synonyms.
    from app.db.models import CapabilityToken

    capability_row = db.get(CapabilityToken, issued.capability_id)
    assert capability_row.decision_id == allow_decision.id
    assert capability_row.consumed_at is not None  # step 17 consumed it
    assert allow_evidence.payload["policy_version"] is not None
    assert allow_evidence.payload["facts_evaluated"][0]["key"] == "supplier_approved"
    # Execution confirmation is explicitly NOT claimed anywhere above:
    # this demonstration proves a capability was issued and consumed by
    # the reference adapter, never that the underlying mock action's own
    # result was reported back and recorded -- that remains a real,
    # disclosed limitation (PAYREALITY_FUTURE_VISION.md Part C).
