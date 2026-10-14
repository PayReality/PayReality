"""Decision Intelligence: the DIAnswer lifecycle (draft -> submitted ->
under_review -> approved|rejected), its immutable versioning (supersede),
and the one hard separation-of-duties rule this module's brief requires
in CODE, not just RBAC: the user who approves an answer can never be the
same user who authored it.

Every submit/approve/reject/supersede writes one DIAuditEvent (di_audit_
service), batched into the same commit as the status change -- an
approval can never exist in the ledger without the answer row it
describes actually having changed, or vice versa.

Each transition also advances the parent DIQuestion's own status as a
side effect (di_question_service._apply_status) -- see that module's own
docstring for why most of DIQuestion.status's vocabulary is driven this
way rather than through a dedicated question endpoint."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DIAnswer
from app.services import di_audit_service, di_question_service


class AnswerNotFoundError(Exception):
    pass


class InvalidAnswerTransitionError(Exception):
    def __init__(self, answer_id: uuid.UUID, from_status: str, to_status: str):
        self.answer_id = answer_id
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"cannot move answer {answer_id} from '{from_status}' to '{to_status}'")


class SeparationOfDutiesError(Exception):
    """The one hard rule this module enforces in code, not just via RBAC
    (DI_ANSWER_SUBMIT vs DI_ANSWER_APPROVE): an answer's author_user_id
    can never equal its approver_user_id, regardless of what either
    user's role would otherwise permit."""


def get_answer(db: Session, answer_id: uuid.UUID, organization_id: uuid.UUID) -> DIAnswer:
    """DIAnswer has no organization_id of its own (its design brief,
    mirroring Agent's own acting_for_principal_id precedent) -- scoped by
    walking question_id -> DIQuestion.organization_id, which also 404s an
    answer whose question belongs to a different organization identically
    to one that doesn't exist at all."""
    answer = db.get(DIAnswer, answer_id)
    if answer is None:
        raise AnswerNotFoundError(str(answer_id))
    try:
        di_question_service.get_question(db, answer.question_id, organization_id)
    except di_question_service.QuestionNotFoundError:
        raise AnswerNotFoundError(str(answer_id))
    return answer


def list_answers_for_question(db: Session, question_id: uuid.UUID, organization_id: uuid.UUID) -> list[DIAnswer]:
    di_question_service.get_question(db, question_id, organization_id)
    return list(
        db.scalars(
            select(DIAnswer).where(DIAnswer.question_id == question_id).order_by(DIAnswer.version.desc())
        )
    )


def create_draft_answer(
    db: Session,
    question_id: uuid.UUID,
    organization_id: uuid.UUID,
    author_user_id: uuid.UUID,
    content: str,
    evidence_refs: list | None = None,
    scope: str | None = None,
    conditions_exceptions: str | None = None,
    effective_date=None,
    review_date=None,
) -> DIAnswer:
    question = di_question_service.get_question(db, question_id, organization_id)

    answer = DIAnswer(
        question_id=question.id,
        content=content,
        evidence_refs=evidence_refs,
        scope=scope,
        conditions_exceptions=conditions_exceptions,
        effective_date=effective_date,
        review_date=review_date,
        author_user_id=author_user_id,
        version=1,
        status="draft",
    )
    db.add(answer)
    db.commit()
    db.refresh(answer)
    return answer


def submit_answer(
    db: Session, answer_id: uuid.UUID, organization_id: uuid.UUID, actor_user_id: uuid.UUID
) -> DIAnswer:
    answer = get_answer(db, answer_id, organization_id)
    if answer.status != "draft":
        raise InvalidAnswerTransitionError(answer_id, answer.status, "submitted")

    previous_status = answer.status
    answer.status = "submitted"
    answer.submitted_at = datetime.now(timezone.utc)
    db.add(answer)

    question = di_question_service.get_question(db, answer.question_id, organization_id)
    di_question_service._apply_status(db, question, "answer_submitted")

    di_audit_service.record_event(
        db, organization_id, actor_user_id, action="submit", entity_type="DIAnswer", entity_id=answer.id,
        previous_value={"status": previous_status}, new_value={"status": answer.status},
    )
    db.commit()
    db.refresh(answer)
    return answer


def approve_answer(
    db: Session, answer_id: uuid.UUID, organization_id: uuid.UUID, approver_user_id: uuid.UUID
) -> DIAnswer:
    answer = get_answer(db, answer_id, organization_id)
    if answer.status not in ("submitted", "under_review"):
        raise InvalidAnswerTransitionError(answer_id, answer.status, "approved")
    if answer.author_user_id == approver_user_id:
        raise SeparationOfDutiesError(
            f"user {approver_user_id} authored answer {answer_id} and cannot also approve it"
        )

    previous_status = answer.status
    answer.status = "approved"
    answer.approver_user_id = approver_user_id
    answer.decided_at = datetime.now(timezone.utc)
    db.add(answer)

    question = di_question_service.get_question(db, answer.question_id, organization_id)
    di_question_service._apply_status(db, question, "approved")

    di_audit_service.record_event(
        db, organization_id, approver_user_id, action="approve", entity_type="DIAnswer", entity_id=answer.id,
        previous_value={"status": previous_status}, new_value={"status": answer.status, "approver_user_id": str(approver_user_id)},
    )
    db.commit()
    db.refresh(answer)
    return answer


def reject_answer(
    db: Session,
    answer_id: uuid.UUID,
    organization_id: uuid.UUID,
    approver_user_id: uuid.UUID,
    reason: str | None = None,
) -> DIAnswer:
    answer = get_answer(db, answer_id, organization_id)
    if answer.status not in ("submitted", "under_review"):
        raise InvalidAnswerTransitionError(answer_id, answer.status, "rejected")
    if answer.author_user_id == approver_user_id:
        raise SeparationOfDutiesError(
            f"user {approver_user_id} authored answer {answer_id} and cannot also reject it"
        )

    previous_status = answer.status
    answer.status = "rejected"
    answer.approver_user_id = approver_user_id
    answer.decided_at = datetime.now(timezone.utc)
    db.add(answer)

    question = di_question_service.get_question(db, answer.question_id, organization_id)
    di_question_service._apply_status(db, question, "awaiting_answer")

    di_audit_service.record_event(
        db, organization_id, approver_user_id, action="reject", entity_type="DIAnswer", entity_id=answer.id,
        previous_value={"status": previous_status}, new_value={"status": answer.status}, reason=reason,
    )
    db.commit()
    db.refresh(answer)
    return answer


def supersede_answer(
    db: Session,
    answer_id: uuid.UUID,
    organization_id: uuid.UUID,
    author_user_id: uuid.UUID,
    content: str,
    evidence_refs: list | None = None,
    scope: str | None = None,
    conditions_exceptions: str | None = None,
    effective_date=None,
    review_date=None,
) -> DIAnswer:
    """Only an `approved` answer can be superseded -- revising a draft/
    rejected answer is a plain edit (create a fresh draft instead), not a
    governance action that needs an immutable version chain."""
    previous = get_answer(db, answer_id, organization_id)
    if previous.status != "approved":
        raise InvalidAnswerTransitionError(answer_id, previous.status, "superseded")

    new_answer = DIAnswer(
        question_id=previous.question_id,
        content=content,
        evidence_refs=evidence_refs,
        scope=scope,
        conditions_exceptions=conditions_exceptions,
        effective_date=effective_date,
        review_date=review_date,
        author_user_id=author_user_id,
        version=previous.version + 1,
        previous_version_id=previous.id,
        status="draft",
    )
    previous.status = "superseded"
    db.add(previous)
    db.add(new_answer)

    di_audit_service.record_event(
        db, organization_id, author_user_id, action="supersede", entity_type="DIAnswer", entity_id=previous.id,
        previous_value={"status": "approved"}, new_value={"status": "superseded", "superseded_by_version": new_answer.version},
    )
    db.commit()
    db.refresh(new_answer)
    return new_answer
