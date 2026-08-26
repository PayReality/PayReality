from datetime import datetime, timezone

from app.domain.compiler_v2.compiler_errors import (
    CONFLICTING_POLICY_STRUCTURE,
    INVALID_ACTION,
    INVALID_FIELD,
    INVALID_RESOURCE,
    INVALID_RUNTIME_POLICY,
)
from app.domain.compiler_v2.compiler_v2 import FinancialVocabulary, compile_bundle
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope

FIXED_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _policy(**overrides) -> RuntimePolicy:
    defaults = dict(
        id="rp-1",
        name="Vendor Payment",
        version=1,
        status=PolicyStatus.APPROVED,
        scope=Scope(principal="prin_1", action="vendor_payment"),
        conditions=ConditionSet(
            all=(Condition(field="amount", operator=Operator.LTE, value=100000),)
        ),
        effect=Effect.ALLOW,
    )
    defaults.update(overrides)
    return RuntimePolicy(**defaults)


def test_successful_compilation_produces_a_bundle_with_no_errors():
    result = compile_bundle([_policy()], "bundle-1", 1, now=FIXED_NOW)
    assert result.ok
    assert result.bundle is not None
    assert result.diagnostics.ok


def test_unrecognized_action_is_rejected():
    result = compile_bundle(
        [_policy(scope=Scope(principal="prin_1", action="do_something_unknown"))],
        "bundle-1",
        1,
        now=FIXED_NOW,
    )
    assert not result.ok
    assert result.bundle is None
    assert any(e.code == INVALID_ACTION for e in result.diagnostics.errors)


def test_recognized_actions_all_pass_the_default_financial_vocabulary():
    for action in ("vendor_payment", "purchase_order_create", "wire_transfer"):
        result = compile_bundle(
            [_policy(scope=Scope(principal="prin_1", action=action))],
            "bundle-1",
            1,
            now=FIXED_NOW,
        )
        assert result.ok, f"{action} should be a recognized action"


def test_blank_resource_is_rejected():
    result = compile_bundle(
        [_policy(scope=Scope(principal="prin_1", action="vendor_payment", resource="   "))],
        "bundle-1",
        1,
        now=FIXED_NOW,
    )
    assert not result.ok
    assert any(e.code == INVALID_RESOURCE for e in result.diagnostics.errors)


def test_malformed_runtime_policy_is_reported_not_raised():
    """An empty name is a Phase 1 validators.py failure; compile_bundle
    must surface it as a diagnostic, never let validators.py's exception
    contract (never raises) become an exception here either."""
    result = compile_bundle([_policy(name="")], "bundle-1", 1, now=FIXED_NOW)
    assert not result.ok
    assert any(e.code == INVALID_RUNTIME_POLICY for e in result.diagnostics.errors)


def test_conflicting_numeric_limits_for_same_principal_and_action_are_detected():
    p1 = _policy(
        id="rp-1",
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value=100000),)),
    )
    p2 = _policy(
        id="rp-2",
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value=50000),)),
    )
    result = compile_bundle([p1, p2], "bundle-1", 1, now=FIXED_NOW)
    assert not result.ok
    assert any(e.code == CONFLICTING_POLICY_STRUCTURE for e in result.diagnostics.errors)


def test_contradictory_equality_conditions_are_detected():
    p1 = _policy(
        id="rp-1",
        conditions=ConditionSet(all=(Condition(field="currency", operator=Operator.EQ, value="ZAR"),)),
    )
    p2 = _policy(
        id="rp-2",
        conditions=ConditionSet(all=(Condition(field="currency", operator=Operator.EQ, value="USD"),)),
    )
    result = compile_bundle([p1, p2], "bundle-1", 1, now=FIXED_NOW)
    assert not result.ok
    assert any(e.code == CONFLICTING_POLICY_STRUCTURE for e in result.diagnostics.errors)


def test_non_overlapping_scope_does_not_trigger_conflict_detection():
    p1 = _policy(id="rp-1", scope=Scope(principal="prin_1", action="vendor_payment"))
    p2 = _policy(id="rp-2", scope=Scope(principal="prin_2", action="vendor_payment"))
    result = compile_bundle([p1, p2], "bundle-1", 1, now=FIXED_NOW)
    assert result.ok


def test_cross_field_conflicts_are_now_detected():
    """This used to be the documented gap (COMPILER_V2_ARCHITECTURE.md's
    "different fields are not analyzed"): two policies constraining
    different fields, for the same principal/action, with nothing in
    either policy that actually rules the other out, so a real Intent
    (any amount <= 100000, currency == USD) could satisfy both.
    ConditionSet's flat-AND, single-field-per-Condition shape (no cross-
    field relations expressible at all) is what makes this decomposable
    into independent per-field checks rather than a real satisfiability
    search -- see scope_overlap.py's module docstring."""
    p1 = _policy(
        id="rp-1",
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value=100000),)),
    )
    p2 = _policy(
        id="rp-2",
        conditions=ConditionSet(
            all=(Condition(field="currency", operator=Operator.EQ, value="USD"),)
        ),
    )
    result = compile_bundle([p1, p2], "bundle-1", 1, now=FIXED_NOW)
    assert not result.ok
    assert any(e.code == CONFLICTING_POLICY_STRUCTURE for e in result.diagnostics.errors)


def test_disjoint_numeric_ranges_across_different_operators_do_not_conflict():
    """amount<=50000 and amount>=60000 can never both hold for the same
    value, even though they're different operators on the same field (the
    old "same operator only" heuristic wouldn't even have compared these
    two conditions to each other)."""
    p1 = _policy(
        id="rp-1",
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value=50000),)),
    )
    p2 = _policy(
        id="rp-2",
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.GTE, value=60000),)),
    )
    result = compile_bundle([p1, p2], "bundle-1", 1, now=FIXED_NOW)
    assert result.ok


def test_overlapping_ranges_across_different_operators_do_conflict():
    """amount<=50000 and amount>=30000 overlap on [30000, 50000] -- a real
    Intent in that range would satisfy both, even though LTE and GTE are
    different operators."""
    p1 = _policy(
        id="rp-1",
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value=50000),)),
    )
    p2 = _policy(
        id="rp-2",
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.GTE, value=30000),)),
    )
    result = compile_bundle([p1, p2], "bundle-1", 1, now=FIXED_NOW)
    assert not result.ok
    assert any(e.code == CONFLICTING_POLICY_STRUCTURE for e in result.diagnostics.errors)


def test_specific_agent_disambiguates_otherwise_conflicting_policies():
    """Same principal/action/conditions, but scoped to two different,
    specific agents: no real Intent (which names exactly one acting
    agent) could ever match both, so this is not a conflict."""
    p1 = _policy(
        id="rp-1",
        scope=Scope(principal="prin_1", action="vendor_payment", agent="agent-a"),
    )
    p2 = _policy(
        id="rp-2",
        scope=Scope(principal="prin_1", action="vendor_payment", agent="agent-b"),
    )
    result = compile_bundle([p1, p2], "bundle-1", 1, now=FIXED_NOW)
    assert result.ok


def test_unscoped_agent_still_conflicts_with_a_specific_one():
    """scope.agent=None means "any agent," so it still overlaps with a
    policy scoped to one specific agent -- only two *different*, both
    *specific* agents disambiguate."""
    p1 = _policy(id="rp-1", scope=Scope(principal="prin_1", action="vendor_payment"))
    p2 = _policy(
        id="rp-2",
        scope=Scope(principal="prin_1", action="vendor_payment", agent="agent-a"),
    )
    result = compile_bundle([p1, p2], "bundle-1", 1, now=FIXED_NOW)
    assert not result.ok


def test_non_overlapping_in_sets_do_not_conflict():
    p1 = _policy(
        id="rp-1",
        conditions=ConditionSet(all=(Condition(field="currency", operator=Operator.IN, value=["USD", "GBP"]),)),
    )
    p2 = _policy(
        id="rp-2",
        conditions=ConditionSet(all=(Condition(field="currency", operator=Operator.IN, value=["ZAR", "EUR"]),)),
    )
    result = compile_bundle([p1, p2], "bundle-1", 1, now=FIXED_NOW)
    assert result.ok


def test_overlapping_in_sets_do_conflict():
    p1 = _policy(
        id="rp-1",
        conditions=ConditionSet(all=(Condition(field="currency", operator=Operator.IN, value=["USD", "GBP"]),)),
    )
    p2 = _policy(
        id="rp-2",
        conditions=ConditionSet(all=(Condition(field="currency", operator=Operator.IN, value=["USD", "EUR"]),)),
    )
    result = compile_bundle([p1, p2], "bundle-1", 1, now=FIXED_NOW)
    assert not result.ok


def test_contains_operator_conservatively_flags_as_a_conflict():
    """No interval structure to reason about for `contains`, so this
    fails closed (assumes overlap) rather than silently claiming safety
    -- same posture as every other "can't actually prove this" case in
    this compiler."""
    p1 = _policy(
        id="rp-1",
        conditions=ConditionSet(all=(Condition(field="currency", operator=Operator.CONTAINS, value="refund"),)),
    )
    p2 = _policy(
        id="rp-2",
        conditions=ConditionSet(all=(Condition(field="currency", operator=Operator.CONTAINS, value="invoice"),)),
    )
    result = compile_bundle([p1, p2], "bundle-1", 1, now=FIXED_NOW)
    assert not result.ok


def test_custom_vocabulary_can_be_injected():
    class ToyVocabulary:
        def is_valid_action(self, action: str) -> bool:
            return action == "grant_access"

        def is_valid_field(self, field: str) -> bool:
            return True

    result = compile_bundle(
        [_policy(scope=Scope(principal="prin_1", action="grant_access"))],
        "bundle-1",
        1,
        vocabulary=ToyVocabulary(),
        now=FIXED_NOW,
    )
    assert result.ok


def test_financial_vocabulary_matches_todays_known_scopes():
    """Cross-check against scope_vocabulary.py's actual current content,
    so this default can never silently drift from the one real adapter
    that exists."""
    from app.domain.decision.scope_vocabulary import KNOWN_SCOPES

    assert FinancialVocabulary().known_actions == KNOWN_SCOPES


def test_typo_d_condition_field_is_rejected_at_compile_time():
    """The bug this vocabulary closes: a condition authored against a
    field that doesn't exist on a real Intent used to compile cleanly
    and simply never match at evaluation time, with no error anywhere."""
    result = compile_bundle(
        [_policy(conditions=ConditionSet(all=(Condition(field="amoutn", operator=Operator.LTE, value=100000),)))],
        "bundle-1",
        1,
        now=FIXED_NOW,
    )
    assert not result.ok
    assert any(e.code == INVALID_FIELD for e in result.diagnostics.errors)


def test_recognized_intent_fields_all_pass():
    for field_name in ("action", "amount", "currency"):
        result = compile_bundle(
            [_policy(conditions=ConditionSet(all=(Condition(field=field_name, operator=Operator.EQ, value="x"),)))],
            "bundle-1",
            1,
            now=FIXED_NOW,
        )
        assert result.ok, f"{field_name} should be a recognized intent field"


def test_context_prefixed_fields_are_always_valid():
    """context.* is a caller-extensible, free-form enrichment dict
    (PHASE_2_RUNTIME_CONTEXT.md) -- not a fixed schema this compiler
    could enumerate without rejecting a real, valid future field."""
    result = compile_bundle(
        [
            _policy(
                conditions=ConditionSet(
                    all=(Condition(field="context.authority.department", operator=Operator.EQ, value="Finance"),)
                )
            )
        ],
        "bundle-1",
        1,
        now=FIXED_NOW,
    )
    assert result.ok


def test_nested_path_on_a_known_top_level_field_is_still_valid():
    """Only the top-level segment is validated -- a real Intent field
    that happens to carry nested structure isn't rejected just because
    this compiler doesn't track its internal shape."""
    result = compile_bundle(
        [_policy(conditions=ConditionSet(all=(Condition(field="amount.sub_total", operator=Operator.EQ, value=1),)))],
        "bundle-1",
        1,
        now=FIXED_NOW,
    )
    assert result.ok


# -- Domain Generalization Milestone --------------------------------------


def test_default_vocabulary_is_generic_not_financial():
    """The default every real call site silently inherits is
    GENERIC_VOCABULARY, not FINANCIAL_VOCABULARY -- a bounded,
    explicitly-authored enumeration that includes a proven non-
    financial action, not an unbounded accept-anything vocabulary."""
    from app.domain.compiler_v2.compiler_v2 import GENERIC_VOCABULARY

    import inspect

    default_vocabulary = inspect.signature(compile_bundle).parameters["vocabulary"].default
    assert default_vocabulary is GENERIC_VOCABULARY


def test_disable_user_compiles_under_the_default_vocabulary():
    """The concrete, explicitly-authored non-financial action this
    milestone proves the platform supports -- and it compiles under
    whatever vocabulary a real call site actually gets today (the
    default), not just under an explicit custom Vocabulary."""
    result = compile_bundle(
        [_policy(scope=Scope(principal="prin_1", action="disable_user"))],
        "bundle-1",
        1,
        now=FIXED_NOW,
    )
    assert result.ok, f"disable_user should compile under the default vocabulary: {result.diagnostics}"


def test_a_genuinely_unauthored_action_is_still_rejected_under_the_generic_default():
    """GENERIC_VOCABULARY is a bounded enumeration, not "any string" --
    confirms the new default doesn't quietly relax the original
    typo-protection test_unrecognized_action_is_rejected already
    covers for the old default."""
    result = compile_bundle(
        [_policy(scope=Scope(principal="prin_1", action="do_something_unknown"))],
        "bundle-1",
        1,
        now=FIXED_NOW,
    )
    assert not result.ok
    assert any(e.code == INVALID_ACTION for e in result.diagnostics.errors)


def test_resource_is_a_recognized_intent_field_under_the_default_vocabulary():
    """Domain Generalization Milestone: `resource` joins action/amount/
    currency as a universal, always-valid top-level condition field --
    previously only the financial three were recognized."""
    result = compile_bundle(
        [_policy(conditions=ConditionSet(all=(Condition(field="resource", operator=Operator.EQ, value="x"),)))],
        "bundle-1",
        1,
        now=FIXED_NOW,
    )
    assert result.ok


def test_resource_scoped_disable_user_policy_compiles_and_generates_resource_matching_rego():
    """End-to-end compile-level proof (OPA-level matching behavior is
    covered by tests/integration/test_domain_generalization.py) that a
    non-financial, resource-scoped policy produces a real Rego resource
    comparison, the same mechanism financial policies already had
    available but never used."""
    policy = _policy(
        scope=Scope(principal="prin_1", action="disable_user", resource="account:USR-829"),
        conditions=ConditionSet(all=(Condition(field="context.environment", operator=Operator.EQ, value="production"),)),
    )
    result = compile_bundle([policy], "bundle-1", 1, now=FIXED_NOW)
    assert result.ok
    assert 'input.intent.resource == "account:USR-829"' in result.bundle.rego_source
