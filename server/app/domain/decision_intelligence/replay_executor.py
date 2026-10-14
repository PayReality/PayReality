"""Pure classification logic for a Replay: given one case's rule
evaluation and its historical baseline decision (if any), decide which
single `outcome_category` it belongs to.

Deliberately pure -- no database access, no ORM models, no I/O. This
codebase enforces a hard architectural boundary (SPECIFICATION/
26_PHASE_2_DEPENDENCY_DECLARATION.md section 26.4.2, verified by test_
architectural_boundaries.py::test_domain_package_never_imports_app_db)
that nothing under domain/ may import app.db, so the actual persistence
of a replay run (loading DIRuleVersion/DICase rows, writing
DIReplayCaseResult rows, updating DIReplayRun's own status/summary) lives
in the service layer instead -- see
services/di_replay_service.py's own module docstring for the orchestration
this module's `evaluate_case` feeds into.

Critical naming/semantics discipline (this module's own brief): an
`outcome_category` measures AGREEMENT with a historical human decision,
never CORRECTNESS of either the historical decision or the candidate
rule. "agrees_with_baseline" means the proposed decision matches what a
human already decided for that case -- it does not mean the rule, or the
original human decision, was right. Nothing in this module, its variable
names, or its stored data may be read as a correctness claim.
"""

from __future__ import annotations

from app.domain.decision_intelligence.rule_evaluator import EvaluationResult, evaluate_rule
from app.domain.decision_intelligence.rule_schema import RuleSchema

OUTCOME_CATEGORIES = (
    "agrees_with_baseline",
    "disagrees_with_baseline",
    "resolved_automatically",
    "requires_human_review",
    "missing_data",
    "error",
)


def _baseline_decision_label(human_decision: dict | str | None) -> str | None:
    """`DICase.human_decision` has no fixed schema (this module's own
    design brief); this extracts a single comparable label from whatever
    shape it was recorded in, so it can be compared against a rule's own
    `action.decision` string. A dict is expected to carry a "decision"
    key (the same field name RuleAction itself uses); anything else
    (a bare string, or a dict without that key) falls back to treating
    the whole value as the label, so a simply-recorded `"approve"` still
    compares sensibly against a rule whose action.decision is "approve"."""
    if human_decision is None:
        return None
    if isinstance(human_decision, dict):
        if "decision" in human_decision:
            return human_decision["decision"]
        return None
    return str(human_decision)


def classify_outcome(evaluation: EvaluationResult, human_decision: dict | str | None) -> tuple[str, str | None]:
    """Returns (outcome_category, notes). One of OUTCOME_CATEGORIES,
    always -- "error" is reserved for the caller (evaluation itself
    raising), never produced by this function."""
    if evaluation.missing_fields and evaluation.decision is None and not evaluation.matched:
        # evaluate_rule only forces matched=False/decision=None on missing
        # data when the rule's own missing_data_behavior says to (route_to_
        # human or fail) -- see its own docstring. Both read as "missing
        # data" here; the distinction between "route to a human" and
        # "simply failed" is preserved in human_review_required, not lost,
        # just not split into two different outcome_category values (the
        # product's fixed vocabulary has only one "missing_data" value).
        return "missing_data", f"missing_fields={evaluation.missing_fields}"

    if evaluation.matched and evaluation.human_review_required:
        return "requires_human_review", None

    baseline_label = _baseline_decision_label(human_decision)
    if baseline_label is not None:
        proposed_label = evaluation.decision
        if proposed_label == baseline_label:
            return "agrees_with_baseline", None
        return "disagrees_with_baseline", f"baseline={baseline_label!r} proposed={proposed_label!r}"

    return "resolved_automatically", None


def evaluate_case(
    rule: RuleSchema, case_facts: dict, human_decision: dict | str | None
) -> tuple[EvaluationResult, str, str | None]:
    """Convenience wrapper combining the single shared `evaluate_rule`
    interpreter with this module's own classification -- still fully
    pure (no DB), and the exact computation both the real replay executor
    and (indirectly, via evaluate_rule alone) the "test this rule"
    endpoint rely on, so they can never silently diverge.

    Returns (evaluation_result, outcome_category, notes). Raises whatever
    evaluate_rule itself raises for a malformed rule tree -- callers that
    must never let one bad case abort an entire batch (the replay
    executor) are responsible for catching that themselves and recording
    it as an "error" outcome."""
    evaluation = evaluate_rule(rule, case_facts)
    outcome_category, notes = classify_outcome(evaluation, human_decision)
    return evaluation, outcome_category, notes
