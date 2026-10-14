"""Decision Intelligence: creating and running a DIReplayRun.

Runs synchronously, in the same request/transaction that creates it
(documented choice, matching replay_executor.py's own docstring): at this
product's scale -- replaying a candidate rule against one workflow's case
set, not a production transaction stream -- a background job queue is
infrastructure this module does not yet need. If that scale assumption
stops holding, the natural evolution is making `create_and_run_replay`
enqueue the row and return it `pending` for a worker to pick up, without
changing `_run_replay`'s own signature at all.

This is the ONLY place that actually executes a replay (loads the rule
version's schema_json, loads the selected DICase rows, classifies each
one via the pure `app.domain.decision_intelligence.replay_executor.
evaluate_case`, writes one DIReplayCaseResult row per case, and writes
the aggregate `summary` onto DIReplayRun) -- deliberately a service, not
a domain/ module: this codebase enforces domain/ never importing app.db
(SPECIFICATION/26_PHASE_2_DEPENDENCY_DECLARATION.md section 26.4.2,
test_architectural_boundaries.py), so the persistence/orchestration half
of "run a replay" lives here, while replay_executor.py keeps only the
pure evaluate/classify half both this service and rules.py's "test this
rule" endpoint share.

A `start` DIAuditEvent is written before execution begins (this module's
own brief: "ReplayRuns (start)"), not after -- even a replay that goes on
to fail leaves an honest record that it was started. Never touches any
Runtime Authority table, and never executes anything live -- a reporting/
evaluation operation only."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DIAnswer, DICase, DIDecisionRule, DIReplayCaseResult, DIReplayRun, DIRuleVersion
from app.domain.decision_intelligence.replay_executor import OUTCOME_CATEGORIES, evaluate_case
from app.domain.decision_intelligence.rule_schema import RuleSchema
from app.services import di_audit_service, di_question_service, di_workflow_service


class ReplayRuleVersionNotFoundError(Exception):
    pass


def _resolve_case_ids(db: Session, replay_run: DIReplayRun) -> list[uuid.UUID]:
    """`case_set_definition` is stored exactly as the caller supplied it:
    either `{"case_ids": [...]}`, an explicit list, or `{"filter": {...}}`,
    a simple description re-applied here at execution time. Always
    re-scoped to this replay run's own organization_id/workflow_id
    regardless of which form was used, so a hand-edited case_set_
    definition can never reach across organizations."""
    definition = replay_run.case_set_definition or {}

    if "case_ids" in definition:
        requested_ids = {uuid.UUID(str(cid)) for cid in definition["case_ids"]}
        stmt = select(DICase.id).where(
            DICase.id.in_(requested_ids),
            DICase.organization_id == replay_run.organization_id,
            DICase.workflow_id == replay_run.workflow_id,
        )
        return list(db.scalars(stmt))

    filter_spec = definition.get("filter", {})
    stmt = select(DICase.id).where(
        DICase.organization_id == replay_run.organization_id,
        DICase.workflow_id == replay_run.workflow_id,
    )
    status = filter_spec.get("status")
    if status:
        stmt = stmt.where(DICase.status == status)
    return list(db.scalars(stmt))


def _run_replay(db: Session, replay_run: DIReplayRun) -> None:
    """Executes `replay_run` end to end. Mutates and commits `replay_run`
    and the new DIReplayCaseResult rows; raises only for a programming
    error (an unresolvable rule version), never for a single case's own
    evaluation failure -- that is recorded as an "error" outcome_category
    row instead, so one bad case can never abort an entire replay."""
    rule_version = db.get(DIRuleVersion, replay_run.rule_version_id)
    if rule_version is None:
        raise ReplayRuleVersionNotFoundError(str(replay_run.rule_version_id))
    rule = RuleSchema.model_validate(rule_version.schema_json)

    replay_run.status = "running"
    replay_run.started_at = datetime.now(timezone.utc)
    db.commit()

    case_ids = _resolve_case_ids(db, replay_run)
    cases = list(db.scalars(select(DICase).where(DICase.id.in_(case_ids)))) if case_ids else []

    counts = {category: 0 for category in OUTCOME_CATEGORIES}

    for case in cases:
        try:
            evaluation, outcome_category, notes = evaluate_case(rule, case.facts or {}, case.human_decision)
            proposed_decision = {
                "decision": evaluation.decision,
                "human_review_required": evaluation.human_review_required,
            }
            matched_conditions = evaluation.matched_conditions
            unmatched_conditions = evaluation.unmatched_conditions
        except Exception as e:  # noqa: BLE001 -- one case's failure must not abort the replay
            outcome_category, notes = "error", str(e)
            proposed_decision = None
            matched_conditions = None
            unmatched_conditions = None

        counts[outcome_category] += 1
        db.add(
            DIReplayCaseResult(
                replay_run_id=replay_run.id,
                case_id=case.id,
                baseline_decision=case.human_decision,
                proposed_decision=proposed_decision,
                matched_conditions=matched_conditions,
                unmatched_conditions=unmatched_conditions,
                outcome_category=outcome_category,
                notes=notes,
            )
        )

    replay_run.status = "completed"
    replay_run.completed_at = datetime.now(timezone.utc)
    replay_run.summary = {"total_cases": len(cases), "counts": counts}
    db.commit()


class ReplayRunNotFoundError(Exception):
    pass


class RuleVersionNotFoundError(Exception):
    pass


def _resolve_rule_version(db: Session, rule_version_id: uuid.UUID, organization_id: uuid.UUID, workflow_id: uuid.UUID) -> DIRuleVersion:
    version = db.get(DIRuleVersion, rule_version_id)
    if version is None:
        raise RuleVersionNotFoundError(str(rule_version_id))
    rule = db.get(DIDecisionRule, version.rule_id)
    if rule is None or rule.organization_id != organization_id or rule.workflow_id != workflow_id:
        raise RuleVersionNotFoundError(str(rule_version_id))
    return version


def create_and_run_replay(
    db: Session,
    organization_id: uuid.UUID,
    workflow_id: uuid.UUID,
    rule_version_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    case_ids: list[uuid.UUID] | None = None,
    filter_status: str | None = None,
) -> DIReplayRun:
    di_workflow_service.get_workflow(db, workflow_id, organization_id)
    _resolve_rule_version(db, rule_version_id, organization_id, workflow_id)

    if case_ids:
        case_set_definition = {"case_ids": [str(cid) for cid in case_ids]}
    else:
        case_set_definition = {"filter": {k: v for k, v in {"status": filter_status}.items() if v is not None}}

    replay_run = DIReplayRun(
        organization_id=organization_id,
        workflow_id=workflow_id,
        rule_version_id=rule_version_id,
        case_set_definition=case_set_definition,
        status="pending",
        created_by_user_id=created_by_user_id,
    )
    db.add(replay_run)
    db.flush()

    di_audit_service.record_event(
        db, organization_id, created_by_user_id, action="start", entity_type="DIReplayRun", entity_id=replay_run.id,
        new_value={"rule_version_id": str(rule_version_id), "case_set_definition": case_set_definition},
    )
    db.commit()
    db.refresh(replay_run)

    _run_replay(db, replay_run)  # synchronous; mutates and commits replay_run itself

    if replay_run.status == "completed":
        # Resolve the question this rule traces back to (rule ->
        # source_answer -> question) and advance it -- best-effort: a
        # replay is still a complete, valid replay even if this rule was
        # never linked all the way back to a question (e.g. authored
        # directly for ad hoc testing).
        rule_version = db.get(DIRuleVersion, rule_version_id)
        rule = db.get(DIDecisionRule, rule_version.rule_id) if rule_version else None
        answer = db.get(DIAnswer, rule.source_answer_id) if rule else None
        if answer is not None:
            try:
                question = di_question_service.get_question(db, answer.question_id, organization_id)
                di_question_service._apply_status(db, question, "replay_completed")
                db.commit()
            except di_question_service.QuestionNotFoundError:
                pass

    db.refresh(replay_run)
    return replay_run


def get_replay_run(db: Session, replay_run_id: uuid.UUID, organization_id: uuid.UUID) -> DIReplayRun:
    replay_run = db.get(DIReplayRun, replay_run_id)
    if replay_run is None or replay_run.organization_id != organization_id:
        raise ReplayRunNotFoundError(str(replay_run_id))
    return replay_run


def list_replay_runs(
    db: Session,
    organization_id: uuid.UUID,
    workflow_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[DIReplayRun], int]:
    stmt = select(DIReplayRun).where(DIReplayRun.organization_id == organization_id)
    if workflow_id is not None:
        stmt = stmt.where(DIReplayRun.workflow_id == workflow_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(DIReplayRun.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt)), total


def list_replay_case_results(
    db: Session, replay_run_id: uuid.UUID, organization_id: uuid.UUID, limit: int = 100, offset: int = 0
) -> tuple[list[DIReplayCaseResult], int]:
    get_replay_run(db, replay_run_id, organization_id)  # raises if wrong org / missing
    stmt = select(DIReplayCaseResult).where(DIReplayCaseResult.replay_run_id == replay_run_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(DIReplayCaseResult.id).limit(limit).offset(offset)
    return list(db.scalars(stmt)), total
