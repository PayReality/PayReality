"""Integration tests against a real, ephemeral OPA server (see
conftest.py) for the Runtime Policy Simulator (Phase 4,
POLICY_SIMULATOR.md).

These test the actual OPA-touching mechanics services/
policy_simulation_service.py relies on -- domain/compiler_v2.dry_run
(already existing, reused unchanged) and domain/policy_simulation.
batch_evaluator (new, this phase) -- with real RuntimePolicy objects
directly, not through the DB-dependent service layer (get_latest/
_other_active_policies require a live Postgres session; this codebase's
own established convention, per test_ai_authority_builder.py and
runtime_policy_service's own test coverage, is that DB-dependent
orchestration is verified against a real database separately, not with
a fake one here). What's proven here is the part that's genuinely new
and genuinely OPA-dependent: that a simulation bundle evaluates
correctly and in isolation from a live "authorization" package, and
that batch evaluation (load once, query many) produces the same
results a one-shot dry run would.
"""

from app.domain.compiler_v2.bundle_builder import build_bundle
from app.domain.compiler_v2.dry_run import dry_run
from app.domain.policy_simulation.batch_evaluator import loaded_bundle, query_loaded_bundle
from app.domain.policy_simulation.explainer import build_rule_evaluations
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope


def _procurement_manager_limit() -> RuntimePolicy:
    return RuntimePolicy(
        id="rp-procurement-manager",
        name="Procurement Manager Max Authority",
        version=12,
        status=PolicyStatus.ACTIVE,
        scope=Scope(principal="Procurement Manager", action="create_purchase_order"),
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value=500000),)),
        effect=Effect.ALLOW,
    )


def _cfo_override_escalation() -> RuntimePolicy:
    return RuntimePolicy(
        id="rp-cfo-override",
        name="CFO Override Escalation",
        version=3,
        status=PolicyStatus.ACTIVE,
        scope=Scope(principal="Procurement Manager", action="create_purchase_order"),
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.GT, value=500000),)),
        effect=Effect.REQUIRE_HUMAN_REVIEW,
    )


def test_simulation_bundle_escalates_when_over_the_limit(opa_url):
    """The exact POLICY_SIMULATOR.md example: R850,000 against a
    R500,000 limit, with a CFO Override rule also active, must escalate
    -- not allow, not deny."""
    policies = [_procurement_manager_limit(), _cfo_override_escalation()]
    bundle = build_bundle(policies, "simulation-test", 1)

    result = dry_run(
        bundle,
        {
            "intent": {"action": "create_purchase_order", "amount": 850000, "resource": "Supplier ABC"},
            "context": {"authority": {"department": "Finance", "region": "South Africa"}},
            "agent": {"acting_for_principal_id": "Procurement Manager"},
            "policy_version": 12,
        },
        opa_url=opa_url,
    )

    assert result.requires_review is True
    assert result.allow is False
    assert "rp-cfo-override" in result.evaluated_mandates
    assert "rp-procurement-manager" not in result.evaluated_mandates


def test_simulation_bundle_allows_when_under_the_limit(opa_url):
    policies = [_procurement_manager_limit(), _cfo_override_escalation()]
    bundle = build_bundle(policies, "simulation-test", 1)

    result = dry_run(
        bundle,
        {
            "intent": {"action": "create_purchase_order", "amount": 250000},
            "context": {},
            "agent": {"acting_for_principal_id": "Procurement Manager"},
            "policy_version": 12,
        },
        opa_url=opa_url,
    )

    assert result.allow is True
    assert result.requires_review is False
    assert "rp-procurement-manager" in result.evaluated_mandates


def test_explainer_agrees_with_real_opa_decision(opa_url):
    """The deterministic Python-side explainer must never disagree with
    what OPA actually decided -- `matched` is read from OPA's own
    evaluated_mandates, so this checks that wiring, not a second,
    independent judgment."""
    policies = [_procurement_manager_limit(), _cfo_override_escalation()]
    bundle = build_bundle(policies, "simulation-test", 1)
    intent = {"action": "create_purchase_order", "amount": 850000}
    context: dict = {}

    result = dry_run(
        bundle,
        {"intent": intent, "context": context, "agent": {"acting_for_principal_id": "Procurement Manager"},
         "policy_version": 12},
        opa_url=opa_url,
    )
    rules = build_rule_evaluations(policies, intent, context, "Procurement Manager", result.evaluated_mandates)

    limit_rule = next(r for r in rules if r.policy_id == "rp-procurement-manager")
    override_rule = next(r for r in rules if r.policy_id == "rp-cfo-override")
    assert limit_rule.matched is False
    assert "500000" in limit_rule.summary or "500,000" in limit_rule.summary
    assert override_rule.matched is True


def test_batch_evaluator_loads_once_and_queries_many_correctly(opa_url):
    """The new load-once-query-many mechanism (batch_evaluator.py) must
    produce the same per-row result a one-shot dry_run() would, across
    several different inputs against the same loaded bundle."""
    policies = [_procurement_manager_limit(), _cfo_override_escalation()]
    bundle = build_bundle(policies, "simulation-batch-test", 1)

    rows = [
        (100000, False),   # well under limit -> allow
        (500000, False),   # exactly at limit -> allow (<=)
        (500001, True),    # just over -> requires_review
        (2000000, True),   # far over -> requires_review
    ]

    with loaded_bundle(bundle, opa_url) as data_path:
        for amount, expect_review in rows:
            result = query_loaded_bundle(
                opa_url, data_path,
                {"intent": {"action": "create_purchase_order", "amount": amount}, "context": {},
                 "agent": {"acting_for_principal_id": "Procurement Manager"}, "policy_version": 12},
            )
            assert bool(result.get("requires_review", False)) == expect_review
            assert bool(result.get("allow", False)) == (not expect_review)


def test_batch_evaluator_cleans_up_after_itself(opa_url):
    """After the `with` block exits, the throwaway package must be gone
    -- querying its data path returns no meaningful result, matching
    dry_run()'s own verified cleanup guarantee."""
    import httpx

    policies = [_procurement_manager_limit()]
    bundle = build_bundle(policies, "simulation-cleanup-test", 1)

    with loaded_bundle(bundle, opa_url) as data_path:
        captured_path = data_path

    resp = httpx.post(
        f"{opa_url}/v1/data/{captured_path}",
        json={"input": {"intent": {"action": "create_purchase_order", "amount": 1},
                         "agent": {"acting_for_principal_id": "Procurement Manager"}}},
        timeout=5,
    )
    resp.raise_for_status()
    assert resp.json().get("result") in (None, {})
