"""Decision Intelligence: pure-function unit tests for scoring.py,
matching this codebase's established "pure logic, no DB" convention
(test_rbac_permissions.py, test_compiler_v2.py).

Feature: configurable scoring weights adds validate_weights and an
optional `weights` parameter to compute_priority_score -- the tests below
for the pre-existing, un-parameterized behavior are UNCHANGED from before
that feature (confirming "an unmodified default still behaves exactly as
before", this feature's own explicit testing requirement); the new
`weights=`-focused tests are grouped separately underneath."""

import pytest

from app.domain.decision_intelligence.scoring import (
    DEFAULT_WEIGHTS,
    SCORING_VERSION,
    InvalidScoringWeightsError,
    compute_priority_score,
    validate_weights,
)


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


# --- Feature: configurable scoring weights ---------------------------------


def test_default_weights_match_the_hardcoded_v1_formula():
    assert DEFAULT_WEIGHTS == {
        "reach": 0.30, "impact": 0.30, "risk": 0.20, "answerability": 0.10, "decision_sensitivity": 0.10,
    }


def test_weights_none_is_identical_to_omitting_the_parameter():
    with_default_param = compute_priority_score(80, 70, 60, 50, 40)
    with_explicit_none = compute_priority_score(80, 70, 60, 50, 40, weights=None)
    assert with_default_param == with_explicit_none


def test_custom_weights_change_the_result():
    equal_weights = {
        "reach": 0.2, "impact": 0.2, "risk": 0.2, "answerability": 0.2, "decision_sensitivity": 0.2,
    }
    default_result = compute_priority_score(100, 0, 0, 0, 0)
    custom_result = compute_priority_score(100, 0, 0, 0, 0, weights=equal_weights)
    assert default_result == 30.0  # 0.30 * 100
    assert custom_result == 20.0  # 0.20 * 100
    assert default_result != custom_result


def test_custom_weights_still_return_none_for_any_missing_dimension():
    """The hard "missing input -> None" contract is unconditional --
    unaffected by which weight set would otherwise have been used."""
    equal_weights = {
        "reach": 0.2, "impact": 0.2, "risk": 0.2, "answerability": 0.2, "decision_sensitivity": 0.2,
    }
    assert compute_priority_score(None, 70, 60, 50, 40, weights=equal_weights) is None


def test_validate_weights_accepts_the_default_set():
    validate_weights(dict(DEFAULT_WEIGHTS))  # must not raise


def test_validate_weights_rejects_a_missing_dimension():
    incomplete = {"reach": 0.3, "impact": 0.3, "risk": 0.2, "answerability": 0.2}
    with pytest.raises(InvalidScoringWeightsError):
        validate_weights(incomplete)


def test_validate_weights_rejects_an_unknown_dimension():
    extra = dict(DEFAULT_WEIGHTS)
    extra["made_up_dimension"] = 0.1
    with pytest.raises(InvalidScoringWeightsError):
        validate_weights(extra)


def test_validate_weights_rejects_a_negative_weight():
    bad = dict(DEFAULT_WEIGHTS)
    bad["reach"] = -0.1
    bad["impact"] = 0.4
    with pytest.raises(InvalidScoringWeightsError):
        validate_weights(bad)


def test_validate_weights_rejects_a_set_that_does_not_sum_to_one():
    too_high = {
        "reach": 0.5, "impact": 0.5, "risk": 0.5, "answerability": 0.5, "decision_sensitivity": 0.5,
    }
    with pytest.raises(InvalidScoringWeightsError):
        validate_weights(too_high)


def test_validate_weights_tolerates_small_floating_point_rounding():
    almost_one = {
        "reach": 0.30000001, "impact": 0.3, "risk": 0.2, "answerability": 0.1, "decision_sensitivity": 0.1,
    }
    validate_weights(almost_one)  # must not raise -- within tolerance
