import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Principal
from app.db.session import get_db
from app.dependencies import require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.agent import (
    CreatePrincipalRequest,
    PrincipalAuthorityContextResponse,
    PrincipalResponse,
)
from app.services import agent_service
from app.services.authority_context_service import resolve_runtime_authority_context

router = APIRouter(prefix="/v1/principals", tags=["principals"])


@router.post(
    "",
    response_model=PrincipalResponse,
    status_code=201,
    dependencies=[Depends(require_permission(Permission.PRINCIPAL_MANAGE))],
)
def create_principal(body: CreatePrincipalRequest, db: Session = Depends(get_db)):
    principal = agent_service.create_principal(
        db,
        name=body.name,
        role=body.role,
        organization_id=body.organization_id,
        business_unit_id=body.business_unit_id,
        department_id=body.department_id,
        team_id=body.team_id,
    )
    return principal


@router.get("", response_model=list[PrincipalResponse])
def list_principals(db: Session = Depends(get_db)):
    return agent_service.list_principals(db)


@router.get(
    "/{principal_id}/authority-context",
    response_model=PrincipalAuthorityContextResponse,
    dependencies=[Depends(require_permission(Permission.AGENT_VIEW))],
)
def get_principal_authority_context(principal_id: uuid.UUID, db: Session = Depends(get_db)):
    """Authority-as-a-continuous-object, Stage I.9: exposes the exact
    same resolve_runtime_authority_context every Intent already calls,
    read-only and identity-only (no `amount`, so no risk_level -- that's
    an Intent-time concept, not a Principal identity one). Adapts the
    existing service by calling it, never a second implementation of
    authority resolution."""
    principal = db.get(Principal, principal_id)
    if principal is None:
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
