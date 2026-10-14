"""Decision Intelligence: DIWorkflow CRUD. The top-level entity every
other DI service below scopes its own organization/workflow checks
against, following organization_structure_service.py's own lightweight-
CRUD style exactly."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DIWorkflow


class WorkflowNotFoundError(Exception):
    pass


def create_workflow(
    db: Session,
    organization_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    name: str,
    description: str | None = None,
    business_context: str | None = None,
    owner_user_id: uuid.UUID | None = None,
) -> DIWorkflow:
    workflow = DIWorkflow(
        organization_id=organization_id,
        created_by_user_id=created_by_user_id,
        name=name,
        description=description,
        business_context=business_context,
        owner_user_id=owner_user_id,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def get_workflow(db: Session, workflow_id: uuid.UUID, organization_id: uuid.UUID) -> DIWorkflow:
    workflow = db.get(DIWorkflow, workflow_id)
    if workflow is None or workflow.organization_id != organization_id:
        raise WorkflowNotFoundError(str(workflow_id))
    return workflow


def list_workflows(
    db: Session,
    organization_id: uuid.UUID,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[DIWorkflow], int]:
    stmt = select(DIWorkflow).where(DIWorkflow.organization_id == organization_id)
    if status:
        stmt = stmt.where(DIWorkflow.status == status)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(DIWorkflow.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt)), total


def update_workflow(
    db: Session,
    workflow_id: uuid.UUID,
    organization_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
    business_context: str | None = None,
    owner_user_id: uuid.UUID | None = None,
    status: str | None = None,
) -> DIWorkflow:
    """Only the fields actually passed (non-None) are changed -- callers
    (the router) should pass `body.model_dump(exclude_unset=True)`, the
    same partial-update convention agent_service.update_agent_metadata
    already uses, rather than this function guessing which fields were
    deliberately omitted versus deliberately cleared."""
    workflow = get_workflow(db, workflow_id, organization_id)
    if name is not None:
        workflow.name = name
    if description is not None:
        workflow.description = description
    if business_context is not None:
        workflow.business_context = business_context
    if owner_user_id is not None:
        workflow.owner_user_id = owner_user_id
    if status is not None:
        workflow.status = status
    db.commit()
    db.refresh(workflow)
    return workflow
