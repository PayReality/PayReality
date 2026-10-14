from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization, User
from app.db.session import get_db
from app.dependencies import get_current_organization, get_current_user, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.decision_intelligence import AnswerResponse, CreateAnswerRequest, RejectAnswerRequest, SupersedeAnswerRequest
from app.services import di_answer_service
from app.services.di_answer_service import (
    AnswerNotFoundError,
    InvalidAnswerTransitionError,
    SeparationOfDutiesError,
)
from app.services.di_question_service import QuestionNotFoundError

# Nested under a question (create/list): a question's own set of answers.
question_answers_router = APIRouter(
    prefix="/v1/decision-intelligence/questions/{question_id}/answers", tags=["decision-intelligence"]
)
# Standalone, keyed by answer id (every lifecycle transition).
router = APIRouter(prefix="/v1/decision-intelligence/answers", tags=["decision-intelligence"])


@question_answers_router.post(
    "", response_model=AnswerResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.DI_ANSWER_SUBMIT))],
)
def create_draft_answer(
    question_id: UUID,
    body: CreateAnswerRequest,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return di_answer_service.create_draft_answer(
            db, question_id, organization.id, user.id, body.content,
            evidence_refs=body.evidence_refs, scope=body.scope, conditions_exceptions=body.conditions_exceptions,
            effective_date=body.effective_date, review_date=body.review_date,
        )
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")


@question_answers_router.get(
    "", response_model=list[AnswerResponse],
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_VIEW))],
)
def list_answers(
    question_id: UUID, organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)
):
    try:
        return di_answer_service.list_answers_for_question(db, question_id, organization.id)
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")


@router.get(
    "/{answer_id}", response_model=AnswerResponse,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_VIEW))],
)
def get_answer(answer_id: UUID, organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)):
    try:
        return di_answer_service.get_answer(db, answer_id, organization.id)
    except AnswerNotFoundError:
        raise HTTPException(status_code=404, detail="answer_not_found")


@router.post(
    "/{answer_id}/submit", response_model=AnswerResponse,
    dependencies=[Depends(require_permission(Permission.DI_ANSWER_SUBMIT))],
)
def submit_answer(
    answer_id: UUID,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return di_answer_service.submit_answer(db, answer_id, organization.id, user.id)
    except AnswerNotFoundError:
        raise HTTPException(status_code=404, detail="answer_not_found")
    except InvalidAnswerTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post(
    "/{answer_id}/approve", response_model=AnswerResponse,
    dependencies=[Depends(require_permission(Permission.DI_ANSWER_APPROVE))],
)
def approve_answer(
    answer_id: UUID,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return di_answer_service.approve_answer(db, answer_id, organization.id, user.id)
    except AnswerNotFoundError:
        raise HTTPException(status_code=404, detail="answer_not_found")
    except InvalidAnswerTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except SeparationOfDutiesError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post(
    "/{answer_id}/reject", response_model=AnswerResponse,
    dependencies=[Depends(require_permission(Permission.DI_ANSWER_APPROVE))],
)
def reject_answer(
    answer_id: UUID,
    body: RejectAnswerRequest = RejectAnswerRequest(),
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return di_answer_service.reject_answer(db, answer_id, organization.id, user.id, reason=body.reason)
    except AnswerNotFoundError:
        raise HTTPException(status_code=404, detail="answer_not_found")
    except InvalidAnswerTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except SeparationOfDutiesError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post(
    "/{answer_id}/supersede", response_model=AnswerResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.DI_ANSWER_SUBMIT))],
)
def supersede_answer(
    answer_id: UUID,
    body: SupersedeAnswerRequest,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return di_answer_service.supersede_answer(
            db, answer_id, organization.id, user.id, body.content,
            evidence_refs=body.evidence_refs, scope=body.scope, conditions_exceptions=body.conditions_exceptions,
            effective_date=body.effective_date, review_date=body.review_date,
        )
    except AnswerNotFoundError:
        raise HTTPException(status_code=404, detail="answer_not_found")
    except InvalidAnswerTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
