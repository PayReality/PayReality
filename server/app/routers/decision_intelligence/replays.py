from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization, User
from app.db.session import get_db
from app.dependencies import get_current_organization, get_current_user, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.decision_intelligence import (
    CreateReplayRequest,
    ReplayCaseResultListResponse,
    ReplayRunListResponse,
    ReplayRunResponse,
)
from app.services import di_replay_service
from app.services.di_replay_service import ReplayRunNotFoundError, RuleVersionNotFoundError
from app.services.di_workflow_service import WorkflowNotFoundError

router = APIRouter(prefix="/v1/decision-intelligence/replays", tags=["decision-intelligence"])


@router.post(
    "", response_model=ReplayRunResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.DI_REPLAY_RUN))],
)
def create_replay(
    body: CreateReplayRequest,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Runs synchronously: the response already carries the completed
    run's summary (see replay_executor.py's own docstring for why this
    is the right choice at this product's scale)."""
    try:
        return di_replay_service.create_and_run_replay(
            db, organization.id, body.workflow_id, body.rule_version_id, user.id,
            case_ids=body.case_ids, filter_status=body.filter_status,
        )
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="workflow_not_found")
    except RuleVersionNotFoundError:
        raise HTTPException(status_code=404, detail="rule_version_not_found")


@router.get(
    "", response_model=ReplayRunListResponse,
    dependencies=[Depends(require_permission(Permission.DI_REPORT_VIEW))],
)
def list_replays(
    workflow_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    replay_runs, total = di_replay_service.list_replay_runs(
        db, organization.id, workflow_id=workflow_id, limit=limit, offset=offset
    )
    return ReplayRunListResponse(replay_runs=replay_runs, total=total, limit=limit, offset=offset)


@router.get(
    "/{replay_run_id}", response_model=ReplayRunResponse,
    dependencies=[Depends(require_permission(Permission.DI_REPORT_VIEW))],
)
def get_replay(
    replay_run_id: UUID, organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)
):
    try:
        return di_replay_service.get_replay_run(db, replay_run_id, organization.id)
    except ReplayRunNotFoundError:
        raise HTTPException(status_code=404, detail="replay_run_not_found")


@router.get(
    "/{replay_run_id}/results", response_model=ReplayCaseResultListResponse,
    dependencies=[Depends(require_permission(Permission.DI_REPORT_VIEW))],
)
def list_replay_results(
    replay_run_id: UUID,
    limit: int = 100,
    offset: int = 0,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    try:
        results, total = di_replay_service.list_replay_case_results(
            db, replay_run_id, organization.id, limit=limit, offset=offset
        )
    except ReplayRunNotFoundError:
        raise HTTPException(status_code=404, detail="replay_run_not_found")
    return ReplayCaseResultListResponse(results=results, total=total, limit=limit, offset=offset)
