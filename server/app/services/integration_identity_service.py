"""Trusted Integration Architecture, Phase 2: IntegrationIdentity's own
lifecycle and certificate management -- a direct mirror of
agent_service.py's own proven state machine and rotation semantics
(same _ALLOWED_TRANSITIONS shape, same "old certificate never deleted,
only one active at a time" discipline), applied to a deliberately
thinner identity that holds no delegated organizational authority and
is never `Scope.principal`.

No audit-event ledger exists here (unlike Agent's own signed
AgentAuditEvent) -- a deliberate Phase 2 scope reduction, not an
oversight: nothing in this milestone's brief requires one, and adding a
second signed lifecycle ledger is exactly the kind of unrequested
symmetry Phase 1's own "do not add a status field merely for symmetry"
discipline already warns against.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import IntegrationIdentity, IntegrationIdentityCertificate
from app.services import sandbox_limits

# Identical shape to agent_service._ALLOWED_TRANSITIONS -- this identity's
# operational lifecycle is not meant to differ from Agent's at all.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "registered": {"active", "revoked", "retired"},
    "active": {"suspended", "revoked", "retired"},
    "suspended": {"active", "revoked", "retired"},
    "revoked": set(),
    "retired": set(),
}

_CERT_LIVE_STATUSES = ("issued", "active")


class IntegrationIdentityNotFoundError(Exception):
    pass


class IntegrationIdentityInvalidTransitionError(Exception):
    def __init__(self, identity_id: uuid.UUID, from_status: str, action: str):
        self.identity_id = identity_id
        self.from_status = from_status
        self.action = action
        super().__init__(f"cannot {action} integration identity {identity_id} from status '{from_status}'")


class NoActiveCertificateError(Exception):
    pass


def register_integration_identity(
    db: Session, organization_id: uuid.UUID, name: str, public_key: str, created_by: str | None = None,
) -> tuple[IntegrationIdentity, IntegrationIdentityCertificate]:
    """Registered, with an `issued` (not yet active) certificate --
    exactly Agent's own create_agent shape. A separate activate call is
    required before this identity's signature is accepted at all (the
    runtime auth dependency only resolves an `active` certificate, the
    same rule verify_agent_signature already enforces for Agent)."""
    if sandbox_limits.is_sandbox_organization(db, organization_id):
        existing = db.scalar(
            select(func.count())
            .select_from(IntegrationIdentity)
            .where(IntegrationIdentity.organization_id == organization_id)
        )
        if existing >= sandbox_limits.MAX_INTEGRATION_IDENTITIES_PER_SANDBOX:
            raise sandbox_limits.SandboxLimitExceededError(
                "integration identities", sandbox_limits.MAX_INTEGRATION_IDENTITIES_PER_SANDBOX
            )

    identity = IntegrationIdentity(
        organization_id=organization_id, name=name, status="registered", created_by=created_by,
    )
    db.add(identity)
    db.flush()

    certificate = IntegrationIdentityCertificate(
        integration_identity_id=identity.id, public_key=public_key, status="issued",
    )
    db.add(certificate)
    db.commit()
    db.refresh(identity)
    db.refresh(certificate)
    return identity, certificate


def get_integration_identity(
    db: Session, identity_id: uuid.UUID, organization_id: uuid.UUID,
) -> IntegrationIdentity:
    identity = db.scalar(
        select(IntegrationIdentity).where(
            IntegrationIdentity.id == identity_id, IntegrationIdentity.organization_id == organization_id,
        )
    )
    if identity is None:
        raise IntegrationIdentityNotFoundError(str(identity_id))
    return identity


def list_integration_identities(db: Session, organization_id: uuid.UUID) -> list[IntegrationIdentity]:
    return list(
        db.scalars(
            select(IntegrationIdentity)
            .where(IntegrationIdentity.organization_id == organization_id)
            .order_by(IntegrationIdentity.created_at)
        )
    )


def list_certificates(db: Session, identity_id: uuid.UUID) -> list[IntegrationIdentityCertificate]:
    return list(
        db.scalars(
            select(IntegrationIdentityCertificate)
            .where(IntegrationIdentityCertificate.integration_identity_id == identity_id)
            .order_by(IntegrationIdentityCertificate.issued_at)
        )
    )


def get_active_certificate_for_identity(
    db: Session, identity_id: uuid.UUID,
) -> IntegrationIdentityCertificate | None:
    return db.scalar(
        select(IntegrationIdentityCertificate).where(
            IntegrationIdentityCertificate.integration_identity_id == identity_id,
            IntegrationIdentityCertificate.status == "active",
        )
    )


def get_active_certificate(db: Session, certificate_id: uuid.UUID) -> IntegrationIdentityCertificate | None:
    """Not organization-scoped -- mirrors agent_service.get_active_
    certificate exactly: at the point this is called (request
    authentication, before any organization context is known), the
    certificate_id from the request header is the only lookup key
    available."""
    cert = db.get(IntegrationIdentityCertificate, certificate_id)
    if cert is None or cert.status != "active":
        return None
    return cert


def activate_integration_identity(
    db: Session, identity_id: uuid.UUID, organization_id: uuid.UUID,
) -> IntegrationIdentity:
    identity = get_integration_identity(db, identity_id, organization_id)
    if "active" not in _ALLOWED_TRANSITIONS.get(identity.status, set()):
        raise IntegrationIdentityInvalidTransitionError(identity_id, identity.status, "activate")

    identity.status = "active"
    issued_cert = db.scalar(
        select(IntegrationIdentityCertificate).where(
            IntegrationIdentityCertificate.integration_identity_id == identity_id,
            IntegrationIdentityCertificate.status == "issued",
        )
    )
    if issued_cert is not None:
        issued_cert.status = "active"
        issued_cert.activated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(identity)
    return identity


def suspend_integration_identity(
    db: Session, identity_id: uuid.UUID, organization_id: uuid.UUID,
) -> IntegrationIdentity:
    identity = get_integration_identity(db, identity_id, organization_id)
    if "suspended" not in _ALLOWED_TRANSITIONS.get(identity.status, set()):
        raise IntegrationIdentityInvalidTransitionError(identity_id, identity.status, "suspend")
    identity.status = "suspended"
    db.commit()
    db.refresh(identity)
    return identity


def revoke_integration_identity(
    db: Session, identity_id: uuid.UUID, organization_id: uuid.UUID,
) -> IntegrationIdentity:
    identity = get_integration_identity(db, identity_id, organization_id)
    if "revoked" not in _ALLOWED_TRANSITIONS.get(identity.status, set()):
        raise IntegrationIdentityInvalidTransitionError(identity_id, identity.status, "revoke")
    identity.status = "revoked"
    live_cert = db.scalar(
        select(IntegrationIdentityCertificate).where(
            IntegrationIdentityCertificate.integration_identity_id == identity_id,
            IntegrationIdentityCertificate.status.in_(_CERT_LIVE_STATUSES),
        )
    )
    if live_cert is not None:
        live_cert.status = "revoked"
        live_cert.revoked_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(identity)
    return identity


def retire_integration_identity(
    db: Session, identity_id: uuid.UUID, organization_id: uuid.UUID,
) -> IntegrationIdentity:
    identity = get_integration_identity(db, identity_id, organization_id)
    if "retired" not in _ALLOWED_TRANSITIONS.get(identity.status, set()):
        raise IntegrationIdentityInvalidTransitionError(identity_id, identity.status, "retire")
    identity.status = "retired"
    live_cert = db.scalar(
        select(IntegrationIdentityCertificate).where(
            IntegrationIdentityCertificate.integration_identity_id == identity_id,
            IntegrationIdentityCertificate.status.in_(_CERT_LIVE_STATUSES),
        )
    )
    if live_cert is not None:
        live_cert.status = "expired"
        live_cert.expires_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(identity)
    return identity


def rotate_certificate(
    db: Session, identity_id: uuid.UUID, organization_id: uuid.UUID, new_public_key: str,
) -> IntegrationIdentityCertificate:
    """Mirrors agent_service.rotate_certificate exactly: the new keypair
    is generated Adapter-side; only the new public key ever reaches
    this function. The old certificate becomes 'rotated', never
    deleted -- existing Intent rows reference `integration_identity_id`,
    never a certificate id, so nothing about past Evidence changes or
    is invalidated by a rotation."""
    identity = get_integration_identity(db, identity_id, organization_id)
    if identity.status not in ("active", "suspended"):
        raise IntegrationIdentityInvalidTransitionError(identity_id, identity.status, "rotate")

    old_cert = get_active_certificate_for_identity(db, identity_id)
    if old_cert is None:
        raise NoActiveCertificateError(str(identity_id))

    now = datetime.now(timezone.utc)
    old_cert.status = "rotated"
    old_cert.rotated_at = now

    new_cert = IntegrationIdentityCertificate(
        integration_identity_id=identity_id, public_key=new_public_key, status="active", activated_at=now,
    )
    db.add(new_cert)
    db.commit()
    db.refresh(new_cert)
    return new_cert
