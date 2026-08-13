import hmac
import uuid

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Agent, Organization, User
from app.db.session import get_db
from app.domain.auth.signature import verify_request_signature
from app.domain.rbac.permissions import Permission, has_permission
from app.services import agent_service, auth_service


async def verify_agent_signature(
    request: Request,
    x_payreality_key_id: str = Header(...),
    x_payreality_signature: str = Header(...),
    db: Session = Depends(get_db),
) -> Agent:
    """spec Section 19 / 21.2: every Intent submission must be signed by the
    Agent's active Certificate over the raw request body. Returns the
    resolved Agent so route handlers never see an unauthenticated request."""
    try:
        certificate_id = uuid.UUID(x_payreality_key_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid_key_id")

    certificate = agent_service.get_active_certificate(db, certificate_id)
    if certificate is None:
        raise HTTPException(status_code=401, detail="unknown_or_inactive_certificate")

    body = await request.body()
    if not verify_request_signature(body, x_payreality_signature, certificate.public_key):
        raise HTTPException(status_code=401, detail="invalid_signature")

    agent = db.get(Agent, certificate.agent_id)
    if agent is None:
        raise HTTPException(status_code=401, detail="agent_not_found")
    return agent


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization[len("bearer ") :].strip()
    return token or None


def require_permission(permission: Permission):
    """Phase 10's layered auth check, in priority order:

    1. The existing shared operator key (`X-PayReality-Operator-Key`), if
       present, behaves EXACTLY as `verify_operator_key` always has --
       every current integration (SDK, frontend, existing automation)
       keeps working unmodified. A present-but-wrong key still fails
       closed with 401, matching prior behavior; it never silently falls
       through to the permission check below.
    2. Otherwise, a bearer token (session id or API key, see
       `auth_service.resolve_role_for_token`) is resolved to a `Role`,
       and that role's permission set decides access. "Never check roles
       directly. Always check permissions" (Phase 10's own directive) --
       this is the one place role identity becomes an authorization
       decision.
    """

    async def _check(
        x_payreality_operator_key: str | None = Header(None),
        authorization: str | None = Header(None),
        db: Session = Depends(get_db),
    ) -> None:
        if x_payreality_operator_key is not None:
            if not settings.admin_api_key:
                raise HTTPException(status_code=503, detail="operator_auth_not_configured")
            if not hmac.compare_digest(x_payreality_operator_key, settings.admin_api_key):
                raise HTTPException(status_code=401, detail="invalid_operator_key")
            return

        token = _bearer_token(authorization)
        if token is None:
            raise HTTPException(status_code=401, detail="authentication_required")

        role = auth_service.resolve_role_for_token(db, token)
        if role is None:
            raise HTTPException(status_code=401, detail="invalid_or_expired_credential")

        if not has_permission(role, permission):
            raise HTTPException(status_code=403, detail="permission_denied")

    return _check


def get_current_user_if_session(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> User | None:
    """Authority-as-a-continuous-object, Stage D: for routes gated by
    `require_permission` (Operator Key OR session OR API key) that also
    want to record *which real person* acted, not just that the caller
    was authorized to. Returns the real User only when a human session
    token was actually used; returns None for the Operator Key, for an
    API key (a service credential with no single acting person), or for
    no credential at all. Callers must keep a free-text fallback for the
    None case -- this is additive alongside `require_permission`, never
    a replacement for it, and never itself a gate."""
    token = _bearer_token(authorization)
    if token is None:
        return None
    return auth_service.resolve_user_for_session_token(db, token)


def get_current_user(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """Session-authenticated routes only (login/me/logout, and any route
    that needs to know exactly which human is acting, e.g. Users
    management) -- an operator key or API key has no single User to
    resolve, so those callers use `require_permission`/
    `get_current_organization` instead, never this."""
    token = _bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="authentication_required")
    user = auth_service.resolve_user_for_session_token(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid_or_expired_session")
    return user


def get_current_organization(
    x_payreality_operator_key: str | None = Header(None),
    x_payreality_organization_id: str | None = Header(None),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> Organization:
    """Resolves "the organisation this request is acting on behalf of":
    a session or API key resolves to its own Organisation directly, the
    same as before Milestone 2.

    Milestone 2 (Multi-Tenant Foundation): the Operator Key is now
    platform-admin-only -- it belongs to no single Organisation, and is
    no longer treated as implicitly acting for "whichever Organisation
    was created first" (a default that only ever made sense for a
    genuinely single-tenant deployment: with more than one Organisation,
    every operator-key request would silently keep acting on the OLDEST
    one regardless of which the caller actually meant, which is exactly
    the kind of cross-tenant ambiguity this milestone exists to remove).
    A request authenticated with the Operator Key must now name its
    target Organisation explicitly via X-PayReality-Organization-Id --
    there is no default, and none is inferred.

    Disclosed, known consequence (see MILESTONE_2_MULTI_TENANT_
    FOUNDATION_SUMMARY.md's Remaining Risks): the frontend's
    OperatorKeyField/apiClient.ts flow, the Python SDK's admin-key path,
    and scripts/smoke_test.py all currently call org-scoped endpoints
    with the Operator Key and no target-org header -- all three will
    start receiving organization_id_required_for_operator_key (400)
    until updated, deliberately left as follow-up work outside this
    milestone's backend-architecture scope."""
    if x_payreality_operator_key is not None:
        if not settings.admin_api_key or not hmac.compare_digest(
            x_payreality_operator_key, settings.admin_api_key
        ):
            raise HTTPException(status_code=401, detail="invalid_operator_key")
        if x_payreality_organization_id is None:
            raise HTTPException(status_code=400, detail="organization_id_required_for_operator_key")
        try:
            organization_id = uuid.UUID(x_payreality_organization_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_organization_id")
        organization = db.get(Organization, organization_id)
        if organization is None:
            raise HTTPException(status_code=404, detail="organization_not_found")
        return organization

    token = _bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="authentication_required")

    organization_id = auth_service.resolve_organization_id_for_token(db, token)
    if organization_id is None:
        raise HTTPException(status_code=401, detail="invalid_or_expired_credential")

    organization = db.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="organization_not_found")
    return organization
