"""Deterministic interpreter for a `RuleSchema` (rule_schema.py) against
one DICase's `facts` dict.

Security contract (non-negotiable, per this module's own brief): this
function NEVER calls `eval()`/`exec()`/anything that executes arbitrary
user-supplied code. It only walks the typed `Condition`/`CompositeCondition`
tree the rule's schema_json already validated into, comparing literal
values with a fixed, closed set of operators. There is exactly one
evaluator in this codebase for this rule language -- both "test this rule
against one case" (routers/decision_intelligence/rules.py) and the real
replay executor (replay_executor.py) call this same function unchanged,
so "what would this rule do" and "what did this rule actually do in the
replay" can never silently diverge into two different implementations.

Evaluates every leaf condition in the tree (no short-circuiting on AND/OR),
deliberately: a human inspecting a rule's test/replay result wants to see
every condition's own verdict, not just however many a short-circuiting
evaluator happened to reach.

Missing-data handling: a leaf condition whose `field` is absent from
`case_facts` (checked by dot-path) always evaluates to False for the
purpose of combining the tree (a condition that cannot be checked is not
affirmatively true), and its field name is recorded in `missing_fields`.
What that means for the FINAL result depends on the rule's own
`missing_data_behavior`:

  - "treat_as_false": no further override -- the tree's computed result
    (with missing leaves already False) IS the final result.
  - "route_to_human": if anything was missing, the final result is
    forced to matched=False, decision=None, human_review_required=True,
    regardless of what the tree computed -- an automatic decision is
    never produced from incomplete data.
  - "fail": if anything was missing, the final result is forced to
    matched=False, decision=None, human_review_required=False -- the
    rule simply did not produce a decision (distinct from "route to a
    human", which is an active routing choice the rule's author did not
    make here).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.domain.decision_intelligence.rule_schema import Condition, CompositeCondition, RuleSchema

_MISSING = object()


class EvaluationResult(BaseModel):
    matched: bool
    decision: str | None
    human_review_required: bool
    matched_conditions: list[str]
    unmatched_conditions: list[str]
    missing_fields: list[str]


def _resolve_field(facts: dict, field: str) -> Any:
    """Dot-path lookup into `facts` (e.g. "vendor.country"). Returns the
    sentinel `_MISSING` if any segment along the path is absent, so a
    present-but-None value (a fact explicitly recorded as null) is
    distinguishable from a field that was never supplied at all."""
    current: Any = facts
    for segment in field.split("."):
        if not isinstance(current, dict) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def _describe(condition: Condition) -> str:
    return f"{condition.field} {condition.operator} {condition.value!r}"


def _evaluate_condition(condition: Condition, facts: dict, missing_fields: list[str]) -> bool:
    if condition.operator == "is_missing":
        return _resolve_field(facts, condition.field) is _MISSING

    actual = _resolve_field(facts, condition.field)
    if actual is _MISSING:
        if condition.field not in missing_fields:
            missing_fields.append(condition.field)
        return False

    operator = condition.operator
    expected = condition.value
    try:
        if operator == "eq":
            return actual == expected
        if operator == "neq":
            return actual != expected
        if operator == "gt":
            return actual > expected
        if operator == "gte":
            return actual >= expected
        if operator == "lt":
            return actual < expected
        if operator == "lte":
            return actual <= expected
        if operator == "in":
            return actual in expected
        if operator == "not_in":
            return actual not in expected
        if operator == "contains":
            return expected in actual
    except TypeError:
        # Incomparable types (e.g. ">" between a string and a number) is a
        # data-quality problem, not a crash -- the condition simply doesn't
        # hold, exactly as if the comparison had failed on its own terms.
        return False
    raise ValueError(f"unknown_operator: {operator}")


def _evaluate_node(
    node: "Condition | CompositeCondition",
    facts: dict,
    missing_fields: list[str],
    matched_descriptions: list[str],
    unmatched_descriptions: list[str],
) -> bool:
    if isinstance(node, Condition):
        result = _evaluate_condition(node, facts, missing_fields)
        (matched_descriptions if result else unmatched_descriptions).append(_describe(node))
        return result

    if isinstance(node, CompositeCondition):
        child_results = [
            _evaluate_node(child, facts, missing_fields, matched_descriptions, unmatched_descriptions)
            for child in node.conditions
        ]
        if node.combinator == "AND":
            return all(child_results) if child_results else True
        return any(child_results) if child_results else False

    raise TypeError(f"unknown_condition_node_type: {type(node)!r}")


def evaluate_rule(rule: RuleSchema, case_facts: dict) -> EvaluationResult:
    facts = case_facts or {}
    missing_fields: list[str] = []
    matched_descriptions: list[str] = []
    unmatched_descriptions: list[str] = []

    root_matched = _evaluate_node(
        rule.root_condition, facts, missing_fields, matched_descriptions, unmatched_descriptions
    )

    exception_matched = False
    for exception_node in rule.exceptions:
        if _evaluate_node(exception_node, facts, missing_fields, matched_descriptions, unmatched_descriptions):
            exception_matched = True

    matched = root_matched and not exception_matched
    decision = rule.action.decision if matched else None
    human_review_required = rule.action.human_review_required if matched else False

    if missing_fields and rule.missing_data_behavior in ("route_to_human", "fail"):
        matched = False
        decision = None
        human_review_required = rule.missing_data_behavior == "route_to_human"

    return EvaluationResult(
        matched=matched,
        decision=decision,
        human_review_required=human_review_required,
        matched_conditions=matched_descriptions,
        unmatched_conditions=unmatched_descriptions,
        missing_fields=missing_fields,
    )
