"""Decision Intelligence: DIPattern CRUD and its DICase linkage."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import DIPattern, DIPatternCase
from app.services import di_case_service, di_workflow_service


class PatternNotFoundError(Exception):
    pass


def create_pattern(
    db: Session,
    organization_id: uuid.UUID,
    workflow_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    name: str,
    description: str,
    category: str,
    proposed_explanation: str,
    alternative_explanations: list | None = None,
    confidence: str | None = None,
) -> DIPattern:
    di_workflow_service.get_workflow(db, workflow_id, organization_id)

    pattern = DIPattern(
        organization_id=organization_id,
        workflow_id=workflow_id,
        created_by_user_id=created_by_user_id,
        name=name,
        description=description,
        category=category,
        proposed_explanation=proposed_explanation,
        alternative_explanations=alternative_explanations,
        confidence=confidence,
    )
    db.add(pattern)
    db.commit()
    db.refresh(pattern)
    return pattern


def get_pattern(db: Session, pattern_id: uuid.UUID, organization_id: uuid.UUID) -> DIPattern:
    pattern = db.get(DIPattern, pattern_id)
    if pattern is None or pattern.organization_id != organization_id:
        raise PatternNotFoundError(str(pattern_id))
    return pattern


def list_patterns(
    db: Session,
    organization_id: uuid.UUID,
    workflow_id: uuid.UUID | None = None,
    review_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[DIPattern], int]:
    stmt = select(DIPattern).where(DIPattern.organization_id == organization_id)
    if workflow_id is not None:
        stmt = stmt.where(DIPattern.workflow_id == workflow_id)
    if review_status:
        stmt = stmt.where(DIPattern.review_status == review_status)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(DIPattern.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt)), total


def update_pattern(
    db: Session,
    pattern_id: uuid.UUID,
    organization_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
    category: str | None = None,
    proposed_explanation: str | None = None,
    alternative_explanations: list | None = None,
    confidence: str | None = None,
    review_status: str | None = None,
) -> DIPattern:
    pattern = get_pattern(db, pattern_id, organization_id)
    if name is not None:
        pattern.name = name
    if description is not None:
        pattern.description = description
    if category is not None:
        pattern.category = category
    if proposed_explanation is not None:
        pattern.proposed_explanation = proposed_explanation
    if alternative_explanations is not None:
        pattern.alternative_explanations = alternative_explanations
    if confidence is not None:
        pattern.confidence = confidence
    if review_status is not None:
        pattern.review_status = review_status
    db.commit()
    db.refresh(pattern)
    return pattern


def link_case(db: Session, pattern_id: uuid.UUID, case_id: uuid.UUID, organization_id: uuid.UUID) -> DIPatternCase:
    pattern = get_pattern(db, pattern_id, organization_id)
    di_case_service.get_case(db, case_id, organization_id)
    link = DIPatternCase(pattern_id=pattern.id, case_id=case_id)
    db.add(link)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Already linked -- idempotent no-op rather than a 500, since
        # "link this case to this pattern" is naturally idempotent from
        # a caller's point of view.
        existing = db.scalar(
            select(DIPatternCase).where(
                DIPatternCase.pattern_id == pattern.id, DIPatternCase.case_id == case_id
            )
        )
        return existing
    db.refresh(link)
    return link


def unlink_case(db: Session, pattern_id: uuid.UUID, case_id: uuid.UUID, organization_id: uuid.UUID) -> None:
    get_pattern(db, pattern_id, organization_id)
    link = db.scalar(
        select(DIPatternCase).where(DIPatternCase.pattern_id == pattern_id, DIPatternCase.case_id == case_id)
    )
    if link is not None:
        db.delete(link)
        db.commit()


def list_linked_cases(db: Session, pattern_id: uuid.UUID, organization_id: uuid.UUID) -> list[uuid.UUID]:
    get_pattern(db, pattern_id, organization_id)
    return list(db.scalars(select(DIPatternCase.case_id).where(DIPatternCase.pattern_id == pattern_id)))
