"""Stripe sandbox adapter (scripts/stripe_sandbox_adapter.py): the
important scenarios from this review's own task list, exercised against
the REAL PayReality lifecycle (real Decision/Capability/Operation
service-layer code, a real Ed25519 signature genuinely generated and
verified for the signed-Adapter reporting path) and a LOCAL SIMULATION
of Stripe (FakeStripeBackend, in `stripe_sandbox_adapter.py` itself --
never a real network call, never presented as a real Stripe test-mode
run). A test requiring a real Stripe test-mode credential would be a
separate, explicitly-labeled, skipped-unless-configured test; none
exist in this file, since test-mode access was never confirmed for
this session (see this review's own final report).

Imports the adapter module directly via importlib (no existing
precedent for importing from scripts/ in this test suite otherwise --
matching tests/unit/test_reference_enforcement_adapter.py's own
established convention exactly), so the exact code that would run for
a real operator is what is under test here, not a reimplemented copy.
"""

import base64
import importlib.util
import json
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import nacl.signing
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import (
    Agent, Base, BusinessOperationIdentity, CapabilityToken, Decision, Intent, Operation, Organization, Principal,
)
from app.domain.auth.signature import verify_request_signature
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
    execution_receipt_service,
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
    integration_runtime_service as runtime_svc,
    operation_service,
    runtime_policy_service as policy_svc,
    signing_key_service,
)

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "stripe_sandbox_adapter.py"
_spec = importlib.util.spec_from_file_location("stripe_sandbox_adapter", _SCRIPT_PATH)
adapter = importlib.util.module_from_spec(_spec)
sys.modules["stripe_sandbox_adapter"] = adapter
_spec.loader.exec_module(adapter)

ACTION = "vendor_payment"
SOURCE_OPERATION = "StripeSandbox/v1.SubmitPayment"
DESTINATION = "stripe:test-mode"
SUPPLIER_RESOURCE = "supplier:stripe-sandbox"


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


def _org(db, name="Stripe Sandbox Org"):
    org = Organization(id=uuid.uuid4(), name=name)
    db.add(org)
    db.commit()
    return org


def _real_signing_keypair():
    """A GENUINE Ed25519 keypair, generated fresh -- not the 'ed25519:
    base64:AAAA' placeholder every other test in this repository uses
    (which can never actually verify a real signature). This is what
    lets this file's own 'signed adapter reporting' tests perform a
    real sign-then-verify round trip, never asserting
    signature_verified=True without having earned it."""
    signing_key = nacl.signing.SigningKey.generate()
    public_key_b64 = base64.b64encode(bytes(signing_key.verify_key)).decode()
    return signing_key, f"ed25519:base64:{public_key_b64}"


def _scenario(db, org_id, opa_url, *, lifecycle_requirement="LIFECYCLE_REQUIRED"):
    signing_key, public_key_str = _real_signing_keypair()
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "Stripe Sandbox Adapter", public_key_str)
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)
    integration = contract_svc.create_integration(db, org_id, f"Stripe Sandbox Integration {uuid.uuid4().hex[:8]}")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, SOURCE_OPERATION, ACTION,
        resource_path="payment.supplier", amount_path="payment.amount", currency_path="payment.currency",
        fact_subject_path=None, context_bindings={}, lifecycle_requirement=lifecycle_requirement,
    )
    contract_version = contract_svc.validate_contract_version(db, contract_version.id, org_id)
    contract_version = contract_svc.approve_contract_version(db, contract_version.id, org_id, approver="governance-admin@example.com")
    principal = Principal(id=uuid.uuid4(), name=f"StripeSandboxAgent{uuid.uuid4().hex[:8]}", organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="Stripe Sandbox Agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    binding = binding_svc.create_draft_binding(db, org_id, identity.id, contract_version.id, "production", agent_ids=[agent.id])
    binding = binding_svc.activate_binding(db, binding.id, org_id)

    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name=f"stripe-sandbox-policy-{uuid.uuid4().hex[:8]}", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal=principal.name, action=ACTION, resource=SUPPLIER_RESOURCE),
        conditions=ConditionSet(all=()), effect=Effect.ALLOW, audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)

    return identity, signing_key, contract_version, binding, agent, integration, principal


def _authorize_and_consume(db, org_id, identity, binding, agent, principal_name, *, business_operation_id, external_operation_id, amount=5000):
    """The real, unmodified lifecycle up through a consumed Capability
    and its resulting Operation -- everything this adapter dispatches
    against. Reuses only existing, already-tested service functions."""
    intent, decision, _ev = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
        amount=amount, currency="USD", counterparty=None, context={},
        requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id=external_operation_id,
        business_operation_id=business_operation_id, intended_destination=DESTINATION,
    )
    assert decision.outcome == "ALLOW", f"expected ALLOW, got {decision.outcome} ({decision.reason})"
    issued = capability_service.issue_capability_for_decision(db, org_id, decision.id, audience="stripe-sandbox-adapter")
    operation = db.scalar(select(Operation).where(Operation.decision_id == decision.id))
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "stripe-sandbox-adapter", ACTION, SUPPLIER_RESOURCE,
        {"amount": f"{amount:.2f}", "currency": "USD", "environment": "production"},
        environment=binding.environment, enforcement_binding_id=binding.id, expected_organization_id=org_id,
    )
    nonce = db.get(CapabilityToken, consumed.capability_id).nonce
    return intent, decision, operation, consumed, nonce


def _sign(signing_key, payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    signature = signing_key.sign(body).signature
    return body, base64.b64encode(signature).decode()


def _intent_digest(db, operation):
    decision = db.get(Decision, operation.decision_id)
    intent = db.get(Intent, decision.intent_id)
    return intent.canonical_action_digest


def _report_signed(db, org_id, operation, identity, signing_key, binding, *, status, payment_intent_id, external_operation_id):
    """Genuine signed-Adapter reporting: signs a real payload with the
    real private key, verifies it with the real public key (exactly
    what routers/execution_receipts.py's own dependency does, just
    without the ASGI transport hop -- see this file's own module
    docstring), and ONLY passes signature_verified=True to the service
    layer once that verification has actually succeeded. This is
    ADAPTER-REPORTED evidence, never independently verified destination
    evidence -- it proves what the Adapter reported, under a real
    signature, not that Stripe's own systems are being told the truth.

    `external_operation_id` must be the ORIGINAL Intent's own
    correlation id (the value passed to submit_attested_intent) --
    submit_execution_receipt verifies this against the Intent it
    resolves via decision_id, as a real linkage check (section 5); it
    is NOT the Stripe PaymentIntent id, which is a destination-side
    object id tracked separately (Operation.destination_operation_id,
    via record_dispatch_evidence, exercised explicitly where a test
    needs to assert it)."""
    payload = {"operation_id": str(operation.id), "status": status, "payment_intent_id": payment_intent_id}
    body, signature_b64 = _sign(signing_key, payload)
    certificate = identity_svc.get_active_certificate_for_identity(db, identity.id)
    assert verify_request_signature(body, signature_b64, certificate.public_key), (
        "test setup error: the signature this test just generated did not verify"
    )
    receipt = execution_receipt_service.submit_execution_receipt(
        db, identity, enforcement_binding_id=binding.id, decision_id=operation.decision_id,
        canonical_action_digest=_intent_digest(db, operation),
        external_operation_id=external_operation_id, destination=DESTINATION, status=status,
        capability_id=operation.capability_id,
    )
    return operation_service.record_observation_for_existing_receipt(
        db, org_id, receipt, reporter_kind=operation_service.REPORTER_SIGNED_ADAPTER_IDENTITY,
        signature_verified=True, reported_by=f"integration_identity:{identity.name}",
    )


def _chain(db, operation) -> dict[str, "adapter.OperationLink"]:
    """Loads every Operation sharing the same business_operation_identity_id
    as `operation` and builds the plain, ORM-free OperationLink chain
    adapter.destination_dispatch_identity needs -- the adapter itself
    never imports SQLAlchemy/app.db.models; this is the real caller-side
    responsibility that module's own docstring describes."""
    rows = db.scalars(
        select(Operation).where(Operation.business_operation_identity_id == operation.business_operation_identity_id)
    ).all()
    return {
        str(row.id): adapter.OperationLink(
            operation_id=str(row.id),
            previous_attempt_operation_id=str(row.previous_attempt_operation_id) if row.previous_attempt_operation_id else None,
            outcome_status=row.outcome_status,
        )
        for row in rows
    }


def _destination_identity(db, operation) -> str:
    return adapter.destination_dispatch_identity(str(operation.id), _chain(db, operation))


def _first_dispatch_attempted_at(db, operation):
    """The real system has no explicit 'first dispatch attempted at'
    timestamp today -- this uses the ROOT operation's own created_at
    (the operation whose id equals the computed destination_dispatch_
    identity) as a reasonable, disclosed proxy, exactly as documented in
    STRIPE_SANDBOX_IMPLEMENTATION_PLAN.md."""
    root_id = _destination_identity(db, operation)
    root = db.get(Operation, uuid.UUID(root_id))
    return root.created_at.replace(tzinfo=timezone.utc) if root.created_at.tzinfo is None else root.created_at


def _dispatch_and_confirm(backend, org, integration, operation, nonce, db, *, amount=5000, payment_method="pm_card_visa", now=None):
    boi = db.get(BusinessOperationIdentity, operation.business_operation_identity_id)
    return adapter.dispatch_payment_intent(
        backend, organization_id=str(org.id), integration_id=str(integration.id),
        destination_dispatch_identity=_destination_identity(db, operation),
        business_operation_identity_id=str(boi.id), operation_id=str(operation.id),
        capability_nonce=nonce, amount=amount, currency="usd", payment_method=payment_method,
        first_dispatch_attempted_at=_first_dispatch_attempted_at(db, operation),
        outcome_status=operation.outcome_status, now=now,
    )


# === 1. Initial operation and normal response =================================


def test_initial_operation_and_normal_response(db, opa_url):
    org = _org(db)
    identity, signing_key, _cv, binding, agent, integration, principal = _scenario(db, org.id, opa_url)
    _intent, _decision, operation, consumed, nonce = _authorize_and_consume(
        db, org.id, identity, binding, agent, principal.name,
        business_operation_id="STRIPE-OP-001", external_operation_id="ext-001",
    )

    backend = adapter.FakeStripeBackend()  # default_outcome="succeeded"
    dispatched = _dispatch_and_confirm(backend, org, integration, operation, nonce, db)
    assert dispatched.status == "succeeded"

    operation_service.record_claim(db, org.id, operation, consumed.capability_id)
    operation_service.record_dispatch_evidence(
        db, org.id, operation.id, reporter_kind=operation_service.REPORTER_SIGNED_ADAPTER_IDENTITY,
        signature_verified=True, reported_by=f"integration_identity:{identity.name}",
        integration_identity_id=identity.id, destination=DESTINATION, destination_operation_id=dispatched.payment_intent_id,
    )
    _report_signed(
        db, org.id, operation, identity, signing_key, binding, status="SUCCEEDED",
        payment_intent_id=dispatched.payment_intent_id, external_operation_id="ext-001",
    )
    db.refresh(operation)
    assert operation.outcome_status == "COMMITTED"
    assert operation.evidence_assurance == "ADAPTER_REPORTED"
    assert operation.destination_operation_id == dispatched.payment_intent_id

    looked_up = adapter.retrieve_status(backend, payment_intent_id=dispatched.payment_intent_id)
    assert looked_up["status"] == "succeeded"


# === 2. Lost response after successful creation, recovered via retry with the
# same idempotency key ===========================================================


def test_lost_response_after_successful_creation_recovered_via_retry_with_same_key(db, opa_url):
    """This review's own literal scenario: Stripe creates a PaymentIntent
    (the create call genuinely executes and its result is cached,
    exactly as Stripe's own docs describe -- 'saving the resulting
    status code and body of the first request... regardless of whether
    it succeeds or fails'), but the create call's own HTTP response is
    lost before PayReality ever durably records the resulting pi_id. Per
    Stripe's own 'Retrieve a PaymentIntent' docs, no metadata-search
    recovery path exists -- the only documented recovery is retrying the
    SAME call with the SAME idempotency key, which is exactly what this
    test proves works: a second call lands on the cached, already-
    created object rather than creating a duplicate one. (The OLD test
    at this position let the test directly mutate backend._payment_
    intents[pi_id]['status'], implying the adapter already knew the
    pi_id despite "the response being lost" -- unrealistic, since Stripe
    generates that id server-side. drop_next_response_for_key below
    models the real gap correctly: the caller never learns the id at all.)"""
    org = _org(db)
    identity, signing_key, _cv, binding, agent, integration, principal = _scenario(db, org.id, opa_url)
    _intent, _decision, operation, _consumed, nonce = _authorize_and_consume(
        db, org.id, identity, binding, agent, principal.name,
        business_operation_id="STRIPE-OP-002", external_operation_id="ext-002",
    )
    backend = adapter.FakeStripeBackend()
    create_key = adapter.idempotency_key(
        organization_id=str(org.id), integration_id=str(integration.id),
        destination_dispatch_identity=_destination_identity(db, operation), operation_kind=adapter.OPERATION_KIND_CREATE,
    )
    backend.drop_next_response_for_key(create_key)

    with pytest.raises(TimeoutError):
        _dispatch_and_confirm(backend, org, integration, operation, nonce, db)

    # Stripe's own side DID process the create call -- only the first
    # caller's own response was lost. Exactly one PaymentIntent exists
    # despite the lost response, before any retry is even attempted.
    assert len(backend._payment_intents) == 1

    dispatched = _dispatch_and_confirm(backend, org, integration, operation, nonce, db)
    assert dispatched.payment_intent_id.startswith("pi_sim_")
    assert dispatched.status == "succeeded"
    assert len(backend._payment_intents) == 1, "the retry must land on the SAME cached object, never create a second one"


# === 3. A replacement after a PROVEN non-commit gets a genuinely fresh identity ==


def test_replacement_after_proven_non_commit_gets_a_fresh_destination_identity(db, opa_url):
    """A genuinely new attempt (new Intent, new Decision, new
    Capability, new nonce, new Operation) at the SAME business
    operation -- following a proven TERMINALLY_NOT_COMMITTED original --
    must derive a DIFFERENT Stripe idempotency key, because its own
    destination_dispatch_identity is genuinely fresh (the chain-walk
    stops at a proven non-commit predecessor), while the metadata
    correlation (BusinessOperationIdentity.id) stays identical. This is
    the ONE case where a fresh Operation.id SHOULD also mean a fresh
    destination identity -- there is no risk of a duplicate effect from
    an original proven never to have taken effect."""
    org = _org(db)
    identity, signing_key, _cv, binding, agent, integration, principal = _scenario(db, org.id, opa_url)
    boid = "STRIPE-OP-003"
    _intent_a, _decision_a, operation_a, consumed_a, nonce_a = _authorize_and_consume(
        db, org.id, identity, binding, agent, principal.name, business_operation_id=boid, external_operation_id="ext-003-a",
    )
    backend = adapter.FakeStripeBackend(default_outcome="declined")
    dispatched_a = _dispatch_and_confirm(backend, org, integration, operation_a, nonce_a, db)
    assert dispatched_a.status == "canceled"

    operation_service.record_claim(db, org.id, operation_a, consumed_a.capability_id)
    operation_service.record_dispatch_evidence(
        db, org.id, operation_a.id, reporter_kind=operation_service.REPORTER_SIGNED_ADAPTER_IDENTITY,
        signature_verified=True, reported_by=f"integration_identity:{identity.name}",
        integration_identity_id=identity.id, destination=DESTINATION, destination_operation_id=dispatched_a.payment_intent_id,
    )
    _report_signed(
        db, org.id, operation_a, identity, signing_key, binding, status="FAILED",
        payment_intent_id=dispatched_a.payment_intent_id, external_operation_id="ext-003-a",
    )
    db.refresh(operation_a)
    assert operation_a.outcome_status == "TERMINALLY_NOT_COMMITTED"

    safety = operation_service.evaluate_replacement_safety(db, org.id, operation_a.id)
    assert safety.safety == "SAFE_TERMINAL_NON_COMMIT_PROVEN"

    # A genuinely new, PayReality-authorized attempt at the SAME business operation.
    _intent_b, _decision_b, operation_b, consumed_b, nonce_b = _authorize_and_consume(
        db, org.id, identity, binding, agent, principal.name, business_operation_id=boid, external_operation_id="ext-003-b",
    )
    assert operation_b.id != operation_a.id
    assert operation_b.previous_attempt_operation_id == operation_a.id
    assert nonce_b != nonce_a, "a fresh Capability must have a fresh nonce"

    boi_a = db.get(BusinessOperationIdentity, operation_a.business_operation_identity_id)
    boi_b = db.get(BusinessOperationIdentity, operation_b.business_operation_identity_id)
    assert boi_a.id == boi_b.id, "both attempts correlate to the SAME business-operation identity"

    identity_a = _destination_identity(db, operation_a)
    identity_b = _destination_identity(db, operation_b)
    assert identity_a == str(operation_a.id)
    assert identity_b == str(operation_b.id), "fresh -- NOT carried forward, unlike the guarantee-based case (see the next test)"
    assert identity_b != identity_a

    key_a = adapter.idempotency_key(organization_id=str(org.id), integration_id=str(integration.id), destination_dispatch_identity=identity_a, operation_kind=adapter.OPERATION_KIND_CREATE)
    key_b = adapter.idempotency_key(organization_id=str(org.id), integration_id=str(integration.id), destination_dispatch_identity=identity_b, operation_kind=adapter.OPERATION_KIND_CREATE)
    assert key_a != key_b, "the two attempts must NOT share a Stripe-level idempotency scope"

    backend.set_default_outcome("succeeded")
    dispatched_b = _dispatch_and_confirm(backend, org, integration, operation_b, nonce_b, db)
    assert dispatched_b.payment_intent_id != dispatched_a.payment_intent_id, "the retry must create a genuinely NEW PaymentIntent, not replay the declined one"
    assert dispatched_b.status == "succeeded"
    assert len(backend._payment_intents) == 2


# === 4. The critical regression: a replacement authorized despite an UNRESOLVED
# outcome must carry forward the SAME destination identity, not mint a fresh one =


def test_replacement_authorized_despite_unresolved_outcome_carries_forward_the_same_destination_identity(db, opa_url):
    """The exact concern this review raised, reproduced for real -- and
    the one scenario the PREVIOUS ('corrected') mapping got wrong. That
    design keyed the idempotency key off Operation.id alone, reasoning
    that a fresh, PayReality-authorized attempt should always get a
    fresh Stripe-level scope. That is correct for the PROVEN-non-commit
    scenario (the test above) but wrong here: a replacement authorized
    via a human-documented duplicate-prevention GUARANTEE despite the
    original's own outcome still being UNKNOWN. Reproduces this review's
    own literal 5-step sequence:

      1. Operation A dispatches; Stripe creates a PaymentIntent.
      2. The response is lost before A's own destination_operation_id is
         ever durably recorded (simulated via drop_next_response_for_key).
      3. A.outcome_status stays UNKNOWN -- nothing resolves it.
      4. A human records a DestinationDuplicatePreventionGuarantee (the
         real, existing escape hatch) -> evaluate_replacement_safety
         returns SAFE_DUPLICATE_PREVENTION_GUARANTEED, and a fresh
         Capability/Operation B is authorized for the same business
         operation.
      5. The adapter dispatches again for B.

    This test fails against the pre-fix (Operation.id-keyed) design: the
    old scheme's own key for B is demonstrated below to differ from A's,
    which would create a SECOND, independent PaymentIntent. The fixed
    design instead carries A's own destination identity forward onto B,
    deriving the IDENTICAL key -- so B's dispatch correctly lands on the
    SAME object A's own (lost-response) create call already produced."""
    org = _org(db)
    identity, signing_key, _cv, binding, agent, integration, principal = _scenario(db, org.id, opa_url)
    _intent_a, _decision_a, operation_a, _consumed_a, nonce_a = _authorize_and_consume(
        db, org.id, identity, binding, agent, principal.name,
        business_operation_id="STRIPE-OP-004", external_operation_id="ext-004a",
    )

    backend = adapter.FakeStripeBackend()
    identity_a = _destination_identity(db, operation_a)
    assert identity_a == str(operation_a.id)  # a root attempt -- no prior chain to carry forward yet
    create_key_a = adapter.idempotency_key(
        organization_id=str(org.id), integration_id=str(integration.id),
        destination_dispatch_identity=identity_a, operation_kind=adapter.OPERATION_KIND_CREATE,
    )
    backend.drop_next_response_for_key(create_key_a)
    with pytest.raises(TimeoutError):
        _dispatch_and_confirm(backend, org, integration, operation_a, nonce_a, db)

    db.refresh(operation_a)
    assert operation_a.outcome_status == "UNKNOWN", "nothing ever resolved A's own fate -- PayReality never learned the resulting pi_id"
    assert len(backend._payment_intents) == 1, "Stripe's own side DID process the create call; only the response was lost"
    real_pi_id = next(iter(backend._payment_intents))

    operation_service.record_destination_duplicate_prevention_guarantee(
        db, org.id, operation_a.id, destination=DESTINATION,
        scope_description="lost create response confirmed non-duplicating by out-of-band support ticket #004",
        retention_until=datetime.now(timezone.utc) + timedelta(hours=1), documented_by="governance-admin@example.com",
    )
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation_a.id)
    assert safety.safety == "SAFE_DUPLICATE_PREVENTION_GUARANTEED"

    _intent_b, _decision_b, operation_b, _consumed_b, nonce_b = _authorize_and_consume(
        db, org.id, identity, binding, agent, principal.name,
        business_operation_id="STRIPE-OP-004", external_operation_id="ext-004b",
    )
    assert operation_b.previous_attempt_operation_id == operation_a.id

    # Proves this test fails against the PRE-FIX design: the old,
    # Operation.id-keyed scheme necessarily derives a DIFFERENT key for
    # B than whatever A's own (lost) create call used.
    old_style_key_a = f"{operation_a.id}:{adapter.OPERATION_KIND_CREATE}"
    old_style_key_b = f"{operation_b.id}:{adapter.OPERATION_KIND_CREATE}"
    assert old_style_key_a != old_style_key_b, (
        "sanity check on the FLAW itself: the old scheme's key is Operation.id-derived, "
        "so B's fresh Operation.id necessarily produces a fresh, unrelated key -- which "
        "would create a second PaymentIntent for what is actually the same destination operation"
    )

    # The fix: B's own destination identity carries A's forward, because
    # the chain-walk finds no TERMINALLY_NOT_COMMITTED predecessor (A has
    # none, and A's OWN outcome is UNKNOWN, not a proven non-commit).
    identity_b = _destination_identity(db, operation_b)
    assert identity_b == identity_a == str(operation_a.id)
    create_key_b = adapter.idempotency_key(
        organization_id=str(org.id), integration_id=str(integration.id),
        destination_dispatch_identity=identity_b, operation_kind=adapter.OPERATION_KIND_CREATE,
    )
    assert create_key_b == create_key_a

    dispatched_b = _dispatch_and_confirm(backend, org, integration, operation_b, nonce_b, db)
    assert dispatched_b.payment_intent_id == real_pi_id
    assert dispatched_b.status == "succeeded"
    assert dispatched_b.confirmation_skipped is False, "this is the FIRST confirm call for this object -- A's own dispatch never got past the (dropped-response) create step"
    assert len(backend._payment_intents) == 1, (
        "exactly one PaymentIntent must exist -- B's dispatch must resume A's own "
        "cached create result, never create a second, independent object"
    )


# === 5. Concurrent attempts ======================================================


def test_concurrent_attempts_at_the_same_idempotency_key_never_both_mutate(db, opa_url):
    """Two threads racing to confirm the SAME Operation's own PaymentIntent
    at once (a realistic double-submission, e.g. a client-side retry
    firing concurrently with the original still in flight) -- exactly
    one succeeds; the other gets Stripe's own documented 409, never a
    second, independent side effect."""
    org = _org(db)
    identity, signing_key, _cv, binding, agent, integration, principal = _scenario(db, org.id, opa_url)
    _intent, _decision, operation, consumed, nonce = _authorize_and_consume(
        db, org.id, identity, binding, agent, principal.name,
        business_operation_id="STRIPE-OP-004B", external_operation_id="ext-004c",
    )
    backend = adapter.FakeStripeBackend()
    boi = db.get(BusinessOperationIdentity, operation.business_operation_identity_id)
    destination_identity = _destination_identity(db, operation)
    created = backend.create_payment_intent(
        idempotency_key=adapter.idempotency_key(organization_id=str(org.id), integration_id=str(integration.id), destination_dispatch_identity=destination_identity, operation_kind=adapter.OPERATION_KIND_CREATE),
        amount=5000, currency="usd",
        metadata=adapter.build_metadata(organization_id=str(org.id), integration_id=str(integration.id), business_operation_identity_id=str(boi.id), destination_dispatch_identity=destination_identity, operation_id=str(operation.id), capability_nonce=nonce),
    )
    backend.set_outcome(created["id"], "succeeded")

    # Make the confirm call itself slow so a genuine concurrent second
    # call lands while the first is still executing.
    real_cached_or_execute = backend._cached_or_execute
    def slow_cached_or_execute(key, params, execute):
        def slow_execute():
            time.sleep(0.2)
            return execute()
        return real_cached_or_execute(key, params, slow_execute)
    backend._cached_or_execute = slow_cached_or_execute

    confirm_key = adapter.idempotency_key(organization_id=str(org.id), integration_id=str(integration.id), destination_dispatch_identity=destination_identity, operation_kind=adapter.OPERATION_KIND_CONFIRM)
    results = []

    def worker():
        try:
            r = backend.confirm_payment_intent(payment_intent_id=created["id"], idempotency_key=confirm_key, payment_method="pm_card_visa", metadata={})
            results.append(("ok", r["status"]))
        except adapter.StripeClientError as e:
            results.append(("error", e.status_code))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    threads[0].start()
    time.sleep(0.05)
    threads[1].start()
    for t in threads:
        t.join(timeout=5)

    outcomes = [r[0] for r in results]
    assert outcomes.count("ok") == 1, f"expected exactly one success, got {results}"
    assert adapter.STRIPE_CONCURRENT_REQUEST_STATUS_CODE in [r[1] for r in results if r[0] == "error"]


# === 6. Changed material parameters ==============================================


def test_changed_material_parameters_rejected_not_silently_processed(db, opa_url):
    """A caller bug that reuses the same derived key with a DIFFERENT
    amount must be rejected by Stripe's own parameter-mismatch check
    (simulated here), never silently processed as if it were a
    legitimate retry of the original. A metadata-only difference is
    deliberately NOT exercised here as a mismatch -- see
    create_payment_intent's own fingerprinting, fixed this review to
    exclude metadata (correlation-only, never part of duplicate-
    prevention matching) from the comparison."""
    org = _org(db)
    identity, signing_key, _cv, binding, agent, integration, principal = _scenario(db, org.id, opa_url)
    _intent, _decision, operation, consumed, nonce = _authorize_and_consume(
        db, org.id, identity, binding, agent, principal.name,
        business_operation_id="STRIPE-OP-005", external_operation_id="ext-005", amount=5000,
    )
    backend = adapter.FakeStripeBackend()
    boi = db.get(BusinessOperationIdentity, operation.business_operation_identity_id)
    destination_identity = _destination_identity(db, operation)
    metadata = adapter.build_metadata(organization_id=str(org.id), integration_id=str(integration.id), business_operation_identity_id=str(boi.id), destination_dispatch_identity=destination_identity, operation_id=str(operation.id), capability_nonce=nonce)
    key = adapter.idempotency_key(organization_id=str(org.id), integration_id=str(integration.id), destination_dispatch_identity=destination_identity, operation_kind=adapter.OPERATION_KIND_CREATE)
    backend.create_payment_intent(idempotency_key=key, amount=5000, currency="usd", metadata=metadata)
    with pytest.raises(adapter.StripeClientError) as exc_info:
        backend.create_payment_intent(idempotency_key=key, amount=999999, currency="usd", metadata=metadata)
    assert exc_info.value.status_code == 400
    assert exc_info.value.body["error"]["type"] == "idempotency_error"


# === 7. Revocation before execution ==============================================


def test_revocation_before_execution_blocks_consumption_dispatch_never_reached(db, opa_url):
    """The Agent is suspended AFTER issuance but BEFORE the Capability
    is ever consumed -- verify_and_consume_capability's own existing,
    already-tested freshness recheck fails closed, and this adapter's
    own dispatch function is structurally never reached (there is no
    consumed Capability to dispatch against)."""
    org = _org(db)
    identity, signing_key, _cv, binding, agent, integration, principal = _scenario(db, org.id, opa_url)
    intent, decision, _ev = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
        amount=5000, currency="USD", counterparty=None, context={},
        requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        external_operation_id="ext-006", business_operation_id="STRIPE-OP-006", intended_destination=DESTINATION,
    )
    assert decision.outcome == "ALLOW"
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="stripe-sandbox-adapter")

    agent_service.suspend_agent(db, agent.id, reason="pending investigation")

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "stripe-sandbox-adapter", ACTION, SUPPLIER_RESOURCE,
            {"amount": "5000.00", "currency": "USD", "environment": "production"},
            environment=binding.environment, enforcement_binding_id=binding.id, expected_organization_id=org.id,
        )
    # No consumed Capability exists, so nothing in this adapter's own
    # dispatch_payment_intent could ever be called -- there is no
    # capability_nonce/consumed result to pass it. Confirmed structurally,
    # not just by absence of a call in this test.
    operation = db.scalar(select(Operation).where(Operation.decision_id == decision.id))
    assert operation.execution_stage == "AUTHORIZED"
    assert operation.capability_id is None


# === 8. Revocation during recovery, with permitted read-only observation =========


def test_revocation_during_recovery_still_permits_read_only_observation(db, opa_url):
    """Execution authority (the Agent) is revoked AFTER dispatch but
    BEFORE the outcome is known -- a later, signed Adapter observation
    must still be recordable (observation authority is a separate
    permission from execution authority), matching this review's own
    earlier-verified schedule_1 trace pattern, now exercised through
    this specific adapter's own dispatch path."""
    org = _org(db)
    identity, signing_key, _cv, binding, agent, integration, principal = _scenario(db, org.id, opa_url)
    _intent, _decision, operation, consumed, nonce = _authorize_and_consume(
        db, org.id, identity, binding, agent, principal.name,
        business_operation_id="STRIPE-OP-007", external_operation_id="ext-007",
    )
    backend = adapter.FakeStripeBackend()  # default_outcome="succeeded"
    dispatched = _dispatch_and_confirm(backend, org, integration, operation, nonce, db)
    operation_service.record_claim(db, org.id, operation, consumed.capability_id)

    agent_service.suspend_agent(db, agent.id, reason="pending investigation")

    # A signed observation is still recordable -- suspending the Agent
    # does not revoke the IntegrationIdentity's own observation authority.
    _report_signed(
        db, org.id, operation, identity, signing_key, binding, status="SUCCEEDED",
        payment_intent_id=dispatched.payment_intent_id, external_operation_id="ext-007",
    )
    db.refresh(operation)
    assert operation.outcome_status == "COMMITTED"

    # But a NEW attempt by this same suspended Agent is correctly
    # blocked -- at the earliest point, Intent submission itself
    # (integration_runtime_service's own origin-Agent eligibility
    # check), before a Decision or Capability is ever reached.
    with pytest.raises(runtime_svc.IntegrationRejectionError, match="origin_agent_not_eligible"):
        runtime_svc.submit_attested_intent(
            db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
            source_operation=SOURCE_OPERATION, action=ACTION, resource=SUPPLIER_RESOURCE,
            amount=5000, currency="USD", counterparty=None, context={},
            requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
            external_operation_id="ext-007-retry", business_operation_id="STRIPE-OP-007-RETRY", intended_destination=DESTINATION,
        )


# === 9. Expired idempotency protection blocks automatic recreation while the
# outcome remains unresolved ======================================================


def test_expired_protection_with_unresolved_outcome_blocks_automatic_recreation(db, opa_url):
    """Two distinct things, both proven: (1) Stripe's own real 24-hour
    key-retention window, simulated directly against FakeStripeBackend --
    past it, the SAME key produces a genuinely new object, never the
    cached original ('we generate a new request if a key is reused
    after the original is pruned'). (2) This review's own new
    requirement: PayReality's adapter must not rely on that window at
    all -- past it, with the outcome still unresolved, dispatch_payment_
    intent must BLOCK outright (DispatchWindowExpiredError) rather than
    silently dispatching under cover of a key Stripe itself would treat
    as brand new."""
    org = _org(db)
    identity, signing_key, _cv, binding, agent, integration, principal = _scenario(db, org.id, opa_url)
    _intent, _decision, operation, consumed, nonce = _authorize_and_consume(
        db, org.id, identity, binding, agent, principal.name,
        business_operation_id="STRIPE-OP-009", external_operation_id="ext-009a",
    )
    backend = adapter.FakeStripeBackend()
    boi = db.get(BusinessOperationIdentity, operation.business_operation_identity_id)
    destination_identity = _destination_identity(db, operation)
    metadata = adapter.build_metadata(organization_id=str(org.id), integration_id=str(integration.id), business_operation_identity_id=str(boi.id), destination_dispatch_identity=destination_identity, operation_id=str(operation.id), capability_nonce=nonce)
    key = adapter.idempotency_key(organization_id=str(org.id), integration_id=str(integration.id), destination_dispatch_identity=destination_identity, operation_kind=adapter.OPERATION_KIND_CREATE)
    first = backend.create_payment_intent(idempotency_key=key, amount=5000, currency="usd", metadata=metadata)

    backend._clock.advance(adapter.STRIPE_IDEMPOTENCY_KEY_RETENTION_HOURS * 3600 + 60)
    second = backend.create_payment_intent(idempotency_key=key, amount=5000, currency="usd", metadata=metadata)
    assert second["id"] != first["id"], "past Stripe's own retention window, the SAME key must produce a genuinely new object, not the cached original"

    # PayReality's own outcome tracking is still UNKNOWN throughout --
    # nothing here or in operation_service infers a resolution merely
    # because time passed.
    assert operation.outcome_status == "UNKNOWN"
    safety = operation_service.evaluate_replacement_safety(db, org.id, operation.id)
    assert safety.safety == "UNSAFE_UNRESOLVED", "an unresolved operation stays unsafe to replace regardless of how much real or simulated time has passed"

    # This review's own new requirement: the real orchestration function
    # must not even attempt to dispatch past this window while unresolved.
    now_past_window = _first_dispatch_attempted_at(db, operation) + timedelta(hours=25)
    pre_existing_count = len(backend._payment_intents)
    with pytest.raises(adapter.DispatchWindowExpiredError):
        _dispatch_and_confirm(backend, org, integration, operation, nonce, db, now=now_past_window)
    assert len(backend._payment_intents) == pre_existing_count, "blocked before any further Stripe-side call was even attempted"


def test_expired_window_does_not_block_once_outcome_is_resolved(db, opa_url):
    """The guard's own complement: once the original's outcome has been
    PROVEN (TERMINALLY_NOT_COMMITTED), the window guard does not apply
    at all -- a resolved operation's own safety is governed by
    evaluate_replacement_safety, not by this expiry guard, which exists
    only to block blind recreation of a still-UNRESOLVED one."""
    org = _org(db)
    identity, signing_key, _cv, binding, agent, integration, principal = _scenario(db, org.id, opa_url)
    _intent, _decision, operation, consumed, nonce = _authorize_and_consume(
        db, org.id, identity, binding, agent, principal.name,
        business_operation_id="STRIPE-OP-009B", external_operation_id="ext-009b",
    )
    backend = adapter.FakeStripeBackend(default_outcome="declined")
    dispatched = _dispatch_and_confirm(backend, org, integration, operation, nonce, db)
    operation_service.record_claim(db, org.id, operation, consumed.capability_id)
    operation_service.record_dispatch_evidence(
        db, org.id, operation.id, reporter_kind=operation_service.REPORTER_SIGNED_ADAPTER_IDENTITY,
        signature_verified=True, reported_by=f"integration_identity:{identity.name}",
        integration_identity_id=identity.id, destination=DESTINATION, destination_operation_id=dispatched.payment_intent_id,
    )
    _report_signed(
        db, org.id, operation, identity, signing_key, binding, status="FAILED",
        payment_intent_id=dispatched.payment_intent_id, external_operation_id="ext-009b",
    )
    db.refresh(operation)
    assert operation.outcome_status == "TERMINALLY_NOT_COMMITTED"

    now_past_window = _first_dispatch_attempted_at(db, operation) + timedelta(hours=25)
    # No exception: the guard only blocks an UNRESOLVED outcome past the window.
    adapter.ensure_dispatch_window_still_valid(
        first_dispatch_attempted_at=_first_dispatch_attempted_at(db, operation),
        outcome_status=operation.outcome_status, now=now_past_window,
    )


# === 10. Wrong account/environment/tenant cannot reuse or redirect an identity ===


def test_wrong_tenant_cannot_reuse_or_redirect_an_identity():
    """Tenant/account scoping is embedded DIRECTLY in the idempotency key
    string itself -- not relied upon via metadata alone (this review's
    own explicit requirement). Even if two different organizations (or
    two different integrations within the same organization) somehow
    computed the identical destination_dispatch_identity value, the
    resulting Stripe-level key would still differ, so one tenant's own
    retry can never resume or redirect another's Stripe object. A pure,
    DB-free test: the property holds at the key-derivation layer itself,
    not merely as an accident of how real UUIDs never collide."""
    shared_destination_identity = str(uuid.uuid4())
    key_org_a = adapter.idempotency_key(
        organization_id="org-a", integration_id="integration-1",
        destination_dispatch_identity=shared_destination_identity, operation_kind=adapter.OPERATION_KIND_CREATE,
    )
    key_org_b = adapter.idempotency_key(
        organization_id="org-b", integration_id="integration-1",
        destination_dispatch_identity=shared_destination_identity, operation_kind=adapter.OPERATION_KIND_CREATE,
    )
    key_same_org_different_integration = adapter.idempotency_key(
        organization_id="org-a", integration_id="integration-2",
        destination_dispatch_identity=shared_destination_identity, operation_kind=adapter.OPERATION_KIND_CREATE,
    )
    assert key_org_a != key_org_b, "two different organizations must never share a Stripe-level key, even given an identical destination identity"
    assert key_org_a != key_same_org_different_integration, "two different integrations within the SAME organization must never share a key either"

    backend = adapter.FakeStripeBackend()
    real = backend.create_payment_intent(idempotency_key=key_org_a, amount=5000, currency="usd", metadata={})
    # Org B's own key, despite the shared destination identity, finds no
    # cached result at all -- it creates its OWN, independent object
    # rather than resuming or redirecting org A's.
    other = backend.create_payment_intent(idempotency_key=key_org_b, amount=5000, currency="usd", metadata={})
    assert other["id"] != real["id"]


# === 11. Status lookup returning an unresolved result =============================


def test_status_lookup_unresolved_result_stays_unknown(db, opa_url):
    org = _org(db)
    identity, signing_key, _cv, binding, agent, integration, principal = _scenario(db, org.id, opa_url)
    _intent, _decision, operation, consumed, nonce = _authorize_and_consume(
        db, org.id, identity, binding, agent, principal.name,
        business_operation_id="STRIPE-OP-009", external_operation_id="ext-009",
    )
    backend = adapter.FakeStripeBackend(default_outcome="requires_action")
    dispatched = _dispatch_and_confirm(backend, org, integration, operation, nonce, db)
    assert dispatched.status == "requires_action"

    looked_up = adapter.retrieve_status(backend, payment_intent_id=dispatched.payment_intent_id)
    assert looked_up["status"] == "requires_action"

    operation_service.record_claim(db, org.id, operation, consumed.capability_id)
    _report_signed(
        db, org.id, operation, identity, signing_key, binding, status="UNKNOWN",
        payment_intent_id=dispatched.payment_intent_id, external_operation_id="ext-009",
    )
    db.refresh(operation)
    assert operation.outcome_status == "UNKNOWN"


# === 12. Observation path cannot create or confirm a PaymentIntent ===============


def test_status_lookup_path_cannot_create_or_confirm(db, opa_url):
    """Structural proof, not just observation: a client object that
    implements ONLY retrieve_payment_intent (no create/confirm methods
    at all) is fully sufficient for retrieve_status -- proving the
    status-lookup path is incapable of mutating anything, by
    construction, not merely by convention."""
    class ReadOnlyOnlyClient:
        def __init__(self, backend):
            self._backend = backend

        def retrieve_payment_intent(self, *, payment_intent_id):
            return self._backend.retrieve_payment_intent(payment_intent_id=payment_intent_id)

    backend = adapter.FakeStripeBackend()
    created = backend.create_payment_intent(idempotency_key="k1", amount=1000, currency="usd", metadata={})
    read_only_client = ReadOnlyOnlyClient(backend)
    result = adapter.retrieve_status(read_only_client, payment_intent_id=created["id"])
    assert result["id"] == created["id"]
    assert not hasattr(read_only_client, "create_payment_intent")
    assert not hasattr(read_only_client, "confirm_payment_intent")


# === 13. Distinct legitimate operations with identical material fields ==========


def test_distinct_operations_with_identical_material_fields_do_not_collide(db, opa_url):
    org = _org(db)
    identity, signing_key, _cv, binding, agent, integration, principal = _scenario(db, org.id, opa_url)
    _intent_a, _decision_a, operation_a, consumed_a, nonce_a = _authorize_and_consume(
        db, org.id, identity, binding, agent, principal.name,
        business_operation_id="STRIPE-OP-011-A", external_operation_id="ext-011-a", amount=5000,
    )
    _intent_b, _decision_b, operation_b, consumed_b, nonce_b = _authorize_and_consume(
        db, org.id, identity, binding, agent, principal.name,
        business_operation_id="STRIPE-OP-011-B", external_operation_id="ext-011-b", amount=5000,
    )
    boi_a = db.get(BusinessOperationIdentity, operation_a.business_operation_identity_id)
    boi_b = db.get(BusinessOperationIdentity, operation_b.business_operation_identity_id)
    assert boi_a.id != boi_b.id, "different declared business_operation_id values must never collide, even with identical material fields"

    backend = adapter.FakeStripeBackend()
    dispatched_a = _dispatch_and_confirm(backend, org, integration, operation_a, nonce_a, db)
    dispatched_b = _dispatch_and_confirm(backend, org, integration, operation_b, nonce_b, db)
    assert dispatched_a.payment_intent_id != dispatched_b.payment_intent_id

    backend.set_outcome(dispatched_a.payment_intent_id, "succeeded")
    backend.set_outcome(dispatched_b.payment_intent_id, "succeeded")
    dispatched_a = _dispatch_and_confirm(backend, org, integration, operation_a, nonce_a, db)
    dispatched_b = _dispatch_and_confirm(backend, org, integration, operation_b, nonce_b, db)
    assert dispatched_a.status == "succeeded"
    assert dispatched_b.status == "succeeded"


# === Real Stripe test-mode: explicitly gated, not run in this session ===========


def test_real_stripe_client_requires_explicit_test_mode_key_and_execution_switch(monkeypatch):
    """No real Stripe call is ever made in this file. This test only
    confirms the double-gate itself: build_real_client_from_env returns
    None (never a client) unless BOTH a real-looking test-mode secret
    key AND the explicit execution switch are present, and
    RealStripeClient refuses construction outright with anything that
    isn't an sk_test_ key -- rejecting a live-mode key even if one were
    (incorrectly) supplied."""
    monkeypatch.delenv("STRIPE_TEST_SECRET_KEY", raising=False)
    monkeypatch.delenv("STRIPE_SANDBOX_EXECUTE", raising=False)
    assert adapter.build_real_client_from_env() is None

    monkeypatch.setenv("STRIPE_TEST_SECRET_KEY", "sk_test_fake_for_this_assertion_only")
    assert adapter.build_real_client_from_env() is None, "must still refuse without the explicit execution switch"

    monkeypatch.setenv("STRIPE_SANDBOX_EXECUTE", "true")
    client = adapter.build_real_client_from_env()
    assert isinstance(client, adapter.RealStripeClient)

    with pytest.raises(ValueError, match="live"):
        adapter.RealStripeClient("sk_live_this_must_be_rejected")
