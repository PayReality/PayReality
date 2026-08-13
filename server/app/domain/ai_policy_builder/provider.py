"""RuntimePolicyExtractionProvider interface: the AI Policy Builder's own
vendor-neutrality boundary (AI_POLICY_BUILDER_ARCHITECTURE.md). Produces
CandidateRuntimePolicy, for RuntimePolicy candidates.

Milestone 6 (AI_PIPELINE_CONSOLIDATION_REVIEW.md): domain/extraction/,
this protocol's original, never-wired-up sibling for a separate
DoA-document-to-Authority-claim pipeline, was deleted; it had been dead
(zero callers) since Phase 0, per SPECIFICATION/17_LEGACY_COMPONENTS.md's
own prior finding. This module was never coupled to it and needs no
other change as a result.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class CandidateCondition:
    field: str
    operator: str
    value: object


@dataclass(frozen=True)
class CandidateRuntimePolicy:
    """Canonical shape every RuntimePolicyExtractionProvider implementation
    must produce (RUNTIME_POLICY_MAPPING.md), regardless of which model
    generated it. Confidence and missing_fields are the model's own,
    uncalibrated self-report (AI_POLICY_BUILDER_ARCHITECTURE.md's "Honesty
    about what confidence means"), never assumed accurate.

    `clause_reference`/`extraction_reasoning`/`detected_assumptions`/
    `ambiguity_flags` (Authority Intelligence Program, Phase 3,
    EXPLAINABILITY_MODEL.md): additive, default null/empty. Only the AI
    Authority Builder's own extraction path (extraction_shared.py) asks
    the model to populate them today; the original, single-document AI
    Policy Builder provider is unmodified and simply leaves them at their
    defaults -- both providers produce the identical dataclass shape,
    unaffected either way."""

    name: str
    principal: str
    action: str
    effect: str
    confidence: float
    source_excerpt: str
    source_location: str
    resource: str | None = None
    conditions: tuple[CandidateCondition, ...] = field(default_factory=tuple)
    delegated_by: str | None = None
    evidence_required: bool | None = None
    risk_level: str | None = None
    metadata_owner: str | None = None
    metadata_tags: tuple[str, ...] = field(default_factory=tuple)
    missing_fields: tuple[str, ...] = field(default_factory=tuple)
    clause_reference: str | None = None
    extraction_reasoning: str | None = None
    detected_assumptions: tuple[str, ...] = field(default_factory=tuple)
    ambiguity_flags: tuple[str, ...] = field(default_factory=tuple)


class RuntimePolicyExtractionProvider(Protocol):
    def extract(self, document_text: str) -> list[CandidateRuntimePolicy]: ...
