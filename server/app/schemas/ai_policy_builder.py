from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.runtime_policy import ConditionSchema, ConstraintsSchema, MetadataSchema, ScopeSchema


class ProviderStatusResponse(BaseModel):
    """Whether extraction is currently backed by a real LLM (Claude) or
    the deterministic fake provider, so the frontend can be honest about
    which one a given deployment is running."""

    ai_enabled: bool


class CandidateContentSchema(BaseModel):
    """The RuntimePolicyRequest-shaped content stored on a candidate
    (RUNTIME_POLICY_MAPPING.md); reuses Policy Studio's own field schemas
    by import rather than redefining them."""

    name: str
    description: str | None = None
    scope: ScopeSchema
    conditions: list[ConditionSchema] = []
    effect: str
    constraints: ConstraintsSchema = ConstraintsSchema()
    metadata: MetadataSchema = MetadataSchema()


class UploadResponse(BaseModel):
    upload_id: str
    filename: str
    format: str
    status: str
    error: str | None
    uploaded_at: datetime


class GraphGateErrorSchema(BaseModel):
    code: str
    message: str
    path: str | None = None


class GraphReadinessSchema(BaseModel):
    """Authority Graph -> RuntimePolicy Compilation Gate (issue #6): a
    read-only preview of whether promoting this candidate would succeed
    against its corpus's latest approved Authority Graph version, and
    exactly why not if it wouldn't -- computed fresh on every request,
    reusing promote_candidate's own gate check, never a separate
    approximation of it."""

    ready: bool
    errors: list[GraphGateErrorSchema] = []


class CandidateResponse(BaseModel):
    candidate_id: str
    upload_id: str | None = None
    corpus_id: str | None = None
    content: CandidateContentSchema
    confidence: float
    missing_fields: list[str]
    source_excerpt: str | None
    source_location: str | None
    status: str
    promoted_policy_key: str | None
    created_at: datetime
    # None for a standalone (non-corpus) candidate, which has no
    # Authority Graph to be ready or not ready against.
    graph_readiness: GraphReadinessSchema | None = None


class EditCandidateRequest(BaseModel):
    content: CandidateContentSchema


class PromoteCandidateResponse(BaseModel):
    policy_key: str
    version: int
    status: str
    # Authority-as-a-continuous-object, Stage I.4: additive. Non-null only
    # when promote_candidate actually created a real Authority row for
    # this candidate (Stage G); null whenever the candidate has no
    # resolved Authority Builder principal behind it, in which case the
    # policy was created with only the free-text delegated_by, exactly as
    # it always has been.
    authority_id: str | None = None
    # Authority Graph -> RuntimePolicy Compilation Gate (issue #6):
    # additive. Non-null only when this promotion was gated on, and
    # succeeded against, a specific approved Authority Graph version.
    source_graph_approval_id: str | None = None
    source_graph_version: int | None = None


class ValidationErrorSchema(BaseModel):
    field: str
    code: str
    message: str
