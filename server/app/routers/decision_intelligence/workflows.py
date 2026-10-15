from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization, User
from app.db.session import get_db
from app.dependencies import get_current_organization, get_current_user, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.decision_intelligence import (
    CreateWorkflowRequest,
    UpdateWorkflowRequest,
    WorkflowListResponse,
    WorkflowOverviewResponse,
    WorkflowResponse,
)
from app.services import di_report_service, di_workflow_service
from app.services.di_workflow_service import WorkflowNotFoundError

router = APIRouter(prefix="/v1/decision-intelligence/workflows", tags=["decision-intelligence"])


@router.post(
    "", response_model=WorkflowResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.DI_WORKFLOW_MANAGE))],
)
def create_workflow(
    body: CreateWorkflowRequest,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return di_workflow_service.create_workflow(
        db, organization.id, user.id, body.name, body.description, body.business_context, body.owner_user_id
    )


@router.get(
    "", response_model=WorkflowListResponse,
    dependencies=[Depends(require_permission(Permission.DI_CASE_VIEW))],
)
def list_workflows(
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    workflows, total = di_workflow_service.list_workflows(db, organization.id, status=status, limit=limit, offset=offset)
    return WorkflowListResponse(workflows=workflows, total=total, limit=limit, offset=offset)


@router.get(
    "/{workflow_id}", response_model=WorkflowResponse,
    dependencies=[Depends(require_permission(Permission.DI_CASE_VIEW))],
)
def get_workflow(workflow_id: UUID, organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)):
    try:
        return di_workflow_service.get_workflow(db, workflow_id, organization.id)
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="workflow_not_found")


@router.patch(
    "/{workflow_id}", response_model=WorkflowResponse,
    dependencies=[Depends(require_permission(Permission.DI_WORKFLOW_MANAGE))],
)
def update_workflow(
    workflow_id: UUID,
    body: UpdateWorkflowRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        return di_workflow_service.update_workflow(db, workflow_id, organization.id, **body.model_dump(exclude_unset=True))
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="workflow_not_found")


@router.get(
    "/{workflow_id}/overview", response_model=WorkflowOverviewResponse,
    dependencies=[Depends(require_permission(Permission.DI_REPORT_VIEW))],
)
def get_workflow_overview(
    workflow_id: UUID, organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)
):
    try:
        return di_report_service.get_workflow_overview(db, workflow_id, organization.id)
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="workflow_not_found")
