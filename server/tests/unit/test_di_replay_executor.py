"""Unit tests for classify_outcome (domain/decision_intelligence/
replay_executor.py), the pure function deciding a replay's per-case
outcome_category. No DB, no ORM, hand-constructed EvaluationResult
inputs with the expected classification known in advance."""

from app.domain.decision_intelligence.replay_executor import classify_outcome
from app.domain.decision_intelligence.rule_evaluator import EvaluationResult


def _evaluation(matched, decision, human_review_required=False, missing_fields=None, unmatched_conditions=None):
    return EvaluationResult(
        matched=matched,
        decision=decision,
        human_review_required=human_review_required,
        matched_conditions=["amount lte 150"] if matched else [],
        unmatched_conditions=unmatched_conditions or ([] if matched else ["amount lte 150"]),
        missing_fields=missing_fields or [],
    )


def test_matched_with_agreeing_baseline():
    category, notes = classify_outcome(_evaluation(matched=True, decision="approve"), {"decision": "approve"})
    assert category == "agrees_with_baseline"
    assert notes is None


def test_matched_with_disagreeing_baseline():
    category, notes = classify_outcome(_evaluation(matched=True, decision="approve"), {"decision": "deny"})
    assert category == "disagrees_with_baseline"
    assert "approve" in notes and "deny" in notes


def test_matched_with_human_review_required_overrides_baseline_comparison():
    category, notes = classify_outcome(
        _evaluation(matched=True, decision="approve", human_review_required=True), {"decision": "approve"}
    )
    assert category == "requires_human_review"


def test_missing_fields_with_no_match_and_no_decision():
    category, notes = classify_outcome(
        _evaluation(matched=False, decision=None, missing_fields=["amount"]), {"decision": "approve"}
    )
    assert category == "missing_data"
    assert "amount" in notes


def test_matched_with_no_recorded_baseline_is_resolved_automatically():
    """A real decision was proposed (the rule's conditions matched); there
    is simply no historical baseline to compare it against. This is a
    genuine automatic resolution."""
    category, notes = classify_outcome(_evaluation(matched=True, decision="approve"), None)
    assert category == "resolved_automatically"


def test_unmatched_with_no_recorded_baseline_requires_human_review():
    """Disclosed bug, fixed: previously this returned "resolved_automatically"
    unconditionally whenever there was no baseline, even when the rule's own
    conditions did NOT match and no decision was produced. A case the rule
    doesn't cover, with nothing to compare it against either, has not been
    resolved by anything; it must be routed to a human, not reported as if
    the system had handled it."""
    category, notes = classify_outcome(_evaluation(matched=False, decision=None), None)
    assert category == "requires_human_review"
    assert notes is not None
