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
from app.services import auth_service, evidence_service, organization_service

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
