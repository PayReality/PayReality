"""The versioned, inspectable Decision Rule representation Decision
Intelligence stores in `DIRuleVersion.schema_json`.

Deliberately its OWN typed condition language, not a reuse of
`app.domain.runtime_policy.conditions` -- that language is intentionally
flat (AND-only, no nesting, see its own module docstring) because it
feeds a Rego compiler enforcing live AI actions; this one is a human-
authored, human-tested hypothesis about how a *business decision* should
be made, which routinely needs AND/OR combinations and exceptions a flat
language can't express. The two product concepts are parallel by design
(this module's own package docstring), so their rule languages are
parallel too, not shared.

Every model here is pure data + structural validation (Pydantic's own
field typing), never executable: nothing in this module runs arbitrary
code, and `rule_evaluator.py` is the only thing that ever interprets a
`RuleSchema` against real facts. That separation is what makes it safe to
store `schema_json` as an opaque JSONB blob and still have a human (or a
future UI) render it faithfully from its own shape.
"""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field


class Condition(BaseModel):
    """One leaf comparison: `<field> <operator> <value>`.

    `field` is a dot-path into a DICase's `facts` dict. There is
    deliberately no fixed case-attribute schema to validate `field`
    against (this module's own design brief) -- it is validated only
    structurally (a non-empty string) by validation.py, never checked
    for "does this field actually exist on some schema".
    """

    field: str
    operator: Literal["eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "contains", "is_missing"]
    value: Any = None


class CompositeCondition(BaseModel):
    """A group of conditions (or nested composite conditions) combined
    with a single boolean combinator. No mixed AND/OR within one
    CompositeCondition -- combining different combinators means nesting
    another CompositeCondition inside `conditions`, so precedence is
    always explicit in the tree's shape, never inferred from operator
    precedence rules a reader would have to remember."""

    combinator: Literal["AND", "OR"]
    conditions: list["ConditionNode"] = Field(default_factory=list)


ConditionNode = Union[Condition, CompositeCondition]
CompositeCondition.model_rebuild()


class RuleAction(BaseModel):
    """What the rule concludes when its root condition (and no
    exception) matches. `decision` is a free-text label chosen by the
    rule's author (e.g. "approve", "deny", "escalate:finance") --
    Decision Intelligence does not constrain it to a fixed vocabulary,
    since that vocabulary is specific to each organisation's workflow."""

    decision: str
    human_review_required: bool = False


class RuleSchema(BaseModel):
    """The complete, versioned rule: a root condition tree, the action it
    produces when matched, an optional list of exception conditions that
    override the root match back to "does not apply", and an explicit
    policy for what happens when a referenced fact is simply absent from
    a case (`missing_data_behavior`) -- deciding that in the rule itself,
    rather than leaving it to whatever the evaluator happens to do, is
    what keeps a rule's behaviour fully determined by its own stored
    schema_json."""

    root_condition: "ConditionNode"
    action: RuleAction
    exceptions: list["ConditionNode"] = Field(default_factory=list)
    missing_data_behavior: Literal["route_to_human", "fail", "treat_as_false"] = "route_to_human"


RuleSchema.model_rebuild()
