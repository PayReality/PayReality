from typing import Any

from pydantic import BaseModel


class DraftRequest(BaseModel):
    instruction: str
    # None for a brand-new rule (Draft mode); the builder's own current
    # RuntimePolicyRequest-shaped form state for Edit mode. Never
    # trusted as authoritative on its own -- policy_drafting_service.py
    # only ever reads it as context for the model, and every field in
    # the returned proposal is independently validated.
    current_draft: dict[str, Any] | None = None


class UnknownEntityResponse(BaseModel):
    field: str
    value: str


class DraftResponse(BaseModel):
    proposal: dict[str, Any] | None
    clarifying_question: str | None
    unknown_entities: list[UnknownEntityResponse]
    requires_additional_policies: bool
    additional_policies_note: str | None
    confidence: float | None
    missing_fields: list[str]


class ExplainRequest(BaseModel):
    current_draft: dict[str, Any]
    # Computed once in the frontend by describePolicy.ts, the exact
    # sentence already shown live in the builder -- see
    # policy_drafting_service.explain's own docstring for why this is
    # passed through rather than recomputed server-side.
    deterministic_summary: str
    question: str | None = None


class ExplainResponse(BaseModel):
    explanation: str
