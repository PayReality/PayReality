import uuid
from datetime import datetime

from pydantic import BaseModel


class CreateBindingRequest(BaseModel):
    integration_identity_id: uuid.UUID
    integration_contract_version_id: uuid.UUID
    environment: str
    agent_ids: list[uuid.UUID] = []


class EditBindingRequest(BaseModel):
    integration_identity_id: uuid.UUID | None = None
    integration_contract_version_id: uuid.UUID | None = None
    environment: str | None = None


class AddAllowedAgentRequest(BaseModel):
    agent_id: uuid.UUID


class BindingResponse(BaseModel):
    id: str
    organization_id: str
    integration_identity_id: str
    integration_contract_version_id: str
    integration_id: str
    source_operation: str
    environment: str
    status: str
    created_by: str | None
    created_at: datetime
    activated_at: datetime | None
    retired_at: datetime | None


class AllowedAgentResponse(BaseModel):
    id: str
    name: str
    status: str
