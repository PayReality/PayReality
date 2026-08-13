"""Milestone 2 (Multi-Tenant Foundation): the first multi-organization
isolation regression tests for Runtime Policy CRUD, extending
test_organization_isolation.py's Milestone 1 pattern to the
runtime_policy_records/policies tables added in this milestone.

Follows this project's own established convention (test_organization_
isolation.py, test_policy_compilation_ordering.py) for testing DB-
touching service functions without a real database: a minimal fake
Session that answers scalar/scalars/get with pre-wired results, never
touching a real database. Where the property under test is "the SQL
statement itself carries an organization filter," the test asserts
against the compiled statement text directly.

compile_policy/deploy_policy/dry_run_policy are deliberately excluded,
per test_runtime_policy_service_diff.py's own established convention:
they compose compiler_v2 and genuinely require a live database session,
verified against the real deployed Postgres instance instead. The real-
OPA per-organization package isolation those functions ultimately rely
on is proven separately in
tests/integration/test_multi_tenant_opa_isolation.py.
"""

import uuid

from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import Metadata
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import runtime_policy_service as svc

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()


class _FakeSession:
    """Never touches a real database; a fixed return value per call is
    enough, matching test_organization_isolation.py's own _FakeSession
    docstring reasoning."""

    def __init__(self, scalar_results=None, scalars_results=None):
        self._scalar_results = list(scalar_results or [])
        self._scalars_results = list(scalars_results or [])
        self.statements = []
        self.added = []
        self.committed = 0

    def scalar(self, stmt):
        self.statements.append(stmt)
        return self._scalar_results.pop(0) if self._scalar_results else None

    def scalars(self, stmt):
        self.statements.append(stmt)
        return self._scalars_results.pop(0) if self._scalars_results else []

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed += 1

    def refresh(self, obj):
        pass


class _FakeLatestRow:
    """Stands in for a RuntimePolicyRecord already resolved to a
    specific organization, for edit_policy's inheritance test below."""

    def __init__(self, organization_id):
        self.organization_id = organization_id
        self.status = "draft"
        self.version = 1


def _compiled(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def _policy(**overrides) -> RuntimePolicy:
    defaults = dict(
        id="rp-1", name="Test Policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="p1", action="a1"), conditions=ConditionSet(all=()),
        effect=Effect.ALLOW, metadata=Metadata(),
    )
    defaults.update(overrides)
    return RuntimePolicy(**defaults)


# --- Read paths: statement carries the organization filter ----------------


def test_list_latest_policies_statement_filters_by_organization_id():
    db = _FakeSession(scalars_results=[[]])
    svc.list_latest_policies(db, ORG_A)
    assert f"'{ORG_A.hex}'" in _compiled(db.statements[0])


def test_get_latest_statement_filters_by_organization_id():
    db = _FakeSession(scalar_results=[None])
    try:
        svc.get_latest(db, uuid.uuid4(), ORG_A)
    except svc.RuntimePolicyNotFoundError:
        pass
    assert f"'{ORG_A.hex}'" in _compiled(db.statements[0])


def test_list_versions_statement_filters_by_organization_id():
    db = _FakeSession(scalars_results=[[]])
    try:
        svc.list_versions(db, uuid.uuid4(), ORG_A)
    except svc.RuntimePolicyNotFoundError:
        pass
    assert f"'{ORG_A.hex}'" in _compiled(db.statements[0])


def test_get_version_statement_filters_by_organization_id():
    db = _FakeSession(scalar_results=[None])
    try:
        svc.get_version(db, uuid.uuid4(), 1, ORG_A)
    except svc.RuntimePolicyNotFoundError:
        pass
    assert f"'{ORG_A.hex}'" in _compiled(db.statements[0])


# --- Write paths: organization_id is stamped, never re-trusted ------------


def test_create_policy_stamps_the_given_organization_id():
    db = _FakeSession()
    row = svc.create_policy(db, _policy(), ORG_A)
    assert row.organization_id == ORG_A
    assert db.added[0].organization_id == ORG_A


def test_edit_policy_inherits_latest_organization_id_never_the_caller_supplied_one():
    """edit_policy's own docstring claim: the new version inherits
    latest.organization_id directly, never the organization_id the
    caller passed in -- there is no path by which editing a policy
    could reassign it to a different organization than the one that
    created it. Simulated by returning a fake "latest" row already
    resolved to ORG_A while the caller passes ORG_B -- get_latest's own
    organization filter is what a real database would enforce; this
    fake session only proves the SUBSEQUENT inheritance step is honest
    even if that filter were ever bypassed."""
    db = _FakeSession(scalar_results=[_FakeLatestRow(ORG_A)])
    row = svc.edit_policy(db, uuid.uuid4(), ORG_B, _policy(version=2))
    assert row.organization_id == ORG_A
    assert row.organization_id != ORG_B
