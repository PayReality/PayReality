"""Phase 5, Release 1: the HTTP surface for the Authority Model's org
hierarchy (PHASE_1_AUTHORITY_MODEL.md's BusinessUnit/Department/Team),
which has existed as real, correctly-modeled tables since Phase 1 but
had no authoring surface at all -- the first of the two remaining
architectural discontinuities named in the Phase 4 Chief Product
Architect verdict. Renaming a unit is supported; re-parenting one
(moving a Department to a different BusinessUnit, etc.) is not -- kept
out of scope to stay a lightweight CRUD surface, not new business logic."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CreateBusinessUnitRequest(BaseModel):
    name: str


class UpdateBusinessUnitRequest(BaseModel):
    name: str


class BusinessUnitResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateDepartmentRequest(BaseModel):
    business_unit_id: UUID
    name: str


class UpdateDepartmentRequest(BaseModel):
    name: str


class DepartmentResponse(BaseModel):
    id: UUID
    business_unit_id: UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateTeamRequest(BaseModel):
    department_id: UUID
    name: str


class UpdateTeamRequest(BaseModel):
    name: str


class TeamResponse(BaseModel):
    id: UUID
    department_id: UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}
