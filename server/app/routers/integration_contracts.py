"""Trusted Integration Architecture, Phase 1: the Integration Contract
kernel's API surface. Additive only -- no existing endpoint is renamed
or changed. No Phase 2 concept (Integration Identity, EnforcementBinding,
Adapter authentication, runtime submission changes) is exposed here.

Every endpoint is organization-scoped through get_current_organization,
matching every other org-scoped router in this codebase; a cross-
organization id is rejected as not-found (never revealed to exist),
never as a distinguishable "forbidden."
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.integration_contract import (
    ApproveContractVersionRequest,
    ContractVersionResponse,
    CreateContractVersionRequest,
    CreateIntegrationRequest,
    EditContractVersionRequest,
    IntegrationResponse,
)
from app.services import integration_contract_service as svc
from app.services.integration_contract_service import (
    ConcurrentVersionConflictError,
    ContractInvalidTransitionError,
    ContractValidationError,
    ContractVersionHasActiveBindingError,
    ContractVersionNotFoundError,
    IntegrationNotFoundError,
)

router = APIRouter(prefix="/v1/integrations", tags=["integration-contracts"])


def _integration_to_response(row) -> IntegrationResponse:
    return IntegrationResponse(
        id=str(row.id), organization_id=str(row.organization_id),
        external_system_label=row.external_system_label,
        created_by=row.created_by, created_at=row.created_at,
    )


def _version_to_response(row) -> ContractVersionResponse:
    return ContractVersionResponse(
        id=str(row.id), integration_id=str(row.integration_id), organization_id=str(row.organization_id),
        source_operation=row.source_operation, version=row.version, canonical_action=row.canonical_action,
        resource_path=row.resource_path, fact_subject_path=row.fact_subject_path,
        amount_path=row.amount_path, currency_path=row.currency_path,
        context_bindings=row.context_bindings, content_hash=row.content_hash,
        source_schema_fingerprint=row.source_schema_fingerprint, status=row.status,
        created_by=row.created_by, created_at=row.created_at, validated_at=row.validated_at,
        approved_by=row.approved_by, approved_at=row.approved_at, retired_at=row.retired_at,
    )


@router.post(
    "", response_model=IntegrationResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_MANAGE))],
)
def create_integration(
    body: CreateIntegrationRequest, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        row = svc.create_integration(db, organization.id, body.external_system_label)
    except ContractValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _integration_to_response(row)


@router.get(
    "", response_model=list[IntegrationResponse],
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_MANAGE))],
)
def list_integrations(
    db: Session = Depends(get_db), organization: Organization = Depends(get_current_organization),
):
    return [_integration_to_response(r) for r in svc.list_integrations(db, organization.id)]


@router.get(
    "/{integration_id}", response_model=IntegrationResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_MANAGE))],
)
def get_integration(
    integration_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        row = svc.get_integration(db, integration_id, organization.id)
    except IntegrationNotFoundError:
        raise HTTPException(status_code=404, detail="integration_not_found")
    return _integration_to_response(row)


@router.post(
    "/{integration_id}/contract-versions", response_model=ContractVersionResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_MANAGE))],
)
def create_contract_version(
    integration_id: uuid.UUID, body: CreateContractVersionRequest, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        row = svc.create_contract_version(
            db, integration_id, organization.id, body.source_operation, body.canonical_action,
            resource_path=body.resource_path, fact_subject_path=body.fact_subject_path,
            amount_path=body.amount_path, currency_path=body.currency_path,
            context_bindings=body.context_bindings, source_schema_fingerprint=body.source_schema_fingerprint,
        )
    except IntegrationNotFoundError:
        raise HTTPException(status_code=404, detail="integration_not_found")
    except ContractValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ConcurrentVersionConflictError as e:
        raise HTTPException(status_code=409, detail=f"concurrent_version_conflict: {e}")
    return _version_to_response(row)


@router.get(
    "/{integration_id}/contract-versions", response_model=list[ContractVersionResponse],
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_MANAGE))],
)
def list_contract_versions(
    integration_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        rows = svc.list_contract_versions(db, integration_id, organization.id)
    except IntegrationNotFoundError:
        raise HTTPException(status_code=404, detail="integration_not_found")
    return [_version_to_response(r) for r in rows]


@router.get(
    "/{integration_id}/contract-versions/{version_id}", response_model=ContractVersionResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_MANAGE))],
)
def get_contract_version(
    integration_id: uuid.UUID, version_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        row = svc.get_contract_version(db, version_id, organization.id)
    except ContractVersionNotFoundError:
        raise HTTPException(status_code=404, detail="contract_version_not_found")
    if row.integration_id != integration_id:
        raise HTTPException(status_code=404, detail="contract_version_not_found")
    return _version_to_response(row)


@router.patch(
    "/{integration_id}/contract-versions/{version_id}", response_model=ContractVersionResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_MANAGE))],
)
def edit_contract_version(
    integration_id: uuid.UUID, version_id: uuid.UUID, body: EditContractVersionRequest,
    db: Session = Depends(get_db), organization: Organization = Depends(get_current_organization),
):
    fields = body.model_dump(exclude_unset=True)
    try:
        row = svc.edit_draft_contract_version(db, version_id, organization.id, **fields)
    except ContractVersionNotFoundError:
        raise HTTPException(status_code=404, detail="contract_version_not_found")
    except ContractInvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ContractValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _version_to_response(row)


@router.post(
    "/{integration_id}/contract-versions/{version_id}/validate", response_model=ContractVersionResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_MANAGE))],
)
def validate_contract_version(
    integration_id: uuid.UUID, version_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        row = svc.validate_contract_version(db, version_id, organization.id)
    except ContractVersionNotFoundError:
        raise HTTPException(status_code=404, detail="contract_version_not_found")
    except ContractInvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ContractValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _version_to_response(row)


@router.post(
    "/{integration_id}/contract-versions/{version_id}/approve", response_model=ContractVersionResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_PUBLISH))],
)
def approve_contract_version(
    integration_id: uuid.UUID, version_id: uuid.UUID, body: ApproveContractVersionRequest,
    db: Session = Depends(get_db), organization: Organization = Depends(get_current_organization),
):
    try:
        row = svc.approve_contract_version(db, version_id, organization.id, approver=body.approver)
    except ContractVersionNotFoundError:
        raise HTTPException(status_code=404, detail="contract_version_not_found")
    except ContractInvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _version_to_response(row)


@router.post(
    "/{integration_id}/contract-versions/{version_id}/retire", response_model=ContractVersionResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_PUBLISH))],
)
def retire_contract_version(
    integration_id: uuid.UUID, version_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        row = svc.retire_contract_version(db, version_id, organization.id)
    except ContractVersionNotFoundError:
        raise HTTPException(status_code=404, detail="contract_version_not_found")
    except ContractInvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ContractVersionHasActiveBindingError as e:
        raise HTTPException(status_code=409, detail=f"contract_version_has_active_binding: {e}")
    return _version_to_response(row)
