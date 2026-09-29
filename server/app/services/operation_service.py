"""Product lifecycle vertical slice (EVIDENCEBOUND-PAYREALITY-RECOVERY-V01
follow-up), hardening pass included.

Deliberately a thin orchestration layer, not a parallel implementation:
every trust decision this module makes (is this identity/organization
still active, does this receipt's linkage match its decision, is this a
duplicate/conflicting/contradictory report) is delegated to the real,
already-tested execution_receipt_service and execution_reconciliation_
service unchanged -- this module adds exactly what those two don't
already do: an Operation existing at all (separately from a Capability's
own single-use lifetime), an append-only evidence-provenance log
distinguishing a signed Adapter report from an unsigned human relay,
validating an incoming observation's claimed material_action_digest
against the Operation's own recorded one, and mapping a reconciliation
outcome onto this module's own coarser Operation.state vocabulary.

Authority vs. safety, kept genuinely separate: AUTHORITY to attempt a
replacement is answered exactly as it always has been -- by submitting a
new Intent through decision/engine.py and seeing whether it evaluates to
ALLOW (or an approved HUMAN_REVIEW). This module never touches that
decision. SAFETY is what evaluate_replacement_safety answers, a
different question entirely: even given fresh authority, would
attempting it risk a duplicate real-world effect against an operation
whose outcome is still open, already committed, or conclusively closed.

Hardening pass, three real fixes over the first version:
  1. record_claim (was record_dispatch): capability CONSUMPTION is not
     dispatch. Claiming a Capability only proves an execution attempt
     was AUTHORIZED to proceed; it does not prove the executor ever
     called the destination. A new, distinct DISPATCHED state, reached
     only via record_dispatch_evidence's own explicit evidence event,
     closes that gap.
  2. record_claim no longer commits itself -- capability_service.
     verify_and_consume_capability now calls it inside the SAME
     transaction as the atomic capability-consume UPDATE, so a
     lifecycle-covered operation's CLAIMED transition cannot be silently
     lost if it fails: the whole transaction rolls back, and the caller
     gets a typed OperationRecordingFailedError, not a stale capability
     with no matching Operation state.
  3. evaluate_replacement_safety now has four distinct outcomes instead
     of three, an actual ENFORCEMENT hook (capability_service.
     issue_capability_for_decision's optional replaces_operation_id
     parameter), and a documented guarantee can be scoped to a specific
     identity/binding, checked at enforcement time, not merely at
     read time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DestinationDuplicatePreventionGuarantee,
    IntegrationIdentity,
    Operation,
    OperationEvidenceEvent,
)
from app.services import execution_receipt_service as receipt_svc
from app.services import execution_reconciliation_service as reconciliation_svc

# Reconciliation outcome -> this module's own, coarser Operation.state.
# See Operation's own docstring (app/db/models.py) for why this mapping
# exists and why it is a mapping onto reconciliation's real outcomes,
# never a second, independently-derived state-transition rule.
_OUTCOME_TO_STATE = {
    "MATCHED": "COMMITTED",
    "EXECUTION_FAILED": "TERMINALLY_NOT_COMMITTED",
    "MISMATCHED": "OUTCOME_UNKNOWN",
    "PARTIAL": "OUTCOME_UNKNOWN",
    "RECEIPT_MISSING": "OUTCOME_UNKNOWN",
    "INDETERMINATE": "OUTCOME_UNKNOWN",
}
# States a later OUTCOME_UNKNOWN-mapping report never overwrites (a
# stray INDETERMINATE/MISMATCHED after a real MATCHED does not erase the
# earlier, stronger evidence). Reconciliation's own fixed precedence
# rule (a later SUCCEEDED always wins over an earlier FAILED, regardless
# of order) still applies for terminal-vs-terminal updates.
_TERMINAL_STATES = frozenset({"COMMITTED", "TERMINALLY_NOT_COMMITTED"})
# States from which an execution attempt (claim) has actually happened --
# the only states an observation about "what happened downstream" can
# ever meaningfully apply to. AUTHORIZED (no claim yet) is deliberately
# excluded: observation evidence about an action nobody has even
# attempted yet is not evidence about this operation.
_STATES_ELIGIBLE_FOR_OBSERVATION = frozenset(
    {"CLAIMED", "DISPATCHED", "COMMITTED", "TERMINALLY_NOT_COMMITTED", "OUTCOME_UNKNOWN"}
)

REPORTER_SIGNED_ADAPTER_IDENTITY = "SIGNED_ADAPTER_IDENTITY"
REPORTER_RBAC_HUMAN = "RBAC_HUMAN"


class OperationNotFoundError(Exception):
    pass


class OperationAlreadyExistsForDecisionError(Exception):
    def __init__(self, operation_id: uuid.UUID):
        self.operation_id = operation_id
        super().__init__(f"operation already exists for this decision: {operation_id}")


class OperationNotClaimedError(Exception):
    """Raised by record_dispatch_evidence and record_observation when the
    Operation hasn't reached a state either of them can meaningfully
    apply to yet (see _STATES_ELIGIBLE_FOR_OBSERVATION / the CLAIMED
    precondition below) -- e.g. an Operation still AUTHORIZED, whose
    Capability was never even consumed."""

    def __init__(self, operation_id: uuid.UUID, state: str):
        self.operation_id, self.state = operation_id, state
        super().__init__(f"operation {operation_id} is {state!r}, not eligible for this evidence")


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
    issue_capability_for_reviewed_decision when called with a
    replaces_operation_id whose evaluate_replacement_safety result is
    not one of the SAFE_* categories -- the real enforcement hook, not
    merely an advisory endpoint a caller could choose to ignore."""

    def __init__(self, operation_id: uuid.UUID, safety: str, reason: str):
        self.operation_id, self.safety, self.reason = operation_id, safety, reason
        super().__init__(f"replacement for operation {operation_id} not safe ({safety}): {reason}")


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
    reading this table, not by trusting a claim."""
    if reporter_kind == REPORTER_SIGNED_ADAPTER_IDENTITY and signature_verified:
        return "SIGNED_ADAPTER_REPORT"
    if reporter_kind == REPORTER_RBAC_HUMAN and not signature_verified:
        return "UNSIGNED_HUMAN_RELAY"
    # Neither of the two real combinations above -- a caller asserting
    # SIGNED_ADAPTER_IDENTITY without signature_verified=True (or the
    # reverse) is a caller lying about its own provenance, not a case
    # this function silently accepts a label for.
    raise ValueError(f"inconsistent reporter provenance: reporter_kind={reporter_kind!r} signature_verified={signature_verified!r}")


def create_operation_for_decision(
    db: Session, organization_id: uuid.UUID, decision_id: uuid.UUID, material_action_digest: str,
) -> Operation:
    """Called once, at Capability issuance time (services/
    capability_service.py's own _issue_and_persist), never independently
    of a real, just-issued Capability. State AUTHORIZED: a Capability
    exists; nothing has been claimed yet."""
    existing = db.scalar(select(Operation).where(Operation.decision_id == decision_id))
    if existing is not None:
        raise OperationAlreadyExistsForDecisionError(existing.id)
    operation = Operation(
        organization_id=organization_id, decision_id=decision_id,
        material_action_digest=material_action_digest, state="AUTHORIZED",
    )
    db.add(operation)
    db.commit()
    db.refresh(operation)
    return operation


def record_claim(db: Session, organization_id: uuid.UUID, operation: Operation, capability_id: uuid.UUID) -> None:
    """Deliberately does NOT call db.commit() -- this function
    participates in capability_service.verify_and_consume_capability's
    OWN transaction, by design (see that function's docstring for the
    atomicity this buys). Every other function in this module commits
    its own work; this one is the disclosed exception.

    AUTHORIZED -> CLAIMED only: the Capability was atomically consumed,
    so an execution attempt was authorized to proceed. This does NOT
    establish that the executor ever actually called the destination --
    see record_dispatch_evidence for that separate, later fact."""
    if operation.organization_id != organization_id:
        raise OperationNotFoundError(str(operation.id))
    operation.capability_id = capability_id
    operation.state = "CLAIMED"
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
    alone, and never itself produces COMMITTED/TERMINALLY_NOT_COMMITTED
    -- only record_observation, backed by real reconciliation, does
    that."""
    operation = _get_operation_for_organization(db, organization_id, operation_id)
    if operation.state != "CLAIMED":
        raise OperationNotClaimedError(operation.id, operation.state)

    strength = _evidence_strength(reporter_kind, signature_verified)
    if destination is not None:
        operation.destination = operation.destination or destination
    if destination_operation_id is not None:
        operation.destination_operation_id = operation.destination_operation_id or destination_operation_id

    event = OperationEvidenceEvent(
        organization_id=organization_id, operation_id=operation.id, event_type="DISPATCH_REPORTED",
        reporter_kind=reporter_kind, integration_identity_id=integration_identity_id, reported_by=reported_by,
        signature_verified=signature_verified, destination=destination, destination_operation_id=destination_operation_id,
        claimed_status="SENT", evidence_strength=strength,
    )
    db.add(event)
    operation.state = "DISPATCHED"
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
    RBAC_HUMAN / False. Neither is inferred.

    Precondition: the Operation must already be CLAIMED or later --
    observation evidence about an operation whose Capability was never
    even consumed is not evidence about this operation at all
    (OperationNotClaimedError). Once CLAIMED, though, evidence is
    accepted regardless of whether DISPATCHED was ever explicitly
    reported: a crash after claim with no dispatch evidence must still
    be handled conservatively -- absence of dispatch evidence does not
    establish absence of an external effect.

    Revocation of OBSERVATION authority specifically (as opposed to
    execution authority) is not re-checked here as a separate step --
    it's already the first thing submit_execution_receipt below checks
    (`identity.status != "active"`), and this function raises whatever
    that raises, unchanged. If observation authority is revoked, this
    call fails before any evidence is recorded and before reconciliation
    ever runs -- the state is left exactly as it was."""
    operation = _get_operation_for_organization(db, organization_id, operation_id)
    if operation.state not in _STATES_ELIGIBLE_FOR_OBSERVATION:
        raise OperationNotClaimedError(operation.id, operation.state)

    if material_action_digest != operation.material_action_digest:
        raise MaterialActionMismatchError(operation.material_action_digest, material_action_digest)

    receipt = receipt_svc.submit_execution_receipt(
        db, identity, enforcement_binding_id=enforcement_binding_id, decision_id=operation.decision_id,
        canonical_action_digest=canonical_action_digest,
        external_operation_id=operation.destination_operation_id or _resolve_external_operation_id(db, operation),
        destination=destination, status=status, capability_id=capability_id,
        occurred_at=occurred_at, detail=detail,
    )
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
    report ALSO advances a lifecycle-covered Operation's state -- without
    this, only the weaker RBAC recovery path could ever reach COMMITTED/
    TERMINALLY_NOT_COMMITTED, which would defeat the point of the
    stronger channel existing at all.

    Silent no-op (returns None) when no Operation is linked to this
    receipt's decision_id -- the same "legacy caller, not lifecycle-
    covered" distinction capability_service.verify_and_consume_
    capability already makes, applied here too."""
    operation = db.scalar(select(Operation).where(Operation.decision_id == receipt.decision_id, Operation.organization_id == organization_id))
    if operation is None:
        return None
    if operation.state not in _STATES_ELIGIBLE_FOR_OBSERVATION:
        # A receipt referencing a Capability that was never actually
        # claimed is exactly the "decision_not_found"-adjacent anomaly
        # submit_execution_receipt's own linkage checks are meant to
        # catch upstream; if one somehow reaches here, fail closed
        # rather than silently forcing a state transition.
        raise OperationNotClaimedError(operation.id, operation.state)
    return _finalize_observation_event(
        db, organization_id, operation, receipt, identity_id=receipt.integration_identity_id,
        reporter_kind=reporter_kind, signature_verified=signature_verified, reported_by=reported_by,
        destination=receipt.destination, status=receipt.status,
    )


def _finalize_observation_event(
    db: Session, organization_id: uuid.UUID, operation: Operation, receipt, *, identity_id: uuid.UUID,
    reporter_kind: str, signature_verified: bool, reported_by: str, destination: str, status: str,
):
    strength = _evidence_strength(reporter_kind, signature_verified)

    if operation.destination is None:
        operation.destination = destination
    if operation.destination_operation_id is None:
        operation.destination_operation_id = receipt.external_operation_id

    event = OperationEvidenceEvent(
        organization_id=organization_id, operation_id=operation.id, event_type="OBSERVATION",
        reporter_kind=reporter_kind, integration_identity_id=identity_id, reported_by=reported_by,
        signature_verified=signature_verified, destination=destination,
        destination_operation_id=operation.destination_operation_id, claimed_status=status,
        evidence_strength=strength, receipt_id=receipt.id,
    )
    db.add(event)

    result = reconciliation_svc.reconcile_decision(db, organization_id, operation.decision_id)
    new_state = _OUTCOME_TO_STATE[result.outcome]
    if operation.state not in _TERMINAL_STATES or new_state in _TERMINAL_STATES:
        operation.state = new_state
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
    top-of-file docstring). Four distinct outcomes, not three:

      BLOCKED_ALREADY_COMMITTED       -- the original operation already
        succeeded. A "replacement" here is not a recovery action, it is
        a duplicate-effect risk in its own right; blocked, not offered
        as safe.
      UNSAFE_UNRESOLVED               -- the original outcome is not yet
        known (CLAIMED/DISPATCHED/OUTCOME_UNKNOWN) and no valid,
        currently-covering guarantee exists. The fail-closed default.
      SAFE_TERMINAL_NON_COMMIT_PROVEN -- destination-authoritative
        evidence establishes the original did not, and will not,
        commit. Safe to attempt a replacement, but `requires_current_
        authorization` is always True: safety here never substitutes
        for a fresh Intent actually evaluating to ALLOW.
      SAFE_DUPLICATE_PREVENTION_GUARANTEED -- a live, human-documented
        guarantee covers this exact operation. If it is scoped to a
        specific identity/binding (restricted_to_integration_identity_id
        / restricted_to_enforcement_binding_id), the caller's own
        `attempting_*` identity must match EXACTLY, or this degrades to
        UNSAFE_UNRESOLVED -- "any permitted attempt must use the
        identity and conditions that guarantee actually protects," not
        any identity at all."""
    operation = _get_operation_for_organization(db, organization_id, operation_id)

    if operation.state == "COMMITTED":
        return ReplacementSafety(
            safety="BLOCKED_ALREADY_COMMITTED",
            reason="the original operation already committed; a further effect would itself be a duplicate, not a recovery",
            requires_current_authorization=True,
        )

    if operation.state == "TERMINALLY_NOT_COMMITTED":
        return ReplacementSafety(
            safety="SAFE_TERMINAL_NON_COMMIT_PROVEN",
            reason="destination-authoritative evidence establishes the original operation did not, and will not, commit",
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
        reason=f"operation state is {operation.state!r}: neither terminal non-commit proof nor a live, scoped duplicate-prevention guarantee exists for this exact operation",
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
