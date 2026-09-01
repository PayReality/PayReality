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
    authorized -- any deviation is rejected, not merely logged.

    `environment`/`enforcement_binding_id`/`principal` (Trusted
    Integration Architecture, Phase 5, sections 6/9) are all optional: a
    PEP that knows which Runtime Connection, environment, or Agent it
    expects may pin any of them against the token's own signed claim; a
    PEP that omits all three skips those specific checks, exactly as
    every pre-Phase-5 Agent-direct verifier already does."""

    token: str
    audience: str
    action: str
    resource: str
    constraints: dict[str, Any]
    environment: str | None = None
    enforcement_binding_id: UUID | None = None
    principal: str | None = None


class VerifyCapabilityResponse(BaseModel):
    capability_id: UUID
    decision_id: str
    resource: str
    constraints: dict[str, Any]
