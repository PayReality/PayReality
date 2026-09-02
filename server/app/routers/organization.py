from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ApiKey, Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.rbac.permissions import Permission, Role
from app.schemas.evidence import EvidenceResponse
from app.schemas.organization import (
    ApiKeyResponse,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
    HealthStatusResponse,
    IntegrationsStatusResponse,
    OrganizationSettingsResponse,
    UpdateOrganizationSettingsRequest,
)
from app.schemas.organization_lifecycle import InvitationResponse, InviteMemberRequest, InviteMemberResponse
from app.services import auth_service, evidence_service, organization_service
from app.services import organization_lifecycle_service as lifecycle_svc
from app.services.organization_lifecycle_service import EmailAlreadyRegisteredError, InvitationNotFoundError, InvitationNotPendingError

router = APIRouter(prefix="/v1/organization", tags=["organization"])


@router.get(
    "/settings",
    response_model=OrganizationSettingsResponse,
    dependencies=[Depends(require_permission(Permission.SETTINGS_VIEW))],
)
def get_settings(organization: Organization = Depends(get_current_organization)):
    data = organization_service.get_settings(organization)
    return OrganizationSettingsResponse(
        name=data["name"],
        logo_url=data["logo_url"],
        timezone=data["timezone"],
        default_currency=data["default_currency"],
        default_language=data["default_language"],
        settings=organization.settings,
        environment=data["environment"],
    )


@router.patch(
    "/settings",
    response_model=OrganizationSettingsResponse,
    dependencies=[Depends(require_permission(Permission.ORGANISATION_MANAGE))],
)
def update_settings(
    body: UpdateOrganizationSettingsRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    updates = body.model_dump(exclude_unset=True)
    extra_settings = updates.pop("settings", None) or {}
    updates.update(extra_settings)
    organization = organization_service.update_settings(db, organization, updates)
    data = organization_service.get_settings(organization)
    return OrganizationSettingsResponse(
        name=data["name"],
        logo_url=data["logo_url"],
        timezone=data["timezone"],
        default_currency=data["default_currency"],
        default_language=data["default_language"],
        settings=organization.settings,
        environment=data["environment"],
    )


@router.get(
    "/integrations",
    response_model=IntegrationsStatusResponse,
    dependencies=[Depends(require_permission(Permission.SETTINGS_VIEW))],
)
def get_integrations():
    return IntegrationsStatusResponse(**organization_service.get_integrations_status())


@router.get(
    "/health",
    response_model=HealthStatusResponse,
    dependencies=[Depends(require_permission(Permission.ASSURANCE_VIEW))],
)
def get_health():
    return HealthStatusResponse(**organization_service.get_health_status())


@router.get(
    "/exports/evidence",
    response_model=list[EvidenceResponse],
    dependencies=[Depends(require_permission(Permission.AUDIT_EXPORT))],
)
def export_evidence(
    organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)
):
    return [EvidenceResponse.from_model(e) for e in evidence_service.list_evidence(db, organization.id)]


@router.get(
    "/api-keys",
    response_model=list[ApiKeyResponse],
    dependencies=[Depends(require_permission(Permission.API_KEYS_MANAGE))],
)
def list_api_keys(
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    keys = db.scalars(
        select(ApiKey).where(ApiKey.organization_id == organization.id).order_by(ApiKey.created_at)
    )
    return [ApiKeyResponse.from_model(k) for k in keys]


@router.post(
    "/api-keys",
    response_model=CreateApiKeyResponse,
    status_code=201,
    dependencies=[Depends(require_permission(Permission.API_KEYS_MANAGE))],
)
def create_api_key(
    body: CreateApiKeyRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        Role(body.role)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_role")

    raw_key, key_hash, key_prefix = auth_service.generate_api_key()
    api_key = ApiKey(
        organization_id=organization.id,
        name=body.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        role=body.role,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return CreateApiKeyResponse(api_key=ApiKeyResponse.from_model(api_key), raw_key=raw_key)


@router.delete(
    "/api-keys/{api_key_id}",
    status_code=204,
    dependencies=[Depends(require_permission(Permission.API_KEYS_MANAGE))],
)
def revoke_api_key(
    api_key_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    api_key = db.get(ApiKey, api_key_id)
    if api_key is None or api_key.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="api_key_not_found")
    if api_key.revoked_at is None:
        api_key.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return None


# --- Organization Lifecycle: inviting members into MY OWN organization ---
#
# Milestone 3 (Enterprise Surface Isolation): distinct from
# routers/organization_lifecycle.py's platform-admin-only create/list/
# deactivate/archive of an ARBITRARY organization -- inviting a member is
# an ordinary per-tenant action, scoped to the caller's own organization
# via get_current_organization, gated by the same USERS_MANAGE permission
# POST /v1/users already uses. The real email-and-accept flow that
# endpoint never was: it creates the User directly with a temporary
# password shown once, no separate accept step.


@router.post(
    "/invitations",
    response_model=InviteMemberResponse,
    status_code=201,
    dependencies=[Depends(require_permission(Permission.USERS_MANAGE))],
)
def invite_member(
    body: InviteMemberRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        Role(body.role)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_role")
    try:
        invitation, raw_token = lifecycle_svc.invite_member(db, organization.id, body.email, body.role)
    except EmailAlreadyRegisteredError:
        raise HTTPException(status_code=409, detail="email_already_exists")
    return InviteMemberResponse(invitation=InvitationResponse.from_model(invitation), raw_token=raw_token)


@router.get(
    "/invitations",
    response_model=list[InvitationResponse],
    dependencies=[Depends(require_permission(Permission.USERS_MANAGE))],
)
def list_invitations(
    status: str | None = None,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    return [
        InvitationResponse.from_model(i) for i in lifecycle_svc.list_invitations(db, organization.id, status=status)
    ]


@router.delete(
    "/invitations/{invitation_id}",
    response_model=InvitationResponse,
    dependencies=[Depends(require_permission(Permission.USERS_MANAGE))],
)
def revoke_invitation(
    invitation_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    try:
        invitation = lifecycle_svc.revoke_invitation(db, invitation_id, organization.id)
    except InvitationNotFoundError:
        raise HTTPException(status_code=404, detail="invitation_not_found")
    except InvitationNotPendingError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return InvitationResponse.from_model(invitation)
