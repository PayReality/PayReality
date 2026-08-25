"""Compiler V2's orchestration: RuntimePolicy list -> validated -> Rego
generated -> assembled into one PolicyBundle, or a CompilerDiagnostics
explaining exactly why not. Never raises for a normal compilation
failure; see compiler_errors.py.

This module owns the two things DOMAIN_ABSTRACTION.md scoped as
"adapter-owned": which action names are valid, and which condition
field names are valid. It does so through an injectable Vocabulary
rather than a hardcoded list, so the compiler itself stays
domain-agnostic even though its one shipped default
(FINANCIAL_VOCABULARY) is not. This is the concrete implementation of
DOMAIN_REFACTOR_PLAN.md's item 2 and item 3.

Field validation closes a real, previously silent gap: a condition
authored against a typo'd or nonexistent field name
(rego_generator.py's `_dot_path_access` compiles it into a plain Rego
dot-path access) used to compile cleanly and simply never match at
evaluation time, with no error anywhere. Direct against
intent_service.py:507, the only place a real Intent dict is actually
built, its shape is exactly `{"action", "amount", "currency"}` -- no
`vendor`, no `memo`, nothing else -- so those are the only top-level
fields this default vocabulary accepts.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.decision.scope_vocabulary import KNOWN_SCOPES
from app.domain.runtime_policy.conditions import Operator
from app.domain.runtime_policy.runtime_policy import RuntimePolicy
from app.domain.runtime_policy.validators import validate as validate_runtime_policy

from app.domain.compiler_v2.bundle_builder import PolicyBundle, build_bundle
from app.domain.compiler_v2.compiler_errors import (
    CONFLICTING_POLICY_STRUCTURE,
    INVALID_ACTION,
    INVALID_FIELD,
    INVALID_RESOURCE,
    INVALID_RUNTIME_POLICY,
    CompilerDiagnostics,
    CompilerError,
)
from app.domain.compiler_v2.scope_overlap import policies_can_jointly_match

# A condition field prefixed "context." always passes vocabulary
# validation regardless of what follows: Runtime Authority Context
# (PHASE_2_RUNTIME_CONTEXT.md) is a caller-extensible, free-form dict
# (intent_service.py merges the caller's own `context` with `timestamp`
# and a resolved `authority` block), not a fixed schema this compiler
# could enumerate in advance without rejecting a real, valid enrichment
# field the moment a new connector adds one. This mirrors
# rego_generator.py's own _resolve_base_and_field, which already
# special-cases this same prefix for the identical reason.
_CONTEXT_FIELD_PREFIX = "context."
# Trusted Enterprise Facts (ENTERPRISE_KNOWLEDGE_DECISION_RECORD.md
# Decision 5): the mirror-image exception to _CONTEXT_FIELD_PREFIX above,
# for the new `enterprise_knowledge` OPA input section
# (domain/decision/engine.py's build_opa_input). Also caller-extensible
# (an org-registered FactSource can attest any fact key), so it can no
# more be enumerated in advance than `context.` can -- same reasoning,
# same treatment. rego_generator.py's own _resolve_base_and_field carries
# the matching prefix so this is a real, not just a permissive, mapping.
_ENTERPRISE_KNOWLEDGE_FIELD_PREFIX = "enterprise_knowledge."


class Vocabulary(Protocol):
    """What a domain adapter must answer for Compiler V2 to validate
    actions and condition fields against it (DOMAIN_ABSTRACTION.md)."""

    def is_valid_action(self, action: str) -> bool: ...
    def is_valid_field(self, field: str) -> bool: ...


@dataclass(frozen=True)
class FinancialVocabulary:
    """Today's actual KNOWN_SCOPES (scope_vocabulary.py).

    Runtime Governance Architecture, Phase 3
    (28_PHASE_3_CANONICAL_FACT_INTELLIGENCE_SPEC.md): this default used to
    hand-copy KNOWN_SCOPES' three literal strings instead of importing
    them -- two independently-written definitions of the same fact
    ("action"), kept in sync only by convention, exactly the identity
    problem Canonical Fact Intelligence exists to catch. Now imports the
    one real definition instead of duplicating it. Zero behavior change:
    the three strings are identical; this only guarantees they can never
    silently drift apart."""

    known_actions: frozenset[str] = KNOWN_SCOPES
    # Exactly intent_service.py:507's real intent dict shape -- see this
    # module's own docstring for why. "context" is deliberately absent
    # here: it's handled separately, as a prefix, not a top-level field.
    known_intent_fields: frozenset[str] = frozenset({"action", "amount", "currency"})

    def is_valid_action(self, action: str) -> bool:
        return action in self.known_actions

    def is_valid_field(self, field: str) -> bool:
        if field.startswith(_CONTEXT_FIELD_PREFIX) or field.startswith(_ENTERPRISE_KNOWLEDGE_FIELD_PREFIX):
            return True
        top_level = field.split(".", 1)[0]
        return top_level in self.known_intent_fields


FINANCIAL_VOCABULARY = FinancialVocabulary()


@dataclass(frozen=True)
class CompileResult:
    bundle: PolicyBundle | None
    diagnostics: CompilerDiagnostics

    @property
    def ok(self) -> bool:
        return self.diagnostics.ok and self.bundle is not None


def _validate_policy_against_vocabulary(
    policy: RuntimePolicy, vocabulary: Vocabulary
) -> list[CompilerError]:
    errors: list[CompilerError] = []
    if not vocabulary.is_valid_action(policy.scope.action):
        errors.append(
            CompilerError(
                code=INVALID_ACTION,
                message=f"'{policy.scope.action}' is not a recognized action for this domain",
                policy_id=policy.id,
                path="scope.action",
            )
        )
    if policy.scope.resource is not None and not policy.scope.resource.strip():
        errors.append(
            CompilerError(
                code=INVALID_RESOURCE,
                message="scope.resource, if present, must not be blank",
                policy_id=policy.id,
                path="scope.resource",
            )
        )
    for condition in policy.conditions.all:
        if not vocabulary.is_valid_field(condition.field):
            errors.append(
                CompilerError(
                    code=INVALID_FIELD,
                    message=f"'{condition.field}' is not a recognized condition field for this domain",
                    policy_id=policy.id,
                    path=f"conditions.{condition.field}",
                )
            )
    return errors


def _policy_conflicts(policies: list[RuntimePolicy]) -> list[CompilerError]:
    """Flags any two policies whose scope and conditions could both match
    the same real Intent (scope_overlap.policies_can_jointly_match): exact
    for every operator except contains/exists, which fail closed to
    "assume overlap" rather than silently claiming safety. Flagged
    regardless of whether the two policies' effects agree -- two `allow`
    policies with different amount caps for the same scope are still
    ambiguous authoring, not a runtime bug, and this compiler has always
    treated that as worth blocking (see
    test_conflicting_numeric_limits_for_same_principal_and_action_are_detected).

    Grouped by (principal, action) first, purely as a cheap pre-filter:
    two policies for different principals or actions can never overlap,
    so there's no need to run the full per-field check on them. agent/
    resource narrowing (which CAN disambiguate two same-principal-action
    policies) is checked inside policies_can_jointly_match itself, not
    here, since scope.agent=None means "any agent" and so isn't safe to
    bucket on directly.
    """
    errors: list[CompilerError] = []
    by_scope: dict[tuple[str, str], list[RuntimePolicy]] = {}
    for p in policies:
        by_scope.setdefault((p.scope.principal, p.scope.action), []).append(p)

    for group in by_scope.values():
        if len(group) < 2:
            continue
        for i, p1 in enumerate(group):
            for p2 in group[i + 1 :]:
                if policies_can_jointly_match(p1, p2) or _has_contradictory_equality(p1, p2):
                    errors.append(_conflict_error(p1, p2))

    return errors


def _has_contradictory_equality(p1: RuntimePolicy, p2: RuntimePolicy) -> bool:
    """The original, narrower rule (POLICY_COMPILER_V2.md), kept as its
    own explicit check rather than folded into policies_can_jointly_match:
    two EQ conditions on the same field with different values are
    logically *disjoint* (no Intent can be both currencies at once), so
    scope_overlap's genuine-overlap logic correctly says they can't both
    match -- but this compiler has always flagged the authoring pattern
    itself (two separate RuntimePolicies split by exact-match value on
    what's arguably one field, rather than one policy with an `in` list)
    as worth surfacing, independent of whether it's a real ambiguity."""
    for c1 in p1.conditions.all:
        if c1.operator != Operator.EQ:
            continue
        for c2 in p2.conditions.all:
            if c2.operator == Operator.EQ and c2.field == c1.field and c2.value != c1.value:
                return True
    return False


def _conflict_error(p1: RuntimePolicy, p2: RuntimePolicy) -> CompilerError:
    fields = sorted({c.field for c in p1.conditions.all} | {c.field for c in p2.conditions.all})
    return CompilerError(
        code=CONFLICTING_POLICY_STRUCTURE,
        message=(
            f"policies '{p1.id}' and '{p2.id}' both apply to principal '{p1.scope.principal}' "
            f"action '{p1.scope.action}' and their conditions ({', '.join(fields) or 'none'}) "
            "are not proven mutually exclusive -- some real Intent could match both"
        ),
        policy_id=p1.id,
        path=fields[0] if fields else None,
    )


def compile_bundle(
    policies: list[RuntimePolicy],
    bundle_id: str,
    bundle_version: int,
    vocabulary: Vocabulary = FINANCIAL_VOCABULARY,
    now: datetime | None = None,
) -> CompileResult:
    """The only entry point this package expects callers to use. Always
    returns a CompileResult; bundle is None whenever diagnostics has any
    error. Runs, in order: RuntimePolicy structural validation (reused
    from Phase 1, not reimplemented), vocabulary validation (action,
    resource, condition fields), conflict detection, then, only if all
    of that is clean, Rego generation and bundle assembly."""
    errors: list[CompilerError] = []

    for policy in policies:
        result = validate_runtime_policy(policy)
        if not result.ok:
            for e in result.errors:
                errors.append(
                    CompilerError(
                        code=INVALID_RUNTIME_POLICY,
                        message=f"{e.code}: {e.message}",
                        policy_id=policy.id,
                        path=e.field,
                    )
                )
        errors.extend(_validate_policy_against_vocabulary(policy, vocabulary))

    errors.extend(_policy_conflicts(policies))

    if errors:
        return CompileResult(bundle=None, diagnostics=CompilerDiagnostics(errors=tuple(errors)))

    bundle = build_bundle(policies, bundle_id=bundle_id, bundle_version=bundle_version, now=now)
    return CompileResult(bundle=bundle, diagnostics=CompilerDiagnostics())
