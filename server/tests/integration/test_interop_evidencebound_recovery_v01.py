"""EVIDENCEBOUND-PAYREALITY-RECOVERY-V01: real-path verification of the
agreed recovery experiment against PayReality's actual implementation.
Every claim below is either (a) a real, executed test result against
real service code, or (b) explicitly labeled as a harness simulation or
an unimplemented design, never presented as shipped behavior. No
production code was changed to make any test in this file pass.

INTEROP_ID = "EVIDENCEBOUND-PAYREALITY-RECOVERY-V01"
OPERATION_ID = "EVIDENCEBOUND-PAYREALITY-RECOVERY-V01-OP-001"

Frozen synthetic action (identical for both recovery schedules):
  operation: order submission
  quantity: 120 units, supplier: A, buyer account: B, delivery location: X
  destination (synthetic, fixed): "synthetic:evidencebound-fulfillment-01"

========================================================================
IMPLEMENTATION MAP (payreality-demo-audit/server/app/, all read fresh
this session, not assumed from a prior audit; git status confirmed none
of these files are touched by the unrelated, pre-existing uncommitted
work already in this working tree):

  Authority evaluation      domain/decision/engine.py (evaluate(); pure
                             function, OPA-backed, no execution)
  Approval binding          services/resolution_service.py
                             (resolve_decision; separate, linked record,
                             never rewrites the original Decision)
  Capability issuance       services/capability_service.py
                             (issue_capability_for_decision /
                             _for_reviewed_decision -> shared
                             _issue_and_persist tail)
  Capability consumption    services/capability_service.py
                             (verify_and_consume_capability;
                             domain/capability/token.py
                             verify_capability_token for the
                             signature/exact-parameter checks)
  Freshness re-check        services/capability_service.py
                             (_check_consumption_freshness -- called
                             BEFORE the atomic consume UPDATE, same
                             transaction)
  Revocation                services/agent_service.py (revoke_agent,
                             terminal); services/integration_identity_
                             service.py (suspend_integration_identity,
                             reversible)
  Integration identities    services/integration_identity_service.py;
                             services/integration_runtime_service.py
                             (submit_attested_intent -- Section 22
                             trusted-context filtering)
  Receipt submission        services/execution_receipt_service.py
                             (submit_execution_receipt)
  Reconciliation            services/execution_reconciliation_service.py
                             (reconcile_decision) -- re-confirmed fresh
                             this session: zero router call sites exist
                             anywhere under app/routers/ (grepped
                             directly); reachable only by calling the
                             Python function, as this file does
  Destination interaction   NONE. Confirmed: no code anywhere in
                             server/app calls out to an external
                             destination. PayReality only ever receives
                             a self-reported receipt through
                             execution_receipt_service; it never
                             observes a destination directly. This is
                             why every FakeDestination call below is
                             this test file's own code, never
                             PayReality's.

Classification used throughout this file's traces and comparison table:
  1. WHAT THE CURRENT CODE ALREADY DOES -- exercised directly against
     the real functions above, in this file, this session.
  2. WHAT A TEST HARNESS CAN SIMULATE -- FakeDestination's controlled
     behaviour, and this file's own multiprocess race driver; never
     presented as PayReality behaviour.
  3. WHAT REQUIRES AN IMPLEMENTATION CHANGE -- named explicitly wherever
     hit (e.g. no HTTP route for reconciliation; no proactive
     authority-change watch on a pending Capability).
  4. WHAT REQUIRES INDEPENDENT DESTINATION EVIDENCE -- effect_count and
     "safety of a new attempt" in particular: PayReality has no
     mechanism to establish either on its own, and this file never
     claims it does, even when its own synthetic destination happens to
     know the ground truth (a test-only privilege, labelled as such in
     every trace's evidence_source field).
========================================================================

Material fields, PAYREALITY-VERIFIED, not assumed: this order's
Integration Contract Version declares resource_path="order.supplier"
(material, always exact-matched) and context_bindings for quantity,
buyer_account, and delivery_location (auto-copied into the Capability's
own `constraints` dict by capability_service._issue_and_persist, exact-
matched at consumption). unit_price is deliberately NOT declared,
exposing the real gap this file's own material-fields tests prove: a
field never captured in the first place is invisible to every layer
that would otherwise catch a change to it, not a theoretical concern.
"""

import json
import multiprocessing
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

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
    agent_service,
    capability_service,
    enforcement_binding_service as binding_svc,
    execution_receipt_service as receipt_svc,
    execution_reconciliation_service as reconciliation_svc,
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
    integration_runtime_service as runtime_svc,
    runtime_policy_service as policy_svc,
    signing_key_service,
)

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)

INTEROP_ID = "EVIDENCEBOUND-PAYREALITY-RECOVERY-V01"
OPERATION_ID = "EVIDENCEBOUND-PAYREALITY-RECOVERY-V01-OP-001"
ACTION = "purchase_order_create"  # KNOWN_SCOPES (domain/decision/scope_vocabulary.py) is a
# deliberately bounded, fixed action vocabulary, confirmed by hitting
# ContractValidationError on an unrecognized name before this fix:
# {"vendor_payment", "purchase_order_create", "wire_transfer",
# "disable_user", "supplier_bank_details_change"}. An order submission
# maps onto "purchase_order_create", not an arbitrary caller-chosen string.
SOURCE_OPERATION = "EVIDENCEBOUND/v1.SubmitOrder"
DESTINATION = "synthetic:evidencebound-fulfillment-01"
SUPPLIER_RESOURCE = "supplier:A"
CONTEXT = {"quantity": 120, "buyer_account": "ACCT-B", "delivery_location": "location:X"}

_TRACE_PATH = os.path.join(
    os.path.dirname(__file__), "_interop_evidencebound_recovery_v01_output", "traces.jsonl",
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
    if "opa_url" not in request.fixturenames:
        yield
        return
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


def _trace(schedule: str, event: str, **fields) -> None:
    """Sanitised, machine-readable, append-only trace record. Sanitised
    means: no credentials, no personal data, no internal endpoints --
    none exist in this synthetic scenario to begin with, which is
    stated here rather than silently assumed. IDs below are this
    session's real, implementation-specific values (UUIDs, token
    hashes), not redacted, since they carry no sensitive information on
    their own."""
    record = {
        "interop_id": INTEROP_ID, "operation_id": OPERATION_ID,
        "schedule": schedule, "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    for k, v in fields.items():
        if isinstance(v, uuid.UUID):
            v = str(v)
        record[k] = v
    with open(_TRACE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


# === FakeDestination: the only mock in this file ================================


class DestinationBehaviour(Enum):
    COMMIT_NO_RECEIPT = "commit_no_receipt"
    NOT_FOUND_NOW = "not_found_now"


@dataclass
class FakeDestination:
    """This file's own synthetic test destination, fixed as
    DESTINATION above for both schedules. PayReality never calls this
    class; only this test file's own "Adapter" logic does, mirroring
    the real architecture (PayReality has no destination-interaction
    code at all -- see the implementation map).

    Design capabilities, stated plainly per the brief's own question:
    - Terminal non-commit proof: this class COULD implement one (a
      TERMINAL_NOT_COMMITTED behaviour, proven feasible in this
      project's prior interop-trace-v0.1 harness); it is deliberately
      never invoked in Schedule 2 below, so Schedule 2 never obtains it.
    - Reliable duplicate prevention for a given operation_id: NOT
      implemented here. This class is stateless per call; it does not
      track "have I already committed this exact operation_id" the way
      a real destination's own idempotency key might. This is a real,
      disclosed limitation of the synthetic harness, not of PayReality.

    `internal_committed_state`/`commit_count` are this fake's own
    private ground truth -- a test-only privilege. Every trace that
    reads them says so in its own evidence_source field, because
    PayReality itself has no access to this state, ever."""

    behaviour: DestinationBehaviour
    internal_committed_state: bool = field(init=False, default=False)
    commit_count: int = field(init=False, default=0)

    def attempt(self, operation_id: str) -> str:
        if self.behaviour == DestinationBehaviour.COMMIT_NO_RECEIPT:
            self.internal_committed_state = True
            self.commit_count += 1
            return "COMMITTED_INTERNALLY_NO_RECEIPT_ISSUED"
        if self.behaviour == DestinationBehaviour.NOT_FOUND_NOW:
            return "NOT_FOUND_NOW"
        raise AssertionError(f"unhandled behaviour {self.behaviour}")

    def late_authoritative_observation(self, operation_id: str) -> str:
        """A separate, later, authoritative query -- distinct from a
        self-reported receipt. Only meaningful for COMMIT_NO_RECEIPT in
        this harness: it returns what the synthetic destination itself
        would authoritatively confirm if asked."""
        if self.behaviour == DestinationBehaviour.COMMIT_NO_RECEIPT:
            return "COMMITTED"
        return "NOT_FOUND_NOW"


# === Real-path setup helpers =====================================================


def _org(db, name="Org EvidenceBound Recovery"):
    org = Organization(id=uuid.uuid4(), name=name)
    db.add(org)
    db.commit()
    return org


def _deploy_policy(db, org_id, opa_url, *, effect=Effect.ALLOW, resource=SUPPLIER_RESOURCE):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="evidencebound-recovery-policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="OrderingAgent01", action=ACTION, resource=resource),
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


def _scenario(db, org_id, *, extra_context_bindings=None):
    """Registers the Trusted Adapter, an Integration Contract Version
    declaring resource_path="order.supplier" plus context_bindings for
    quantity/buyer_account/delivery_location (unit_price deliberately
    NOT declared -- see the material-fields gap tests), and the origin
    Agent."""
    bindings = {"quantity": "order.quantity", "buyer_account": "order.buyer_account", "delivery_location": "order.delivery_location"}
    if extra_context_bindings:
        bindings.update(extra_context_bindings)
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "EvidenceBound Reference Adapter", "ed25519:base64:AAAA")
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)
    integration = contract_svc.create_integration(db, org_id, "EvidenceBound Fulfillment (reference)")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, SOURCE_OPERATION, ACTION,
        resource_path="order.supplier", amount_path=None, currency_path=None,
        fact_subject_path=None, context_bindings=bindings,
    )
    contract_version = contract_svc.validate_contract_version(db, contract_version.id, org_id)
    contract_version = contract_svc.approve_contract_version(db, contract_version.id, org_id, approver="governance-admin@example.com")

    principal = Principal(id=uuid.uuid4(), name="OrderingAgent01", organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="Ordering Agent 01", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()

    binding = binding_svc.create_draft_binding(db, org_id, identity.id, contract_version.id, "production", agent_ids=[agent.id])
    binding = binding_svc.activate_binding(db, binding.id, org_id)
    return identity, contract_version, binding, agent


def _submit_order_intent(db, identity, binding, agent, *, external_operation_id, resource=SUPPLIER_RESOURCE, context=None):
    return runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=resource,
        amount=None, currency=None, counterparty=None,
        context=context if context is not None else dict(CONTEXT), requested_at=datetime.now(timezone.utc),
        nonce=uuid.uuid4().hex, correlation_id=None, external_operation_id=external_operation_id,
    )


def _expected_constraints(context=None, environment="production"):
    constraints = {}
    for k, v in (context if context is not None else CONTEXT).items():
        constraints[k] = str(v)
    constraints["environment"] = environment
    return constraints


def _submit_receipt(db, identity, binding, decision, intent, *, status, capability_id=None):
    return receipt_svc.submit_execution_receipt(
        db, identity, enforcement_binding_id=binding.id, decision_id=decision.id,
        canonical_action_digest=intent.canonical_action_digest,
        external_operation_id=intent.external_operation_id,
        destination=DESTINATION, status=status, capability_id=capability_id,
    )


# === Schedule 1: late committed outcome =========================================


def test_schedule_1_late_committed_outcome(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)

    # Step 1: execution authority is valid.
    intent, decision, _ev = _submit_order_intent(db, identity, binding, agent, external_operation_id=OPERATION_ID)
    assert decision.outcome == "ALLOW"
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")
    _trace(
        "1", "execution_authority_valid", attempt_id=intent.id, capability_id=issued.capability_id,
        execution_authority="GRANTED", evidence_source="payreality_decision_engine",
    )

    # Step 2: the operation is authorized and attempted (single-use consumption).
    destination = FakeDestination(DestinationBehaviour.COMMIT_NO_RECEIPT)
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    _trace(
        "1", "operation_attempted", attempt_id=intent.id, capability_id=consumed.capability_id,
        execution_authority="CONSUMED_SINGLE_USE", evidence_source="payreality_capability_consumption",
    )

    # Step 3: destination commits once; caller has no durable receipt.
    result = destination.attempt(OPERATION_ID)
    assert result == "COMMITTED_INTERNALLY_NO_RECEIPT_ISSUED"
    _trace(
        "1", "destination_commit_no_receipt", destination_observation="COMMITTED_INTERNALLY_NO_RECEIPT_ISSUED",
        effect_count=destination.commit_count, evidence_source="synthetic_destination_internal_state (test harness ground truth, NOT obtainable by PayReality)",
    )
    # PayReality's own reading at this point: no receipt was submitted,
    # so its effect count is UNKNOWN, not the harness's privileged "1".
    result_before_receipt = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result_before_receipt.outcome == "RECEIPT_MISSING"
    _trace(
        "1", "payreality_reconciliation_before_receipt", recovery_state="RECEIPT_MISSING",
        effect_count="UNKNOWN", evidence_source="payreality_reconciliation_service (no receipt received)",
    )

    # Step 4: execution authority is revoked.
    agent_service.revoke_agent(db, agent.id, reason="pending investigation, EvidenceBound recovery schedule 1")
    _trace("1", "execution_authority_revoked", agent_id=agent.id, execution_authority="REVOKED", evidence_source="payreality_agent_service")

    # Step 5: a late, authoritative destination observation reports
    # COMMITTED for the original operation_id.
    late_observation = destination.late_authoritative_observation(OPERATION_ID)
    assert late_observation == "COMMITTED"
    _trace("1", "late_authoritative_observation", destination_observation="COMMITTED", evidence_source="synthetic_destination (test-designated authoritative observation)")

    # Check: does execution-authority revocation (the Agent) also block
    # this late observation from being recorded? Real-code answer: no --
    # submit_execution_receipt checks the IntegrationIdentity's and
    # Organization's status, never the Agent's. Observation authority is
    # a separate fact from execution authority; proven, not assumed.
    receipt = _submit_receipt(db, identity, binding, decision, intent, status="SUCCEEDED", capability_id=consumed.capability_id)
    _trace(
        "1", "observation_recorded_despite_revoked_execution_authority", receipt_id=receipt.id,
        execution_authority="REVOKED", observation_authority="INTACT",
        evidence_source="payreality_execution_receipt_service (adapter-reported, authenticated)",
    )

    # Step 6: reconciliation records the historical outcome.
    result_after = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result_after.outcome == "MATCHED"
    _trace(
        "1", "reconciled_matched", recovery_state="MATCHED", effect_count=1,
        evidence_source="payreality_reconciliation_service + adapter_reported_receipt (self-reported integration evidence, not independently destination-authoritative)",
        receipt_id=receipt.id,
    )

    # Step 7: the old capability remains unusable; no duplicate/replacement effect.
    # Real-code finding, not assumed: the freshness re-check
    # (_check_consumption_freshness) runs BEFORE the atomic consume
    # check, so a revoked agent's OriginAgentNotActiveError fires here,
    # not CapabilityTokenAlreadyConsumedError -- the "already consumed"
    # signal is masked once execution authority is also revoked. Either
    # way the token remains unusable; which specific rejection reason
    # surfaces depends on check ordering, reported precisely rather than
    # assumed.
    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
            _expected_constraints(), environment=binding.environment,
            enforcement_binding_id=binding.id, expected_organization_id=org.id,
        )
    with pytest.raises(capability_service.CapabilityAlreadyConsumedForDecisionError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")
    assert destination.commit_count == 1, "no duplicate effect was introduced by any recovery/observation step"
    _trace(
        "1", "capability_remains_unusable_no_duplicate_effect", effect_count=1,
        rejection_reason="OriginAgentNotActiveError (freshness re-check fires before the already-consumed check)",
        recovery_state="MATCHED", authority_to_make_new_attempt="N/A (same operation, not a replacement)",
        evidence_source="payreality_capability_service (single-use + decision-scoped idempotency, both real code)",
    )


def test_schedule_1_identity_revocation_also_blocks_observation(db, opa_url):
    """Explicit check requested by the brief: does revoking the
    IntegrationIdentity (as opposed to the Agent) also block receipt/
    status observation? Real-code answer: yes --
    execution_receipt_service.submit_execution_receipt checks
    `identity.status != "active"` and rejects outright. Reported as the
    actual blocked behaviour, not invented."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    intent, decision, _ev = _submit_order_intent(db, identity, binding, agent, external_operation_id=f"{OPERATION_ID}-IDENTITY-CHECK")
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    destination = FakeDestination(DestinationBehaviour.COMMIT_NO_RECEIPT)
    destination.attempt(f"{OPERATION_ID}-IDENTITY-CHECK")

    identity_svc.suspend_integration_identity(db, identity.id, org.id)
    _trace("1", "observation_authority_revoked_via_identity_suspension", integration_identity_id=identity.id, observation_authority="REVOKED")

    late_observation = destination.late_authoritative_observation(f"{OPERATION_ID}-IDENTITY-CHECK")
    assert late_observation == "COMMITTED"

    from app.services.execution_receipt_service import ExecutionReceiptRejectionError

    with pytest.raises(ExecutionReceiptRejectionError):
        _submit_receipt(db, identity, binding, decision, intent, status="SUCCEEDED", capability_id=consumed.capability_id)
    _trace(
        "1", "late_observation_blocked_by_identity_revocation", destination_observation="COMMITTED",
        observation_authority="REVOKED", recovery_state="RECEIPT_MISSING", effect_count="UNKNOWN",
        evidence_source="payreality_execution_receipt_service (rejected: integration_identity_not_active)",
    )
    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "RECEIPT_MISSING", "outcome stays unresolved -- the real, authoritative COMMITTED observation exists, but no channel can record it"


# === Schedule 2: outcome remains unknown ========================================


def test_schedule_2_outcome_remains_unknown(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-SCHEDULE-2"
    intent, decision, _ev = _submit_order_intent(db, identity, binding, agent, external_operation_id=op_id)
    assert decision.outcome == "ALLOW"
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )

    destination = FakeDestination(DestinationBehaviour.NOT_FOUND_NOW)
    response = destination.attempt(op_id)
    assert response == "NOT_FOUND_NOW"
    _trace(
        "2", "attempt_not_found_now", destination_observation="NOT_FOUND_NOW",
        recovery_state="UNKNOWN", effect_count="UNKNOWN",
        evidence_source="synthetic_destination (ambiguous, not authoritative)",
    )
    # NOT_FOUND_NOW is not treated as proof the operation cannot commit
    # later: no terminal-non-commit branch exists or is invoked; the
    # harness makes no such claim, and no code anywhere infers it either.

    agent_service.revoke_agent(db, agent.id, reason="revoked without terminal outcome evidence, EvidenceBound recovery schedule 2")
    _trace("2", "execution_authority_revoked", agent_id=agent.id, execution_authority="REVOKED")

    # No authoritative terminal outcome evidence is ever obtained. Never
    # query for it, never submit a receipt: there is nothing true to
    # report, matching this project's own prior "no silent success"
    # finding (a missing receipt is not evidence of failure either).

    result = reconciliation_svc.reconcile_decision(db, org.id, decision.id)
    assert result.outcome == "RECEIPT_MISSING"
    _trace(
        "2", "historical_outcome_unresolved", recovery_state="UNRESOLVED (PayReality code value: RECEIPT_MISSING)",
        effect_count="UNKNOWN", evidence_source="payreality_reconciliation_service",
    )

    # No automatic retry or release of the original capability. Same
    # ordering finding as Schedule 1: the freshness re-check fires
    # before the already-consumed check once the agent is revoked.
    with pytest.raises(capability_service.OriginAgentNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
            _expected_constraints(), environment=binding.environment,
            enforcement_binding_id=binding.id, expected_organization_id=org.id,
        )
    with pytest.raises(capability_service.CapabilityAlreadyConsumedForDecisionError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")
    _trace(
        "2", "no_auto_retry_no_release", effect_count="UNKNOWN", recovery_state="UNRESOLVED",
        rejection_reason="OriginAgentNotActiveError (freshness re-check fires before the already-consumed check)",
    )

    # Authority to make a NEW attempt (a genuinely new operation_id) is
    # evaluated and reported as a SEPARATE fact from whether making that
    # attempt is safe. Current policy is unchanged (still ALLOW), so
    # PayReality's own authority layer grants it -- proving grant and
    # safety are genuinely different questions, not the same check
    # phrased two ways.
    from app.services.integration_runtime_service import IntegrationRejectionError

    replacement_op_id = f"{OPERATION_ID}-SCHEDULE-2-REPLACEMENT-001"
    # The SAME revoked agent cannot even submit a new Intent:
    # submit_attested_intent's own _resolve_origin_agent re-checks the
    # origin Agent's status BEFORE evaluation, a separate, earlier check
    # than capability consumption's freshness re-check. Confirmed
    # directly here, not assumed.
    with pytest.raises(IntegrationRejectionError, match="origin_agent_not_eligible"):
        _submit_order_intent(db, identity, binding, agent, external_operation_id=replacement_op_id)
    _trace(
        "2", "authority_to_make_new_attempt_denied_same_agent",
        authority_to_make_new_attempt="DENIED (this specific revoked agent cannot submit even a new, distinct operation_id)",
        evidence_source="payreality_integration_runtime_service (origin_agent_not_eligible)",
    )

    # A DIFFERENT, still-active agent, under the SAME unchanged (still
    # ALLOW) policy, is a genuinely separate question -- and PayReality
    # grants it, proving authority-to-attempt and safety-of-attempt are
    # not the same check phrased two ways.
    _identity2, _cv2, binding2, fresh_agent = _scenario(db, org.id, extra_context_bindings=None)
    replacement_intent, replacement_decision, _e2 = _submit_order_intent(
        db, _identity2, binding2, fresh_agent, external_operation_id=replacement_op_id,
    )
    assert replacement_decision.outcome == "ALLOW", "a fresh, active agent is granted authority under current, unchanged policy"
    _trace(
        "2", "authority_to_make_new_attempt_evaluated",
        authority_to_make_new_attempt="GRANTED (a different, active agent, current policy unchanged)",
        safety_of_new_attempt="NOT_ESTABLISHED (PayReality has no mechanism evaluating duplicate-effect risk against an unresolved prior operation; confirmed by grep, no such service exists)",
        recovery_state="UNRESOLVED", effect_count="UNKNOWN",
        evidence_source="payreality_decision_engine (authority grant) + absence-of-mechanism (no code path establishes safety)",
    )
    # Deliberately stop here: no capability is issued or consumed for
    # this replacement. Authority being grantable is not treated as
    # proof that using it would be safe.
    _trace(
        "2", "replacement_conclusion",
        destination_terminal_non_commit_proof="NOT_OBTAINED (never queried in this schedule; the harness's FakeDestination could offer it, per this file's docstring, but this test deliberately never asks)",
        destination_duplicate_prevention="NOT_OFFERED (this synthetic destination has no operation_id-keyed idempotency; a real destination's guarantee here is unknown and out of scope for this harness)",
        conclusion="REPLACEMENT_REMAINS_UNSAFE",
    )


# === Material fields: what's protected, and the real, disclosed gap ============


def test_material_fields_supplier_change_rejected(db, opa_url):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-MATERIAL-SUPPLIER"
    intent, decision, _ev = _submit_order_intent(db, identity, binding, agent, external_operation_id=op_id)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")

    with pytest.raises(capability_token.CapabilityConstraintMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-pep", ACTION, "supplier:B",  # changed A -> B
            _expected_constraints(), environment=binding.environment,
            enforcement_binding_id=binding.id, expected_organization_id=org.id,
        )
    _trace("material", "supplier_change_rejected", field="supplier", declared_material=True, result="REJECTED")


@pytest.mark.parametrize("field,changed_value", [("quantity", 121), ("buyer_account", "ACCT-B-PRIME"), ("delivery_location", "location:Y")])
def test_material_fields_declared_context_field_change_rejected(db, opa_url, field, changed_value):
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-MATERIAL-{field.upper()}"
    intent, decision, _ev = _submit_order_intent(db, identity, binding, agent, external_operation_id=op_id)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")

    changed_context = dict(CONTEXT)
    changed_context[field] = changed_value
    with pytest.raises(capability_token.CapabilityConstraintMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
            _expected_constraints(context=changed_context), environment=binding.environment,
            enforcement_binding_id=binding.id, expected_organization_id=org.id,
        )
    _trace("material", f"{field}_change_rejected", field=field, declared_material=True, result="REJECTED")


def test_material_fields_undeclared_field_change_not_caught(db, opa_url):
    """The real, disclosed gap: unit_price is never declared in this
    order's Integration Contract Version (see _scenario). An order
    submitted without it, then "executed" at a different unit_price,
    is NOT caught anywhere -- not at the capability layer (nothing was
    ever bound), not anywhere else. Exposed directly, not assumed."""
    org = _org(db)
    identity, _cv, binding, agent = _scenario(db, org.id)
    _deploy_policy(db, org.id, opa_url)
    op_id = f"{OPERATION_ID}-MATERIAL-UNIT-PRICE-GAP"
    intent, decision, _ev = _submit_order_intent(db, identity, binding, agent, external_operation_id=op_id)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")

    # Consumption succeeds even though the "real" order's unit_price
    # (never submitted, never bound) has silently changed -- there is
    # nothing to compare, so nothing rejects it.
    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
        _expected_constraints(), environment=binding.environment,
        enforcement_binding_id=binding.id, expected_organization_id=org.id,
    )
    assert "unit_price" not in consumed.constraints
    _trace(
        "material", "unit_price_change_NOT_caught", field="unit_price", declared_material=False,
        result="CONSUMED_WITHOUT_ANY_UNIT_PRICE_CHECK",
        gap="unit_price is not declared in the Integration Contract Version's context_bindings; PayReality enforces no universal list of required order fields, only whatever a specific integration actually declares",
    )

    # Complementary finding: had the caller instead tried to SUBMIT
    # unit_price as part of the Intent's context (rather than silently
    # never mentioning it), submission itself is rejected outright, not
    # silently accepted -- Section 22's trusted-context filtering.
    from app.services.integration_runtime_service import IntegrationRejectionError

    with pytest.raises(IntegrationRejectionError, match="unexpected_context_keys"):
        _submit_order_intent(
            db, identity, binding, agent, external_operation_id=f"{op_id}-ATTEMPTED-SUBMIT",
            context={**CONTEXT, "unit_price": 42.5},
        )
    _trace(
        "material", "unit_price_explicit_submission_rejected_outright", field="unit_price",
        result="REJECTED_AT_SUBMISSION (IntegrationRejectionError: unexpected_context_keys)",
        note="an undeclared field is refused if explicitly submitted, not silently accepted -- the gap above is specifically about a field never submitted at all",
    )


# === Separate experiment: two-connection consumption race ======================


def _race_worker(db_path: str, token: str, environment: str, enforcement_binding_id: str, org_id: str, barrier, result_queue, connection_id: str):
    """Runs in its own OS process (multiprocessing, spawn context --
    this module is re-imported fresh by the child, so all top-level
    settings assignments above re-execute before this runs). Opens its
    OWN engine/session against the SAME file-backed SQLite database the
    parent process set up and committed before any child started."""
    import uuid as _uuid
    from sqlalchemy import create_engine as _create_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker
    from app.services import capability_service as _capability_service

    engine = _create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 30})
    session = _sessionmaker(bind=engine)()
    try:
        barrier.wait(timeout=30)
        consumed = _capability_service.verify_and_consume_capability(
            session, token, "reference-pep", ACTION, SUPPLIER_RESOURCE,
            _expected_constraints(), environment=environment,
            enforcement_binding_id=_uuid.UUID(enforcement_binding_id), expected_organization_id=_uuid.UUID(org_id),
        )
        result_queue.put((connection_id, "SUCCESS", str(consumed.capability_id), None))
    except Exception as e:  # pragma: no cover -- surfaced via the assertions below, never swallowed
        result_queue.put((connection_id, "REJECTED", None, f"{type(e).__name__}: {e}"))
    finally:
        session.close()


def test_two_connection_consumption_race(tmp_path, opa_url):
    """Genuine two-PROCESS race (multiprocessing, not threading): two
    independent OS processes, each with its own SQLAlchemy engine and
    connection, racing to consume the identical Capability, against a
    real, file-backed (not in-memory) SQLite database both can actually
    share. Kept structurally separate from the two recovery schedules
    above, per the brief's own instruction.

    Disclosed honestly: this repository's production backing store is
    Postgres, and this project's own prior interop-trace-v0.1 harness
    already attempted the equivalent genuine multi-connection race
    against real Postgres (matching this repo's own
    test_capability_issuance_idempotency_postgres.py precedent) and
    could not, because Docker's daemon was unreachable in that sandboxed
    session -- rechecked fresh this session (`docker ps` still fails to
    reach the daemon). SQLite was substituted here specifically because
    it is the one backing store this environment can genuinely run
    from two separate OS processes without Docker. The application code
    under race -- capability_service.verify_and_consume_capability's
    atomic `UPDATE ... WHERE consumed_at IS NULL` -- is identical code
    to what Postgres would run; SQLite's own file-locking model
    serializes writers differently at the storage layer than Postgres's
    MVCC would, but the correctness property under test here (a single
    SQL UPDATE statement either affects the row or it doesn't) is a
    property of that one statement's atomicity, which SQLite provides
    the same guarantee for. This is stated as what it is: a real
    two-process race against SQLite, not a claim of having reproduced
    the Postgres-specific proof."""
    db_path = str(tmp_path / "evidencebound_race.sqlite3")
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 30})
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

    org = _org(session)
    identity, _cv, binding, agent = _scenario(session, org.id)
    _deploy_policy(session, org.id, opa_url)
    op_id = f"{OPERATION_ID}-RACE-001"
    intent, decision, _ev = _submit_order_intent(session, identity, binding, agent, external_operation_id=op_id)
    issued = capability_service.issue_capability_for_decision(session, org.id, decision.id, audience="reference-pep")
    # Capture plain Python values before closing: the ORM objects
    # themselves become detached once the session closes, and a later
    # attribute access not already loaded into memory would try (and
    # fail) to lazy-load against the closed session.
    binding_environment, binding_id, org_id_str = binding.environment, str(binding.id), str(org.id)
    session.close()  # fully flush/commit and release the setup connection before children start
    _trace("race", "setup_complete", capability_id=issued.capability_id, db_backend="sqlite (file-backed, two-process)")

    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    result_queue = ctx.Queue()
    p1 = ctx.Process(target=_race_worker, args=(db_path, issued.token, binding_environment, binding_id, org_id_str, barrier, result_queue, "connection-1"))
    p2 = ctx.Process(target=_race_worker, args=(db_path, issued.token, binding_environment, binding_id, org_id_str, barrier, result_queue, "connection-2"))
    p1.start()
    p2.start()
    p1.join(timeout=60)
    p2.join(timeout=60)

    results = [result_queue.get(timeout=5) for _ in range(2)]
    for connection_id, outcome, capability_id, error in results:
        _trace(
            "race", "consumption_attempt_result", connection_id=connection_id,
            result=outcome, capability_id=capability_id, error=error,
        )

    successes = [r for r in results if r[1] == "SUCCESS"]
    rejections = [r for r in results if r[1] == "REJECTED"]
    assert len(successes) == 1, f"expected exactly one successful consumption, got {len(successes)}: {results}"
    assert len(rejections) == 1, f"expected exactly one rejected consumption, got {len(rejections)}: {results}"
    assert "CapabilityTokenAlreadyConsumedError" in rejections[0][3], f"the loser must fail with the real typed rejection, not a lock artifact: {rejections[0][3]}"

    verify_session = sessionmaker(bind=engine)()
    row = verify_session.get(CapabilityToken, issued.capability_id)
    assert row.consumed_at is not None
    verify_session.close()
    _trace(
        "race", "final_state", capability_id=issued.capability_id, effect_count=1,
        winner=successes[0][0], loser=rejections[0][0],
        atomic_at_backing_store=True, evidence_source="two independent OS processes, real file-backed SQLite, real application code",
    )

