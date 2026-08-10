"""Phase 5, Release 1: lightweight CRUD over BusinessUnit/Department/Team
-- the existing Authority Model org hierarchy (PHASE_1_AUTHORITY_MODEL.md),
unmodified. No authority logic, no runtime behavior, no principal
resolution: this only lets a reviewer create/rename/remove the rows that
already existed as schema with no way to author them."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import BusinessUnit, Department, Team


class BusinessUnitNotFoundError(Exception):
    pass


class DepartmentNotFoundError(Exception):
    pass


class TeamNotFoundError(Exception):
    pass


class StillReferencedError(Exception):
    """Raised when deleting would violate a foreign key -- a child
    Department/Team, or a Principal, still references this row. The
    database's own FK constraint is what actually catches this; this
    just translates that into a clear application-level error."""


# --- Business Units ---------------------------------------------------

def list_business_units(db: Session, organization_id: uuid.UUID) -> list[BusinessUnit]:
    return list(
        db.scalars(
            select(BusinessUnit)
            .where(BusinessUnit.organization_id == organization_id)
            .order_by(BusinessUnit.name)
        )
    )


def create_business_unit(db: Session, organization_id: uuid.UUID, name: str) -> BusinessUnit:
    unit = BusinessUnit(organization_id=organization_id, name=name)
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return unit


def update_business_unit(db: Session, business_unit_id: uuid.UUID, name: str) -> BusinessUnit:
    unit = db.get(BusinessUnit, business_unit_id)
    if unit is None:
        raise BusinessUnitNotFoundError(str(business_unit_id))
    unit.name = name
    db.commit()
    db.refresh(unit)
    return unit


def delete_business_unit(db: Session, business_unit_id: uuid.UUID) -> None:
    unit = db.get(BusinessUnit, business_unit_id)
    if unit is None:
        raise BusinessUnitNotFoundError(str(business_unit_id))
    db.delete(unit)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise StillReferencedError(str(business_unit_id)) from e


# --- Departments --------------------------------------------------------

def list_departments(db: Session, business_unit_id: uuid.UUID | None = None) -> list[Department]:
    stmt = select(Department).order_by(Department.name)
    if business_unit_id is not None:
        stmt = stmt.where(Department.business_unit_id == business_unit_id)
    return list(db.scalars(stmt))


def create_department(db: Session, business_unit_id: uuid.UUID, name: str) -> Department:
    if db.get(BusinessUnit, business_unit_id) is None:
        raise BusinessUnitNotFoundError(str(business_unit_id))
    department = Department(business_unit_id=business_unit_id, name=name)
    db.add(department)
    db.commit()
    db.refresh(department)
    return department


def update_department(db: Session, department_id: uuid.UUID, name: str) -> Department:
    department = db.get(Department, department_id)
    if department is None:
        raise DepartmentNotFoundError(str(department_id))
    department.name = name
    db.commit()
    db.refresh(department)
    return department


def delete_department(db: Session, department_id: uuid.UUID) -> None:
    department = db.get(Department, department_id)
    if department is None:
        raise DepartmentNotFoundError(str(department_id))
    db.delete(department)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise StillReferencedError(str(department_id)) from e


# --- Teams ----------------------------------------------------------------

def list_teams(db: Session, department_id: uuid.UUID | None = None) -> list[Team]:
    stmt = select(Team).order_by(Team.name)
    if department_id is not None:
        stmt = stmt.where(Team.department_id == department_id)
    return list(db.scalars(stmt))


def create_team(db: Session, department_id: uuid.UUID, name: str) -> Team:
    if db.get(Department, department_id) is None:
        raise DepartmentNotFoundError(str(department_id))
    team = Team(department_id=department_id, name=name)
    db.add(team)
    db.commit()
    db.refresh(team)
    return team


def update_team(db: Session, team_id: uuid.UUID, name: str) -> Team:
    team = db.get(Team, team_id)
    if team is None:
        raise TeamNotFoundError(str(team_id))
    team.name = name
    db.commit()
    db.refresh(team)
    return team


def delete_team(db: Session, team_id: uuid.UUID) -> None:
    team = db.get(Team, team_id)
    if team is None:
        raise TeamNotFoundError(str(team_id))
    db.delete(team)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise StillReferencedError(str(team_id)) from e
