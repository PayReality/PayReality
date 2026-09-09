"""Post-audit implementation, Priority 6: the minimal, generic
authorised-vs-executed reconciliation service -- given a Decision that
actually authorized an action (ALLOW, or an approved HUMAN_REVIEW), and
that reached Runtime Authority through the Adapter-mediated path, this
reconciles what was authorized against what the ingested execution
receipts (Priority 5) say happened.

Deliberately generic, not workflow-specific: no knowledge of what any
specific canonical action or destination means, no customer-declared
reconciliation rules. Reuses every existing trusted record rather than
re-deriving anything: the Decision/Intent pair, the Decision's own
(at most one) consumed Capability, and every ExecutionReceiptRecord row
Priority 5's own ingestion already trust-checked before persisting.

Scope boundary, stated precisely (do not overclaim beyond this): this
reconciles PayReality's own already-trusted internal records against each
other. It does not, and cannot, independently observe the external
system a receipt reports on -- see DECLARED_VS_OBSERVED_RECONCILIATION.md
for the single-attester limitation this service does not close or
extend. "Reconciled" here means "internally consistent with what
PayReality was told," never "independently verified to be true."

Out-of-order receipts, handled by a fixed, disclosed precedence rule, not
a timeline reconstruction: if ANY execution receipt for this Decision has
ever reported SUCCEEDED, the outcome is MATCHED, regardless of whether an
earlier or later receipt also reported FAILED/PARTIALLY_SUCCEEDED/UNKNOWN,
and regardless of submission order. This is a deliberate simplification --
a customer whose downstream system can genuinely flip a completed
operation's outcome after the fact needs a domain-specific reconciliation
rule this generic bridge does not provide (see this module's own
_TERMINAL_PRECEDENCE and _STATUS_TO_OUTCOME below for the complete rule).

Historical correctness: this service never re-runs Runtime Authority,
never re-checks the organization's CURRENT active policy, and never
consults anything other than the Decision's own already-persisted,
immutable records -- reconciling a Decision made under a policy version
the organization has since replaced still produces the same result today
as it would have the day the Decision was made."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    CapabilityToken,
    DecisionResolution,
    EnforcementBinding,
    ExecutionReceiptRecord,
    Intent,
    ReconciliationResultRecord,
)
from app.domain.evidence.signing import payload_hash
from app.services import intent_service
from app.services.intent_service import CrossOrganizationAccessError, DecisionNotFoundError

# Fixed severity precedence, most-authoritative first -- see this
# module's own top-level docstring for why this is order-independent by
# design, not a timeline reconstruction.
_TERMINAL_PRECEDENCE = ("SUCCEEDED", "PARTIALLY_SUCCEEDED", "FAILED", "UNKNOWN", "ACCEPTED")
_STATUS_TO_OUTCOME = {
    "SUCCEEDED": "MATCHED",
    "PARTIALLY_SUCCEEDED": "PARTIAL",
    "FAILED": "EXECUTION_FAILED",
    "UNKNOWN": "INDETERMINATE",
    "ACCEPTED": "INDETERMINATE",
}


class ReconciliationNotApplicableError(Exception):
    """Raised instead of ever producing a reconciliation result for a
    Decision this service has no honest basis to reconcile: one that was
    never actually authorized to execute (DENY, or an unresolved/rejected
    HUMAN_REVIEW), or one that never reached Runtime Authority through the
    Adapter-mediated path at all (an Agent-direct Intent has no Adapter,
    no Contract, no execution-receipt channel -- reconciling it would mean
    inventing a channel that does not exist for it)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _decision_is_authorized(db: Session, decision) -> bool:
    if decision.outcome == "ALLOW":
        return True
    if decision.outcome == "HUMAN_REVIEW":
        resolution = db.query(DecisionResolution).filter_by(decision_id=decision.id).one_or_none()
        return resolution is not None and resolution.resolution == "approved"
    return False


def _result_digest(
    organization_id: uuid.UUID, decision_id: uuid.UUID, outcome: str,
    capability_id: uuid.UUID | None, latest_execution_receipt_id: uuid.UUID | None,
) -> str:
    payload = {
        "organization_id": str(organization_id),
        "decision_id": str(decision_id),
        "outcome": outcome,
        "capability_id": str(capability_id) if capability_id else None,
        "latest_execution_receipt_id": str(latest_execution_receipt_id) if latest_execution_receipt_id else None,
    }
    return payload_hash(payload)


def _latest_existing_result(db: Session, decision_id: uuid.UUID) -> ReconciliationResultRecord | None:
    return db.scalar(
        select(ReconciliationResultRecord)
        .where(ReconciliationResultRecord.decision_id == decision_id)
        .order_by(ReconciliationResultRecord.computed_at.desc())
        .limit(1)
    )


def _persist_result(
    db: Session, organization_id: uuid.UUID, decision_id: uuid.UUID, outcome: str,
    capability_id: uuid.UUID | None, latest_execution_receipt_id: uuid.UUID | None,
    canonical_action_digest: str | None, detail: str | None,
) -> ReconciliationResultRecord:
    """Section 6's own idempotency requirement: re-running reconciliation
    with no new information must be a true no-op, never a pointless
    duplicate row appended on every call. The comparison is the digest
    over exactly the fields that determine the outcome -- not a full-row
    comparison, since `detail` alone changing (e.g. wording) without the
    outcome/capability/receipt changing is not a new reconciliation
    finding worth a new immutable Evidence event."""
    digest = _result_digest(organization_id, decision_id, outcome, capability_id, latest_execution_receipt_id)
    existing = _latest_existing_result(db, decision_id)
    if existing is not None and existing.result_digest == digest:
        return existing

    evidence = intent_service.append_generic_evidence_event(
        db, organization_id, decision_id, "RECONCILIATION_OUTCOME",
        {
            "outcome": outcome,
            "capability_id": str(capability_id) if capability_id else None,
            "latest_execution_receipt_id": str(latest_execution_receipt_id) if latest_execution_receipt_id else None,
            "canonical_action_digest": canonical_action_digest,
            "detail": detail,
        },
    )
    row = ReconciliationResultRecord(
        organization_id=organization_id,
        decision_id=decision_id,
        capability_id=capability_id,
        latest_execution_receipt_id=latest_execution_receipt_id,
        canonical_action_digest=canonical_action_digest,
        outcome=outcome,
        result_digest=digest,
        detail=detail,
        evidence_id=evidence.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def reconcile_decision(
    db: Session, organization_id: uuid.UUID, decision_id: uuid.UUID,
) -> ReconciliationResultRecord:
    """Computes (or, if nothing has changed since the last computation,
    returns unchanged) the current authorised-vs-executed reconciliation
    result for one Decision. Never modifies the Decision, its Intent, its
    Capability, or any ExecutionReceiptRecord row -- only ever appends a
    new ReconciliationResultRecord and a matching immutable Evidence
    event (or returns the existing one, on a genuine no-op re-run)."""
    try:
        decision = intent_service.get_decision_for_organization(db, decision_id, organization_id)
    except (DecisionNotFoundError, CrossOrganizationAccessError):
        raise ReconciliationNotApplicableError("decision_not_found")

    if not _decision_is_authorized(db, decision):
        raise ReconciliationNotApplicableError("decision_not_authorized")

    intent = db.get(Intent, decision.intent_id)
    if intent.enforcement_binding_id is None:
        raise ReconciliationNotApplicableError("agent_direct_intent_not_applicable")

    binding = db.get(EnforcementBinding, intent.enforcement_binding_id)
    capability = db.scalar(select(CapabilityToken).where(CapabilityToken.decision_id == decision_id))
    capability_id = capability.id if capability else None

    # Enforcement precondition check: a Binding that DECLARES its own
    # downstream checkpoint requires a consumed Capability, but whose
    # Decision has no consumed Capability at all, is a real, checkable
    # anomaly -- the authorization existed, but its own declared
    # enforcement precondition was never satisfied.
    if binding is not None and binding.enforcement_assurance == "CAPABILITY_REQUIRED":
        if capability is None or capability.consumed_at is None:
            return _persist_result(
                db, organization_id, decision_id, "MISMATCHED", capability_id, None,
                intent.canonical_action_digest, "capability_required_but_not_consumed",
            )

    receipts = list(
        db.scalars(
            select(ExecutionReceiptRecord)
            .where(ExecutionReceiptRecord.decision_id == decision_id)
            .order_by(ExecutionReceiptRecord.submitted_at.asc())
        )
    )
    if not receipts:
        return _persist_result(
            db, organization_id, decision_id, "RECEIPT_MISSING", capability_id, None,
            intent.canonical_action_digest, "no_execution_receipt_recorded_yet",
        )

    by_status = {r.status: r for r in receipts}
    chosen_status = next(s for s in _TERMINAL_PRECEDENCE if s in by_status)
    latest_receipt = by_status[chosen_status]
    outcome = _STATUS_TO_OUTCOME[chosen_status]
    detail = None

    # Defense-in-depth re-verification: Priority 5's own ingestion already
    # rejects a receipt whose canonical_action_digest disagrees with the
    # Intent's own -- this branch should be unreachable in normal
    # operation. It exists so reconciliation never blindly trusts a past
    # enforcement result without re-checking it against what is actually
    # persisted right now, rather than to catch a scenario expected to
    # occur.
    if latest_receipt.canonical_action_digest != intent.canonical_action_digest:
        outcome = "MISMATCHED"
        detail = "canonical_action_digest_mismatch_on_reverification"

    return _persist_result(
        db, organization_id, decision_id, outcome, capability_id, latest_receipt.id,
        intent.canonical_action_digest, detail,
    )
