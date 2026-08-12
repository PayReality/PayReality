"""Runtime Policy Lifecycle & Enterprise Runtime Management (Phase 5,
RUNTIME_POLICY_LIFECYCLE.md): governs Runtime Policies as versioned,
reviewed, activatable enterprise assets, comparable to a GitHub Pull
Request or a Terraform Plan.

Every function here composes `services/runtime_policy_service.py`'s
existing, UNMODIFIED functions (create_policy, edit_policy,
submit_for_review, approve, reject, compile_policy, deploy_policy,
diff_versions, reconcile_opa_with_active_policies) rather than
re-implementing any of their logic -- the explicit instruction from the
Phase 5 prompt ("Do NOT redesign existing architecture... Reuse existing
validation. Never duplicate logic.") is a hard constraint on this
module's design, not just a style preference. The one genuinely new state
transition this module adds that `runtime_policy_service` has no
equivalent for is `retire_policy` (retiring an ACTIVE policy WITHOUT a
superseding version) -- everything else is a thin, audited wrapper.

`services/runtime_policy_safety_checks.py` gates every activation
(immediate or scheduled): a policy that would introduce a circular
delegation, a duplicate authority, a broken inheritance chain, an invalid
threshold, or a missing principal is refused, and the refusal itself is
recorded as an `activation_blocked` lifecycle event.
"""

import dataclasses
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PolicyActivationSchedule, RuntimePolicyLifecycleEvent, RuntimePolicyRecord
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus
from app.domain.runtime_policy.schema import from_dict
from app.services.runtime_policy_safety_checks import SafetyCheckResult, run_safety_checks
from app.services import runtime_policy_service as svc
from app.services.runtime_policy_lifecycle_events import record_lifecycle_event

_ACTIVATABLE_STATUSES = ("approved", "compiled")


class ActivationBlockedError(Exception):
    """Raised by activate_policy/schedule_activation when
    run_safety_checks reports at least one violation. The candidate
    version is left exactly as it was -- never compiled, never deployed --
    and an `activation_blocked` lifecycle event is written before this is
    raised, so a blocked attempt is itself part of the audit trail."""

    def __init__(self, violations: tuple):
        self.violations = violations
        super().__init__(
            "activation blocked by " + ", ".join(sorted({v.check for v in violations})) + " safety check(s)"
        )


class ScheduleNotFoundError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _record_blocked(db: Session, policy_key: uuid.UUID, version: int, actor: str | None, safety: SafetyCheckResult) -> None:
    record_lifecycle_event(
        db, policy_key, version, "activation_blocked", actor=actor,
        payload={"violations": [{"check": v.check, "message": v.message, "details": v.details} for v in safety.violations]},
    )


# --- Activation (immediate) --------------------------------------------


def activate_policy(
    db: Session, policy_key: uuid.UUID, opa_url: str, actor: str, reason: str | None = None
) -> RuntimePolicyRecord:
    """Immediate activation. Reuses compile_policy (only if the candidate
    hasn't been compiled yet) and deploy_policy unchanged; adds only the
    safety gate and the richer, actor-aware activation metadata
    deploy_policy itself has no parameters for."""
    row = svc.get_latest(db, policy_key)
    if row.status not in _ACTIVATABLE_STATUSES:
        raise svc.InvalidTransitionError(row.status, "activate")

    safety = run_safety_checks(db, policy_key, row)
    if not safety.ok:
        _record_blocked(db, policy_key, row.version, actor, safety)
        raise ActivationBlockedError(safety.violations)

    if row.status == "approved":
        outcome = svc.compile_policy(db, policy_key)
        if not outcome.ok:
            raise svc.CompilationRequiredError(
                f"{policy_key} v{row.version} failed to compile: "
                + "; ".join(e.message for e in outcome.diagnostics.errors)
            )

    svc.deploy_policy(db, policy_key, opa_url=opa_url)

    row = svc.get_latest(db, policy_key)
    row.activated_by = actor
    row.activated_at = _now()
    row.activation_reason = reason
    db.commit()
    db.refresh(row)
    record_lifecycle_event(
        db, policy_key, row.version, "activated", actor=actor, reason=reason,
        payload={"bundle_hash": row.bundle_hash},
    )
    return row


# --- Scheduling ----------------------------------------------------------


def schedule_activation(
    db: Session, policy_key: uuid.UUID, effective_at: datetime, actor: str, reason: str | None = None
) -> PolicyActivationSchedule:
    """Records a future activation; nothing activates now. Safety checks
    run at schedule time as an early warning, and are re-run at execution
    time by process_due_schedules (state may have drifted between now and
    then -- e.g. another policy could have taken the same authority in
    the interim), so a schedule passing this check is not a guarantee its
    later execution will."""
    row = svc.get_latest(db, policy_key)
    if row.status not in _ACTIVATABLE_STATUSES:
        raise svc.InvalidTransitionError(row.status, "schedule activation")

    safety = run_safety_checks(db, policy_key, row)
    if not safety.ok:
        _record_blocked(db, policy_key, row.version, actor, safety)
        raise ActivationBlockedError(safety.violations)

    schedule = PolicyActivationSchedule(
        id=uuid.uuid4(), policy_key=policy_key, version=row.version, action="activate",
        effective_at=effective_at, reason=reason, created_by=actor,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    record_lifecycle_event(
        db, policy_key, row.version, "scheduled", actor=actor, reason=reason,
        payload={"action": "activate", "effective_at": effective_at.isoformat(), "schedule_id": str(schedule.id)},
    )
    return schedule


def schedule_retirement(
    db: Session, policy_key: uuid.UUID, effective_at: datetime, actor: str, reason: str | None = None
) -> PolicyActivationSchedule:
    row = svc.get_latest(db, policy_key)
    if row.status != "active":
        raise svc.InvalidTransitionError(row.status, "schedule retirement")

    schedule = PolicyActivationSchedule(
        id=uuid.uuid4(), policy_key=policy_key, version=row.version, action="retire",
        effective_at=effective_at, reason=reason, created_by=actor,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    record_lifecycle_event(
        db, policy_key, row.version, "scheduled", actor=actor, reason=reason,
        payload={"action": "retire", "effective_at": effective_at.isoformat(), "schedule_id": str(schedule.id)},
    )
    return schedule


def cancel_schedule(db: Session, schedule_id: uuid.UUID, actor: str, reason: str | None = None) -> PolicyActivationSchedule:
    schedule = db.get(PolicyActivationSchedule, schedule_id)
    if schedule is None:
        raise ScheduleNotFoundError(str(schedule_id))
    if schedule.status != "pending":
        raise svc.InvalidTransitionError(schedule.status, "cancel")
    schedule.status = "cancelled"
    db.commit()
    db.refresh(schedule)
    record_lifecycle_event(
        db, schedule.policy_key, schedule.version, "schedule_cancelled", actor=actor, reason=reason,
        payload={"schedule_id": str(schedule.id), "action": schedule.action},
    )
    return schedule


@dataclass(frozen=True)
class ScheduleExecutionResult:
    schedule_id: uuid.UUID
    policy_key: uuid.UUID
    action: str
    ok: bool
    error: str | None = None


def process_due_schedules(
    db: Session, opa_url: str, now: datetime | None = None
) -> list[ScheduleExecutionResult]:
    """NOT a background job -- there is no task runner anywhere in this
    platform (confirmed during Phase 5's research pass). This function
    must be invoked manually or by an external trigger (a cron job, a CI
    step, an operator action); nothing in this codebase calls it on its
    own. Every due, still-pending schedule is attempted in effective_at
    order; a failure marks that schedule 'failed' with its error and
    leaves every other due schedule to be attempted independently rather
    than aborting the whole batch."""
    now = now or _now()
    due = list(
        db.scalars(
            select(PolicyActivationSchedule)
            .where(PolicyActivationSchedule.status == "pending", PolicyActivationSchedule.effective_at <= now)
            .order_by(PolicyActivationSchedule.effective_at)
        )
    )
    results: list[ScheduleExecutionResult] = []
    for schedule in due:
        actor = schedule.created_by or "scheduled-execution"
        try:
            if schedule.action == "activate":
                activate_policy(db, schedule.policy_key, opa_url, actor=actor, reason=schedule.reason)
            else:
                retire_policy(db, schedule.policy_key, opa_url, actor=actor, reason=schedule.reason)
            schedule.status = "executed"
            schedule.executed_at = _now()
            db.commit()
            results.append(ScheduleExecutionResult(schedule.id, schedule.policy_key, schedule.action, ok=True))
        except Exception as e:
            db.rollback()
            schedule.status = "failed"
            schedule.execution_error = str(e)
            db.commit()
            results.append(ScheduleExecutionResult(schedule.id, schedule.policy_key, schedule.action, ok=False, error=str(e)))
    return results


# --- Retirement (no superseding version) --------------------------------


def retire_policy(db: Session, policy_key: uuid.UUID, opa_url: str, actor: str, reason: str | None = None) -> RuntimePolicyRecord:
    """The one transition `runtime_policy_service` has no equivalent for:
    deploy_policy only ever retires the PRIOR version of the SAME
    policy_key when a NEW version of that key activates. This retires the
    current active version with no replacement, then reuses
    reconcile_opa_with_active_policies (unchanged) to push the remaining
    active set to OPA -- never re-implementing bundle compilation here."""
    row = svc.get_latest(db, policy_key)
    if row.status != "active":
        raise svc.InvalidTransitionError(row.status, "retire")

    row.status = "retired"
    db.commit()
    db.refresh(row)
    svc.reconcile_opa_with_active_policies(db, opa_url=opa_url)
    record_lifecycle_event(db, policy_key, row.version, "retired", actor=actor, reason=reason)
    return row


def deprecate_policy(db: Session, policy_key: uuid.UUID, actor: str, reason: str | None = None) -> RuntimePolicyRecord:
    """A label on the ACTIVE row, never a status change -- see
    PolicyStatus.ARCHIVED's docstring for why: a deprecated-but-not-yet-
    retired policy must keep being enforced until its scheduled
    retirement actually runs."""
    row = svc.get_latest(db, policy_key)
    if row.status != "active":
        raise svc.InvalidTransitionError(row.status, "deprecate")
    row.deprecated_at = _now()
    row.deprecation_reason = reason
    db.commit()
    db.refresh(row)
    record_lifecycle_event(db, policy_key, row.version, "deprecated", actor=actor, reason=reason)
    return row


def archive_policy(db: Session, policy_key: uuid.UUID, actor: str, reason: str | None = None) -> RuntimePolicyRecord:
    row = svc.get_latest(db, policy_key)
    if row.status == "active":
        raise svc.InvalidTransitionError(row.status, "archive (retire it first)")
    if row.status == "archived":
        raise svc.InvalidTransitionError(row.status, "archive")
    row.status = "archived"
    db.commit()
    db.refresh(row)
    record_lifecycle_event(db, policy_key, row.version, "archived", actor=actor, reason=reason)
    return row


# --- Rollback -------------------------------------------------------------


def rollback_policy(
    db: Session, policy_key: uuid.UUID, target_version: int, actor: str, reason: str | None = None
) -> RuntimePolicyRecord:
    """Reverting to any previous ACTIVE version, per RUNTIME_POLICY_
    LIFECYCLE.md section 4: creates a new DRAFT version whose content is
    byte-identical to `target_version`'s, tagged with
    rollback_of_version. This deliberately does NOT skip the review
    pipeline -- "never reactivate historical records directly" is read
    literally here: the new version must still go through submit /
    approve / compile / activate like any other change, reusing that
    existing pipeline rather than a shortcut that bypasses approval."""
    target_row = svc.get_version(db, policy_key, target_version)
    if target_row.activated_at is None and target_row.status not in ("active",):
        raise svc.InvalidTransitionError(target_row.status, "rollback to a version that was never activated")

    latest = svc.get_latest(db, policy_key)
    if latest.status == "archived":
        raise svc.InvalidTransitionError(latest.status, "rollback")

    target_policy = from_dict(target_row.content)
    now = _now()
    audit = AuditTrail(
        created=target_policy.audit.created if target_policy.audit else now,
        modified=now,
    )
    reverted_policy = dataclasses.replace(
        target_policy, version=latest.version + 1, status=PolicyStatus.DRAFT, audit=audit
    )
    new_row = svc.edit_policy(db, policy_key, reverted_policy)
    new_row.rollback_of_version = target_version
    db.commit()
    db.refresh(new_row)
    record_lifecycle_event(
        db, policy_key, new_row.version, "rolled_back", actor=actor, reason=reason,
        payload={"target_version": target_version},
    )
    return new_row


# --- Runtime Impact Preview ----------------------------------------------


@dataclass(frozen=True)
class ActivationImpactPreview:
    policy_key: uuid.UUID
    candidate_version: int
    current_active_version: int | None
    diff: object | None  # svc.PolicyDiff, or None on a policy's first-ever activation
    safety: SafetyCheckResult


def preview_activation_impact(db: Session, policy_key: uuid.UUID) -> ActivationImpactPreview:
    """Before activation: how this candidate differs from whatever is
    currently active (reusing svc.diff_versions/compute_condition_diff
    unchanged), plus the same safety checks activation itself will run,
    so a reviewer sees potential conflicts before committing to
    activating. Reuses the existing Diff engine exactly as instructed --
    no separate impact-computation logic exists here."""
    candidate = svc.get_latest(db, policy_key)
    safety = run_safety_checks(db, policy_key, candidate)

    current_active = db.scalar(
        select(RuntimePolicyRecord).where(
            RuntimePolicyRecord.policy_key == policy_key, RuntimePolicyRecord.status == "active"
        )
    )
    diff = None
    if current_active is not None and current_active.version != candidate.version:
        diff = svc.diff_versions(db, policy_key, current_active.version, candidate.version)

    return ActivationImpactPreview(
        policy_key=policy_key,
        candidate_version=candidate.version,
        current_active_version=current_active.version if current_active is not None else None,
        diff=diff,
        safety=safety,
    )


# --- Timeline, effective status, search, dashboard ------------------------


def get_timeline(db: Session, policy_key: uuid.UUID) -> list[RuntimePolicyLifecycleEvent]:
    return list(
        db.scalars(
            select(RuntimePolicyLifecycleEvent)
            .where(RuntimePolicyLifecycleEvent.policy_key == policy_key)
            .order_by(RuntimePolicyLifecycleEvent.occurred_at)
        )
    )


def list_schedules(
    db: Session, policy_key: uuid.UUID | None = None, status: str | None = None
) -> list[PolicyActivationSchedule]:
    stmt = select(PolicyActivationSchedule)
    if policy_key is not None:
        stmt = stmt.where(PolicyActivationSchedule.policy_key == policy_key)
    if status is not None:
        stmt = stmt.where(PolicyActivationSchedule.status == status)
    return list(db.scalars(stmt.order_by(PolicyActivationSchedule.effective_at)))


def effective_status(db: Session, row: RuntimePolicyRecord) -> str:
    """'archived' is the only new stored status; 'superseded' is a
    read-side label, not a status: a 'retired' row with a newer ACTIVE
    sibling of the same policy_key is superseded by that sibling, a
    'retired' row with no such sibling (e.g. explicitly retire_policy'd
    with nothing to replace it) is just 'retired'."""
    if row.status != "retired":
        return row.status
    newer_active = db.scalar(
        select(RuntimePolicyRecord).where(
            RuntimePolicyRecord.policy_key == row.policy_key,
            RuntimePolicyRecord.status == "active",
            RuntimePolicyRecord.version > row.version,
        )
    )
    return "superseded" if newer_active is not None else "retired"


@dataclass(frozen=True)
class PolicySearchFilters:
    principal: str | None = None
    resource: str | None = None
    action: str | None = None
    state: str | None = None
    version: int | None = None
    reviewer: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None


def search_policies(db: Session, filters: PolicySearchFilters) -> list[RuntimePolicyRecord]:
    """In-Python filtering over every version's JSONB `content`, not a
    real database-level search -- `content` is stored as a single JSONB
    blob keyed by RuntimePolicy's own shape, and this codebase has no
    existing JSONB-query helper to reuse (list_policies_for_principal
    already does the exact same "load rows, filter in Python" thing for
    the one field it filters on). Fine at this platform's current scale;
    a real search index is future work if/when it isn't, and this is
    disclosed as a known limitation, not claimed as a scalable solution.
    """
    rows = list(db.scalars(select(RuntimePolicyRecord).order_by(RuntimePolicyRecord.policy_key, RuntimePolicyRecord.version)))
    if filters.version is not None:
        rows = [r for r in rows if r.version == filters.version]

    results = []
    for row in rows:
        content = row.content
        scope = content.get("scope") or {}
        if filters.principal and filters.principal.lower() not in (scope.get("principal") or "").lower():
            continue
        if filters.resource and filters.resource.lower() not in (scope.get("resource") or "").lower():
            continue
        if filters.action and filters.action.lower() not in (scope.get("action") or "").lower():
            continue
        if filters.state and effective_status(db, row) != filters.state:
            continue
        if filters.reviewer:
            audit = content.get("audit") or {}
            reviewer_fields = " ".join(
                filter(None, [audit.get("approved_by"), audit.get("rejected_by")])
            ).lower()
            if filters.reviewer.lower() not in reviewer_fields:
                continue
        if filters.created_after and row.created_at < filters.created_after:
            continue
        if filters.created_before and row.created_at > filters.created_before:
            continue
        results.append(row)
    return results


@dataclass(frozen=True)
class DashboardSummary:
    counts_by_state: dict = field(default_factory=dict)
    pending_approvals: list = field(default_factory=list)
    upcoming_activations: list = field(default_factory=list)
    # Two distinct shapes of "expiring soon", kept separate rather than
    # mixed into one list: an ACTIVE row with effective_until set (an
    # expiry date recorded directly on the policy at activation time) vs.
    # a pending 'retire' PolicyActivationSchedule row (a retirement
    # scheduled separately, after the fact). A UI can render each with
    # its own shape without type-sniffing a mixed list.
    upcoming_expirations: list = field(default_factory=list)
    upcoming_retirement_schedules: list = field(default_factory=list)
    recently_activated: list = field(default_factory=list)
    deprecated_policies: list = field(default_factory=list)
    rollback_history: list = field(default_factory=list)
    conflict_alerts: list = field(default_factory=list)


def get_dashboard(db: Session) -> DashboardSummary:
    latest_rows = svc.list_latest_policies(db)

    counts_by_state: dict[str, int] = {}
    for row in latest_rows:
        label = effective_status(db, row)
        counts_by_state[label] = counts_by_state.get(label, 0) + 1

    pending_approvals = [r for r in latest_rows if r.status == "pending_review"]

    pending_schedules = list_schedules(db, status="pending")
    upcoming_activations = [s for s in pending_schedules if s.action == "activate"]
    upcoming_retirement_schedules = [s for s in pending_schedules if s.action == "retire"]
    upcoming_expirations = [r for r in latest_rows if r.status == "active" and r.effective_until is not None]

    recently_activated = sorted(
        (r for r in latest_rows if r.activated_at is not None),
        key=lambda r: r.activated_at, reverse=True,
    )[:10]

    deprecated_policies = [r for r in latest_rows if r.status == "active" and r.deprecated_at is not None]

    all_rows = list(db.scalars(select(RuntimePolicyRecord)))
    rollback_history = [r for r in all_rows if r.rollback_of_version is not None]

    conflict_alerts = []
    for row in latest_rows:
        if row.status not in ("approved", "compiled"):
            continue
        safety = run_safety_checks(db, row.policy_key, row)
        if not safety.ok:
            conflict_alerts.append({"policy_key": str(row.policy_key), "version": row.version, "violations": safety.violations})

    return DashboardSummary(
        counts_by_state=counts_by_state,
        pending_approvals=pending_approvals,
        upcoming_activations=upcoming_activations,
        upcoming_expirations=upcoming_expirations,
        upcoming_retirement_schedules=upcoming_retirement_schedules,
        recently_activated=recently_activated,
        deprecated_policies=deprecated_policies,
        rollback_history=rollback_history,
        conflict_alerts=conflict_alerts,
    )
