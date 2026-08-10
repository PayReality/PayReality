"""Authority-as-a-continuous-object, Stage J: the minimal architectural
surface for EnterpriseSystem (the model itself has existed, unreachable
by HTTP, since Stage A). Registers that a downstream system exists and
what class it is -- never a connection, never a health check. `status`
is left at its column default ('configuration_required') by every path
here; nothing in this module ever sets it to 'connected', because no
connector code exists anywhere in this codebase to earn that state."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EnterpriseSystem


def create_enterprise_system(
    db: Session, organization_id: uuid.UUID, name: str, type: str
) -> EnterpriseSystem:
    system = EnterpriseSystem(organization_id=organization_id, name=name, type=type)
    db.add(system)
    db.commit()
    db.refresh(system)
    return system


def list_enterprise_systems(db: Session, organization_id: uuid.UUID) -> list[EnterpriseSystem]:
    return list(
        db.scalars(
            select(EnterpriseSystem)
            .where(EnterpriseSystem.organization_id == organization_id)
            .order_by(EnterpriseSystem.created_at.desc())
        )
    )
