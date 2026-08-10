from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CreatePrincipalRequest(BaseModel):
    """Not in the spec's literal API surface (Section 19); Principals are
    normally created implicitly during document onboarding (spec 8.2's
    lifecycle: "Created when a DoA document is onboarded"). This endpoint is
    a Phase 1 convenience so an Agent/Mandate can be bootstrapped and tested
    before any document has been uploaded and reviewed.

    Authority-as-a-continuous-object, Stage B: role and the organisational
    hierarchy are additive and optional. Every existing caller sending only
    `name` keeps working exactly as before; these fields exist so a
    Principal can actually carry the organisational identity the rest of
    the platform's copy already claims it does."""

    name: str
    role: str | None = None
    organization_id: UUID | None = None
    business_unit_id: UUID | None = None
    department_id: UUID | None = None
    team_id: UUID | None = None


class PrincipalResponse(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    role: str | None = None
    organization_id: UUID | None = None
    business_unit_id: UUID | None = None
    department_id: UUID | None = None
    team_id: UUID | None = None

    model_config = {"from_attributes": True}


class DelegationEdgeResponse(BaseModel):
    """One active, direct inbound delegation
    (authority_context_service._active_inbound_delegations)."""

    id: str
    from_principal_id: str | None
    resource_id: str | None
    operation: str | None


class PrincipalAuthorityContextResponse(BaseModel):
    """Authority-as-a-continuous-object, Stage I.9: the same Runtime
    Authority Context dict resolve_runtime_authority_context already
    assembles for every Intent, exposed standalone (identity-only, no
    `amount`) so Agent Detail can show a Principal's real organisational
    placement and active delegations instead of a bare name."""

    organization: str | None
    business_unit: str | None
    department: str | None
    team: str | None
    role: str | None
    delegations: list[DelegationEdgeResponse]


class CreateAgentRequest(BaseModel):
    """spec 19.4."""

    name: str
    acting_for_principal_id: UUID
    public_key: str
    owner: str | None = None
    description: str | None = None


class AgentResponse(BaseModel):
    """Phase 9 (AGENT_LIFECYCLE.md): extended with the full set of
    ownership/metadata fields and a computed `health`. `status` now
    includes 'registered' and 'retired' alongside the original three."""

    id: UUID
    certificate_id: UUID | None = None
    certificate_status: str | None = None
    name: str
    acting_for_principal_id: UUID
    status: str
    owner: str | None = None
    business_unit: str | None = None
    environment: str | None = None
    tags: list[str] = []
    description: str | None = None
    purpose: str | None = None
    model: str | None = None
    version: str | None = None
    runtime: str | None = None
    platform: str | None = None
    labels: list[str] = []
    sdk_version: str | None = None
    last_seen_at: datetime | None = None
    health: str
    rotation_requested_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class AgentListResponse(BaseModel):
    """Pagination envelope (AGENT_DIRECTORY.md): "manage 10,000+ agents"
    only holds up if the list endpoint isn't returning all of them at
    once."""

    agents: list[AgentResponse]
    total: int
    limit: int
    offset: int


class CertificateResponse(BaseModel):
    id: UUID
    agent_id: UUID
    status: str
    public_key: str
    issued_at: datetime
    activated_at: datetime | None = None
    rotated_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    model_config = {"from_attributes": True}


class LinkedPolicySummary(BaseModel):
    policy_key: UUID
    name: str
    version: int
    status: str


class DecisionSummary(BaseModel):
    id: UUID
    outcome: str
    reason: str | None = None
    created_at: datetime


class EvidenceSummary(BaseModel):
    id: UUID
    status: str
    created_at: datetime


class AuditEventResponse(BaseModel):
    id: UUID
    agent_id: UUID
    event_type: str
    actor: str | None = None
    payload: dict
    key_id: str
    signature: str
    created_at: datetime

    model_config = {"from_attributes": True}


class VerifyAuditEventResponse(BaseModel):
    event_id: UUID
    valid: bool
    key_id: str
    verified_at: datetime


class AgentDetailResponse(BaseModel):
    """Agent Detail Page (AGENT_DIRECTORY.md): identity + principal +
    linked Runtime Policies + certificate history + recent decisions +
    recent evidence + recent audit events, all in one call so the page
    doesn't have to make eight separate round trips before it can render."""

    agent: AgentResponse
    principal_name: str
    policies: list[LinkedPolicySummary]
    certificates: list[CertificateResponse]
    recent_decisions: list[DecisionSummary]
    recent_evidence: list[EvidenceSummary]
    recent_audit_events: list[AuditEventResponse]


class UpdateAgentRequest(BaseModel):
    """PATCH /agents/{id}: routine metadata, never status or ownership
    (those go through the dedicated lifecycle endpoints so every status
    change and every ownership change is validated and audited)."""

    description: str | None = None
    purpose: str | None = None
    model: str | None = None
    version: str | None = None
    runtime: str | None = None
    platform: str | None = None
    environment: str | None = None
    tags: list[str] | None = None
    labels: list[str] | None = None


class LifecycleActionRequest(BaseModel):
    reason: str | None = None
    actor: str | None = None


class RotateCertificateRequest(BaseModel):
    new_public_key: str
    actor: str | None = None


class HeartbeatRequest(BaseModel):
    version: str | None = None
    sdk_version: str | None = None
    runtime: str | None = None


class HeartbeatResponse(BaseModel):
    agent_id: UUID
    last_seen_at: datetime
    health: str


class TransferOwnerRequest(BaseModel):
    new_owner: str
    new_business_unit: str | None = None
    actor: str | None = None


class BulkAgentActionRequest(BaseModel):
    agent_ids: list[UUID]
    reason: str | None = None
    actor: str | None = None


class BulkActionItemResult(BaseModel):
    agent_id: str
    ok: bool
    error: str | None = None


class BulkActionResponse(BaseModel):
    results: list[BulkActionItemResult]
    succeeded: int
    failed: int
