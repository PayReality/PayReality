"""Organisation Settings and the Organisation Owner bootstrap.

`ensure_owner_bootstrapped` follows the same "startup hook + idempotent
registration" pattern already used for evidence-key rotation
(`signing_key_service.ensure_current_key_registered`, called from
main.py's lifespan): on every boot, create the one Organisation and its
Owner user if they don't exist yet, and do nothing if they already do.
This is additive -- the existing shared operator key keeps working
completely unchanged; this just gives the platform a first real human
identity to log in as.
"""

import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Organization, User
from app.domain.rbac.permissions import Role
from app.services import auth_service

logger = logging.getLogger("payreality.organization")


def ensure_owner_bootstrapped(db: Session) -> None:
    """Milestone 3 (Enterprise Surface Isolation): runs its create-org-
    and-owner logic only when ZERO organizations exist anywhere -- never
    "whichever organization happens to be oldest," a distinction that
    matters now that organization_lifecycle_service.create_organization
    is a real, repeatable way to bring a second (or Nth) organization
    into existence, always with its own Owner created atomically in the
    same transaction. Once any organization exists, this hook has
    nothing left to do, on this or any later boot -- it never inspects,
    and never assumes anything about, "the first" organization
    specifically. Confirmed as the one remaining "first organization"
    assumption in the codebase by this milestone's own repository audit
    (MULTI_TENANT_ARCHITECTURE_VERIFICATION.md already flagged and fixed
    the other one, dependencies.get_current_organization's Operator Key
    default, in Milestone 2)."""
    any_organization_exists = db.scalar(select(Organization.id).limit(1)) is not None
    if any_organization_exists:
        return

    organization = Organization(name=settings.organization_name)
    db.add(organization)
    db.flush()
    logger.info("organisation_bootstrapped name=%s", organization.name)

    # The password is deliberately never surfaced anywhere, including the
    # logs: it's a random, unrecoverable placeholder, not a credential
    # meant for anyone to actually retrieve and use. The real way to get
    # in is POST /v1/auth/setup-owner (frontend: /setup-owner), which
    # lets anyone holding the Operator Key -- a credential every real
    # deployment already has -- claim this account with their own email
    # and password. See RBAC.md's "Claiming the bootstrapped account".
    owner = User(
        organization_id=organization.id,
        email=settings.owner_email,
        name="Organisation Owner",
        password_hash=auth_service.hash_password(secrets.token_urlsafe(18)),
        role=Role.OWNER.value,
        must_reset_password=True,
    )
    db.add(owner)
    db.commit()
    logger.warning(
        "organisation_owner_bootstrapped email=%s -- unclaimed. Visit "
        "/setup-owner with the Operator Key to set a real password.",
        settings.owner_email,
    )


def get_settings(organization: Organization) -> dict:
    return {
        "name": organization.name,
        "logo_url": organization.logo_url,
        "timezone": organization.timezone,
        "default_currency": organization.default_currency,
        "default_language": organization.default_language,
        **organization.settings,
    }


_ORGANIZATION_COLUMNS = {"name", "logo_url", "timezone", "default_currency", "default_language"}


def update_settings(db: Session, organization: Organization, updates: dict) -> Organization:
    """Fields with their own column get set directly; everything else
    (Security/Runtime Authority/Notifications/Audit tab fields) is merged
    into the JSONB settings blob, never overwritten wholesale, so
    updating one tab's fields never clobbers another's."""
    merged_extra = dict(organization.settings)
    for key, value in updates.items():
        if key in _ORGANIZATION_COLUMNS:
            setattr(organization, key, value)
        else:
            merged_extra[key] = value
    organization.settings = merged_extra
    organization.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(organization)
    return organization


def get_integrations_status() -> dict:
    """Real state only. Azure OpenAI and AWS Bedrock have zero integration
    code in this codebase today -- reporting them as "configuration
    required" (never "connected") is the honest status until an adapter
    for either actually exists."""
    return {
        "anthropic": "connected" if settings.anthropic_api_key else "configuration_required",
        "azure_openai": "configuration_required",
        "aws_bedrock": "configuration_required",
        "opa": "connected" if _opa_reachable() else "disconnected",
        "postgresql": "connected" if _database_reachable() else "disconnected",
    }


def _database_reachable() -> bool:
    from sqlalchemy import text

    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        db.close()


def _opa_reachable() -> bool:
    from app.opa_client import HttpOpaClient

    try:
        return HttpOpaClient().health()
    except Exception:
        return False


def get_health_status() -> dict:
    """Reuses the same live checks as /health/ready rather than a second,
    independent notion of "healthy" -- Runtime Authority and the Evidence
    Engine have no separate health probe of their own (they're this
    process, backed by this database), so their status is honestly
    derived from the database check, not fabricated separately. The
    Compiler is a pure in-process module with no external dependency, so
    it has no failure mode a health check could observe here."""
    database_ok = _database_reachable()
    opa_ok = _opa_reachable()
    anthropic_configured = bool(settings.anthropic_api_key)

    return {
        "runtime_authority": "healthy" if database_ok else "offline",
        "evidence_engine": "healthy" if database_ok else "offline",
        "opa": "healthy" if opa_ok else "offline",
        "compiler": "healthy",
        "database": "healthy" if database_ok else "offline",
        "anthropic": "healthy" if anthropic_configured else "warning",
    }
