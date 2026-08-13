"""Unit tests for services/runtime_policy_lifecycle_service.py.

Most of this module's functions (activate_policy, rollback_policy,
retire_policy, ...) are multi-step DB orchestration composed directly
from runtime_policy_service's own CRUD/transition functions -- exactly
the category of code this codebase has never unit-tested with a fake
session (test_runtime_policy_service_diff.py's docstring: "genuinely
requires a live database session and is verified against the real
deployed Postgres instance instead"). Faking that many sequential
get_latest/commit/refresh calls convincingly would test the fake, not
the behavior; per RUNTIME_POLICY_LIFECYCLE.md's own "known limitations,"
those functions are NOT unit-tested here and require a live database to
verify, consistent with compile_policy/deploy_policy already being in
that same, disclosed category.

What IS tested here: the genuinely pure or single-query logic --
effective_status's superseded/retired distinction, search_policies'
in-Python filtering, process_due_schedules' control flow (which
functions get called for which due schedules, and that a failure in one
doesn't abort the batch), and ActivationBlockedError's message
formatting.
"""

import uuid
from datetime import datetime, timezone

import app.services.runtime_policy_lifecycle_service as lsvc
from app.services.runtime_policy_lifecycle_service import (
    ActivationBlockedError,
    PolicySearchFilters,
    effective_status,
    search_policies,
)
from app.services.runtime_policy_safety_checks import SafetyViolation


class _FakeRow:
    def __init__(self, policy_key, version, status, content, created_at=None):
        self.policy_key = policy_key
        self.version = version
        self.status = status
        self.content = content
        self.created_at = created_at or datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeSchedule:
    def __init__(
        self, id, policy_key, action, status="pending", created_by=None, reason=None, effective_at=None,
        organization_id=None,
    ):
        self.id = id
        self.policy_key = policy_key
        self.version = 1
        self.action = action
        self.status = status
        self.created_by = created_by
        self.reason = reason
        self.effective_at = effective_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.executed_at = None
        self.execution_error = None
        self.organization_id = organization_id


class _FakeSession:
    def __init__(self, scalars_results=None, scalar_results=None):
        self._scalars_results = list(scalars_results or [])
        self._scalar_results = list(scalar_results or [])
        self.committed = 0
        self.rolled_back = 0

    def scalars(self, stmt):
        return self._scalars_results.pop(0) if self._scalars_results else []

    def scalar(self, stmt):
        return self._scalar_results.pop(0) if self._scalar_results else None

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1


def _content(principal="p1", action="pay", resource=None):
    return {"name": "Test Policy", "scope": {"principal": principal, "action": action, "resource": resource, "agent": None}, "audit": {}}


# --- effective_status --------------------------------------------------------


def test_effective_status_passes_through_non_retired_statuses():
    row = _FakeRow(uuid.uuid4(), 1, "active", _content())
    assert effective_status(_FakeSession(), row) == "active"


def test_effective_status_is_superseded_when_a_newer_active_sibling_exists():
    key = uuid.uuid4()
    row = _FakeRow(key, 1, "retired", _content())
    db = _FakeSession(scalar_results=[_FakeRow(key, 2, "active", _content())])
    assert effective_status(db, row) == "superseded"


def test_effective_status_is_plain_retired_with_no_newer_sibling():
    row = _FakeRow(uuid.uuid4(), 1, "retired", _content())
    db = _FakeSession(scalar_results=[None])
    assert effective_status(db, row) == "retired"


# --- search_policies ----------------------------------------------------------


def test_search_filters_by_principal_case_insensitively():
    rows = [_FakeRow(uuid.uuid4(), 1, "active", _content(principal="Regional Controller"))]
    db = _FakeSession(scalars_results=[rows])
    result = search_policies(db, None, PolicySearchFilters(principal="regional"))
    assert len(result) == 1


def test_search_excludes_non_matching_principal():
    rows = [_FakeRow(uuid.uuid4(), 1, "active", _content(principal="Regional Controller"))]
    db = _FakeSession(scalars_results=[rows])
    result = search_policies(db, None, PolicySearchFilters(principal="nobody"))
    assert result == []


def test_search_filters_by_version():
    key = uuid.uuid4()
    rows = [_FakeRow(key, 1, "draft", _content()), _FakeRow(key, 2, "active", _content())]
    db = _FakeSession(scalars_results=[rows])
    result = search_policies(db, None, PolicySearchFilters(version=2))
    assert [r.version for r in result] == [2]


def test_search_filters_by_state_using_effective_status(monkeypatch):
    """state="superseded" must reach effective_status, not row.status
    directly -- a retired row with a newer active sibling should match a
    search for "superseded" even though its stored status is "retired"."""
    row = _FakeRow(uuid.uuid4(), 1, "retired", _content())
    db = _FakeSession(scalars_results=[[row]])
    monkeypatch.setattr(lsvc, "effective_status", lambda db, r: "superseded")
    result = search_policies(db, None, PolicySearchFilters(state="superseded"))
    assert result == [row]


# --- process_due_schedules control flow ---------------------------------------


def test_process_due_schedules_executes_activate_action(monkeypatch):
    schedule = _FakeSchedule(uuid.uuid4(), uuid.uuid4(), action="activate", created_by="alice")
    db = _FakeSession(scalars_results=[[schedule]])
    called = {}
    monkeypatch.setattr(
        lsvc, "activate_policy",
        lambda db, key, organization_id, opa_url, actor, reason: called.setdefault("activate", (key, actor, reason)),
    )
    results = lsvc.process_due_schedules(db, opa_url="http://opa", now=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert called["activate"] == (schedule.policy_key, "alice", None)
    assert schedule.status == "executed"
    assert results[0].ok is True


def test_process_due_schedules_executes_retire_action(monkeypatch):
    schedule = _FakeSchedule(uuid.uuid4(), uuid.uuid4(), action="retire", created_by="bob")
    db = _FakeSession(scalars_results=[[schedule]])
    called = {}
    monkeypatch.setattr(
        lsvc, "retire_policy",
        lambda db, key, organization_id, opa_url, actor, reason: called.setdefault("retire", (key, actor)),
    )
    lsvc.process_due_schedules(db, opa_url="http://opa", now=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert called["retire"] == (schedule.policy_key, "bob")
    assert schedule.status == "executed"


def test_process_due_schedules_marks_failure_without_aborting_the_batch(monkeypatch):
    ok_schedule = _FakeSchedule(uuid.uuid4(), uuid.uuid4(), action="activate", created_by="alice")
    bad_schedule = _FakeSchedule(uuid.uuid4(), uuid.uuid4(), action="retire", created_by="bob")
    db = _FakeSession(scalars_results=[[bad_schedule, ok_schedule]])

    def _fake_retire(db, key, organization_id, opa_url, actor, reason):
        raise RuntimeError("boom")

    monkeypatch.setattr(lsvc, "retire_policy", _fake_retire)
    monkeypatch.setattr(lsvc, "activate_policy", lambda db, key, organization_id, opa_url, actor, reason: None)
    results = lsvc.process_due_schedules(db, opa_url="http://opa", now=datetime(2026, 1, 2, tzinfo=timezone.utc))

    by_id = {r.schedule_id: r for r in results}
    assert by_id[bad_schedule.id].ok is False
    assert "boom" in by_id[bad_schedule.id].error
    assert bad_schedule.status == "failed"
    assert by_id[ok_schedule.id].ok is True
    assert ok_schedule.status == "executed"
    assert db.rolled_back == 1


# --- ActivationBlockedError ----------------------------------------------------


def test_activation_blocked_error_message_lists_distinct_checks():
    violations = (
        SafetyViolation(check="duplicate_authority", message="m1"),
        SafetyViolation(check="circular_delegation", message="m2"),
        SafetyViolation(check="duplicate_authority", message="m3"),
    )
    error = ActivationBlockedError(violations)
    assert "circular_delegation" in str(error)
    assert "duplicate_authority" in str(error)
    assert error.violations == violations
