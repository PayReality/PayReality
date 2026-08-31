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
    # Trusted Integration Architecture, Phase 4: additive -- the allow-
    # list's own ids, inline on the Binding itself. Avoids an N+1 fan-out
    # (one GET .../allowed-agents per Binding) for every screen that
    # needs to answer "which Bindings include Agent X" (Agent Detail's
    # own Trusted Connections section) or "how many Agents does this
    # connection allow" (the Integrations list/detail screens) -- the
    # full Agent name/status list is still its own separate endpoint,
    # this is only the id set.
    allowed_agent_ids: list[str] = []


class AllowedAgentResponse(BaseModel):
    id: str
    name: str
    status: str
