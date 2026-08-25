from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class IssueCapabilityRequest(BaseModel):
    audience: str
    issued_by: str | None = None
    ttl_seconds: int | None = None


class IssueCapabilityResponse(BaseModel):
    token: str
    capability_id: UUID
    expires_at: datetime


class VerifyCapabilityRequest(BaseModel):
    """The reference enforcement adapter's own request shape: what it
    proposes to execute, checked against exactly what the token
    authorized -- any deviation is rejected, not merely logged."""

    token: str
    audience: str
    action: str
    resource: str
    constraints: dict[str, Any]


class VerifyCapabilityResponse(BaseModel):
    capability_id: UUID
    decision_id: str
    resource: str
    constraints: dict[str, Any]
