import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Policy


def list_policies(db: Session, organization_id: uuid.UUID) -> list[Policy]:
    """Milestone 12 (MILESTONE_12_POLICY_API_SECURITY_SUMMARY.md):
    `organization_id` is new and required -- this previously queried
    every organization's Policy rows unscoped, a CRITICAL finding from
    Milestone 11's sweep (confirmed live-exploitable in production).
    `Policy.organization_id` is nullable (legacy, pre-Milestone-2 rows);
    filtering by a real caller's organization_id naturally excludes
    those, the same discipline every other Policy-reading code path in
    this codebase already applies."""
    return list(
        db.scalars(
            select(Policy)
            .where(Policy.organization_id == organization_id)
            .order_by(Policy.version.desc())
        )
    )
