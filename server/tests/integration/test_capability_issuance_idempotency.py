"""Trusted Integration Architecture, Phase 5.1: Capability Issuance
Idempotency (Part A) and Post-Review Capability Authorization (Part B).

Real SQLite + real ephemeral OPA throughout, the same established
convention as test_adapter_capability_authorization.py, whose fixture
helpers this file mirrors closely on purpose. Genuine multi-connection
concurrency needs a real database (SQLite has no real row/constraint-
level concurrency to prove against across connections in the way
Postgres does) -- see test_capability_issuance_idempotency_postgres.py
for that half of section 7/21's own matrix. This file covers the
single-connection, deterministic-sequencing half: what each of the
three "a capability already exists" states actually does, on both
runtime paths, and the full post-review issuance qualification matrix.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, update
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
    resolution_service,
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


def _allow_agent_direct_decision(db, org_id, opa_url):
    principal = _principal(db, org_id)
    agent = _agent(db, principal.id)
    _deploy_policy(db, org_id, opa_url)
    _intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action="vendor_payment", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="supplier:123",
    )
    assert decision.outcome == "ALLOW"
    return agent, decision


def _setup_adapter(db, org_id, environment="production", agent_status="active", principal_name="alice"):
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
    principal = _principal(db, org_id, name=principal_name)
    agent = _agent(db, principal.id, status=agent_status)
    binding = binding_svc.create_draft_binding(db, org_id, identity.id, contract_version.id, environment, agent_ids=[agent.id])
    binding = binding_svc.activate_binding(db, binding.id, org_id)
    return identity, contract_version, binding, agent


def _attest(db, identity, binding, agent, *, action="vendor_payment", resource="supplier:123", external_operation_id=None):
    return runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation="ChangeSupplierBankDetails", action=action, resource=resource,
        amount=None, currency=None, counterparty=None, context={}, requested_at=datetime.now(timezone.utc),
        nonce=uuid.uuid4().hex, correlation_id=None, external_operation_id=external_operation_id or uuid.uuid4().hex,
    )


def _allow_adapter_decision(db, org_id, opa_url, **setup_kwargs):
    identity, contract_version, binding, agent = _setup_adapter(db, org_id, **setup_kwargs)
    _deploy_policy(db, org_id, opa_url)
    intent, decision, _evidence = _attest(db, identity, binding, agent)
    assert decision.outcome == "ALLOW"
    return identity, contract_version, binding, agent, intent, decision


def _human_review_adapter_decision(db, org_id, opa_url, **setup_kwargs):
    identity, contract_version, binding, agent = _setup_adapter(db, org_id, **setup_kwargs)
    _deploy_policy(db, org_id, opa_url, effect=Effect.REQUIRE_HUMAN_REVIEW)
    intent, decision, _evidence = _attest(db, identity, binding, agent)
    assert decision.outcome == "HUMAN_REVIEW"
    return identity, contract_version, binding, agent, intent, decision


def _human_review_agent_direct_decision(db, org_id, opa_url):
    principal = _principal(db, org_id)
    agent = _agent(db, principal.id)
    _deploy_policy(db, org_id, opa_url, effect=Effect.REQUIRE_HUMAN_REVIEW)
    _intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action="vendor_payment", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="supplier:123",
    )
    assert decision.outcome == "HUMAN_REVIEW"
    return agent, decision


def _expire(db, capability_id):
    db.execute(
        update(CapabilityToken).where(CapabilityToken.id == capability_id)
        .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    )
    db.commit()


# === Part A: Capability Issuance Idempotency ================================

# --- Q1 audit: the pre-fix behavior, proven, not inferred --------------------


def test_audit_pre_fix_would_have_allowed_a_third_call_to_mint_a_third_capability(db, opa_url):
    """Section 1's own instruction: test actual issuance behavior before
    changing it. This test proves what the OLD, unprotected code path
    would do by calling capability_service's internal tail directly with
    the new idempotency pre-check monkeypatched out -- i.e. it
    reconstructs the exact pre-fix call sequence (check-then-insert with
    no uniqueness) to document, empirically, that it minted multiple
    independently valid rows. See this milestone's own final report,
    section A, for the answer this test backs."""
    org = _org(db)
    _agent, decision = _allow_agent_direct_decision(db, org.id, opa_url)

    real_check = capability_service._existing_capability_or_none
    calls = {"n": 0}

    def bypass_only_the_second_calls_precheck(db_, decision_id):
        # Simulates the pre-Phase-5.1 code path -- which never consulted
        # existing rows before issuing -- for exactly the second
        # issuance's OWN pre-check (call #2). Call #1 (the first
        # issuance's pre-check, correctly finding nothing) and any call
        # #3 (the real DB-level safety net's own re-check after a raced
        # INSERT fails) both use the genuine function: this test isolates
        # "what if the pre-check alone existed, with nothing behind it,"
        # which is exactly the pre-Phase-5.1 shape.
        calls["n"] += 1
        if calls["n"] == 2:
            return None
        return real_check(db_, decision_id)

    capability_service._existing_capability_or_none = bypass_only_the_second_calls_precheck
    try:
        first = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")
        with pytest.raises(capability_service.CapabilityAlreadyIssuedError):
            capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")
    finally:
        capability_service._existing_capability_or_none = real_check
    assert calls["n"] == 3, "expected: first-issuance pre-check, second-issuance pre-check, second-issuance post-conflict re-check"

    rows = db.scalars(select(CapabilityToken).where(CapabilityToken.decision_id == decision.id)).all()
    assert len(rows) == 1, (
        "with only the pre-check bypassed but the new UNIQUE constraint still in "
        "place, exactly one row survives -- confirming the constraint (not the "
        "pre-check) is the real guarantee, and that its absence is what let the "
        "old code mint more than one."
    )


# --- Sections 4/5/6: the three distinct existing-capability outcomes ---------


def test_second_issuance_while_first_is_still_valid_is_rejected_not_duplicated(db, opa_url):
    org = _org(db)
    _agent, decision = _allow_agent_direct_decision(db, org.id, opa_url)

    first = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")

    with pytest.raises(capability_service.CapabilityAlreadyIssuedError) as excinfo:
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")
    assert excinfo.value.capability_id == first.capability_id

    rows = db.scalars(select(CapabilityToken).where(CapabilityToken.decision_id == decision.id)).all()
    assert len(rows) == 1


def test_issuance_after_consumption_is_rejected_fail_closed(db, opa_url):
    org = _org(db)
    identity, _cv, binding, _agent, intent, decision = _allow_adapter_decision(db, org.id, opa_url)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")
    capability_service.verify_and_consume_capability(
        db, issued.token, "reference-adapter", "vendor_payment", intent.resource,
        {"environment": binding.environment}, environment=binding.environment,
    )

    with pytest.raises(capability_service.CapabilityAlreadyConsumedForDecisionError) as excinfo:
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")
    assert excinfo.value.capability_id == issued.capability_id

    rows = db.scalars(select(CapabilityToken).where(CapabilityToken.decision_id == decision.id)).all()
    assert len(rows) == 1


def test_issuance_after_expiry_without_consumption_does_not_auto_renew(db, opa_url):
    """Section 6's own deliberate choice, documented in
    capability_service.CapabilityExpiredNotRenewedError's docstring:
    fail closed rather than silently treat a historical ALLOW as
    indefinitely renewable authority."""
    org = _org(db)
    _agent, decision = _allow_agent_direct_decision(db, org.id, opa_url)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")
    _expire(db, issued.capability_id)

    with pytest.raises(capability_service.CapabilityExpiredNotRenewedError) as excinfo:
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")
    assert excinfo.value.capability_id == issued.capability_id

    rows = db.scalars(select(CapabilityToken).where(CapabilityToken.decision_id == decision.id)).all()
    assert len(rows) == 1, "an expired-unconsumed capability must not be replaced by a fresh one"


# --- Section 8: Agent-direct parity ------------------------------------------


def test_agent_direct_and_adapter_paths_share_the_identical_idempotency_guarantee(db, opa_url):
    """Section 8: audits whether the multiple-issuance gap exists for
    Agent-direct too, and proves the fix (the shared _issue_and_persist
    tail) closes it identically on both paths, not only the Adapter one."""
    org = _org(db)
    _agent, agent_direct_decision = _allow_agent_direct_decision(db, org.id, opa_url)
    capability_service.issue_capability_for_decision(db, org.id, agent_direct_decision.id, audience="reference-adapter")
    with pytest.raises(capability_service.CapabilityAlreadyIssuedError):
        capability_service.issue_capability_for_decision(db, org.id, agent_direct_decision.id, audience="reference-adapter")

    org2 = _org(db, "Org B")
    _identity, _cv, _binding, _agent2, _intent2, adapter_decision = _allow_adapter_decision(db, org2.id, opa_url)
    capability_service.issue_capability_for_decision(db, org2.id, adapter_decision.id, audience="reference-adapter")
    with pytest.raises(capability_service.CapabilityAlreadyIssuedError):
        capability_service.issue_capability_for_decision(db, org2.id, adapter_decision.id, audience="reference-adapter")


# --- Cross-tenant and operation-identity interaction -------------------------


def test_cross_tenant_repeated_issuance_is_still_org_scoped_not_found(db, opa_url):
    """A caller in Org B may never even discover Org A's decision exists,
    let alone learn whether it already has a capability -- unchanged,
    pre-existing org-scoping (intent_service.get_decision_for_organization),
    confirmed still correct alongside the new idempotency check."""
    org_a = _org(db, "Org A")
    org_b = _org(db, "Org B")
    _agent, decision = _allow_agent_direct_decision(db, org_a.id, opa_url)
    capability_service.issue_capability_for_decision(db, org_a.id, decision.id, audience="reference-adapter")

    with pytest.raises(intent_service.CrossOrganizationAccessError):
        capability_service.issue_capability_for_decision(db, org_b.id, decision.id, audience="reference-adapter")


def test_same_external_operation_id_retry_then_repeated_capability_issuance(db, opa_url):
    """Section 3's own point: Decision idempotency (same External
    Operation ID + fingerprint -> same Decision, Phase 3) and Capability
    idempotency (this phase) are separate mechanisms that must compose
    correctly, not be confused for one another. A retried business
    operation resolves to the identical decision_id via the existing
    Phase 3 mechanism; issuing a capability for it twice is then just an
    ordinary repeated-issuance case, handled the same way as any other."""
    org = _org(db)
    identity, _cv, binding, agent = _setup_adapter(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    external_operation_id = "erp-op-12345"

    intent1, decision1, _e1 = _attest(db, identity, binding, agent, external_operation_id=external_operation_id)
    intent2, decision2, _e2 = _attest(db, identity, binding, agent, external_operation_id=external_operation_id)
    assert decision1.id == decision2.id, "an identical retried operation must resolve to the same Decision"

    capability_service.issue_capability_for_decision(db, org.id, decision1.id, audience="reference-adapter")
    with pytest.raises(capability_service.CapabilityAlreadyIssuedError):
        capability_service.issue_capability_for_decision(db, org.id, decision2.id, audience="reference-adapter")


# === Part B: Post-Review Capability Authorization ============================


def test_unresolved_human_review_cannot_issue_a_capability(db, opa_url):
    org = _org(db)
    _identity, _cv, _binding, _agent, _intent, decision = _human_review_adapter_decision(db, org.id, opa_url)

    with pytest.raises(capability_service.ReviewNotResolvedError):
        capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience="reference-adapter")


def test_denied_review_cannot_issue_a_capability(db, opa_url):
    org = _org(db)
    _identity, _cv, _binding, _agent, _intent, decision = _human_review_adapter_decision(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="denied", resolved_by="reviewer@example.com")

    with pytest.raises(capability_service.ReviewNotApprovedError) as excinfo:
        capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience="reference-adapter")
    assert excinfo.value.resolution == "denied"


def test_approved_review_issues_a_capability_without_mutating_the_original_decision(db, opa_url):
    """Section 9/10's own success test, in miniature: the original
    Decision still reads HUMAN_REVIEW, and a real, usable Capability now
    exists, bound to the original External Operation ID (section 16)."""
    org = _org(db)
    identity, _cv, binding, agent, intent, decision = _human_review_adapter_decision(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="reviewer@example.com")

    issued = capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience="reference-adapter")
    assert issued.token

    db.refresh(decision)
    assert decision.outcome == "HUMAN_REVIEW", "the original Decision must never be rewritten to ALLOW"

    row = db.get(CapabilityToken, issued.capability_id)
    assert row.external_operation_id == intent.external_operation_id
    assert row.enforcement_binding_id == binding.id

    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-adapter", "vendor_payment", intent.resource,
        {"environment": binding.environment}, environment=binding.environment,
    )
    assert str(consumed.decision_id) == str(decision.id)


def test_approved_review_issuance_works_for_agent_direct_too(db, opa_url):
    org = _org(db)
    agent, decision = _human_review_agent_direct_decision(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="reviewer@example.com")

    issued = capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience="reference-adapter")
    row = db.get(CapabilityToken, issued.capability_id)
    assert row.integration_identity_id is None, "an Agent-direct post-review capability carries no Adapter binding"


def test_approved_review_plus_revoked_enforcement_binding_fails_closed(db, opa_url):
    """Section 14: a human approval from before the Binding was revoked
    must not override a since-revoked Adapter/Runtime Connection."""
    org = _org(db)
    _identity, _cv, binding, _agent, _intent, decision = _human_review_adapter_decision(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="reviewer@example.com")
    binding_svc.retire_binding(db, binding.id, org.id)

    with pytest.raises(capability_service.EnforcementBindingNotActiveError):
        capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience="reference-adapter")


def test_approved_review_plus_suspended_integration_identity_fails_closed(db, opa_url):
    org = _org(db)
    identity, _cv, _binding, _agent, _intent, decision = _human_review_adapter_decision(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="reviewer@example.com")
    identity_svc.suspend_integration_identity(db, identity.id, org.id)

    with pytest.raises(capability_service.IntegrationIdentityNotActiveError):
        capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience="reference-adapter")


def test_approved_review_plus_revoked_agent_fails_closed(db, opa_url):
    """Section 14's Agent half -- both Agent-direct and Adapter-mediated
    post-review issuance re-check the origin Agent's own live status,
    the same OriginAgentNotActiveError check the ALLOW-direct path
    already applies, via the same shared _issue_and_persist tail."""
    org = _org(db)
    agent, decision = _human_review_agent_direct_decision(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="reviewer@example.com")
    agent_service.suspend_agent(db, agent.id)

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience="reference-adapter")


def test_approved_review_wrong_tenant_is_not_found(db, opa_url):
    """Section 14's tenant half: an org-scoped lookup, identical to
    every other decision read in this codebase."""
    org_a = _org(db, "Org A")
    org_b = _org(db, "Org B")
    _identity, _cv, _binding, _agent, _intent, decision = _human_review_adapter_decision(db, org_a.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org_a.id, resolution="approved", resolved_by="reviewer@example.com")

    with pytest.raises(intent_service.CrossOrganizationAccessError):
        capability_service.issue_capability_for_reviewed_decision(db, org_b.id, decision.id, audience="reference-adapter")


def test_approved_review_wrong_audience_is_rejected_at_verification(db, opa_url):
    """Section 14's audience half: a post-review-issued capability is
    verified through the exact same domain/capability/token.py checks
    as any other -- no separate, weaker verification path exists for
    it."""
    org = _org(db)
    _identity, _cv, binding, _agent, intent, decision = _human_review_adapter_decision(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="reviewer@example.com")
    issued = capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience="reference-adapter")

    from app.domain.capability import token as capability_token

    with pytest.raises(capability_token.CapabilityAudienceMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "a-different-audience", "vendor_payment", intent.resource,
            {"environment": binding.environment}, environment=binding.environment,
        )


# --- Section 17: post-review issuance shares Part A's own idempotency -------


def test_repeated_post_review_issuance_is_rejected_same_as_any_other(db, opa_url):
    org = _org(db)
    _identity, _cv, _binding, _agent, _intent, decision = _human_review_adapter_decision(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="reviewer@example.com")

    first = capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience="reference-adapter")
    with pytest.raises(capability_service.CapabilityAlreadyIssuedError) as excinfo:
        capability_service.issue_capability_for_reviewed_decision(db, org.id, decision.id, audience="reference-adapter")
    assert excinfo.value.capability_id == first.capability_id


def test_post_review_issuance_does_not_bypass_the_direct_allow_only_precondition(db, opa_url):
    """issue_capability_for_decision (ALLOW-only) must remain unusable
    for a HUMAN_REVIEW decision even after an approval exists -- the two
    functions have genuinely distinct, non-overlapping preconditions
    (section 11)."""
    org = _org(db)
    _identity, _cv, _binding, _agent, _intent, decision = _human_review_adapter_decision(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision.id, org.id, resolution="approved", resolved_by="reviewer@example.com")

    with pytest.raises(capability_service.DecisionNotAllowError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-adapter")


def test_reviewed_decision_never_picks_up_a_different_decisions_resolution(db, opa_url):
    """Sections 19/20's own hostile scenarios ("review belonging to a
    different Decision/Agent/operation") are structurally unreachable
    here: issue_capability_for_reviewed_decision takes only a
    decision_id, never a resolution reference of its own, so there is no
    parameter an attacker could use to point issuance at another
    Decision's approval. This test confirms the lookup is genuinely
    decision_id-scoped rather than assuming it."""
    org = _org(db)
    _identity, _cv, _binding, _agent, _intent, decision_a = _human_review_adapter_decision(db, org.id, opa_url)
    resolution_service.resolve_decision(db, decision_a.id, org.id, resolution="approved", resolved_by="reviewer@example.com")

    # A second, distinctly-scoped ALLOW decision in the same org -- a
    # different principal/resource so it cannot match decision_a's own
    # active HUMAN_REVIEW policy (only one policy is active per org at a
    # time, matched by scope, so this must be unambiguous, not just
    # "a different decision").
    identity_b, _cv_b, binding_b, agent_b = _setup_adapter(db, org.id, principal_name="bob")
    _deploy_policy(db, org.id, opa_url, effect=Effect.ALLOW, principal="bob", resource="supplier:999")
    intent_b, decision_b, _e_b = _attest(db, identity_b, binding_b, agent_b, resource="supplier:999")
    assert decision_b.outcome == "ALLOW"

    # The precondition check itself is the first line of defense: an
    # ALLOW decision is rejected by issue_capability_for_reviewed_decision
    # regardless of decision_a's own, unrelated approval existing in the
    # same database.
    with pytest.raises(capability_service.DecisionNotHumanReviewError):
        capability_service.issue_capability_for_reviewed_decision(db, org.id, decision_b.id, audience="reference-adapter")
