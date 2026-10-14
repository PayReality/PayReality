from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization, User
from app.db.session import get_db
from app.dependencies import get_current_organization, get_current_user, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.decision_intelligence import CaseListResponse, CaseResponse, CreateCaseRequest, UpdateCaseRequest
from app.services import di_case_service
from app.services.di_case_service import CaseNotFoundError
from app.services.di_workflow_service import WorkflowNotFoundError

router = APIRouter(prefix="/v1/decision-intelligence/cases", tags=["decision-intelligence"])


@router.post(
    "", response_model=CaseResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.DI_CASE_MANAGE))],
)
def create_case(
    body: CreateCaseRequest,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return di_case_service.create_case(
            db, organization.id, body.workflow_id, user.id, body.facts,
            external_ref=body.external_ref, evidence_refs=body.evidence_refs,
            ai_recommendation=body.ai_recommendation, human_decision=body.human_decision,
            escalation_reason=body.escalation_reason, outcome=body.outcome, outcome_evidence=body.outcome_evidence,
        )
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="workflow_not_found")


@router.get(
    "", response_model=CaseListResponse,
    dependencies=[Depends(require_permission(Permission.DI_CASE_VIEW))],
)
def list_cases(
    workflow_id: UUID | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    cases, total = di_case_service.list_cases(
        db, organization.id, workflow_id=workflow_id, status=status, limit=limit, offset=offset
    )
    return CaseListResponse(cases=cases, total=total, limit=limit, offset=offset)


@router.get(
    "/{case_id}", response_model=CaseResponse,
    dependencies=[Depends(require_permission(Permission.DI_CASE_VIEW))],
)
def get_case(case_id: UUID, organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)):
    try:
        return di_case_service.get_case(db, case_id, organization.id)
    except CaseNotFoundError:
        raise HTTPException(status_code=404, detail="case_not_found")


@router.patch(
    "/{case_id}", response_model=CaseResponse,
    dependencies=[Depends(require_permission(Permission.DI_CASE_MANAGE))],
)
def update_case(
    case_id: UUID,
    body: UpdateCaseRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        return di_case_service.update_case(db, case_id, organization.id, **body.model_dump(exclude_unset=True))
    except CaseNotFoundError:
        raise HTTPException(status_code=404, detail="case_not_found")
