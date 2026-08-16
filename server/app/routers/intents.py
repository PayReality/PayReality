from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Agent, EnterpriseSystem, Evidence, Organization, Policy, User
from app.db.session import get_db
from app.dependencies import (
    get_current_organization,
    get_current_user_if_session,
    require_permission,
    verify_agent_signature,
)
from app.domain.auth.signature import check_timestamp_window
from app.domain.rbac.permissions import Permission
from app.schemas.intent import (
    DecisionExplanationResponse,
    DecisionPolicyBindingResponse,
    DecisionSummary,
    GetDecisionResponse,
    PolicyManifestEntry,
    ResolutionSummary,
    ResolveDecisionRequest,
    ResolveDecisionResponse,
    SubmitIntentRequest,
    SubmitIntentResponse,
)
from app.schemas.policy_simulation import ConditionEvaluationResponse, RuleEvaluationResponse
from app.services import decision_explanation_service, intent_service, resolution_service
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

    # Runtime Decision Center V2, Phase 2A: policy_version/policy_bundle_hash/
    # authority_version are never persisted on Decision itself (see
    # decision_engine.Decision's own docstring) -- this decision's own
    # earliest Evidence record is where Phase 1 already pinned them, so
    # they're read from there rather than recomputed. None of the three
    # queries below are new persistence; they read what submit_intent
    # already wrote.
    earliest_evidence = (
        db.query(Evidence)
        .filter(Evidence.decision_id == decision.id)
        .order_by(Evidence.created_at.asc(), Evidence.id.asc())
        .first()
    )
    evidence_payload = earliest_evidence.payload if earliest_evidence is not None else {}

    return GetDecisionResponse(
        id=decision.id,
        status=status,
        outcome=decision.outcome,
        reason=decision.reason,
        agent_id=intent.agent_id,
        action=intent.action,
        amount=float(intent.amount),
        currency=intent.currency,
        created_at=decision.created_at,
        evaluated_mandates=decision.evaluated_mandates or [],
        evaluated_mandate_ids=decision.evaluated_mandate_ids or [],
        enterprise_system_id=decision.enterprise_system_id,
        enterprise_system_name=_enterprise_system_name(db, decision.enterprise_system_id),
        policy_version=evidence_payload.get("policy_version"),
        policy_bundle_hash=evidence_payload.get("policy_bundle_hash"),
        authority_version=evidence_payload.get("authority_version"),
        resolution=resolution,
    )


@router.get(
    "/decisions/{decision_id}/policy-binding",
    response_model=DecisionPolicyBindingResponse,
)
def get_decision_policy_binding(
    decision_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Historical Policy Binding: answers 'exactly which policy state
    evaluated this decision?' without ever reading whatever policy is
    active today. Decision.policy_id already points to an immutable,
    retired-not-deleted `policies` row (deploy_policy never mutates or
    deletes one); this just surfaces it, plus the manifest of which
    RuntimePolicyRecord versions were compiled into it, if the bundle
    was deployed after Policy.bundle_manifest existed.

    Org-scoped the same way runtime_policies.py's own read endpoints
    are (compare against Policy.organization_id, 404 on mismatch --
    never a 403 that would confirm the decision exists at all to a
    caller from a different organization). GET /v1/decisions/{id}
    itself has no such scoping (a separate, pre-existing, unrelated
    fact, not something this endpoint changes); this one does, since
    it's the one that can reveal another organization's actual policy
    content."""
    decision = intent_service.get_decision(db, decision_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="decision_not_found")
    if decision.policy_id is None:
        raise HTTPException(status_code=404, detail="no_policy_bound")

    policy = db.get(Policy, decision.policy_id)
    if policy is None or policy.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="decision_not_found")

    manifest = policy.bundle_manifest or {}
    return DecisionPolicyBindingResponse(
        decision_id=decision.id,
        policy_id=policy.id,
        bundle_hash=policy.bundle_hash,
        bundle_version=policy.version,
        compiled_at=policy.compiled_at,
        activated_at=policy.activated_at,
        retired_at=policy.retired_at,
        policies=[PolicyManifestEntry(**p) for p in manifest.get("policies", [])],
    )


def _rule_to_response(r) -> RuleEvaluationResponse:
    """Same conversion routers/policy_simulation.py's own
    _rule_to_response does for the Simulator's identical
    RuleEvaluation/ConditionEvaluation dataclasses -- reusing the
    SCHEMA (RuleEvaluationResponse/ConditionEvaluationResponse) rather
    than defining a second one; kept as its own small function here
    (not imported from that router module) since this is presentation-
    layer glue, not business logic, and importing across router modules
    for six lines would be an odd cross-dependency for no real reuse
    benefit."""
    return RuleEvaluationResponse(
        policy_id=r.policy_id, policy_name=r.policy_name, principal=r.principal, action=r.action,
        effect=r.effect, scope_matched=r.scope_matched, matched=r.matched, summary=r.summary,
        conditions=[
            ConditionEvaluationResponse(
                field=c.field, operator=c.operator, expected_value=c.expected_value,
                actual_value=c.actual_value, passed=c.passed,
            )
            for c in r.conditions
        ],
    )


@router.get(
    "/decisions/{decision_id}/explanation",
    response_model=DecisionExplanationResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_VIEW))],
)
def get_decision_explanation(
    decision_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Phase 2B: the explanatory path. Gated by Permission.RUNTIME_POLICY_VIEW,
    the same permission routers/policy_simulation.py already uses for
    every read-only rule-evaluation exposure in this codebase (that
    router's own docstring: "simulating... is an exploratory, read-only
    action... not an edit/publish action"), reusing precedent rather
    than inventing a new gate. Org-scoped the same way
    get_decision_policy_binding is (404, never 403, on a cross-org
    Policy)."""
    try:
        result = decision_explanation_service.get_decision_explanation(db, decision_id, organization.id)
    except decision_explanation_service.DecisionNotFoundError:
        raise HTTPException(status_code=404, detail="decision_not_found")
    except decision_explanation_service.CrossOrganizationAccessError:
        raise HTTPException(status_code=404, detail="decision_not_found")

    if isinstance(result, decision_explanation_service.ExplanationUnavailable):
        return DecisionExplanationResponse(decision_id=result.decision_id, available=False, unavailable_reason=result.reason)

    return DecisionExplanationResponse(
        decision_id=result.decision_id,
        available=True,
        outcome=result.outcome,
        reason=result.reason,
        policy_id=result.policy_id,
        bundle_hash=result.bundle_hash,
        bundle_version=result.bundle_version,
        compiled_at=result.compiled_at,
        activated_at=result.activated_at,
        retired_at=result.retired_at,
        evaluated_at=result.evaluated_at,
        causal_policy_id=result.causal_policy_id,
        rules=[_rule_to_response(r) for r in result.rules],
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
