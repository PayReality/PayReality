import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Agent, AgentAuditEvent, Certificate, Principal
from app.domain.evidence.signing import sign_payload, verify_payload, Signature
from app.services import sandbox_limits, signing_key_service
from app.services.organization_structure_service import (
    BusinessUnitNotFoundError,
    DepartmentNotFoundError,
    TeamNotFoundError,
    business_unit_organization_id,
    department_organization_id,
    team_organization_id,
)

logger = logging.getLogger("payreality.agent_lifecycle")

# Phase 9 (AGENT_LIFECYCLE.md): the full state machine. `registered` is the
# entry state (exists, not operational); `active` can sign Intents;
# `suspended` is a temporary lock reachable only from `active`; `revoked`
# and `retired` are terminal. Kept as a plain dict of allowed destinations
# per source state rather than a library-backed state machine: five states
# and a handful of transitions doesn't earn the dependency.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "registered": {"active", "revoked", "retired"},
    "active": {"suspended", "revoked", "retired"},
    "suspended": {"active", "revoked", "retired"},
    "revoked": set(),
    "retired": set(),
}

# Certificate.status values a rotate/revoke/retire action can act on; once a
# certificate is 'rotated', 'expired', or already 'revoked' it is done.
_CERT_LIVE_STATUSES = ("issued", "active")


class PrincipalNotFoundError(Exception):
    pass


class AgentNotFoundError(Exception):
    pass


class InvalidTransitionError(Exception):
    """Raised when a lifecycle action doesn't match _ALLOWED_TRANSITIONS,
    e.g. suspending an already-retired agent. Carries enough detail for the
    router to return a clear 409."""

    def __init__(self, agent_id: uuid.UUID, from_status: str, action: str):
        self.agent_id = agent_id
        self.from_status = from_status
        self.action = action
        super().__init__(f"cannot {action} agent {agent_id} from status '{from_status}'")


class NoActiveCertificateError(Exception):
    """Raised by rotate_certificate when the agent has no active
    certificate to rotate (e.g. it's still only 'registered')."""


class AuditEventNotFoundError(Exception):
    pass


def create_principal(
    db: Session,
    name: str,
    organization_id: uuid.UUID,
    role: str | None = None,
    business_unit_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
) -> Principal:
    # Authority-as-a-continuous-object, Stage B: every new parameter is
    # optional and defaults to None, exactly matching the column
    # defaults Phase 1's schema already established. A caller passing
    # only `name`, as every existing caller does, gets identical
    # behaviour to before this change.
    #
    # Milestone 1 (Security & Authorization Hardening): organization_id
    # is now required and must be the caller's OWN organization (the
    # router resolves it via get_current_organization, never trusts a
    # client-supplied value) -- previously a caller could name any
    # organization_id in the request body and create a Principal under
    # it. business_unit_id/department_id/team_id, if given, must each
    # resolve to that same organization; a mismatch is treated as "not
    # found" for whichever one didn't resolve, the same
    # not-found-not-403 pattern used everywhere else in this milestone.
    if business_unit_id is not None and business_unit_organization_id(db, business_unit_id) != organization_id:
        raise BusinessUnitNotFoundError(str(business_unit_id))
    if department_id is not None and department_organization_id(db, department_id) != organization_id:
        raise DepartmentNotFoundError(str(department_id))
    if team_id is not None and team_organization_id(db, team_id) != organization_id:
        raise TeamNotFoundError(str(team_id))

    principal = Principal(
        name=name,
        role=role,
        organization_id=organization_id,
        business_unit_id=business_unit_id,
        department_id=department_id,
        team_id=team_id,
    )
    db.add(principal)
    db.commit()
    db.refresh(principal)
    return principal


def list_principals(db: Session, organization_id: uuid.UUID) -> list[Principal]:
    return list(db.scalars(select(Principal).where(Principal.organization_id == organization_id)))


def _append_audit_event(
    db: Session, agent_id: uuid.UUID, event_type: str, actor: str | None, details: dict
) -> AgentAuditEvent:
    """Phase 9: every lifecycle transition becomes one signed, immutable
    row, using the exact same canonicalize + ED25519-sign primitives as
    Decision Evidence (domain/evidence/signing.py), so an audit event is
    just as independently verifiable as any other Evidence record, even
    though it lives in its own table (see AgentAuditEvent's docstring)."""
    payload = {
        "event_type": event_type,
        "agent_id": str(agent_id),
        "actor": actor or "operator",
        "details": details,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    signature = sign_payload(
        payload, settings.evidence_signing_key_b64, settings.evidence_signing_key_id
    )
    event = AgentAuditEvent(
        agent_id=agent_id,
        event_type=event_type,
        actor=actor or "operator",
        payload=payload,
        key_id=signature.key_id,
        signature=signature.value,
    )
    db.add(event)
    db.flush()
    return event


def create_agent(
    db: Session,
    name: str,
    acting_for_principal_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    public_key: str,
    owner: str | None = None,
    description: str | None = None,
) -> tuple[Agent, Certificate]:
    """Phase 9 (AGENT_LIFECYCLE.md, "Registered" state): registering an
    Agent now provisions its first Certificate as 'issued', not 'active',
    and the Agent itself starts 'registered', not 'active'. A separate
    activate_agent() call is required before the agent can sign Intents
    (verify_agent_signature only accepts an 'active' certificate). This is
    a deliberate behavior change from Phase 1: existing agents already in
    the database (created 'active' with an 'active' certificate) are
    completely unaffected, since this only changes what happens for agents
    created from now on.

    Milestone 3 (Enterprise Surface Isolation): `organization_id` is the
    caller's own, resolved via get_current_organization -- a client could
    otherwise register an Agent acting for a Principal belonging to a
    DIFFERENT organization, confirmed as unchecked before this. A
    Principal that exists but belongs to another organization is treated
    identically to one that doesn't exist at all, the same "cross-
    organization access looks like not-found" convention this codebase
    already established for every other cross-organization reference."""
    principal = db.get(Principal, acting_for_principal_id)
    if principal is None or principal.organization_id != organization_id:
        raise PrincipalNotFoundError(str(acting_for_principal_id))

    if sandbox_limits.is_sandbox_organization(db, organization_id):
        existing = db.scalar(
            select(func.count())
            .select_from(Agent)
            .join(Principal, Agent.acting_for_principal_id == Principal.id)
            .where(Principal.organization_id == organization_id)
        )
        if existing >= sandbox_limits.MAX_AGENTS_PER_SANDBOX:
            raise sandbox_limits.SandboxLimitExceededError("agents", sandbox_limits.MAX_AGENTS_PER_SANDBOX)

    agent = Agent(
        name=name,
        acting_for_principal_id=acting_for_principal_id,
        owner=owner,
        description=description,
        status="registered",
    )
    db.add(agent)
    db.flush()  # assign agent.id without committing yet

    certificate = Certificate(agent_id=agent.id, public_key=public_key, status="issued")
    db.add(certificate)
    db.flush()

    _append_audit_event(
        db, agent.id, "agent_created", actor=None,
        details={"name": name, "principal_id": str(acting_for_principal_id), "owner": owner},
    )
    db.commit()
    db.refresh(agent)
    db.refresh(certificate)
    return agent, certificate


def get_agent(db: Session, agent_id: uuid.UUID) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise AgentNotFoundError(str(agent_id))
    return agent


def get_active_certificate_for_agent(db: Session, agent_id: uuid.UUID) -> Certificate | None:
    return db.scalar(
        select(Certificate).where(Certificate.agent_id == agent_id, Certificate.status == "active")
    )


def list_certificates(db: Session, agent_id: uuid.UUID) -> list[Certificate]:
    return list(
        db.scalars(
            select(Certificate).where(Certificate.agent_id == agent_id).order_by(Certificate.issued_at)
        )
    )


def list_agents_with_active_certificate(db: Session) -> list[tuple[Agent, Certificate | None]]:
    """Unchanged Phase 1 helper (kept for any existing caller); prefer
    list_agents() below for anything that needs filtering/pagination."""
    agents = list(db.scalars(select(Agent)))
    certs_by_agent = {
        c.agent_id: c
        for c in db.scalars(select(Certificate).where(Certificate.status == "active"))
    }
    return [(a, certs_by_agent.get(a.id)) for a in agents]


def list_agents(
    db: Session,
    organization_id: uuid.UUID | None,
    status: str | None = None,
    environment: str | None = None,
    owner: str | None = None,
    principal_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[tuple[Agent, Certificate | None]], int]:
    """Agent Directory query (AGENT_DIRECTORY.md): search/filter/sort plus
    pagination, since "manage 10,000+ agents" only holds up if the list
    endpoint doesn't return all of them at once. Sort is always by
    created_at desc (newest first) -- no column-level sort param yet, see
    AGENT_DIRECTORY.md's known limitations.

    Milestone 3 (Enterprise Surface Isolation): scoped to organization_id
    via an inner join through Principal -- confirmed unscoped before
    this (any caller could enumerate every organization's agents).
    Agent.acting_for_principal_id is NOT NULL, so the join never
    silently excludes a legitimate row."""
    stmt = (
        select(Agent)
        .join(Principal, Agent.acting_for_principal_id == Principal.id)
        .where(Principal.organization_id == organization_id)
    )
    if status:
        stmt = stmt.where(Agent.status == status)
    if environment:
        stmt = stmt.where(Agent.environment == environment)
    if owner:
        stmt = stmt.where(Agent.owner == owner)
    if principal_id:
        stmt = stmt.where(Agent.acting_for_principal_id == principal_id)
    if q:
        stmt = stmt.where(Agent.name.ilike(f"%{q}%"))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    stmt = stmt.order_by(Agent.created_at.desc()).limit(limit).offset(offset)
    agents = list(db.scalars(stmt))
    certs_by_agent = {
        c.agent_id: c
        for c in db.scalars(
            select(Certificate).where(
                Certificate.agent_id.in_([a.id for a in agents]), Certificate.status == "active"
            )
        )
    } if agents else {}
    return [(a, certs_by_agent.get(a.id)) for a in agents], total


def get_active_certificate(db: Session, certificate_id: uuid.UUID) -> Certificate | None:
    cert = db.get(Certificate, certificate_id)
    if cert is None or cert.status != "active":
        return None
    return cert


def compute_health(agent: Agent, now: datetime | None = None) -> str:
    """Agent Heartbeat (AGENT_LIFECYCLE.md): Healthy / Warning / Offline,
    derived from last_seen_at. Thresholds are a deliberate default (the
    spec doesn't define them, the same kind of judgment call as
    authority_context_service.classify_risk's risk bands): Healthy within 5 minutes,
    Warning within 30 minutes, Offline beyond that or if never seen. An
    agent that isn't 'active' (or 'suspended', which can still heartbeat)
    is reported 'unknown' rather than Offline -- it was never expected to
    be reporting in the first place."""
    if agent.status not in ("active", "suspended"):
        return "unknown"
    if agent.last_seen_at is None:
        return "offline"
    now = now or datetime.now(timezone.utc)
    age_seconds = (now - agent.last_seen_at).total_seconds()
    if age_seconds <= 300:
        return "healthy"
    if age_seconds <= 1800:
        return "warning"
    return "offline"


def activate_agent(db: Session, agent_id: uuid.UUID, actor: str | None = None) -> Agent:
    """Registered -> Active, or Suspended -> Active (reactivation). Only
    the registered->active path also has a certificate to activate (a
    suspended agent's certificate was never touched by suspension)."""
    agent = get_agent(db, agent_id)
    if "active" not in _ALLOWED_TRANSITIONS.get(agent.status, set()):
        raise InvalidTransitionError(agent_id, agent.status, "activate")

    from_status = agent.status
    agent.status = "active"

    issued_cert = db.scalar(
        select(Certificate).where(Certificate.agent_id == agent_id, Certificate.status == "issued")
    )
    if issued_cert is not None:
        issued_cert.status = "active"
        issued_cert.activated_at = datetime.now(timezone.utc)

    event_type = "agent_reactivated" if from_status == "suspended" else "agent_activated"
    _append_audit_event(db, agent_id, event_type, actor, details={"from_status": from_status})
    db.commit()
    db.refresh(agent)
    return agent


def suspend_agent(
    db: Session, agent_id: uuid.UUID, reason: str | None = None, actor: str | None = None
) -> Agent:
    agent = get_agent(db, agent_id)
    if "suspended" not in _ALLOWED_TRANSITIONS.get(agent.status, set()):
        raise InvalidTransitionError(agent_id, agent.status, "suspend")

    agent.status = "suspended"
    _append_audit_event(db, agent_id, "agent_suspended", actor, details={"reason": reason})
    db.commit()
    db.refresh(agent)
    return agent


def retire_agent(
    db: Session, agent_id: uuid.UUID, reason: str | None = None, actor: str | None = None
) -> Agent:
    """Registered, Active, or Suspended -> Retired (terminal). The active
    (or issued) certificate is marked 'expired': a retired agent has no
    live certificate, so verify_agent_signature rejects any further
    signed request from it independently of the explicit status check in
    intent_service.submit_intent (defense in depth, not redundancy)."""
    agent = get_agent(db, agent_id)
    if "retired" not in _ALLOWED_TRANSITIONS.get(agent.status, set()):
        raise InvalidTransitionError(agent_id, agent.status, "retire")

    from_status = agent.status
    agent.status = "retired"

    live_cert = db.scalar(
        select(Certificate).where(
            Certificate.agent_id == agent_id, Certificate.status.in_(_CERT_LIVE_STATUSES)
        )
    )
    if live_cert is not None:
        live_cert.status = "expired"
        live_cert.expires_at = datetime.now(timezone.utc)

    _append_audit_event(
        db, agent_id, "agent_retired", actor, details={"from_status": from_status, "reason": reason}
    )
    db.commit()
    db.refresh(agent)
    return agent


def revoke_agent(
    db: Session, agent_id: uuid.UUID, reason: str | None = None, actor: str | None = None
) -> Agent:
    """Registered, Active, or Suspended -> Revoked (terminal, cannot be
    reactivated). Not in the spec's literal API list (only suspend/
    activate/retire/rotate/heartbeat/transfer are named), but "Revoked" is
    a required state in the same spec's own state machine section --
    without this endpoint it would be unreachable, so it's added here and
    called out explicitly rather than left as a dead state. Distinct from
    retire(): revoke implies the certificate itself may be compromised."""
    agent = get_agent(db, agent_id)
    if "revoked" not in _ALLOWED_TRANSITIONS.get(agent.status, set()):
        raise InvalidTransitionError(agent_id, agent.status, "revoke")

    from_status = agent.status
    agent.status = "revoked"

    live_cert = db.scalar(
        select(Certificate).where(
            Certificate.agent_id == agent_id, Certificate.status.in_(_CERT_LIVE_STATUSES)
        )
    )
    if live_cert is not None:
        live_cert.status = "revoked"
        live_cert.revoked_at = datetime.now(timezone.utc)

    _append_audit_event(
        db, agent_id, "agent_revoked", actor, details={"from_status": from_status, "reason": reason}
    )
    db.commit()
    db.refresh(agent)
    return agent


def rotate_certificate(
    db: Session, agent_id: uuid.UUID, new_public_key: str, actor: str | None = None
) -> Certificate:
    """CERTIFICATE_ROTATION.md's flow, server side: the new key pair is
    generated agent-side (SDK) or by the caller; only the new public key
    ever reaches this function (security.md: no private keys are ever
    stored by PayReality). The old certificate becomes 'rotated', never
    deleted; existing Intents/Decisions/Evidence reference agent_id, not
    certificate_id, so nothing about past Evidence needs to change or is
    invalidated by this."""
    agent = get_agent(db, agent_id)
    if agent.status not in ("active", "suspended"):
        raise InvalidTransitionError(agent_id, agent.status, "rotate")

    old_cert = get_active_certificate_for_agent(db, agent_id)
    if old_cert is None:
        raise NoActiveCertificateError(str(agent_id))

    now = datetime.now(timezone.utc)
    old_cert.status = "rotated"
    old_cert.rotated_at = now

    new_cert = Certificate(agent_id=agent_id, public_key=new_public_key, status="active", activated_at=now)
    db.add(new_cert)
    db.flush()

    agent.rotation_requested_at = None
    _append_audit_event(
        db, agent_id, "certificate_rotated", actor,
        details={"old_certificate_id": str(old_cert.id), "new_certificate_id": str(new_cert.id)},
    )
    db.commit()
    db.refresh(new_cert)
    return new_cert


def request_certificate_rotation(db: Session, agent_id: uuid.UUID, actor: str | None = None) -> Agent:
    """The honest half of "Bulk: Rotate Certificates" (CERTIFICATE_ROTATION.md):
    PayReality never holds an agent's private key, so it cannot generate a
    new key pair on an agent's behalf. This flags the agent for rotation
    (visible in the Directory and to the agent's own next heartbeat/
    authorize() call) rather than fabricating a rotation that would
    require possessing key material the platform is specifically
    designed never to have."""
    agent = get_agent(db, agent_id)
    agent.rotation_requested_at = datetime.now(timezone.utc)
    _append_audit_event(db, agent_id, "certificate_rotation_requested", actor, details={})
    db.commit()
    db.refresh(agent)
    return agent


def record_heartbeat(
    db: Session,
    agent_id: uuid.UUID,
    version: str | None = None,
    sdk_version: str | None = None,
    runtime: str | None = None,
) -> Agent:
    """No audit event: at 10,000+-agent scale a heartbeat every few
    minutes from every agent would flood the audit ledger for no auditing
    value. Only last_seen_at (and whichever of version/sdk_version/
    runtime were supplied) is updated."""
    agent = get_agent(db, agent_id)
    agent.last_seen_at = datetime.now(timezone.utc)
    if version is not None:
        agent.version = version
    if sdk_version is not None:
        agent.sdk_version = sdk_version
    if runtime is not None:
        agent.runtime = runtime
    db.commit()
    db.refresh(agent)
    return agent


def transfer_owner(
    db: Session,
    agent_id: uuid.UUID,
    new_owner: str,
    new_business_unit: str | None = None,
    actor: str | None = None,
) -> Agent:
    agent = get_agent(db, agent_id)
    from_owner, from_business_unit = agent.owner, agent.business_unit
    agent.owner = new_owner
    if new_business_unit is not None:
        agent.business_unit = new_business_unit

    _append_audit_event(
        db, agent_id, "owner_changed", actor,
        details={
            "from_owner": from_owner, "to_owner": new_owner,
            "from_business_unit": from_business_unit, "to_business_unit": agent.business_unit,
        },
    )
    db.commit()
    db.refresh(agent)
    return agent


def update_agent_metadata(db: Session, agent_id: uuid.UUID, **fields) -> Agent:
    """PATCH /agents/{id}: routine metadata edits (description, purpose,
    model, version, runtime, platform, environment, tags, labels). Not a
    lifecycle transition and not in the spec's named audit-event list, so
    no AgentAuditEvent row is produced (see AgentAuditEvent's docstring
    and AGENT_LIFECYCLE.md's audit-trail section for what is/isn't
    audited and why)."""
    agent = get_agent(db, agent_id)
    for field, value in fields.items():
        if value is not None:
            setattr(agent, field, value)
    db.commit()
    db.refresh(agent)
    return agent


def list_audit_events(db: Session, agent_id: uuid.UUID, limit: int = 50) -> list[AgentAuditEvent]:
    return list(
        db.scalars(
            select(AgentAuditEvent)
            .where(AgentAuditEvent.agent_id == agent_id)
            .order_by(AgentAuditEvent.created_at.desc())
            .limit(limit)
        )
    )


def get_audit_event(db: Session, event_id: uuid.UUID) -> AgentAuditEvent:
    event = db.get(AgentAuditEvent, event_id)
    if event is None:
        raise AuditEventNotFoundError(str(event_id))
    return event


def verify_audit_event(db: Session, event_id: uuid.UUID) -> tuple[bool, str]:
    """Mirrors evidence_service.verify_evidence, including resolving the
    public key through the signing-key registry by `event.key_id`
    (EVIDENCE_KEY_ROTATION.md) rather than whatever key is currently
    configured, so an audit event stays verifiable across a key
    rotation. See evidence_service.verify_evidence's docstring for the
    identical fallback/anomaly-logging reasoning."""
    event = get_audit_event(db, event_id)
    from app.domain.evidence.signing import public_key_b64_from_signing_key_b64

    public_key_b64 = signing_key_service.get_public_key_for_key_id(db, event.key_id)
    if public_key_b64 is None:
        logger.warning(
            "signing_key_registry_miss audit_event_id=%s key_id=%s: falling back to the "
            "currently configured key. This should not happen once the registry has "
            "been seeded; investigate if it recurs.",
            event_id, event.key_id,
        )
        public_key_b64 = public_key_b64_from_signing_key_b64(settings.evidence_signing_key_b64)
    valid = verify_payload(
        event.payload, Signature(algorithm="ed25519", key_id=event.key_id, value=event.signature), public_key_b64
    )
    return valid, event.key_id


def _agent_organization_id(db: Session, agent_id: uuid.UUID) -> uuid.UUID | None:
    """Milestone 3 (Enterprise Surface Isolation): Agent has no
    organization_id of its own -- reachable only via acting_for_
    principal_id -> Principal.organization_id, the same path
    _authorized_agent (routers/agents.py) resolves for single-agent
    endpoints. Returns None (never matches a real organization_id) for
    a missing agent, matching the "cross-organization access looks like
    not-found" convention rather than raising here."""
    agent = db.get(Agent, agent_id)
    if agent is None:
        return None
    principal = db.get(Principal, agent.acting_for_principal_id)
    return principal.organization_id if principal else None


def bulk_transition(
    db: Session,
    agent_ids: list[uuid.UUID],
    action: str,
    organization_id: uuid.UUID | None,
    reason: str | None = None,
    actor: str | None = None,
) -> list[dict]:
    """Bulk Operations (AGENT_DIRECTORY.md): each agent is processed
    independently -- one invalid transition in a batch of a thousand
    doesn't abort the other 999. Known scaling limit: this is still N
    sequential transactions, not a single set-based UPDATE; fine for the
    batch sizes an operator drives from the Directory UI, not a substitute
    for a real bulk-data migration tool at true 10,000+-agent scale (see
    AGENT_DIRECTORY.md).

    Milestone 3: `organization_id` is the caller's own. Any agent_id in
    the batch belonging to a DIFFERENT organization is rejected as
    "agent_not_found" -- confirmed unchecked before this, which would
    otherwise let one organization's own bulk action suspend, activate,
    retire, or request rotation for another organization's agents by id."""
    action_fn = {
        "suspend": lambda aid: suspend_agent(db, aid, reason=reason, actor=actor),
        "activate": lambda aid: activate_agent(db, aid, actor=actor),
        "retire": lambda aid: retire_agent(db, aid, reason=reason, actor=actor),
        "request_rotation": lambda aid: request_certificate_rotation(db, aid, actor=actor),
    }.get(action)
    if action_fn is None:
        raise ValueError(f"unknown bulk action: {action}")

    results = []
    for agent_id in agent_ids:
        if _agent_organization_id(db, agent_id) != organization_id:
            results.append(
                {"agent_id": str(agent_id), "ok": False, "error": str(AgentNotFoundError(str(agent_id)))}
            )
            continue
        try:
            action_fn(agent_id)
            results.append({"agent_id": str(agent_id), "ok": True, "error": None})
        except (AgentNotFoundError, InvalidTransitionError, NoActiveCertificateError) as e:
            db.rollback()
            results.append({"agent_id": str(agent_id), "ok": False, "error": str(e)})
    return results
