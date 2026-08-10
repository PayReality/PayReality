from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Agent, EnterpriseSystem, User
from app.db.session import get_db
from app.dependencies import get_current_user_if_session, require_permission, verify_agent_signature
from app.domain.auth.signature import check_timestamp_window
from app.domain.rbac.permissions import Permission
from app.schemas.intent import (
    DecisionSummary,
    GetDecisionResponse,
    ResolutionSummary,
    ResolveDecisionRequest,
    ResolveDecisionResponse,
    SubmitIntentRequest,
    SubmitIntentResponse,
)
from app.services import intent_service, resolution_service
from app.services.intent_service import (
    AgentNotOperationalError,
    AgentRetiredError,
    AgentRevokedError,
    ReplayDetectedError,
)
from app.services.resolution_service import (
    DecisionAlreadyResolvedError,
    DecisionNotFoundError,
    DecisionNotHumanReviewError,
)

router = APIRouter(prefix="/v1", tags=["intents"])


def _enterprise_system_name(db: Session, enterprise_system_id: UUID | None) -> str | None:
    """Phase 5, Release 2: resolves the same id intent_service already
    persisted on the Decision row -- never recomputed, only displayed."""
    if enterprise_system_id is None:
        return None
    system = db.get(EnterpriseSystem, enterprise_system_id)
    return system.name if system else None


@router.post("/intents", response_model=SubmitIntentResponse)
def submit_intent(
    body: SubmitIntentRequest,
    agent: Agent = Depends(verify_agent_signature),
    db: Session = Depends(get_db),
):
    """spec 19.5. The `agent` dependency has already verified the request
    signature over the raw body; this handler is authenticated by the
    time it runs."""
    if str(body.agent_id) != str(agent.id):
        raise HTTPException(status_code=401, detail="agent_id_does_not_match_signing_key")

    window_check = check_timestamp_window(
        body.requested_at, settings.intent_signature_window_seconds
    )
    if not window_check.ok:
        raise HTTPException(status_code=401, detail=window_check.reason)

    try:
        intent, decision, evidence = intent_service.submit_intent(
            db,
            agent=agent,
            action=body.action,
            amount=body.amount,
            currency=body.currency,
            counterparty=body.counterparty,
            context=body.context,
            requested_at=body.requested_at,
            nonce=body.nonce,
            correlation_id=body.correlation_id,
        )
    except AgentRevokedError:
        raise HTTPException(status_code=403, detail="agent_revoked")
    except AgentRetiredError:
        raise HTTPException(status_code=403, detail="agent_retired")
    except AgentNotOperationalError:
        raise HTTPException(status_code=403, detail="agent_not_operational")
    except ReplayDetectedError:
        raise HTTPException(status_code=409, detail="replay_detected")

    status = "PENDING" if decision.outcome == "HUMAN_REVIEW" else "RESOLVED"

    return SubmitIntentResponse(
        intent_id=intent.id,
        decision=DecisionSummary(
            outcome=decision.outcome,
            decision_id=decision.id,
            evaluated_mandates=decision.evaluated_mandates or [],
            evaluated_mandate_ids=decision.evaluated_mandate_ids or [],
            enterprise_system_id=decision.enterprise_system_id,
            enterprise_system_name=_enterprise_system_name(db, decision.enterprise_system_id),
            reason=decision.reason,
        ),
        evidence_id=evidence.id,
        status=status,
    )


@router.get("/decisions/{decision_id}", response_model=GetDecisionResponse)
def get_decision(decision_id: UUID, db: Session = Depends(get_db)):
    """New (not in spec 19's literal API): the poll endpoint a caller uses
    until a HUMAN_REVIEW decision is resolved (see plan's addition)."""
    decision = intent_service.get_decision(db, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="decision_not_found")

    from app.db.models import DecisionResolution, Intent

    intent = db.get(Intent, decision.intent_id)
    resolution_row = db.query(DecisionResolution).filter_by(decision_id=decision.id).one_or_none()

    resolution = None
    if resolution_row is not None:
        resolution = ResolutionSummary(
            resolution=resolution_row.resolution,
            resolved_by=resolution_row.resolved_by,
            reason=resolution_row.reason,
            created_at=resolution_row.created_at,
        )

    status = "PENDING" if (decision.outcome == "HUMAN_REVIEW" and resolution is None) else "RESOLVED"

    return GetDecisionResponse(
        id=decision.id,
        status=status,
        outcome=decision.outcome,
        reason=decision.reason,
        agent_id=intent.agent_id,
        action=intent.action,
        amount=float(intent.amount),
        currency=intent.currency,
        evaluated_mandates=decision.evaluated_mandates or [],
        evaluated_mandate_ids=decision.evaluated_mandate_ids or [],
        enterprise_system_id=decision.enterprise_system_id,
        enterprise_system_name=_enterprise_system_name(db, decision.enterprise_system_id),
        resolution=resolution,
    )


@router.post(
    "/decisions/{decision_id}/resolve",
    response_model=ResolveDecisionResponse,
    dependencies=[Depends(require_permission(Permission.DECISIONS_RESOLVE))],
)
def resolve_decision(
    decision_id: UUID,
    body: ResolveDecisionRequest,
    db: Session = Depends(get_db),
    session_user: User | None = Depends(get_current_user_if_session),
):
    """The Phase 1 addition (see plan's 'The one addition: resolving
    HUMAN_REVIEW'). Gated by permission (RBAC.md) so not anyone can resolve
    a review.

    Authority-as-a-continuous-object, Stage D: `resolved_by` (free text)
    is still the field every existing reader displays, and the caller can
    still send whatever name they like there. Where the request actually
    carried a real session (not the Operator Key, not a bare API key),
    `resolved_by_user_id` now also records the exact, authenticated User
    who clicked, so the audit trail can't diverge from who was actually
    permitted to act."""
    if body.resolution not in ("approved", "denied"):
        raise HTTPException(status_code=422, detail="invalid_resolution")

    try:
        resolution_row = resolution_service.resolve_decision(
            db,
            decision_id=decision_id,
            resolution=body.resolution,
            resolved_by=body.resolved_by,
            reason=body.reason,
            resolved_by_user_id=session_user.id if session_user else None,
        )
    except DecisionNotFoundError:
        raise HTTPException(status_code=404, detail="decision_not_found")
    except DecisionNotHumanReviewError as e:
        raise HTTPException(status_code=409, detail=f"decision_not_human_review:{e}")
    except DecisionAlreadyResolvedError:
        raise HTTPException(status_code=409, detail="decision_already_resolved")

    return ResolveDecisionResponse(
        decision_id=decision_id,
        resolution=ResolutionSummary(
            resolution=resolution_row.resolution,
            resolved_by=resolution_row.resolved_by,
            reason=resolution_row.reason,
            created_at=resolution_row.created_at,
        ),
        evidence_id=resolution_row.evidence_id,
    )
