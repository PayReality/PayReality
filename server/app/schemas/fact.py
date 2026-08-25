from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class RegisterFactSourceRequest(BaseModel):
    name: str
    public_key_b64: str


class FactSourceResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    status: str
    created_at: datetime
    revoked_at: datetime | None

    model_config = {"from_attributes": True}


class IngestFactRequest(BaseModel):
    """The router-facing shape; every field here except `signature` is
    exactly PAYREALITY_FUTURE_VISION.md Part A's canonical, signed
    attestation payload (fact_service.CanonicalFactAttestation) -- the
    router does not add or drop a field between what's signed and what's
    verified."""

    organization_id: UUID
    source_id: UUID
    subject: str | None = None
    key: str
    value: Any
    observed_at: datetime
    expires_at: datetime
    nonce: str
    signature: str


class FactResponse(BaseModel):
    id: UUID
    organization_id: UUID
    source_id: UUID
    subject: str | None
    key: str
    value: Any
    observed_at: datetime
    recorded_at: datetime
    expires_at: datetime
    attestation_type: str

    model_config = {"from_attributes": True}
