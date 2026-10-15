"""Decision Intelligence: DIDecisionRule / DIRuleVersion authoring and
validation, and the "test this rule" inspection endpoint's own service
layer.

A rule may only be CREATED from an `approved` DIAnswer, and may only be
marked `validated` once `validation.py`'s own checks pass (re-checked
here, not trusted from creation time, since the source answer could have
been superseded in between) -- both are real governance gates, not
formalities. Editing a rule never mutates an existing DIRuleVersion's own
schema_json; it always inserts a new version row and repoints the parent
rule's `current_version_id`, matching this codebase's established
"never mutate, always append a new version" discipline for RuntimePolicy."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DIAnswer, DIDecisionRule, DIRuleVersion
from app.domain.decision_intelligence.rule_evaluator import EvaluationResult, evaluate_rule
from app.domain.decision_intelligence.rule_schema import RuleSchema
from app.domain.decision_intelligence.validation import validate_rule_version
from app.services import di_audit_service, di_case_service, di_question_service, di_workflow_service


class RuleNotFoundError(Exception):
    pass


class RuleVersionNotFoundError(Exception):
    pass


class SourceAnswerNotApprovedError(Exception):
    pass


def _answer_and_question(db: Session, answer_id: uuid.UUID, organization_id: uuid.UUID):
    answer = db.get(DIAnswer, answer_id)
    if answer is None:
        raise SourceAnswerNotApprovedError(f"source_answer_not_found: {answer_id}")
    question = di_question_service.get_question(db, answer.question_id, organization_id)
    return answer, question


def create_rule(
    db: Session,
    organization_id: uuid.UUID,
    workflow_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    name: str,
    source_answer_id: uuid.UUID,
    schema_json: dict,
) -> DIDecisionRule:
    di_workflow_service.get_workflow(db, workflow_id, organization_id)
    answer, question = _answer_and_question(db, source_answer_id, organization_id)
    if answer.status != "approved":
        raise SourceAnswerNotApprovedError(
            f"source_answer {source_answer_id} has status '{answer.status}', must be 'approved'"
        )

    # Structural validation only (does this parse as a well-formed rule
    # tree at all) -- pydantic raises ValidationError for the router to
    # translate into a 422. The GOVERNANCE check (validation.py) only
    # ever runs at explicit validate_rule time, never here.
    RuleSchema.model_validate(schema_json)

    rule = DIDecisionRule(
        organization_id=organization_id,
        workflow_id=workflow_id,
        name=name,
        source_answer_id=source_answer_id,
        created_by_user_id=created_by_user_id,
        status="draft",
    )
    db.add(rule)
    db.flush()

    version = DIRuleVersion(
        rule_id=rule.id, version=1, schema_json=schema_json, created_by_user_id=created_by_user_id
    )
    db.add(version)
    db.flush()

    rule.current_version_id = version.id
    db.add(rule)

    di_question_service._apply_status(db, question, "logic_drafted")

    di_audit_service.record_event(
        db, organization_id, created_by_user_id, action="create", entity_type="DIDecisionRule", entity_id=rule.id,
        new_value={"name": name, "source_answer_id": str(source_answer_id), "version": 1},
    )
    db.commit()
    db.refresh(rule)
    return rule


def get_rule(db: Session, rule_id: uuid.UUID, organization_id: uuid.UUID) -> DIDecisionRule:
    rule = db.get(DIDecisionRule, rule_id)
    if rule is None or rule.organization_id != organization_id:
        raise RuleNotFoundError(str(rule_id))
    return rule


def list_rules(
    db: Session,
    organization_id: uuid.UUID,
    workflow_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[DIDecisionRule], int]:
    stmt = select(DIDecisionRule).where(DIDecisionRule.organization_id == organization_id)
    if workflow_id is not None:
        stmt = stmt.where(DIDecisionRule.workflow_id == workflow_id)
    if status:
        stmt = stmt.where(DIDecisionRule.status == status)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(DIDecisionRule.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt)), total


def get_current_version(db: Session, rule: DIDecisionRule) -> DIRuleVersion:
    if rule.current_version_id is None:
        raise RuleVersionNotFoundError(f"rule {rule.id} has no current version")
    version = db.get(DIRuleVersion, rule.current_version_id)
    if version is None:
        raise RuleVersionNotFoundError(str(rule.current_version_id))
    return version


def list_versions(db: Session, rule_id: uuid.UUID, organization_id: uuid.UUID) -> list[DIRuleVersion]:
    get_rule(db, rule_id, organization_id)
    return list(
        db.scalars(select(DIRuleVersion).where(DIRuleVersion.rule_id == rule_id).order_by(DIRuleVersion.version.desc()))
    )


def create_rule_version(
    db: Session,
    rule_id: uuid.UUID,
    organization_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    schema_json: dict,
    scope: str | None = None,
) -> DIRuleVersion:
    rule = get_rule(db, rule_id, organization_id)
    RuleSchema.model_validate(schema_json)

    latest_version_number = db.scalar(
        select(func.max(DIRuleVersion.version)).where(DIRuleVersion.rule_id == rule.id)
    ) or 0

    version = DIRuleVersion(
        rule_id=rule.id, version=latest_version_number + 1, schema_json=schema_json, scope=scope,
        created_by_user_id=created_by_user_id,
    )
    db.add(version)
    db.flush()

    previous_status = rule.status
    rule.current_version_id = version.id
    # A new version is an un-validated hypothesis again, even if the
    # previous version had been validated -- validation is per-version,
    # never inherited.
    rule.status = "draft"
    db.add(rule)

    _, question = _answer_and_question(db, rule.source_answer_id, organization_id)
    di_question_service._apply_status(db, question, "logic_drafted")

    di_audit_service.record_event(
        db, organization_id, created_by_user_id, action="create_version", entity_type="DIDecisionRule",
        entity_id=rule.id, previous_value={"status": previous_status},
        new_value={"status": rule.status, "version": version.version},
    )
    db.commit()
    db.refresh(version)
    return version


def validate_rule(db: Session, rule_id: uuid.UUID, organization_id: uuid.UUID, actor_user_id: uuid.UUID) -> DIDecisionRule:
    """Raises validation.RuleValidationError (unchanged) if the current
    version fails either of validation.py's two checks -- never silently
    marks a rule validated on a failed check."""
    rule = get_rule(db, rule_id, organization_id)
    version = get_current_version(db, rule)
    source_answer = db.get(DIAnswer, rule.source_answer_id)

    # validation.py is a pure domain module (no app.db import allowed --
    # see its own docstring) -- resolve the actual rows here and pass
    # plain values across the boundary.
    validate_rule_version(
        version.schema_json, source_answer.status if source_answer is not None else None
    )  # raises RuleValidationError on failure

    previous_status = rule.status
    rule.status = "validated"
    db.add(rule)

    _, question = _answer_and_question(db, rule.source_answer_id, organization_id)
    di_question_service._apply_status(db, question, "logic_validated")

    di_audit_service.record_event(
        db, organization_id, actor_user_id, action="validate", entity_type="DIDecisionRule", entity_id=rule.id,
        previous_value={"status": previous_status}, new_value={"status": "validated", "version": version.version},
    )
    db.commit()
    db.refresh(rule)
    return rule


def test_rule(
    db: Session,
    rule_id: uuid.UUID,
    organization_id: uuid.UUID,
    case_facts: dict | None = None,
    case_id: uuid.UUID | None = None,
) -> EvaluationResult:
    """Runs the rule's CURRENT version against either a supplied facts
    payload or an existing case's own facts -- never persists anything.
    The exact same `evaluate_rule` function the real replay executor
    uses, so "what would this rule do" here can never diverge from what
    a replay later actually records."""
    rule = get_rule(db, rule_id, organization_id)
    version = get_current_version(db, rule)
    schema = RuleSchema.model_validate(version.schema_json)

    if case_id is not None:
        case = di_case_service.get_case(db, case_id, organization_id)
        facts = case.facts or {}
    else:
        facts = case_facts or {}

    return evaluate_rule(schema, facts)
