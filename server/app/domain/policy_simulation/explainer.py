"""Runtime Policy Simulator, Phase 4 (POLICY_SIMULATOR.md): a deterministic,
DB-free, rule-by-rule explanation of why a policy matched or didn't --
built alongside the real OPA-computed decision, never instead of it.

This module mirrors domain/compiler_v2/rego_generator.py's exact field-
resolution and operator semantics in Python (the "context." field prefix
routes to input.context instead of input.intent; a missing field resolves
to "not present" rather than raising, exactly like Rego's own dot-path
access on a missing key) so that this explanation is mechanically
guaranteed to agree with what the compiled Rego actually does -- it reads
the same Condition/Scope objects the Rego generator reads, it does not
maintain a second, independently-written notion of what a policy means.
Nothing here calls an LLM, nothing here is a second, independent judgment
of authorization: the OPA-computed Decision (domain/decision/engine.py,
unmodified) remains the sole source of truth for allow/deny/review; this
module only explains it in business-readable terms.
"""

from dataclasses import dataclass
from typing import Any

from app.domain.runtime_policy.conditions import Condition, Operator
from app.domain.runtime_policy.runtime_policy import RuntimePolicy

_CONTEXT_FIELD_PREFIX = "context."


def _resolve_value(field_path: str, intent: dict[str, Any], context: dict[str, Any]) -> Any:
    """Same base-selection rule as rego_generator._resolve_base_and_field:
    a "context."-prefixed field reads from input.context (Runtime
    Authority Context), everything else reads from input.intent. A
    missing key at any depth resolves to None ("not present"), the same
    outcome Rego's own direct dot-path access produces on a missing
    intermediate key -- never a KeyError."""
    if field_path.startswith(_CONTEXT_FIELD_PREFIX):
        base: Any = context
        path = field_path[len(_CONTEXT_FIELD_PREFIX):]
    else:
        base = intent
        path = field_path
    for part in path.split("."):
        if not isinstance(base, dict) or part not in base:
            return None
        base = base[part]
    return base


def _condition_holds(operator: Operator, actual: Any, expected: Any) -> bool:
    """One Condition's pass/fail, mirroring
    rego_generator.generate_condition_expression's semantics exactly:
    EXISTS is the only operator that treats "missing" as a meaningful
    outcome on its own; every other operator simply fails to hold when
    the field is missing (undefined in Rego, never an error)."""
    if operator == Operator.EXISTS:
        return (actual is not None) == bool(expected)
    if actual is None:
        return False
    try:
        if operator == Operator.LTE:
            return actual <= expected
        if operator == Operator.GTE:
            return actual >= expected
        if operator == Operator.EQ:
            return actual == expected
        if operator == Operator.NEQ:
            return actual != expected
        if operator == Operator.LT:
            return actual < expected
        if operator == Operator.GT:
            return actual > expected
        if operator == Operator.IN:
            return actual in expected
        if operator == Operator.CONTAINS:
            return expected in actual
    except TypeError:
        # A type mismatch (e.g. comparing a string to a number) is a
        # non-match in Rego too -- comparison operators between
        # incompatible types are themselves undefined, not an error that
        # propagates.
        return False
    raise ValueError(f"no evaluation case for operator {operator!r}")


@dataclass(frozen=True)
class ConditionEvaluation:
    field: str
    operator: str
    expected_value: Any
    actual_value: Any
    passed: bool


@dataclass(frozen=True)
class RuleEvaluation:
    """One row of the Decision Explanation -- one RuntimePolicy's own
    evaluation, scope match plus every condition, so a reviewer sees
    exactly which threshold or field decided the outcome, not just a
    final boolean."""

    policy_id: str
    policy_name: str
    principal: str
    action: str
    effect: str
    scope_matched: bool
    conditions: tuple[ConditionEvaluation, ...]
    matched: bool
    summary: str


def _scope_matches(policy: RuntimePolicy, intent: dict[str, Any]) -> bool:
    """Mirrors rego_generator.generate_scope_block's AND of action,
    principal, and optionally agent/resource -- agent narrowing isn't
    evaluated here (the simulator's Intent has no separate `agent.id`
    from `acting_for_principal_id` the way a live Agent identity would),
    so a policy scoped to a specific agent is reported as scope-matched
    on action+principal+resource alone; its own conditions still apply."""
    if intent.get("action") != policy.scope.action:
        return False
    if policy.scope.resource is not None and intent.get("resource") != policy.scope.resource:
        return False
    return True


def evaluate_condition(condition: Condition, intent: dict[str, Any], context: dict[str, Any]) -> ConditionEvaluation:
    actual = _resolve_value(condition.field, intent, context)
    passed = _condition_holds(condition.operator, actual, condition.value)
    return ConditionEvaluation(
        field=condition.field, operator=condition.operator.value,
        expected_value=condition.value, actual_value=actual, passed=passed,
    )


def evaluate_rule(
    policy: RuntimePolicy,
    intent: dict[str, Any],
    context: dict[str, Any],
    acting_for_principal_id: str,
    matched_policy_ids: frozenset[str],
) -> RuleEvaluation:
    """`matched_policy_ids` is `DryRunResult.evaluated_mandates` (the real
    OPA output) -- `matched` is read from there, not recomputed in
    Python, so this explanation can never disagree with the actual
    decision about whether this specific rule fired. Everything else
    (which condition passed or failed, and why) is this module's own
    deterministic re-statement of the same Condition data the Rego was
    compiled from."""
    principal_matches = acting_for_principal_id == policy.scope.principal
    scope_matched = principal_matches and _scope_matches(policy, intent)
    conditions = tuple(evaluate_condition(c, intent, context) for c in policy.conditions.all)
    matched = policy.id in matched_policy_ids

    if not principal_matches:
        summary = f"Does not apply: policy is scoped to {policy.scope.principal!r}, not {acting_for_principal_id!r}."
    elif not scope_matched:
        summary = "Does not apply: action or resource does not match this policy's scope."
    else:
        failed = [c for c in conditions if not c.passed]
        if not failed:
            summary = f"Matched -- effect: {policy.effect.value}."
        else:
            c = failed[0]
            summary = f"Failed: {c.field} {c.operator} {c.expected_value!r} (actual: {c.actual_value!r})."

    return RuleEvaluation(
        policy_id=policy.id, policy_name=policy.name, principal=policy.scope.principal,
        action=policy.scope.action, effect=policy.effect.value, scope_matched=scope_matched,
        conditions=conditions, matched=matched, summary=summary,
    )


def build_rule_evaluations(
    policies: list[RuntimePolicy],
    intent: dict[str, Any],
    context: dict[str, Any],
    acting_for_principal_id: str,
    evaluated_mandates: list[str],
) -> list[RuleEvaluation]:
    matched = frozenset(evaluated_mandates)
    return [evaluate_rule(p, intent, context, acting_for_principal_id, matched) for p in policies]
