"""Milestone 3 (Enterprise Surface Isolation): the Organization Lifecycle
-- create, list (discovery), update, deactivate, reactivate, and archive
an ARBITRARY organization. Distinct from routers/organization.py's
`/v1/organization` (singular, "my own org", gated by ordinary per-tenant
permissions): every endpoint here can name and act on any organization,
which is a platform-level capability, not a per-tenant one.

Gated on `verify_operator_key` (security.py) -- the pure Operator-Key-only
check with no session/role fallback, the same platform-admin-only
primitive `process_due_schedules` uses. `require_permission`'s
operator-key branch doesn't fit here for the same reason it didn't fit
there: Role.OWNER holds every Permission via `_ALL_PERMISSIONS`
(permissions.py's own "Owner: full platform control" design), so no
Permission value could ever be made operator-key-exclusive within that
system. Confirmed as the correct primitive by this milestone's own
repository audit: `Organization(...)` was, before this router existed,
constructed in exactly one place in the whole codebase -- a startup-only
bootstrap hook with no API of any kind.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.organization import OrganizationSettingsResponse, UpdateOrganizationSettingsRequest
from app.schemas.organization_lifecycle import (
    CreateOrganizationRequest,
    CreateOrganizationResponse,
    OrganizationActionRequest,
    OrganizationLifecycleResponse,
)
from app.schemas.users import UserResponse
from app.security import verify_operator_key
from app.services import organization_lifecycle_service as svc
from app.services import organization_service
from app.services.organization_lifecycle_service import InvalidOrganizationStatusError, OrganizationNotFoundError

router = APIRouter(
    prefix="/v1/organizations", tags=["organization-lifecycle"], dependencies=[Depends(verify_operator_key)]
)


@router.post("", response_model=CreateOrganizationResponse, status_code=201)
def create_organization(body: CreateOrganizationRequest, db: Session = Depends(get_db)):
    organization, owner, temporary_password = svc.create_organization(
        db, name=body.name, owner_email=body.owner_email, owner_name=body.owner_name
    )
    return CreateOrganizationResponse(
        organization=OrganizationLifecycleResponse.from_model(organization),
        owner=UserResponse.from_model(owner),
        temporary_password=temporary_password,
    )


@router.get("", response_model=list[OrganizationLifecycleResponse])
def list_organizations(db: Session = Depends(get_db)):
    """Organization Discovery: the one place every organization is ever
    listed at once, so a platform admin holding only the Operator Key
    can learn which organization ids are valid to put in
    X-PayReality-Organization-Id."""
    return [OrganizationLifecycleResponse.from_model(o) for o in svc.list_organizations(db)]


@router.get("/{organization_id}", response_model=OrganizationLifecycleResponse)
def get_organization(organization_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        organization = svc.get_organization(db, organization_id)
    except OrganizationNotFoundError:
        raise HTTPException(status_code=404, detail="organization_not_found")
    return OrganizationLifecycleResponse.from_model(organization)


@router.patch("/{organization_id}", response_model=OrganizationSettingsResponse)
def update_organization(
    organization_id: uuid.UUID, body: UpdateOrganizationSettingsRequest, db: Session = Depends(get_db)
):
    """Reuses organization_service.update_settings unchanged -- it
    already takes an Organization object directly rather than resolving
    one itself via get_current_organization, so it works identically
    here for an arbitrary, platform-admin-named organization."""
    try:
        organization = svc.get_organization(db, organization_id)
    except OrganizationNotFoundError:
        raise HTTPException(status_code=404, detail="organization_not_found")
    updates = body.model_dump(exclude_unset=True)
    extra_settings = updates.pop("settings", None) or {}
    updates.update(extra_settings)
    organization = organization_service.update_settings(db, organization, updates)
    data = organization_service.get_settings(organization)
    return OrganizationSettingsResponse(
        name=data["name"], logo_url=data["logo_url"], timezone=data["timezone"],
        default_currency=data["default_currency"], default_language=data["default_language"],
        settings=organization.settings,
    )


@router.post("/{organization_id}/deactivate", response_model=OrganizationLifecycleResponse)
def deactivate_organization(
    organization_id: uuid.UUID, body: OrganizationActionRequest = OrganizationActionRequest(), db: Session = Depends(get_db)
):
    try:
        organization = svc.deactivate_organization(db, organization_id, actor=body.actor)
    except OrganizationNotFoundError:
        raise HTTPException(status_code=404, detail="organization_not_found")
    except InvalidOrganizationStatusError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return OrganizationLifecycleResponse.from_model(organization)


@router.post("/{organization_id}/reactivate", response_model=OrganizationLifecycleResponse)
def reactivate_organization(
    organization_id: uuid.UUID, body: OrganizationActionRequest = OrganizationActionRequest(), db: Session = Depends(get_db)
):
    try:
        organization = svc.reactivate_organization(db, organization_id, actor=body.actor)
    except OrganizationNotFoundError:
        raise HTTPException(status_code=404, detail="organization_not_found")
    except InvalidOrganizationStatusError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return OrganizationLifecycleResponse.from_model(organization)


@router.post("/{organization_id}/archive", response_model=OrganizationLifecycleResponse)
def archive_organization(
    organization_id: uuid.UUID, body: OrganizationActionRequest = OrganizationActionRequest(), db: Session = Depends(get_db)
):
    try:
        organization = svc.archive_organization(db, organization_id, actor=body.actor)
    except OrganizationNotFoundError:
        raise HTTPException(status_code=404, detail="organization_not_found")
    except InvalidOrganizationStatusError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return OrganizationLifecycleResponse.from_model(organization)
