"""Unit tests for services/runtime_policy_safety_checks.py (Phase 5,
RUNTIME_POLICY_LIFECYCLE.md section 6). This codebase has no DB-backed
unit-test fixture anywhere (test_policy_compilation_ordering.py,
test_enterprise_system_resolution.py) -- these tests follow the same
established convention: a minimal fake Session that answers
scalar/scalars/get with pre-wired results, never touching a real
database, verified against the actual SQL statements only where that's
what the behavior under test is (this module cares about the *results*
of those calls, not the statements, so plain queues are enough).
"""

import uuid

from app.domain.ai_authority_builder.provider import CandidateConflict
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.constraints import Constraints
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import Metadata
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.domain.runtime_policy.schema import to_dict
from app.services.runtime_policy_safety_checks import (
    _check_broken_inheritance,
    _check_circular_delegation,
    _check_duplicate_authority,
    _check_invalid_thresholds,
    _check_missing_principal,
    run_safety_checks,
)


class _FakeRow:
    def __init__(self, policy_key, policy):
        self.policy_key = policy_key
        self.content = to_dict(policy)


class _FakeSession:
    def __init__(self, scalars_results=None, scalar_results=None, get_results=None):
        self._scalars_results = list(scalars_results or [])
        self._scalar_results = list(scalar_results or [])
        self._get_results = dict(get_results or {})

    def scalars(self, stmt):
        return self._scalars_results.pop(0) if self._scalars_results else []

    def scalar(self, stmt):
        return self._scalar_results.pop(0) if self._scalar_results else None

    def get(self, model, id):
        return self._get_results.get(str(id))


def _policy(**overrides) -> RuntimePolicy:
    defaults = dict(
        id="rp-1",
        name="Vendor Payment Limit",
        version=1,
        status=PolicyStatus.APPROVED,
        scope=Scope(principal="Regional Controller", action="vendor_payment"),
        conditions=ConditionSet(all=()),
        effect=Effect.ALLOW,
        constraints=Constraints(),
        metadata=Metadata(),
    )
    defaults.update(overrides)
    return RuntimePolicy(**defaults)


# --- duplicate authority ---------------------------------------------------


def test_duplicate_authority_detected_for_identical_signature():
    candidate = _policy()
    other_key = uuid.uuid4()
    others = [(other_key, _policy())]
    violations = _check_duplicate_authority(candidate, uuid.uuid4(), others)
    assert len(violations) == 1
    assert violations[0].check == "duplicate_authority"
    assert violations[0].details["conflicting_policy_key"] == str(other_key)


def test_duplicate_authority_not_flagged_when_conditions_differ():
    """Two legitimate tiers of the same authority (e.g. under/over $50k)
    differ in their conditions and must not be flagged as duplicates."""
    candidate = _policy(conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value=50000),)))
    other = _policy(conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.GT, value=50000),)))
    violations = _check_duplicate_authority(candidate, uuid.uuid4(), [(uuid.uuid4(), other)])
    assert violations == []


def test_duplicate_authority_not_flagged_for_different_principal():
    candidate = _policy(scope=Scope(principal="A", action="vendor_payment"))
    other = _policy(scope=Scope(principal="B", action="vendor_payment"))
    assert _check_duplicate_authority(candidate, uuid.uuid4(), [(uuid.uuid4(), other)]) == []


# --- circular delegation (reused from ai_authority_builder_service) -------


def test_circular_delegation_reused_via_delegated_by_chain():
    a = _policy(scope=Scope(principal="a", action="x"), constraints=Constraints(delegated_by="c"))
    b = _policy(scope=Scope(principal="b", action="x"), constraints=Constraints(delegated_by="a"))
    c = _policy(scope=Scope(principal="c", action="x"), constraints=Constraints(delegated_by="b"))
    violations = _check_circular_delegation([a, b, c])
    assert len(violations) == 1
    assert violations[0].check == "circular_delegation"


def test_no_circular_delegation_in_a_normal_hierarchy():
    manager = _policy(scope=Scope(principal="manager", action="x"), constraints=Constraints())
    analyst = _policy(scope=Scope(principal="analyst", action="x"), constraints=Constraints(delegated_by="manager"))
    assert _check_circular_delegation([manager, analyst]) == []


def test_circular_delegation_returns_conflict_objects_from_the_reused_function(monkeypatch):
    """Confirms detect_circular_delegations itself is called (not
    reimplemented): monkeypatching it to return a canned conflict must be
    reflected verbatim in the safety violation's message."""
    import app.services.runtime_policy_safety_checks as mod

    monkeypatch.setattr(
        mod, "detect_circular_delegations",
        lambda graph: [CandidateConflict(description="fake cycle", confidence=1.0, reasoning="test", conflict_type="circular_delegation")],
    )
    a = _policy(scope=Scope(principal="a", action="x"), constraints=Constraints(delegated_by="b"))
    violations = _check_circular_delegation([a])
    assert violations[0].message == "fake cycle"


# --- invalid thresholds (reused from runtime_policy.validators) ------------


def test_invalid_threshold_flagged_for_wrong_value_type():
    bad = _policy(conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value="not-a-number"),)))
    violations = _check_invalid_thresholds(bad)
    assert any(v.check == "invalid_threshold" for v in violations)


def test_no_invalid_threshold_for_a_well_formed_policy():
    good = _policy(conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value=50000),)))
    assert _check_invalid_thresholds(good) == []


# --- missing principal ------------------------------------------------------


def test_missing_principal_skipped_for_non_uuid_principal():
    """Manually-authored policies name their principal as free text; this
    cannot be verified against a real entity, the same tolerance
    diff_versions/resolve_mandate_ids already apply to this exact field."""
    candidate = _policy(scope=Scope(principal="Regional Controller", action="x"))
    db = _FakeSession()  # never touched
    assert _check_missing_principal(db, candidate) == []


def test_missing_principal_flagged_when_uuid_does_not_resolve():
    principal_id = str(uuid.uuid4())
    candidate = _policy(scope=Scope(principal=principal_id, action="x"))
    db = _FakeSession(get_results={})
    violations = _check_missing_principal(db, candidate)
    assert len(violations) == 1
    assert violations[0].check == "missing_principal"


def test_missing_principal_not_flagged_when_uuid_resolves():
    principal_id = uuid.uuid4()
    candidate = _policy(scope=Scope(principal=str(principal_id), action="x"))
    db = _FakeSession(get_results={str(principal_id): object()})
    assert _check_missing_principal(db, candidate) == []


# --- broken inheritance ------------------------------------------------------


def test_broken_inheritance_resolved_via_sibling_active_policy_without_touching_db():
    candidate = _policy(scope=Scope(principal="analyst", action="x"), constraints=Constraints(delegated_by="manager"))
    sibling = _policy(scope=Scope(principal="manager", action="y"))
    db = _FakeSession()  # asserts nothing is ever queried
    assert _check_broken_inheritance(db, candidate, [candidate, sibling]) == []


def test_broken_inheritance_flagged_when_delegated_by_resolves_nowhere():
    candidate = _policy(scope=Scope(principal="analyst", action="x"), constraints=Constraints(delegated_by="nobody"))
    db = _FakeSession(scalar_results=[None])
    violations = _check_broken_inheritance(db, candidate, [candidate])
    assert len(violations) == 1
    assert violations[0].check == "broken_inheritance"


def test_broken_inheritance_not_flagged_when_no_delegation_declared():
    candidate = _policy(constraints=Constraints(delegated_by=None))
    db = _FakeSession()
    assert _check_broken_inheritance(db, candidate, [candidate]) == []


# --- run_safety_checks (full composition) -----------------------------------


def test_run_safety_checks_reports_ok_for_a_clean_candidate():
    candidate_key = uuid.uuid4()
    candidate = _policy(scope=Scope(principal="Regional Controller", action="vendor_payment"))
    row = _FakeRow(candidate_key, candidate)
    db = _FakeSession(scalars_results=[[]])  # no other active policies
    result = run_safety_checks(db, candidate_key, row)
    assert result.ok
    assert result.violations == ()


def test_run_safety_checks_surfaces_duplicate_authority_against_other_active_rows():
    candidate_key = uuid.uuid4()
    candidate = _policy(scope=Scope(principal="Regional Controller", action="vendor_payment"))
    row = _FakeRow(candidate_key, candidate)
    other_row = _FakeRow(uuid.uuid4(), _policy(scope=Scope(principal="Regional Controller", action="vendor_payment")))
    db = _FakeSession(scalars_results=[[other_row]])
    result = run_safety_checks(db, candidate_key, row)
    assert not result.ok
    assert any(v.check == "duplicate_authority" for v in result.violations)
