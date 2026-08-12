"""Unit tests for domain/policy_simulation/explainer.py and
authority_trace.py (Runtime Policy Simulator, Phase 4). Pure, DB-free,
no OPA -- these test the deterministic Python-side re-statement of
Condition/Scope semantics against hand-built inputs; the real-OPA-vs-
explainer agreement is separately verified in
tests/integration/test_policy_simulation_opa.py."""

from app.domain.policy_simulation.authority_trace import build_authority_trace
from app.domain.policy_simulation.explainer import build_rule_evaluations, evaluate_condition
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope


def _policy(**overrides) -> RuntimePolicy:
    defaults = dict(
        id="rp-1", name="Test Policy", version=1, status=PolicyStatus.ACTIVE,
        scope=Scope(principal="Procurement Manager", action="create_purchase_order"),
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value=500000),)),
        effect=Effect.ALLOW,
    )
    defaults.update(overrides)
    return RuntimePolicy(**defaults)


def test_evaluate_condition_lte_passes_when_under():
    c = Condition(field="amount", operator=Operator.LTE, value=500000)
    result = evaluate_condition(c, {"amount": 250000}, {})
    assert result.passed is True
    assert result.actual_value == 250000


def test_evaluate_condition_lte_fails_when_over():
    c = Condition(field="amount", operator=Operator.LTE, value=500000)
    result = evaluate_condition(c, {"amount": 850000}, {})
    assert result.passed is False


def test_evaluate_condition_reads_context_prefixed_fields_from_context_not_intent():
    """Mirrors rego_generator._resolve_base_and_field's own routing
    exactly: "context.authority.department" reads from the context dict,
    never from intent, even if intent happens to have a same-named key."""
    c = Condition(field="context.authority.department", operator=Operator.EQ, value="Finance")
    result = evaluate_condition(c, {"authority": {"department": "WRONG"}}, {"authority": {"department": "Finance"}})
    assert result.passed is True
    assert result.actual_value == "Finance"


def test_evaluate_condition_missing_field_fails_without_raising():
    c = Condition(field="amount", operator=Operator.LTE, value=500000)
    result = evaluate_condition(c, {}, {})
    assert result.passed is False
    assert result.actual_value is None


def test_evaluate_condition_exists_true_passes_when_present():
    c = Condition(field="vendor.approved", operator=Operator.EXISTS, value=True)
    result = evaluate_condition(c, {"vendor": {"approved": False}}, {})
    assert result.passed is True  # present (even though falsy), so exists=true holds


def test_evaluate_condition_exists_false_passes_when_missing():
    c = Condition(field="vendor.approved", operator=Operator.EXISTS, value=False)
    result = evaluate_condition(c, {}, {})
    assert result.passed is True


def test_evaluate_condition_in_operator():
    c = Condition(field="region", operator=Operator.IN, value=["South Africa", "Namibia"])
    assert evaluate_condition(c, {"region": "South Africa"}, {}).passed is True
    assert evaluate_condition(c, {"region": "Kenya"}, {}).passed is False


def test_evaluate_condition_contains_operator():
    c = Condition(field="notes", operator=Operator.CONTAINS, value="urgent")
    assert evaluate_condition(c, {"notes": "this is urgent"}, {}).passed is True
    assert evaluate_condition(c, {"notes": "routine"}, {}).passed is False


def test_build_rule_evaluations_matches_the_policy_simulator_worked_example():
    """The exact POLICY_SIMULATOR.md example: Rule 1 (Procurement
    Manager Max Authority, R500,000) fails against a R850,000 request;
    Rule 2 (CFO Override) matches and decides the outcome."""
    limit_policy = _policy(id="rp-limit", name="Procurement Manager Max Authority")
    override_policy = _policy(
        id="rp-override", name="CFO Override Escalation",
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.GT, value=500000),)),
        effect=Effect.REQUIRE_HUMAN_REVIEW,
    )
    intent = {"action": "create_purchase_order", "amount": 850000}
    rules = build_rule_evaluations(
        [limit_policy, override_policy], intent, {}, "Procurement Manager", ["rp-override"]
    )

    limit_rule, override_rule = rules
    assert limit_rule.matched is False
    assert limit_rule.conditions[0].passed is False
    assert "500000" in limit_rule.summary
    assert override_rule.matched is True
    assert override_rule.effect == "require_human_review"


def test_rule_evaluation_reports_scope_mismatch_when_principal_differs():
    policy = _policy(scope=Scope(principal="CFO", action="create_purchase_order"))
    rules = build_rule_evaluations(
        [policy], {"action": "create_purchase_order", "amount": 1}, {}, "Procurement Manager", []
    )
    assert rules[0].scope_matched is False
    assert "not apply" in rules[0].summary.lower()


def test_build_authority_trace_includes_the_deciding_rule_when_different_from_candidate():
    trace = build_authority_trace(
        agent_name="Procurement AI Agent", acting_as_principal="Procurement Manager",
        policy_name="Procurement Manager Max Authority", policy_version=12,
        matched_policy_name="CFO Override Escalation", outcome="HUMAN_REVIEW",
    )
    labels = [s.label for s in trace]
    assert "Procurement AI Agent" in labels
    assert "Procurement Manager" in labels
    assert "Procurement Manager Max Authority v12" in labels
    assert "CFO Override Escalation" in labels
    assert "Escalation Required" in labels


def test_build_authority_trace_omits_deciding_rule_when_same_as_candidate():
    trace = build_authority_trace(
        agent_name="Agent", acting_as_principal="Procurement Manager",
        policy_name="Procurement Manager Max Authority", policy_version=12,
        matched_policy_name="Procurement Manager Max Authority", outcome="ALLOW",
    )
    labels = [s.label for s in trace]
    assert labels.count("Procurement Manager Max Authority v12") == 1
    assert "Approved" in labels
