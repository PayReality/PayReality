"""Trusted Integration Architecture, Phase 6 (Reference End-to-End
Enforcement Demonstration): drives the complete, real authority-to-
execution loop this milestone exists to prove -- an Agent attempts a
business operation, a Trusted Adapter observes and reports it through
an approved Action Mapping, PayReality evaluates it to HUMAN_REVIEW, an
authorized reviewer approves it (the original Decision never changes),
a Capability is issued from that approval, a reference Policy
Enforcement Point verifies and consumes it, and only then does a
reference downstream business system "execute." Then it proves the
required negative demonstrations: the same Capability cannot be reused,
and a second Capability cannot be minted for the same authority
lifecycle.

Real SQLite + real ephemeral OPA throughout, the same established
convention as test_capability_issuance_idempotency.py, whose fixture
helpers this file mirrors closely on purpose. This file is deliberately
NOT a re-run of every scenario Phase 5.1's own test file already covers
(revoked Agent/Identity/Binding, wrong environment/binding/audience,
cross-tenant, expired-no-renewal) -- those are proven there and remain
in force, referenced rather than duplicated wholesale. What is new here:
the full scenario stitched into one real, runnable sequence matching
this milestone's own recommended reference scenario (a supplier
bank-details change -- canonically the same `vendor_payment` action every
earlier milestone's own demo fixture already uses for this identical
scenario (the closed action vocabulary, scope_vocabulary.py's
KNOWN_SCOPES, has no separate "change bank details" action of its own),
but with no amount/currency at all, proving the constraints model
doesn't secretly require them), the reference PEP script's own
execute_downstream_operation() actually being invoked (not mocked away)
after real consumption, and the specific negative demonstrations
section 5 of this milestone's brief requires: replaying a consumed
Capability through the real verify-and-consume path, and requesting a
second Capability against the same already-issued authority lifecycle.
"""

import importlib.util
import uuid
from datetime import datetime, timezone
from pathlib import Path

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
    resolution_service,
    runtime_policy_service as policy_svc,
    signing_key_service,
)

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "reference_enforcement_adapter.py"
_spec = importlib.util.spec_from_file_location("reference_enforcement_adapter_e2e", _SCRIPT_PATH)
reference_pep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reference_pep)

ACTION = "vendor_payment"  # the only real, closed-vocabulary action a supplier bank-details change canonically maps to -- see scope_vocabulary.py's KNOWN_SCOPES; the same mapping the existing demo fixture (DECISION_HERO_ADAPTER_REVIEW) already uses for this identical scenario
RESOURCE = "supplier:SUPPLIER_482"
SOURCE_OPERATION = "ChangeSupplierBankDetails"
AUDIENCE = "reference-pep"


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


def _org(db, name="Org Phase 6"):
    org = Organization(id=uuid.uuid4(), name=name)
    db.add(org)
    db.commit()
    return org


def _deploy_human_review_policy(db, org_id, opa_url):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="supplier bank details require review", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="FinanceAgent01", action=ACTION, resource=RESOURCE),
        conditions=ConditionSet(all=()), effect=Effect.REQUIRE_HUMAN_REVIEW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)


def _scenario(db, org_id, opa_url, environment="demo", external_operation_id=None):
    """The full reference scenario's setup, from a trusted connection
    with an approved mapping through to the FinanceAgent01 whose
    attempted bank-details change is about to be attested. A non-
    financial action (no amount_path/currency_path bound at all) --
    this milestone's own recommended scenario, deliberately different
    from every earlier milestone's vendor_payment example, proving the
    Capability/constraints model generalizes."""
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "Reference Business System Adapter", "ed25519:base64:AAAA")
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)
    integration = contract_svc.create_integration(db, org_id, "Reference Business System")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, SOURCE_OPERATION, ACTION,
        resource_path="supplier.id", amount_path=None, currency_path=None,
        fact_subject_path=None, context_bindings={},
    )
    contract_version = contract_svc.validate_contract_version(db, contract_version.id, org_id)
    contract_version = contract_svc.approve_contract_version(db, contract_version.id, org_id, approver="governance-admin@example.com")

    principal = Principal(id=uuid.uuid4(), name="FinanceAgent01", organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="Finance Agent 01", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()

    binding = binding_svc.create_draft_binding(db, org_id, identity.id, contract_version.id, environment, agent_ids=[agent.id])
    binding = binding_svc.activate_binding(db, binding.id, org_id)

    _deploy_human_review_policy(db, org_id, opa_url)

    intent, decision, _evidence = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=RESOURCE,
        amount=None, currency=None, counterparty=None, context={}, requested_at=datetime.now(timezone.utc),
        nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=external_operation_id or uuid.uuid4().hex,
    )
    assert decision.outcome == "HUMAN_REVIEW", "the reference scenario's whole point is starting at HUMAN_REVIEW"
    return identity, contract_version, binding, agent, intent, decision


# === The full happy path, end to end, through the real reference PEP script =====


def test_full_reference_scenario_authority_to_execution(db, opa_url):
    """Section 19's own completion criteria, exercised in one real
    sequence: attest -> HUMAN_REVIEW -> approve -> the original Decision
    still reads HUMAN_REVIEW -> issue Capability from the approved
    review -> the real reference PEP script verifies, consumes, and
    only then invokes the reference downstream business system."""
    org = _org(db)
    identity, _cv, binding, agent, intent, decision = _scenario(db, org.id, opa_url)

    # A legitimate reviewer, holding Permission.DECISIONS_RESOLVE in the
    # real RBAC model, approves.
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="governance-admin@example.com")

    db.refresh(decision)
    assert decision.outcome == "HUMAN_REVIEW", "section 9/19: the original Decision must never be rewritten"

    issued = capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience=AUDIENCE)
    assert issued.token

    row = db.get(CapabilityToken, issued.capability_id)
    assert row.integration_identity_id == identity.id
    assert row.enforcement_binding_id == binding.id
    assert row.external_operation_id == intent.external_operation_id

    def fake_verify_and_consume(token, audience, action, resource, constraints, environment=None, enforcement_binding_id=None, principal=None):
        consumed = capability_service.verify_and_consume_capability(
            db, token, audience, action, resource, constraints,
            environment=environment, enforcement_binding_id=enforcement_binding_id, principal=principal,
        )
        return reference_pep.VerifyResult(ok=True, capability_id=str(consumed.capability_id), decision_id=str(consumed.decision_id), reason=None)

    real_verify_and_consume = reference_pep.verify_and_consume
    reference_pep.verify_and_consume = fake_verify_and_consume
    try:
        ok = reference_pep.run(
            issued.token, AUDIENCE, ACTION, RESOURCE, {"environment": binding.environment},
            environment=binding.environment, enforcement_binding_id=str(binding.id), principal="FinanceAgent01",
        )
    finally:
        reference_pep.verify_and_consume = real_verify_and_consume

    assert ok is True, "the reference PEP must report success: real consumption, real (reference) downstream execution"

    db.refresh(row)
    assert row.consumed_at is not None
    db.refresh(decision)
    assert decision.outcome == "HUMAN_REVIEW", "still never rewritten, even after a real execution happened downstream of it"


# === Negative demonstration 1: replaying a consumed Capability ==================


def test_replaying_a_consumed_capability_is_refused_and_never_reaches_downstream_execution(db, opa_url):
    """Section 5's own required negative demonstration, through the
    real reference PEP script's own run() function, not simulated in a
    UI: the SECOND attempt with the SAME token must fail because the
    Capability was already consumed, and execute_downstream_operation
    must never be called for it."""
    org = _org(db)
    _identity, _cv, binding, _agent, _intent, decision = _scenario(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="governance-admin@example.com")
    issued = capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience=AUDIENCE)

    def fake_verify_and_consume(token, audience, action, resource, constraints, **kwargs):
        try:
            consumed = capability_service.verify_and_consume_capability(db, token, audience, action, resource, constraints, **kwargs)
        except capability_service.CapabilityTokenAlreadyConsumedError:
            return reference_pep.VerifyResult(ok=False, capability_id=None, decision_id=None, reason="capability_token_already_consumed")
        return reference_pep.VerifyResult(ok=True, capability_id=str(consumed.capability_id), decision_id=str(consumed.decision_id), reason=None)

    execute_calls = {"n": 0}
    real_execute = reference_pep.execute_downstream_operation
    real_verify_and_consume = reference_pep.verify_and_consume

    def counting_execute(action, resource, constraints):
        execute_calls["n"] += 1
        return real_execute(action, resource, constraints)

    reference_pep.verify_and_consume = fake_verify_and_consume
    reference_pep.execute_downstream_operation = counting_execute
    try:
        first = reference_pep.run(issued.token, AUDIENCE, ACTION, RESOURCE, {"environment": binding.environment}, environment=binding.environment)
        second = reference_pep.run(issued.token, AUDIENCE, ACTION, RESOURCE, {"environment": binding.environment}, environment=binding.environment)
    finally:
        reference_pep.verify_and_consume = real_verify_and_consume
        reference_pep.execute_downstream_operation = real_execute

    assert first is True
    assert second is False, "the second attempt with the same, already-consumed token must be refused"
    assert execute_calls["n"] == 1, "downstream execution must have run exactly once -- never for the replayed attempt"


# === Negative demonstration 2: a second Capability for the same authority lifecycle =


def test_requesting_a_second_capability_after_issuance_fails_no_replacement_minted(db, opa_url):
    """Section 5's second required negative demonstration: after a
    Capability already exists for this Decision (whether or not it has
    been consumed yet), requesting another must fail -- never silently
    mint a replacement, never fabricate a fresh Decision to make the
    demonstration "work.\""""
    org = _org(db)
    _identity, _cv, _binding, _agent, _intent, decision = _scenario(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="governance-admin@example.com")
    first = capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience=AUDIENCE)

    with pytest.raises(capability_service.CapabilityAlreadyIssuedError) as excinfo:
        capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience=AUDIENCE)
    assert excinfo.value.capability_id == first.capability_id

    rows = db.scalars(select(CapabilityToken).where(CapabilityToken.decision_id == decision.id)).all()
    assert len(rows) == 1


# === DENY / unresolved / denied review can never reach downstream execution =====


def test_deny_outcome_can_never_reach_downstream_execution(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _setup_reference_adapter_deny(db, org.id, opa_url)
    intent, decision, _evidence = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=RESOURCE,
        amount=None, currency=None, counterparty=None, context={}, requested_at=datetime.now(timezone.utc),
        nonce=uuid.uuid4().hex, correlation_id=None, external_operation_id=uuid.uuid4().hex,
    )
    assert decision.outcome == "DENY"

    with pytest.raises(capability_service.DecisionNotAllowError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience=AUDIENCE)
    with pytest.raises(capability_service.DecisionNotHumanReviewError):
        capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience=AUDIENCE)

    assert db.scalars(select(CapabilityToken).where(CapabilityToken.decision_id == decision.id)).first() is None


def _setup_reference_adapter_deny(db, org_id, opa_url):
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "Reference Business System Adapter", "ed25519:base64:AAAA")
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)
    integration = contract_svc.create_integration(db, org_id, "Reference Business System")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, SOURCE_OPERATION, ACTION,
        resource_path="supplier.id", amount_path=None, currency_path=None,
        fact_subject_path=None, context_bindings={},
    )
    contract_version = contract_svc.validate_contract_version(db, contract_version.id, org_id)
    contract_version = contract_svc.approve_contract_version(db, contract_version.id, org_id, approver="governance-admin@example.com")
    principal = Principal(id=uuid.uuid4(), name="FinanceAgent01", organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="Finance Agent 01", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    binding = binding_svc.create_draft_binding(db, org_id, identity.id, contract_version.id, "demo", agent_ids=[agent.id])
    binding = binding_svc.activate_binding(db, binding.id, org_id)

    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="deny bank details change", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="FinanceAgent01", action=ACTION, resource=RESOURCE),
        conditions=ConditionSet(all=()), effect=Effect.DENY,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return identity, contract_version, binding, agent


def test_unresolved_human_review_can_never_reach_downstream_execution(db, opa_url):
    org = _org(db)
    _identity, _cv, _binding, _agent, _intent, decision = _scenario(db, org.id, opa_url)
    with pytest.raises(capability_service.ReviewNotResolvedError):
        capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience=AUDIENCE)
    assert db.scalars(select(CapabilityToken).where(CapabilityToken.decision_id == decision.id)).first() is None


def test_denied_human_review_can_never_reach_downstream_execution(db, opa_url):
    org = _org(db)
    _identity, _cv, _binding, _agent, _intent, decision = _scenario(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="denied", resolved_by="governance-admin@example.com")
    with pytest.raises(capability_service.ReviewNotApprovedError):
        capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience=AUDIENCE)
    assert db.scalars(select(CapabilityToken).where(CapabilityToken.decision_id == decision.id)).first() is None


# === Wrong-scope hostile attempts specific to the reference scenario ============


def test_capability_for_wrong_resource_is_refused(db, opa_url):
    org = _org(db)
    _identity, _cv, binding, _agent, _intent, decision = _scenario(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="governance-admin@example.com")
    issued = capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience=AUDIENCE)

    from app.domain.capability import token as capability_token

    with pytest.raises(capability_token.CapabilityConstraintMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued.token, AUDIENCE, ACTION, "supplier:SOME_OTHER_SUPPLIER", {"environment": binding.environment},
            environment=binding.environment,
        )


def test_capability_for_wrong_principal_is_refused(db, opa_url):
    org = _org(db)
    _identity, _cv, binding, _agent, _intent, decision = _scenario(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="governance-admin@example.com")
    issued = capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience=AUDIENCE)

    from app.domain.capability import token as capability_token

    with pytest.raises(capability_token.CapabilityConstraintMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued.token, AUDIENCE, ACTION, RESOURCE, {"environment": binding.environment},
            environment=binding.environment, principal="SomeoneElseEntirely",
        )


def test_capability_for_wrong_environment_is_refused(db, opa_url):
    org = _org(db)
    _identity, _cv, binding, _agent, _intent, decision = _scenario(db, org.id, opa_url, environment="demo")
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="governance-admin@example.com")
    issued = capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience=AUDIENCE)

    from app.domain.capability import token as capability_token

    with pytest.raises(capability_token.CapabilityBindingMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued.token, AUDIENCE, ACTION, RESOURCE, {"environment": "demo"},
            environment="production",
        )


def test_revoked_agent_after_approval_but_before_issuance_fails_closed(db, opa_url):
    """Section 13's own ordering: identities can be revoked at any of
    several points in this sequence. This one -- after approval, before
    Capability issuance -- is the case most specific to the post-review
    path Phase 5.1 added; the ordinary pre-review-approval cases are
    already covered by Phase 5.1's own test file."""
    org = _org(db)
    _identity, _cv, _binding, agent, _intent, decision = _scenario(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="governance-admin@example.com")
    agent_service.suspend_agent(db, agent.id)

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience=AUDIENCE)


def test_revoked_integration_identity_after_issuance_but_before_verification_fails_closed(db, opa_url):
    """Section 13's other ordering: revoked AFTER issuance, before
    verification. Capability issuance itself only re-checks live status
    at the moment of issuance (Phase 5's own documented TOCTOU limit,
    SPECIFICATION/14_SECURITY_MODEL.md sS14.8) -- an already-issued,
    unexpired token still verifies successfully even if the identity is
    revoked a moment later, since verify_and_consume_capability checks
    the token's own signed claim, not live database state. This test
    documents that honestly rather than asserting a guarantee that
    doesn't exist."""
    org = _org(db)
    identity, _cv, binding, _agent, _intent, decision = _scenario(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="governance-admin@example.com")
    issued = capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience=AUDIENCE)

    identity_svc.suspend_integration_identity(db, identity.id, org.id)

    # Documented, not a regression: verification is against the token's
    # own signed claim (what was true at issuance), never a fresh
    # database lookup of current identity status.
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, AUDIENCE, ACTION, RESOURCE, {"environment": binding.environment},
        environment=binding.environment,
    )
    assert consumed is not None


# === Business operation idempotency composes correctly with this scenario =======


def test_transport_retry_after_approval_does_not_create_a_new_decision_or_bypass_issuance(db, opa_url):
    """Section 6: a retried business operation (same external_operation_id,
    same authority-relevant fields) must still resolve to the SAME
    Decision, even after that Decision has already been approved and had
    a Capability issued from it -- a transport-level retry must never
    accidentally create a second authority lifecycle for the same real
    operation."""
    org = _org(db)
    external_operation_id = "OP-92819"
    identity, _cv, binding, agent, intent1, decision1 = _scenario(db, org.id, opa_url, external_operation_id=external_operation_id)
    resolution_service.resolve_decision(db, decision1.id, org.id, resolution="approved", resolved_by="governance-admin@example.com")
    capability_service.issue_capability_for_reviewed_decision(db, org.id, decision1.id, audience=AUDIENCE)

    intent2, decision2, _evidence2 = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=RESOURCE,
        amount=None, currency=None, counterparty=None, context={}, requested_at=datetime.now(timezone.utc),
        nonce=uuid.uuid4().hex, correlation_id=None, external_operation_id=external_operation_id,
    )

    assert decision2.id == decision1.id, "the retried operation must resolve to the same Decision, not a fresh evaluation"

    with pytest.raises(capability_service.CapabilityAlreadyIssuedError):
        capability_service.issue_capability_for_reviewed_decision(db, org.id, decision2.id, audience=AUDIENCE)
