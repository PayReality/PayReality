"""Milestone 6 (Production Blocker Resolution): regression tests for the
Runtime Policy Simulator's own multi-tenant gap, discovered live against
Azure production before this milestone existed.

The bug: `policy_simulation_service.py::_compile_for_simulation` called
`runtime_policy_service.get_latest(db, policy_key)` and
`_other_active_policies(db, policy_key)` with no `organization_id`
argument, even though both functions have required it since Milestone 2
(Multi-Tenant Foundation). Every call into this module -- simulate,
run_batch, and every Test Scenario endpoint -- raised
`TypeError: get_latest() missing 1 required positional argument:
'organization_id'` in production, for every organization, on every
call, confirmed live in MILESTONE_5_AZURE_PRODUCTION_CUTOVER_SUMMARY.md.
The router itself also never resolved an organization at all, and
`SimulationScenario.organization_id` (added, additive, in Milestone 2)
was never populated or filtered on by anything, a second, independent
isolation gap this same fix closes.

Follows the established fake-session convention
(test_multi_tenant_runtime_policy_isolation.py): a minimal fake Session
answering scalar/scalars/get/add/commit/refresh, never touching a real
database. compile_bundle is pure/offline (no OPA call -- only
dry_run/deploy_policy touch OPA over HTTP), so `_compile_for_simulation`
itself is fully testable this way; `simulate`/`run_batch` themselves are
not (they call OPA via dry_run/batch_evaluator), and remain covered by
the real-OPA integration tests in
tests/integration/test_policy_simulation_opa.py per that file's own
documented convention.
"""

import uuid

from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import Metadata
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.domain.runtime_policy.schema import to_dict
from app.services import policy_simulation_service as sim_svc
from app.services import runtime_policy_service as rp_svc

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()


class _FakeSession:
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

    def get(self, model, id):
        return self._scalar_results.pop(0) if self._scalar_results else None

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed += 1

    def refresh(self, obj):
        pass


def _compiled(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def _policy(**overrides) -> RuntimePolicy:
    """action="vendor_payment": compile_bundle (unlike the plain
    dataclass construction test_multi_tenant_runtime_policy_isolation.py
    uses its own "a1" fixture for) actually runs scope_vocabulary
    validation, which "a1" is not a recognized action for."""
    defaults = dict(
        id="rp-1", name="Test Policy", version=1, status=PolicyStatus.ACTIVE,
        scope=Scope(principal="p1", action="vendor_payment"), conditions=ConditionSet(all=()),
        effect=Effect.ALLOW, metadata=Metadata(),
    )
    defaults.update(overrides)
    return RuntimePolicy(**defaults)


class _FakePolicyRow:
    """Stands in for a RuntimePolicyRecord: just enough attributes for
    _row_to_policy (reads .content) and _compile_for_simulation (reads
    .version)."""

    def __init__(self, organization_id, version=1):
        self.organization_id = organization_id
        self.version = version
        self.content = to_dict(_policy(version=version))


# --- The exact production bug: organization_id threading -------------------


def test_compile_for_simulation_no_longer_raises_typeerror_with_organization_id():
    """Before this fix, calling with a 3rd positional argument at all
    would have been a TypeError from get_latest's own signature mismatch
    -- this simply proves the call succeeds end-to-end (get_latest,
    _other_active_policies, compile_bundle) once organization_id is
    actually threaded through, which it never was in production."""
    policy_key = uuid.uuid4()
    db = _FakeSession(
        scalar_results=[_FakePolicyRow(ORG_A)],
        scalars_results=[[]],  # no other active policies
    )
    row, this_policy, all_policies, result = sim_svc._compile_for_simulation(db, policy_key, ORG_A)
    assert row.organization_id == ORG_A
    assert this_policy.id == "rp-1"
    assert all_policies == [this_policy]
    assert result.ok is True


def test_compile_for_simulation_get_latest_statement_filters_by_organization_id():
    db = _FakeSession(scalar_results=[None])
    try:
        sim_svc._compile_for_simulation(db, uuid.uuid4(), ORG_A)
    except rp_svc.RuntimePolicyNotFoundError:
        pass
    assert f"'{ORG_A.hex}'" in _compiled(db.statements[0])


def test_compile_for_simulation_cross_organization_lookup_is_not_found_not_a_crash():
    """A policy_key belonging to ORG_A, looked up under ORG_B, must
    behave exactly like an unknown policy_key -- the same
    "cross-organization access looks like not-found" convention this
    codebase already applies everywhere else -- never a TypeError, and
    never real data leaking across the boundary."""
    db = _FakeSession(scalar_results=[None])  # get_latest's own org filter would find nothing
    raised = False
    try:
        sim_svc._compile_for_simulation(db, uuid.uuid4(), ORG_B)
    except rp_svc.RuntimePolicyNotFoundError:
        raised = True
    assert raised
    assert f"'{ORG_B.hex}'" in _compiled(db.statements[0])


def test_compile_for_simulation_other_active_policies_statement_filters_by_organization_id():
    policy_key = uuid.uuid4()
    db = _FakeSession(scalar_results=[_FakePolicyRow(ORG_A)], scalars_results=[[]])
    sim_svc._compile_for_simulation(db, policy_key, ORG_A)
    other_active_stmt = db.statements[1]
    assert f"'{ORG_A.hex}'" in _compiled(other_active_stmt)


# --- Test Scenarios: organization_id was never stamped or filtered ---------


def test_create_scenario_stamps_the_given_organization_id():
    db = _FakeSession(scalar_results=[_FakePolicyRow(ORG_A)])
    from app.services.policy_simulation_service import SimulationInput

    scenario = sim_svc.create_scenario(
        db, uuid.uuid4(), name="Big purchase", sim_input=SimulationInput(principal="p1", action="a1"),
        expected_outcome="ALLOW", organization_id=ORG_A,
    )
    assert scenario.organization_id == ORG_A
    assert db.added[0].organization_id == ORG_A


def test_create_scenario_rejects_a_policy_key_from_another_organization():
    db = _FakeSession(scalar_results=[None])  # get_latest finds nothing under ORG_B
    from app.services.policy_simulation_service import SimulationInput

    raised = False
    try:
        sim_svc.create_scenario(
            db, uuid.uuid4(), name="x", sim_input=SimulationInput(principal="p1", action="a1"),
            expected_outcome="ALLOW", organization_id=ORG_B,
        )
    except rp_svc.RuntimePolicyNotFoundError:
        raised = True
    assert raised
    assert not db.added


def test_list_scenarios_statement_filters_by_organization_id():
    db = _FakeSession(scalar_results=[_FakePolicyRow(ORG_A)], scalars_results=[[]])
    sim_svc.list_scenarios(db, uuid.uuid4(), ORG_A)
    list_stmt = db.statements[1]
    assert f"'{ORG_A.hex}'" in _compiled(list_stmt)


def test_get_scenario_from_another_organization_is_not_found():
    """A scenario that genuinely exists, but belongs to ORG_A, must be
    invisible to ORG_B -- SimulationScenario.organization_id has existed
    since Milestone 2 but nothing ever checked it until now."""

    class _FakeScenarioRow:
        organization_id = ORG_A

    db = _FakeSession(scalar_results=[_FakeScenarioRow()])
    raised = False
    try:
        sim_svc.get_scenario(db, uuid.uuid4(), ORG_B)
    except sim_svc.ScenarioNotFoundError:
        raised = True
    assert raised


def test_run_scenario_from_another_organization_is_not_found_before_touching_opa():
    """The cross-organization case must short-circuit at get_scenario,
    never reaching simulate()/OPA at all -- proven here by the fake
    session having no second result queued for any further lookup."""

    class _FakeScenarioRow:
        organization_id = ORG_A
        policy_key = uuid.uuid4()
        input = {"principal": "p1", "action": "a1"}

    db = _FakeSession(scalar_results=[_FakeScenarioRow()])
    raised = False
    try:
        sim_svc.run_scenario(db, uuid.uuid4(), ORG_B)
    except sim_svc.ScenarioNotFoundError:
        raised = True
    assert raised
