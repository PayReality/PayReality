"""Milestone 2 (Multi-Tenant Foundation): the flagship proof of the
architecture decision confirmed in MILESTONE_2_MULTI_TENANT_FOUNDATION_
SUMMARY.md's ADR (Option 2 -- a distinct compiled Policy row AND a
distinct OPA package per organization). Runs against a real, ephemeral
OPA server (see conftest.py), not a mock, the same discipline
test_compiler_v2_opa.py/test_policy_simulation_opa.py already established
for this codebase's Compiler V2 work.

Two organizations that coincidentally use the exact same scope.principal
and scope.action -- the "noisy neighbor" scenario the ADR names -- must
evaluate completely independently once uploaded under their own per-org
package (opa_client.org_package_path/org_data_path/org_policy_id,
bundle_builder.retarget_package). This is the real behavior the fake-
session unit tests in test_runtime_policy_service.py's org-scoping
cannot prove on their own: OPA itself, not just the Python code that
calls it, must actually keep the two packages apart.
"""

import uuid

import httpx

from app.domain.compiler_v2.bundle_builder import build_bundle, retarget_package
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.opa_client import DATA_PATH, org_data_path, org_package_path, org_policy_id


def _policy(**overrides) -> RuntimePolicy:
    defaults = dict(
        id="rp-1",
        name="Vendor Payment",
        version=1,
        status=PolicyStatus.APPROVED,
        scope=Scope(principal="prin_1", action="vendor_payment"),
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value=100000),)),
        effect=Effect.ALLOW,
    )
    defaults.update(overrides)
    return RuntimePolicy(**defaults)


def _upload(opa_url: str, policy_id: str, rego_source: str) -> None:
    resp = httpx.put(
        f"{opa_url}/v1/policies/{policy_id}",
        content=rego_source.encode("utf-8"),
        headers={"Content-Type": "text/plain"},
        timeout=5,
    )
    resp.raise_for_status()


def _delete(opa_url: str, policy_id: str) -> None:
    """Best-effort: `opa_url` is a session-scoped, shared server (see
    conftest.py), and OPA refuses to let two different policy ids declare
    the same package. Every test in this file removes exactly what it
    uploaded once done, regardless of pass/fail, so no test here leaves
    package names claimed for whichever test file happens to run next --
    the same "authorization" and "live" ids test_compiler_v2_opa.py's own
    tests rely on being free to claim."""
    httpx.delete(f"{opa_url}/v1/policies/{policy_id}", timeout=5)


def _query(opa_url: str, data_path: str, input_doc: dict) -> dict:
    resp = httpx.post(f"{opa_url}{data_path}", json={"input": input_doc}, timeout=5)
    resp.raise_for_status()
    return resp.json().get("result", {})


def test_two_organizations_with_identical_scope_do_not_cross_contaminate(opa_url):
    """ORG_A's policy allows this exact intent; ORG_B's policy, matching
    the identical principal/action, denies everything. Under a single
    shared package (pre-Milestone-2), whichever compiled last would
    silently win for BOTH organizations. Under per-org packages, each
    must see only its own rule."""
    org_a, org_b = uuid.uuid4(), uuid.uuid4()

    allow_policy = _policy(id="rp-a", effect=Effect.ALLOW)
    deny_policy = _policy(
        id="rp-b",
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.GT, value=0),)),
        effect=Effect.DENY,
    )

    bundle_a = build_bundle([allow_policy], "bundle-a", 1)
    bundle_b = build_bundle([deny_policy], "bundle-b", 1)

    rego_a = retarget_package(bundle_a.rego_source, org_package_path(org_a))
    rego_b = retarget_package(bundle_b.rego_source, org_package_path(org_b))

    try:
        _upload(opa_url, org_policy_id(org_a), rego_a)
        _upload(opa_url, org_policy_id(org_b), rego_b)

        intent = {
            "intent": {"action": "vendor_payment", "amount": 50000},
            "agent": {"acting_for_principal_id": "prin_1"},
        }

        result_a = _query(opa_url, org_data_path(org_a), intent)
        result_b = _query(opa_url, org_data_path(org_b), intent)

        assert result_a["allow"] is True
        assert result_a["deny"] is False
        assert result_a["evaluated_mandates"] == ["rp-a"]

        assert result_b["allow"] is False
        assert result_b["deny"] is True
        assert result_b["evaluated_mandates"] == ["rp-b"]
    finally:
        _delete(opa_url, org_policy_id(org_a))
        _delete(opa_url, org_policy_id(org_b))


def test_legacy_shared_package_is_unaffected_by_organization_packages(opa_url):
    """organization_id=None deployments (a never-bootstrapped platform,
    or any pre-Milestone-2 test fixture) keep uploading to the exact
    literal "payreality.authorization"/"authorization" package and
    policy id every organization used to share -- unaffected by, and
    coexisting alongside, per-org packages loaded into the same OPA
    instance.

    This shares its `opa_url` server (session-scoped) with test_compiler_
    v2_opa.py, which registers the same literal "payreality.authorization"
    package under a different policy id ("live"). OPA refuses to let two
    different policy ids declare the same package, so "live" is removed
    first -- defensively, ignoring a missing-policy error if it was never
    registered -- and "authorization" is removed again at the end,
    rather than making either this test's outcome, or a later run of
    test_compiler_v2_opa.py's own tests, depend on file execution
    order."""
    _delete(opa_url, "live")
    org = uuid.uuid4()

    try:
        legacy_policy = _policy(id="rp-legacy")
        legacy_bundle = build_bundle([legacy_policy], "bundle-legacy", 1)
        _upload(opa_url, "authorization", legacy_bundle.rego_source)

        org_policy = _policy(
            id="rp-org",
            effect=Effect.DENY,
            conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.GT, value=0),)),
        )
        org_bundle = build_bundle([org_policy], "bundle-org", 1)
        rego_org = retarget_package(org_bundle.rego_source, org_package_path(org))
        _upload(opa_url, org_policy_id(org), rego_org)

        intent = {
            "intent": {"action": "vendor_payment", "amount": 50000},
            "agent": {"acting_for_principal_id": "prin_1"},
        }

        legacy_result = _query(opa_url, DATA_PATH, intent)
        org_result = _query(opa_url, org_data_path(org), intent)

        assert legacy_result["allow"] is True
        assert legacy_result["evaluated_mandates"] == ["rp-legacy"]

        assert org_result["deny"] is True
        assert org_result["evaluated_mandates"] == ["rp-org"]
    finally:
        _delete(opa_url, "authorization")
        _delete(opa_url, org_policy_id(org))
