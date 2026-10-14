from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization, User
from app.db.session import get_db
from app.dependencies import get_current_organization, get_current_user, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.decision_intelligence import (
    CreatePatternRequest,
    LinkCaseRequest,
    PatternListResponse,
    PatternResponse,
    UpdatePatternRequest,
)
from app.services import di_pattern_service
from app.services.di_case_service import CaseNotFoundError
from app.services.di_pattern_service import PatternNotFoundError
from app.services.di_workflow_service import WorkflowNotFoundError

router = APIRouter(prefix="/v1/decision-intelligence/patterns", tags=["decision-intelligence"])


@router.post(
    "", response_model=PatternResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.DI_PATTERN_MANAGE))],
)
def create_pattern(
    body: CreatePatternRequest,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return di_pattern_service.create_pattern(
            db, organization.id, body.workflow_id, user.id, body.name, body.description, body.category,
            body.proposed_explanation, alternative_explanations=body.alternative_explanations,
            confidence=body.confidence,
        )
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="workflow_not_found")


@router.get(
    "", response_model=PatternListResponse,
    dependencies=[Depends(require_permission(Permission.DI_CASE_VIEW))],
)
def list_patterns(
    workflow_id: UUID | None = None,
    review_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    patterns, total = di_pattern_service.list_patterns(
        db, organization.id, workflow_id=workflow_id, review_status=review_status, limit=limit, offset=offset
    )
    return PatternListResponse(patterns=patterns, total=total, limit=limit, offset=offset)


@router.get(
    "/{pattern_id}", response_model=PatternResponse,
    dependencies=[Depends(require_permission(Permission.DI_CASE_VIEW))],
)
def get_pattern(pattern_id: UUID, organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)):
    try:
        return di_pattern_service.get_pattern(db, pattern_id, organization.id)
    except PatternNotFoundError:
        raise HTTPException(status_code=404, detail="pattern_not_found")


@router.get(
    "/{pattern_id}/cases", response_model=list[UUID],
    dependencies=[Depends(require_permission(Permission.DI_CASE_VIEW))],
)
def list_pattern_cases(
    pattern_id: UUID, organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)
):
    """Frontend integration fix: `di_pattern_service.list_linked_cases`
    already existed (written alongside `link_case`/`unlink_case` below)
    but was never wired to a router endpoint, so a Pattern's own linked
    Cases -- its evidence, per DIPatternCase's own model docstring ("a
    Pattern with no linked Cases is an unsupported assertion, not
    evidence") -- were write-only: a caller could link/unlink a case but
    never list which ones were actually linked. DIQuestion already has
    the read-side equivalent (QuestionDetailResponse.case_ids, via
    di_question_service.list_linked_cases); this closes the same gap for
    DIPattern using the identical, already-tested service function and
    permission (DI_CASE_VIEW, matching list_patterns/get_pattern above),
    zero new service-layer code.
    """
    try:
        return di_pattern_service.list_linked_cases(db, pattern_id, organization.id)
    except PatternNotFoundError:
        raise HTTPException(status_code=404, detail="pattern_not_found")


@router.patch(
    "/{pattern_id}", response_model=PatternResponse,
    dependencies=[Depends(require_permission(Permission.DI_PATTERN_MANAGE))],
)
def update_pattern(
    pattern_id: UUID,
    body: UpdatePatternRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        return di_pattern_service.update_pattern(db, pattern_id, organization.id, **body.model_dump(exclude_unset=True))
    except PatternNotFoundError:
        raise HTTPException(status_code=404, detail="pattern_not_found")


@router.post(
    "/{pattern_id}/cases", status_code=201,
    dependencies=[Depends(require_permission(Permission.DI_PATTERN_MANAGE))],
)
def link_case(
    pattern_id: UUID,
    body: LinkCaseRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        di_pattern_service.link_case(db, pattern_id, body.case_id, organization.id)
    except PatternNotFoundError:
        raise HTTPException(status_code=404, detail="pattern_not_found")
    except CaseNotFoundError:
        raise HTTPException(status_code=404, detail="case_not_found")
    return {"pattern_id": str(pattern_id), "case_id": str(body.case_id), "linked": True}


@router.delete(
    "/{pattern_id}/cases/{case_id}", status_code=204,
    dependencies=[Depends(require_permission(Permission.DI_PATTERN_MANAGE))],
)
def unlink_case(
    pattern_id: UUID,
    case_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        di_pattern_service.unlink_case(db, pattern_id, case_id, organization.id)
    except PatternNotFoundError:
        raise HTTPException(status_code=404, detail="pattern_not_found")
