"""Post-audit implementation, Priority 6: proves execution_reconciliation_
service.reconcile_decision against real, persisted Adapter-mediated
Decisions, real Capability issuance/consumption, and real ingested
execution receipts (execution_receipt_service.submit_execution_receipt) --
not hand-constructed rows -- the same real-path discipline
test_canonical_action_runtime.py and test_execution_receipts.py already
establish for this milestone.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import (
    Agent, Base, CapabilityToken, Evidence, Organization, Principal, ReconciliationResultRecord,
)
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64
from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import (
    capability_service,
    enforcement_binding_service as binding_svc,
    execution_receipt_service as receipt_svc,
    execution_reconciliation_service as reconciliation_svc,
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
    integration_runtime_service as runtime_svc,
    resolution_service,
    runtime_policy_service as policy_svc,
    signing_key_service,
)
from app.services.execution_reconciliation_service import ReconciliationNotApplicableError

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)

ACTION = "supplier_bank_details_change"
RESOURCE = "supplier:SUPPLIER_482"
SOURCE_OPERATION = "ChangeSupplierBankDetails"
DESTINATION = "erp:vendor_master"


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


def _org(db, name="Org Reconciliation"):
    org = Organization(id=uuid.uuid4(), name=name)
    db.add(org)
    db.commit()
    return org


def _deploy_policy(db, org_id, opa_url, effect=Effect.ALLOW):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="reconciliation-test-policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="FinanceAgent01", action=ACTION, resource=RESOURCE),
        conditions=ConditionSet(all=()), effect=effect,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row


def _scenario(db, org_id, *, enforcement_assurance="ADVISORY"):
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "Reference Adapter", "ed25519:base64:AAAA")
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)
    integration = contract_svc.create_integration(db, org_id, "Reference System")
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
    if enforcement_assurance != "ADVISORY":
        binding = binding_svc.set_enforcement_assurance(db, binding.id, org_id, enforcement_assurance)
    return identity, contract_version, binding, agent


def _submit_intent(db, identity, binding, agent, external_operation_id):
    return runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=RESOURCE,
        amount=None, currency=None, counterparty=None, context={}, requested_at=datetime.now(timezone.utc),
        nonce=uuid.uuid4().hex, correlation_id=None, external_operation_id=external_operation_id,
    )


def _issue_and_consume_capability(db, org_id, decision, intent, binding):
    issued = capability_service.issue_capability_for_decision(db, org_id, decision.id, audience="reference-pep")
    resource = intent.resource or intent.correlation_id or str(intent.id)
    return capability_service.verify_and_consume_capability(
        db, issued.token, audience="reference-pep", action=intent.action, resource=resource,
        constraints={"environment": binding.environment}, environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org_id,
    )


def _submit_receipt(db, identity, binding, decision, intent, *, capability_id=None, status="ACCEPTED", destination=DESTINATION):
    return receipt_svc.submit_execution_receipt(
        db, identity, enforcement_binding_id=binding.id, decision_id=decision.id,
        canonical_action_digest=intent.canonical_action_digest,
        external_operation_id=intent.external_operation_id,
        destination=destination, status=status, capability_id=capability_id,
    )


# === MATCHED ===================================================================


def test_a_succeeded_receipt_reconciles_as_matched(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    _submit_receipt(db, identity, binding, decision, intent, status="ACCEPTED")
    _submit_receipt(db, identity, binding, decision, intent, status="SUCCEEDED")

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)

    assert result.outcome == "MATCHED"
    evidence_row = db.get(Evidence, result.evidence_id)
    assert evidence_row.payload["event_type"] == "RECONCILIATION_OUTCOME"
    assert evidence_row.payload["outcome"] == "MATCHED"


def test_matched_with_capability_required_and_consumed(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id, enforcement_assurance="CAPABILITY_REQUIRED")
    _deploy_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    consumed = _issue_and_consume_capability(db, org.id, decision, intent, binding)
    _submit_receipt(db, identity, binding, decision, intent, status="SUCCEEDED", capability_id=consumed.capability_id)

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "MATCHED"
    assert result.capability_id == consumed.capability_id


# === RECEIPT_MISSING ============================================================


def test_no_receipt_yet_reconciles_as_receipt_missing(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "RECEIPT_MISSING"


# === EXECUTION_FAILED / PARTIAL / INDETERMINATE ================================


def test_a_failed_receipt_with_no_success_reconciles_as_execution_failed(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    _submit_receipt(db, identity, binding, decision, intent, status="FAILED")

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "EXECUTION_FAILED"


def test_a_partially_succeeded_receipt_reconciles_as_partial(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    _submit_receipt(db, identity, binding, decision, intent, status="PARTIALLY_SUCCEEDED")

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "PARTIAL"


@pytest.mark.parametrize("status", ["ACCEPTED", "UNKNOWN"])
def test_a_non_terminal_only_receipt_reconciles_as_indeterminate(db, opa_url, status):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    _submit_receipt(db, identity, binding, decision, intent, status=status)

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "INDETERMINATE"


# === MISMATCHED ================================================================


def test_capability_required_but_never_consumed_reconciles_as_mismatched(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id, enforcement_assurance="CAPABILITY_REQUIRED")
    _deploy_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    # A capability is issued (so it exists) but deliberately never
    # consumed -- the enforcement precondition this Binding declares was
    # never actually satisfied.
    capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "MISMATCHED"
    assert result.detail == "capability_required_but_not_consumed"


def test_a_digest_anomaly_on_a_persisted_receipt_reconciles_as_mismatched_on_reverification(db, opa_url):
    """Priority 5's own ingestion already rejects a receipt whose
    canonical_action_digest disagrees with the Intent's own -- this
    scenario simulates a legacy/anomalous row bypassing that ingestion
    check entirely (a direct DB write, not the service), proving
    reconciliation's own defense-in-depth re-verification actually fires
    rather than blindly trusting a persisted row."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    row = _submit_receipt(db, identity, binding, decision, intent, status="SUCCEEDED")
    row.canonical_action_digest = "tampered" * 8
    db.commit()

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "MISMATCHED"
    assert result.detail == "canonical_action_digest_mismatch_on_reverification"


# === Not applicable ============================================================


def test_a_deny_decision_is_not_reconcilable(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    # No ALLOW policy deployed at all for this scope -> the compiled
    # bundle's own deny-if-no-mandates-covered rule (see this milestone's
    # own Priority 2 finding) produces a real, deterministic DENY.
    _deploy_policy(db, org.id, opa_url, effect=Effect.DENY)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    assert decision.outcome == "DENY"

    with pytest.raises(ReconciliationNotApplicableError) as exc:
        reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert exc.value.reason == "decision_not_authorized"


def test_an_unresolved_human_review_decision_is_not_reconcilable(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url, effect=Effect.REQUIRE_HUMAN_REVIEW)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    assert decision.outcome == "HUMAN_REVIEW"

    with pytest.raises(ReconciliationNotApplicableError) as exc:
        reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert exc.value.reason == "decision_not_authorized"


def test_an_approved_human_review_decision_is_reconcilable(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url, effect=Effect.REQUIRE_HUMAN_REVIEW)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    resolution_service.resolve_decision(db, decision.id, org.id, "approved", resolved_by="reviewer@example.com")
    _submit_receipt(db, identity, binding, decision, intent, status="SUCCEEDED")

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "MATCHED"


def test_an_agent_direct_intent_is_not_reconcilable(db, opa_url):
    from app.services import intent_service

    org = _org(db)
    principal = Principal(id=uuid.uuid4(), name="alice", organization_id=org.id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="alice agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="alice-allow", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="alice", action=ACTION, resource=RESOURCE),
        conditions=ConditionSet(all=()), effect=Effect.ALLOW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org.id)
    policy_svc.submit_for_review(db, row.policy_key, org.id)
    policy_svc.approve(db, row.policy_key, org.id, approver="test-suite")
    compile_result = policy_svc.compile_policy(db, row.policy_key, org.id)
    assert compile_result.ok
    policy_svc.deploy_policy(db, row.policy_key, org.id, opa_url=None)

    intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action=ACTION, amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource=RESOURCE,
    )
    assert decision.outcome == "ALLOW"

    with pytest.raises(ReconciliationNotApplicableError) as exc:
        reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert exc.value.reason == "agent_direct_intent_not_applicable"


def test_a_decision_from_a_different_organization_is_not_reconcilable(db, opa_url):
    org_a = _org(db, "Org A")
    org_b = _org(db, "Org B")
    identity_a, _cv, binding_a, agent_a = _scenario(db, org_a.id)
    _deploy_policy(db, org_a.id, opa_url)
    _intent, decision, _evidence = _submit_intent(db, identity_a, binding_a, agent_a, uuid.uuid4().hex)

    with pytest.raises(ReconciliationNotApplicableError) as exc:
        reconciliation_svc.reconcile_decision(db, org_b.id, decision.id)
    assert exc.value.reason == "decision_not_found"


# === Idempotency ================================================================


def test_reconciling_twice_with_no_new_information_is_a_true_no_op(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    _submit_receipt(db, identity, binding, decision, intent, status="SUCCEEDED")

    first = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    second = reconciliation_svc.reconcile_decision(db, org.id, decision.id)

    assert first.id == second.id
    count = db.scalar(select(func.count()).select_from(ReconciliationResultRecord))
    assert count == 1


def test_new_information_after_an_earlier_reconciliation_appends_a_new_row(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    _submit_receipt(db, identity, binding, decision, intent, status="ACCEPTED")

    first = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert first.outcome == "INDETERMINATE"

    _submit_receipt(db, identity, binding, decision, intent, status="SUCCEEDED")
    second = reconciliation_svc.reconcile_decision(db, org.id, decision.id)

    assert second.id != first.id
    assert second.outcome == "MATCHED"
    count = db.scalar(select(func.count()).select_from(ReconciliationResultRecord))
    assert count == 2


# === Out-of-order events ========================================================


def test_a_failed_receipt_submitted_before_a_success_still_reconciles_as_matched(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    _submit_receipt(db, identity, binding, decision, intent, status="FAILED")
    _submit_receipt(db, identity, binding, decision, intent, status="SUCCEEDED")

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "MATCHED", "SUCCEEDED wins regardless of submission order (fixed precedence, not a timeline)"


def test_a_success_submitted_before_a_later_failure_still_reconciles_as_matched(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    _submit_receipt(db, identity, binding, decision, intent, status="SUCCEEDED")
    _submit_receipt(db, identity, binding, decision, intent, status="FAILED")

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "MATCHED", "the fixed precedence rule is order-independent by design"


# === Historical reconstruction after policy changes ============================


def test_reconciliation_of_an_old_decision_is_unaffected_by_a_later_policy_replacement(db, opa_url):
    from app.services import runtime_policy_lifecycle_service

    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    first_policy = _deploy_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    _submit_receipt(db, identity, binding, decision, intent, status="SUCCEEDED")

    # The organisation's active policy is retired and replaced with a
    # DENY-effect one for the same scope, well after the Decision above
    # was already made.
    runtime_policy_lifecycle_service.retire_policy(
        db, first_policy.policy_key, org.id, opa_url=opa_url, actor="test-suite",
    )
    _deploy_policy(db, org.id, opa_url, effect=Effect.DENY)

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "MATCHED", (
        "reconciliation reads only the Decision's own already-persisted records, "
        "never today's current policy"
    )
