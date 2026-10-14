"""Decision Intelligence: the one minimal reporting endpoint this module
ships, GET /v1/decision-intelligence/workflows/{id}/overview. Every
number below is a real, live query against the actual persisted rows for
that workflow -- there is no hardcoded or estimated figure anywhere in
this module."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DIAnswer, DICase, DIDecisionRule, DIPattern, DIQuestion, DIReplayRun
from app.services import di_workflow_service


def get_workflow_overview(db: Session, workflow_id: uuid.UUID, organization_id: uuid.UUID) -> dict:
    di_workflow_service.get_workflow(db, workflow_id, organization_id)  # raises if missing/wrong org

    case_count = db.scalar(
        select(func.count()).select_from(DICase).where(DICase.workflow_id == workflow_id)
    ) or 0
    unresolved_case_count = db.scalar(
        select(func.count()).select_from(DICase).where(
            DICase.workflow_id == workflow_id, DICase.status != "resolved"
        )
    ) or 0
    pattern_count = db.scalar(
        select(func.count()).select_from(DIPattern).where(DIPattern.workflow_id == workflow_id)
    ) or 0

    questions_by_status: dict[str, int] = {
        status: count
        for status, count in db.execute(
            select(DIQuestion.status, func.count())
            .where(DIQuestion.workflow_id == workflow_id)
            .group_by(DIQuestion.status)
        )
    }

    answers_awaiting_approval = db.scalar(
        select(func.count())
        .select_from(DIAnswer)
        .join(DIQuestion, DIQuestion.id == DIAnswer.question_id)
        .where(DIQuestion.workflow_id == workflow_id, DIAnswer.status.in_(("submitted", "under_review")))
    ) or 0

    rules_validated = db.scalar(
        select(func.count())
        .select_from(DIDecisionRule)
        .where(DIDecisionRule.workflow_id == workflow_id, DIDecisionRule.status == "validated")
    ) or 0

    replays_completed = db.scalar(
        select(func.count())
        .select_from(DIReplayRun)
        .where(DIReplayRun.workflow_id == workflow_id, DIReplayRun.status == "completed")
    ) or 0

    return {
        "workflow_id": workflow_id,
        "case_count": case_count,
        "unresolved_case_count": unresolved_case_count,
        "pattern_count": pattern_count,
        "questions_by_status": questions_by_status,
        "answers_awaiting_approval": answers_awaiting_approval,
        "rules_validated": rules_validated,
        "replays_completed": replays_completed,
    }
