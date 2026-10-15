"""Decision Intelligence: reporting and real-export queries.

Originally shipped with exactly one endpoint, GET /v1/decision-
intelligence/workflows/{id}/overview. Feature: cross-workflow reports and
real exports adds (1) an organization-wide aggregate across every
workflow, and (2) the row-building queries behind this module's two real
CSV exports (Priority Questions, Replay results) -- CSV *rendering*
(sanitization, RFC 4180 writing) stays in the pure
`app.domain.decision_intelligence.csv_export` module; this file only ever
produces the plain rows.

Every number below is a real, live query against the actual persisted
rows -- there is no hardcoded or estimated figure anywhere in this
module."""

import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    DIAnswer,
    DICase,
    DIDecisionRule,
    DIPattern,
    DIQuestion,
    DIQuestionCase,
    DIQuestionPattern,
    DIReplayRun,
    DIWorkflow,
)
from app.services import di_replay_service, di_workflow_service


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


# --- Cross-workflow organization overview -----------------------------


def _counts_by_workflow(db: Session, organization_id: uuid.UUID, model, status_filter=None) -> dict[uuid.UUID, int]:
    """Shared helper: `{workflow_id: count}` for any DI model that carries
    its own `workflow_id`/`organization_id` columns directly (DICase,
    DIPattern, DIQuestion, DIDecisionRule, DIReplayRun) -- a single real
    GROUP BY per table, never one query per workflow."""
    stmt = select(model.workflow_id, func.count()).where(model.organization_id == organization_id)
    if status_filter is not None:
        stmt = stmt.where(model.status == status_filter)
    stmt = stmt.group_by(model.workflow_id)
    return {workflow_id: count for workflow_id, count in db.execute(stmt)}


def _answer_counts_by_workflow(db: Session, organization_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """DIAnswer has no organization_id/workflow_id of its own (see its own
    model docstring -- reachable only via question_id), so this one needs
    its own join, same as get_workflow_overview's own
    answers_awaiting_approval query above."""
    stmt = (
        select(DIQuestion.workflow_id, func.count())
        .select_from(DIAnswer)
        .join(DIQuestion, DIQuestion.id == DIAnswer.question_id)
        .where(DIQuestion.organization_id == organization_id)
        .group_by(DIQuestion.workflow_id)
    )
    return {workflow_id: count for workflow_id, count in db.execute(stmt)}


def get_organization_overview(db: Session, organization_id: uuid.UUID) -> dict:
    """Feature: cross-workflow reports. Real aggregate totals (cases,
    patterns, questions, answers, rules, replays) across EVERY workflow in
    the caller's organization, plus a real per-workflow breakdown -- every
    number here is computed from the same tables get_workflow_overview
    already queries, just grouped across the whole organization instead of
    scoped to one workflow, never cached or hardcoded. A workflow with zero
    activity in every category still appears in `by_workflow` (left-joined
    in Python below, not dropped by an inner GROUP BY), so an organization
    can see it has an empty workflow rather than that workflow silently
    vanishing from the report."""
    workflows = list(
        db.scalars(select(DIWorkflow).where(DIWorkflow.organization_id == organization_id).order_by(DIWorkflow.created_at))
    )

    cases_by_workflow = _counts_by_workflow(db, organization_id, DICase)
    patterns_by_workflow = _counts_by_workflow(db, organization_id, DIPattern)
    questions_by_workflow = _counts_by_workflow(db, organization_id, DIQuestion)
    rules_by_workflow = _counts_by_workflow(db, organization_id, DIDecisionRule)
    replays_by_workflow = _counts_by_workflow(db, organization_id, DIReplayRun)
    answers_by_workflow = _answer_counts_by_workflow(db, organization_id)

    by_workflow = []
    for workflow in workflows:
        by_workflow.append(
            {
                "workflow_id": workflow.id,
                "workflow_name": workflow.name,
                "case_count": cases_by_workflow.get(workflow.id, 0),
                "pattern_count": patterns_by_workflow.get(workflow.id, 0),
                "question_count": questions_by_workflow.get(workflow.id, 0),
                "answer_count": answers_by_workflow.get(workflow.id, 0),
                "rule_count": rules_by_workflow.get(workflow.id, 0),
                "replay_count": replays_by_workflow.get(workflow.id, 0),
            }
        )

    return {
        "organization_id": organization_id,
        "workflow_count": len(workflows),
        "total_cases": sum(cases_by_workflow.values()),
        "total_patterns": sum(patterns_by_workflow.values()),
        "total_questions": sum(questions_by_workflow.values()),
        "total_answers": sum(answers_by_workflow.values()),
        "total_rules": sum(rules_by_workflow.values()),
        "total_replays": sum(replays_by_workflow.values()),
        "by_workflow": by_workflow,
    }


# --- Export row-builders -------------------------------------------------
#
# These return plain rows (lists of plain values); CSV rendering itself
# (header, RFC 4180 quoting, the formula-injection guard) is
# app.domain.decision_intelligence.csv_export.build_csv's job, not this
# module's -- kept separate so the injection guard lives in exactly one
# place no matter how many exports this module grows.

PRIORITY_QUESTIONS_EXPORT_HEADER = [
    "id", "title", "status", "priority_score", "owner_user_id", "linked_pattern_count", "linked_case_count",
]

REPLAY_RESULTS_EXPORT_HEADER = [
    "case_id", "case_external_ref", "baseline_decision", "proposed_decision", "outcome_category", "notes",
]


def get_priority_questions_export_rows(
    db: Session, organization_id: uuid.UUID, workflow_id: uuid.UUID | None = None
) -> list[list]:
    """Row data for the Priority Questions CSV export: id, title, status,
    priority_score, owner, and real linked pattern/case counts (two more
    real queries, never a placeholder), ordered highest priority_score
    first (nulls last) -- the same ordering `GET /questions?sort_by=
    priority_score` already uses, since an export of this list is most
    useful sorted the same way the screen it's exported from is."""
    stmt = select(DIQuestion).where(DIQuestion.organization_id == organization_id)
    if workflow_id is not None:
        stmt = stmt.where(DIQuestion.workflow_id == workflow_id)
    stmt = stmt.order_by(DIQuestion.priority_score.desc().nullslast())
    questions = list(db.scalars(stmt))

    pattern_counts = {
        qid: count
        for qid, count in db.execute(
            select(DIQuestionPattern.question_id, func.count())
            .where(DIQuestionPattern.question_id.in_([q.id for q in questions]))
            .group_by(DIQuestionPattern.question_id)
        )
    } if questions else {}
    case_counts = {
        qid: count
        for qid, count in db.execute(
            select(DIQuestionCase.question_id, func.count())
            .where(DIQuestionCase.question_id.in_([q.id for q in questions]))
            .group_by(DIQuestionCase.question_id)
        )
    } if questions else {}

    return [
        [
            str(q.id),
            q.title,
            q.status,
            float(q.priority_score) if q.priority_score is not None else None,
            str(q.owner_user_id) if q.owner_user_id else None,
            pattern_counts.get(q.id, 0),
            case_counts.get(q.id, 0),
        ]
        for q in questions
    ]


def get_replay_results_export_rows(db: Session, replay_run_id: uuid.UUID, organization_id: uuid.UUID) -> list[list]:
    """Row data for one Replay run's per-case results CSV export:
    case_id, the case's own external_ref (for a human to cross-reference
    without a second lookup), baseline_decision/proposed_decision (JSON-
    serialized, since both are structured JSONB in the database), and
    outcome_category/notes exactly as replay_executor.py classified them.
    Raises ReplayRunNotFoundError via di_replay_service.get_replay_run if
    `replay_run_id` doesn't resolve in this organization."""
    di_replay_service.get_replay_run(db, replay_run_id, organization_id)  # raises if missing/wrong org
    results, _total = di_replay_service.list_replay_case_results(db, replay_run_id, organization_id, limit=100000)

    case_ids = [r.case_id for r in results]
    external_refs = {
        cid: ref
        for cid, ref in db.execute(select(DICase.id, DICase.external_ref).where(DICase.id.in_(case_ids)))
    } if case_ids else {}

    return [
        [
            str(r.case_id),
            external_refs.get(r.case_id),
            json.dumps(r.baseline_decision) if r.baseline_decision is not None else None,
            json.dumps(r.proposed_decision) if r.proposed_decision is not None else None,
            r.outcome_category,
            r.notes,
        ]
        for r in results
    ]


#: Feature: lightweight customer-comparison template (brief Part 8). One
#: row per metric the brief itself names, two blank columns for a human
#: to fill in while running the SAME task both ways -- deliberately not a
#: full experimentation platform, just a structured starting point. Never
#: pre-filled with a number this module hasn't actually measured.
COMPARISON_TEMPLATE_HEADER = ["metric", "current_method", "payreality", "notes"]
COMPARISON_TEMPLATE_METRICS = [
    "Time spent preparing (hours)",
    "Time spent reviewing (hours)",
    "Useful questions identified (count)",
    "Irrelevant or duplicate questions (count)",
    "Important questions missed, that an expert could identify (count)",
    "Cases whose handling could change as a result (count)",
    "Result on separately reviewed evaluation cases (free text)",
]


def get_comparison_template_rows(
    db: Session, organization_id: uuid.UUID, workflow_id: uuid.UUID
) -> list[list]:
    """Blank metric rows (the human fills in `current_method`/
    `payreality`/`notes` themselves) PLUS the workflow's own real,
    current Priority Questions as a concrete starting point for counting
    "useful questions identified" against -- never a fabricated example
    list. Raises WorkflowNotFoundError via di_workflow_service.get_workflow
    if the workflow doesn't resolve in this organization."""
    di_workflow_service.get_workflow(db, workflow_id, organization_id)

    rows = [[metric, "", "", ""] for metric in COMPARISON_TEMPLATE_METRICS]
    rows.append(["", "", "", ""])
    rows.append(["-- Current Priority Questions for this workflow, for reference --", "", "", ""])

    questions = list(
        db.scalars(
            select(DIQuestion)
            .where(DIQuestion.organization_id == organization_id, DIQuestion.workflow_id == workflow_id)
            .order_by(DIQuestion.priority_score.desc().nullslast())
        )
    )
    for q in questions:
        rows.append([q.title, str(q.priority_score) if q.priority_score is not None else "not yet assessed", q.status, ""])
    return rows
