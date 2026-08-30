from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CreateIntegrationRequest(BaseModel):
    external_system_label: str


class IntegrationResponse(BaseModel):
    id: str
    organization_id: str
    external_system_label: str
    created_by: str | None
    created_at: datetime


class CreateContractVersionRequest(BaseModel):
    source_operation: str
    canonical_action: str
    resource_path: str | None = None
    fact_subject_path: str | None = None
    amount_path: str | None = None
    currency_path: str | None = None
    context_bindings: dict[str, Any] = {}
    source_schema_fingerprint: str | None = None


class EditContractVersionRequest(BaseModel):
    """Every field optional; only fields the caller actually included in
    the request body are applied (the router reads this via
    `model_dump(exclude_unset=True)`) -- an explicit `null` for an
    optional path still means "clear it," distinct from omitting the
    field entirely, which means "leave unchanged." """

    source_operation: str | None = None
    canonical_action: str | None = None
    resource_path: str | None = None
    fact_subject_path: str | None = None
    amount_path: str | None = None
    currency_path: str | None = None
    context_bindings: dict[str, Any] | None = None
    source_schema_fingerprint: str | None = None


class ApproveContractVersionRequest(BaseModel):
    approver: str


class ContractVersionResponse(BaseModel):
    id: str
    integration_id: str
    organization_id: str
    source_operation: str
    version: int
    canonical_action: str
    resource_path: str | None
    fact_subject_path: str | None
    amount_path: str | None
    currency_path: str | None
    context_bindings: dict[str, Any]
    content_hash: str | None
    source_schema_fingerprint: str | None
    status: str
    created_by: str | None
    created_at: datetime
    validated_at: datetime | None
    approved_by: str | None
    approved_at: datetime | None
    retired_at: datetime | None
