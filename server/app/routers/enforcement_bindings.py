"""Trusted Integration Architecture, Phase 2: EnforcementBinding's own
API surface. Draft/configuration work is gated on integration_
contract.manage (Phase 1's own permission, reused -- this is
configuration, not governance approval); activation/retirement is
gated on integration_contract.publish, the one real governance
boundary (Phase 2's own RBAC decision, section 32)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.enforcement_binding import (
    AddAllowedAgentRequest,
    AllowedAgentResponse,
    BindingResponse,
    CreateBindingRequest,
    EditBindingRequest,
)
from app.services import enforcement_binding_service as svc
from app.services.enforcement_binding_service import (
    BindingInvalidTransitionError,
    BindingValidationError,
    ConcurrentActivationConflictError,
    EnforcementBindingNotFoundError,
)
from app.services.integration_contract_service import ContractVersionNotFoundError
from app.services.integration_identity_service import IntegrationIdentityNotFoundError

router = APIRouter(prefix="/v1/enforcement-bindings", tags=["enforcement-bindings"])


def _binding_to_response(db: Session, row) -> BindingResponse:
    allowed_agents = svc.list_allowed_agents(db, row.id, row.organization_id)
    return BindingResponse(
        id=str(row.id), organization_id=str(row.organization_id),
        integration_identity_id=str(row.integration_identity_id),
        integration_contract_version_id=str(row.integration_contract_version_id),
        integration_id=str(row.integration_id), source_operation=row.source_operation,
        environment=row.environment, status=row.status, created_by=row.created_by,
        created_at=row.created_at, activated_at=row.activated_at, retired_at=row.retired_at,
        allowed_agent_ids=[str(a.id) for a in allowed_agents],
    )


@router.post(
    "", response_model=BindingResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_MANAGE))],
)
def create_draft_binding(
    body: CreateBindingRequest, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        binding = svc.create_draft_binding(
            db, organization.id, body.integration_identity_id, body.integration_contract_version_id,
            body.environment, agent_ids=body.agent_ids,
        )
    except IntegrationIdentityNotFoundError:
        raise HTTPException(status_code=404, detail="integration_identity_not_found")
    except ContractVersionNotFoundError:
        raise HTTPException(status_code=404, detail="contract_version_not_found")
    except BindingValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _binding_to_response(db, binding)


@router.get(
    "", response_model=list[BindingResponse],
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_MANAGE))],
)
def list_bindings(db: Session = Depends(get_db), organization: Organization = Depends(get_current_organization)):
    return [_binding_to_response(db, b) for b in svc.list_bindings(db, organization.id)]


@router.get(
    "/{binding_id}", response_model=BindingResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_MANAGE))],
)
def get_binding(
    binding_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        binding = svc.get_binding(db, binding_id, organization.id)
    except EnforcementBindingNotFoundError:
        raise HTTPException(status_code=404, detail="enforcement_binding_not_found")
    return _binding_to_response(db, binding)


@router.patch(
    "/{binding_id}", response_model=BindingResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_MANAGE))],
)
def edit_draft_binding(
    binding_id: uuid.UUID, body: EditBindingRequest, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    fields = body.model_dump(exclude_unset=True)
    try:
        binding = svc.edit_draft_binding(db, binding_id, organization.id, **fields)
    except EnforcementBindingNotFoundError:
        raise HTTPException(status_code=404, detail="enforcement_binding_not_found")
    except (IntegrationIdentityNotFoundError, ContractVersionNotFoundError):
        raise HTTPException(status_code=404, detail="referenced_resource_not_found")
    except BindingInvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except BindingValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _binding_to_response(db, binding)


@router.post(
    "/{binding_id}/allowed-agents", response_model=BindingResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_MANAGE))],
)
def add_allowed_agent(
    binding_id: uuid.UUID, body: AddAllowedAgentRequest, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        binding = svc.add_allowed_agent(db, binding_id, organization.id, body.agent_id)
    except EnforcementBindingNotFoundError:
        raise HTTPException(status_code=404, detail="enforcement_binding_not_found")
    except BindingInvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except BindingValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _binding_to_response(db, binding)


@router.delete(
    "/{binding_id}/allowed-agents/{agent_id}", response_model=BindingResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_MANAGE))],
)
def remove_allowed_agent(
    binding_id: uuid.UUID, agent_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        binding = svc.remove_allowed_agent(db, binding_id, organization.id, agent_id)
    except EnforcementBindingNotFoundError:
        raise HTTPException(status_code=404, detail="enforcement_binding_not_found")
    except BindingInvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _binding_to_response(db, binding)


@router.get(
    "/{binding_id}/allowed-agents", response_model=list[AllowedAgentResponse],
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_MANAGE))],
)
def list_allowed_agents(
    binding_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        agents = svc.list_allowed_agents(db, binding_id, organization.id)
    except EnforcementBindingNotFoundError:
        raise HTTPException(status_code=404, detail="enforcement_binding_not_found")
    return [AllowedAgentResponse(id=str(a.id), name=a.name, status=a.status) for a in agents]


@router.post(
    "/{binding_id}/activate", response_model=BindingResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_PUBLISH))],
)
def activate_binding(
    binding_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        binding = svc.activate_binding(db, binding_id, organization.id)
    except EnforcementBindingNotFoundError:
        raise HTTPException(status_code=404, detail="enforcement_binding_not_found")
    except BindingInvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except BindingValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ConcurrentActivationConflictError as e:
        raise HTTPException(status_code=409, detail=f"concurrent_activation_conflict: {e}")
    return _binding_to_response(db, binding)


@router.post(
    "/{binding_id}/retire", response_model=BindingResponse,
    dependencies=[Depends(require_permission(Permission.INTEGRATION_CONTRACT_PUBLISH))],
)
def retire_binding(
    binding_id: uuid.UUID, db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    try:
        binding = svc.retire_binding(db, binding_id, organization.id)
    except EnforcementBindingNotFoundError:
        raise HTTPException(status_code=404, detail="enforcement_binding_not_found")
    except BindingInvalidTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _binding_to_response(db, binding)
