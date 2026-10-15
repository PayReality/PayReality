from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization, User
from app.db.session import get_db
from app.dependencies import get_current_organization, get_current_user, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.decision_intelligence import (
    CaseLinkResponse,
    CreateQuestionRequest,
    LinkCaseRequest,
    LinkPatternRequest,
    PriorityOverrideRequest,
    QuestionDetailResponse,
    QuestionListResponse,
    QuestionResponse,
    RelinkCaseKindRequest,
    UpdateQuestionRequest,
)
from app.services import di_question_service
from app.services.di_case_service import CaseNotFoundError
from app.services.di_pattern_service import PatternNotFoundError
from app.services.di_question_service import (
    CaseLinkNotFoundError,
    InvalidQuestionTransitionError,
    QuestionNotFoundError,
)
from app.services.di_workflow_service import WorkflowNotFoundError

router = APIRouter(prefix="/v1/decision-intelligence/questions", tags=["decision-intelligence"])


@router.post(
    "", response_model=QuestionResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_MANAGE))],
)
def create_question(
    body: CreateQuestionRequest,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return di_question_service.create_question(
            db, organization.id, body.workflow_id, user.id, body.title, body.description, body.owner_user_id
        )
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="workflow_not_found")


@router.get(
    "", response_model=QuestionListResponse,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_VIEW))],
)
def list_questions(
    workflow_id: UUID | None = None,
    status: str | None = None,
    sort_by: str = "created_at",
    limit: int = 100,
    offset: int = 0,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    questions, total = di_question_service.list_questions(
        db, organization.id, workflow_id=workflow_id, status=status, sort_by=sort_by, limit=limit, offset=offset
    )
    return QuestionListResponse(questions=questions, total=total, limit=limit, offset=offset)


@router.get(
    "/{question_id}", response_model=QuestionDetailResponse,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_VIEW))],
)
def get_question(
    question_id: UUID, organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)
):
    try:
        question = di_question_service.get_question(db, question_id, organization.id)
        patterns = di_question_service.list_linked_patterns(db, question_id, organization.id)
        case_links = di_question_service.list_linked_case_links(db, question_id, organization.id)
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")
    return QuestionDetailResponse(
        question=question,
        patterns=patterns,
        case_ids=[link.case_id for link in case_links],
        case_links=case_links,
    )


@router.patch(
    "/{question_id}", response_model=QuestionResponse,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_MANAGE))],
)
def update_question(
    question_id: UUID,
    body: UpdateQuestionRequest,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return di_question_service.update_question(
            db, question_id, organization.id, user.id, **body.model_dump(exclude_unset=True)
        )
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")


@router.post(
    "/{question_id}/score", response_model=QuestionResponse,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_MANAGE))],
)
def score_question(
    question_id: UUID,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return di_question_service.score_question(db, question_id, organization.id, user.id)
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")


@router.post(
    "/{question_id}/submit", response_model=QuestionResponse,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_MANAGE))],
)
def submit_question_for_review(
    question_id: UUID,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return di_question_service.submit_for_review(db, question_id, organization.id, user.id)
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")
    except InvalidQuestionTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post(
    "/{question_id}/ready-for-review", response_model=QuestionResponse,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_MANAGE))],
)
def mark_question_ready_for_review(
    question_id: UUID,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Not in the brief's own literal Questions endpoint list, added
    (matching agents.py's own precedent for revoke_agent) because
    'ready_for_review' is a required step in DIQuestion.status's own
    fixed vocabulary and would otherwise be unreachable through any
    endpoint."""
    try:
        return di_question_service.mark_ready_for_review(db, question_id, organization.id, user.id)
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")
    except InvalidQuestionTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post(
    "/{question_id}/approve-for-operational-use", response_model=QuestionResponse,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_MANAGE))],
)
def approve_question_for_operational_use(
    question_id: UUID,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Same reasoning as mark_question_ready_for_review above:
    'approved_for_operational_use' is this status vocabulary's own
    terminal state."""
    try:
        return di_question_service.approve_for_operational_use(db, question_id, organization.id, user.id)
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")
    except InvalidQuestionTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post(
    "/{question_id}/patterns", status_code=201,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_MANAGE))],
)
def link_pattern(
    question_id: UUID,
    body: LinkPatternRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        di_question_service.link_pattern(db, question_id, body.pattern_id, organization.id)
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")
    except PatternNotFoundError:
        raise HTTPException(status_code=404, detail="pattern_not_found")
    return {"question_id": str(question_id), "pattern_id": str(body.pattern_id), "linked": True}


@router.delete(
    "/{question_id}/patterns/{pattern_id}", status_code=204,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_MANAGE))],
)
def unlink_pattern(
    question_id: UUID,
    pattern_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        di_question_service.unlink_pattern(db, question_id, pattern_id, organization.id)
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")


@router.post(
    "/{question_id}/cases", status_code=201,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_MANAGE))],
)
def link_case(
    question_id: UUID,
    body: LinkCaseRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        di_question_service.link_case(db, question_id, body.case_id, organization.id, kind=body.kind, reason=body.reason)
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")
    except CaseNotFoundError:
        raise HTTPException(status_code=404, detail="case_not_found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"question_id": str(question_id), "case_id": str(body.case_id), "linked": True}


@router.patch(
    "/{question_id}/cases/{case_id}", response_model=CaseLinkResponse,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_MANAGE))],
)
def relink_case_kind(
    question_id: UUID,
    case_id: UUID,
    body: RelinkCaseKindRequest,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Correcting a case's relevance category -- e.g. a reviewer demoting
    a model-inferred "potentially_affected" case to "excluded" after
    actually checking it. Preserves the original link (and, via the
    DIAuditEvent this writes, the full review history) rather than
    deleting and recreating it."""
    try:
        return di_question_service.relink_case_kind(
            db, question_id, case_id, organization.id, user.id, body.new_kind, body.reason
        )
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")
    except CaseLinkNotFoundError:
        raise HTTPException(status_code=404, detail="case_link_not_found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete(
    "/{question_id}/cases/{case_id}", status_code=204,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_MANAGE))],
)
def unlink_case(
    question_id: UUID,
    case_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        di_question_service.unlink_case(db, question_id, case_id, organization.id)
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")


@router.post(
    "/{question_id}/priority-override", response_model=QuestionResponse,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_MANAGE))],
)
def override_priority(
    question_id: UUID,
    body: PriorityOverrideRequest,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return di_question_service.override_priority(
            db, question_id, organization.id, user.id, body.score, body.reason
        )
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")
