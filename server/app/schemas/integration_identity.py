from datetime import datetime

from pydantic import BaseModel


class RegisterIntegrationIdentityRequest(BaseModel):
    name: str
    public_key: str


class RotateCertificateRequest(BaseModel):
    new_public_key: str


class IntegrationIdentityResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    status: str
    created_by: str | None
    created_at: datetime


class IntegrationIdentityCertificateResponse(BaseModel):
    id: str
    integration_identity_id: str
    status: str
    issued_at: datetime
    activated_at: datetime | None
    rotated_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
