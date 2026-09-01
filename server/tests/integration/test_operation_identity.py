"""Trusted Integration Architecture, Phase 3: business-operation
identity for the trusted-Adapter runtime path. Real SQLite + real
ephemeral OPA throughout (this codebase's own established convention --
see test_integration_runtime_path.py, test_enterprise_facts.py), never
mocked at the authorization-boundary level. Real-PostgreSQL concurrency
proofs live in test_operation_identity_concurrency.py, not here.
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
from app.services import (
    authorization_receipt_service,
    capability_service,
    enforcement_binding_service as binding_svc,
    fact_service,
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
    integration_runtime_service as runtime_svc,
    intent_service,
    operation_identity_service,
    runtime_policy_service as policy_svc,
)
from app.services.integration_runtime_service import (
    AdapterReplayDetectedError,
    ExternalOperationConflictError,
    IntegrationRejectionError,
)

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


def _org(db, name="Org A"):
    org = Organization(id=uuid.uuid4(), name=name)
    db.add(org)
    db.commit()
    return org


def _principal(db, org_id, name="alice"):
    principal = Principal(id=uuid.uuid4(), name=name, organization_id=org_id)
    db.add(principal)
    db.commit()
    return principal


def _agent(db, principal_id, name="AP Invoice Agent", status="active"):
    agent = Agent(id=uuid.uuid4(), name=name, acting_for_principal_id=principal_id, status=status)
    db.add(agent)
    db.commit()
    return agent


def _deploy_policy(db, org_id, opa_url, policy_key=None, effect=Effect.ALLOW, action="vendor_payment",
                    resource="supplier:123", principal="alice", condition=None):
    policy = RuntimePolicy(
        id=str(policy_key) if policy_key else str(uuid.uuid4()), name="test policy", version=1,
        status=PolicyStatus.DRAFT, scope=Scope(principal=principal, action=action, resource=resource),
        conditions=ConditionSet(all=(condition,) if condition else ()), effect=effect,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row.policy_key


def _redeploy_new_version(db, org_id, opa_url, policy_key, effect, action="vendor_payment",
                           resource="supplier:123", principal="alice", condition=None):
    """A real new version of the SAME policy_key -- edit_policy ->
    submit_for_review -> approve -> compile -> deploy, exactly the
    lifecycle Policy Studio itself uses, proving section 8's "retry
    after a real policy change" scenario against genuinely different,
    genuinely redeployed authority, not a stand-in."""
    updated = RuntimePolicy(
        id=str(policy_key), name="test policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal=principal, action=action, resource=resource),
        conditions=ConditionSet(all=(condition,) if condition else ()), effect=effect,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.edit_policy(db, policy_key, org_id, updated)
    policy_svc.submit_for_review(db, policy_key, org_id)
    policy_svc.approve(db, policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, policy_key, org_id, opa_url=opa_url)
    return row


def _setup(db, org_id, resource_path="supplier.id", amount_path=None, currency_path=None,
           fact_subject_path=None, context_bindings=None, environment="production",
           integration=None, extra_agent=False):
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "Reference SAP Adapter", "ed25519:base64:AAAA")
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)

    if integration is None:
        integration = contract_svc.create_integration(db, org_id, "SAP S/4HANA (reference)")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, "ChangeSupplierBankDetails", "vendor_payment",
        resource_path=resource_path, amount_path=amount_path, currency_path=currency_path,
        fact_subject_path=fact_subject_path, context_bindings=context_bindings or {},
    )
    contract_version = contract_svc.validate_contract_version(db, contract_version.id, org_id)
    contract_version = contract_svc.approve_contract_version(db, contract_version.id, org_id, approver="governance-admin@example.com")

    principal = _principal(db, org_id)
    agent = _agent(db, principal.id)
    agent_ids = [agent.id]
    second_agent = None
    if extra_agent:
        second_agent = _agent(db, principal.id, "Second Allowed Agent")
        agent_ids.append(second_agent.id)
    binding = binding_svc.create_draft_binding(
        db, org_id, identity.id, contract_version.id, environment, agent_ids=agent_ids,
    )
    binding = binding_svc.activate_binding(db, binding.id, org_id)
    return identity, integration, contract_version, binding, agent, second_agent


def _attest(db, identity, binding, agent, *, source_operation="ChangeSupplierBankDetails", action="vendor_payment",
            resource="supplier:123", amount=None, currency=None, counterparty=None, context=None, nonce=None,
            external_operation_id="OP-1"):
    return runtime_svc.submit_attested_intent(
        db, identity,
        enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=source_operation, action=action, resource=resource,
        amount=amount, currency=currency, counterparty=counterparty,
        context=context or {}, requested_at=datetime.now(timezone.utc),
        nonce=nonce or uuid.uuid4().hex, correlation_id=None,
        external_operation_id=external_operation_id,
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


def _ingest_fact(db, org_id, source, keypair, subject, key, value, nonce=None):
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=1)
    attestation = fact_service.CanonicalFactAttestation(
        organization_id=str(org_id), source_id=str(source.id), subject=subject, key=key, value=value,
        observed_at=now.isoformat(), expires_at=expires_at.isoformat(), nonce=nonce or uuid.uuid4().hex,
    )
    signature = keypair.sign(attestation.to_dict())
    return fact_service.ingest_fact(
        db, org_id, source.id, subject, key, value, now, expires_at, attestation.nonce, signature,
    )


def _count_calls(monkeypatch, module, attr_name):
    original = getattr(module, attr_name)
    counter = {"n": 0}

    def wrapper(*args, **kwargs):
        counter["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(module, attr_name, wrapper)
    return counter


# --- Basic semantics (sections 7, 40.1-40.4) --------------------------------


def test_new_operation_creates_one_decision(db, opa_url):
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    intent, decision, evidence = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    assert decision.outcome == "ALLOW"
    assert intent.external_operation_id == "OP-1"
    assert intent.canonical_operation_fingerprint is not None


def test_matching_retry_returns_same_decision_id(db, opa_url):
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    intent1, decision1, _e1 = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    intent2, decision2, _e2 = _attest(db, identity, binding, agent, external_operation_id="OP-1")

    assert intent2.id == intent1.id
    assert decision2.id == decision1.id


def test_matching_retry_creates_no_new_intent(db, opa_url):
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    _attest(db, identity, binding, agent, external_operation_id="OP-1")
    _attest(db, identity, binding, agent, external_operation_id="OP-1")

    assert len(list(db.scalars(select(Intent)))) == 1


def test_matching_retry_creates_no_new_evidence(db, opa_url):
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    _attest(db, identity, binding, agent, external_operation_id="OP-1")
    _attest(db, identity, binding, agent, external_operation_id="OP-1")

    assert len(list(db.scalars(select(Evidence)))) == 1
    assert len(list(db.scalars(select(Decision)))) == 1


def test_matching_retry_never_reresolves_facts_or_reevaluates_policy(db, opa_url, monkeypatch):
    """Sections 36/37: the direct, structural proof -- idempotent return
    happens before Runtime Truth/TEF resolution and before
    decision_engine.evaluate, not merely "returns the same answer by
    coincidence." """
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id, fact_subject_path="supplier.id")
    _deploy_policy(db, org.id, opa_url)

    eval_calls = _count_calls(monkeypatch, intent_service.decision_engine, "evaluate")
    fact_calls = _count_calls(monkeypatch, intent_service.fact_service, "resolve_facts")
    # Force the fact-resolution branch to actually execute on the
    # original submission, so a 2nd invocation on retry would be
    # observable rather than vacuously absent because nothing needed it.
    monkeypatch.setattr(
        intent_service.runtime_policy_service, "list_enterprise_knowledge_keys_for_active_policies",
        lambda db, organization_id: ["supplier_approved"],
    )

    _attest(db, identity, binding, agent, counterparty="ABC Ltd", external_operation_id="OP-1")
    assert eval_calls["n"] == 1
    assert fact_calls["n"] == 1

    _attest(db, identity, binding, agent, counterparty="ABC Ltd", external_operation_id="OP-1")
    assert eval_calls["n"] == 1, "decision_engine.evaluate must not be called again on a matching retry"
    assert fact_calls["n"] == 1, "fact_service.resolve_facts must not be called again on a matching retry"


# --- Retry after real-world change: original Decision must still win -------


def test_matching_retry_after_policy_change_returns_original_decision(db, opa_url):
    """Section 8: a retry does not become a new operation just because
    organizational policy changed afterward -- proven against a real
    redeployed new policy version, not a stand-in."""
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    policy_key = _deploy_policy(db, org.id, opa_url, effect=Effect.DENY)

    _intent1, decision1, _e1 = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    assert decision1.outcome == "DENY"

    _redeploy_new_version(db, org.id, opa_url, policy_key, effect=Effect.ALLOW)

    _intent2, decision2, _e2 = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    assert decision2.id == decision1.id
    assert decision2.outcome == "DENY", "a matching retry must never re-evaluate under newer authority"


def test_matching_retry_after_fact_change_returns_original_decision(db, opa_url):
    """Section 9/35/36: the original Decision reflects the fact value
    that was true when it was made; a matching retry must not resolve
    Trusted Enterprise Facts again even though the real fact has since
    changed."""
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id, fact_subject_path="supplier.id")
    _deploy_policy(
        db, org.id, opa_url,
        condition=Condition(field="enterprise_knowledge.supplier_approved", operator=Operator.EQ, value=True),
    )
    source, keypair = _register_source(db, org.id)
    _ingest_fact(db, org.id, source, keypair, "ABC Ltd", "supplier_approved", True)

    _intent1, decision1, _e1 = _attest(db, identity, binding, agent, counterparty="ABC Ltd", external_operation_id="OP-1")
    assert decision1.outcome == "ALLOW"

    # The real fact changes -- a genuinely new, later attestation with a
    # different value for the same subject/key.
    _ingest_fact(db, org.id, source, keypair, "ABC Ltd", "supplier_approved", False)

    _intent2, decision2, _e2 = _attest(db, identity, binding, agent, counterparty="ABC Ltd", external_operation_id="OP-1")
    assert decision2.id == decision1.id
    assert decision2.outcome == "ALLOW", "a matching retry must never re-resolve facts and flip the outcome"


# NOTE: "rotating the Adapter's certificate does not reset idempotency"
# (section 11) is proven in test_operation_identity_postgres.py --
# rotate_certificate itself hits the exact same SQLite/partial-index
# divergence (idx_integration_identity_certificates_single_active) Phase
# 2's own test_integration_identity_lifecycle.py already documented, so
# it is only ever exercised there against real PostgreSQL.


# NOTE: "a retry through a REPLACED Binding still dedupes" (section 10)
# and "a semantically-identical replacement Contract version still
# dedupes" (section 9/32) are both proven against real PostgreSQL in
# test_operation_identity_postgres.py, not here. Both scenarios create a
# second EnforcementBinding for the same (integration_identity_id,
# integration_id, source_operation, environment) scope as a since-
# RETIRED first binding -- and idx_enforcement_bindings_single_active_
# per_scope's `postgresql_where` clause is ignored on SQLite, which
# materializes a plain, non-partial UNIQUE across those four columns
# instead, rejecting the second binding even though a RETIRED row must
# never block a new one. Same class of divergence already documented in
# test_enforcement_binding_lifecycle.py (Phase 2).


# --- Conflicts: same id, different authority-relevant meaning --------------


# NOTE: "changed Contract meaning conflicts" via a REPLACEMENT Binding
# for the same scope is proven in test_operation_identity_postgres.py
# for the same SQLite/partial-index reason as above. A changed Contract
# MEANING while reusing the very same Binding (impossible -- Binding's
# pinned Contract version is immutable once ACTIVE) is not a real
# scenario; a meaning change always implies a replacement Binding.


def test_changed_action_conflicts(db, opa_url):
    """The Contract's own canonical_action gate already forbids this in
    the general case (a mismatched action is itself an integration
    rejection, section 19/20), so this proves the conflict path via two
    Integrations/Contracts each legitimately mapping to a different
    canonical_action, sharing one external_operation_id."""
    org = _org(db)
    identity, integration, _cv1, binding1, agent, _ = _setup(db, org.id, resource_path=None)
    _deploy_policy(db, org.id, opa_url, action="vendor_payment", resource=None)
    _attest(db, identity, binding1, agent, action="vendor_payment", resource=None, external_operation_id="OP-1")

    cv2 = contract_svc.create_contract_version(
        db, integration.id, org.id, "DisableUserAccount", "disable_user",
    )
    cv2 = contract_svc.validate_contract_version(db, cv2.id, org.id)
    cv2 = contract_svc.approve_contract_version(db, cv2.id, org.id, approver="governance-admin@example.com")
    binding2 = binding_svc.create_draft_binding(db, org.id, identity.id, cv2.id, "production", agent_ids=[agent.id])
    binding2 = binding_svc.activate_binding(db, binding2.id, org.id)
    _deploy_policy(db, org.id, opa_url, action="disable_user", resource=None)

    with pytest.raises(ExternalOperationConflictError):
        _attest(
            db, identity, binding2, agent, source_operation="DisableUserAccount", action="disable_user",
            resource=None, external_operation_id="OP-1",
        )


def test_changed_resource_conflicts(db, opa_url):
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    _attest(db, identity, binding, agent, resource="supplier:123", external_operation_id="OP-1")

    with pytest.raises(ExternalOperationConflictError):
        _attest(db, identity, binding, agent, resource="supplier:456", external_operation_id="OP-1")


def test_changed_amount_conflicts(db, opa_url):
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id, resource_path=None, amount_path="amount", currency_path="currency")
    _deploy_policy(db, org.id, opa_url, resource=None)
    _attest(db, identity, binding, agent, resource=None, amount=100.0, currency="USD", external_operation_id="OP-1")

    with pytest.raises(ExternalOperationConflictError):
        _attest(db, identity, binding, agent, resource=None, amount=200.0, currency="USD", external_operation_id="OP-1")


def test_changed_currency_conflicts(db, opa_url):
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id, resource_path=None, amount_path="amount", currency_path="currency")
    _deploy_policy(db, org.id, opa_url, resource=None)
    _attest(db, identity, binding, agent, resource=None, amount=100.0, currency="USD", external_operation_id="OP-1")

    with pytest.raises(ExternalOperationConflictError):
        _attest(db, identity, binding, agent, resource=None, amount=100.0, currency="EUR", external_operation_id="OP-1")


def test_changed_fact_subject_conflicts(db, opa_url):
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id, resource_path=None, fact_subject_path="supplier.id")
    _deploy_policy(db, org.id, opa_url, resource=None)
    _attest(db, identity, binding, agent, resource=None, counterparty="ABC Ltd", external_operation_id="OP-1")

    with pytest.raises(ExternalOperationConflictError):
        _attest(db, identity, binding, agent, resource=None, counterparty="XYZ Ltd", external_operation_id="OP-1")


def test_changed_trusted_context_conflicts(db, opa_url):
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id, context_bindings={"department": "dept.name"})
    _deploy_policy(db, org.id, opa_url)
    _attest(db, identity, binding, agent, context={"department": "engineering"}, external_operation_id="OP-1")

    with pytest.raises(ExternalOperationConflictError):
        _attest(db, identity, binding, agent, context={"department": "finance"}, external_operation_id="OP-1")


def test_changed_agent_conflicts(db, opa_url):
    """Section 5/21: MANDATORY regression test. Agent A and Agent B may
    both be allowed through the same Binding but hold different
    organizational authority -- a retry naming a different origin Agent
    must conflict, never return Agent A's Decision as though it
    satisfied Agent B's own authority check."""
    org = _org(db)
    identity, _integ, _cv, binding, agent_a, agent_b = _setup(db, org.id, extra_agent=True)
    _deploy_policy(db, org.id, opa_url, principal="alice")

    _intent1, decision1, _e1 = _attest(db, identity, binding, agent_a, external_operation_id="OP-1")
    assert decision1.outcome == "ALLOW"

    with pytest.raises(ExternalOperationConflictError):
        _attest(db, identity, binding, agent_b, external_operation_id="OP-1")

    # Never silently returned Agent A's Decision for Agent B.
    reloaded = db.scalar(select(Intent).where(Intent.external_operation_id == "OP-1"))
    assert reloaded.agent_id == agent_a.id


# --- Scope: no false collisions ---------------------------------------------


def test_same_id_in_different_integration_does_not_collide(db, opa_url):
    org = _org(db)
    identity1, _integ1, _cv1, binding1, agent1, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    _intent1, decision1, _e1 = _attest(db, identity1, binding1, agent1, external_operation_id="OP-1")

    identity2, _integ2, _cv2, binding2, agent2, _ = _setup(db, org.id, integration=None)
    _intent2, decision2, _e2 = _attest(db, identity2, binding2, agent2, external_operation_id="OP-1")

    assert decision2.id != decision1.id


def test_same_id_in_different_environment_does_not_collide(db, opa_url):
    org = _org(db)
    identity, integration, cv, _binding_prod, agent, _ = _setup(db, org.id, environment="production")
    staging_binding = binding_svc.create_draft_binding(db, org.id, identity.id, cv.id, "staging", agent_ids=[agent.id])
    staging_binding = binding_svc.activate_binding(db, staging_binding.id, org.id)
    _deploy_policy(db, org.id, opa_url)

    prod_binding = binding_svc.get_binding(
        db,
        next(b.id for b in binding_svc.list_bindings(db, org.id) if b.environment == "production"),
        org.id,
    )

    _intent1, decision1, _e1 = _attest(db, identity, prod_binding, agent, external_operation_id="OP-123")
    _intent2, decision2, _e2 = _attest(db, identity, staging_binding, agent, external_operation_id="OP-123")

    assert decision2.id != decision1.id


# --- HUMAN_REVIEW / ALLOW / DENY retry behavior (sections 12-14) -----------


def test_pending_human_review_retry_returns_same_pending_decision(db, opa_url):
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url, effect=Effect.REQUIRE_HUMAN_REVIEW)

    _intent1, decision1, _e1 = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    assert decision1.outcome == "HUMAN_REVIEW"

    _intent2, decision2, _e2 = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    assert decision2.id == decision1.id
    assert decision2.outcome == "HUMAN_REVIEW"


def test_resolved_human_review_retry_returns_same_decision_and_resolution(db, opa_url):
    from app.services import resolution_service

    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url, effect=Effect.REQUIRE_HUMAN_REVIEW)

    _intent1, decision1, _e1 = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    resolution_service.resolve_decision(
        db, decision_id=decision1.id, organization_id=org.id, resolution="approved",
        resolved_by="reviewer@example.com", reason="looks fine",
    )

    _intent2, decision2, _e2 = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    assert decision2.id == decision1.id
    assert decision2.outcome == "HUMAN_REVIEW"  # the original outcome, never rewritten
    resolution_row = intent_service.get_decision(db, decision2.id)
    assert resolution_row is not None


def test_allow_retry_still_resolves_to_the_one_decision_a_capability_can_be_issued_for(db, opa_url):
    """Trusted Integration Architecture, Phase 5: retrying the same
    business operation (section 12) must not mint a second, independent
    authority decision for capability issuance to attach to -- it
    resolves to the exact same Decision row both times, and a Capability
    issued from it is bound to that one Decision, not a fresh one the
    retry might otherwise have manufactured."""
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    _intent1, decision1, _e1 = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    _intent2, decision2, _e2 = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    assert decision2.outcome == "ALLOW"
    assert decision2.id == decision1.id  # the retry, not a second authority decision

    issued = capability_service.issue_capability_for_decision(db, org.id, decision2.id, audience="reference-adapter")
    assert issued.token


def test_deny_retry_returns_original_deny(db, opa_url):
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url, effect=Effect.DENY)

    _intent1, decision1, _e1 = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    assert decision1.outcome == "DENY"
    _intent2, decision2, _e2 = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    assert decision2.id == decision1.id
    assert decision2.outcome == "DENY"


# --- Failure handling (sections 15, 16) -------------------------------------


def test_invalid_external_operation_id_is_rejected_and_does_not_poison(db, opa_url):
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    with pytest.raises(IntegrationRejectionError, match="invalid_external_operation_id"):
        _attest(db, identity, binding, agent, external_operation_id="   ")

    # The same id string, now valid non-whitespace input under a
    # DIFFERENT (real) external_operation_id, succeeds normally --
    # nothing about the earlier malformed attempt is stuck anywhere.
    _intent, decision, _evidence = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    assert decision.outcome == "ALLOW"


def test_failed_pre_evaluation_request_does_not_poison_operation_id(db, opa_url):
    """Section 15: a request rejected for integration-trust reasons
    (here: an unlisted origin Agent) before an Intent is ever
    constructed must not permanently block a later, corrected request
    from using the same external_operation_id."""
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id, extra_agent=False)
    _deploy_policy(db, org.id, opa_url)

    principal2 = _principal(db, org.id, "dave")
    unlisted_agent = _agent(db, principal2.id, "Unlisted Agent")

    with pytest.raises(IntegrationRejectionError, match="origin_agent_not_allowed_for_binding"):
        _attest(db, identity, binding, unlisted_agent, external_operation_id="OP-1")

    assert operation_identity_service.find_existing_operation(
        db, binding.integration_id, binding.environment, "OP-1",
    ) is None

    _intent, decision, _evidence = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    assert decision.outcome == "ALLOW"


def test_transaction_rollback_before_commit_does_not_poison_operation_id(db, opa_url, monkeypatch):
    """Section 16: integration validation succeeded (the Intent row --
    with external_operation_id/integration_id/fingerprint already set --
    was flushed) but the transaction fails before Decision/Evidence
    commit. The whole transaction must roll back together (existing
    transaction boundaries, not a second state machine), so the
    operation id remains available for a real retry."""
    org = _org(db)
    identity, _integ, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    class _InjectedFailure(Exception):
        pass

    def _boom(*args, **kwargs):
        raise _InjectedFailure("simulated evaluation failure")

    monkeypatch.setattr(intent_service.decision_engine, "evaluate", _boom)
    with pytest.raises(_InjectedFailure):
        _attest(db, identity, binding, agent, external_operation_id="OP-1")

    # What FastAPI's get_db dependency teardown does on an unhandled
    # exception (db.close() on a session with a pending transaction) --
    # simulated explicitly here since this test drives the service
    # directly, not through a request lifecycle.
    db.rollback()

    assert list(db.scalars(select(Intent))) == []
    assert operation_identity_service.find_existing_operation(
        db, binding.integration_id, binding.environment, "OP-1",
    ) is None

    monkeypatch.undo()
    _intent, decision, _evidence = _attest(db, identity, binding, agent, external_operation_id="OP-1")
    assert decision.outcome == "ALLOW"
    assert len(list(db.scalars(select(Intent)))) == 1


# --- Agent-direct path unchanged (section 23) -------------------------------


def test_agent_direct_path_does_not_require_or_accept_external_operation_id(db, opa_url):
    org = _org(db)
    principal = _principal(db, org.id)
    agent = _agent(db, principal.id)
    _deploy_policy(db, org.id, opa_url, resource="account:USR-829", action="disable_user")

    intent, decision, evidence = intent_service.submit_intent(
        db, agent=agent, action="disable_user", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="account:USR-829", source=None,
    )
    assert decision.outcome == "ALLOW"
    assert intent.external_operation_id is None
    assert intent.integration_id is None
    assert intent.canonical_operation_fingerprint is None


def test_agent_direct_receipt_has_no_integration_provenance(db, opa_url):
    org = _org(db)
    principal = _principal(db, org.id)
    agent = _agent(db, principal.id)
    _deploy_policy(db, org.id, opa_url, resource="account:USR-829", action="disable_user")

    _intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action="disable_user", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="account:USR-829", source=None,
    )
    receipt = authorization_receipt_service.get_authorization_receipt(db, decision.id, org.id)
    assert receipt.integration is None


# --- Phase 4: Decision Detail / Receipt surface integration_id, and
#     BindingResponse surfaces allowed_agent_ids inline -------------------


def test_receipt_and_decision_response_expose_integration_id_for_adapter_mediated_decisions(db, opa_url):
    """Trusted Integration Architecture, Phase 4: routers/intents.py's
    GetDecisionResponse.integration (new) and the Authorization Receipt's
    own integration.integration_id (additive field) both resolve
    directly to the owning Integration, without a caller having to walk
    integration_contract_version_id -> IntegrationContractVersion first."""
    from app.routers.intents import _build_decision_response

    org = _org(db)
    identity, integration, _cv, binding, agent, _ = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    _intent, decision, _evidence = _attest(db, identity, binding, agent, external_operation_id="OP-1")

    receipt = authorization_receipt_service.get_authorization_receipt(db, decision.id, org.id)
    assert receipt.integration is not None
    assert receipt.integration.integration_id == str(integration.id)

    response = _build_decision_response(db, decision)
    assert response.integration is not None
    assert response.integration.integration_id == str(integration.id)
    assert response.integration.external_operation_id == "OP-1"


def test_decision_response_integration_is_none_for_agent_direct(db, opa_url):
    from app.routers.intents import _build_decision_response

    org = _org(db)
    principal = _principal(db, org.id)
    agent = _agent(db, principal.id)
    _deploy_policy(db, org.id, opa_url, resource="account:USR-829", action="disable_user")

    _intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action="disable_user", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="account:USR-829", source=None,
    )
    response = _build_decision_response(db, decision)
    assert response.integration is None


def test_binding_response_exposes_allowed_agent_ids_inline(db, opa_url):
    from app.routers.enforcement_bindings import _binding_to_response

    org = _org(db)
    identity, _integ, _cv, binding, agent, second_agent = _setup(db, org.id, extra_agent=False)

    response = _binding_to_response(db, binding)
    assert response.allowed_agent_ids == [str(agent.id)]
