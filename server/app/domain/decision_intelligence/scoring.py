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
scoring", never coercing it to a number. This contract is unconditional
and does not change with configurable weights below -- a missing
dimension stays missing no matter which weight set is active.

Pure function: no DB access, no I/O, fully unit-testable in isolation.

Configurable weights (Feature: Settings - configurable scoring weights):
`DEFAULT_WEIGHTS` below is this module's own, permanent "v1" weighting --
it never changes. An organization MAY override it with its own
`DIScoringConfig` row (app.db.models), whose weights are passed in here
via the `weights` parameter rather than this module reaching into the
database itself (domain/ may never import app.db, see
test_architectural_boundaries.py). Passing `weights=None` (the default)
reproduces the exact v1 behavior unchanged -- every existing caller and
every existing test keeps working with zero code changes.

Critically, changing an organization's `DIScoringConfig` must NEVER
retroactively reinterpret a `DIQuestion.priority_score` that was already
computed and persisted under a previous weight set: this function is
stateless and only ever computes a fresh score from the weights handed to
it at call time. The caller (di_question_service.score_question) is what
makes this safe in practice -- it only runs when a human explicitly
(re-)requests a score, never automatically when the config changes, so
an old, unrescored question's stored `priority_score`/`scoring_version`
simply stays whatever it already was."""

SCORING_VERSION = "v1"

DEFAULT_WEIGHTS = {
    "reach": 0.30,
    "impact": 0.30,
    "risk": 0.20,
    "answerability": 0.10,
    "decision_sensitivity": 0.10,
}

# Retained as a private alias: this module's own internal references (and
# any external code that reached in before weights became configurable)
# keep working unchanged.
_WEIGHTS = DEFAULT_WEIGHTS

_WEIGHT_SUM_TOLERANCE = 0.001


class InvalidScoringWeightsError(ValueError):
    """Raised by validate_weights (and anything that reuses it) when a
    candidate weight set is structurally unsound -- a missing dimension,
    a negative weight, or a set that doesn't sum to 1.0 within rounding
    tolerance. Never silently normalized: see validate_weights' own
    docstring for why this module chose to reject rather than rescale."""


def validate_weights(weights: dict[str, float]) -> None:
    """A deliberate choice (this feature's brief explicitly left this
    open): weights MUST sum to 1.0 (within a small floating-point
    tolerance), checked here, rather than silently normalized/rescaled at
    compute time. Silent normalization would let a governance admin
    submit e.g. weights that sum to 2.0 thinking each is an independent
    0-100 "importance" slider, and have the product quietly reinterpret
    them into something else -- the exact kind of silent reinterpretation
    this module's own scoring contract (see module docstring) already
    refuses to do for a missing input. Rejecting loudly and explaining
    why is more consistent with that existing discipline than rescaling
    on the caller's behalf."""
    missing = sorted(set(DEFAULT_WEIGHTS) - set(weights))
    if missing:
        raise InvalidScoringWeightsError(f"missing_weight_dimensions: {missing}")
    extra = sorted(set(weights) - set(DEFAULT_WEIGHTS))
    if extra:
        raise InvalidScoringWeightsError(f"unknown_weight_dimensions: {extra}")
    for name, value in weights.items():
        if value is None or float(value) < 0:
            raise InvalidScoringWeightsError(f"weight_must_be_non_negative: {name}={value!r}")
    total = sum(float(v) for v in weights.values())
    if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
        raise InvalidScoringWeightsError(f"weights_must_sum_to_one: got {total!r}")


def compute_priority_score(
    reach: float | None,
    impact: float | None,
    risk: float | None,
    answerability: float | None,
    decision_sensitivity: float | None,
    weights: dict[str, float] | None = None,
) -> float | None:
    """Combines the five 0-100 dimension scores into a single 0-100
    priority score. Uses `DEFAULT_WEIGHTS` (this module's fixed v1
    weighting) when `weights` is omitted/None -- every pre-existing
    caller is unaffected. When a caller passes an organization's own
    `DIScoringConfig` weights instead, the combination formula itself
    (a weighted linear sum) is unchanged; only the weight values differ.
    Returns None, never a substituted default, if any input is None,
    regardless of which weight set is in play."""
    inputs = {
        "reach": reach,
        "impact": impact,
        "risk": risk,
        "answerability": answerability,
        "decision_sensitivity": decision_sensitivity,
    }
    if any(value is None for value in inputs.values()):
        return None

    active_weights = weights if weights is not None else DEFAULT_WEIGHTS
    score = sum(active_weights[name] * float(value) for name, value in inputs.items())
    return round(score, 2)
