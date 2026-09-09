"""Post-audit implementation, Priority 5: proves execution_receipt_service.
submit_execution_receipt against a real, persisted Adapter-mediated
Decision (integration_runtime_service.submit_attested_intent) and a real
ephemeral OPA -- not a hand-constructed Intent/Decision pair -- so every
trust/linkage check below is exercised against genuine prior state, the
same discipline test_canonical_action_runtime.py and
test_delegation_runtime_decisions.py already establish for this milestone.

Deliberately does not re-test integration_runtime_service's own already-
covered mechanics (contract mismatch, replay, structural fields) -- this
file is scoped to what's new: execution_receipt_service.py's own ingestion
trust rules and idempotency/conflict resolution.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import (
    Agent, Base, CapabilityToken, Evidence, ExecutionReceiptRecord, Organization, Principal,
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
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
    integration_runtime_service as runtime_svc,
    organization_lifecycle_service,
    runtime_policy_service as policy_svc,
    signing_key_service,
)
from app.services.execution_receipt_service import (
    ExecutionReceiptConflictError,
    ExecutionReceiptRejectionError,
)

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


def _org(db, name="Org Receipts"):
    org = Organization(id=uuid.uuid4(), name=name)
    db.add(org)
    db.commit()
    return org


def _deploy_allow_policy(db, org_id, opa_url):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="allow policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="FinanceAgent01", action=ACTION, resource=RESOURCE),
        conditions=ConditionSet(all=()), effect=Effect.ALLOW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)


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
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, audience="reference-pep", action=intent.action, resource=resource,
        constraints={"environment": binding.environment}, environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org_id,
    )
    return consumed


def _submit_receipt(db, identity, binding, decision, intent, *, capability_id=None, status="ACCEPTED", destination=DESTINATION, external_operation_id=None):
    return receipt_svc.submit_execution_receipt(
        db, identity,
        enforcement_binding_id=binding.id,
        decision_id=decision.id,
        canonical_action_digest=intent.canonical_action_digest,
        external_operation_id=external_operation_id or intent.external_operation_id,
        destination=destination,
        status=status,
        capability_id=capability_id,
    )


# === A. Valid receipt =========================================================


def test_valid_receipt_is_accepted_and_persisted(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    assert decision.outcome == "ALLOW"

    row = _submit_receipt(db, identity, binding, decision, intent)

    assert row.id is not None
    assert row.status == "ACCEPTED"
    assert row.organization_id == org.id
    assert row.decision_id == decision.id
    assert row.evidence_id is not None
    evidence_row = db.get(Evidence, row.evidence_id)
    assert evidence_row.payload["event_type"] == "EXECUTION_RECEIPT_ACCEPTED"
    assert evidence_row.payload["decision_id"] == str(decision.id)


# === B/L. Tenant isolation ====================================================


def test_a_decision_from_a_different_organization_is_rejected(db, opa_url):
    org_a = _org(db, "Org A")
    org_b = _org(db, "Org B")
    identity_a, _cv_a, binding_a, agent_a = _scenario(db, org_a.id)
    identity_b, _cv_b, binding_b, agent_b = _scenario(db, org_b.id)
    _deploy_allow_policy(db, org_a.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity_a, binding_a, agent_a, uuid.uuid4().hex)

    with pytest.raises(ExecutionReceiptRejectionError) as exc:
        _submit_receipt(db, identity_b, binding_b, decision, intent)
    assert exc.value.reason == "decision_not_found"


# === C. Wrong capability ======================================================


def test_a_capability_bound_to_a_different_decision_is_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id, enforcement_assurance="CAPABILITY_REQUIRED")
    _deploy_allow_policy(db, org.id, opa_url)
    intent1, decision1, _e1 = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    intent2, decision2, _e2 = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    consumed_for_decision2 = _issue_and_consume_capability(db, org.id, decision2, intent2, binding)

    with pytest.raises(ExecutionReceiptRejectionError) as exc:
        _submit_receipt(db, identity, binding, decision1, intent1, capability_id=consumed_for_decision2.capability_id)
    assert exc.value.reason == "capability_not_found_for_decision"


def test_capability_required_binding_rejects_a_receipt_with_no_capability(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id, enforcement_assurance="CAPABILITY_REQUIRED")
    _deploy_allow_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)

    with pytest.raises(ExecutionReceiptRejectionError) as exc:
        _submit_receipt(db, identity, binding, decision, intent)
    assert exc.value.reason == "capability_required_but_not_supplied"


def test_an_unconsumed_capability_is_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id, enforcement_assurance="CAPABILITY_REQUIRED")
    _deploy_allow_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")
    from sqlalchemy import select
    unconsumed_row = db.scalar(select(CapabilityToken).where(CapabilityToken.decision_id == decision.id))

    with pytest.raises(ExecutionReceiptRejectionError) as exc:
        _submit_receipt(db, identity, binding, decision, intent, capability_id=unconsumed_row.id)
    assert exc.value.reason == "capability_not_consumed"


def test_receipt_after_capability_expiry_but_valid_prior_execution_is_accepted(db, opa_url):
    """A short-lived Capability expiring before the downstream operation's
    own receipt arrives must not retroactively invalidate an execution
    that already, validly, consumed it -- see execution_receipt_service.py's
    own module docstring for why capability freshness is deliberately not
    re-checked here."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id, enforcement_assurance="CAPABILITY_REQUIRED")
    _deploy_allow_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    consumed = _issue_and_consume_capability(db, org.id, decision, intent, binding)

    from sqlalchemy import select
    cap_row = db.scalar(select(CapabilityToken).where(CapabilityToken.id == consumed.capability_id))
    cap_row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()

    row = _submit_receipt(db, identity, binding, decision, intent, capability_id=consumed.capability_id, status="SUCCEEDED")
    assert row.status == "SUCCEEDED"


# === E. Wrong action digest ===================================================


def test_a_mismatched_canonical_action_digest_is_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)

    with pytest.raises(ExecutionReceiptRejectionError) as exc:
        receipt_svc.submit_execution_receipt(
            db, identity, enforcement_binding_id=binding.id, decision_id=decision.id,
            canonical_action_digest="a" * 64, external_operation_id=intent.external_operation_id,
            destination=DESTINATION, status="ACCEPTED",
        )
    assert exc.value.reason == "canonical_action_digest_mismatch"


# === F. Wrong destination (mismatched from a prior receipt) ==================


def test_a_destination_that_changes_between_receipts_for_the_same_operation_is_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    _submit_receipt(db, identity, binding, decision, intent, status="ACCEPTED", destination="erp:vendor_master")

    with pytest.raises(ExecutionReceiptRejectionError) as exc:
        _submit_receipt(db, identity, binding, decision, intent, status="SUCCEEDED", destination="erp:general_ledger")
    assert exc.value.reason == "destination_mismatch"


# === G. Wrong enforcement binding =============================================


def test_a_binding_that_was_not_used_for_this_decision_is_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)

    # A second, otherwise-valid binding for the same identity/contract.
    integration = contract_svc.create_integration(db, org.id, "Second System")
    contract_version2 = contract_svc.create_contract_version(
        db, integration.id, org.id, "OtherOperation", ACTION,
        resource_path="supplier.id", amount_path=None, currency_path=None,
        fact_subject_path=None, context_bindings={},
    )
    contract_version2 = contract_svc.validate_contract_version(db, contract_version2.id, org.id)
    contract_version2 = contract_svc.approve_contract_version(db, contract_version2.id, org.id, approver="governance-admin@example.com")
    other_binding = binding_svc.create_draft_binding(db, org.id, identity.id, contract_version2.id, "demo", agent_ids=[agent.id])
    other_binding = binding_svc.activate_binding(db, other_binding.id, org.id)

    with pytest.raises(ExecutionReceiptRejectionError) as exc:
        _submit_receipt(db, identity, other_binding, decision, intent)
    assert exc.value.reason == "enforcement_binding_not_bound_to_decision"


# === H/I. Idempotency vs conflict =============================================


def test_an_identical_retry_is_idempotent_and_does_not_create_a_second_row(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)

    first = _submit_receipt(db, identity, binding, decision, intent)
    second = _submit_receipt(db, identity, binding, decision, intent)

    assert second.id == first.id
    from sqlalchemy import func, select
    count = db.scalar(select(func.count()).select_from(ExecutionReceiptRecord))
    assert count == 1


def test_a_conflicting_retry_with_a_different_destination_is_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)
    _submit_receipt(db, identity, binding, decision, intent, status="ACCEPTED", destination="erp:vendor_master")

    # Manually clear the first-receipt-establishes-destination guard by
    # asserting the same status but a DIFFERENT destination is rejected as
    # a conflict once a receipt already exists for (operation, status) --
    # this is the natural-key conflict path, distinct from the cross-
    # receipt destination-consistency check (test F above), which fires
    # for a *new* status against an established destination.
    with pytest.raises(ExecutionReceiptRejectionError):
        _submit_receipt(db, identity, binding, decision, intent, status="ACCEPTED", destination="erp:general_ledger")


def test_a_state_progression_for_the_same_operation_creates_a_second_row(db, opa_url):
    """ACCEPTED -> SUCCEEDED for the same external_operation_id is a
    legitimate state transition, not a duplicate -- history is append-
    only, so this must be a second row, never an update of the first."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)

    accepted = _submit_receipt(db, identity, binding, decision, intent, status="ACCEPTED")
    succeeded = _submit_receipt(db, identity, binding, decision, intent, status="SUCCEEDED")

    assert accepted.id != succeeded.id
    from sqlalchemy import func, select
    count = db.scalar(select(func.count()).select_from(ExecutionReceiptRecord))
    assert count == 2


def test_a_simulated_concurrent_duplicate_submission_resolves_to_the_same_idempotent_row(db, opa_url):
    """Mirrors integration_runtime_service.submit_attested_intent's own
    testing convention (test_canonical_action_runtime's idempotent-retry
    test): two real, sequential calls with identical material fields --
    exercising the same outcome the DB-level UNIQUE constraint guarantees
    under a genuine race, without needing literal concurrent threads
    against a single-connection SQLite test database."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)

    first = _submit_receipt(db, identity, binding, decision, intent)
    second = _submit_receipt(db, identity, binding, decision, intent)
    assert first.id == second.id


# === K. Failed / partial / unknown states =====================================


@pytest.mark.parametrize("status", ["FAILED", "PARTIALLY_SUCCEEDED", "UNKNOWN"])
def test_every_terminal_and_indeterminate_status_is_accepted(db, opa_url, status):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)

    row = _submit_receipt(db, identity, binding, decision, intent, status=status)
    assert row.status == status


# === Organisation kill switch (Priority 1 <-> Priority 5 integration) ========


def test_a_deactivated_organizations_receipts_are_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)
    intent, decision, _evidence = _submit_intent(db, identity, binding, agent, uuid.uuid4().hex)

    organization_lifecycle_service.deactivate_organization(db, org.id)

    with pytest.raises(ExecutionReceiptRejectionError) as exc:
        _submit_receipt(db, identity, binding, decision, intent)
    assert exc.value.reason.startswith("organization_not_active")
