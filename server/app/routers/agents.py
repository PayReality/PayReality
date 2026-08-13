from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Agent, Certificate, Organization, Principal
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission, verify_agent_signature
from app.domain.rbac.permissions import Permission
from app.schemas.agent import (
    AgentDetailResponse,
    AgentListResponse,
    AgentResponse,
    AuditEventResponse,
    BulkActionItemResult,
    BulkActionResponse,
    BulkAgentActionRequest,
    CertificateResponse,
    CreateAgentRequest,
    DecisionSummary,
    EvidenceSummary,
    HeartbeatRequest,
    HeartbeatResponse,
    LifecycleActionRequest,
    LinkedPolicySummary,
    RotateCertificateRequest,
    TransferOwnerRequest,
    UpdateAgentRequest,
    VerifyAuditEventResponse,
)
from app.services import agent_service, intent_service, runtime_policy_service
from app.services.agent_service import (
    AgentNotFoundError,
    AuditEventNotFoundError,
    InvalidTransitionError,
    NoActiveCertificateError,
    PrincipalNotFoundError,
)

router = APIRouter(prefix="/v1/agents", tags=["agents"])


def _to_response(agent: Agent, certificate: Certificate | None = None) -> AgentResponse:
    return AgentResponse(
        id=agent.id,
        certificate_id=certificate.id if certificate else None,
        certificate_status=certificate.status if certificate else None,
        name=agent.name,
        acting_for_principal_id=agent.acting_for_principal_id,
        status=agent.status,
        owner=agent.owner,
        business_unit=agent.business_unit,
        environment=agent.environment,
        tags=agent.tags or [],
        description=agent.description,
        purpose=agent.purpose,
        model=agent.model,
        version=agent.version,
        runtime=agent.runtime,
        platform=agent.platform,
        labels=agent.labels or [],
        sdk_version=agent.sdk_version,
        last_seen_at=agent.last_seen_at,
        health=agent_service.compute_health(agent),
        rotation_requested_at=agent.rotation_requested_at,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _invalid_transition_response(e: InvalidTransitionError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=f"invalid_transition: cannot {e.action} agent from status '{e.from_status}'",
    )


def _authorized_agent(
    agent_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> Agent:
    """Milestone 3 (Enterprise Surface Isolation): the single gate every
    single-agent endpoint below depends on -- confirmed unauthenticated
    and unscoped before this in MULTI_TENANT_ARCHITECTURE_VERIFICATION.md
    (GET /v1/agents/{id} and, transitively, every sibling endpoint keyed
    by the same agent_id: certificates, audit events, activate/suspend/
    retire/revoke/rotate/transfer). Agent has no organization_id of its
    own -- reachable only via acting_for_principal_id -> Principal.
    organization_id -- so this resolves that chain once and 404s an
    agent belonging to a different organization identically to one that
    doesn't exist, the same convention _authorized_corpus already
    established for AI Authority Builder."""
    try:
        agent = agent_service.get_agent(db, agent_id)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail="agent_not_found")
    principal = db.get(Principal, agent.acting_for_principal_id)
    if principal is None or principal.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="agent_not_found")
    return agent


@router.post(
    "", response_model=AgentResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.AGENT_REGISTER))],
)
def create_agent(
    body: CreateAgentRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        agent, certificate = agent_service.create_agent(
            db,
            name=body.name,
            acting_for_principal_id=body.acting_for_principal_id,
            organization_id=organization.id,
            public_key=body.public_key,
            owner=body.owner,
            description=body.description,
        )
    except PrincipalNotFoundError:
        raise HTTPException(status_code=404, detail="principal_not_found")
    return _to_response(agent, certificate)


@router.get("", response_model=AgentListResponse)
def list_agents(
    status: str | None = None,
    environment: str | None = None,
    owner: str | None = None,
    principal_id: UUID | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Agent Directory (AGENT_DIRECTORY.md): search/filter via query
    params, paginated. `limit` is capped at 500 regardless of what's
    requested, the same defensive cap pattern used elsewhere in this
    codebase for any list endpoint that could otherwise return an
    unbounded result set."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    pairs, total = agent_service.list_agents(
        db, organization.id, status=status, environment=environment, owner=owner,
        principal_id=principal_id, q=q, limit=limit, offset=offset,
    )
    return AgentListResponse(
        agents=[_to_response(a, cert) for a, cert in pairs], total=total, limit=limit, offset=offset
    )


# --- Bulk operations. Declared before /{agent_id} routes: FastAPI/Starlette
# matches routes in registration order, and an untyped {agent_id} path
# segment structurally matches a literal "bulk" segment too, so bulk
# routes must come first or a request to /agents/bulk/suspend would be
# captured by /agents/{agent_id}/suspend (agent_id="bulk") and fail UUID
# validation instead of reaching the intended handler. ---


def _bulk_response(results: list[dict]) -> BulkActionResponse:
    items = [BulkActionItemResult(**r) for r in results]
    return BulkActionResponse(
        results=items, succeeded=sum(1 for r in items if r.ok), failed=sum(1 for r in items if not r.ok)
    )


@router.post(
    "/bulk/suspend", response_model=BulkActionResponse,
    dependencies=[Depends(require_permission(Permission.AGENT_SUSPEND))],
)
def bulk_suspend(
    body: BulkAgentActionRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    return _bulk_response(
        agent_service.bulk_transition(
            db, body.agent_ids, "suspend", organization.id, reason=body.reason, actor=body.actor
        )
    )


@router.post(
    "/bulk/activate", response_model=BulkActionResponse,
    dependencies=[Depends(require_permission(Permission.AGENT_ACTIVATE))],
)
def bulk_activate(
    body: BulkAgentActionRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    return _bulk_response(
        agent_service.bulk_transition(db, body.agent_ids, "activate", organization.id, actor=body.actor)
    )


@router.post(
    "/bulk/retire", response_model=BulkActionResponse,
    dependencies=[Depends(require_permission(Permission.AGENT_RETIRE))],
)
def bulk_retire(
    body: BulkAgentActionRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    return _bulk_response(
        agent_service.bulk_transition(
            db, body.agent_ids, "retire", organization.id, reason=body.reason, actor=body.actor
        )
    )


@router.post(
    "/bulk/rotate", response_model=BulkActionResponse,
    dependencies=[Depends(require_permission(Permission.AGENT_ROTATE))],
)
def bulk_rotate(
    body: BulkAgentActionRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Honest bulk rotation (CERTIFICATE_ROTATION.md): PayReality never
    holds an agent's private key, so an operator-triggered bulk action
    cannot generate new key pairs on 10,000 agents' behalf. This flags
    each selected agent for rotation; the actual cryptographic rotation
    still happens per-agent via POST /agents/{id}/rotate, called with a
    freshly generated public key from that agent's own side (SDK
    agent.rotate_keys())."""
    return _bulk_response(
        agent_service.bulk_transition(db, body.agent_ids, "request_rotation", organization.id, actor=body.actor)
    )


@router.get("/{agent_id}", response_model=AgentDetailResponse)
def get_agent_detail(agent_id: UUID, agent: Agent = Depends(_authorized_agent), db: Session = Depends(get_db)):
    certificate = agent_service.get_active_certificate_for_agent(db, agent_id)
    certificates = agent_service.list_certificates(db, agent_id)
    return _build_agent_detail(db, agent, certificate, certificates)


def _build_agent_detail(db: Session, agent: Agent, certificate, certificates) -> AgentDetailResponse:
    principal = db.get(Principal, agent.acting_for_principal_id)
    principal_name = principal.name if principal else "unknown"

    policy_rows = runtime_policy_service.list_policies_for_principal(
        db, principal.organization_id if principal else None, principal_name
    )
    policies = [
        LinkedPolicySummary(
            policy_key=row.policy_key, name=row.content.get("name", ""), version=row.version, status=row.status
        )
        for row in policy_rows
    ]

    decisions = intent_service.list_decisions_for_agent(db, agent.id)
    evidence = intent_service.list_evidence_for_agent(db, agent.id)
    audit_events = agent_service.list_audit_events(db, agent.id)

    return AgentDetailResponse(
        agent=_to_response(agent, certificate),
        principal_name=principal_name,
        policies=policies,
        certificates=[CertificateResponse.model_validate(c) for c in certificates],
        recent_decisions=[
            DecisionSummary(id=d.id, outcome=d.outcome, reason=d.reason, created_at=d.created_at)
            for d in decisions
        ],
        recent_evidence=[
            EvidenceSummary(id=e.id, status=e.status, created_at=e.created_at) for e in evidence
        ],
        recent_audit_events=[AuditEventResponse.model_validate(a) for a in audit_events],
    )


@router.patch(
    "/{agent_id}", response_model=AgentResponse,
    dependencies=[Depends(require_permission(Permission.AGENT_MANAGE))],
)
def update_agent(
    agent_id: UUID,
    body: UpdateAgentRequest,
    _: Agent = Depends(_authorized_agent),
    db: Session = Depends(get_db),
):
    try:
        agent = agent_service.update_agent_metadata(db, agent_id, **body.model_dump(exclude_unset=True))
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail="agent_not_found")
    certificate = agent_service.get_active_certificate_for_agent(db, agent_id)
    return _to_response(agent, certificate)


@router.delete(
    "/{agent_id}", response_model=AgentResponse,
    dependencies=[Depends(require_permission(Permission.AGENT_RETIRE))],
)
def delete_agent(agent_id: UUID, _: Agent = Depends(_authorized_agent), db: Session = Depends(get_db)):
    """Not a real delete: AGENT_LIFECYCLE.md's own design philosophy is
    "Nothing is deleted. Everything is auditable," which a hard DELETE
    directly contradicts. This alias retires the agent instead (same
    effect a human-identity system's "deactivate account" action has)
    rather than silently no-op'ing the verb or omitting it, since DELETE
    is explicitly named in the spec's own API list."""
    try:
        agent = agent_service.retire_agent(db, agent_id, reason="deleted via DELETE /agents/{id}")
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail="agent_not_found")
    except InvalidTransitionError as e:
        raise _invalid_transition_response(e)
    certificate = agent_service.get_active_certificate_for_agent(db, agent_id)
    return _to_response(agent, certificate)


@router.get("/{agent_id}/certificates", response_model=list[CertificateResponse])
def list_certificates(agent_id: UUID, _: Agent = Depends(_authorized_agent), db: Session = Depends(get_db)):
    return [CertificateResponse.model_validate(c) for c in agent_service.list_certificates(db, agent_id)]


@router.get("/{agent_id}/audit", response_model=list[AuditEventResponse])
def list_audit_events(
    agent_id: UUID, limit: int = 50, _: Agent = Depends(_authorized_agent), db: Session = Depends(get_db)
):
    return [
        AuditEventResponse.model_validate(a)
        for a in agent_service.list_audit_events(db, agent_id, limit=min(max(limit, 1), 200))
    ]


@router.post("/{agent_id}/audit/{event_id}/verify", response_model=VerifyAuditEventResponse)
def verify_audit_event(
    agent_id: UUID, event_id: UUID, _: Agent = Depends(_authorized_agent), db: Session = Depends(get_db)
):
    try:
        event = agent_service.get_audit_event(db, event_id)
    except AuditEventNotFoundError:
        raise HTTPException(status_code=404, detail="audit_event_not_found")
    if event.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="audit_event_not_found")

    valid, key_id = agent_service.verify_audit_event(db, event_id)
    return VerifyAuditEventResponse(
        event_id=event_id, valid=valid, key_id=key_id, verified_at=datetime.now(timezone.utc)
    )


@router.post(
    "/{agent_id}/activate", response_model=AgentResponse,
    dependencies=[Depends(require_permission(Permission.AGENT_ACTIVATE))],
)
def activate_agent(
    agent_id: UUID,
    body: LifecycleActionRequest = LifecycleActionRequest(),
    _: Agent = Depends(_authorized_agent),
    db: Session = Depends(get_db),
):
    try:
        agent = agent_service.activate_agent(db, agent_id, actor=body.actor)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail="agent_not_found")
    except InvalidTransitionError as e:
        raise _invalid_transition_response(e)
    certificate = agent_service.get_active_certificate_for_agent(db, agent_id)
    return _to_response(agent, certificate)


@router.post(
    "/{agent_id}/suspend", response_model=AgentResponse,
    dependencies=[Depends(require_permission(Permission.AGENT_SUSPEND))],
)
def suspend_agent(
    agent_id: UUID,
    body: LifecycleActionRequest = LifecycleActionRequest(),
    _: Agent = Depends(_authorized_agent),
    db: Session = Depends(get_db),
):
    try:
        agent = agent_service.suspend_agent(db, agent_id, reason=body.reason, actor=body.actor)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail="agent_not_found")
    except InvalidTransitionError as e:
        raise _invalid_transition_response(e)
    certificate = agent_service.get_active_certificate_for_agent(db, agent_id)
    return _to_response(agent, certificate)


@router.post(
    "/{agent_id}/retire", response_model=AgentResponse,
    dependencies=[Depends(require_permission(Permission.AGENT_RETIRE))],
)
def retire_agent(
    agent_id: UUID,
    body: LifecycleActionRequest = LifecycleActionRequest(),
    _: Agent = Depends(_authorized_agent),
    db: Session = Depends(get_db),
):
    try:
        agent = agent_service.retire_agent(db, agent_id, reason=body.reason, actor=body.actor)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail="agent_not_found")
    except InvalidTransitionError as e:
        raise _invalid_transition_response(e)
    certificate = agent_service.get_active_certificate_for_agent(db, agent_id)
    return _to_response(agent, certificate)


@router.post(
    "/{agent_id}/revoke", response_model=AgentResponse,
    dependencies=[Depends(require_permission(Permission.AGENT_REVOKE))],
)
def revoke_agent(
    agent_id: UUID,
    body: LifecycleActionRequest = LifecycleActionRequest(),
    _: Agent = Depends(_authorized_agent),
    db: Session = Depends(get_db),
):
    """Not in the spec's literal API list (only suspend/activate/retire/
    rotate/heartbeat/transfer are named there), added because "Revoked"
    is a required terminal state in the same spec's own state-machine
    section and would otherwise be unreachable through any endpoint."""
    try:
        agent = agent_service.revoke_agent(db, agent_id, reason=body.reason, actor=body.actor)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail="agent_not_found")
    except InvalidTransitionError as e:
        raise _invalid_transition_response(e)
    certificate = agent_service.get_active_certificate_for_agent(db, agent_id)
    return _to_response(agent, certificate)


@router.post(
    "/{agent_id}/rotate", response_model=CertificateResponse,
    dependencies=[Depends(require_permission(Permission.AGENT_ROTATE))],
)
def rotate_certificate(
    agent_id: UUID,
    body: RotateCertificateRequest,
    _: Agent = Depends(_authorized_agent),
    db: Session = Depends(get_db),
):
    try:
        certificate = agent_service.rotate_certificate(db, agent_id, body.new_public_key, actor=body.actor)
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail="agent_not_found")
    except InvalidTransitionError as e:
        raise _invalid_transition_response(e)
    except NoActiveCertificateError:
        raise HTTPException(status_code=409, detail="no_active_certificate_to_rotate")
    return CertificateResponse.model_validate(certificate)


@router.post(
    "/{agent_id}/transfer", response_model=AgentResponse,
    dependencies=[Depends(require_permission(Permission.AGENT_MANAGE))],
)
def transfer_owner(
    agent_id: UUID,
    body: TransferOwnerRequest,
    _: Agent = Depends(_authorized_agent),
    db: Session = Depends(get_db),
):
    try:
        agent = agent_service.transfer_owner(
            db, agent_id, body.new_owner, new_business_unit=body.new_business_unit, actor=body.actor
        )
    except AgentNotFoundError:
        raise HTTPException(status_code=404, detail="agent_not_found")
    certificate = agent_service.get_active_certificate_for_agent(db, agent_id)
    return _to_response(agent, certificate)


@router.post("/{agent_id}/heartbeat", response_model=HeartbeatResponse)
def heartbeat(
    agent_id: UUID,
    body: HeartbeatRequest,
    signed_agent: Agent = Depends(verify_agent_signature),
    db: Session = Depends(get_db),
):
    """Not operator-gated: a heartbeat is the agent asserting its own
    liveness, authenticated the same way an Intent is (its own active
    Certificate's signature over the raw body), not by the shared admin
    key. See SDK_AGENT_GUIDE.md's agent.heartbeat()."""
    if str(agent_id) != str(signed_agent.id):
        raise HTTPException(status_code=401, detail="agent_id_does_not_match_signing_key")

    agent = agent_service.record_heartbeat(
        db, agent_id, version=body.version, sdk_version=body.sdk_version, runtime=body.runtime
    )
    return HeartbeatResponse(
        agent_id=agent.id, last_seen_at=agent.last_seen_at, health=agent_service.compute_health(agent)
    )
