from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ScopeSchema(BaseModel):
    principal: str
    action: str
    agent: str | None = None
    resource: str | None = None


class ConditionSchema(BaseModel):
    field: str
    operator: str
    value: Any


class ConstraintsSchema(BaseModel):
    delegated_by: str | None = None
    expires: datetime | None = None
    evidence_required: bool = True
    risk_level: str | None = None
    # Authority-as-a-continuous-object, Stage G: read-only in practice --
    # set by promotion (authority_id) and by publish/deploy (mandate_id),
    # never by a client submitting a RuntimePolicyRequest by hand. Present
    # here so _record_to_response's existing **content["constraints"]
    # unpacking surfaces them without a separate response shape.
    authority_id: str | None = None
    mandate_id: str | None = None
    # Phase 5, Release 2 (Enterprise System binding): unlike authority_id/
    # mandate_id above, this one IS client-editable -- a reviewer
    # explicitly declares which registered EnterpriseSystem this policy's
    # allowed action reaches. Never inferred; runtime_policy_service.
    # resolve_enterprise_system only trusts this value once it's
    # confirmed to still reference a real row.
    enterprise_system_id: str | None = None


class MetadataSchema(BaseModel):
    owner: str | None = None
    created_by: str | None = None
    tags: list[str] = []
    # Authority Graph -> RuntimePolicy Compilation Gate (issue #6):
    # additive, read-only in practice (set only by promote_candidate's
    # graph-gated path, never by a client submitting a
    # RuntimePolicyRequest by hand) -- present here so
    # _record_to_response's existing **content["metadata"] unpacking
    # surfaces them without a separate response shape, the same
    # precedent Constraints.authority_id/mandate_id already established.
    source_type: str | None = None
    source_corpus_id: str | None = None
    source_graph_approval_id: str | None = None
    source_graph_version: int | None = None
    source_candidate_id: str | None = None


class RuntimePolicyRequest(BaseModel):
    """The request body for creating or editing a RuntimePolicy. `id` is
    intentionally absent: the server assigns policy_key on create, and
    edit is addressed by policy_key in the URL, not the body (see
    POLICY_STUDIO_ARCHITECTURE.md's API surface)."""

    name: str
    description: str | None = None
    scope: ScopeSchema
    conditions: list[ConditionSchema] = []
    effect: str
    constraints: ConstraintsSchema = ConstraintsSchema()
    metadata: MetadataSchema = MetadataSchema()


class RuntimePolicyResponse(BaseModel):
    policy_key: str
    version: int
    status: str
    name: str
    description: str | None
    scope: ScopeSchema
    conditions: list[ConditionSchema]
    effect: str
    constraints: ConstraintsSchema
    metadata: MetadataSchema
    audit: dict[str, Any] | None
    bundle_id: str | None
    bundle_hash: str | None
    created_at: datetime


class RejectRequest(BaseModel):
    reviewer: str
    reason: str


class ApproveRequest(BaseModel):
    approver: str


class CompilerErrorSchema(BaseModel):
    code: str
    message: str
    policy_id: str | None
    path: str | None


class CompileResponse(BaseModel):
    ok: bool
    errors: list[CompilerErrorSchema]
    bundle_id: str | None
    bundle_hash: str | None


class DryRunRequest(BaseModel):
    principal: str
    action: str
    resource: str | None = None
    context: dict[str, Any] = {}


class DryRunResponse(BaseModel):
    decision: str
    allow: bool
    deny: bool
    requires_review: bool
    evaluated_mandates: list[str]
    review_reason: str | None
    deny_reason: str | None
    evidence_required: bool


class DeployResponse(BaseModel):
    bundle_id: str
    bundle_hash: str
    deployed_at: datetime
    # Authority-as-a-continuous-object, Stage I.5: additive, threaded
    # from DeployOutcome. Null whenever this policy has no resolved
    # Authority behind it.
    authority_id: str | None = None
    mandate_id: str | None = None


class ConditionDiffSchema(BaseModel):
    kind: str
    field: str
    operator: str
    old_value: Any = None
    new_value: Any = None


class AffectedAgentSchema(BaseModel):
    id: str
    name: str


class AffectedPolicySchema(BaseModel):
    policy_key: str
    name: str
    version: int
    status: str
    same_action: bool


class DiffResponse(BaseModel):
    conditions: list[ConditionDiffSchema]
    scope_changed: bool
    effect_changed: bool
    constraints_changed: bool
    affected_agents: list[AffectedAgentSchema]
    affected_policies: list[AffectedPolicySchema]
    risk_impact: str
    risk_reason: str
