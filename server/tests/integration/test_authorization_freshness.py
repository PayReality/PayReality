"""Trusted Integration Architecture, Phase 6.1 (Production Authorization
Assurance), Part A: Authorization Freshness at Capability Consumption.

Real SQLite + real ephemeral OPA throughout, mirroring
test_capability_issuance_idempotency.py's own fixture helpers.

The governing question this file answers with real tests, not
inference: once a Capability has been issued, does revoking the
identity/binding/tenant it depends on actually stop it from being
consumed? Before this milestone, no -- confirmed dishonestly-disclosed,
not silently assumed, in the immediately-prior milestone's own test
suite (test_reference_enforcement_demonstration.py's
test_revoked_integration_identity_after_issuance_but_before_verification_
fails_closed used to assert the OLD, gap-having behavior; it now asserts
the fixed one). This file covers every revocable object Part A's own
brief names, for both the Agent-direct and Adapter-mediated paths, plus
the state-restoration question the brief explicitly demanded not be
left ambiguous.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Base, CapabilityToken, Organization, Principal
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64
from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import (
    agent_service,
    capability_service,
    enforcement_binding_service as binding_svc,
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
    integration_runtime_service as runtime_svc,
    intent_service,
    organization_lifecycle_service,
    runtime_policy_service as policy_svc,
    signing_key_service,
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


def _org(db, name="Org Freshness"):
    org = Organization(id=uuid.uuid4(), name=name)
    db.add(org)
    db.commit()
    return org


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


def _allow_agent_direct_decision(db, org_id, opa_url):
    principal = Principal(id=uuid.uuid4(), name="alice", organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="AP Invoice Agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    _deploy_policy(db, org_id, opa_url)
    _intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action="vendor_payment", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="supplier:123",
    )
    assert decision.outcome == "ALLOW"
    return agent, decision


def _allow_adapter_decision(db, org_id, opa_url, environment="production"):
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "Reference SAP Adapter", "ed25519:base64:AAAA")
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)
    integration = contract_svc.create_integration(db, org_id, "SAP S/4HANA (reference)")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, "ChangeSupplierBankDetails", "vendor_payment",
        resource_path="supplier.id", amount_path=None, currency_path=None,
        fact_subject_path=None, context_bindings={},
    )
    contract_version = contract_svc.validate_contract_version(db, contract_version.id, org_id)
    contract_version = contract_svc.approve_contract_version(db, contract_version.id, org_id, approver="governance-admin@example.com")
    principal = Principal(id=uuid.uuid4(), name="alice", organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="AP Invoice Agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    binding = binding_svc.create_draft_binding(db, org_id, identity.id, contract_version.id, environment, agent_ids=[agent.id])
    binding = binding_svc.activate_binding(db, binding.id, org_id)
    _deploy_policy(db, org_id, opa_url)
    intent, decision, _evidence = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation="ChangeSupplierBankDetails", action="vendor_payment", resource="supplier:123",
        amount=None, currency=None, counterparty=None, context={}, requested_at=datetime.now(timezone.utc),
        nonce=uuid.uuid4().hex, correlation_id=None, external_operation_id=uuid.uuid4().hex,
    )
    assert decision.outcome == "ALLOW"
    return identity, binding, agent, intent, decision


# === Agent revoked between issuance and consumption =========================


def test_agent_direct_consumption_fails_closed_after_agent_revoked(db, opa_url):
    org = _org(db)
    agent, decision = _allow_agent_direct_decision(db, org.id, opa_url)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")

    agent_service.suspend_agent(db, agent.id)

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-adapter", "vendor_payment", "supplier:123", {},
        )

    row = db.get(CapabilityToken, issued.capability_id)
    assert row.consumed_at is None, "a failed freshness check must never mark the token consumed"


def test_adapter_mediated_consumption_fails_closed_after_agent_revoked(db, opa_url):
    org = _org(db)
    identity, binding, agent, intent, decision = _allow_adapter_decision(db, org.id, opa_url)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")

    agent_service.suspend_agent(db, agent.id)

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-adapter", "vendor_payment", intent.resource,
            {"environment": binding.environment}, environment=binding.environment,
        )
    row = db.get(CapabilityToken, issued.capability_id)
    assert row.consumed_at is None


# === IntegrationIdentity revoked between issuance and consumption ===========


def test_consumption_fails_closed_after_integration_identity_revoked(db, opa_url):
    org = _org(db)
    identity, binding, agent, intent, decision = _allow_adapter_decision(db, org.id, opa_url)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")

    identity_svc.suspend_integration_identity(db, identity.id, org.id)

    with pytest.raises(capability_service.IntegrationIdentityNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-adapter", "vendor_payment", intent.resource,
            {"environment": binding.environment}, environment=binding.environment,
        )
    row = db.get(CapabilityToken, issued.capability_id)
    assert row.consumed_at is None


# === Runtime Connection (EnforcementBinding) revoked =========================


def test_consumption_fails_closed_after_enforcement_binding_retired(db, opa_url):
    org = _org(db)
    identity, binding, agent, intent, decision = _allow_adapter_decision(db, org.id, opa_url)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")

    binding_svc.retire_binding(db, binding.id, org.id)

    with pytest.raises(capability_service.EnforcementBindingNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-adapter", "vendor_payment", intent.resource,
            {"environment": binding.environment}, environment=binding.environment,
        )
    row = db.get(CapabilityToken, issued.capability_id)
    assert row.consumed_at is None


# === Tenant deactivated between issuance and consumption =====================


def test_consumption_fails_closed_after_tenant_deactivated(db, opa_url):
    org = _org(db)
    agent, decision = _allow_agent_direct_decision(db, org.id, opa_url)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")

    organization_lifecycle_service.deactivate_organization(db, org.id, actor="test-suite")

    with pytest.raises(capability_service.TenantNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-adapter", "vendor_payment", "supplier:123", {},
        )
    row = db.get(CapabilityToken, issued.capability_id)
    assert row.consumed_at is None


def test_issuance_also_fails_closed_for_a_deactivated_tenant(db, opa_url):
    """Part A's own consistency extension (this milestone's brief did
    not ask to touch issuance, but leaving Organization unchecked there
    while checking it at consumption would be a real, avoidable
    asymmetry -- see capability_service.TenantNotActiveError's own
    docstring)."""
    org = _org(db)
    _agent, decision = _allow_agent_direct_decision(db, org.id, opa_url)

    organization_lifecycle_service.deactivate_organization(db, org.id, actor="test-suite")

    with pytest.raises(capability_service.TenantNotActiveError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")


# === Valid, unchanged lifecycle still succeeds exactly once ==================


def test_valid_unchanged_lifecycle_consumes_successfully_once(db, opa_url):
    org = _org(db)
    agent, decision = _allow_agent_direct_decision(db, org.id, opa_url)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")

    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-adapter", "vendor_payment", "supplier:123", {},
    )
    assert consumed is not None

    with pytest.raises(capability_service.CapabilityTokenAlreadyConsumedError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-adapter", "vendor_payment", "supplier:123", {},
        )


# === State restoration: explicitly defined and tested, not left ambiguous ===


def test_state_restoration_lets_a_subsequent_attempt_succeed(db, opa_url):
    """Section 6/24 of this milestone's own brief demands this be
    explicitly defined and tested, not left ambiguous: a freshness
    failure never itself consumes the token (proven above, per revoked
    object), so if the underlying state is restored before the
    Capability expires, a fresh attempt re-checks CURRENT state and may
    succeed -- this is the deliberate, stated design, not an oversight."""
    org = _org(db)
    agent, decision = _allow_agent_direct_decision(db, org.id, opa_url)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")

    agent_service.suspend_agent(db, agent.id)
    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-adapter", "vendor_payment", "supplier:123", {},
        )

    agent_service.activate_agent(db, agent.id)
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-adapter", "vendor_payment", "supplier:123", {},
    )
    assert consumed is not None

    # And now that it's genuinely consumed, replay still fails -- state
    # restoration does not weaken the single-use guarantee itself.
    with pytest.raises(capability_service.CapabilityTokenAlreadyConsumedError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-adapter", "vendor_payment", "supplier:123", {},
        )


# === Phase 5.1/6 invariants, reconfirmed alongside the new checks ===========


def test_expired_capability_still_does_not_auto_renew_and_freshness_checks_dont_change_that(db, opa_url):
    from datetime import timedelta
    from sqlalchemy import update

    org = _org(db)
    _agent, decision = _allow_agent_direct_decision(db, org.id, opa_url)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")
    db.execute(
        update(CapabilityToken).where(CapabilityToken.id == issued.capability_id)
        .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    db.commit()

    with pytest.raises(capability_service.CapabilityExpiredNotRenewedError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")


def test_duplicate_issuance_still_fails_alongside_freshness_checks(db, opa_url):
    org = _org(db)
    _agent, decision = _allow_agent_direct_decision(db, org.id, opa_url)
    first = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")
    with pytest.raises(capability_service.CapabilityAlreadyIssuedError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")
    rows = db.scalars(select(CapabilityToken).where(CapabilityToken.decision_id == decision.id)).all()
    assert len(rows) == 1
    assert rows[0].id == first.capability_id
