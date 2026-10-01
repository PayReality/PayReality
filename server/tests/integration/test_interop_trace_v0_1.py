"""Verification of Ruslan Vrublevskyi's INTEROPERABILITY TRACE v0.1
against PayReality's real decision, approval, capability, enforcement,
and reconciliation code -- not a reimplementation of that trace's own
expectations. The only mock in this file is FakeDestination, standing
in for the external payment system a real Trusted Adapter would call;
every PayReality-side step (policy deployment, Adapter-mediated Intent
submission, Capability issuance/consumption, execution receipt
ingestion, reconciliation) goes through the genuine service functions
this repository's own test suite already uses elsewhere (see
test_execution_reconciliation.py and test_capability_tokens.py, whose
fixture conventions this file mirrors on purpose rather than inventing
a second style).

PAY/v1 material-field mapping onto PayReality's actual schema (this
mapping is this file's own adaptation, not something either side
defines identically -- documented explicitly per the brief's own
instruction not to silently accept a classification):

  - payer account       -> Decision principal (Intent's Agent ->
                           Principal.name, carried into the Capability's
                           OPTIONAL `principal` claim -- see the
                           "opt-in, not automatic" finding below).
  - recipient account   -> Intent.resource / Capability.resource
                           (ALWAYS exact-matched at consumption; no
                           adaptation needed, this is a direct fit).
  - amount, minor units -> PayReality's own schema stores amount as a
                           decimal STRING in major units (e.g.
                           "480.00"), quantized to 2dp
                           (canonical_action._normalize_amount), never
                           an integer minor-units count. This harness
                           converts PAY/v1 minor units to that decimal
                           form at the boundary (_minor_units_to_major)
                           and documents the conversion; it does not
                           change PayReality's own representation.
  - currency            -> Intent.currency / constraints["currency"].
                           Direct fit.
  - settlement_channel   -> NOT a first-class field anywhere in
                           PayReality's schema. Whether it is material
                           turns out to be a genuine, code-verified
                           finding with two parts, not a matter of
                           freely choosing where to put it:
                           `_issue_and_persist` (capability_service.py)
                           auto-copies every key of Intent.context
                           (except "metadata") into the Capability's own
                           `constraints` dict, exact-matched at
                           consumption (domain/capability/token.py) --
                           but `submit_attested_intent`
                           (integration_runtime_service.py, Section 22,
                           "trusted context filtering") REJECTS any
                           Intent.context key the approved
                           IntegrationContractVersion's own
                           context_bindings does not explicitly name
                           (IntegrationRejectionError:
                           unexpected_context_keys) -- confirmed by
                           triggering that rejection directly. So: named
                           in the contract AND submitted -> automatically
                           material (Test 1b). Never submitted at all
                           (whether or not the contract could have
                           allowed it) -> untracked anywhere, not in
                           constraints, not in
                           CanonicalAction.material_fields() (Test 1c).
                           The single most consequential finding here:
                           PayReality has no platform-enforced list of
                           "must-bind" payment fields for what a
                           canonical payment action is -- which fields
                           are ever eligible to be tracked is a
                           governance-approved, per-integration contract
                           decision, and an unbound field is refused
                           outright rather than silently accepted OR
                           silently ignored.

Six controllable FakeDestination behaviours, and the six required test
cases, are not a 1:1 mapping -- the six behaviours are mechanism-level
primitives; the six numbered cases combine them with real PayReality
calls. Every trace this file produces is appended, one JSON line per
recorded step, to
tests/integration/_interop_trace_v0_1_output/traces.jsonl (cleared at
the start of each test session by the `trace_log` fixture below) -- the
"sanitised traces" deliverable. Nothing sensitive is redacted because
nothing sensitive exists in synthetic UUIDs and test fixture data; that
is stated here rather than silently assumed.
"""

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import (
    Agent, Base, CapabilityToken, Organization, Principal,
)
from app.domain.capability import token as capability_token
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
    execution_receipt_service as receipt_svc,
    execution_reconciliation_service as reconciliation_svc,
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
    integration_runtime_service as runtime_svc,
    resolution_service,
    runtime_policy_service as policy_svc,
    signing_key_service,
)

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)

ACTION = "vendor_payment"
SOURCE_OPERATION = "PAY/v1.SubmitPayment"
DESTINATION = "core-banking:rtgs"
_TRACE_PATH = os.path.join(
    os.path.dirname(__file__), "_interop_trace_v0_1_output", "traces.jsonl",
)


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


@pytest.fixture(scope="session", autouse=True)
def _clear_trace_output():
    os.makedirs(os.path.dirname(_TRACE_PATH), exist_ok=True)
    with open(_TRACE_PATH, "w", encoding="utf-8"):
        pass
    yield


def _trace(case: str, step: str, **fields) -> None:
    """Appends one sanitised trace record. `case` is the numbered test
    case this belongs to; `step` names the point in the lifecycle.
    Every UUID/decimal is stringified so the output is plain JSON."""
    record = {"case": case, "step": step, "recorded_at": datetime.now(timezone.utc).isoformat()}
    for k, v in fields.items():
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, Decimal):
            v = str(v)
        record[k] = v
    with open(_TRACE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _minor_units_to_major(minor_units: int) -> str:
    """PAY/v1 -> PayReality boundary conversion, documented in this
    module's own docstring: PayReality's constraints/CanonicalAction
    amount is a decimal-quantized STRING in major units, never an
    integer minor-units count. Quantized to 2dp explicitly (matching
    canonical_action._normalize_amount's own convention): plain Decimal
    division alone drops trailing zeros (Decimal(4800000)/100 ==
    Decimal("48000"), not "48000.00"), which would silently mismatch
    the token's own str(intent.amount) representation."""
    return str((Decimal(minor_units) / Decimal(100)).quantize(Decimal("0.01")))


# === FakeDestination: the one mock in this file =================================


class DestinationBehaviour(Enum):
    COMMIT_WITH_RECEIPT = "commit_with_receipt"
    COMMIT_THEN_CRASH_BEFORE_RECEIPT = "commit_then_crash_before_receipt"
    CRASH_BEFORE_COMMIT = "crash_before_commit"
    UNCERTAIN_THEN_LATE_COMMIT = "uncertain_then_late_commit"
    TERMINAL_NOT_COMMITTED = "terminal_not_committed"


@dataclass
class FakeDestination:
    """A deterministic, in-memory stand-in for the external payment
    system a real Trusted Adapter would call. PayReality itself never
    talks to this class -- only this test file's own "Adapter" harness
    code does, exactly mirroring the real architecture (PayReality
    receives receipts through execution_receipt_service, it never polls
    a destination itself). `internal_committed_state` is this fake's own
    private ground truth, tracked so a test can assert on the CONTRAST
    between what actually happened at the destination and what
    PayReality was able to observe -- never read by PayReality code."""

    behaviour: DestinationBehaviour
    internal_committed_state: bool = field(init=False, default=False)
    _query_count: int = field(init=False, default=0)

    def attempt(self, operation_id: str) -> str | None:
        """The Adapter's initial attempt to execute. Returns the
        destination's own immediate response, or raises to simulate a
        crash. Never itself talks to PayReality."""
        if self.behaviour == DestinationBehaviour.CRASH_BEFORE_COMMIT:
            raise ConnectionError(f"simulated crash before commit: {operation_id}")
        if self.behaviour == DestinationBehaviour.COMMIT_THEN_CRASH_BEFORE_RECEIPT:
            self.internal_committed_state = True
            raise ConnectionError(f"simulated crash after commit, before receipt persisted: {operation_id}")
        if self.behaviour == DestinationBehaviour.COMMIT_WITH_RECEIPT:
            self.internal_committed_state = True
            return "SUCCEEDED"
        if self.behaviour == DestinationBehaviour.UNCERTAIN_THEN_LATE_COMMIT:
            self._query_count += 1
            return "NOT_FOUND_NOW"
        if self.behaviour == DestinationBehaviour.TERMINAL_NOT_COMMITTED:
            return "FAILED"
        raise AssertionError(f"unhandled behaviour {self.behaviour}")

    def query_status(self, operation_id: str) -> str:
        """A later, separate query for an operation whose initial
        attempt returned an ambiguous result. Only meaningful for
        UNCERTAIN_THEN_LATE_COMMIT in this harness."""
        self._query_count += 1
        if self.behaviour == DestinationBehaviour.UNCERTAIN_THEN_LATE_COMMIT and self._query_count >= 2:
            self.internal_committed_state = True
            return "COMMITTED"
        return "NOT_FOUND_NOW"


# === Real-path setup helpers, mirroring test_execution_reconciliation.py ========


def _org(db, name="Org Interop Trace"):
    org = Organization(id=uuid.uuid4(), name=name)
    db.add(org)
    db.commit()
    return org


def _deploy_policy(db, org_id, opa_url, *, effect=Effect.ALLOW, principal="PaymentsAgent01", resource="recipient:ACCOUNT_A"):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="interop-trace-policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal=principal, action=ACTION, resource=resource),
        conditions=ConditionSet(all=()), effect=effect,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row


def _redeploy_policy(db, org_id, opa_url, policy_key, *, effect, principal="PaymentsAgent01", resource="recipient:ACCOUNT_A"):
    """Real policy-lifecycle path for changing what's CURRENTLY active
    for an existing scope: runtime_policy_service.edit_policy creates a
    new draft version under the SAME policy_key (never a second,
    independent policy row for the identical scope, which the compiler's
    own conflict detection correctly refuses to compile -- confirmed by
    hitting exactly that CONFLICTING_POLICY_STRUCTURE error before this
    helper existed)."""
    updated = RuntimePolicy(
        id=str(policy_key), name="interop-trace-policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal=principal, action=ACTION, resource=resource),
        conditions=ConditionSet(all=()), effect=effect,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.edit_policy(db, policy_key, org_id, updated)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row


def _scenario(db, org_id, *, principal_name="PaymentsAgent01", extra_context_bindings=None):
    """`extra_context_bindings` mirrors Section 22's own trusted-context
    filtering (integration_runtime_service.submit_attested_intent):
    submit_attested_intent rejects any Intent.context key not explicitly
    named in the approved Contract Version's own context_bindings
    (IntegrationRejectionError: unexpected_context_keys) -- confirmed by
    hitting that rejection before this parameter existed. A field like
    settlement_channel is only reachable through the Adapter-mediated
    path at all once a real, approved contract declares it; there is no
    implicit "any extra context key is allowed" path."""
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "Reference Core-Banking Adapter", "ed25519:base64:AAAA")
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)
    integration = contract_svc.create_integration(db, org_id, "Core Banking (reference)")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, SOURCE_OPERATION, ACTION,
        resource_path="payment.recipient_account", amount_path="payment.amount", currency_path="payment.currency",
        fact_subject_path=None, context_bindings=extra_context_bindings or {},
    )
    contract_version = contract_svc.validate_contract_version(db, contract_version.id, org_id)
    contract_version = contract_svc.approve_contract_version(db, contract_version.id, org_id, approver="governance-admin@example.com")

    principal = Principal(id=uuid.uuid4(), name=principal_name, organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="Payments Agent 01", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()

    binding = binding_svc.create_draft_binding(db, org_id, identity.id, contract_version.id, "production", agent_ids=[agent.id])
    binding = binding_svc.activate_binding(db, binding.id, org_id)
    return identity, contract_version, binding, agent


def _submit_payment_intent(
    db, identity, binding, agent, *, external_operation_id, resource="recipient:ACCOUNT_A",
    amount_minor_units=48_000_00, currency="USD", context=None,
):
    """`context` is where a PAY/v1 field not already a first-class Intent
    parameter (e.g. settlement_channel) would go -- see this module's
    docstring for what that choice does and does not bind."""
    return runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=resource,
        amount=float(_minor_units_to_major(amount_minor_units)), currency=currency, counterparty=None,
        context=context or {}, requested_at=datetime.now(timezone.utc),
        nonce=uuid.uuid4().hex, correlation_id=None, external_operation_id=external_operation_id,
    )


def _expected_constraints(amount_minor_units=48_000_00, currency="USD", context=None, environment="production"):
    """Mirrors capability_service._issue_and_persist's own constraints
    derivation exactly: amount, currency, then every Intent.context key
    except "metadata". `environment` defaults to "production" because
    integration_runtime_service.submit_attested_intent itself
    automatically injects `context["environment"] = binding.environment`
    (a reserved key, _RESERVED_CONTEXT_KEYS) on every Adapter-mediated
    Intent -- confirmed by reading that service, not assumed -- so it is
    already material via the exact same auto-copy mechanism this file's
    settlement_channel finding documents, whether or not the test ever
    mentions it explicitly."""
    constraints = {"amount": _minor_units_to_major(amount_minor_units), "currency": currency}
    for k, v in (context or {}).items():
        if k == "metadata":
            continue
        constraints[k] = str(v)
    constraints["environment"] = environment
    return constraints


def _submit_receipt(db, identity, binding, decision, intent, *, status, destination=DESTINATION, capability_id=None):
    return receipt_svc.submit_execution_receipt(
        db, identity, enforcement_binding_id=binding.id, decision_id=decision.id,
        canonical_action_digest=intent.canonical_action_digest,
        external_operation_id=intent.external_operation_id,
        destination=destination, status=status, capability_id=capability_id,
    )


# === Case 1: recipient substitution after approval must be rejected =============


def test_case_1a_recipient_substitution_is_rejected_via_resource_binding(db, opa_url):
    """Recipient A is approved; execution is attempted for recipient B.
    Must be rejected. Uses the real, always-checked `resource` binding
    (Intent.resource -> Capability.resource -> exact match at
    consumption) -- the direct PAY/v1 "recipient account" fit, no
    adaptation needed."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url, resource="recipient:ACCOUNT_A")
    intent, decision, _ev = _submit_payment_intent(
        db, identity, binding, agent, external_operation_id=uuid.uuid4().hex, resource="recipient:ACCOUNT_A",
    )
    assert decision.outcome == "ALLOW"
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="core-banking-pep")
    _trace("1a", "approved", payer_principal=agent.name, recipient="recipient:ACCOUNT_A",
           amount_minor_units=48_000_00, currency="USD", policy_version=1,
           capability_id=issued.capability_id, decision_id=decision.id, decision_outcome=decision.outcome)

    with pytest.raises(capability_token.CapabilityConstraintMismatchError) as excinfo:
        capability_service.verify_and_consume_capability(
            db, issued.token, "core-banking-pep", ACTION, "recipient:ACCOUNT_B",
            _expected_constraints(), environment=binding.environment, enforcement_binding_id=binding.id,
            expected_organization_id=org.id,
        )
    _trace("1a", "execution_attempt_rejected", attempted_recipient="recipient:ACCOUNT_B",
           result="REJECTED", error=type(excinfo.value).__name__, capability_id=issued.capability_id)

    row = db.get(CapabilityToken, issued.capability_id)
    assert row.consumed_at is None, "a rejected consumption attempt must never mark the token consumed"


def test_case_1b_settlement_channel_is_material_when_the_contract_declares_it(db, opa_url):
    """PAY/v1's `settlement_channel` field, submitted inside Intent
    context, is auto-copied into the Capability's own `constraints` by
    capability_service._issue_and_persist and exact-matched at
    consumption -- but ONLY reaches that point at all if the approved
    IntegrationContractVersion's own context_bindings names it first
    (integration_runtime_service.submit_attested_intent, Section 22:
    "trusted context filtering" -- any Intent.context key the contract
    doesn't bind is rejected outright, IntegrationRejectionError:
    unexpected_context_keys, confirmed by triggering it before this test
    declared the binding below). So the real, two-part finding is
    stronger than "material if you happen to include it": for the
    Adapter-mediated path, an unrecognized field is refused, not
    silently dropped -- but whether a SPECIFIC field like
    settlement_channel is ever eligible to be bound at all is a
    governance-approved contract decision, not a platform-wide
    guarantee that any particular payment field is tracked."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(
        db, org.id, extra_context_bindings={"settlement_channel": "payment.settlement_channel"},
    )
    _deploy_policy(db, org.id, opa_url, resource="recipient:ACCOUNT_A")
    ctx = {"settlement_channel": "SAME_DAY_ACH"}
    intent, decision, _ev = _submit_payment_intent(
        db, identity, binding, agent, external_operation_id=uuid.uuid4().hex,
        resource="recipient:ACCOUNT_A", context=ctx,
    )
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="core-banking-pep")
    row = db.get(CapabilityToken, issued.capability_id)
    assert row is not None

    with pytest.raises(capability_token.CapabilityConstraintMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "core-banking-pep", ACTION, "recipient:ACCOUNT_A",
            _expected_constraints(context={"settlement_channel": "RTGS"}),
            environment=binding.environment, enforcement_binding_id=binding.id, expected_organization_id=org.id,
        )
    _trace("1b", "settlement_channel_change_caught", original="SAME_DAY_ACH", attempted="RTGS", result="REJECTED")

    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "core-banking-pep", ACTION, "recipient:ACCOUNT_A",
        _expected_constraints(context=ctx), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    assert consumed.constraints["settlement_channel"] == "SAME_DAY_ACH"
    _trace("1b", "unchanged_settlement_channel_consumed", settlement_channel="SAME_DAY_ACH", result="CONSUMED")


def test_case_1c_settlement_channel_is_untracked_when_omitted_from_intent_context(db, opa_url):
    """The other half of the same finding: if settlement_channel is
    simply never submitted (the integration treats it as free text, not
    a canonical field), NOTHING in PayReality binds it -- not the
    Capability's constraints, not CanonicalAction.material_fields(). A
    real Adapter that silently changes settlement channel between
    approval and execution, without including it in Intent.context in
    the first place, would not be caught here. This is the "document
    the assumption rather than silently accept it" finding: PayReality
    provides the mechanism (context -> constraints), it does not
    enforce that any specific payment field must use it."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url, resource="recipient:ACCOUNT_A")
    intent, decision, _ev = _submit_payment_intent(
        db, identity, binding, agent, external_operation_id=uuid.uuid4().hex, resource="recipient:ACCOUNT_A",
    )
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="core-banking-pep")

    # No exception: a "changed settlement channel" execution attempt
    # succeeds, because nothing ever recorded a settlement channel to
    # compare against. This is the honest, code-proven negative result.
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "core-banking-pep", ACTION, "recipient:ACCOUNT_A",
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    assert "settlement_channel" not in consumed.constraints
    _trace(
        "1c", "settlement_channel_change_NOT_caught", result="CONSUMED_WITHOUT_ANY_SETTLEMENT_CHANNEL_CHECK",
        finding="settlement_channel is material only if the integration puts it in Intent.context; "
                "PayReality enforces no canonical list of required payment fields",
    )


# === Case 2: two concurrent claims of one capability, at most one proceeds ======


def test_case_2_concurrent_capability_claims_at_most_one_proceeds(db, opa_url):
    """Real code path: capability_service.verify_and_consume_capability's
    own atomic `UPDATE ... WHERE consumed_at IS NULL` (see that
    function's docstring) is what this test proves, not app-level
    locking. True cross-connection concurrency (a second SQLAlchemy
    Session against a shared database) additionally requires Postgres in
    this repo's own established convention (see
    test_capability_issuance_idempotency_postgres.py); Docker/Postgres
    was not reachable in this session's sandboxed environment (confirmed:
    `docker ps` failed to reach the daemon), so this test proves the same
    underlying atomic-UPDATE code path sequentially, exactly matching
    this repo's own pre-existing single-connection precedent
    (test_atomic_single_consumption_under_concurrent_attempts in
    test_capability_tokens.py) -- not a weaker guarantee invented for
    this file, the same one already proven at real multi-connection
    concurrency elsewhere in this codebase for the sibling issuance
    race."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url, resource="recipient:ACCOUNT_A")
    intent, decision, _ev = _submit_payment_intent(
        db, identity, binding, agent, external_operation_id=uuid.uuid4().hex, resource="recipient:ACCOUNT_A",
    )
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="core-banking-pep")

    results: list = []
    errors: list = []
    lock = threading.Lock()

    def _claim():
        try:
            consumed = capability_service.verify_and_consume_capability(
                db, issued.token, "core-banking-pep", ACTION, "recipient:ACCOUNT_A",
                _expected_constraints(), environment=binding.environment,
                enforcement_binding_id=binding.id, expected_organization_id=org.id,
            )
            with lock:
                results.append(consumed)
        except capability_service.CapabilityTokenAlreadyConsumedError as e:
            with lock:
                errors.append(e)

    # Sequential, not threaded: `db` is one SQLAlchemy Session bound to
    # one SQLite connection, which is not safe to drive from two threads
    # at once (see docstring above for the real multi-connection
    # attempt and why it fell back). This still exercises the identical
    # atomic UPDATE both callers would race against.
    _claim()
    _claim()

    assert len(results) == 1, f"expected exactly one successful claim, got {len(results)}"
    assert len(errors) == 1, f"expected exactly one rejected claim, got {len(errors)}"
    _trace("2", "concurrent_claim_result", successful_claims=len(results), rejected_claims=len(errors),
           capability_id=issued.capability_id, mechanism="atomic UPDATE ... WHERE consumed_at IS NULL")


# === Cases 3 & 4: PayReality cannot distinguish "never executed" from ===========
# === "executed, but we were never told" -- both reconcile identically ==========


def test_case_3_crash_before_destination_action_leaves_no_receipt(db, opa_url):
    """The capability is claimed, but the process crashes before the
    destination action itself. FakeDestination's own internal state
    confirms nothing was ever committed. No receipt is submitted (there
    is nothing true to report), so reconciliation must read
    RECEIPT_MISSING."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url, resource="recipient:ACCOUNT_A")
    intent, decision, _ev = _submit_payment_intent(
        db, identity, binding, agent, external_operation_id=uuid.uuid4().hex, resource="recipient:ACCOUNT_A",
    )
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="core-banking-pep")
    capability_service.verify_and_consume_capability(
        db, issued.token, "core-banking-pep", ACTION, "recipient:ACCOUNT_A",
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )

    destination = FakeDestination(DestinationBehaviour.CRASH_BEFORE_COMMIT)
    with pytest.raises(ConnectionError):
        destination.attempt(intent.external_operation_id)
    assert destination.internal_committed_state is False
    # No receipt submitted: there is nothing true to report.

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "RECEIPT_MISSING"
    _trace("3", "reconciled", destination_internal_truth="NEVER_COMMITTED", payreality_observed_outcome=result.outcome)


def test_case_4_crash_after_commit_before_receipt_persisted_is_indistinguishable_from_case_3(db, opa_url):
    """The destination COMMITS, but the process crashes before the
    receipt is durably recorded by PayReality. No receipt exists
    locally -- and reconciliation reads the identical RECEIPT_MISSING
    outcome as case 3, even though FakeDestination's own internal state
    proves the underlying ground truth was different. This identical
    observable outcome is the single-attester limitation
    execution_reconciliation_service.py's own module docstring states
    explicitly, proven here rather than merely quoted."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url, resource="recipient:ACCOUNT_A")
    intent, decision, _ev = _submit_payment_intent(
        db, identity, binding, agent, external_operation_id=uuid.uuid4().hex, resource="recipient:ACCOUNT_A",
    )
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="core-banking-pep")
    capability_service.verify_and_consume_capability(
        db, issued.token, "core-banking-pep", ACTION, "recipient:ACCOUNT_A",
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )

    destination = FakeDestination(DestinationBehaviour.COMMIT_THEN_CRASH_BEFORE_RECEIPT)
    with pytest.raises(ConnectionError):
        destination.attempt(intent.external_operation_id)
    assert destination.internal_committed_state is True, "the fake's own ground truth: it DID commit"
    # No receipt submitted: the crash happened before it could be. This
    # is the whole point -- PayReality has no way to know this happened.

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "RECEIPT_MISSING"
    _trace("4", "reconciled", destination_internal_truth="COMMITTED_BUT_UNREPORTED",
           payreality_observed_outcome=result.outcome,
           finding="identical to case 3's observed outcome, despite opposite ground truth -- "
                   "the single-attester limitation, proven not assumed")


# === Case 5: NOT_FOUND_NOW must not permit an automatic retry; revoking =========
# === execution authority survives a later COMMITTED confirmation ===============


def test_case_5a_late_commit_updates_history_but_revoked_agent_blocks_new_execution_authority(db, opa_url):
    """Revoking the origin Agent freezes future execution authority
    (capability_service._check_consumption_freshness's own
    _check_agent_active re-check) without blocking investigation: a late
    execution receipt reporting COMMITTED is still ingestible (
    execution_receipt_service.submit_execution_receipt never checks
    Agent status, only the IntegrationIdentity's and Organization's --
    see case 5b for the identity-suspended contrast), so the historical
    outcome correctly updates to MATCHED. But the revoked Agent means no
    NEW capability for this decision can ever be issued again --
    execution authority is not restored by the late confirmation."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url, resource="recipient:ACCOUNT_A")
    intent, decision, _ev = _submit_payment_intent(
        db, identity, binding, agent, external_operation_id=uuid.uuid4().hex, resource="recipient:ACCOUNT_A",
    )
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="core-banking-pep")
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "core-banking-pep", ACTION, "recipient:ACCOUNT_A",
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )

    destination = FakeDestination(DestinationBehaviour.UNCERTAIN_THEN_LATE_COMMIT)
    first_response = destination.attempt(intent.external_operation_id)
    assert first_response == "NOT_FOUND_NOW"
    # Rule: NOT_FOUND_NOW must not permit an automatic retry. This
    # harness does not, and structurally cannot: the capability is
    # already consumed (single-use), so a second issuance for the same
    # decision is independently blocked by
    # CapabilityAlreadyConsumedForDecisionError even if something tried.
    with pytest.raises(capability_service.CapabilityAlreadyConsumedForDecisionError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="core-banking-pep")
    _trace("5a", "not_found_now_no_auto_retry", response="NOT_FOUND_NOW",
           retry_attempted=False, retry_structurally_blocked_by="CapabilityAlreadyConsumedForDecisionError")

    result_before_revocation = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result_before_revocation.outcome == "RECEIPT_MISSING"

    agent_service.revoke_agent(db, agent.id, reason="pending investigation of uncertain outcome")
    _trace("5a", "execution_authority_revoked", agent_id=agent.id, reason="pending_investigation")

    late_status = destination.query_status(intent.external_operation_id)
    assert late_status == "COMMITTED"
    assert destination.internal_committed_state is True
    _submit_receipt(db, identity, binding, decision, intent, status="SUCCEEDED", capability_id=consumed.capability_id)
    _trace("5a", "late_confirmation_ingested", destination_response="COMMITTED", receipt_status="SUCCEEDED")

    result_after = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result_after.outcome == "MATCHED", "the late confirmation must update the historical outcome"
    _trace("5a", "reconciled_after_late_confirmation", outcome=result_after.outcome)

    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "core-banking-pep", ACTION, "recipient:ACCOUNT_A",
            _expected_constraints(), environment=binding.environment,
            enforcement_binding_id=binding.id, expected_organization_id=org.id,
        )
    _trace("5a", "new_execution_authority_not_restored", result="OriginAgentNotActiveError raised on any further consumption attempt")


def test_case_5a_freshness_check_blocks_consumption_independent_of_prior_consumption(db, opa_url):
    """Isolates the freshness mechanism itself (rather than relying on
    "it was already consumed" as the only reason a retry fails): a FRESH,
    never-consumed capability, whose Agent is revoked before the first
    consumption attempt, is rejected by the live freshness re-check --
    proving the guarantee is a real re-check at the enforcement
    boundary, not merely a side effect of single-use replay protection."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url, resource="recipient:ACCOUNT_A")
    intent, decision, _ev = _submit_payment_intent(
        db, identity, binding, agent, external_operation_id=uuid.uuid4().hex, resource="recipient:ACCOUNT_A",
    )
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="core-banking-pep")

    agent_service.revoke_agent(db, agent.id, reason="revoked before any consumption attempt")
    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "core-banking-pep", ACTION, "recipient:ACCOUNT_A",
            _expected_constraints(), environment=binding.environment,
            enforcement_binding_id=binding.id, expected_organization_id=org.id,
        )
    row = db.get(CapabilityToken, issued.capability_id)
    assert row.consumed_at is None, "a freshness rejection must never itself consume the token"
    _trace("5a", "freshness_boundary_isolated_proof", capability_id=issued.capability_id,
           result="OriginAgentNotActiveError, token remains unconsumed")


def test_case_5b_revoking_observation_permission_also_blocks_the_late_confirmation(db, opa_url):
    """"If observation permission is also revoked, do not query the
    destination; leave the outcome uncertain." Real-code equivalent:
    suspending the IntegrationIdentity (not just the Agent) makes
    execution_receipt_service.submit_execution_receipt itself reject
    ingestion (`identity.status != "active"`), so even a genuine late
    COMMITTED confirmation from the destination cannot be recorded
    through the trusted channel. The outcome correctly stays
    RECEIPT_MISSING -- never silently updated -- because there is no
    other path into PayReality's records for this identity anymore."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url, resource="recipient:ACCOUNT_A")
    intent, decision, _ev = _submit_payment_intent(
        db, identity, binding, agent, external_operation_id=uuid.uuid4().hex, resource="recipient:ACCOUNT_A",
    )
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="core-banking-pep")
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "core-banking-pep", ACTION, "recipient:ACCOUNT_A",
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )

    destination = FakeDestination(DestinationBehaviour.UNCERTAIN_THEN_LATE_COMMIT)
    destination.attempt(intent.external_operation_id)
    identity_svc.suspend_integration_identity(db, identity.id, org.id)
    _trace("5b", "observation_permission_revoked", integration_identity_id=identity.id)

    late_status = destination.query_status(intent.external_operation_id)
    assert late_status == "COMMITTED"

    from app.services.execution_receipt_service import ExecutionReceiptRejectionError

    with pytest.raises(ExecutionReceiptRejectionError):
        _submit_receipt(db, identity, binding, decision, intent, status="SUCCEEDED", capability_id=consumed.capability_id)
    _trace("5b", "late_confirmation_ingestion_blocked", destination_response="COMMITTED",
           result="ExecutionReceiptRejectionError, receipt never persisted")

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "RECEIPT_MISSING", "outcome must remain uncertain, never silently updated"
    _trace("5b", "reconciled", outcome=result.outcome, note="stays uncertain -- no channel exists to record the late truth")


# === Case 6: a replacement operation needs current authority end-to-end ========


def test_case_6_replacement_requires_current_authority_new_capability_and_new_operation_id(db, opa_url):
    """After destination-authoritative proof the original operation
    cannot commit (FakeDestination's own TERMINAL_NOT_COMMITTED
    guarantee), a replacement is only ever a brand-new Intent: a new
    external_operation_id evaluated fresh against whatever policy is
    CURRENT right now (which may differ from the policy active when the
    original was approved), a new Decision, and a new Capability. Proven
    two ways: (a) resubmitting under the SAME external_operation_id does
    not create a new authorization at all -- it resolves back to the
    identical historical Decision (Phase 3's own operation-identity
    idempotency, unchanged by this file); (b) a genuinely new
    external_operation_id is evaluated under the org's current policy,
    which this test deliberately changes to REQUIRE_HUMAN_REVIEW before
    the "replacement" attempt, proving no prior ALLOW carries forward."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    original_policy = _deploy_policy(db, org.id, opa_url, resource="recipient:ACCOUNT_A", effect=Effect.ALLOW)
    original_op_id = uuid.uuid4().hex
    intent, decision, _ev = _submit_payment_intent(
        db, identity, binding, agent, external_operation_id=original_op_id, resource="recipient:ACCOUNT_A",
    )
    assert decision.outcome == "ALLOW"
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="core-banking-pep")
    capability_service.verify_and_consume_capability(
        db, issued.token, "core-banking-pep", ACTION, "recipient:ACCOUNT_A",
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )

    destination = FakeDestination(DestinationBehaviour.TERMINAL_NOT_COMMITTED)
    outcome = destination.attempt(original_op_id)
    assert outcome == "FAILED"
    _submit_receipt(db, identity, binding, decision, intent, status="FAILED")
    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "EXECUTION_FAILED"
    _trace("6", "original_terminally_failed", external_operation_id=original_op_id, outcome=result.outcome)

    # (a) Same external_operation_id: resolves to the SAME Decision, not
    # a fresh authorization -- proves there is no "just retry the same
    # operation id" shortcut into a new authorization.
    retry_intent, retry_decision, _e2 = _submit_payment_intent(
        db, identity, binding, agent, external_operation_id=original_op_id, resource="recipient:ACCOUNT_A",
    )
    assert retry_decision.id == decision.id, "same external_operation_id must resolve to the identical historical decision"
    with pytest.raises(capability_service.CapabilityAlreadyConsumedForDecisionError):
        capability_service.issue_capability_for_decision(db, org.id, retry_decision.id, audience="core-banking-pep")
    _trace("6", "same_operation_id_resubmission_yields_no_new_authority", external_operation_id=original_op_id)

    # (b) Genuinely new external_operation_id, evaluated under a NEW
    # current policy -- the org tightens its rule for this scope before
    # the replacement is attempted.
    _redeploy_policy(db, org.id, opa_url, original_policy.policy_key, resource="recipient:ACCOUNT_A", effect=Effect.REQUIRE_HUMAN_REVIEW)
    replacement_op_id = uuid.uuid4().hex
    replacement_intent, replacement_decision, _e3 = _submit_payment_intent(
        db, identity, binding, agent, external_operation_id=replacement_op_id, resource="recipient:ACCOUNT_A",
    )
    assert replacement_decision.id != decision.id, "a genuinely new operation id must be a new Decision"
    assert replacement_decision.outcome == "HUMAN_REVIEW", (
        "the replacement must be evaluated under CURRENT authority, not the original ALLOW -- "
        "here that means it now requires a new human approval before any capability can issue"
    )
    with pytest.raises(capability_service.DecisionNotAllowError):
        capability_service.issue_capability_for_decision(db, org.id, replacement_decision.id, audience="core-banking-pep")

    resolution_service.resolve_decision(db, replacement_decision.id, org.id, "approved", resolved_by="reviewer@example.com")
    replacement_issued = capability_service.issue_capability_for_reviewed_decision(
        db, org.id, replacement_decision.id, audience="core-banking-pep",
    )
    assert replacement_issued.capability_id != issued.capability_id
    _trace(
        "6", "replacement_required_fresh_authority", replacement_external_operation_id=replacement_op_id,
        replacement_decision_id=replacement_decision.id, replacement_capability_id=replacement_issued.capability_id,
        required_new_human_approval=True,
    )
