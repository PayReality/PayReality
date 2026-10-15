"""Decision Intelligence: DICase CRUD -- the real, concrete instances of a
workflow's recurring decision that patterns and questions are discovered
from."""

import uuid

from sqlalchemy import cast, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.types import Text as SA_Text

from app.db.models import DICase
from app.services import di_workflow_service


class CaseNotFoundError(Exception):
    pass


def create_case(
    db: Session,
    organization_id: uuid.UUID,
    workflow_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    facts: dict,
    external_ref: str | None = None,
    evidence_refs: list | None = None,
    ai_recommendation: dict | None = None,
    human_decision: dict | None = None,
    escalation_reason: str | None = None,
    outcome: str | None = None,
    outcome_evidence: str | None = None,
) -> DICase:
    # Raises WorkflowNotFoundError (propagated to the router) if workflow_id
    # doesn't belong to this organization -- a case can never be filed
    # against another organization's workflow.
    di_workflow_service.get_workflow(db, workflow_id, organization_id)

    case = DICase(
        organization_id=organization_id,
        workflow_id=workflow_id,
        created_by_user_id=created_by_user_id,
        facts=facts or {},
        external_ref=external_ref,
        evidence_refs=evidence_refs,
        ai_recommendation=ai_recommendation,
        human_decision=human_decision,
        escalation_reason=escalation_reason,
        outcome=outcome,
        outcome_evidence=outcome_evidence,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def get_case(db: Session, case_id: uuid.UUID, organization_id: uuid.UUID) -> DICase:
    case = db.get(DICase, case_id)
    if case is None or case.organization_id != organization_id:
        raise CaseNotFoundError(str(case_id))
    return case


def _apply_search_filter(stmt, q: str | None):
    """Feature: server-side case search, factored out of list_cases below
    purely so it can be unit-tested as a statement-building function
    (compiled to SQL text and inspected) without needing a real database
    connection -- SQLAlchemy Core statement construction is itself pure/
    lazy, only `db.scalars(stmt)` below actually touches Postgres.

    `q`, when given, matches case-insensitive substrings against
    `external_ref` OR against `facts` (via `facts::text ILIKE`, a
    Postgres JSONB-as-text search) -- the brief's own documented, demo-
    scale-appropriate simple approach, chosen over a GIN-indexed `@@`
    full-text search for this pass; a matching trigram-GIN index is added
    in this feature's migration so the ILIKE queries are real and
    indexed, not a sequential scan, even though the query itself stays
    simple."""
    if not q:
        return stmt
    pattern = f"%{q}%"
    return stmt.where(
        or_(
            DICase.external_ref.ilike(pattern),
            cast(DICase.facts, SA_Text).ilike(pattern),
        )
    )


def list_cases(
    db: Session,
    organization_id: uuid.UUID,
    workflow_id: uuid.UUID | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[DICase], int]:
    """`q` is always combined with the organization_id/workflow_id
    scoping below -- it can never be used to search outside the caller's
    own organization. See `_apply_search_filter` above for what `q`
    actually matches against."""
    stmt = select(DICase).where(DICase.organization_id == organization_id)
    if workflow_id is not None:
        stmt = stmt.where(DICase.workflow_id == workflow_id)
    if status:
        stmt = stmt.where(DICase.status == status)
    stmt = _apply_search_filter(stmt, q)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(DICase.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt)), total


def update_case(
    db: Session,
    case_id: uuid.UUID,
    organization_id: uuid.UUID,
    facts: dict | None = None,
    evidence_refs: list | None = None,
    ai_recommendation: dict | None = None,
    human_decision: dict | None = None,
    escalation_reason: str | None = None,
    outcome: str | None = None,
    outcome_evidence: str | None = None,
    status: str | None = None,
) -> DICase:
    case = get_case(db, case_id, organization_id)
    if facts is not None:
        case.facts = facts
    if evidence_refs is not None:
        case.evidence_refs = evidence_refs
    if ai_recommendation is not None:
        case.ai_recommendation = ai_recommendation
    if human_decision is not None:
        case.human_decision = human_decision
    if escalation_reason is not None:
        case.escalation_reason = escalation_reason
    if outcome is not None:
        case.outcome = outcome
    if outcome_evidence is not None:
        case.outcome_evidence = outcome_evidence
    if status is not None:
        case.status = status
    db.commit()
    db.refresh(case)
    return case
