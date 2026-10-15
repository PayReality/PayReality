"""Decision Intelligence: per-organization configurable scoring weights
(DIScoringConfig). See app.domain.decision_intelligence.scoring's own
module docstring for the full contract this service must uphold: changing
an organization's weights must NEVER retroactively alter an already-
persisted DIQuestion.priority_score/scoring_version pair -- only enforced
here by NEVER touching any DIQuestion row. The only thing this service
ever mutates is the DIScoringConfig row itself; di_question_service.
score_question is the only caller that reads it, and only at the exact
moment a human explicitly (re-)requests a score."""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DIScoringConfig
from app.domain.decision_intelligence.scoring import DEFAULT_WEIGHTS, SCORING_VERSION, validate_weights
from app.services import di_audit_service

_VERSION_PATTERN = re.compile(r"^v(\d+)$")


def _next_version(current: str) -> str:
    """"v1" -> "v2" -> "v3" ... A version string outside this module's own
    "vN" convention (shouldn't happen -- this service is the only writer)
    falls back to "v2" rather than raising, so a config row can never get
    permanently stuck un-bumpable."""
    match = _VERSION_PATTERN.match(current or "")
    if not match:
        return "v2"
    return f"v{int(match.group(1)) + 1}"


def get_config(db: Session, organization_id: uuid.UUID) -> DIScoringConfig | None:
    """Returns None, not a synthesized row, when the organization has
    never set its own config -- callers that need concrete weights to
    compute with should use `get_weights_and_version` below, which folds
    in scoring.py's own hardcoded defaults for exactly that case."""
    return db.scalar(select(DIScoringConfig).where(DIScoringConfig.organization_id == organization_id))


def get_weights_and_version(db: Session, organization_id: uuid.UUID) -> tuple[dict[str, float], str]:
    """The single call site di_question_service.score_question uses: a
    configured organization gets its own weights/version, an unconfigured
    one gets scoring.py's own DEFAULT_WEIGHTS/SCORING_VERSION ("v1") --
    identical to this feature not existing at all, for any organization
    that hasn't opted in."""
    config = get_config(db, organization_id)
    if config is None:
        return dict(DEFAULT_WEIGHTS), SCORING_VERSION
    weights = {
        "reach": float(config.reach_weight),
        "impact": float(config.impact_weight),
        "risk": float(config.risk_weight),
        "answerability": float(config.answerability_weight),
        "decision_sensitivity": float(config.decision_sensitivity_weight),
    }
    return weights, config.scoring_version


def upsert_config(
    db: Session, organization_id: uuid.UUID, actor_user_id: uuid.UUID, weights: dict[str, float]
) -> DIScoringConfig:
    """Validates `weights` (scoring.validate_weights -- must name exactly
    the five known dimensions, each non-negative, summing to 1.0 within
    tolerance; raises InvalidScoringWeightsError otherwise, surfaced by
    the router as a 422) and either creates the organization's first
    DIScoringConfig row (starting at "v2" -- a deliberate, explicit
    override of the "v1" implicit default, never "v1" itself, so a
    DIQuestion scored under this new config is never confused for one
    scored under the un-configured hardcoded default) or bumps the
    existing row's version and overwrites its weights.

    Every successful call bumps `scoring_version`, even one that
    resubmits identical weights -- this service deliberately does not
    diff old vs. new weights to decide whether a bump is "needed": the
    action of calling PUT is itself the organization declaring a new
    configuration decision, and scoring_version's whole job (per
    scoring.py's own docstring) is marking which CONFIGURATION produced a
    score, not merely which numeric weights did."""
    validate_weights(weights)

    config = get_config(db, organization_id)
    previous = None
    if config is None:
        config = DIScoringConfig(
            organization_id=organization_id,
            reach_weight=weights["reach"],
            impact_weight=weights["impact"],
            risk_weight=weights["risk"],
            answerability_weight=weights["answerability"],
            decision_sensitivity_weight=weights["decision_sensitivity"],
            scoring_version="v2",
            updated_by_user_id=actor_user_id,
        )
        db.add(config)
    else:
        previous = {
            "weights": {
                "reach": float(config.reach_weight),
                "impact": float(config.impact_weight),
                "risk": float(config.risk_weight),
                "answerability": float(config.answerability_weight),
                "decision_sensitivity": float(config.decision_sensitivity_weight),
            },
            "scoring_version": config.scoring_version,
        }
        config.reach_weight = weights["reach"]
        config.impact_weight = weights["impact"]
        config.risk_weight = weights["risk"]
        config.answerability_weight = weights["answerability"]
        config.decision_sensitivity_weight = weights["decision_sensitivity"]
        config.scoring_version = _next_version(config.scoring_version)
        config.updated_by_user_id = actor_user_id
    db.flush()

    di_audit_service.record_event(
        db, organization_id, actor_user_id, action="update", entity_type="DIScoringConfig", entity_id=config.id,
        previous_value=previous,
        new_value={"weights": weights, "scoring_version": config.scoring_version},
    )
    db.commit()
    db.refresh(config)
    return config


__all__ = ["get_config", "get_weights_and_version", "upsert_config"]
