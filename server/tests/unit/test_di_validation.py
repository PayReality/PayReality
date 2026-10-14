"""Decision Intelligence: pure-function unit tests for validation.py.
No DB -- validate_rule_version takes plain schema_json/status values,
exactly because domain/ may never import app.db (see its own module
docstring and test_architectural_boundaries.py)."""

import pytest

from app.domain.decision_intelligence.rule_schema import Condition, RuleAction, RuleSchema
from app.domain.decision_intelligence.validation import RuleValidationError, validate_rule_version

_VALID_SCHEMA = RuleSchema(
    root_condition=Condition(field="amount", operator="lte", value=1000),
    action=RuleAction(decision="approve"),
).model_dump()


def test_passes_when_answer_approved_and_fields_are_valid():
    validate_rule_version(_VALID_SCHEMA, "approved")  # must not raise


def test_rejects_when_source_answer_not_approved():
    for status in ("draft", "submitted", "under_review", "rejected", "superseded", None):
        with pytest.raises(RuleValidationError):
            validate_rule_version(_VALID_SCHEMA, status)


def test_rejects_empty_string_field_in_root_condition():
    schema = RuleSchema(
        root_condition=Condition(field="", operator="eq", value=1), action=RuleAction(decision="approve")
    ).model_dump()
    with pytest.raises(RuleValidationError):
        validate_rule_version(schema, "approved")


def test_rejects_whitespace_only_field():
    schema = RuleSchema(
        root_condition=Condition(field="   ", operator="eq", value=1), action=RuleAction(decision="approve")
    ).model_dump()
    with pytest.raises(RuleValidationError):
        validate_rule_version(schema, "approved")


def test_rejects_empty_field_hidden_inside_an_exception():
    schema = RuleSchema(
        root_condition=Condition(field="amount", operator="lte", value=1000),
        action=RuleAction(decision="approve"),
        exceptions=[Condition(field="", operator="eq", value=True)],
    ).model_dump()
    with pytest.raises(RuleValidationError):
        validate_rule_version(schema, "approved")


def test_rejects_empty_field_nested_in_a_composite_condition():
    schema = {
        "root_condition": {
            "combinator": "AND",
            "conditions": [
                {"field": "amount", "operator": "lte", "value": 1000},
                {"field": "", "operator": "eq", "value": True},
            ],
        },
        "action": {"decision": "approve", "human_review_required": False},
        "exceptions": [],
        "missing_data_behavior": "route_to_human",
    }
    with pytest.raises(RuleValidationError):
        validate_rule_version(schema, "approved")
