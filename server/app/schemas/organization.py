from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class OrganizationSettingsResponse(BaseModel):
    name: str
    logo_url: str | None
    timezone: str
    default_currency: str
    default_language: str
    settings: dict[str, Any]


class UpdateOrganizationSettingsRequest(BaseModel):
    """Every field optional: a PATCH from one Settings tab (e.g. General)
    should never require re-sending every other tab's fields."""

    name: str | None = None
    logo_url: str | None = None
    timezone: str | None = None
    default_currency: str | None = None
    default_language: str | None = None
    settings: dict[str, Any] | None = None


class IntegrationsStatusResponse(BaseModel):
    anthropic: str
    azure_ai_foundry: str
    azure_openai: str
    aws_bedrock: str
    opa: str
    postgresql: str


class HealthStatusResponse(BaseModel):
    runtime_authority: str
    evidence_engine: str
    opa: str
    compiler: str
    database: str
    anthropic: str


class ApiKeyResponse(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    role: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def from_model(cls, api_key):
        return cls(
            id=api_key.id,
            name=api_key.name,
            key_prefix=api_key.key_prefix,
            role=api_key.role,
            created_at=api_key.created_at,
            last_used_at=api_key.last_used_at,
            revoked_at=api_key.revoked_at,
        )


class CreateApiKeyRequest(BaseModel):
    name: str
    role: str


class CreateApiKeyResponse(BaseModel):
    api_key: ApiKeyResponse
    # Shown exactly once. Only key_hash is ever persisted (see
    # app.services.auth_service.generate_api_key) -- if this is lost, the
    # only recovery is revoking it and creating a new one.
    raw_key: str
