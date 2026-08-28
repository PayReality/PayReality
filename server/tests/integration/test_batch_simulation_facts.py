"""PayReality 1.0 Audit finding G03, Batch Simulation half (verification-
closure pass): run_batch previously hand-built its own OPA input,
exactly like simulate() used to, with the identical Trusted Enterprise
Facts gap -- a fact-gated policy replayed every CSV row as though no
facts existed at all. Fixed the same way simulate() was fixed: reuse
build_opa_input/fact_service.resolve_facts, plus a new, minimal
`counterparty`/`vendor` CSV column (Option A, true parity) with an
explicit, non-silent CANNOT_SIMULATE outcome for a row that needs a
fact but has no subject to resolve it against (Option B).

Follows this codebase's established real-SQLite + real-ephemeral-OPA
integration test convention, reusing test_enterprise_facts.py's own
db/org_and_agent/_policy/_deploy_policy/_register_source/
_sign_attestation helpers verbatim.
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
from app.db.models import (
    Agent, Base, CapabilityToken, Decision, Evidence, Intent, Organization, Principal,
)
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import sign_payload
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import fact_service, intent_service, policy_simulation_service as sim_svc
from app.services import runtime_policy_service as svc

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


def _submit(db, agent, action, amount, counterparty=None):
    return intent_service.submit_intent(
        db, agent=agent, action=action, amount=amount, currency="USD", counterparty=counterparty,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
    )


class _SourceKeypair:
    def __init__(self):
        self.signing_key = nacl.signing.SigningKey.generate()

    @property
    def public_key_b64(self) -> str:
        return base64.b64encode(bytes(self.signing_key.verify_key)).decode("ascii")

    def sign(self, payload: dict) -> str:
        return sign_payload(payload, base64.b64encode(bytes(self.signing_key)).decode("ascii"), "test-source").value


def _register_source(db, org_id):
    keypair = _SourceKeypair()
    source = fact_service.register_fact_source(db, org_id, "SAP S/4HANA (reference)", keypair.public_key_b64)
    return source, keypair


def _sign_attestation(keypair, org_id, source_id, subject, key, value, observed_at, expires_at, nonce) -> str:
    attestation = fact_service.CanonicalFactAttestation(
        organization_id=str(org_id), source_id=str(source_id), subject=subject, key=key, value=value,
        observed_at=observed_at.isoformat(), expires_at=expires_at.isoformat(), nonce=nonce,
    )
    return keypair.sign(attestation.to_dict())


def _row(principal="alice", action="vendor_payment", amount=9800.0, counterparty=None):
    row = {"principal": principal, "action": action, "amount": amount}
    if counterparty is not None:
        row["counterparty"] = counterparty
    return row


# --- 1. Ordinary, non-TEF policy: unchanged behavior ------------------------


def test_non_tef_policy_batch_simulation_unaffected(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id, _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW), opa_url,
    )
    result = sim_svc.run_batch(db, policy_key, [_row(amount=100.0), _row(amount=999999.0)], org.id, opa_url=opa_url)
    assert result.cannot_simulate == 0
    assert result.allowed == 1
    assert result.denied == 1


# --- 2/4/5/6. TEF-gated policy: parity with live runtime --------------------


def test_batch_matches_runtime_with_a_valid_fact_and_a_counterparty_given(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True), Effect.ALLOW),
        opa_url,
    )
    source, keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    sig = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce)
    fact_service.ingest_fact(db, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce, sig)

    _, real_decision, _ = _submit(db, agent, "vendor_payment", 9800.0, counterparty="supplier-1")
    assert real_decision.outcome == "ALLOW"

    result = sim_svc.run_batch(db, policy_key, [_row(counterparty="supplier-1")], org.id, opa_url=opa_url)
    assert result.cannot_simulate == 0
    assert result.allowed == 1 and real_decision.outcome == "ALLOW"


def test_batch_matches_runtime_deny_with_missing_fact_but_counterparty_given(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True), Effect.ALLOW),
        opa_url,
    )
    _, real_decision, _ = _submit(db, agent, "vendor_payment", 9800.0, counterparty="supplier-no-fact")
    assert real_decision.outcome == "DENY"

    result = sim_svc.run_batch(db, policy_key, [_row(counterparty="supplier-no-fact")], org.id, opa_url=opa_url)
    assert result.cannot_simulate == 0
    assert result.denied == 1, "a genuinely-looked-up-and-not-found fact is real parity, not a limitation"


def test_batch_matches_runtime_deny_with_expired_fact(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True), Effect.ALLOW),
        opa_url,
    )
    source, keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    already_expired = now - timedelta(minutes=1)
    nonce = uuid.uuid4().hex
    sig = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now - timedelta(hours=1), already_expired, nonce)
    fact_service.ingest_fact(db, org.id, source.id, "supplier-1", "supplier_approved", True, now - timedelta(hours=1), already_expired, nonce, sig)

    _, real_decision, _ = _submit(db, agent, "vendor_payment", 9800.0, counterparty="supplier-1")
    assert real_decision.outcome == "DENY"

    result = sim_svc.run_batch(db, policy_key, [_row(counterparty="supplier-1")], org.id, opa_url=opa_url)
    assert result.cannot_simulate == 0
    assert result.denied == 1


def test_batch_matches_runtime_deny_with_conflicting_facts(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True), Effect.ALLOW),
        opa_url,
    )
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=1)
    source_a, keypair_a = _register_source(db, org.id)
    nonce_a = uuid.uuid4().hex
    sig_a = _sign_attestation(keypair_a, org.id, source_a.id, "supplier-conflict", "supplier_approved", True, now, expires, nonce_a)
    fact_service.ingest_fact(db, org.id, source_a.id, "supplier-conflict", "supplier_approved", True, now, expires, nonce_a, sig_a)
    source_b, keypair_b = _register_source(db, org.id)
    nonce_b = uuid.uuid4().hex
    sig_b = _sign_attestation(keypair_b, org.id, source_b.id, "supplier-conflict", "supplier_approved", False, now, expires, nonce_b)
    fact_service.ingest_fact(db, org.id, source_b.id, "supplier-conflict", "supplier_approved", False, now, expires, nonce_b, sig_b)

    _, real_decision, _ = _submit(db, agent, "vendor_payment", 9800.0, counterparty="supplier-conflict")
    assert real_decision.outcome == "DENY"

    result = sim_svc.run_batch(db, policy_key, [_row(counterparty="supplier-conflict")], org.id, opa_url=opa_url)
    assert result.cannot_simulate == 0
    assert result.denied == 1


# --- 3. TEF-gated policy, no counterparty given: explicit, non-silent limit -


def test_batch_row_without_counterparty_is_marked_cannot_simulate_not_silently_guessed(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True), Effect.ALLOW),
        opa_url,
    )
    result = sim_svc.run_batch(db, policy_key, [_row()], org.id, opa_url=opa_url)  # no counterparty column
    assert result.cannot_simulate == 1
    assert result.allowed == 0 and result.denied == 0 and result.escalated == 0 and result.errors == 0
    row = result.sample_rows[0]
    assert row.decision is None
    assert row.limitation is not None and "counterparty" in row.limitation


def test_batch_mixed_rows_only_flags_the_ones_missing_a_counterparty(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True), Effect.ALLOW),
        opa_url,
    )
    source, keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    sig = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce)
    fact_service.ingest_fact(db, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce, sig)

    rows = [_row(counterparty="supplier-1"), _row(), _row(counterparty="supplier-no-fact")]
    result = sim_svc.run_batch(db, policy_key, rows, org.id, opa_url=opa_url)
    assert result.total == 3
    assert result.cannot_simulate == 1
    assert result.allowed == 1
    assert result.denied == 1


# --- 7. No real side effects -------------------------------------------------


def test_batch_simulation_creates_no_real_side_effects(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True), Effect.ALLOW),
        opa_url,
    )
    source, keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    sig = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce)
    fact_service.ingest_fact(db, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce, sig)

    rows = [_row(counterparty="supplier-1"), _row(), _row(counterparty="supplier-no-fact")] * 5
    sim_svc.run_batch(db, policy_key, rows, org.id, opa_url=opa_url)

    assert db.scalars(select(Intent)).all() == []
    assert db.scalars(select(Decision)).all() == []
    assert db.scalars(select(Evidence)).all() == []
    assert db.scalars(select(CapabilityToken)).all() == []
