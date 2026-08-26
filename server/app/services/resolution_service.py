import uuid

from sqlalchemy.orm import Session

from app.db.models import Decision, DecisionResolution, Intent
from app.services.intent_service import _resolve_chain_scope, append_evidence


class DecisionNotFoundError(Exception):
    pass


class DecisionNotHumanReviewError(Exception):
    pass


class DecisionAlreadyResolvedError(Exception):
    pass


def resolve_decision(
    db: Session,
    decision_id: uuid.UUID,
    organization_id: uuid.UUID | None,
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
    or API-key paths, which remain fully supported.

    Runtime Governance Architecture, Phase 1 (24_PHASE_1_RUNTIME_CORE_PLAN.md
    section 24.2.2): this function is the one and only place Decision
    Evidence's "who reviewed" role actually applies -- a human resolving a
    decision Runtime Authority itself could not reach alone. The
    Evidence payload's existing `approver`/`approval_outcome` keys (kept
    unchanged, since real readers already depend on them) are exact
    aliases of `resolved_by`/`resolution.upper()`; `reviewer`/
    `review_outcome` are added at this same call site so a reader using
    canon vocabulary finds the correctly-named field without the
    existing keys ever needing to change or be removed.

    Milestone 11 (MILESTONE_11_SECURITY_BOUNDARY_COMPLETION_SUMMARY.md):
    `organization_id` is new -- this write path previously had no
    organisation-ownership check at all, meaning any caller holding
    Permission.DECISIONS_RESOLVE for ANY organisation could resolve a
    HUMAN_REVIEW decision belonging to a DIFFERENT one. Checked
    immediately after confirming the decision exists and before any
    other branch (HUMAN_REVIEW state, already-resolved state), so a
    cross-org caller learns nothing about the decision's actual state --
    the same DecisionNotFoundError a genuinely nonexistent decision
    raises, never a different signal. Resolved via the same
    Agent -> Principal -> organization_id chain
    (intent_service._resolve_chain_scope) every other decision-security
    boundary in this codebase already uses, not a new mechanism."""
    decision = db.get(Decision, decision_id)
    if decision is None:
        raise DecisionNotFoundError(str(decision_id))

    intent = db.get(Intent, decision.intent_id)
    decision_organization_id = _resolve_chain_scope(db, intent.agent_id)
    if decision_organization_id != organization_id:
        raise DecisionNotFoundError(str(decision_id))

    if decision.outcome != "HUMAN_REVIEW":
        raise DecisionNotHumanReviewError(decision.outcome)

    existing = (
        db.query(DecisionResolution).filter_by(decision_id=decision_id).one_or_none()
    )
    if existing is not None:
        raise DecisionAlreadyResolvedError(str(decision_id))

    evidence = append_evidence(
        db,
        decision.id,
        intent.agent_id,
        intent.action,
        # Domain Generalization Milestone: intent.amount is genuinely
        # nullable (a non-financial decision has none) -- the previously
        # unconditional float() here raised TypeError the moment a
        # HUMAN_REVIEW decision with no amount was resolved.
        float(intent.amount) if intent.amount is not None else None,
        decision.evaluated_mandates or [],
        outcome=decision.outcome,
        approval_outcome=resolution.upper(),
        approver=resolved_by,
        reviewer=resolved_by,
        review_outcome=resolution.upper(),
        status="VERIFIED" if resolution == "approved" else "REJECTED",
        resource=intent.resource,
        currency=intent.currency,
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
