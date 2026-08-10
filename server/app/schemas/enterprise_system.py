from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

EnterpriseSystemType = Literal[
    "erp", "crm", "finance", "hr", "procurement", "legal", "manufacturing", "other"
]


class CreateEnterpriseSystemRequest(BaseModel):
    """Registers the existence of a downstream system Runtime Authority
    is meant to eventually gate -- never a connection. `type` mirrors the
    `enterprise_systems` table's own check constraint
    (ck_enterprise_systems_type) so an invalid value is rejected by
    Pydantic before it ever reaches the database."""

    name: str
    type: EnterpriseSystemType


class EnterpriseSystemResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    type: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
