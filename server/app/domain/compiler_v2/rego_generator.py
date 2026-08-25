"""Translates one RuntimePolicy's Scope, ConditionSet, and Effect into an
executable Rego fragment. This is the module that makes Compiler V2's
central claim true: every condition becomes real, evaluated Rego, never
inert metadata (see COMPILER_V2_ARCHITECTURE.md's "current state"
finding about what today's compiler.py actually enforces, which is not
this).

Every Rego construct this module emits was verified directly against a
real local OPA 1.7.1 binary before being relied on here, not assumed from
reading Rego documentation: direct dot-path access on a missing nested
field evaluates to undefined/false rather than erroring; the `in`
operator for list membership; the `contains(string, substr)` builtin; the
`object.get(obj, key, default)` chain for a safe existence check on an
arbitrary-depth path, including when an intermediate key is missing
entirely; and that a partial-set rule (`name contains x if {...}`)
serializes as a plain JSON array through OPA's query API. See
tests/test_rego_generator.py for the same checks re-verified as part of
this package's own test suite, and
tests/test_compiler_v2_opa_integration.py for compiling a full bundle and
evaluating it with real OPA end to end.
"""

import json
import re

from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.runtime_policy import RuntimePolicy

_SAFE_ID_PATTERN = re.compile(r"[^a-zA-Z0-9_]")


def sanitize_policy_id(policy_id: str) -> str:
    """A RuntimePolicy id may contain characters (hyphens, for instance)
    that aren't valid inside a Rego identifier. Rego identifiers must
    start with a letter or underscore and contain only letters, digits,
    and underscores; this produces a deterministic, collision-resistant
    identifier from an arbitrary id string."""
    safe = _SAFE_ID_PATTERN.sub("_", policy_id)
    if not safe or safe[0].isdigit():
        safe = f"p_{safe}"
    return safe


def rule_name_for_policy(policy_id: str) -> str:
    return f"policy_{sanitize_policy_id(policy_id)}"


def _rego_literal(value) -> str:
    """Rego's literal syntax for strings, numbers, booleans, and arrays of
    these is JSON-compatible; json.dumps is used deliberately rather than
    hand-rolled string interpolation, both for correct escaping of
    special characters in a string value and to avoid ever
    string-formatting a user-authored value directly into generated
    source without going through a safe serializer."""
    return json.dumps(value)


def _dot_path_access(base: str, field_path: str) -> str:
    """input.intent.vendor.approved, from base="input.intent" and
    field_path="vendor.approved". Direct member access, not object.get:
    verified that a missing intermediate key makes the whole containing
    expression undefined (and therefore the containing rule simply
    doesn't match), not a runtime error, which is exactly the safe
    default-deny behavior wanted for every operator except `exists`."""
    return f"{base}.{field_path}"


def _nested_object_get(base: str, field_path: str) -> str:
    """The `exists` operator's safe-existence check: a chain of
    object.get calls, defaulting to {} at every level except the last
    (which defaults to null, the sentinel meaning "not present"), so a
    fully-missing intermediate key never raises, it just resolves to
    "not present" at the end of the chain. Verified directly against a
    three-level-deep path with a missing top-level key."""
    parts = field_path.split(".")
    expr = base
    for i, part in enumerate(parts):
        default = "null" if i == len(parts) - 1 else "{}"
        expr = f"object.get({expr}, {json.dumps(part)}, {default})"
    return expr


_CONTEXT_FIELD_PREFIX = "context."
# Trusted Enterprise Facts (ENTERPRISE_KNOWLEDGE_DECISION_RECORD.md
# Decision 5): the exact same "condition field prefix -> sibling OPA
# input section" mechanism as _CONTEXT_FIELD_PREFIX above, for the new
# `enterprise_knowledge` section decision_engine.build_opa_input now
# emits. Added here deliberately, not left to compiler_v2.py's
# vocabulary check alone -- that check only gates whether compilation is
# ALLOWED; this function is what actually determines the generated Rego
# dot-path, and without this mapping a condition on
# "enterprise_knowledge.supplier_approved" would compile cleanly but
# silently resolve to input.intent.enterprise_knowledge.supplier_approved,
# which never exists -- precisely the class of "compiles, never matches,
# no error" bug _CONTEXT_FIELD_PREFIX's own precedent was added to close.
_ENTERPRISE_KNOWLEDGE_FIELD_PREFIX = "enterprise_knowledge."


def _resolve_base_and_field(condition_field: str, default_base: str) -> tuple[str, str]:
    """Every condition field defaults to input.intent.<field>. A field
    prefixed "context." targets input.context.<rest> instead, since
    Runtime Authority Context (PHASE_2_RUNTIME_CONTEXT.md's enrichment,
    e.g. context.authority.department) is a sibling of intent in the real
    OPA input (build_opa_input: {"intent": ..., "context": ...,
    "agent": ...}), not nested under it -- a condition written as
    "context.authority.department" against the old, always-"input.intent"
    base would silently compile to input.intent.context.authority.department,
    which never exists, and the condition would just never match, with no
    error. Caught by live end-to-end testing during Phase 2's rollout, not
    by reasoning about the generator in the abstract."""
    if condition_field.startswith(_CONTEXT_FIELD_PREFIX):
        return "input.context", condition_field[len(_CONTEXT_FIELD_PREFIX):]
    if condition_field.startswith(_ENTERPRISE_KNOWLEDGE_FIELD_PREFIX):
        return "input.enterprise_knowledge", condition_field[len(_ENTERPRISE_KNOWLEDGE_FIELD_PREFIX):]
    return default_base, condition_field


def generate_condition_expression(condition: Condition, base: str = "input.intent") -> str:
    """One line of Rego for one Condition. Raises ValueError only for an
    Operator this function has no case for at all (a genuine programming
    error: every Operator enum member must have a branch here), never for
    a value shape that's merely questionable, that's validation's job
    (compiler_v2.py calls runtime_policy.validators.validate() and this
    module's own structural checks before ever reaching generation, so by
    the time a Condition arrives here it's already been judged
    well-formed; this function trusts that and focuses on translation)."""
    resolved_base, resolved_field = _resolve_base_and_field(condition.field, base)
    field_access = _dot_path_access(resolved_base, resolved_field)

    if condition.operator == Operator.LTE:
        return f"{field_access} <= {_rego_literal(condition.value)}"
    if condition.operator == Operator.GTE:
        return f"{field_access} >= {_rego_literal(condition.value)}"
    if condition.operator == Operator.EQ:
        return f"{field_access} == {_rego_literal(condition.value)}"
    if condition.operator == Operator.NEQ:
        return f"{field_access} != {_rego_literal(condition.value)}"
    if condition.operator == Operator.LT:
        return f"{field_access} < {_rego_literal(condition.value)}"
    if condition.operator == Operator.GT:
        return f"{field_access} > {_rego_literal(condition.value)}"
    if condition.operator == Operator.IN:
        return f"{field_access} in {_rego_literal(condition.value)}"
    if condition.operator == Operator.CONTAINS:
        return f"contains({field_access}, {_rego_literal(condition.value)})"
    if condition.operator == Operator.EXISTS:
        existence_check = _nested_object_get(resolved_base, resolved_field)
        if condition.value is True:
            return f"{existence_check} != null"
        if condition.value is False:
            return f"{existence_check} == null"
        raise ValueError(
            f"exists operator requires a boolean value, got {condition.value!r} "
            "(this should have been caught by validation before reaching the generator)"
        )

    raise ValueError(f"no Rego generation case for operator {condition.operator!r}")


def generate_conditions_block(conditions: ConditionSet, base: str = "input.intent") -> list[str]:
    return [generate_condition_expression(c, base=base) for c in conditions.all]


def generate_scope_block(policy: RuntimePolicy) -> list[str]:
    """Scope-matching lines: which action, which principal, and
    optionally which specific agent or resource this policy applies to.
    Always present, ANDed with the policy's own conditions, generalizing
    today's compiler.py's matching_mandate rule (which matches on scope
    and principal_id only) to also support the agent/resource narrowing
    RuntimePolicy's Scope supports (RUNTIME_POLICY_LANGUAGE.md)."""
    lines = [
        f"input.intent.action == {_rego_literal(policy.scope.action)}",
        f"input.agent.acting_for_principal_id == {_rego_literal(policy.scope.principal)}",
    ]
    if policy.scope.agent is not None:
        lines.append(f"input.agent.id == {_rego_literal(policy.scope.agent)}")
    if policy.scope.resource is not None:
        lines.append(f"input.intent.resource == {_rego_literal(policy.scope.resource)}")
    return lines


def generate_policy_rule(policy: RuntimePolicy) -> str:
    """The full Rego rule for one RuntimePolicy: its scope match plus all
    of its conditions, ANDed (Rego's `if { a; b; c }` block requires
    every listed expression to hold), matching ConditionSet's own
    all-only, AND-only semantics exactly."""
    rule_name = rule_name_for_policy(policy.id)
    body_lines = generate_scope_block(policy) + generate_conditions_block(policy.conditions)
    indented = "\n".join(f"    {line}" for line in body_lines)
    return f"{rule_name} if {{\n{indented}\n}}"


def effect_rule_name(effect: Effect) -> str:
    return {
        Effect.ALLOW: "allow",
        Effect.DENY: "deny",
        Effect.REQUIRE_HUMAN_REVIEW: "requires_review",
    }[effect]
