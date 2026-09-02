"""Milestone 3 (Enterprise Surface Isolation): the Organization Lifecycle
-- create, deactivate, archive, and member invitation/acceptance.

Complements `organization_service.py`'s existing single-org settings/
health/bootstrap functions rather than replacing them: `update_settings`
there already takes an `Organization` object directly (never resolving
one itself), so `PATCH /v1/organizations/{id}` (an arbitrary org, not
"my own") reuses it unchanged.

Confirmed in MULTI_TENANT_ARCHITECTURE_VERIFICATION.md: `Organization(...)`
was constructed in exactly one place in the entire codebase --
`organization_service.ensure_owner_bootstrapped`, a startup-only hook
that only ever looks at "the oldest" Organization. `create_organization`
below is the first real, repeatable, callable path to a second tenant.
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Organization, OrganizationInvitation, User
from app.domain.rbac.permissions import Role
from app.services import auth_service

# A distinct prefix from api_keys' "pr_live_" and the SDK's own
# conventions, so an invitation token is visually distinguishable from
# an API key if either is ever pasted somewhere by mistake.
_INVITATION_TOKEN_PREFIX = "pri_"
_INVITATION_VALIDITY = timedelta(days=7)


class OrganizationNotFoundError(Exception):
    pass


class InvalidOrganizationStatusError(Exception):
    def __init__(self, from_status: str, action: str):
        self.from_status = from_status
        self.action = action
        super().__init__(f"cannot {action} an organization in status '{from_status}'")


class InvitationNotFoundError(Exception):
    pass


class InvitationNotPendingError(Exception):
    pass


class InvitationExpiredError(Exception):
    pass


class EmailAlreadyRegisteredError(Exception):
    pass


def create_organization(
    db: Session, name: str, owner_email: str, owner_name: str, environment: str = "production"
) -> tuple[Organization, User, str]:
    """Mirrors `ensure_owner_bootstrapped`'s own Owner-creation shape
    (a temporary, unrecoverable password; `must_reset_password=True`;
    claimed later via the existing `POST /v1/auth/setup-owner` or a
    real login+reset), but as an on-demand, callable operation rather
    than a boot-time side effect that only ever runs once. Returns the
    raw temporary password -- shown to the platform admin exactly once,
    the same discipline `generate_api_key`/`create_user` already hold
    themselves to for a newly minted secret.

    `environment` (Developer Distribution & Sandbox v1): defaults to
    "production" so every existing caller of this function is
    unaffected. `routers/sandbox.py`'s own provisioning endpoint is the
    only caller that ever passes "sandbox" -- see Organization.environment's
    own docstring in db/models.py for what this label does and does not
    mean (never a security boundary of its own)."""
    organization = Organization(name=name, environment=environment)
    db.add(organization)
    db.flush()

    temporary_password = secrets.token_urlsafe(18)
    owner = User(
        organization_id=organization.id,
        email=owner_email,
        name=owner_name,
        password_hash=auth_service.hash_password(temporary_password),
        role=Role.OWNER.value,
        must_reset_password=True,
    )
    db.add(owner)
    db.commit()
    db.refresh(organization)
    db.refresh(owner)
    return organization, owner, temporary_password


def list_organizations(db: Session) -> list[Organization]:
    """Organization Discovery. Deliberately the only place every
    Organization is ever listed at once -- there is no per-user "list
    my organizations" concept in this codebase (a User belongs to
    exactly one Organization via a NOT NULL FK), so this function, and
    the platform-admin-only endpoint that calls it, exist specifically
    for the Operator Key's own discovery need: knowing which
    organization ids are valid to put in X-PayReality-Organization-Id."""
    return list(db.scalars(select(Organization).order_by(Organization.created_at)))


def get_organization(db: Session, organization_id: uuid.UUID) -> Organization:
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise OrganizationNotFoundError(str(organization_id))
    return organization


def deactivate_organization(db: Session, organization_id: uuid.UUID, actor: str | None = None) -> Organization:
    organization = get_organization(db, organization_id)
    if organization.status != "active":
        raise InvalidOrganizationStatusError(organization.status, "deactivate")
    organization.status = "deactivated"
    organization.deactivated_at = datetime.now(timezone.utc)
    organization.deactivated_by = actor
    db.commit()
    db.refresh(organization)
    return organization


def reactivate_organization(db: Session, organization_id: uuid.UUID, actor: str | None = None) -> Organization:
    """Not in this milestone's own explicit lifecycle list, but the
    natural, symmetric inverse of deactivate_organization -- without it,
    a deactivation would be permanent in practice (archive is the only
    other transition out of 'deactivated', and that one deliberately
    is)."""
    organization = get_organization(db, organization_id)
    if organization.status != "deactivated":
        raise InvalidOrganizationStatusError(organization.status, "reactivate")
    organization.status = "active"
    organization.deactivated_at = None
    organization.deactivated_by = None
    db.commit()
    db.refresh(organization)
    return organization


def archive_organization(db: Session, organization_id: uuid.UUID, actor: str | None = None) -> Organization:
    """Sequential, not skippable: an Organization must be deactivated
    first -- the same "retire, don't skip states" discipline
    Agent/RuntimePolicy lifecycles already hold themselves to."""
    organization = get_organization(db, organization_id)
    if organization.status != "deactivated":
        raise InvalidOrganizationStatusError(organization.status, "archive (deactivate it first)")
    organization.status = "archived"
    organization.archived_at = datetime.now(timezone.utc)
    organization.archived_by = actor
    db.commit()
    db.refresh(organization)
    return organization


def _hash_invitation_token(raw_token: str) -> str:
    """Same SHA-256-of-a-generated-secret pattern as
    auth_service.hash_api_key -- the raw token is high-entropy and
    machine-generated, never human-chosen, so bcrypt buys nothing here."""
    return auth_service.hash_api_key(raw_token)


def invite_member(
    db: Session, organization_id: uuid.UUID, email: str, role: str, invited_by: str | None = None
) -> tuple[OrganizationInvitation, str]:
    """The real email-and-accept flow `POST /v1/users` never was: that
    endpoint (still supported, unchanged) creates the User directly
    with a temporary password shown once in the response -- no email
    delivery, no separate accept step. This platform still sends no
    email itself; the raw token is returned to the inviter exactly
    once, to deliver however they choose."""
    existing_user = db.scalar(
        select(User).where(User.organization_id == organization_id, User.email == email)
    )
    if existing_user is not None:
        raise EmailAlreadyRegisteredError(email)

    raw_token = _INVITATION_TOKEN_PREFIX + secrets.token_urlsafe(32)
    invitation = OrganizationInvitation(
        id=uuid.uuid4(),
        organization_id=organization_id,
        email=email,
        role=role,
        token_hash=_hash_invitation_token(raw_token),
        invited_by=invited_by,
        expires_at=datetime.now(timezone.utc) + _INVITATION_VALIDITY,
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return invitation, raw_token


def list_invitations(
    db: Session, organization_id: uuid.UUID, status: str | None = None
) -> list[OrganizationInvitation]:
    stmt = select(OrganizationInvitation).where(OrganizationInvitation.organization_id == organization_id)
    if status is not None:
        stmt = stmt.where(OrganizationInvitation.status == status)
    return list(db.scalars(stmt.order_by(OrganizationInvitation.created_at.desc())))


def revoke_invitation(db: Session, invitation_id: uuid.UUID, organization_id: uuid.UUID) -> OrganizationInvitation:
    """A different organization's invitation is treated identically to
    one that doesn't exist, the same convention this entire milestone
    applies everywhere else."""
    invitation = db.get(OrganizationInvitation, invitation_id)
    if invitation is None or invitation.organization_id != organization_id:
        raise InvitationNotFoundError(str(invitation_id))
    if invitation.status != "pending":
        raise InvitationNotPendingError(f"cannot revoke an invitation in status '{invitation.status}'")
    invitation.status = "revoked"
    db.commit()
    db.refresh(invitation)
    return invitation


def accept_invitation(db: Session, raw_token: str, name: str, password: str) -> User:
    """Membership Validation: token existence, pending status, and
    expiry are all checked before a User row is ever created -- this is
    the actual point membership is validated at, not merely assumed
    from a caller who happens to hold the token. Unauthenticated by
    necessity (the same reason POST /v1/auth/login is): a brand new
    member has no session or API key yet."""
    token_hash = _hash_invitation_token(raw_token)
    invitation = db.scalar(select(OrganizationInvitation).where(OrganizationInvitation.token_hash == token_hash))
    if invitation is None:
        raise InvitationNotFoundError("invalid token")
    if invitation.status != "pending":
        raise InvitationNotPendingError(f"invitation is already '{invitation.status}'")
    if invitation.expires_at <= datetime.now(timezone.utc):
        invitation.status = "expired"
        db.commit()
        raise InvitationExpiredError(str(invitation.id))

    existing_user = db.scalar(
        select(User).where(User.organization_id == invitation.organization_id, User.email == invitation.email)
    )
    if existing_user is not None:
        raise EmailAlreadyRegisteredError(invitation.email)

    user = User(
        organization_id=invitation.organization_id,
        email=invitation.email,
        name=name,
        password_hash=auth_service.hash_password(password),
        role=invitation.role,
    )
    db.add(user)
    db.flush()  # assign user.id without committing yet, matching agent_service.create_agent's own pattern

    invitation.status = "accepted"
    invitation.accepted_at = datetime.now(timezone.utc)
    invitation.accepted_by_user_id = user.id

    db.commit()
    db.refresh(user)
    return user


# --- Developer Distribution & Sandbox v1: sandbox lifecycle -----------------


def find_sandbox_organization_by_owner_email(db: Session, owner_email: str) -> Organization | None:
    """Enforces "one sandbox per developer" at provisioning time
    (`routers/sandbox.py`): a non-archived sandbox Organization whose
    Owner already has this email means a new one is refused, not
    silently created alongside it. Archived sandboxes don't count --
    someone whose earlier sandbox was cleaned up may request a new one."""
    return db.scalar(
        select(Organization)
        .join(User, User.organization_id == Organization.id)
        .where(
            Organization.environment == "sandbox",
            Organization.status != "archived",
            User.email == owner_email,
            User.role == Role.OWNER.value,
        )
    )


def list_stale_sandbox_organizations(db: Session, older_than_days: int) -> list[Organization]:
    """Sandbox Organizations, still active, created more than
    `older_than_days` ago -- the candidate set `scripts/
    cleanup_stale_sandboxes.py` archives. Never includes a
    'production' Organization regardless of age; never includes one
    already deactivated/archived (nothing to do)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    return list(
        db.scalars(
            select(Organization).where(
                Organization.environment == "sandbox",
                Organization.status == "active",
                Organization.created_at < cutoff,
            )
        )
    )


def archive_stale_sandbox_organizations(
    db: Session, older_than_days: int, actor: str = "sandbox-cleanup"
) -> list[Organization]:
    """Runs the real, unmodified deactivate-then-archive sequence
    (`deactivate_organization` / `archive_organization` above) against
    every stale sandbox found by `list_stale_sandbox_organizations` --
    no shortcut, no direct status write. Returns the archived
    Organizations. Not wired into any scheduler by this milestone; see
    `scripts/cleanup_stale_sandboxes.py` for the operational entry
    point this function is meant to be called from."""
    archived = []
    for organization in list_stale_sandbox_organizations(db, older_than_days):
        deactivate_organization(db, organization.id, actor=actor)
        archived.append(archive_organization(db, organization.id, actor=actor))
    return archived
