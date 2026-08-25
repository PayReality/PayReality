"""Runtime Policy Lifecycle & Enterprise Runtime Management (Phase 5)
REST surface. Follows the existing API style
(routers/runtime_policies.py): one router, plain function-per-endpoint,
service-layer exceptions mapped to HTTP status codes here rather than in
the service.

Authorization (RUNTIME_POLICY_LIFECYCLE.md section 11): no new
Permission values. Activate/Schedule/Cancel/Rollback/Retire/Archive/
Deprecate all gate on the existing Permission.RUNTIME_POLICY_PUBLISH --
the same permission `deploy_policy` already gates on, held only by
Role.GOVERNANCE_ADMIN and Role.OWNER (this platform's "Policy
Administrator" equivalent). "Create Revision" reuses
Permission.RUNTIME_POLICY_EDIT, matching the existing edit endpoint it
wraps. Read endpoints (timeline, history, dashboard, search, schedules,
activation preview) carry no permission dependency, matching every
existing read endpoint in routers/runtime_policies.py -- any
authenticated caller may read.

One deliberate scope note: Approve/Reject stay on the existing
`/v1/runtime-policies/{policy_key}/approve` endpoint
(Permission.AUTHORITY_REVIEW, held by Role.REVIEWER too) rather than
moving to Permission.RUNTIME_POLICY_PUBLISH -- that endpoint and its
permission predate this phase and changing it would be modifying
existing, working RBAC behavior, not building additively on it."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.rbac.permissions import Permission
from app.security import verify_operator_key
from app.schemas.runtime_policy import AffectedAgentSchema, AffectedPolicySchema, ConditionDiffSchema, DiffResponse
from app.schemas.runtime_policy_lifecycle import (
    ActivateRequest,
    ActivationImpactPreviewResponse,
    ActorReasonRequest,
    AttestRequest,
    ConflictAlertSchema,
    DashboardResponse,
    PolicyLifecycleSummary,
    ProcessSchedulesResponse,
    RollbackRequest,
    SafetyCheckResultSchema,
    SafetyViolationSchema,
    ScheduleActivateRequest,
    ScheduleExecutionResultSchema,
    ScheduleRetireRequest,
    ScheduleSchema,
    SearchResponse,
    TimelineResponse,
    LifecycleEventSchema,
)
from app.services import runtime_policy_lifecycle_service as lsvc
from app.services.runtime_policy_service import (
    CompilationRequiredError,
    InvalidTransitionError,
    RuntimePolicyNotFoundError,
)

router = APIRouter(prefix="/v1/runtime-policies", tags=["runtime-policy-lifecycle"])
dashboard_router = APIRouter(prefix="/v1/runtime-policy-lifecycle", tags=["runtime-policy-lifecycle"])


def _opa_url() -> str:
    from app.config import settings

    return settings.opa_url


def _safety_to_schema(safety) -> SafetyCheckResultSchema:
    return SafetyCheckResultSchema(
        ok=safety.ok,
        violations=[
            SafetyViolationSchema(check=v.check, message=v.message, details=v.details) for v in safety.violations
        ],
    )


def _diff_to_schema(result) -> DiffResponse:
    return DiffResponse(
        conditions=[
            ConditionDiffSchema(kind=c.kind, field=c.field, operator=c.operator, old_value=c.old_value, new_value=c.new_value)
            for c in result.conditions
        ],
        scope_changed=result.scope_changed,
        effect_changed=result.effect_changed,
        constraints_changed=result.constraints_changed,
        affected_agents=[AffectedAgentSchema(**a) for a in result.affected_agents],
        affected_policies=[AffectedPolicySchema(**p) for p in result.affected_policies],
        risk_impact=result.risk_impact,
        risk_reason=result.risk_reason,
    )


def _event_to_schema(event) -> LifecycleEventSchema:
    return LifecycleEventSchema(
        id=str(event.id), policy_key=str(event.policy_key), version=event.version, event_type=event.event_type,
        actor=event.actor, reason=event.reason, payload=event.payload, event_hash=event.event_hash,
        occurred_at=event.occurred_at,
    )


def _schedule_to_schema(schedule) -> ScheduleSchema:
    return ScheduleSchema(
        id=str(schedule.id), policy_key=str(schedule.policy_key), version=schedule.version, action=schedule.action,
        effective_at=schedule.effective_at, reason=schedule.reason, status=schedule.status,
        created_by=schedule.created_by, created_at=schedule.created_at, executed_at=schedule.executed_at,
        execution_error=schedule.execution_error,
    )


def _row_to_summary(row, db: Session) -> PolicyLifecycleSummary:
    from app.schemas.runtime_policy import ScopeSchema

    content = row.content
    return PolicyLifecycleSummary(
        policy_key=str(row.policy_key), version=row.version, name=content["name"], status=row.status,
        effective_status=lsvc.effective_status(db, row), scope=ScopeSchema(**content["scope"]),
        created_at=row.created_at, activated_by=row.activated_by, activated_at=row.activated_at,
        activation_reason=row.activation_reason, effective_from=row.effective_from,
        effective_until=row.effective_until, deprecated_at=row.deprecated_at,
        deprecation_reason=row.deprecation_reason, rollback_of_version=row.rollback_of_version,
        last_attested_at=row.last_attested_at, next_review_at=row.next_review_at,
        review_cadence_days=row.review_cadence_days, authority_expires_at=row.authority_expires_at,
    )


# --- Activation, scheduling, rollback, retirement, archival ---------------


@router.post(
    "/{policy_key}/lifecycle/activate", response_model=PolicyLifecycleSummary,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_PUBLISH))],
)
def activate(
    policy_key: uuid.UUID,
    body: ActivateRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        row = lsvc.activate_policy(
            db, policy_key, organization.id, opa_url=_opa_url(), actor=body.actor, reason=body.reason
        )
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except lsvc.ActivationBlockedError as e:
        raise HTTPException(status_code=422, detail={"message": str(e), "violations": [
            {"check": v.check, "message": v.message, "details": v.details} for v in e.violations
        ]})
    except CompilationRequiredError as e:
        raise HTTPException(status_code=409, detail=f"compilation_required: {e}")
    return _row_to_summary(row, db)


@router.post(
    "/{policy_key}/lifecycle/schedule-activation", response_model=ScheduleSchema,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_PUBLISH))],
)
def schedule_activation(
    policy_key: uuid.UUID,
    body: ScheduleActivateRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        schedule = lsvc.schedule_activation(
            db, policy_key, organization.id, body.effective_at, actor=body.actor, reason=body.reason
        )
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except lsvc.ActivationBlockedError as e:
        raise HTTPException(status_code=422, detail={"message": str(e), "violations": [
            {"check": v.check, "message": v.message, "details": v.details} for v in e.violations
        ]})
    return _schedule_to_schema(schedule)


@router.post(
    "/{policy_key}/lifecycle/schedule-retirement", response_model=ScheduleSchema,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_PUBLISH))],
)
def schedule_retirement(
    policy_key: uuid.UUID,
    body: ScheduleRetireRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        schedule = lsvc.schedule_retirement(
            db, policy_key, organization.id, body.effective_at, actor=body.actor, reason=body.reason
        )
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _schedule_to_schema(schedule)


@router.post(
    "/{policy_key}/lifecycle/retire", response_model=PolicyLifecycleSummary,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_PUBLISH))],
)
def retire(
    policy_key: uuid.UUID,
    body: ActorReasonRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        row = lsvc.retire_policy(
            db, policy_key, organization.id, opa_url=_opa_url(), actor=body.actor, reason=body.reason
        )
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _row_to_summary(row, db)


@router.post(
    "/{policy_key}/lifecycle/deprecate", response_model=PolicyLifecycleSummary,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_PUBLISH))],
)
def deprecate(
    policy_key: uuid.UUID,
    body: ActorReasonRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        row = lsvc.deprecate_policy(db, policy_key, organization.id, actor=body.actor, reason=body.reason)
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _row_to_summary(row, db)


@router.post(
    "/{policy_key}/lifecycle/attest", response_model=PolicyLifecycleSummary,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def attest(
    policy_key: uuid.UUID,
    body: AttestRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Authority Freshness (PAYREALITY_FUTURE_VISION.md Part B). Gated
    on Permission.AUTHORITY_REVIEW -- the same permission Approve/Reject
    already use -- rather than RUNTIME_POLICY_PUBLISH: re-attesting is a
    review action (confirming existing authority still reflects
    reality), not a publish action, and Role.REVIEWER holds
    AUTHORITY_REVIEW but not RUNTIME_POLICY_PUBLISH."""
    try:
        row = lsvc.attest_policy(
            db, policy_key, organization.id, actor=body.actor, reason=body.reason,
            review_cadence_days=body.review_cadence_days,
        )
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _row_to_summary(row, db)


@router.post(
    "/{policy_key}/lifecycle/archive", response_model=PolicyLifecycleSummary,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_PUBLISH))],
)
def archive(
    policy_key: uuid.UUID,
    body: ActorReasonRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        row = lsvc.archive_policy(db, policy_key, organization.id, actor=body.actor, reason=body.reason)
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _row_to_summary(row, db)


@router.post(
    "/{policy_key}/lifecycle/rollback", response_model=PolicyLifecycleSummary,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_PUBLISH))],
)
def rollback(
    policy_key: uuid.UUID,
    body: RollbackRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        row = lsvc.rollback_policy(
            db, policy_key, organization.id, body.target_version, actor=body.actor, reason=body.reason
        )
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _row_to_summary(row, db)


@router.post(
    "/{policy_key}/lifecycle/schedules/{schedule_id}/cancel", response_model=ScheduleSchema,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_PUBLISH))],
)
def cancel_schedule(
    policy_key: uuid.UUID,
    schedule_id: uuid.UUID,
    body: ActorReasonRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        schedule = lsvc.cancel_schedule(db, schedule_id, organization.id, actor=body.actor, reason=body.reason)
    except lsvc.ScheduleNotFoundError:
        raise HTTPException(status_code=404, detail="schedule_not_found")
    except InvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _schedule_to_schema(schedule)


# --- Read: preview, timeline, schedules ------------------------------------


@router.get(
    "/{policy_key}/lifecycle/activation-preview", response_model=ActivationImpactPreviewResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_VIEW))],
)
def activation_preview(
    policy_key: uuid.UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        preview = lsvc.preview_activation_impact(db, policy_key, organization.id)
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    return ActivationImpactPreviewResponse(
        policy_key=str(preview.policy_key), candidate_version=preview.candidate_version,
        current_active_version=preview.current_active_version,
        diff=_diff_to_schema(preview.diff) if preview.diff is not None else None,
        safety=_safety_to_schema(preview.safety),
    )


@router.get(
    "/{policy_key}/lifecycle/timeline", response_model=TimelineResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_VIEW))],
)
def timeline(
    policy_key: uuid.UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        events = lsvc.get_timeline(db, policy_key, organization.id)
    except RuntimePolicyNotFoundError:
        raise HTTPException(status_code=404, detail="runtime_policy_not_found")
    return TimelineResponse(policy_key=str(policy_key), events=[_event_to_schema(e) for e in events])


@router.get(
    "/{policy_key}/lifecycle/schedules", response_model=list[ScheduleSchema],
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_VIEW))],
)
def get_schedules(
    policy_key: uuid.UUID,
    status: str | None = None,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    schedules = lsvc.list_schedules(db, organization.id, policy_key=policy_key, status=status)
    return [_schedule_to_schema(s) for s in schedules]


# --- Cross-policy: dashboard, search, process-due-schedules ----------------


@dashboard_router.get(
    "/dashboard", response_model=DashboardResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_VIEW))],
)
def dashboard(organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)):
    summary = lsvc.get_dashboard(db, organization.id)
    return DashboardResponse(
        counts_by_state=summary.counts_by_state,
        pending_approvals=[_row_to_summary(r, db) for r in summary.pending_approvals],
        upcoming_activations=[_schedule_to_schema(s) for s in summary.upcoming_activations],
        upcoming_expirations=[_row_to_summary(r, db) for r in summary.upcoming_expirations],
        upcoming_retirements=[_schedule_to_schema(s) for s in summary.upcoming_retirement_schedules],
        recently_activated=[_row_to_summary(r, db) for r in summary.recently_activated],
        deprecated_policies=[_row_to_summary(r, db) for r in summary.deprecated_policies],
        rollback_history=[_row_to_summary(r, db) for r in summary.rollback_history],
        conflict_alerts=[
            ConflictAlertSchema(
                policy_key=a["policy_key"], version=a["version"],
                violations=[SafetyViolationSchema(check=v.check, message=v.message, details=v.details) for v in a["violations"]],
            )
            for a in summary.conflict_alerts
        ],
        due_for_reattestation=[_row_to_summary(r, db) for r in summary.due_for_reattestation],
    )


@dashboard_router.get(
    "/search", response_model=SearchResponse,
    dependencies=[Depends(require_permission(Permission.RUNTIME_POLICY_VIEW))],
)
def search(
    principal: str | None = None, resource: str | None = None, action: str | None = None,
    state: str | None = None, version: int | None = None, reviewer: str | None = None,
    created_after: datetime | None = None, created_before: datetime | None = None,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    filters = lsvc.PolicySearchFilters(
        principal=principal, resource=resource, action=action, state=state, version=version,
        reviewer=reviewer, created_after=created_after, created_before=created_before,
    )
    rows = lsvc.search_policies(db, organization.id, filters)
    return SearchResponse(results=[_row_to_summary(r, db) for r in rows])


@dashboard_router.post(
    "/process-due-schedules", response_model=ProcessSchedulesResponse,
    dependencies=[Depends(verify_operator_key)],
)
def process_due_schedules(db: Session = Depends(get_db)):
    """Manually (or externally, e.g. a cron job) triggered -- there is no
    background task runner in this platform, so nothing calls this on
    its own. See runtime_policy_lifecycle_service.process_due_schedules's
    own docstring.

    Milestone 3 (Enterprise Surface Isolation): this executes EVERY
    organization's due schedules in one pass, by design (each schedule
    row carries and uses its own organization_id internally -- see that
    function's docstring). That makes it a genuinely platform-wide
    operation, which `Permission.RUNTIME_POLICY_PUBLISH` does not
    correctly gate: it's held by the ordinary per-tenant Role.OWNER/
    Role.GOVERNANCE_ADMIN roles (confirmed in MULTI_TENANT_ARCHITECTURE_
    VERIFICATION.md), so any tenant's own admin could previously trigger
    activation/retirement of every OTHER tenant's due policy changes.
    Gated on `verify_operator_key` instead -- the pure Operator-Key-only
    check with no session/role fallback, already used nowhere else in
    this codebase but exactly the platform-admin-only primitive this
    endpoint needs (require_permission's operator-key branch doesn't fit:
    Role.OWNER holds every Permission via _ALL_PERMISSIONS, so no new
    Permission value could ever be operator-key-exclusive within that
    system)."""
    results = lsvc.process_due_schedules(db, opa_url=_opa_url())
    return ProcessSchedulesResponse(
        results=[
            ScheduleExecutionResultSchema(
                schedule_id=str(r.schedule_id), policy_key=str(r.policy_key), action=r.action, ok=r.ok, error=r.error
            )
            for r in results
        ]
    )
