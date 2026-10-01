"""Product lifecycle vertical slice (EVIDENCEBOUND-PAYREALITY-RECOVERY-V01
follow-up), hardening pass, closeout pass.

Deliberately a thin orchestration layer, not a parallel implementation:
every trust decision this module makes (is this identity/organization
still active, does this receipt's linkage match its decision, is this a
duplicate/conflicting/contradictory report) is delegated to the real,
already-tested execution_receipt_service and execution_reconciliation_
service unchanged -- this module adds exactly what those two don't
already do: an Operation existing at all (separately from a Capability's
own single-use lifetime), an append-only evidence-provenance log
distinguishing what kind of evidence actually supports a conclusion, and
mapping a reconciliation outcome onto this module's own vocabulary under
an explicit evidence-acceptance policy.

Authority vs. safety, kept genuinely separate: AUTHORITY to attempt a
replacement is answered exactly as it always has been -- by submitting a
new Intent through decision/engine.py and seeing whether it evaluates to
ALLOW (or an approved HUMAN_REVIEW). This module never touches that
decision. SAFETY is what evaluate_replacement_safety answers, a
different question entirely: even given fresh authority, would
attempting it risk a duplicate real-world effect against an operation
whose outcome is still open, already committed, or conclusively closed.

Closeout pass, three real fixes over the hardening pass:

  1. Business-operation identity (section 1): the hardening pass's own
     replacement-safety gate ran only when a caller supplied
     replaces_operation_id -- an unlinked Intent bypassed it entirely.
     link_business_operation_attempt is the real fix: for a "supported
     integration" that declares business_operation_id + intended_
     destination at submission time (Intent, schemas/integration_
     runtime.py), the prior operation for a REPEATED identity is
     resolved and safety-checked AUTOMATICALLY, at both capability
     issuance (this module) and capability consumption
     (verify_still_current_attempt, called from capability_service's
     own record_claim transaction) -- never trusting the caller to
     declare a replacement. See app/db/models.py's BusinessOperationIdentity
     docstring for the identity's own definition and why it is
     deliberately NOT material-action equality.

  2. Evidence acceptance rules (section 2): the hardening pass let an
     unsigned RBAC_HUMAN relay drive outcome_status straight to
     COMMITTED merely because reconciliation happened to compute
     MATCHED -- provenance was recorded, but nothing actually gated on
     it. Fixed: only SIGNED_ADAPTER_IDENTITY evidence (or an explicit,
     separately-permissioned manual adjudication) can move outcome_
     status into a terminal value; an unsigned relay's reconciliation
     result is still computed and preserved (OperationEvidenceEvent.
     reconciliation_outcome), but alone leaves outcome_status at
     UNKNOWN. See Operation.evidence_assurance's own docstring
     (app/db/models.py) for the three-tier vocabulary this enforces.

  3. Execution stage vs. outcome certainty (section 3): Operation.state
     (one collapsed string) is replaced by two independent columns,
     execution_stage and outcome_status -- see Operation's own docstring
     for why the single-column design was a real bug (an observation
     resolving to "unknown" silently erased whether the operation had
     been CLAIMED or DISPATCHED), not merely under-documented.

Contract-enforcement pass, two further fixes:

  4. Lifecycle enrollment is now a versioned, per-contract SETTING
     (IntegrationContractVersion.lifecycle_requirement), not merely an
     optional pair of request fields -- a LIFECYCLE_REQUIRED contract's
     submissions are rejected before authorization if either field is
     missing (integration_runtime_service.submit_attested_intent), with
     a defense-in-depth recheck at capability issuance too
     (capability_service._link_business_operation_attempt_if_covered).
     BusinessOperationIdentity's own namespace gained `action` (the
     canonical action type), closing a real collision risk: two
     unrelated action types under the same integration/destination
     could otherwise share a business_operation_id string.

  5. verify_still_current_attempt now rechecks a SECOND, independent
     mutable safety fact at consumption time, not only "is this attempt
     still current": if this operation is itself a replacement
     (previous_attempt_operation_id is set), the safety justification
     that permitted issuing it over the prior attempt is re-evaluated
     right now -- a guarantee withdrawn, expired, or overtaken by new
     evidence between issuance and consumption blocks consumption too
     (ReplacementSafetyWithdrawnError), not only a change in which
     attempt is current (OperationSupersededError).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    BusinessOperationIdentity,
    DestinationDuplicatePreventionGuarantee,
    IntegrationIdentity,
    Operation,
    OperationEvidenceEvent,
)
from app.services import execution_receipt_service as receipt_svc
from app.services import execution_reconciliation_service as reconciliation_svc
from app.services import operation_identity_service

# Reconciliation outcome -> this module's own outcome_status vocabulary,
# BEFORE the evidence-acceptance gate in _finalize_observation_event is
# applied (see that function for why a RAW mapping to a terminal value
# here does not, by itself, mean outcome_status actually moves there).
_RECONCILIATION_OUTCOME_TO_OUTCOME_STATUS = {
    "MATCHED": "COMMITTED",
    "EXECUTION_FAILED": "TERMINALLY_NOT_COMMITTED",
    "MISMATCHED": "UNKNOWN",
    "PARTIAL": "UNKNOWN",
    "RECEIPT_MISSING": "UNKNOWN",
    "INDETERMINATE": "UNKNOWN",
}
# outcome_status values a later report never overwrites (a stray
# unresolved report after a real terminal conclusion does not erase the
# earlier, stronger evidence). Reconciliation's own fixed precedence
# rule (a later SUCCEEDED always wins over an earlier FAILED, regardless
# of order) still applies for terminal-vs-terminal updates.
_TERMINAL_OUTCOMES = frozenset({"COMMITTED", "TERMINALLY_NOT_COMMITTED"})
# execution_stage values from which an execution attempt has actually
# happened -- the only stages an observation about "what happened
# downstream" can ever meaningfully apply to. AUTHORIZED (no claim yet)
# is deliberately excluded: observation evidence about an action nobody
# has even attempted yet is not evidence about this operation.
_STAGES_ELIGIBLE_FOR_OBSERVATION = frozenset({"CLAIMED", "DISPATCHED"})

REPORTER_SIGNED_ADAPTER_IDENTITY = "SIGNED_ADAPTER_IDENTITY"
REPORTER_RBAC_HUMAN = "RBAC_HUMAN"
REPORTER_MANUAL_ADJUDICATION = "MANUAL_ADJUDICATION"


class OperationNotFoundError(Exception):
    pass


class OperationAlreadyExistsForDecisionError(Exception):
    def __init__(self, operation_id: uuid.UUID):
        self.operation_id = operation_id
        super().__init__(f"operation already exists for this decision: {operation_id}")


class OperationNotClaimedError(Exception):
    """Raised by record_dispatch_evidence and record_observation when the
    Operation hasn't reached a stage either of them can meaningfully
    apply to yet (see _STAGES_ELIGIBLE_FOR_OBSERVATION / the CLAIMED
    precondition below) -- e.g. an Operation still AUTHORIZED, whose
    Capability was never even consumed."""

    def __init__(self, operation_id: uuid.UUID, execution_stage: str):
        self.operation_id, self.execution_stage = operation_id, execution_stage
        super().__init__(f"operation {operation_id} execution_stage={execution_stage!r}, not eligible for this evidence")


class OperationRecordingFailedError(Exception):
    """Raised by capability_service.verify_and_consume_capability (via
    record_claim) when a lifecycle-covered operation's CLAIMED
    transition could not be durably recorded in the same transaction as
    the capability consume -- the whole transaction was rolled back, so
    the capability remains unconsumed; this is the caller-visible signal
    that reconciliation/retry is needed, not a claim that anything
    silently succeeded."""

    def __init__(self, operation_id: uuid.UUID, reason: str):
        self.operation_id, self.reason = operation_id, reason
        super().__init__(f"operation {operation_id}: {reason}")


class OperationSupersededError(Exception):
    """Closeout pass, section 1: raised at capability CONSUMPTION time
    when the operation being claimed is business-operation-identity-
    covered and is no longer its identity's current_operation_id -- a
    concurrent, later attempt became current between this operation's
    own issuance and this consumption attempt. Rolls back the whole
    consumption transaction (capability_service.verify_and_consume_
    capability), the same fail-closed shape as OperationRecordingFailedError,
    but distinct: this is not a durability failure, it is stale
    authority that must never be allowed to proceed."""

    def __init__(self, operation_id: uuid.UUID, current_operation_id: uuid.UUID | None):
        self.operation_id, self.current_operation_id = operation_id, current_operation_id
        super().__init__(
            f"operation {operation_id} has been superseded; current governing attempt is {current_operation_id}"
        )


class MaterialActionMismatchError(Exception):
    """The single check neither execution_receipt_service nor
    execution_reconciliation_service performs: an incoming observation's
    claimed material_action_digest (domain/order_action_contract.py, or
    whatever canonical-action-equivalent digest applies) does not match
    what this Operation was actually authorized against. Raised, never
    silently accepted -- an observation about a DIFFERENT material action
    is not evidence about this one."""

    def __init__(self, expected: str, received: str):
        self.expected, self.received = expected, received
        super().__init__(f"material_action_digest mismatch: expected={expected!r} received={received!r}")


class ReplacementNotSafeError(Exception):
    """Raised by capability_service.issue_capability_for_decision /
    issue_capability_for_reviewed_decision -- either via an explicit
    replaces_operation_id, or (closeout pass, section 1) automatically
    for a business-operation-identity-covered decision whose identity
    already has a governing prior attempt that is not SAFE_* to
    replace."""

    def __init__(self, operation_id: uuid.UUID, safety: str, reason: str):
        self.operation_id, self.safety, self.reason = operation_id, safety, reason
        super().__init__(f"replacement for operation {operation_id} not safe ({safety}): {reason}")


class InvalidManualAdjudicationError(Exception):
    """record_manual_adjudication's own validation failures: an empty
    rationale, a non-terminal requested outcome, or evidence_reference_ids
    naming rows that do not exist (or belong to a different Operation) --
    section 2's own "recorded rationale, evidence references" requirement
    is enforced here, not merely documented."""


class LifecycleRequirementNotSatisfiedError(Exception):
    """Contract-enforcement pass, section 1: the defense-in-depth
    recheck in capability_service._link_business_operation_attempt_if_
    covered -- reached only if some caller somehow constructed an Intent
    without going through integration_runtime_service.submit_attested_
    intent's own, earlier gate (which rejects this same condition before
    a Decision is ever made)."""

    def __init__(self, intent_id: uuid.UUID, contract_version_id: uuid.UUID):
        self.intent_id, self.contract_version_id = intent_id, contract_version_id
        super().__init__(
            f"intent {intent_id} is bound to LIFECYCLE_REQUIRED contract version {contract_version_id} "
            f"but is missing business_operation_id/intended_destination"
        )


class ReplacementSafetyWithdrawnError(Exception):
    """Contract-enforcement pass, section 1: raised at capability
    CONSUMPTION time (verify_still_current_attempt) when THIS operation
    itself is a replacement (previous_attempt_operation_id is set) and
    re-evaluating replacement safety against that prior attempt, right
    now, no longer returns a SAFE_* outcome -- the guarantee (or
    terminal-non-commit conclusion) that justified issuing THIS
    replacement over the prior attempt has since been withdrawn,
    expired, or overtaken by new evidence. Consumption must not proceed
    on a safety justification that no longer holds, even though this
    operation is still, correctly, its identity's current attempt."""

    def __init__(self, operation_id: uuid.UUID, previous_attempt_operation_id: uuid.UUID, safety: str, reason: str):
        self.operation_id = operation_id
        self.previous_attempt_operation_id = previous_attempt_operation_id
        self.safety, self.reason = safety, reason
        super().__init__(
            f"operation {operation_id}: the replacement-safety justification for superseding "
            f"{previous_attempt_operation_id} no longer holds ({safety}): {reason}"
        )


@dataclass(frozen=True)
class ReplacementSafety:
    # BLOCKED_ALREADY_COMMITTED | UNSAFE_UNRESOLVED |
    # SAFE_TERMINAL_NON_COMMIT_PROVEN | SAFE_DUPLICATE_PREVENTION_GUARANTEED
    safety: str
    reason: str
    requires_current_authorization: bool  # always True -- safety never substitutes for authority


def _get_operation_for_organization(db: Session, organization_id: uuid.UUID, operation_id: uuid.UUID) -> Operation:
    operation = db.get(Operation, operation_id)
    if operation is None or operation.organization_id != organization_id:
        raise OperationNotFoundError(str(operation_id))
    return operation


def _evidence_strength(reporter_kind: str, signature_verified: bool) -> str:
    """Mechanically derived, never a free string a caller can set --
    section 5's own "evidence strength" requirement, answerable by
    reading this table, not by trusting a claim. MANUAL_ADJUDICATION
    always carries signature_verified=False (it is a human decision, not
    a cryptographic proof) and gets its own, distinct label -- never
    conflated with an unsigned RBAC_HUMAN relay of an external claim."""
    if reporter_kind == REPORTER_SIGNED_ADAPTER_IDENTITY and signature_verified:
        return "SIGNED_ADAPTER_REPORT"
    if reporter_kind == REPORTER_RBAC_HUMAN and not signature_verified:
        return "UNSIGNED_HUMAN_RELAY"
    if reporter_kind == REPORTER_MANUAL_ADJUDICATION and not signature_verified:
        return "MANUAL_ADJUDICATION"
    # None of the three real combinations above -- a caller asserting
    # SIGNED_ADAPTER_IDENTITY without signature_verified=True (or the
    # reverse) is a caller lying about its own provenance, not a case
    # this function silently accepts a label for.
    raise ValueError(f"inconsistent reporter provenance: reporter_kind={reporter_kind!r} signature_verified={signature_verified!r}")


def create_operation_for_decision(
    db: Session, organization_id: uuid.UUID, decision_id: uuid.UUID, material_action_digest: str, *,
    business_operation_identity_id: uuid.UUID | None = None,
    integration_id: uuid.UUID | None = None,
    integration_contract_version_id: uuid.UUID | None = None,
    destination: str | None = None,
    previous_attempt_operation_id: uuid.UUID | None = None,
) -> Operation:
    """Called once, at Capability issuance time (services/
    capability_service.py's own _issue_and_persist / link_business_
    operation_attempt), never independently of a real, just-issued
    Capability. execution_stage AUTHORIZED, outcome_status UNKNOWN,
    evidence_assurance NONE: a Capability exists; nothing has been
    attempted or observed yet.

    The five identity-related keyword params are all optional and
    additive -- every caller that omits them (every non-identity-covered
    decision, exactly today's default) gets an Operation with no
    business-operation-identity coverage, unaffected by section 1's
    automatic resolution/enforcement; only the pre-existing, explicit
    replaces_operation_id mechanism remains available to it."""
    existing = db.scalar(select(Operation).where(Operation.decision_id == decision_id))
    if existing is not None:
        raise OperationAlreadyExistsForDecisionError(existing.id)
    operation = Operation(
        organization_id=organization_id, decision_id=decision_id,
        material_action_digest=material_action_digest,
        execution_stage="AUTHORIZED", outcome_status="UNKNOWN", evidence_assurance="NONE",
        business_operation_identity_id=business_operation_identity_id,
        integration_id=integration_id, integration_contract_version_id=integration_contract_version_id,
        destination=destination, previous_attempt_operation_id=previous_attempt_operation_id,
    )
    db.add(operation)
    # Consolidation review finding (medium-high): the read-then-insert
    # above is a fast path, not the guarantee -- two concurrent issuance
    # calls for the same Decision (e.g. a caller's own timeout-retry,
    # the exact scenario _link_business_operation_attempt_if_covered's
    # own comment anticipates) can both pass the pre-check above before
    # either commits. uq_operations_decision (migration a7c3e9f1b5d6) is
    # what actually makes this safe; catching the loser's IntegrityError
    # here and re-raising the SAME typed error the non-racing pre-check
    # above already raises matches the identical discipline this same
    # feature already applies in operation_identity_service.resolve_or_
    # create_business_operation_identity and capability_service._issue_
    # and_persist for their own analogous unique constraints -- without
    # this, the race escaped as an unhandled IntegrityError instead of
    # the typed, caller-classifiable error every other racing insert in
    # this feature already produces.
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raced = db.scalar(select(Operation).where(Operation.decision_id == decision_id))
        if raced is None:
            raise  # pragma: no cover -- a UNIQUE violation with no row to explain it is unexpected
        raise OperationAlreadyExistsForDecisionError(raced.id) from None
    db.refresh(operation)
    return operation


def link_business_operation_attempt(
    db: Session, organization_id: uuid.UUID, decision, intent, material_action_digest: str,
) -> Operation:
    """Closeout pass, section 1: the real, automatic enforcement path.
    Called from capability_service.issue_capability_for_decision /
    issue_capability_for_reviewed_decision whenever intent.
    business_operation_id is set -- i.e. for every "supported
    integration" submission, with NO dependence on the caller separately
    declaring replaces_operation_id. Resolves (or creates) the
    BusinessOperationIdentity for (organization, intent.integration_id,
    intent.intended_destination, intent.business_operation_id), reads
    its current governing attempt, and:

      - if none exists yet, this is a genuine first attempt: creates the
        Operation and races (via operation_identity_service.
        advance_current_attempt's atomic conditional UPDATE) to become
        the identity's current_operation_id. A concurrent FIRST attempt
        at the same identity cannot both win -- the loser re-resolves
        against whatever actually won and is safety-checked against it,
        exactly like any other repeat (this is the "handle concurrent
        creation ... using database constraints and transactions"
        requirement, not a documentation-only claim).
      - if a prior attempt exists, evaluate_replacement_safety is run
        against it BEFORE this attempt's own Operation is even created
        (ReplacementNotSafeError blocks issuance outright if unsafe --
        "block another effect if the original committed," "block an
        unsafe attempt while the original outcome is unknown," both
        enforced here, unconditionally, never opt-in).
      - either way, `requires_current_authorization` is always True on
        the safety result -- a fresh Intent still had to independently
        evaluate to ALLOW for this function to even be reached; safety
        never substitutes for that.

    The original operation, and every superseded attempt, is preserved
    untouched (previous_attempt_operation_id chains them) -- "record
    subsequent attempts separately" is not merely a phrase here, it is
    the actual row structure."""
    identity = operation_identity_service.resolve_or_create_business_operation_identity(
        db, organization_id, intent.integration_id, intent.action,
        intent.intended_destination, intent.business_operation_id,
    )
    db.commit()
    db.refresh(identity)

    prior_operation_id = identity.current_operation_id
    if prior_operation_id is not None:
        safety = evaluate_replacement_safety(
            db, organization_id, prior_operation_id,
            attempting_integration_identity_id=intent.integration_identity_id,
            attempting_enforcement_binding_id=intent.enforcement_binding_id,
        )
        if not safety.safety.startswith("SAFE_"):
            raise ReplacementNotSafeError(prior_operation_id, safety.safety, safety.reason)

    operation = create_operation_for_decision(
        db, organization_id, decision.id, material_action_digest,
        business_operation_identity_id=identity.id, integration_id=intent.integration_id,
        integration_contract_version_id=intent.integration_contract_version_id,
        destination=intent.intended_destination, previous_attempt_operation_id=prior_operation_id,
    )

    for _ in range(operation_identity_service.MAX_CONCURRENT_ATTEMPT_RETRIES):
        won = operation_identity_service.advance_current_attempt(
            db, identity, expected_current_operation_id=prior_operation_id, new_operation_id=operation.id,
        )
        db.commit()
        if won:
            return operation

        # Lost the race: a concurrent attempt became current between our
        # read and our update. Never force our own value in on top of a
        # winner we have not evaluated -- re-resolve and re-check safety
        # against whatever actually won, then retry.
        db.refresh(identity)
        new_prior_id = identity.current_operation_id
        if new_prior_id == operation.id:
            return operation  # a previous pass of this same loop already won
        safety = evaluate_replacement_safety(
            db, organization_id, new_prior_id,
            attempting_integration_identity_id=intent.integration_identity_id,
            attempting_enforcement_binding_id=intent.enforcement_binding_id,
        )
        if not safety.safety.startswith("SAFE_"):
            raise ReplacementNotSafeError(new_prior_id, safety.safety, safety.reason)
        operation.previous_attempt_operation_id = new_prior_id
        db.commit()
        prior_operation_id = new_prior_id

    raise operation_identity_service.ConcurrentBusinessOperationAttemptError(identity.id)


def verify_still_current_attempt(db: Session, organization_id: uuid.UUID, operation: Operation) -> None:
    """Contract-enforcement pass, section 1: the CONSUMPTION-time half of
    "enforce this at issuance and consumption, including when safety
    facts change between them." Called from record_claim, inside
    capability_service.verify_and_consume_capability's own transaction
    -- a no-op for a non-identity-covered operation (business_operation_
    identity_id is None). Two independent, both real, checks for an
    identity-covered one:

      1. Still current -- re-confirms this operation is STILL its
         identity's current_operation_id; if a later attempt has since
         become current (issued after this one, in between this
         operation's own issuance and this consumption attempt), raises
         OperationSupersededError.
      2. Replacement safety not withdrawn -- if THIS operation is
         itself a replacement (previous_attempt_operation_id is set),
         re-runs evaluate_replacement_safety against the prior attempt
         it replaced, using the SAME attempting identity/binding used
         at issuance (resolved from this Operation's own Decision/
         Intent, never re-derived from anything the consuming caller
         supplies). The guarantee or terminal-non-commit conclusion
         that justified issuing this replacement can itself be
         withdrawn, corrected, or superseded between issuance and
         consumption -- "recheck mutable safety facts at consumption,
         not just whether an attempt is still current" is this check,
         not merely check 1 above.

    Either failure rolls back the whole consumption -- stale authority,
    or authority whose safety justification has since evaporated, is
    never allowed to proceed merely because it was valid when issued."""
    if operation.business_operation_identity_id is None:
        return
    identity = db.get(BusinessOperationIdentity, operation.business_operation_identity_id)
    if identity is None or identity.current_operation_id != operation.id:
        raise OperationSupersededError(operation.id, identity.current_operation_id if identity else None)

    if operation.previous_attempt_operation_id is not None:
        from app.db.models import Decision, Intent

        decision = db.get(Decision, operation.decision_id)
        intent = db.get(Intent, decision.intent_id)
        safety = evaluate_replacement_safety(
            db, organization_id, operation.previous_attempt_operation_id,
            attempting_integration_identity_id=intent.integration_identity_id,
            attempting_enforcement_binding_id=intent.enforcement_binding_id,
        )
        if not safety.safety.startswith("SAFE_"):
            raise ReplacementSafetyWithdrawnError(operation.id, operation.previous_attempt_operation_id, safety.safety, safety.reason)


def record_claim(db: Session, organization_id: uuid.UUID, operation: Operation, capability_id: uuid.UUID) -> None:
    """Deliberately does NOT call db.commit() -- this function
    participates in capability_service.verify_and_consume_capability's
    OWN transaction, by design (see that function's docstring for the
    atomicity this buys). Every other function in this module commits
    its own work; this one is the disclosed exception.

    AUTHORIZED -> CLAIMED only: the Capability was atomically consumed,
    so an execution attempt was authorized to proceed. This does NOT
    establish that the executor ever actually called the destination --
    see record_dispatch_evidence for that separate, later fact.

    Re-checks verify_still_current_attempt FIRST -- a superseded
    business-operation-identity attempt must never be allowed to claim,
    even though its Capability itself was validly issued at the time."""
    if operation.organization_id != organization_id:
        raise OperationNotFoundError(str(operation.id))
    verify_still_current_attempt(db, organization_id, operation)
    operation.capability_id = capability_id
    operation.execution_stage = "CLAIMED"
    operation.attempt_count += 1
    operation.updated_at = datetime.now(timezone.utc)


def record_dispatch_evidence(
    db: Session, organization_id: uuid.UUID, operation_id: uuid.UUID, *,
    reporter_kind: str, signature_verified: bool, reported_by: str,
    integration_identity_id: uuid.UUID | None = None,
    destination: str | None = None, destination_operation_id: str | None = None,
) -> Operation:
    """The executor's own, EXPLICIT report that it sent the destination
    request -- a distinct evidence event from claiming the Capability
    (which only proves the attempt was authorized) and from an
    observation (which reports what the destination said back, if
    anything). CLAIMED -> DISPATCHED only; never inferred from CLAIMED
    alone, and never itself touches outcome_status -- only
    _finalize_observation_event, under the evidence-acceptance rules
    below, does that."""
    operation = _get_operation_for_organization(db, organization_id, operation_id)
    if operation.execution_stage != "CLAIMED":
        raise OperationNotClaimedError(operation.id, operation.execution_stage)

    strength = _evidence_strength(reporter_kind, signature_verified)
    if destination is not None:
        operation.destination = operation.destination or destination
    if destination_operation_id is not None:
        operation.destination_operation_id = operation.destination_operation_id or destination_operation_id

    event = OperationEvidenceEvent(
        organization_id=organization_id, operation_id=operation.id, event_type="DISPATCH_REPORTED",
        reporter_kind=reporter_kind, integration_identity_id=integration_identity_id, reported_by=reported_by,
        signature_verified=signature_verified, destination=destination, destination_operation_id=destination_operation_id,
        claimed_status="SENT", evidence_strength=strength, execution_stage_at_event=operation.execution_stage,
    )
    db.add(event)
    operation.execution_stage = "DISPATCHED"
    operation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(operation)
    return operation


def record_observation(
    db: Session,
    organization_id: uuid.UUID,
    operation_id: uuid.UUID,
    identity: IntegrationIdentity,
    *,
    reporter_kind: str,
    signature_verified: bool,
    reported_by: str,
    enforcement_binding_id: uuid.UUID,
    material_action_digest: str,
    canonical_action_digest: str,
    destination: str,
    status: str,
    capability_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
    detail: str | None = None,
):
    """The narrowly scoped observation path. Structurally, not merely by
    convention, this function CANNOT issue a Capability, submit a new
    Intent, or change a material action: it calls exactly two other
    functions, execution_receipt_service.submit_execution_receipt
    (append evidence for an operation that already has a Decision) and
    execution_reconciliation_service.reconcile_decision (read-only
    computation over already-persisted records) -- neither of which is
    capable of any of those things either.

    Requires `reporter_kind`/`signature_verified`/`reported_by`
    explicitly, with no defaults -- every caller must be honest about
    what it actually is. The real, signature-authenticated Adapter path
    (routers/execution_receipts.py) passes SIGNED_ADAPTER_IDENTITY /
    True; the RBAC recovery path (routers/operations.py) passes
    RBAC_HUMAN / False. Neither is inferred. See _finalize_observation_
    event for what each is actually ALLOWED to conclude (section 2:
    acceptance rules, not just provenance labels).

    Precondition: the Operation must already be CLAIMED or DISPATCHED --
    observation evidence about an operation whose Capability was never
    even consumed is not evidence about this operation at all
    (OperationNotClaimedError). Once CLAIMED, though, evidence is
    accepted regardless of whether DISPATCHED was ever explicitly
    reported: a crash after claim with no dispatch evidence must still
    be handled conservatively -- absence of dispatch evidence does not
    establish absence of an external effect.

    A CONTRADICTORY report (execution_receipt_service's own conflict
    detection) is retained, not silently discarded -- see the
    OBSERVATION_CONFLICT_REJECTED event written below -- and never
    overwrites whatever outcome_status/evidence_assurance already stood
    before the conflicting attempt."""
    operation = _get_operation_for_organization(db, organization_id, operation_id)
    if operation.execution_stage not in _STAGES_ELIGIBLE_FOR_OBSERVATION:
        raise OperationNotClaimedError(operation.id, operation.execution_stage)

    if material_action_digest != operation.material_action_digest:
        raise MaterialActionMismatchError(operation.material_action_digest, material_action_digest)

    try:
        receipt = receipt_svc.submit_execution_receipt(
            db, identity, enforcement_binding_id=enforcement_binding_id, decision_id=operation.decision_id,
            canonical_action_digest=canonical_action_digest,
            external_operation_id=operation.destination_operation_id or _resolve_external_operation_id(db, operation),
            destination=destination, status=status, capability_id=capability_id,
            occurred_at=occurred_at, detail=detail,
        )
    except receipt_svc.ExecutionReceiptConflictError:
        # Section 2: "retain contradictory reports and prevent them from
        # silently overwriting a terminal conclusion." The conflicting
        # claim itself is preserved (a real, auditable attempt was
        # made), but nothing about the Operation's own state changes --
        # the caller still sees the conflict raised, unmodified.
        conflict_event = OperationEvidenceEvent(
            organization_id=organization_id, operation_id=operation.id, event_type="OBSERVATION_CONFLICT_REJECTED",
            reporter_kind=reporter_kind, integration_identity_id=identity.id, reported_by=reported_by,
            signature_verified=signature_verified, destination=destination, claimed_status=status,
            evidence_strength=_evidence_strength(reporter_kind, signature_verified),
            execution_stage_at_event=operation.execution_stage,
        )
        db.add(conflict_event)
        db.commit()
        raise

    return _finalize_observation_event(
        db, organization_id, operation, receipt, identity_id=identity.id,
        reporter_kind=reporter_kind, signature_verified=signature_verified, reported_by=reported_by,
        destination=destination, status=status,
    )


def record_observation_for_existing_receipt(
    db: Session, organization_id: uuid.UUID, receipt, *, reporter_kind: str, signature_verified: bool, reported_by: str,
):
    """Companion to record_observation, for the REAL signed-Adapter path
    (routers/execution_receipts.py's POST /v1/execution-receipts) --
    that endpoint's own request shape has no material_action_digest
    concept (it predates this milestone and validates linkage a
    different, already-real way: submit_execution_receipt's own
    canonical_action_digest/identity/binding checks), so this does NOT
    re-run that step. It exists so a genuine, signature-verified Adapter
    report ALSO advances a lifecycle-covered Operation's state -- and,
    per section 2, this is the ONLY ordinary observation path that can
    actually move outcome_status into a terminal value.

    Silent no-op (returns None) when no Operation is linked to this
    receipt's decision_id -- the same "legacy caller, not lifecycle-
    covered" distinction capability_service.verify_and_consume_
    capability already makes, applied here too."""
    operation = db.scalar(select(Operation).where(Operation.decision_id == receipt.decision_id, Operation.organization_id == organization_id))
    if operation is None:
        return None
    if operation.execution_stage not in _STAGES_ELIGIBLE_FOR_OBSERVATION:
        # A receipt referencing a Capability that was never actually
        # claimed is exactly the "decision_not_found"-adjacent anomaly
        # submit_execution_receipt's own linkage checks are meant to
        # catch upstream; if one somehow reaches here, fail closed
        # rather than silently forcing a state transition.
        raise OperationNotClaimedError(operation.id, operation.execution_stage)
    return _finalize_observation_event(
        db, organization_id, operation, receipt, identity_id=receipt.integration_identity_id,
        reporter_kind=reporter_kind, signature_verified=signature_verified, reported_by=reported_by,
        destination=receipt.destination, status=receipt.status,
    )


def _finalize_observation_event(
    db: Session, organization_id: uuid.UUID, operation: Operation, receipt, *, identity_id: uuid.UUID,
    reporter_kind: str, signature_verified: bool, reported_by: str, destination: str, status: str,
):
    """Section 2's own evidence-acceptance gate. Reconciliation is
    ALWAYS computed and ALWAYS preserved on the event
    (reconciliation_outcome) -- "reconciliation MATCHED establishes
    consistency with the authorized action; it does not independently
    prove destination commitment" -- but only a signature-verified
    Adapter report is allowed to actually move outcome_status into a
    terminal value. An unsigned RBAC_HUMAN relay's own reconciliation
    result, even a raw MATCHED/EXECUTION_FAILED, is capped at UNKNOWN
    here: it is evidence that SOMETHING was claimed, never proof that it
    happened, and must not "automatically become verified destination
    truth." """
    strength = _evidence_strength(reporter_kind, signature_verified)

    if operation.destination is None:
        operation.destination = destination
    if operation.destination_operation_id is None:
        operation.destination_operation_id = receipt.external_operation_id

    result = reconciliation_svc.reconcile_decision(db, organization_id, operation.decision_id)
    raw_new_outcome = _RECONCILIATION_OUTCOME_TO_OUTCOME_STATUS[result.outcome]
    is_adapter_verified = reporter_kind == REPORTER_SIGNED_ADAPTER_IDENTITY and signature_verified
    effective_new_outcome = raw_new_outcome if (is_adapter_verified or raw_new_outcome == "UNKNOWN") else "UNKNOWN"

    event = OperationEvidenceEvent(
        organization_id=organization_id, operation_id=operation.id, event_type="OBSERVATION",
        reporter_kind=reporter_kind, integration_identity_id=identity_id, reported_by=reported_by,
        signature_verified=signature_verified, destination=destination,
        destination_operation_id=operation.destination_operation_id, claimed_status=status,
        reconciliation_outcome=result.outcome, evidence_strength=strength, receipt_id=receipt.id,
        # Section 2: a permanent snapshot of what execution_stage WAS
        # at the moment this observation arrived -- if this is still
        # CLAIMED (no DISPATCH_REPORTED event ever happened for this
        # operation), that gap is recorded here explicitly, not
        # papered over by this observation itself ever touching
        # execution_stage (it never does, see below).
        execution_stage_at_event=operation.execution_stage,
    )
    db.add(event)

    if operation.outcome_status not in _TERMINAL_OUTCOMES or effective_new_outcome in _TERMINAL_OUTCOMES:
        operation.outcome_status = effective_new_outcome
        if effective_new_outcome in _TERMINAL_OUTCOMES:
            operation.evidence_assurance = "ADAPTER_REPORTED"
        elif operation.evidence_assurance == "NONE" and reporter_kind == REPORTER_RBAC_HUMAN:
            operation.evidence_assurance = "REPORTED_UNVERIFIED"
    operation.updated_at = datetime.now(timezone.utc)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        # The receipt itself was already durably committed by
        # submit_execution_receipt's own internal commit before this
        # function was ever called -- real evidence is not lost -- but
        # this operation's own lifecycle bookkeeping (the evidence event
        # + state transition) could not be. Surfaced distinctly so a
        # caller/operator knows reconciliation is required, rather than
        # assuming success.
        raise OperationRecordingFailedError(
            operation.id, f"receipt {receipt.id} was recorded, but Operation lifecycle state could not be updated ({e})",
        ) from e

    db.refresh(operation)
    return operation, receipt, result


def record_manual_adjudication(
    db: Session, organization_id: uuid.UUID, operation_id: uuid.UUID, *,
    adjudicated_by: str, outcome_status: str, rationale: str, evidence_reference_ids: list[uuid.UUID],
) -> Operation:
    """Section 2: the ONLY other way (besides a signature-verified
    Adapter report) outcome_status can reach a terminal value. A
    governance decision, not a report of an external fact -- gated by
    Permission.OPERATION_MANUAL_ADJUDICATE at the router layer
    (Governance Administrator only, deliberately NOT reachable by an
    OPERATION_OBSERVE-only credential), and always requires a non-empty
    rationale plus at least one real, existing evidence_reference_id
    from THIS operation's own event log -- an adjudication with nothing
    to point at is not representable here, by construction. Written as
    its own OperationEvidenceEvent (reporter_kind=MANUAL_ADJUDICATION,
    signature_verified=False -- a human decision, never a cryptographic
    proof) so the full record -- who, why, based on what -- is
    permanently distinguishable from an ordinary observation."""
    operation = _get_operation_for_organization(db, organization_id, operation_id)
    if outcome_status not in _TERMINAL_OUTCOMES:
        raise InvalidManualAdjudicationError(f"outcome_status must be one of {sorted(_TERMINAL_OUTCOMES)}, got {outcome_status!r}")
    if not rationale or not rationale.strip():
        raise InvalidManualAdjudicationError("rationale is required")
    if not evidence_reference_ids:
        raise InvalidManualAdjudicationError("at least one evidence_reference_id is required")

    referenced = db.scalars(
        select(OperationEvidenceEvent).where(
            OperationEvidenceEvent.id.in_(evidence_reference_ids),
            OperationEvidenceEvent.operation_id == operation.id,
        )
    ).all()
    if len(referenced) != len(set(evidence_reference_ids)):
        found = {row.id for row in referenced}
        missing = set(evidence_reference_ids) - found
        raise InvalidManualAdjudicationError(f"evidence_reference_ids not found on this operation: {sorted(str(i) for i in missing)}")

    strength = _evidence_strength(REPORTER_MANUAL_ADJUDICATION, False)
    event = OperationEvidenceEvent(
        organization_id=organization_id, operation_id=operation.id, event_type="MANUAL_ADJUDICATION",
        reporter_kind=REPORTER_MANUAL_ADJUDICATION, reported_by=adjudicated_by, signature_verified=False,
        claimed_status=outcome_status, evidence_strength=strength, rationale=rationale,
        evidence_reference_ids=[str(i) for i in evidence_reference_ids],
        execution_stage_at_event=operation.execution_stage,
    )
    db.add(event)

    if operation.outcome_status not in _TERMINAL_OUTCOMES or outcome_status in _TERMINAL_OUTCOMES:
        operation.outcome_status = outcome_status
        operation.evidence_assurance = "MANUAL_ADJUDICATED"
    operation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(operation)
    return operation


def _resolve_external_operation_id(db: Session, operation: Operation) -> str:
    """Only reached when an Operation has never recorded a destination_
    operation_id at all (its very first observation) -- resolves the
    real external_operation_id from the Operation's own Decision/Intent,
    never invents one."""
    from app.db.models import Decision, Intent

    decision = db.get(Decision, operation.decision_id)
    intent = db.get(Intent, decision.intent_id)
    return intent.external_operation_id


def evaluate_replacement_safety(
    db: Session, organization_id: uuid.UUID, operation_id: uuid.UUID, *,
    attempting_integration_identity_id: uuid.UUID | None = None,
    attempting_enforcement_binding_id: uuid.UUID | None = None,
) -> ReplacementSafety:
    """Answers SAFETY only -- never AUTHORITY (see this module's own
    top-of-file docstring). Reads outcome_status (closeout pass, section
    3), never the old collapsed `state` -- execution_stage is
    irrelevant to this question by construction: an operation stuck at
    execution_stage=CLAIMED forever with outcome_status=UNKNOWN is just
    as UNSAFE_UNRESOLVED as one stuck at DISPATCHED with the same
    outcome_status; which stage it reached tells you nothing about
    whether a duplicate effect is still possible.

    Four distinct outcomes, not three:

      BLOCKED_ALREADY_COMMITTED       -- the original operation already
        succeeded. A "replacement" here is not a recovery action, it is
        a duplicate-effect risk in its own right; blocked, not offered
        as safe.
      UNSAFE_UNRESOLVED               -- outcome_status is not yet
        COMMITTED or TERMINALLY_NOT_COMMITTED, and no valid, currently-
        covering guarantee exists. The fail-closed default -- reached
        both for an ordinary unresolved operation AND (section 2) for
        one whose only "terminal-looking" evidence came from an
        unsigned relay and was therefore capped at UNKNOWN.
      SAFE_TERMINAL_NON_COMMIT_PROVEN -- sufficient evidence establishes
        the original did not, and will not, commit. Safe to attempt a
        replacement, but `requires_current_authorization` is always
        True: safety here never substitutes for a fresh Intent actually
        evaluating to ALLOW.
      SAFE_DUPLICATE_PREVENTION_GUARANTEED -- a live, human-documented
        guarantee covers this exact operation. If it is scoped to a
        specific identity/binding (restricted_to_integration_identity_id
        / restricted_to_enforcement_binding_id), the caller's own
        `attempting_*` identity must match EXACTLY, or this degrades to
        UNSAFE_UNRESOLVED -- "any permitted attempt must use the
        identity and conditions that guarantee actually protects," not
        any identity at all."""
    operation = _get_operation_for_organization(db, organization_id, operation_id)

    if operation.outcome_status == "COMMITTED":
        return ReplacementSafety(
            safety="BLOCKED_ALREADY_COMMITTED",
            reason="the original operation already committed; a further effect would itself be a duplicate, not a recovery",
            requires_current_authorization=True,
        )

    if operation.outcome_status == "TERMINALLY_NOT_COMMITTED":
        return ReplacementSafety(
            safety="SAFE_TERMINAL_NON_COMMIT_PROVEN",
            reason="sufficient evidence establishes the original operation did not, and will not, commit",
            requires_current_authorization=True,
        )

    guarantee = db.scalar(
        select(DestinationDuplicatePreventionGuarantee).where(
            DestinationDuplicatePreventionGuarantee.operation_id == operation_id,
        )
    )
    if guarantee is not None:
        retention_until = guarantee.retention_until
        if retention_until.tzinfo is None:
            # SQLite (this test suite's own backing store) does not
            # round-trip timezone-aware DateTime values -- a value
            # stored tz-aware comes back naive. Postgres's DateTime
            # (timezone=True) does not have this gap; normalizing
            # defensively here is correct either way.
            retention_until = retention_until.replace(tzinfo=timezone.utc)
        if retention_until > datetime.now(timezone.utc):
            if guarantee.restricted_to_integration_identity_id is not None and guarantee.restricted_to_integration_identity_id != attempting_integration_identity_id:
                return ReplacementSafety(
                    safety="UNSAFE_UNRESOLVED",
                    reason=f"a guarantee exists but is restricted to integration_identity_id={guarantee.restricted_to_integration_identity_id}; the attempting identity does not match",
                    requires_current_authorization=True,
                )
            if guarantee.restricted_to_enforcement_binding_id is not None and guarantee.restricted_to_enforcement_binding_id != attempting_enforcement_binding_id:
                return ReplacementSafety(
                    safety="UNSAFE_UNRESOLVED",
                    reason=f"a guarantee exists but is restricted to enforcement_binding_id={guarantee.restricted_to_enforcement_binding_id}; the attempting binding does not match",
                    requires_current_authorization=True,
                )
            return ReplacementSafety(
                safety="SAFE_DUPLICATE_PREVENTION_GUARANTEED",
                reason=f"documented guarantee (scope: {guarantee.scope_description!r}, by {guarantee.documented_by!r}, valid until {retention_until.isoformat()})",
                requires_current_authorization=True,
            )

    return ReplacementSafety(
        safety="UNSAFE_UNRESOLVED",
        reason=f"outcome_status is {operation.outcome_status!r} (evidence_assurance={operation.evidence_assurance!r}): neither terminal non-commit proof nor a live, scoped duplicate-prevention guarantee exists for this exact operation",
        requires_current_authorization=True,
    )


def record_destination_duplicate_prevention_guarantee(
    db: Session, organization_id: uuid.UUID, operation_id: uuid.UUID, *,
    destination: str, scope_description: str, retention_until: datetime, documented_by: str,
    restricted_to_integration_identity_id: uuid.UUID | None = None,
    restricted_to_enforcement_binding_id: uuid.UUID | None = None,
) -> DestinationDuplicatePreventionGuarantee:
    """A human-documented fact, never auto-inferred. Gated by
    Permission.OPERATION_SAFETY_APPROVE at the router layer (Governance
    Administrator only) -- deliberately NOT reachable by an Operation-
    OBSERVE-only credential (section 4: "an observer cannot grant
    themselves replacement safety"). Fails closed on an empty
    scope_description or a retention_until that has already passed."""
    operation = _get_operation_for_organization(db, organization_id, operation_id)
    if not scope_description or not scope_description.strip():
        raise ValueError("scope_description is required")
    if retention_until.tzinfo is None:
        retention_until = retention_until.replace(tzinfo=timezone.utc)
    if retention_until <= datetime.now(timezone.utc):
        raise ValueError("retention_until must be in the future")

    existing = db.scalar(
        select(DestinationDuplicatePreventionGuarantee).where(
            DestinationDuplicatePreventionGuarantee.operation_id == operation_id,
        )
    )
    if existing is not None:
        existing.destination = destination
        existing.scope_description = scope_description
        existing.retention_until = retention_until
        existing.documented_by = documented_by
        existing.restricted_to_integration_identity_id = restricted_to_integration_identity_id
        existing.restricted_to_enforcement_binding_id = restricted_to_enforcement_binding_id
        db.commit()
        db.refresh(existing)
        return existing

    guarantee = DestinationDuplicatePreventionGuarantee(
        organization_id=organization_id, operation_id=operation_id, destination=destination,
        scope_description=scope_description, retention_until=retention_until, documented_by=documented_by,
        restricted_to_integration_identity_id=restricted_to_integration_identity_id,
        restricted_to_enforcement_binding_id=restricted_to_enforcement_binding_id,
    )
    db.add(guarantee)
    db.commit()
    db.refresh(guarantee)
    return guarantee
