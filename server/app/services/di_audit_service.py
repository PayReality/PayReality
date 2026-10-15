"""Decision Intelligence's append-only audit ledger (DIAuditEvent),
following agent_service._append_audit_event's own precedent: `db.add` +
`db.flush` only, never `db.commit` -- the caller's own mutation function
commits the audit row and the entity change together, in one transaction,
so an audit event can never exist without the mutation it describes (or
vice versa). No UPDATE/DELETE path for DIAuditEvent is ever exposed
through the API -- append-only, matching this module's own design brief."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DIAuditEvent


def record_event(
    db: Session,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    previous_value: dict | None = None,
    new_value: dict | None = None,
    reason: str | None = None,
) -> DIAuditEvent:
    event = DIAuditEvent(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        previous_value=previous_value,
        new_value=new_value,
        reason=reason,
    )
    db.add(event)
    db.flush()
    return event


def list_events_for_entity(
    db: Session, organization_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID
) -> list[DIAuditEvent]:
    return list(
        db.scalars(
            select(DIAuditEvent)
            .where(
                DIAuditEvent.organization_id == organization_id,
                DIAuditEvent.entity_type == entity_type,
                DIAuditEvent.entity_id == entity_id,
            )
            .order_by(DIAuditEvent.created_at.desc())
        )
    )
