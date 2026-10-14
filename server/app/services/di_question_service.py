"""Decision Intelligence: DIQuestion CRUD, its Pattern/Case linkage, its
priority scoring, and the human-invoked steps of its own lifecycle.

Most of DIQuestion.status's vocabulary advances as a SIDE EFFECT of other
services (answer submission/approval, rule drafting/validation, replay
completion) rather than through a dedicated endpoint here -- see each of
those services' own module docstrings. Only the early steps (submit for
analysis) and the final two steps (ready for review, approved for
operational use) are human-invoked directly against the question itself,
since nothing else in the product naturally triggers them."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import DIPattern, DIQuestion, DIQuestionCase, DIQuestionPattern
from app.domain.decision_intelligence.scoring import SCORING_VERSION, compute_priority_score
from app.services import di_audit_service, di_case_service, di_pattern_service, di_workflow_service


class QuestionNotFoundError(Exception):
    pass


class InvalidQuestionTransitionError(Exception):
    def __init__(self, question_id: uuid.UUID, from_status: str, to_status: str):
        self.question_id = question_id
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"cannot move question {question_id} from '{from_status}' to '{to_status}'")


def create_question(
    db: Session,
    organization_id: uuid.UUID,
    workflow_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    title: str,
    description: str | None = None,
    owner_user_id: uuid.UUID | None = None,
) -> DIQuestion:
    di_workflow_service.get_workflow(db, workflow_id, organization_id)

    question = DIQuestion(
        organization_id=organization_id,
        workflow_id=workflow_id,
        created_by_user_id=created_by_user_id,
        title=title,
        description=description,
        owner_user_id=owner_user_id,
    )
    db.add(question)
    db.flush()

    di_audit_service.record_event(
        db, organization_id, created_by_user_id, action="create", entity_type="DIQuestion", entity_id=question.id,
        new_value={"title": title, "workflow_id": str(workflow_id)},
    )
    db.commit()
    db.refresh(question)
    return question


def get_question(db: Session, question_id: uuid.UUID, organization_id: uuid.UUID) -> DIQuestion:
    question = db.get(DIQuestion, question_id)
    if question is None or question.organization_id != organization_id:
        raise QuestionNotFoundError(str(question_id))
    return question


def list_questions(
    db: Session,
    organization_id: uuid.UUID,
    workflow_id: uuid.UUID | None = None,
    status: str | None = None,
    sort_by: str = "created_at",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[DIQuestion], int]:
    stmt = select(DIQuestion).where(DIQuestion.organization_id == organization_id)
    if workflow_id is not None:
        stmt = stmt.where(DIQuestion.workflow_id == workflow_id)
    if status:
        stmt = stmt.where(DIQuestion.status == status)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    if sort_by == "priority_score":
        stmt = stmt.order_by(DIQuestion.priority_score.desc().nullslast())
    else:
        stmt = stmt.order_by(DIQuestion.created_at.desc())
    stmt = stmt.limit(limit).offset(offset)
    return list(db.scalars(stmt)), total


def update_question(
    db: Session,
    question_id: uuid.UUID,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    title: str | None = None,
    description: str | None = None,
    owner_user_id: uuid.UUID | None = None,
    reach_score: float | None = None,
    impact_score: float | None = None,
    risk_score: float | None = None,
    answerability_score: float | None = None,
    decision_sensitivity_score: float | None = None,
) -> DIQuestion:
    """Dimension scores set here are the raw, human-assigned judgements --
    `priority_score` itself is never set here, only ever by `score_question`
    below, so recomputing it is always an explicit, auditable action, not
    an incidental side effect of editing an unrelated field."""
    question = get_question(db, question_id, organization_id)
    changed: dict = {}
    if title is not None:
        changed["title"] = title
        question.title = title
    if description is not None:
        changed["description"] = description
        question.description = description
    if owner_user_id is not None:
        changed["owner_user_id"] = str(owner_user_id)
        question.owner_user_id = owner_user_id
    if reach_score is not None:
        changed["reach_score"] = reach_score
        question.reach_score = reach_score
    if impact_score is not None:
        changed["impact_score"] = impact_score
        question.impact_score = impact_score
    if risk_score is not None:
        changed["risk_score"] = risk_score
        question.risk_score = risk_score
    if answerability_score is not None:
        changed["answerability_score"] = answerability_score
        question.answerability_score = answerability_score
    if decision_sensitivity_score is not None:
        changed["decision_sensitivity_score"] = decision_sensitivity_score
        question.decision_sensitivity_score = decision_sensitivity_score

    if changed:
        di_audit_service.record_event(
            db, organization_id, actor_user_id, action="update", entity_type="DIQuestion", entity_id=question.id,
            new_value=changed,
        )
    db.commit()
    db.refresh(question)
    return question


def score_question(
    db: Session, question_id: uuid.UUID, organization_id: uuid.UUID, actor_user_id: uuid.UUID
) -> DIQuestion:
    """(Re)computes `priority_score` from the question's current five
    dimension scores via the single shared, versioned formula
    (scoring.py). Persists `scoring_version` alongside it so a later
    change to the formula never silently reinterprets an old score --
    `priority_score` stays None, not a fabricated number, if any
    dimension hasn't been assessed yet."""
    question = get_question(db, question_id, organization_id)
    previous_score = float(question.priority_score) if question.priority_score is not None else None
    question.priority_score = compute_priority_score(
        float(question.reach_score) if question.reach_score is not None else None,
        float(question.impact_score) if question.impact_score is not None else None,
        float(question.risk_score) if question.risk_score is not None else None,
        float(question.answerability_score) if question.answerability_score is not None else None,
        float(question.decision_sensitivity_score) if question.decision_sensitivity_score is not None else None,
    )
    question.scoring_version = SCORING_VERSION

    di_audit_service.record_event(
        db, organization_id, actor_user_id, action="score", entity_type="DIQuestion", entity_id=question.id,
        previous_value={"priority_score": previous_score},
        new_value={"priority_score": question.priority_score, "scoring_version": SCORING_VERSION},
    )
    db.commit()
    db.refresh(question)
    return question


# --- Lifecycle transitions ------------------------------------------------
#
# The full status vocabulary's path: proposed/in_analysis -> awaiting_answer
# (submit_for_review, below) -> answer_submitted -> approved (both driven by
# di_answer_service) -> logic_drafted -> logic_validated (both driven by
# di_rule_service) -> replay_completed (driven by di_replay_service) ->
# ready_for_review -> approved_for_operational_use (both below). Only the
# first and last two steps are human-invoked directly against the question
# itself; every step in between is a side effect of progress on the
# question's own answer/rule/replay -- see _apply_status's own docstring.


def _apply_status(db: Session, question: DIQuestion, new_status: str) -> DIQuestion:
    """Internal helper for the other DI services (answer/rule/replay) to
    advance a question's status as a side effect of THEIR OWN lifecycle
    event -- deliberately not transition-validated the way the public
    endpoints below are: the system itself is driving this, not a human
    skipping steps, and each caller already knows exactly which status it
    means to set."""
    question.status = new_status
    db.add(question)
    db.flush()
    return question


def _transition(
    db: Session, question: DIQuestion, organization_id: uuid.UUID, actor_user_id: uuid.UUID, new_status: str
) -> DIQuestion:
    previous_status = question.status
    question.status = new_status
    db.add(question)
    di_audit_service.record_event(
        db, organization_id, actor_user_id, action="transition", entity_type="DIQuestion", entity_id=question.id,
        previous_value={"status": previous_status}, new_value={"status": new_status},
    )
    db.commit()
    db.refresh(question)
    return question


def submit_for_review(
    db: Session, question_id: uuid.UUID, organization_id: uuid.UUID, actor_user_id: uuid.UUID
) -> DIQuestion:
    """A human-invoked step: the question has been fleshed out (linked
    patterns/cases, a description) and its proposer wants it formally
    worked -- moves `proposed`/`in_analysis` to `awaiting_answer`."""
    question = get_question(db, question_id, organization_id)
    if question.status not in ("proposed", "in_analysis"):
        raise InvalidQuestionTransitionError(question_id, question.status, "awaiting_answer")
    return _transition(db, question, organization_id, actor_user_id, "awaiting_answer")


def mark_ready_for_review(
    db: Session, question_id: uuid.UUID, organization_id: uuid.UUID, actor_user_id: uuid.UUID
) -> DIQuestion:
    question = get_question(db, question_id, organization_id)
    if question.status != "replay_completed":
        raise InvalidQuestionTransitionError(question_id, question.status, "ready_for_review")
    return _transition(db, question, organization_id, actor_user_id, "ready_for_review")


def approve_for_operational_use(
    db: Session, question_id: uuid.UUID, organization_id: uuid.UUID, actor_user_id: uuid.UUID
) -> DIQuestion:
    question = get_question(db, question_id, organization_id)
    if question.status != "ready_for_review":
        raise InvalidQuestionTransitionError(question_id, question.status, "approved_for_operational_use")
    return _transition(db, question, organization_id, actor_user_id, "approved_for_operational_use")


# --- Pattern / Case linkage ------------------------------------------------


def link_pattern(
    db: Session, question_id: uuid.UUID, pattern_id: uuid.UUID, organization_id: uuid.UUID
) -> DIQuestionPattern:
    question = get_question(db, question_id, organization_id)
    di_pattern_service.get_pattern(db, pattern_id, organization_id)
    link = DIQuestionPattern(question_id=question.id, pattern_id=pattern_id)
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(
            select(DIQuestionPattern).where(
                DIQuestionPattern.question_id == question.id, DIQuestionPattern.pattern_id == pattern_id
            )
        )
    db.refresh(link)
    return link


def unlink_pattern(db: Session, question_id: uuid.UUID, pattern_id: uuid.UUID, organization_id: uuid.UUID) -> None:
    get_question(db, question_id, organization_id)
    link = db.scalar(
        select(DIQuestionPattern).where(
            DIQuestionPattern.question_id == question_id, DIQuestionPattern.pattern_id == pattern_id
        )
    )
    if link is not None:
        db.delete(link)
        db.commit()


def link_case(db: Session, question_id: uuid.UUID, case_id: uuid.UUID, organization_id: uuid.UUID) -> DIQuestionCase:
    question = get_question(db, question_id, organization_id)
    di_case_service.get_case(db, case_id, organization_id)
    link = DIQuestionCase(question_id=question.id, case_id=case_id)
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(
            select(DIQuestionCase).where(DIQuestionCase.question_id == question.id, DIQuestionCase.case_id == case_id)
        )
    db.refresh(link)
    return link


def unlink_case(db: Session, question_id: uuid.UUID, case_id: uuid.UUID, organization_id: uuid.UUID) -> None:
    get_question(db, question_id, organization_id)
    link = db.scalar(
        select(DIQuestionCase).where(DIQuestionCase.question_id == question_id, DIQuestionCase.case_id == case_id)
    )
    if link is not None:
        db.delete(link)
        db.commit()


def list_linked_patterns(db: Session, question_id: uuid.UUID, organization_id: uuid.UUID) -> list[DIPattern]:
    get_question(db, question_id, organization_id)
    stmt = (
        select(DIPattern)
        .join(DIQuestionPattern, DIQuestionPattern.pattern_id == DIPattern.id)
        .where(DIQuestionPattern.question_id == question_id)
    )
    return list(db.scalars(stmt))


def list_linked_cases(db: Session, question_id: uuid.UUID, organization_id: uuid.UUID) -> list[uuid.UUID]:
    get_question(db, question_id, organization_id)
    return list(db.scalars(select(DIQuestionCase.case_id).where(DIQuestionCase.question_id == question_id)))
