"""Trusted Integration Architecture, Phase 2: IntegrationIdentity's own
API surface. Follows Agent's own registration/lifecycle conventions
where they genuinely apply, without pretending an IntegrationIdentity
is an Agent (see the model's own docstring). Gated on the new
integration_identity.manage permission throughout, deliberately not
runtime_policy/integration_contract permissions (Phase 2's own RBAC
decision, section 32)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.integration_identity import (
    IntegrationIdentityCertificateResponse,
    IntegrationIdentityResponse,
    RegisterIntegrationIdentityRequest,
    RotateCertificateRequest,
)
from app.services import integration_identity_service as svc
from app.services import sandbox_limits
from app.services.integration_identity_service import (
    IntegrationIdentityInvalidTransitionError,
    IntegrationIdentityNotFoundError,
    NoActiveCertificateError,
)

router = APIRouter(prefix="/v1/integration-identities", tags=["integration-identities"])


def _identity_to_response(row) -> IntegrationIdentityResponse:
    return IntegrationIdentityResponse(
        id=str(row.id), organization_id=str(row.organization_id), name=row.name,
        status=row.status, created_by=row.created_by, created_at=row.created_at,
    )


def _certificate_to_response(row) -> IntegrationIdentityCertificateResponse:
    return IntegrationIdentityCertificateResponse(
        id=str(row.id), integration_identity_id=str(row.integration_identity_id), status=row.status,
        issued_at=row.issued_at, activated_at=row.activated_at, rotated_at=row.rotated_at,
        expires_at=row.expires_at, revoked_at=row.revoked_at,
    )


@router.post(
    "", response_model=IntegrationIdentityResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_IDENTITY_MANAGE))],
)
def register_integration_identity(
    body: RegisterIntegrationIdentityRequest, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        identity, _certificate = svc.register_integration_identity(db, organization.id, body.name, body.public_key)
    except sandbox_limits.SandboxLimitExceededError as e:
        raise HTTPException(status_code=403, detail=f"sandbox_limit_exceeded:{e.resource}")
    return _identity_to_response(identity)


@router.get(
    "", response_model=list[IntegrationIdentityResponse],
    dependencies=[Depends(require_permission(Permission.INTEGRATION_IDENTITY_MANAGE))],
)
def list_integration_identities(
    db: Session = Depends(get_db), organization: Organization = Depends(get_current_organization),
):
    return [_identity_to_response(r) for r in svc.list_integration_identities(db, organization.id)]


@router.get(
    "/{identity_id}", response_model=IntegrationIdentityResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_IDENTITY_MANAGE))],
)
def get_integration_identity(
    identity_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        row = svc.get_integration_identity(db, identity_id, organization.id)
    except IntegrationIdentityNotFoundError:
        raise HTTPException(status_code=404, detail="integration_identity_not_found")
    return _identity_to_response(row)


@router.get(
    "/{identity_id}/certificates", response_model=list[IntegrationIdentityCertificateResponse],
    dependencies=[Depends(require_permission(Permission.INTEGRATION_IDENTITY_MANAGE))],
)
def list_certificates(
    identity_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    svc.get_integration_identity(db, identity_id, organization.id)  # org-ownership check
    return [_certificate_to_response(c) for c in svc.list_certificates(db, identity_id)]


@router.post(
    "/{identity_id}/activate", response_model=IntegrationIdentityResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_IDENTITY_MANAGE))],
)
def activate_integration_identity(
    identity_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        row = svc.activate_integration_identity(db, identity_id, organization.id)
    except IntegrationIdentityNotFoundError:
        raise HTTPException(status_code=404, detail="integration_identity_not_found")
    except IntegrationIdentityInvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _identity_to_response(row)


@router.post(
    "/{identity_id}/suspend", response_model=IntegrationIdentityResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_IDENTITY_MANAGE))],
)
def suspend_integration_identity(
    identity_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        row = svc.suspend_integration_identity(db, identity_id, organization.id)
    except IntegrationIdentityNotFoundError:
        raise HTTPException(status_code=404, detail="integration_identity_not_found")
    except IntegrationIdentityInvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _identity_to_response(row)


@router.post(
    "/{identity_id}/revoke", response_model=IntegrationIdentityResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_IDENTITY_MANAGE))],
)
def revoke_integration_identity(
    identity_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        row = svc.revoke_integration_identity(db, identity_id, organization.id)
    except IntegrationIdentityNotFoundError:
        raise HTTPException(status_code=404, detail="integration_identity_not_found")
    except IntegrationIdentityInvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _identity_to_response(row)


@router.post(
    "/{identity_id}/retire", response_model=IntegrationIdentityResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_IDENTITY_MANAGE))],
)
def retire_integration_identity(
    identity_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        row = svc.retire_integration_identity(db, identity_id, organization.id)
    except IntegrationIdentityNotFoundError:
        raise HTTPException(status_code=404, detail="integration_identity_not_found")
    except IntegrationIdentityInvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _identity_to_response(row)


@router.post(
    "/{identity_id}/rotate", response_model=IntegrationIdentityCertificateResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_IDENTITY_MANAGE))],
)
def rotate_certificate(
    identity_id: uuid.UUID, body: RotateCertificateRequest, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        certificate = svc.rotate_certificate(db, identity_id, organization.id, body.new_public_key)
    except IntegrationIdentityNotFoundError:
        raise HTTPException(status_code=404, detail="integration_identity_not_found")
    except IntegrationIdentityInvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except NoActiveCertificateError:
        raise HTTPException(status_code=409, detail="no_active_certificate_to_rotate")
    return _certificate_to_response(certificate)
