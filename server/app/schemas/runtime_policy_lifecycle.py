from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.runtime_policy import DiffResponse, ScopeSchema


class ActivateRequest(BaseModel):
    actor: str
    reason: str | None = None


class ScheduleActivateRequest(BaseModel):
    effective_at: datetime
    actor: str
    reason: str | None = None


class ScheduleRetireRequest(BaseModel):
    effective_at: datetime
    actor: str
    reason: str | None = None


class ActorReasonRequest(BaseModel):
    """Shared shape for the simple actor+optional-reason actions: cancel
    schedule, retire, deprecate, archive."""

    actor: str
    reason: str | None = None


class RollbackRequest(BaseModel):
    target_version: int
    actor: str
    reason: str | None = None


class SafetyViolationSchema(BaseModel):
    check: str
    message: str
    details: dict[str, Any] = {}


class SafetyCheckResultSchema(BaseModel):
    ok: bool
    violations: list[SafetyViolationSchema]


class ActivationImpactPreviewResponse(BaseModel):
    policy_key: str
    candidate_version: int
    current_active_version: int | None
    diff: DiffResponse | None
    safety: SafetyCheckResultSchema


class LifecycleEventSchema(BaseModel):
    id: str
    policy_key: str
    version: int
    event_type: str
    actor: str | None
    reason: str | None
    payload: dict[str, Any]
    event_hash: str
    occurred_at: datetime


class TimelineResponse(BaseModel):
    policy_key: str
    events: list[LifecycleEventSchema]


class ScheduleSchema(BaseModel):
    id: str
    policy_key: str
    version: int
    action: str
    effective_at: datetime
    reason: str | None
    status: str
    created_by: str | None
    created_at: datetime
    executed_at: datetime | None
    execution_error: str | None


class ScheduleExecutionResultSchema(BaseModel):
    schedule_id: str
    policy_key: str
    action: str
    ok: bool
    error: str | None


class ProcessSchedulesResponse(BaseModel):
    results: list[ScheduleExecutionResultSchema]


class PolicyLifecycleSummary(BaseModel):
    """A search/dashboard row: enough to identify and triage a policy
    version without the full RuntimePolicyResponse shape. `effective_status`
    is the read-side label (e.g. "superseded") layered on top of the
    stored `status` -- see runtime_policy_lifecycle_service.effective_status."""

    policy_key: str
    version: int
    name: str
    status: str
    effective_status: str
    scope: ScopeSchema
    created_at: datetime
    activated_by: str | None = None
    activated_at: datetime | None = None
    activation_reason: str | None = None
    effective_from: datetime | None = None
    effective_until: datetime | None = None
    deprecated_at: datetime | None = None
    deprecation_reason: str | None = None
    rollback_of_version: int | None = None


class ConflictAlertSchema(BaseModel):
    policy_key: str
    version: int
    violations: list[SafetyViolationSchema]


class DashboardResponse(BaseModel):
    counts_by_state: dict[str, int]
    pending_approvals: list[PolicyLifecycleSummary]
    upcoming_activations: list[ScheduleSchema]
    upcoming_expirations: list[PolicyLifecycleSummary]
    upcoming_retirements: list[ScheduleSchema]
    recently_activated: list[PolicyLifecycleSummary]
    deprecated_policies: list[PolicyLifecycleSummary]
    rollback_history: list[PolicyLifecycleSummary]
    conflict_alerts: list[ConflictAlertSchema]


class SearchResponse(BaseModel):
    results: list[PolicyLifecycleSummary]
