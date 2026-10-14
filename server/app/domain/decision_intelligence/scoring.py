"""Decision Intelligence question-priority scoring.

A DIQuestion is prioritised along five independently-judged dimensions
(DECISION_INTELLIGENCE module brief):

  reach                 -- how many decisions/cases does this question affect?
  impact                -- how much does the outcome matter when it's wrong?
  risk                  -- what's the downside of leaving it unanswered?
  answerability         -- how feasible is it to actually get a good answer?
  decision_sensitivity  -- how much does the final decision change based on
                           the answer (a question whose answer never changes
                           the outcome isn't worth prioritising)?

Each dimension is scored on a 0-100 scale by a human (reviewer/governance
admin), the same "an expert judgement label, not a fabricated statistic"
posture DIPattern.confidence already takes -- this module does no scoring
of its own, it only combines scores a human already assigned.

Formula (SCORING_VERSION "v1"): a fixed-weight linear combination, each
input scaled to the same 0-100 range before combining, producing a single
0-100 priority_score:

    priority = 0.30*reach + 0.30*impact + 0.20*risk
             + 0.10*answerability + 0.10*decision_sensitivity

Weights sum to 1.0 so the output stays on the same 0-100 scale as the
inputs. Reach and impact are weighted highest because a question that
affects many decisions, wrongly, is the clearest case for prioritisation;
answerability and decision_sensitivity are weighted lowest because they
temper the raw size of the problem rather than define it.

Hard contract: if ANY of the five inputs is None, compute_priority_score
returns None. A missing score reflects missing evidence (nobody has
judged that dimension yet) -- silently treating a missing input as 0, or
as some other default, would make an unscored question look artificially
low-priority (or, with a different default, artificially urgent) instead
of visibly "not yet assessed". The caller (the question service / its
API) is responsible for surfacing a None priority_score as "needs
scoring", never coercing it to a number.

Pure function: no DB access, no I/O, fully unit-testable in isolation.
"""

SCORING_VERSION = "v1"

_WEIGHTS = {
    "reach": 0.30,
    "impact": 0.30,
    "risk": 0.20,
    "answerability": 0.10,
    "decision_sensitivity": 0.10,
}


def compute_priority_score(
    reach: float | None,
    impact: float | None,
    risk: float | None,
    answerability: float | None,
    decision_sensitivity: float | None,
) -> float | None:
    """Combines the five 0-100 dimension scores into a single 0-100
    priority score, per this module's fixed v1 weighting. Returns None,
    never a substituted default, if any input is None."""
    inputs = {
        "reach": reach,
        "impact": impact,
        "risk": risk,
        "answerability": answerability,
        "decision_sensitivity": decision_sensitivity,
    }
    if any(value is None for value in inputs.values()):
        return None

    score = sum(_WEIGHTS[name] * float(value) for name, value in inputs.items())
    return round(score, 2)
