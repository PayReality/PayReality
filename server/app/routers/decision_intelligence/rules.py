from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization, User
from app.db.session import get_db
from app.dependencies import get_current_organization, get_current_user, require_permission
from app.domain.decision_intelligence.rule_evaluator import EvaluationResult
from app.domain.decision_intelligence.validation import RuleValidationError
from app.domain.rbac.permissions import Permission
from app.schemas.decision_intelligence import (
    CreateRuleRequest,
    CreateRuleVersionRequest,
    RuleListResponse,
    RuleResponse,
    RuleVersionResponse,
    TestRuleRequest,
)
from app.services import di_rule_service
from app.services.di_case_service import CaseNotFoundError
from app.services.di_rule_service import RuleNotFoundError, RuleVersionNotFoundError, SourceAnswerNotApprovedError
from app.services.di_workflow_service import WorkflowNotFoundError

router = APIRouter(prefix="/v1/decision-intelligence/rules", tags=["decision-intelligence"])


@router.post(
    "", response_model=RuleResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.DI_RULE_MANAGE))],
)
def create_rule(
    body: CreateRuleRequest,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return di_rule_service.create_rule(
            db, organization.id, body.workflow_id, user.id, body.name, body.source_answer_id,
            body.schema_json.model_dump(),
        )
    except WorkflowNotFoundError:
        raise HTTPException(status_code=404, detail="workflow_not_found")
    except SourceAnswerNotApprovedError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get(
    "", response_model=RuleListResponse,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_VIEW))],
)
def list_rules(
    workflow_id: UUID | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    rules, total = di_rule_service.list_rules(
        db, organization.id, workflow_id=workflow_id, status=status, limit=limit, offset=offset
    )
    return RuleListResponse(rules=rules, total=total, limit=limit, offset=offset)


@router.get(
    "/{rule_id}", response_model=RuleResponse,
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_VIEW))],
)
def get_rule(rule_id: UUID, organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)):
    try:
        return di_rule_service.get_rule(db, rule_id, organization.id)
    except RuleNotFoundError:
        raise HTTPException(status_code=404, detail="rule_not_found")


@router.get(
    "/{rule_id}/versions", response_model=list[RuleVersionResponse],
    dependencies=[Depends(require_permission(Permission.DI_QUESTION_VIEW))],
)
def list_rule_versions(
    rule_id: UUID, organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)
):
    try:
        return di_rule_service.list_versions(db, rule_id, organization.id)
    except RuleNotFoundError:
        raise HTTPException(status_code=404, detail="rule_not_found")


@router.post(
    "/{rule_id}/versions", response_model=RuleVersionResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.DI_RULE_MANAGE))],
)
def create_rule_version(
    rule_id: UUID,
    body: CreateRuleVersionRequest,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return di_rule_service.create_rule_version(
            db, rule_id, organization.id, user.id, body.schema_json.model_dump(), scope=body.scope
        )
    except RuleNotFoundError:
        raise HTTPException(status_code=404, detail="rule_not_found")


@router.post(
    "/{rule_id}/validate", response_model=RuleResponse,
    dependencies=[Depends(require_permission(Permission.DI_RULE_MANAGE))],
)
def validate_rule(
    rule_id: UUID,
    organization: Organization = Depends(get_current_organization),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return di_rule_service.validate_rule(db, rule_id, organization.id, user.id)
    except RuleNotFoundError:
        raise HTTPException(status_code=404, detail="rule_not_found")
    except RuleVersionNotFoundError:
        raise HTTPException(status_code=409, detail="rule_has_no_current_version")
    except RuleValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post(
    "/{rule_id}/test", response_model=EvaluationResult,
    dependencies=[Depends(require_permission(Permission.DI_RULE_MANAGE))],
)
def test_rule(
    rule_id: UUID,
    body: TestRuleRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Never persists anything -- this is purely "what would this rule's
    current version do against this data", using the same evaluate_rule
    interpreter the real replay executor uses."""
    try:
        return di_rule_service.test_rule(
            db, rule_id, organization.id, case_facts=body.case_facts, case_id=body.case_id
        )
    except RuleNotFoundError:
        raise HTTPException(status_code=404, detail="rule_not_found")
    except RuleVersionNotFoundError:
        raise HTTPException(status_code=409, detail="rule_has_no_current_version")
    except CaseNotFoundError:
        raise HTTPException(status_code=404, detail="case_not_found")
