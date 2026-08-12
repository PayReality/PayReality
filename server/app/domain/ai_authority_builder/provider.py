"""AuthorityGraphExtractionProvider interface: the AI Authority Builder's
extension of domain/ai_policy_builder/provider.py's vendor-neutrality
pattern to a full Authority Graph (AI_AUTHORITY_BUILDER_ARCHITECTURE.md).
CandidateRuntimePolicy is imported and reused unchanged for the one
category both systems share; everything else here is new.

Explainability Model (Authority Intelligence Program, Phase 3,
EXPLAINABILITY_MODEL.md): `clause_reference`, `extraction_reasoning`,
`detected_assumptions`, and `ambiguity_flags` are first-class fields on
every entity/relationship candidate below, populated by the model itself
(extraction_shared.py's tool schema), never inferred or hidden inside a
free-form LLM response. All four are additive and default to
null/empty -- any existing caller that doesn't know about them
(AI Policy Builder's own, unrelated extraction path for the one dataclass
these two systems share, CandidateRuntimePolicy) is unaffected."""

from dataclasses import dataclass, field
from typing import Protocol

from app.domain.ai_policy_builder.provider import CandidateRuntimePolicy


@dataclass(frozen=True)
class CandidatePrincipal:
    name: str
    confidence: float
    source_excerpt: str
    source_location: str
    role: str | None = None
    reports_to: str | None = None
    clause_reference: str | None = None
    extraction_reasoning: str | None = None
    detected_assumptions: tuple[str, ...] = field(default_factory=tuple)
    ambiguity_flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CandidateResource:
    name: str
    confidence: float
    source_excerpt: str
    source_location: str
    description: str | None = None
    clause_reference: str | None = None
    extraction_reasoning: str | None = None
    detected_assumptions: tuple[str, ...] = field(default_factory=tuple)
    ambiguity_flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CandidateOperation:
    name: str
    confidence: float
    source_excerpt: str
    source_location: str
    description: str | None = None
    clause_reference: str | None = None
    extraction_reasoning: str | None = None
    detected_assumptions: tuple[str, ...] = field(default_factory=tuple)
    ambiguity_flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CandidateRelationship:
    """kind is one of delegation/escalation/inheritance
    (AI_AUTHORITY_BUILDER_ARCHITECTURE.md); enforced by the DB check
    constraint, not re-validated as an enum here."""

    kind: str
    from_principal: str
    to_principal: str
    confidence: float
    source_excerpt: str
    source_location: str
    description: str | None = None
    clause_reference: str | None = None
    extraction_reasoning: str | None = None
    detected_assumptions: tuple[str, ...] = field(default_factory=tuple)
    ambiguity_flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CandidateConflict:
    """Model-reported, never a formal proof. No source citation: a
    conflict is a relationship between two or more other findings, not a
    single passage in the source text.

    `conflict_type` (Phase 3): one of authority/threshold/role/policy/
    delegation/circular_delegation -- see EXPLAINABILITY_MODEL.md's
    Conflict Workspace section. `circular_delegation` conflicts are
    additionally, independently detected by deterministic graph analysis
    (ai_authority_builder_service.detect_circular_delegations) -- the
    model may also notice and report one directly; both paths writing the
    same conflict is redundant confirmation, not a bug.
    `reviewer_recommendation` is never asked of the model -- it is
    computed deterministically in Python from conflict_type/confidence
    (see the same service module), per Phase 3's own security principle
    that only deterministic evidence is stored, never a second, hidden
    round of AI judgment."""

    description: str
    confidence: float
    reasoning: str | None = None
    conflict_type: str | None = None
    reviewer_recommendation: str | None = None


@dataclass(frozen=True)
class CandidateGap:
    description: str
    confidence: float
    source_excerpt: str | None = None
    source_location: str | None = None


@dataclass(frozen=True)
class CandidateQuestion:
    """Not confidence-scored: a question is a request for information,
    not a claim to be confident or unconfident about."""

    question: str
    context: str | None = None


@dataclass(frozen=True)
class AuthorityGraph:
    """The full extraction result for one corpus: every category the
    directive asked for, held to the same confidence/citation standard
    the AI Policy Builder already established for its one category."""

    policies: tuple[CandidateRuntimePolicy, ...] = field(default_factory=tuple)
    principals: tuple[CandidatePrincipal, ...] = field(default_factory=tuple)
    resources: tuple[CandidateResource, ...] = field(default_factory=tuple)
    operations: tuple[CandidateOperation, ...] = field(default_factory=tuple)
    relationships: tuple[CandidateRelationship, ...] = field(default_factory=tuple)
    conflicts: tuple[CandidateConflict, ...] = field(default_factory=tuple)
    gaps: tuple[CandidateGap, ...] = field(default_factory=tuple)
    questions: tuple[CandidateQuestion, ...] = field(default_factory=tuple)


class AuthorityGraphExtractionProvider(Protocol):
    def extract(self, corpus_text: str) -> AuthorityGraph: ...
