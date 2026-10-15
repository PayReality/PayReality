"""Decision Intelligence: DIPattern CRUD and its DICase linkage."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import DIPattern, DIPatternCase
from app.services import di_audit_service, di_case_service, di_workflow_service

#: DIPatternCase.kind's fixed vocabulary -- see that column's own
#: docstring (app/db/models.py) for what each value means.
CASE_LINK_KINDS = ("supporting", "potentially_affected", "excluded", "undetermined")


class PatternNotFoundError(Exception):
    pass


class CaseLinkNotFoundError(Exception):
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


def link_case(
    db: Session,
    pattern_id: uuid.UUID,
    case_id: uuid.UUID,
    organization_id: uuid.UUID,
    kind: str = "supporting",
    reason: str | None = None,
) -> DIPatternCase:
    """`kind` defaults to "supporting" (a manually-linked case is assumed
    to be real evidence unless the caller says otherwise) -- see
    CASE_LINK_KINDS. Re-linking an already-linked case is idempotent and
    does NOT silently change its existing kind/reason; use
    `relink_case_kind` to correct one on purpose."""
    if kind not in CASE_LINK_KINDS:
        raise ValueError(f"kind must be one of {CASE_LINK_KINDS}, got {kind!r}")
    pattern = get_pattern(db, pattern_id, organization_id)
    di_case_service.get_case(db, case_id, organization_id)
    link = DIPatternCase(pattern_id=pattern.id, case_id=case_id, kind=kind, reason=reason)
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


def relink_case_kind(
    db: Session,
    pattern_id: uuid.UUID,
    case_id: uuid.UUID,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    new_kind: str,
    reason: str | None = None,
) -> DIPatternCase:
    """A reviewer correcting a suggestion-originated (or anyone else's)
    relevance call -- e.g. demoting a model-inferred "potentially_
    affected" case to "excluded" after actually checking it. The original
    link row is updated in place (never deleted/recreated, so its own
    `created_at` is preserved), and the correction is recorded as a
    DIAuditEvent -- that audit trail, not a separate history table, is
    this feature's "preserve review history" mechanism."""
    if new_kind not in CASE_LINK_KINDS:
        raise ValueError(f"new_kind must be one of {CASE_LINK_KINDS}, got {new_kind!r}")
    get_pattern(db, pattern_id, organization_id)
    link = db.scalar(
        select(DIPatternCase).where(DIPatternCase.pattern_id == pattern_id, DIPatternCase.case_id == case_id)
    )
    if link is None:
        raise CaseLinkNotFoundError(f"case {case_id} is not linked to pattern {pattern_id}")
    previous_kind = link.kind
    link.kind = new_kind
    link.reason = reason
    db.add(link)
    di_audit_service.record_event(
        db, organization_id, actor_user_id, action="relink_case", entity_type="DIPatternCase", entity_id=link.id,
        previous_value={"kind": previous_kind}, new_value={"kind": new_kind, "reason": reason}, reason=reason,
    )
    db.commit()
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


def list_linked_case_links(db: Session, pattern_id: uuid.UUID, organization_id: uuid.UUID) -> list[DIPatternCase]:
    """Like `list_linked_cases`, but returns the full link rows (kind,
    reason) rather than bare case ids -- what a reviewer needs to see WHY
    each case is linked, not just that it is."""
    get_pattern(db, pattern_id, organization_id)
    return list(db.scalars(select(DIPatternCase).where(DIPatternCase.pattern_id == pattern_id)))
