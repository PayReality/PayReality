"""Trusted Integration Architecture, Phase 2: the trusted-Adapter
runtime path end to end -- submit_attested_intent's every pre-
evaluation trust check (section 25), its ALLOW/DENY/HUMAN_REVIEW
outcomes once those checks pass, Adapter-scoped replay protection kept
separate from Agent-direct's own, Evidence/Authorization Receipt
provenance, and Capability issuance suppression. Real OPA throughout
(the `opa_url` fixture, this codebase's own established convention --
see test_decision_history.py), real SQLite for the DB.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Base, Organization, Principal
from app.domain.decision import engine as decision_engine
from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import (
    authorization_receipt_service,
    capability_service,
    enforcement_binding_service as binding_svc,
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
    integration_runtime_service as runtime_svc,
    intent_service,
    runtime_policy_service as policy_svc,
)
from app.services.integration_runtime_service import AdapterReplayDetectedError, IntegrationRejectionError

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


def _deploy_policy(db, org_id, opa_url, effect=Effect.ALLOW, action="vendor_payment", resource="supplier:123", principal="alice"):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="test policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal=principal, action=action, resource=resource),
        conditions=ConditionSet(all=()), effect=effect,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row.policy_key


def _setup(db, org_id, resource_path="supplier.id", amount_path=None, currency_path=None,
           fact_subject_path=None, context_bindings=None, environment="production", agent_status="active"):
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "Reference SAP Adapter", "ed25519:base64:AAAA")
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)

    integration = contract_svc.create_integration(db, org_id, "SAP S/4HANA (reference)")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, "ChangeSupplierBankDetails", "vendor_payment",
        resource_path=resource_path, amount_path=amount_path, currency_path=currency_path,
        fact_subject_path=fact_subject_path, context_bindings=context_bindings or {},
    )
    contract_version = contract_svc.validate_contract_version(db, contract_version.id, org_id)
    contract_version = contract_svc.approve_contract_version(db, contract_version.id, org_id, approver="governance-admin@example.com")

    principal = _principal(db, org_id)
    agent = _agent(db, principal.id, status=agent_status)
    binding = binding_svc.create_draft_binding(
        db, org_id, identity.id, contract_version.id, environment, agent_ids=[agent.id],
    )
    binding = binding_svc.activate_binding(db, binding.id, org_id)
    return identity, contract_version, binding, agent


def _attest(db, identity, binding, agent, *, source_operation="ChangeSupplierBankDetails", action="vendor_payment",
            resource="supplier:123", amount=None, currency=None, counterparty=None, context=None, nonce=None):
    return runtime_svc.submit_attested_intent(
        db, identity,
        enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=source_operation, action=action, resource=resource,
        amount=amount, currency=currency, counterparty=counterparty,
        context=context or {}, requested_at=datetime.now(timezone.utc),
        nonce=nonce or uuid.uuid4().hex, correlation_id=None,
    )


# --- Successful paths, every outcome ---------------------------------------


def test_valid_attested_intent_allows_and_carries_full_provenance(db, opa_url):
    org = _org(db)
    identity, contract_version, binding, agent = _setup(db, org.id, context_bindings={"department": "dept.name"})
    _deploy_policy(db, org.id, opa_url)

    intent, decision, evidence = _attest(db, identity, binding, agent, context={"department": "engineering"})

    assert decision.outcome == "ALLOW"
    assert intent.agent_id == agent.id  # never replaced by the Adapter's own identity
    assert intent.integration_identity_id == identity.id
    assert intent.enforcement_binding_id == binding.id
    assert intent.integration_contract_version_id == contract_version.id
    assert intent.environment == binding.environment
    assert intent.context["environment"] == binding.environment  # server-injected, not caller-supplied

    payload = evidence.payload
    assert payload["integration_identity_id"] == str(identity.id)
    assert payload["enforcement_binding_id"] == str(binding.id)
    assert payload["integration_contract_version_id"] == str(contract_version.id)
    assert payload["integration_contract_content_hash"] == contract_version.content_hash
    assert payload["environment"] == binding.environment
    assert payload["source_operation"] == "ChangeSupplierBankDetails"


def test_deny_outcome_still_produces_a_real_decision_and_evidence(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id, context_bindings={})
    _deploy_policy(db, org.id, opa_url, effect=Effect.DENY)

    _intent, decision, evidence = _attest(db, identity, binding, agent)
    assert decision.outcome == "DENY"
    assert evidence is not None


def test_human_review_outcome_for_adapter_mediated_request(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id, context_bindings={})
    _deploy_policy(db, org.id, opa_url, effect=Effect.REQUIRE_HUMAN_REVIEW)

    _intent, decision, _evidence = _attest(db, identity, binding, agent)
    assert decision.outcome == "HUMAN_REVIEW"


# --- Pre-evaluation trust failures (section 25) -----------------------------


def test_suspended_origin_agent_is_rejected_not_routed_to_human_review(db, opa_url):
    """Deliberate Phase 2 scope reduction, disclosed: unlike Agent-direct's
    own suspended -> HUMAN_REVIEW special case, an Adapter-mediated
    request naming an ineligible origin Agent is a pre-evaluation
    rejection -- it never becomes a Decision at all. The agent starts
    eligible (activation itself requires that, section 12) and is
    suspended afterward, the realistic sequence this runtime check
    guards against."""
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id, context_bindings={})
    agent.status = "suspended"
    db.commit()
    with pytest.raises(IntegrationRejectionError, match="origin_agent_not_eligible"):
        _attest(db, identity, binding, agent)


def test_unknown_binding_is_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id, context_bindings={})
    fake_binding = type("Fake", (), {"id": uuid.uuid4()})
    with pytest.raises(IntegrationRejectionError, match="enforcement_binding_not_found"):
        _attest(db, identity, fake_binding, agent)


def test_binding_belonging_to_a_different_identity_looks_not_found(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id, context_bindings={})
    other_identity, _cert = identity_svc.register_integration_identity(db, org.id, "Second Adapter", "ed25519:base64:BBBB")
    other_identity = identity_svc.activate_integration_identity(db, other_identity.id, org.id)
    with pytest.raises(IntegrationRejectionError, match="enforcement_binding_not_found"):
        _attest(db, other_identity, binding, agent)


def test_draft_binding_is_rejected_as_not_active(db, opa_url):
    org = _org(db)
    identity, contract_version, _active_binding, agent = _setup(db, org.id, context_bindings={})
    draft_binding = binding_svc.create_draft_binding(
        db, org.id, identity.id, contract_version.id, "staging", agent_ids=[agent.id],
    )
    with pytest.raises(IntegrationRejectionError, match="enforcement_binding_not_active"):
        _attest(db, identity, draft_binding, agent)


def test_origin_agent_not_allowed_for_binding_is_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, _allowed_agent = _setup(db, org.id, context_bindings={})
    principal = _principal(db, org.id, "bob")
    other_agent = _agent(db, principal.id, "Other Agent")
    with pytest.raises(IntegrationRejectionError, match="origin_agent_not_allowed_for_binding"):
        _attest(db, identity, binding, other_agent)


def test_cross_org_origin_agent_is_rejected(db, opa_url):
    org = _org(db, "Org A")
    other_org = _org(db, "Org B")
    identity, _cv, binding, _setup_agent = _setup(db, org.id, context_bindings={})
    other_principal = _principal(db, other_org.id, "carol")
    other_org_agent = _agent(db, other_principal.id, "Other Org Agent")
    with pytest.raises(IntegrationRejectionError, match="origin_agent_not_found"):
        _attest(db, identity, binding, other_org_agent)


def test_source_operation_mismatch_is_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id, context_bindings={})
    with pytest.raises(IntegrationRejectionError, match="source_operation_mismatch"):
        _attest(db, identity, binding, agent, source_operation="SomeOtherOperation")


def test_canonical_action_mismatch_is_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id, context_bindings={})
    with pytest.raises(IntegrationRejectionError, match="canonical_action_mismatch"):
        _attest(db, identity, binding, agent, action="disable_user")


def test_missing_required_resource_is_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id, resource_path="supplier.id", context_bindings={})
    with pytest.raises(IntegrationRejectionError, match="missing_required_resource"):
        _attest(db, identity, binding, agent, resource=None)


def test_unexpected_resource_supplied_when_contract_declares_no_path(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id, resource_path=None, context_bindings={})
    with pytest.raises(IntegrationRejectionError, match="unexpected_resource"):
        _attest(db, identity, binding, agent, resource="supplier:123")


def test_reserved_environment_context_key_is_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id, context_bindings={})
    with pytest.raises(IntegrationRejectionError, match="reserved_context_key_supplied"):
        _attest(db, identity, binding, agent, context={"environment": "staging"})


def test_unexpected_context_key_is_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id, context_bindings={})
    with pytest.raises(IntegrationRejectionError, match="unexpected_context_keys"):
        _attest(db, identity, binding, agent, context={"not_declared": "value"})


def test_missing_required_context_key_is_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id, context_bindings={"department": "dept.name"})
    with pytest.raises(IntegrationRejectionError, match="missing_required_context_keys"):
        _attest(db, identity, binding, agent, context={})


# --- Replay protection, scoped separately from Agent-direct's own ----------


def test_adapter_nonce_replay_for_the_same_identity_is_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id, context_bindings={})
    _deploy_policy(db, org.id, opa_url)
    nonce = uuid.uuid4().hex
    _attest(db, identity, binding, agent, nonce=nonce)
    with pytest.raises(AdapterReplayDetectedError):
        _attest(db, identity, binding, agent, nonce=nonce)


def test_adapter_nonce_replay_is_scoped_to_the_identity_regardless_of_origin_agent(db, opa_url):
    """Section 24: the Adapter-scoped replay invariant is keyed on
    (integration_identity_id, nonce), not on the origin Agent named in
    the request -- reusing the same nonce for a second, different, but
    equally-allowed origin Agent under the same identity must still be
    rejected."""
    org = _org(db)
    identity, contract_version, _binding, agent1 = _setup(db, org.id, context_bindings={})
    principal2 = _principal(db, org.id, "dave")
    agent2 = _agent(db, principal2.id, "Second Allowed Agent")
    two_agent_binding = binding_svc.create_draft_binding(
        db, org.id, identity.id, contract_version.id, "staging", agent_ids=[agent1.id, agent2.id],
    )
    two_agent_binding = binding_svc.activate_binding(db, two_agent_binding.id, org.id)
    _deploy_policy(db, org.id, opa_url)
    nonce = uuid.uuid4().hex

    _attest(db, identity, two_agent_binding, agent1, nonce=nonce)
    with pytest.raises(AdapterReplayDetectedError):
        _attest(db, identity, two_agent_binding, agent2, nonce=nonce)


def test_adapter_nonce_does_not_collide_with_an_unrelated_agent_direct_nonce(db, opa_url):
    """Never weakening Agent-direct's own (agent_id, nonce) replay
    protection: an Agent-direct submission for one Agent, and an
    Adapter-mediated submission naming a DIFFERENT origin Agent, may
    legitimately reuse the same literal nonce string -- the two rows
    never share an (agent_id, nonce) tuple, and the identity-scoped
    constraint was never touched by the Agent-direct call at all."""
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id, context_bindings={})
    principal2 = _principal(db, org.id, "dave")
    unrelated_agent = _agent(db, principal2.id, "Unrelated Agent")
    _deploy_policy(db, org.id, opa_url)
    nonce = uuid.uuid4().hex

    intent_service.submit_intent(
        db, agent=unrelated_agent, action="vendor_payment", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=nonce, correlation_id=None,
        resource="supplier:123", source=None,
    )
    _intent, decision, _evidence = _attest(db, identity, binding, agent, nonce=nonce)
    assert decision.outcome == "ALLOW"


# --- Capability suppression and Authorization Receipt provenance ----------


def test_capability_issuance_is_suppressed_for_adapter_mediated_allow_decision(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id, context_bindings={})
    _deploy_policy(db, org.id, opa_url)
    _intent, decision, _evidence = _attest(db, identity, binding, agent)

    with pytest.raises(capability_service.CapabilityNotAvailableForIntegrationIntentError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")


def test_authorization_receipt_carries_integration_provenance_only_for_adapter_mediated_decisions(db, opa_url):
    org = _org(db)
    identity, contract_version, binding, agent = _setup(db, org.id, context_bindings={})
    _deploy_policy(db, org.id, opa_url)

    _intent, adapter_decision, _evidence = _attest(db, identity, binding, agent)
    adapter_receipt = authorization_receipt_service.get_authorization_receipt(db, adapter_decision.id, org.id)
    assert adapter_receipt.integration is not None
    assert adapter_receipt.integration.integration_identity_id == str(identity.id)
    assert adapter_receipt.integration.integration_contract_content_hash == contract_version.content_hash

    _agent_intent, agent_decision, _agent_evidence = intent_service.submit_intent(
        db, agent=agent, action="vendor_payment", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="supplier:123", source=None,
    )
    agent_receipt = authorization_receipt_service.get_authorization_receipt(db, agent_decision.id, org.id)
    assert agent_receipt.integration is None
