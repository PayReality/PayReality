"""Decision Intelligence: pure-function unit tests for scoring.py,
matching this codebase's established "pure logic, no DB" convention
(test_rbac_permissions.py, test_compiler_v2.py)."""

from app.domain.decision_intelligence.scoring import SCORING_VERSION, compute_priority_score


def test_scoring_version_is_v1():
    assert SCORING_VERSION == "v1"


def test_all_dimensions_present_produces_a_score():
    score = compute_priority_score(
        reach=80, impact=80, risk=80, answerability=80, decision_sensitivity=80
    )
    assert score == 80.0


def test_weights_sum_to_one_so_uniform_inputs_pass_through_unchanged():
    for value in (0, 25, 50, 100):
        assert compute_priority_score(value, value, value, value, value) == float(value)


def test_any_missing_dimension_returns_none_reach():
    assert compute_priority_score(None, 80, 80, 80, 80) is None


def test_any_missing_dimension_returns_none_impact():
    assert compute_priority_score(80, None, 80, 80, 80) is None


def test_any_missing_dimension_returns_none_risk():
    assert compute_priority_score(80, 80, None, 80, 80) is None


def test_any_missing_dimension_returns_none_answerability():
    assert compute_priority_score(80, 80, 80, None, 80) is None


def test_any_missing_dimension_returns_none_decision_sensitivity():
    assert compute_priority_score(80, 80, 80, 80, None) is None


def test_all_missing_returns_none():
    assert compute_priority_score(None, None, None, None, None) is None


def test_reach_and_impact_are_weighted_higher_than_answerability_and_decision_sensitivity():
    """A question high on reach/impact but low on the other three should
    score higher than one with the inputs reversed -- confirms the
    weighting actually favors "affects many decisions, wrongly" over
    "feasible to answer"."""
    high_reach_impact = compute_priority_score(
        reach=100, impact=100, risk=0, answerability=0, decision_sensitivity=0
    )
    high_answerability_only = compute_priority_score(
        reach=0, impact=0, risk=0, answerability=100, decision_sensitivity=100
    )
    assert high_reach_impact > high_answerability_only


def test_score_never_negative_or_above_100_for_inputs_in_range():
    score = compute_priority_score(0, 0, 0, 0, 0)
    assert score == 0.0
    score = compute_priority_score(100, 100, 100, 100, 100)
    assert score == 100.0
