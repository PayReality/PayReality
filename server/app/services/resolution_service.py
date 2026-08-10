import uuid

from sqlalchemy.orm import Session

from app.db.models import Decision, DecisionResolution, Intent
from app.services.intent_service import append_evidence


class DecisionNotFoundError(Exception):
    pass


class DecisionNotHumanReviewError(Exception):
    pass


class DecisionAlreadyResolvedError(Exception):
    pass


def resolve_decision(
    db: Session,
    decision_id: uuid.UUID,
    resolution: str,
    resolved_by: str,
    reason: str | None = None,
    resolved_by_user_id: uuid.UUID | None = None,
) -> DecisionResolution:
    """The Phase 1 addition described in the plan: closes the HUMAN_REVIEW
    loop without mutating the immutable Decision row (spec 8.2's lifecycle
    guarantee: "created once, immutable, never updated"). Appends a new
    chained Evidence record capturing the resolution as a separate fact
    (spec 17's evidence-by-default principle applied to this new event).

    Authority-as-a-continuous-object, Stage D: `resolved_by` (free text)
    is kept exactly as every existing caller and reader depends on it.
    `resolved_by_user_id` is additive: populated only when the caller
    actually resolved a real session user (see
    dependencies.get_current_user_if_session), None for the Operator Key
    or API-key paths, which remain fully supported."""
    decision = db.get(Decision, decision_id)
    if decision is None:
        raise DecisionNotFoundError(str(decision_id))
    if decision.outcome != "HUMAN_REVIEW":
        raise DecisionNotHumanReviewError(decision.outcome)

    existing = (
        db.query(DecisionResolution).filter_by(decision_id=decision_id).one_or_none()
    )
    if existing is not None:
        raise DecisionAlreadyResolvedError(str(decision_id))

    intent = db.get(Intent, decision.intent_id)

    evidence = append_evidence(
        db,
        decision.id,
        intent.agent_id,
        intent.action,
        float(intent.amount),
        decision.evaluated_mandates or [],
        outcome=decision.outcome,
        approval_outcome=resolution.upper(),
        approver=resolved_by,
        status="VERIFIED" if resolution == "approved" else "REJECTED",
        # Authority-as-a-continuous-object, Stage H: reuses the real
        # Mandate ids already resolved and persisted on the original
        # Decision row at submit_intent time -- nothing recomputed here.
        mandate_ids=decision.evaluated_mandate_ids or [],
        # Phase 5, Release 2: same reuse pattern -- the Enterprise System
        # was already resolved and persisted on the original Decision row.
        enterprise_system_id=decision.enterprise_system_id,
    )

    resolution_row = DecisionResolution(
        decision_id=decision_id,
        resolution=resolution,
        resolved_by=resolved_by,
        reason=reason,
        evidence_id=evidence.id,
        resolved_by_user_id=resolved_by_user_id,
    )
    db.add(resolution_row)
    db.commit()
    db.refresh(resolution_row)
    return resolution_row
