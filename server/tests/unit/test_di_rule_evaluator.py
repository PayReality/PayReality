"""Decision Intelligence: pure-function unit tests for rule_evaluator.py
-- AND/OR combinations, every operator, exceptions, missing-field
handling, and human_review_required routing. No DB, matching this
codebase's established convention for pure domain logic."""

from app.domain.decision_intelligence.rule_evaluator import evaluate_rule
from app.domain.decision_intelligence.rule_schema import Condition, CompositeCondition, RuleAction, RuleSchema


def _rule(root_condition, action=None, exceptions=None, missing_data_behavior="route_to_human"):
    return RuleSchema(
        root_condition=root_condition,
        action=action or RuleAction(decision="approve", human_review_required=False),
        exceptions=exceptions or [],
        missing_data_behavior=missing_data_behavior,
    )


# --- Operators --------------------------------------------------------


def test_eq_operator():
    rule = _rule(Condition(field="status", operator="eq", value="open"))
    assert evaluate_rule(rule, {"status": "open"}).matched is True
    assert evaluate_rule(rule, {"status": "closed"}).matched is False


def test_neq_operator():
    rule = _rule(Condition(field="status", operator="neq", value="open"))
    assert evaluate_rule(rule, {"status": "closed"}).matched is True
    assert evaluate_rule(rule, {"status": "open"}).matched is False


def test_gt_gte_lt_lte_operators():
    assert evaluate_rule(_rule(Condition(field="amount", operator="gt", value=100)), {"amount": 101}).matched
    assert not evaluate_rule(_rule(Condition(field="amount", operator="gt", value=100)), {"amount": 100}).matched
    assert evaluate_rule(_rule(Condition(field="amount", operator="gte", value=100)), {"amount": 100}).matched
    assert evaluate_rule(_rule(Condition(field="amount", operator="lt", value=100)), {"amount": 99}).matched
    assert evaluate_rule(_rule(Condition(field="amount", operator="lte", value=100)), {"amount": 100}).matched


def test_in_and_not_in_operators():
    rule_in = _rule(Condition(field="country", operator="in", value=["US", "CA"]))
    assert evaluate_rule(rule_in, {"country": "US"}).matched is True
    assert evaluate_rule(rule_in, {"country": "FR"}).matched is False

    rule_not_in = _rule(Condition(field="country", operator="not_in", value=["US", "CA"]))
    assert evaluate_rule(rule_not_in, {"country": "FR"}).matched is True
    assert evaluate_rule(rule_not_in, {"country": "US"}).matched is False


def test_contains_operator():
    rule = _rule(Condition(field="tags", operator="contains", value="urgent"))
    assert evaluate_rule(rule, {"tags": ["urgent", "finance"]}).matched is True
    assert evaluate_rule(rule, {"tags": ["finance"]}).matched is False


def test_is_missing_operator_true_when_field_absent():
    rule = _rule(Condition(field="vendor.approved", operator="is_missing", value=None))
    assert evaluate_rule(rule, {}).matched is True
    assert evaluate_rule(rule, {"vendor": {"approved": True}}).matched is False


def test_dot_path_field_resolution():
    rule = _rule(Condition(field="vendor.country", operator="eq", value="US"))
    assert evaluate_rule(rule, {"vendor": {"country": "US"}}).matched is True


def test_unknown_operator_raises_rather_than_silently_passing():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Condition(field="x", operator="bogus", value=1)


def test_incomparable_types_fail_the_condition_not_crash():
    rule = _rule(Condition(field="amount", operator="gt", value=100))
    result = evaluate_rule(rule, {"amount": "not_a_number"})
    assert result.matched is False


# --- AND / OR combinations ------------------------------------------------


def test_and_requires_all_children_true():
    rule = _rule(
        CompositeCondition(
            combinator="AND",
            conditions=[
                Condition(field="amount", operator="lte", value=1000),
                Condition(field="approved", operator="eq", value=True),
            ],
        )
    )
    assert evaluate_rule(rule, {"amount": 500, "approved": True}).matched is True
    assert evaluate_rule(rule, {"amount": 500, "approved": False}).matched is False


def test_or_requires_any_child_true():
    rule = _rule(
        CompositeCondition(
            combinator="OR",
            conditions=[
                Condition(field="vip", operator="eq", value=True),
                Condition(field="amount", operator="lte", value=100),
            ],
        )
    )
    assert evaluate_rule(rule, {"vip": True, "amount": 99999}).matched is True
    assert evaluate_rule(rule, {"vip": False, "amount": 50}).matched is True
    assert evaluate_rule(rule, {"vip": False, "amount": 99999}).matched is False


def test_nested_composite_conditions():
    rule = _rule(
        CompositeCondition(
            combinator="AND",
            conditions=[
                Condition(field="amount", operator="lte", value=1000),
                CompositeCondition(
                    combinator="OR",
                    conditions=[
                        Condition(field="vendor.approved", operator="eq", value=True),
                        Condition(field="vendor.country", operator="in", value=["US", "CA"]),
                    ],
                ),
            ],
        )
    )
    assert evaluate_rule(rule, {"amount": 500, "vendor": {"approved": True, "country": "FR"}}).matched is True
    assert evaluate_rule(rule, {"amount": 500, "vendor": {"approved": False, "country": "DE"}}).matched is False


# --- Exceptions -------------------------------------------------------


def test_exception_overrides_a_matched_root_condition():
    rule = _rule(
        Condition(field="amount", operator="lte", value=1000),
        exceptions=[Condition(field="flagged", operator="eq", value=True)],
        missing_data_behavior="treat_as_false",
    )
    result = evaluate_rule(rule, {"amount": 500, "flagged": True})
    assert result.matched is False
    assert result.decision is None


def test_no_exception_match_leaves_root_match_intact():
    rule = _rule(
        Condition(field="amount", operator="lte", value=1000),
        exceptions=[Condition(field="flagged", operator="eq", value=True)],
        missing_data_behavior="treat_as_false",
    )
    result = evaluate_rule(rule, {"amount": 500, "flagged": False})
    assert result.matched is True
    assert result.decision == "approve"


# --- Missing data handling ----------------------------------------------


def test_treat_as_false_proceeds_without_overriding_the_tree_result():
    rule = _rule(
        Condition(field="approved", operator="eq", value=True), missing_data_behavior="treat_as_false"
    )
    result = evaluate_rule(rule, {})
    assert result.matched is False
    assert result.missing_fields == ["approved"]
    # Not forced to human review -- treat_as_false trusts the (False) tree result.
    assert result.human_review_required is False


def test_route_to_human_overrides_a_result_when_data_is_missing():
    rule = _rule(
        Condition(field="approved", operator="eq", value=False), missing_data_behavior="route_to_human"
    )
    # Root condition as computed (missing -> False) would actually equal
    # the expected value False... but "approved" itself is missing, so
    # route_to_human must still force human review regardless.
    result = evaluate_rule(rule, {})
    assert result.missing_fields == ["approved"]
    assert result.matched is False
    assert result.decision is None
    assert result.human_review_required is True


def test_fail_behavior_does_not_set_human_review_required():
    rule = _rule(Condition(field="approved", operator="eq", value=True), missing_data_behavior="fail")
    result = evaluate_rule(rule, {})
    assert result.matched is False
    assert result.decision is None
    assert result.human_review_required is False


def test_no_missing_fields_when_everything_is_present():
    rule = _rule(Condition(field="approved", operator="eq", value=True))
    result = evaluate_rule(rule, {"approved": True})
    assert result.missing_fields == []


# --- human_review_required routing --------------------------------------


def test_matched_rule_surfaces_human_review_required_from_its_action():
    rule = _rule(
        Condition(field="amount", operator="gt", value=100000),
        action=RuleAction(decision="escalate", human_review_required=True),
    )
    result = evaluate_rule(rule, {"amount": 200000})
    assert result.matched is True
    assert result.decision == "escalate"
    assert result.human_review_required is True


def test_unmatched_rule_never_reports_human_review_required():
    rule = _rule(
        Condition(field="amount", operator="gt", value=100000),
        action=RuleAction(decision="escalate", human_review_required=True),
    )
    result = evaluate_rule(rule, {"amount": 10})
    assert result.matched is False
    assert result.human_review_required is False


# --- matched_conditions / unmatched_conditions descriptions --------------


def test_matched_and_unmatched_condition_descriptions_are_human_readable():
    rule = _rule(
        CompositeCondition(
            combinator="AND",
            conditions=[
                Condition(field="amount", operator="lte", value=1000),
                Condition(field="approved", operator="eq", value=True),
            ],
        )
    )
    result = evaluate_rule(rule, {"amount": 500, "approved": False})
    assert "amount lte 1000" in result.matched_conditions
    assert "approved eq True" in result.unmatched_conditions
