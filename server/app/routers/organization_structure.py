import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.rbac.permissions import Permission
from app.schemas.organization_structure import (
    BusinessUnitResponse,
    CreateBusinessUnitRequest,
    CreateDepartmentRequest,
    CreateTeamRequest,
    DepartmentResponse,
    TeamResponse,
    UpdateBusinessUnitRequest,
    UpdateDepartmentRequest,
    UpdateTeamRequest,
)
from app.services import organization_structure_service as svc
from app.services.organization_structure_service import (
    BusinessUnitNotFoundError,
    DepartmentNotFoundError,
    StillReferencedError,
    TeamNotFoundError,
)

business_units_router = APIRouter(prefix="/v1/business-units", tags=["organization-structure"])
departments_router = APIRouter(prefix="/v1/departments", tags=["organization-structure"])
teams_router = APIRouter(prefix="/v1/teams", tags=["organization-structure"])


@business_units_router.get(
    "", response_model=list[BusinessUnitResponse],
    dependencies=[Depends(require_permission(Permission.SETTINGS_VIEW))],
)
def list_business_units(
    organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)
):
    return svc.list_business_units(db, organization.id)


@business_units_router.post(
    "", response_model=BusinessUnitResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.ORGANISATION_MANAGE))],
)
def create_business_unit(
    body: CreateBusinessUnitRequest,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    return svc.create_business_unit(db, organization.id, body.name)


@business_units_router.patch(
    "/{business_unit_id}", response_model=BusinessUnitResponse,
    dependencies=[Depends(require_permission(Permission.ORGANISATION_MANAGE))],
)
def update_business_unit(
    business_unit_id: uuid.UUID, body: UpdateBusinessUnitRequest, db: Session = Depends(get_db)
):
    try:
        return svc.update_business_unit(db, business_unit_id, body.name)
    except BusinessUnitNotFoundError:
        raise HTTPException(status_code=404, detail="business_unit_not_found")


@business_units_router.delete(
    "/{business_unit_id}", status_code=204,
    dependencies=[Depends(require_permission(Permission.ORGANISATION_MANAGE))],
)
def delete_business_unit(business_unit_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        svc.delete_business_unit(db, business_unit_id)
    except BusinessUnitNotFoundError:
        raise HTTPException(status_code=404, detail="business_unit_not_found")
    except StillReferencedError:
        raise HTTPException(
            status_code=409,
            detail="business_unit_still_referenced: remove its Departments and any Principal assigned to it first",
        )


@departments_router.get(
    "", response_model=list[DepartmentResponse],
    dependencies=[Depends(require_permission(Permission.SETTINGS_VIEW))],
)
def list_departments(business_unit_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    return svc.list_departments(db, business_unit_id)


@departments_router.post(
    "", response_model=DepartmentResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.ORGANISATION_MANAGE))],
)
def create_department(body: CreateDepartmentRequest, db: Session = Depends(get_db)):
    try:
        return svc.create_department(db, body.business_unit_id, body.name)
    except BusinessUnitNotFoundError:
        raise HTTPException(status_code=404, detail="business_unit_not_found")


@departments_router.patch(
    "/{department_id}", response_model=DepartmentResponse,
    dependencies=[Depends(require_permission(Permission.ORGANISATION_MANAGE))],
)
def update_department(department_id: uuid.UUID, body: UpdateDepartmentRequest, db: Session = Depends(get_db)):
    try:
        return svc.update_department(db, department_id, body.name)
    except DepartmentNotFoundError:
        raise HTTPException(status_code=404, detail="department_not_found")


@departments_router.delete(
    "/{department_id}", status_code=204,
    dependencies=[Depends(require_permission(Permission.ORGANISATION_MANAGE))],
)
def delete_department(department_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        svc.delete_department(db, department_id)
    except DepartmentNotFoundError:
        raise HTTPException(status_code=404, detail="department_not_found")
    except StillReferencedError:
        raise HTTPException(
            status_code=409,
            detail="department_still_referenced: remove its Teams and any Principal assigned to it first",
        )


@teams_router.get(
    "", response_model=list[TeamResponse],
    dependencies=[Depends(require_permission(Permission.SETTINGS_VIEW))],
)
def list_teams(department_id: uuid.UUID | None = None, db: Session = Depends(get_db)):
    return svc.list_teams(db, department_id)


@teams_router.post(
    "", response_model=TeamResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.ORGANISATION_MANAGE))],
)
def create_team(body: CreateTeamRequest, db: Session = Depends(get_db)):
    try:
        return svc.create_team(db, body.department_id, body.name)
    except DepartmentNotFoundError:
        raise HTTPException(status_code=404, detail="department_not_found")


@teams_router.patch(
    "/{team_id}", response_model=TeamResponse,
    dependencies=[Depends(require_permission(Permission.ORGANISATION_MANAGE))],
)
def update_team(team_id: uuid.UUID, body: UpdateTeamRequest, db: Session = Depends(get_db)):
    try:
        return svc.update_team(db, team_id, body.name)
    except TeamNotFoundError:
        raise HTTPException(status_code=404, detail="team_not_found")


@teams_router.delete(
    "/{team_id}", status_code=204,
    dependencies=[Depends(require_permission(Permission.ORGANISATION_MANAGE))],
)
def delete_team(team_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        svc.delete_team(db, team_id)
    except TeamNotFoundError:
        raise HTTPException(status_code=404, detail="team_not_found")
    except StillReferencedError:
        raise HTTPException(
            status_code=409,
            detail="team_still_referenced: remove any Principal assigned to it first",
        )
