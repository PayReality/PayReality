"""Decision Intelligence: Feature "Settings - configurable scoring
weights" (DIScoringConfig). One row per organization -- see
di_scoring_config_service.py and DIScoringConfig's own model docstring
for why.

RBAC: gated on a NEW permission, `DI_SETTINGS_MANAGE`, rather than the
existing `DI_WORKFLOW_MANAGE` -- a judgment call the brief explicitly
left open. See the Permission enum's own comment (app/domain/rbac/
permissions.py) for the reasoning: a scoring config is an organization-
wide policy about how every question in every workflow gets prioritised,
not a property of any one DIWorkflow, so a dedicated permission keeps
this module's existing "explicit namespace per kind of thing" discipline
rather than folding it into workflow management. Wired into
`ROLE_PERMISSIONS` for Governance Administrator only (and Owner, via the
`_ALL_PERMISSIONS` catch-all), the same role every other DI_*_MANAGE
permission already goes to -- gating the GET here too, not just the PUT,
since this is a settings surface the same roles that can change it are
the ones who should see it."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization, User
from app.db.session import get_db
from app.dependencies import get_current_organization, get_current_user, require_permission
from app.domain.decision_intelligence.scoring import DEFAULT_WEIGHTS, SCORING_VERSION, InvalidScoringWeightsError
from app.domain.rbac.permissions import Permission
from app.schemas.decision_intelligence import ScoringConfigResponse, ScoringWeights, UpdateScoringConfigRequest
from app.services import di_scoring_config_service

router = APIRouter(prefix="/v1/decision-intelligence/scoring-config", tags=["decision-intelligence"])


def _to_response(organization_id, config) -> ScoringConfigResponse:
    if config is None:
        return ScoringConfigResponse(
            organization_id=organization_id,
            weights=ScoringWeights(**DEFAULT_WEIGHTS),
            scoring_version=SCORING_VERSION,
            is_default=True,
            updated_at=None,
        )
    return ScoringConfigResponse(
        organization_id=organization_id,
        weights=ScoringWeights(
            reach=float(config.reach_weight),
            impact=float(config.impact_weight),
            risk=float(config.risk_weight),
            answerability=float(config.answerability_weight),
            decision_sensitivity=float(config.decision_sensitivity_weight),
        ),
        scoring_version=config.scoring_version,
        is_default=False,
        updated_at=config.updated_at,
    )


@router.get(
    "", response_model=ScoringConfigResponse,
    dependencies=[Depends(require_permission(Permission.DI_SETTINGS_MANAGE))],
)
def get_scoring_config(organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)):
    """Always returns 200 with a concrete weight set -- scoring.py's own
    hardcoded `DEFAULT_WEIGHTS`/`SCORING_VERSION` ("v1", `is_default:
    true`) when the organization has never configured its own, never a
    404. There is nothing missing to 404 on: "not yet configured" is
    itself a valid, well-defined state with a real answer."""
    config = di_scoring_config_service.get_config(db, organization.id)
    return _to_response(organization.id, config)


@router.put(
    "", response_model=ScoringConfigResponse,
    dependencies=[Depends(require_permission(Permission.DI_SETTINGS_MANAGE))],
)
def update_scoring_config(
    body: UpdateScoringConfigRequest,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Validates the five weights sum to 1.0 (scoring.validate_weights,
    422 on failure) and bumps `scoring_version` for whatever gets
    (re-)scored next -- never touches any already-persisted DIQuestion
    row, so no existing priority_score/scoring_version is retroactively
    reinterpreted (di_scoring_config_service.py's own docstring)."""
    try:
        config = di_scoring_config_service.upsert_config(
            db, organization.id, user.id, body.weights.model_dump()
        )
    except InvalidScoringWeightsError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _to_response(organization.id, config)
