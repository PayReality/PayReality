"""Structural gate for marking a DIRuleVersion's parent DIDecisionRule
`validated`.

Deliberately conservative, not a completeness guarantee (this module's
own design brief): there is no fixed case-attribute schema in this
product yet, so this cannot check "does every field this rule references
actually exist on a real case" -- only that every field is a real,
non-empty string, i.e. the rule's author actually named something rather
than leaving a placeholder. A rule passing this check is NOT thereby
proven correct or complete; it has only cleared the two structural/
governance preconditions below.

Pure function: takes the rule's own `schema_json` and the source
answer's `status` as plain values, not ORM objects -- domain/ may never
import app.db (SPECIFICATION/26_PHASE_2_DEPENDENCY_DECLARATION.md section
26.4.2, enforced by test_architectural_boundaries.py), so resolving the
actual DIRuleVersion/DIAnswer rows is the service layer's job (see
services/di_rule_service.py's own validate_rule)."""

from __future__ import annotations

from app.domain.decision_intelligence.rule_schema import Condition, CompositeCondition, RuleSchema


class RuleValidationError(Exception):
    """Raised with a human-readable reason when a rule version fails one
    of validate_rule_version's checks."""


def _iter_fields(node: "Condition | CompositeCondition"):
    if isinstance(node, Condition):
        yield node.field
        return
    for child in node.conditions:
        yield from _iter_fields(child)


def _all_referenced_fields(rule: RuleSchema) -> list[str]:
    fields = list(_iter_fields(rule.root_condition))
    for exception_node in rule.exceptions:
        fields.extend(_iter_fields(exception_node))
    return fields


def validate_rule_version(schema_json: dict, source_answer_status: str | None) -> None:
    """Raises RuleValidationError if a rule version with this
    `schema_json`, sourced from an answer currently at
    `source_answer_status`, may NOT be marked validated. Two checks,
    both required:

    1. The source answer's status must be `approved` -- a rule can never
       be more authoritative than the human answer it claims to
       implement. `source_answer_status=None` means the service layer
       could not resolve a source answer at all (treated the same as
       "not approved"). This is the real governance gate: nobody
       automates a decision nobody with authority has actually signed
       off on.
    2. Every `field` named anywhere in the rule's condition tree
       (root_condition and exceptions) must be a non-empty string -- a
       deliberately shallow structural sanity check, not a claim that
       the field is a real, known case attribute (see module docstring).
    """
    if source_answer_status != "approved":
        raise RuleValidationError(
            f"source_answer_not_approved: answer status is {source_answer_status!r}, must be 'approved'"
        )

    rule = RuleSchema.model_validate(schema_json)
    for field in _all_referenced_fields(rule):
        if not isinstance(field, str) or not field.strip():
            raise RuleValidationError(f"invalid_condition_field: {field!r} is not a non-empty string")
