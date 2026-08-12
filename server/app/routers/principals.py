import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization, Principal
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.agent import (
    CreatePrincipalRequest,
    PrincipalAuthorityContextResponse,
    PrincipalResponse,
)
from app.services import agent_service
from app.services.authority_context_service import resolve_runtime_authority_context
from app.services.organization_structure_service import (
    BusinessUnitNotFoundError,
    DepartmentNotFoundError,
    TeamNotFoundError,
)

router = APIRouter(prefix="/v1/principals", tags=["principals"])


@router.post(
    "",
    response_model=PrincipalResponse,
    status_code=201,
    dependencies=[Depends(require_permission(Permission.PRINCIPAL_MANAGE))],
)
def create_principal(
    body: CreatePrincipalRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Milestone 1 (Security & Authorization Hardening): organization_id
    is sourced from the caller's own authenticated organization, never
    from the request body -- CreatePrincipalRequest.organization_id is
    accepted for backward compatibility (existing callers may still send
    it) but is no longer trusted; sending a different organization_id
    than the caller's own has no effect."""
    try:
        principal = agent_service.create_principal(
            db,
            name=body.name,
            organization_id=organization.id,
            role=body.role,
            business_unit_id=body.business_unit_id,
            department_id=body.department_id,
            team_id=body.team_id,
        )
    except BusinessUnitNotFoundError:
        raise HTTPException(status_code=404, detail="business_unit_not_found")
    except DepartmentNotFoundError:
        raise HTTPException(status_code=404, detail="department_not_found")
    except TeamNotFoundError:
        raise HTTPException(status_code=404, detail="team_not_found")
    return principal


@router.get(
    "", response_model=list[PrincipalResponse],
    dependencies=[Depends(require_permission(Permission.AGENT_VIEW))],
)
def list_principals(
    organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)
):
    return agent_service.list_principals(db, organization.id)


@router.get(
    "/{principal_id}/authority-context",
    response_model=PrincipalAuthorityContextResponse,
    dependencies=[Depends(require_permission(Permission.AGENT_VIEW))],
)
def get_principal_authority_context(
    principal_id: uuid.UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """Authority-as-a-continuous-object, Stage I.9: exposes the exact
    same resolve_runtime_authority_context every Intent already calls,
    read-only and identity-only (no `amount`, so no risk_level -- that's
    an Intent-time concept, not a Principal identity one). Adapts the
    existing service by calling it, never a second implementation of
    authority resolution.

    Milestone 1 (Security & Authorization Hardening): org-scoped, same
    class of fix as list_principals above -- found while fixing that
    endpoint, in the same file, so fixed alongside it rather than left
    as a second, adjacent gap."""
    principal = db.get(Principal, principal_id)
    if principal is None or principal.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="principal_not_found")
    context = resolve_runtime_authority_context(db, principal, amount=None)
    return PrincipalAuthorityContextResponse(
        organization=context.get("organization"),
        business_unit=context.get("business_unit"),
        department=context.get("department"),
        team=context.get("team"),
        role=context.get("role"),
        delegations=context.get("delegations", []),
    )
