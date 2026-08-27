"""PayReality 1.0 Audit finding G03: the Runtime Policy Simulator used
to hand-build its own OPA input and never resolved Trusted Enterprise
Facts at all -- a fact-gated policy simulated as if no facts existed,
silently diverging from what real Runtime Authority would actually
decide. These tests prove the fix by direct comparison: for the same
scenario, the Simulator's result must equal what a real
intent_service.submit_intent() call against the exact same deployed
policy actually decided -- not merely "look plausible" but be equal to
production truth, run alongside it as the reference.

Follows this codebase's established real-SQLite + real-ephemeral-OPA
integration test convention (test_enterprise_facts.py,
test_decision_security_boundary.py), reusing that file's own
db/org_and_agent/_policy/_deploy_policy/_register_source/
_sign_attestation helpers verbatim rather than re-deriving them.
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
from app.db.models import Agent, Base, Decision, Evidence, Intent, Organization, Principal
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


def _sim_input(counterparty=None):
    return sim_svc.SimulationInput(
        principal="alice", action="vendor_payment", amount=9800.0, currency="USD", counterparty=counterparty,
    )


# --- Parity: simulator must agree with what real Runtime Authority decided -


def test_simulator_matches_runtime_allow_with_valid_fact(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True), Effect.ALLOW),
        opa_url,
    )
    source, keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    signature = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce)
    fact_service.ingest_fact(db, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce, signature)

    _, real_decision, _ = _submit(db, agent, "vendor_payment", 9800.0, counterparty="supplier-1")
    assert real_decision.outcome == "ALLOW"

    result = sim_svc.simulate(db, policy_key, _sim_input(counterparty="supplier-1"), org.id, opa_url=opa_url)
    assert result.decision == "ALLOW" == real_decision.outcome
    assert result.facts_evaluated == {"supplier_approved": True}
    assert result.warnings == []


def test_simulator_matches_runtime_deny_with_missing_fact(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True), Effect.ALLOW),
        opa_url,
    )
    _, real_decision, _ = _submit(db, agent, "vendor_payment", 9800.0, counterparty="supplier-with-no-fact")

    result = sim_svc.simulate(db, policy_key, _sim_input(counterparty="supplier-with-no-fact"), org.id, opa_url=opa_url)
    assert result.decision == real_decision.outcome == "DENY"
    assert result.facts_evaluated == {}
    # A genuinely-looked-up-and-not-found fact is not the "no counterparty
    # given" case -- no warning, this is real production truth, not a
    # simulation limitation.
    assert result.warnings == []


def test_simulator_matches_runtime_deny_with_expired_fact(db, org_and_agent, opa_url):
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
    signature = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now - timedelta(hours=1), already_expired, nonce)
    fact_service.ingest_fact(db, org.id, source.id, "supplier-1", "supplier_approved", True, now - timedelta(hours=1), already_expired, nonce, signature)

    _, real_decision, _ = _submit(db, agent, "vendor_payment", 9800.0, counterparty="supplier-1")

    result = sim_svc.simulate(db, policy_key, _sim_input(counterparty="supplier-1"), org.id, opa_url=opa_url)
    assert result.decision == real_decision.outcome == "DENY"
    assert result.facts_evaluated == {}


def test_simulator_matches_runtime_deny_with_conflicting_facts(db, org_and_agent, opa_url):
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

    result = sim_svc.simulate(db, policy_key, _sim_input(counterparty="supplier-conflict"), org.id, opa_url=opa_url)
    assert result.decision == real_decision.outcome == "DENY"
    assert result.facts_evaluated == {}
    # A conflict is real, resolved, production-matching fail-closed
    # behavior (same FactConflictError -> [] fallback intent_service
    # itself uses) -- not a simulation limitation, so no warning.
    assert result.warnings == []


def test_simulator_unaffected_by_facts_for_a_policy_that_does_not_reference_any(db, org_and_agent, opa_url):
    """An ordinary policy with no enterprise_knowledge.* condition must
    behave exactly as it did before this milestone -- no fact lookup
    attempted, no warning produced, no behavior change."""
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="amount", operator=Operator.LTE, value=50000), Effect.ALLOW),
        opa_url,
    )
    _, real_decision, _ = _submit(db, agent, "vendor_payment", 9800.0)

    result = sim_svc.simulate(db, policy_key, _sim_input(counterparty=None), org.id, opa_url=opa_url)
    assert result.decision == real_decision.outcome == "ALLOW"
    assert result.facts_evaluated == {}
    assert result.warnings == []


# --- Visible limitation, never a silent guess -------------------------------


def test_simulator_warns_instead_of_silently_guessing_when_no_counterparty_given(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True), Effect.ALLOW),
        opa_url,
    )

    result = sim_svc.simulate(db, policy_key, _sim_input(counterparty=None), org.id, opa_url=opa_url)
    # Fails closed exactly like a genuinely-missing fact would (the
    # referencing rule simply never matches) -- but WHY is now visible.
    assert result.decision == "DENY"
    assert result.facts_evaluated == {}
    assert len(result.warnings) == 1
    assert "no counterparty" in result.warnings[0]


# --- Side-effect isolation: the simulator must never write real state ------


def test_simulate_of_a_fact_gated_policy_writes_no_real_intent_decision_or_evidence(db, org_and_agent, opa_url):
    org, _, agent = org_and_agent
    policy_key = _deploy_policy(
        db, org.id,
        _policy("alice", "vendor_payment", Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True), Effect.ALLOW),
        opa_url,
    )
    source, keypair = _register_source(db, org.id)
    now = datetime.now(timezone.utc)
    nonce = uuid.uuid4().hex
    signature = _sign_attestation(keypair, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce)
    fact_service.ingest_fact(db, org.id, source.id, "supplier-1", "supplier_approved", True, now, now + timedelta(hours=1), nonce, signature)

    for _ in range(3):
        sim_svc.simulate(db, policy_key, _sim_input(counterparty="supplier-1"), org.id, opa_url=opa_url)

    assert db.scalars(select(Intent)).all() == []
    assert db.scalars(select(Decision)).all() == []
    assert db.scalars(select(Evidence)).all() == []
