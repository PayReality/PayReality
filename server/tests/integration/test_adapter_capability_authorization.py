"""Trusted Integration Architecture, Phase 5: extends Capability
Authorization to the Adapter-mediated runtime path. Real SQLite + real
ephemeral OPA throughout, the same established convention as
test_integration_runtime_path.py and test_capability_tokens.py, which
this file's fixtures mirror closely on purpose -- Agent-direct's own
capability test matrix already lives in test_capability_tokens.py and is
not duplicated here; this file covers only what is new or different for
the Adapter-mediated path.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, Base, CapabilityToken, Organization, Principal
from app.domain.capability import token as capability_token
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64
from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import (
    capability_service,
    enforcement_binding_service as binding_svc,
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
    integration_runtime_service as runtime_svc,
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


def _setup(db, org_id, environment="production", agent_status="active"):
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

    principal = _principal(db, org_id)
    agent = _agent(db, principal.id, status=agent_status)
    binding = binding_svc.create_draft_binding(
        db, org_id, identity.id, contract_version.id, environment, agent_ids=[agent.id],
    )
    binding = binding_svc.activate_binding(db, binding.id, org_id)
    return identity, contract_version, binding, agent


def _attest(db, identity, binding, agent, *, source_operation="ChangeSupplierBankDetails", action="vendor_payment",
            resource="supplier:123", external_operation_id=None):
    return runtime_svc.submit_attested_intent(
        db, identity,
        enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=source_operation, action=action, resource=resource,
        amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc),
        nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=external_operation_id or uuid.uuid4().hex,
    )


def _allow_adapter_decision(db, org, opa_url, **setup_kwargs):
    identity, contract_version, binding, agent = _setup(db, org.id, **setup_kwargs)
    _deploy_policy(db, org.id, opa_url)
    intent, decision, evidence = _attest(db, identity, binding, agent)
    assert decision.outcome == "ALLOW"
    return identity, contract_version, binding, agent, intent, decision


# --- Issuance: bindings ------------------------------------------------------


def test_adapter_capability_is_bound_to_integration_and_binding(db, opa_url):
    org = _org(db)
    identity, contract_version, binding, agent, intent, decision = _allow_adapter_decision(db, org, opa_url)

    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")
    row = db.get(CapabilityToken, issued.capability_id)
    assert row.integration_identity_id == identity.id
    assert row.enforcement_binding_id == binding.id
    assert row.integration_contract_version_id == contract_version.id
    assert row.environment == binding.environment
    assert row.external_operation_id == intent.external_operation_id

    payload, _sig, _key_id = capability_token._decode_token(issued.token)
    assert payload.enforcement_binding_id == str(binding.id)
    assert payload.environment == binding.environment


def test_agent_direct_capability_still_has_no_integration_binding(db, opa_url):
    """Backward compatibility (section 38): an Agent-direct capability's
    five new columns/payload fields are all None, exactly as before this
    milestone."""
    org = _org(db)
    principal = _principal(db, org.id)
    agent = _agent(db, principal.id)
    _deploy_policy(db, org.id, opa_url)
    from app.services import intent_service as intent_svc

    _intent, decision, _evidence = intent_svc.submit_intent(
        db, agent=agent, action="vendor_payment", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="supplier:123",
    )
    assert decision.outcome == "ALLOW"
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")
    row = db.get(CapabilityToken, issued.capability_id)
    assert row.integration_identity_id is None
    assert row.enforcement_binding_id is None
    assert row.environment is None


def test_issuance_fails_closed_when_integration_identity_no_longer_active(db, opa_url):
    org = _org(db)
    identity, _cv, _binding, _agent, _intent, decision = _allow_adapter_decision(db, org, opa_url)
    identity_svc.suspend_integration_identity(db, identity.id, org.id)

    with pytest.raises(capability_service.IntegrationIdentityNotActiveError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")


def test_issuance_fails_closed_when_enforcement_binding_no_longer_active(db, opa_url):
    org = _org(db)
    _identity, _cv, binding, _agent, _intent, decision = _allow_adapter_decision(db, org, opa_url)
    binding_svc.retire_binding(db, binding.id, org.id)

    with pytest.raises(capability_service.EnforcementBindingNotActiveError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")


def test_issuance_fails_closed_when_origin_agent_no_longer_active(db, opa_url):
    """Section 6/40 ("wrong Agent"/"Agent removed from allowed list"):
    an EnforcementBinding's allow-list is immutable once ACTIVE (an
    Agent cannot literally be removed from it without retiring the whole
    Binding, already covered above), but the Agent's OWN status is not
    -- a hostile review of this milestone found this was never
    re-checked at issuance time, for either runtime path."""
    from app.services import agent_service

    org = _org(db)
    _identity, _cv, _binding, agent, _intent, decision = _allow_adapter_decision(db, org, opa_url)
    agent_service.suspend_agent(db, agent.id)

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")


def test_agent_direct_issuance_also_fails_closed_when_agent_no_longer_active(db, opa_url):
    """The same fix applies to the Agent-direct path, not only the
    Adapter-mediated one -- this was a real gap in the pre-existing
    model, not something Phase 5 introduced only for the new path."""
    from app.services import agent_service
    from app.services import intent_service as intent_svc

    org = _org(db)
    principal = _principal(db, org.id)
    agent = _agent(db, principal.id)
    _deploy_policy(db, org.id, opa_url)
    _intent, decision, _evidence = intent_svc.submit_intent(
        db, agent=agent, action="vendor_payment", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="supplier:123",
    )
    assert decision.outcome == "ALLOW"
    agent_service.retire_agent(db, agent.id)

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")


# --- Verification: the new binding checks ------------------------------------


def _issue(db, org, decision, audience="reference-adapter"):
    return capability_service.issue_capability_for_decision(db, org.id, decision.id, audience=audience)


def test_verification_succeeds_with_matching_environment(db, opa_url):
    org = _org(db)
    _identity, _cv, binding, _agent, intent, decision = _allow_adapter_decision(db, org, opa_url)
    issued = _issue(db, org, decision)

    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-adapter", "vendor_payment", intent.resource,
        {"environment": binding.environment},
        environment=binding.environment,
    )
    assert str(consumed.decision_id) == str(decision.id)


def test_verification_rejects_wrong_environment(db, opa_url):
    org = _org(db)
    _identity, _cv, _binding, _agent, intent, decision = _allow_adapter_decision(db, org, opa_url, environment="production")
    issued = _issue(db, org, decision)

    with pytest.raises(capability_token.CapabilityBindingMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-adapter", "vendor_payment", intent.resource,
            {"environment": "production"},
            environment="staging",
        )


def test_verification_rejects_wrong_enforcement_binding(db, opa_url):
    org = _org(db)
    _identity, _cv, binding, _agent, intent, decision = _allow_adapter_decision(db, org, opa_url)
    issued = _issue(db, org, decision)
    other_binding_id = uuid.uuid4()
    assert other_binding_id != binding.id

    with pytest.raises(capability_token.CapabilityBindingMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-adapter", "vendor_payment", intent.resource,
            {"environment": binding.environment},
            enforcement_binding_id=other_binding_id,
        )


def test_verification_without_binding_expectations_still_works(db, opa_url):
    """A PEP that does not know or care which connection/environment
    issued the capability may omit both -- fully backward compatible."""
    org = _org(db)
    _identity, _cv, binding, _agent, intent, decision = _allow_adapter_decision(db, org, opa_url)
    issued = _issue(db, org, decision)

    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-adapter", "vendor_payment", intent.resource,
        {"environment": binding.environment},
    )
    assert consumed is not None


def test_verification_rejects_wrong_principal(db, opa_url):
    """Section 6/7: Agent/principal is a required binding. A capability
    issued for the origin Agent's own principal must not verify as
    belonging to a different one, closing a gap a hostile review of
    this milestone's own new bindings found (verify_and_consume_capability
    previously had no way to check principal at all)."""
    org = _org(db)
    _identity, _cv, binding, _agent, intent, decision = _allow_adapter_decision(db, org, opa_url)
    issued = _issue(db, org, decision)

    with pytest.raises(capability_token.CapabilityConstraintMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-adapter", "vendor_payment", intent.resource,
            {"environment": binding.environment},
            principal="someone-else-entirely",
        )


def test_verification_succeeds_with_matching_principal(db, opa_url):
    """_setup's own _principal() helper defaults to "alice" -- the
    signed payload's `principal` field is the Principal's name (who the
    Agent acts for), never the Agent's own name."""
    org = _org(db)
    _identity, _cv, binding, _agent, intent, decision = _allow_adapter_decision(db, org, opa_url)
    issued = _issue(db, org, decision)

    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-adapter", "vendor_payment", intent.resource,
        {"environment": binding.environment},
        principal="alice",
    )
    assert consumed is not None


def test_agent_direct_capability_verification_environment_check_is_a_mismatch(db, opa_url):
    """An Agent-direct capability's payload.environment is None -- a PEP
    that (incorrectly) expects a specific environment for it must fail
    closed, not silently pass because the token never carried one."""
    org = _org(db)
    principal = _principal(db, org.id)
    agent = _agent(db, principal.id)
    _deploy_policy(db, org.id, opa_url)
    from app.services import intent_service as intent_svc

    _intent, decision, _evidence = intent_svc.submit_intent(
        db, agent=agent, action="vendor_payment", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="supplier:123",
    )
    issued = _issue(db, org, decision)
    with pytest.raises(capability_token.CapabilityBindingMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-adapter", "vendor_payment", _intent.resource, {},
            environment="production",
        )


# --- DENY / integration rejection never produce a capability -----------------


def test_deny_adapter_decision_cannot_issue_capability(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url, effect=Effect.DENY)
    _intent, decision, _evidence = _attest(db, identity, binding, agent)
    assert decision.outcome == "DENY"

    with pytest.raises(capability_service.DecisionNotAllowError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")


def test_human_review_adapter_decision_cannot_issue_capability(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url, effect=Effect.REQUIRE_HUMAN_REVIEW)
    _intent, decision, _evidence = _attest(db, identity, binding, agent)
    assert decision.outcome == "HUMAN_REVIEW"

    with pytest.raises(capability_service.DecisionNotAllowError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")


def test_human_review_decision_stays_ineligible_even_after_human_approval(db, opa_url):
    """Section 20: the original Decision's outcome is never mutated to
    ALLOW by a human's later approval (resolve_decision only ever
    appends a separate DecisionResolution + second Evidence row), so
    this rejection is permanent, not merely "not yet resolved"."""
    from app.services import resolution_service

    org = _org(db)
    identity, _cv, binding, agent = _setup(db, org.id)
    _deploy_policy(db, org.id, opa_url, effect=Effect.REQUIRE_HUMAN_REVIEW)
    _intent, decision, _evidence = _attest(db, identity, binding, agent)
    assert decision.outcome == "HUMAN_REVIEW"

    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="reviewer@example.com")
    db.refresh(decision)
    assert decision.outcome == "HUMAN_REVIEW"  # never rewritten

    with pytest.raises(capability_service.DecisionNotAllowError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")


# --- Cross-tenant --------------------------------------------------------


def test_cross_tenant_adapter_capability_issuance_is_denied(db, opa_url):
    org = _org(db)
    _identity, _cv, _binding, _agent, _intent, decision = _allow_adapter_decision(db, org, opa_url)
    other_org = Organization(id=uuid.uuid4(), name="Org B")
    db.add(other_org)
    db.commit()

    from app.services.intent_service import CrossOrganizationAccessError

    with pytest.raises(CrossOrganizationAccessError):
        capability_service.issue_capability_for_decision(db, other_org.id, decision.id, audience="reference-adapter")


def test_cross_organization_binding_reuse_is_rejected_by_audience(db, opa_url):
    """Mirrors test_capability_tokens.py's own documented behavior for
    Agent-direct: cross-tenant misuse is prevented by audience (and now
    also environment/binding) mismatch, not a separate organization
    check inside verify_and_consume_capability itself -- confirmed here
    for the Adapter-mediated path too, not assumed."""
    org_a = _org(db, "Org A")
    _identity, _cv, binding, _agent, intent, decision = _allow_adapter_decision(db, org_a, opa_url)
    issued = _issue(db, org_a, decision, audience="org-a-adapter")

    with pytest.raises(capability_token.CapabilityAudienceMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "org-b-adapter", "vendor_payment", intent.resource, {},
        )


# --- Signing key rotation -------------------------------------------------


def test_adapter_capability_verifies_after_signing_key_rotation(db, opa_url):
    """Key rotation never breaks verification of an already-issued
    capability -- the same guarantee Evidence already has, reused
    unchanged (signing_key_service's own historical key_id lookup by the
    key_id embedded in the token itself, not whatever key is active
    now)."""
    import base64

    import nacl.signing

    original_key_b64, original_key_id = settings.evidence_signing_key_b64, settings.evidence_signing_key_id
    org = _org(db)
    _identity, _cv, binding, _agent, intent, decision = _allow_adapter_decision(db, org, opa_url)
    issued = _issue(db, org, decision)

    new_signing_key = nacl.signing.SigningKey.generate()
    new_signing_key_b64 = base64.b64encode(bytes(new_signing_key)).decode()
    new_public_key_b64 = base64.b64encode(bytes(new_signing_key.verify_key)).decode()
    new_key_id = "rotated-key-2"
    signing_key_service.ensure_current_key_registered(db, new_key_id, new_public_key_b64)
    settings.evidence_signing_key_b64 = new_signing_key_b64
    settings.evidence_signing_key_id = new_key_id
    try:
        # The token was signed under the OLD key, already registered by
        # this file's own `db` fixture -- it must still verify correctly
        # even though a different key is now active for new issuance.
        consumed = capability_service.verify_and_consume_capability(
            db, issued.token, "reference-adapter", "vendor_payment", intent.resource,
            {"environment": binding.environment},
        )
        assert consumed is not None
    finally:
        settings.evidence_signing_key_b64, settings.evidence_signing_key_id = original_key_b64, original_key_id


# --- Receipt/Decision-detail surfacing ---------------------------------------


def test_receipt_shows_adapter_capability_with_execution_disclaimer_intact(db, opa_url):
    from app.services import authorization_receipt_service

    org = _org(db)
    _identity, _cv, binding, _agent, _intent, decision = _allow_adapter_decision(db, org, opa_url)
    capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")

    receipt = authorization_receipt_service.get_authorization_receipt(db, decision.id, org.id)
    assert receipt.capability is not None
    assert receipt.capability.issued is True
    assert receipt.capability.environment == binding.environment
    assert receipt.integration is not None  # Phase 4 provenance, unaffected by this milestone


# --- Enforcement assurance (sections 30/31) ----------------------------------


def test_enforcement_assurance_defaults_to_advisory(db, opa_url):
    org = _org(db)
    _identity, _cv, binding, _agent = _setup(db, org.id)
    assert binding.enforcement_assurance == "ADVISORY"


def test_enforcement_assurance_can_be_set_to_capability_required(db, opa_url):
    org = _org(db)
    _identity, _cv, binding, _agent = _setup(db, org.id)
    updated = binding_svc.set_enforcement_assurance(db, binding.id, org.id, "CAPABILITY_REQUIRED")
    assert updated.enforcement_assurance == "CAPABILITY_REQUIRED"


@pytest.mark.parametrize("bad_value", ["VERIFIED", "REGISTERED_EXTERNAL_PEP", "DECLARED_DECISION_CHECK", "not_a_real_value"])
def test_enforcement_assurance_rejects_unimplemented_levels(db, opa_url, bad_value):
    """Section 32: no code path may set VERIFIED or
    REGISTERED_EXTERNAL_PEP -- this phase never registers or
    authenticates a distinct external PEP workload, so those levels
    would be fake completeness, not a real claim."""
    org = _org(db)
    _identity, _cv, binding, _agent = _setup(db, org.id)
    with pytest.raises(binding_svc.InvalidEnforcementAssuranceError):
        binding_svc.set_enforcement_assurance(db, binding.id, org.id, bad_value)
