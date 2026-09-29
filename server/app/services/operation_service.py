"""Product lifecycle vertical slice (EVIDENCEBOUND-PAYREALITY-RECOVERY-V01
follow-up): the durable Operation record and its state machine, plus the
narrowly scoped observation path and the replacement-safety gate.

Deliberately a thin orchestration layer, not a parallel implementation:
every trust decision this module makes (is this identity/organization
still active, does this receipt's linkage match its decision, is this a
duplicate/conflicting/contradictory report) is delegated to the real,
already-tested execution_receipt_service and execution_reconciliation_
service unchanged -- this module adds exactly three things those two
don't already do: (1) an Operation existing at all, separately from a
Capability's own single-use lifetime, (2) validating an incoming
observation's claimed material_action_digest against the Operation's own
recorded one (a check neither of those two services performs, since
neither knows about order_action_contract.py), and (3) mapping a
reconciliation outcome onto this module's own coarser Operation.state
vocabulary.

Authority vs. safety, kept genuinely separate (section 8's own
instruction): AUTHORITY to attempt a replacement is answered exactly as
it always has been -- by submitting a new Intent through decision/
engine.py and seeing whether it evaluates to ALLOW (or an approved
HUMAN_REVIEW). This module never touches that decision. SAFETY is what
this module's own evaluate_replacement_safety answers, and it answers a
different question entirely: even given fresh authority, would attempting
it risk a duplicate real-world effect against an operation whose outcome
is still open. The two are two different function calls in two different
modules on purpose, not one check phrased two ways.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    CapabilityToken,
    DestinationDuplicatePreventionGuarantee,
    IntegrationIdentity,
    Operation,
)
from app.services import execution_receipt_service as receipt_svc
from app.services import execution_reconciliation_service as reconciliation_svc
from app.services import intent_service

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
# States that section 9's own instruction ("a late COMMITTED result
# updates historical knowledge; it does not restore current execution
# authority") never regresses OUT of once reached. OUTCOME_UNKNOWN is
# deliberately absent: it is the one state later evidence is expected to
# move on FROM.
_TERMINAL_STATES = frozenset({"COMMITTED", "TERMINALLY_NOT_COMMITTED"})


class OperationNotFoundError(Exception):
    pass


class OperationAlreadyExistsForDecisionError(Exception):
    def __init__(self, operation_id: uuid.UUID):
        self.operation_id = operation_id
        super().__init__(f"operation already exists for this decision: {operation_id}")


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
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"replacement not safe: {reason}")


@dataclass(frozen=True)
class ReplacementSafety:
    safety: str  # "SAFE_TERMINAL_NON_COMMIT_PROVEN" | "SAFE_DUPLICATE_PREVENTION_GUARANTEED" | "UNSAFE_UNRESOLVED"
    reason: str


def _get_operation_for_organization(db: Session, organization_id: uuid.UUID, operation_id: uuid.UUID) -> Operation:
    operation = db.get(Operation, operation_id)
    if operation is None or operation.organization_id != organization_id:
        raise OperationNotFoundError(str(operation_id))
    return operation


def create_operation_for_decision(
    db: Session, organization_id: uuid.UUID, decision_id: uuid.UUID, material_action_digest: str,
) -> Operation:
    """Called once, at Capability issuance time (services/
    capability_service.py's own _issue_and_persist), never independently
    of a real, just-issued Capability -- an Operation with no Capability
    behind it would have nothing granting it any execution authority to
    track in the first place. State AUTHORIZED: a Capability exists;
    nothing has been attempted yet."""
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


def record_dispatch(db: Session, organization_id: uuid.UUID, decision_id: uuid.UUID, capability_id: uuid.UUID) -> Operation:
    """Called from services/capability_service.verify_and_consume_
    capability, in the SAME transaction as the atomic single-use consume
    -- an attempt was just made. AUTHORIZED -> DISPATCHED, attempt_count
    incremented. Idempotent-by-construction in practice: this is only
    ever called once per Operation, because the Capability it's called
    from can only ever be consumed once (the atomic UPDATE this follows
    is the actual guarantee; this function trusts that guarantee rather
    than re-deriving it)."""
    operation = db.scalar(select(Operation).where(Operation.decision_id == decision_id))
    if operation is None or operation.organization_id != organization_id:
        raise OperationNotFoundError(str(decision_id))
    operation.capability_id = capability_id
    operation.state = "DISPATCHED"
    operation.attempt_count += 1
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
    enforcement_binding_id: uuid.UUID,
    material_action_digest: str,
    canonical_action_digest: str,
    destination: str,
    status: str,
    capability_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
    detail: str | None = None,
):
    """The narrowly scoped observation path (section 7). Structurally,
    not merely by convention, this function CANNOT issue a Capability,
    submit a new Intent, or change a material action: it calls exactly
    two other functions, execution_receipt_service.submit_execution_
    receipt (append evidence for an operation that already has a
    Decision) and execution_reconciliation_service.reconcile_decision
    (read-only computation over already-persisted records) -- neither of
    which is capable of any of those things either. "Constrain
    observation to an already-existing operation" is enforced literally:
    the very first thing this does is look the Operation up and fail
    closed (OperationNotFoundError) if it doesn't exist; there is no
    parameter anywhere in this function that could create one.

    Revocation of OBSERVATION authority specifically (as opposed to
    execution authority) is not re-checked here as a separate step --
    it's already the first thing submit_execution_receipt below checks
    (`identity.status != "active"`), and this function raises whatever
    that raises, unchanged. If observation authority is revoked, this
    call fails before any evidence is recorded and before reconciliation
    ever runs -- the state is left exactly as it was, matching section
    7's own "leave the outcome uncertain" instruction precisely, not
    approximately."""
    operation = _get_operation_for_organization(db, organization_id, operation_id)

    if material_action_digest != operation.material_action_digest:
        raise MaterialActionMismatchError(operation.material_action_digest, material_action_digest)

    receipt = receipt_svc.submit_execution_receipt(
        db, identity, enforcement_binding_id=enforcement_binding_id, decision_id=operation.decision_id,
        canonical_action_digest=canonical_action_digest, external_operation_id=operation.destination_operation_id
        or _placeholder_or_bind_destination_operation_id(db, operation),
        destination=destination, status=status, capability_id=capability_id,
        occurred_at=occurred_at, detail=detail,
    )

    if operation.destination is None:
        operation.destination = destination
    if operation.destination_operation_id is None:
        operation.destination_operation_id = receipt.external_operation_id

    result = reconciliation_svc.reconcile_decision(db, organization_id, operation.decision_id)
    new_state = _OUTCOME_TO_STATE[result.outcome]
    if operation.state not in _TERMINAL_STATES or new_state in _TERMINAL_STATES:
        # A terminal state is never overwritten by a later OUTCOME_UNKNOWN-
        # mapping report (a stray INDETERMINATE/MISMATCHED after a real
        # MATCHED does not erase the earlier, stronger evidence); it CAN
        # be updated by another terminal-mapping outcome, matching
        # reconciliation's own fixed precedence rule (a later SUCCEEDED
        # always wins regardless of order -- see execution_reconciliation_
        # service.py's own _TERMINAL_PRECEDENCE).
        operation.state = new_state
    operation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(operation)
    return operation, receipt, result


def _placeholder_or_bind_destination_operation_id(db: Session, operation: Operation) -> str:
    """Only reached when an Operation has never recorded a destination_
    operation_id at all (its very first observation) -- resolves the
    real external_operation_id from the Operation's own Decision/Intent,
    never invents one. Kept as its own small function purely so record_
    observation's own body reads as "the normal path", not because this
    is a meaningfully separate concern."""
    from app.db.models import Decision, Intent

    decision = db.get(Decision, operation.decision_id)
    intent = db.get(Intent, decision.intent_id)
    return intent.external_operation_id


def evaluate_replacement_safety(db: Session, organization_id: uuid.UUID, operation_id: uuid.UUID) -> ReplacementSafety:
    """Answers SAFETY only -- never AUTHORITY (see this module's own
    top-of-file docstring). Fails closed: SAFE only if this exact
    Operation has reached TERMINALLY_NOT_COMMITTED, or a non-expired
    DestinationDuplicatePreventionGuarantee has been documented for it.
    Every other state, including OUTCOME_UNKNOWN and even COMMITTED
    (a genuinely successful original operation is not itself a reason a
    SEPARATE new attempt would be safe from double-effect -- it simply
    isn't the scenario this gate exists for, and this function does not
    special-case it into an implicit "yes")."""
    operation = _get_operation_for_organization(db, organization_id, operation_id)

    if operation.state == "TERMINALLY_NOT_COMMITTED":
        return ReplacementSafety(
            safety="SAFE_TERMINAL_NON_COMMIT_PROVEN",
            reason="destination-authoritative evidence establishes the original operation did not, and will not, commit",
        )

    guarantee = db.scalar(
        select(DestinationDuplicatePreventionGuarantee).where(
            DestinationDuplicatePreventionGuarantee.operation_id == operation_id,
        )
    )
    # SQLite (this test suite's own backing store) does not round-trip
    # timezone-aware DateTime values -- a value stored tz-aware comes
    # back naive, confirmed by hitting a naive/aware comparison
    # TypeError before this fix. Postgres's DateTime(timezone=True) does
    # not have this gap; normalizing defensively here is correct either
    # way, not merely a SQLite workaround.
    retention_until = guarantee.retention_until if guarantee is not None else None
    if retention_until is not None and retention_until.tzinfo is None:
        retention_until = retention_until.replace(tzinfo=timezone.utc)
    if guarantee is not None and retention_until > datetime.now(timezone.utc):
        return ReplacementSafety(
            safety="SAFE_DUPLICATE_PREVENTION_GUARANTEED",
            reason=f"documented guarantee (scope: {guarantee.scope_description!r}, by {guarantee.documented_by!r}, valid until {guarantee.retention_until.isoformat()})",
        )

    return ReplacementSafety(
        safety="UNSAFE_UNRESOLVED",
        reason=f"operation state is {operation.state!r}: neither terminal non-commit proof nor a live, scoped duplicate-prevention guarantee exists for this exact operation",
    )


def record_destination_duplicate_prevention_guarantee(
    db: Session, organization_id: uuid.UUID, operation_id: uuid.UUID, *,
    destination: str, scope_description: str, retention_until: datetime, documented_by: str,
) -> DestinationDuplicatePreventionGuarantee:
    """A human-documented fact, never auto-inferred (section 8's own
    instruction). Fails closed on an empty scope_description or a
    retention_until that has already passed -- an undated or unscoped
    "guarantee" is not representable here, structurally, matching
    DestinationDuplicatePreventionGuarantee's own NOT NULL columns."""
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
        db.commit()
        db.refresh(existing)
        return existing

    guarantee = DestinationDuplicatePreventionGuarantee(
        organization_id=organization_id, operation_id=operation_id, destination=destination,
        scope_description=scope_description, retention_until=retention_until, documented_by=documented_by,
    )
    db.add(guarantee)
    db.commit()
    db.refresh(guarantee)
    return guarantee
