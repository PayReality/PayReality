"""DiscoveryProvider interface: the AI discovery feature's own vendor-
neutrality boundary, the same shape as
domain/ai_policy_builder/provider.py's RuntimePolicyExtractionProvider and
domain/ai_authority_builder/provider.py's AuthorityGraphExtractionProvider.

`CaseForDiscovery` is the one input shape every provider receives --
`id` is a plain `str` (not `uuid.UUID`), the same discipline
replay_executor.py already holds itself to: domain/ never imports app.db,
so nothing here can or should import DICase; the service layer
(di_discovery_service.py) is the only place that reads a real DICase row
and maps it into this dataclass.

Data-minimization note (brief's own requirement: never send a provider
more than the sibling AI features already consider acceptable): a case's
`organization_id`, `created_by_user_id`, `external_ref`, `evidence_refs`,
`ai_recommendation`, and `outcome_evidence` are deliberately NOT part of
this dataclass. Only the five fields the brief itself named as the
discovery mechanism's input -- facts, escalation_reason, human_decision,
outcome, status -- plus the case's own id (so a suggestion can cite which
cases it's grounded in) ever reach a provider, real or fake."""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class CaseForDiscovery:
    id: str
    facts: dict
    escalation_reason: str | None
    human_decision: dict | None
    outcome: str | None
    status: str


@dataclass(frozen=True)
class CandidateQuestion:
    """One candidate priority question that, if answered, would resolve
    its parent CandidatePattern's uncertainty. Not confidence-scored, the
    same precedent domain/ai_authority_builder/provider.py's
    CandidateQuestion already established and documented: a question is a
    request for information, not a claim to be confident or unconfident
    about. `supporting_case_ids` may be empty when a question is framed at
    the pattern level without citing additional cases of its own beyond
    the pattern's.

    The four fields below exist so a suggestion reads as a specific,
    investigable proposal rather than a bare flag. Every one of them is a
    labelled CANDIDATE, never a settled conclusion -- a provider (fake or
    Claude) populates them only with what the supplied cases actually
    support, and leaves a field empty/generic rather than inventing
    specifics the data doesn't ground:
    - `candidate_explanation`: the single hypothesis this question would
      test, stated as a hypothesis, not a fact.
    - `alternative_explanations`: other plausible causes a reviewer should
      weigh before accepting the candidate_explanation (e.g. a legitimate
      case-specific exception, a data/recording error, a retrieval or
      integration defect, genuine unresolved ambiguity -- never an
      exhaustive or certain list).
    - `missing_evidence`: what isn't in the data today that would help an
      expert actually decide (e.g. "which policy version governed each
      case").
    - `potential_impact`: what an expert's answer might change, in plain
      terms -- never a claim that answering it WILL change anything."""

    title: str
    description: str
    rationale: str
    supporting_case_ids: tuple[str, ...] = field(default_factory=tuple)
    candidate_explanation: str | None = None
    alternative_explanations: tuple[str, ...] = field(default_factory=tuple)
    missing_evidence: tuple[str, ...] = field(default_factory=tuple)
    potential_impact: str | None = None


#: DIPattern.category's own fixed vocabulary (app/db/models.py's
#: ck_di_patterns_category) -- reused verbatim here rather than redefined,
#: since a CandidatePattern's `category` is stored as-is onto the real
#: DIPattern created when a human accepts it.
PATTERN_CATEGORIES = (
    "missing_facts",
    "unclear_policy",
    "conflicting_rules",
    "authority_gap",
    "context_interpretation",
    "human_judgement",
    "other",
)


@dataclass(frozen=True)
class CandidatePattern:
    """One candidate recurring-uncertainty grouping of cases, with zero or
    more candidate questions that would resolve it. `confidence` is a
    human-readable low/medium/high label, matching DIPattern.confidence's
    own precedent exactly -- never a fabricated statistical score. Every
    shipped provider (fake and Claude) is honest that this is a heuristic/
    model self-report, never a trained model's calibrated confidence.

    `category` must be one of PATTERN_CATEGORIES above -- the identical
    vocabulary a human manually creating a Pattern is already constrained
    to, reused as-is for the real DIPattern created on accept.

    `alternative_explanations` reuses DIPattern.alternative_explanations
    (app/db/models.py) verbatim -- that column already existed for a
    human manually creating a Pattern, but no provider ever populated it
    for a discovered one until now. `rationale` continues to map onto
    DIPattern.proposed_explanation as it already did."""

    title: str
    description: str
    rationale: str
    confidence: str  # "low" | "medium" | "high"
    category: str  # one of PATTERN_CATEGORIES
    supporting_case_ids: tuple[str, ...]
    questions: tuple[CandidateQuestion, ...] = field(default_factory=tuple)
    alternative_explanations: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DiscoveryResult:
    patterns: tuple[CandidatePattern, ...] = field(default_factory=tuple)


class DiscoveryProvider(Protocol):
    def discover(self, cases: list[CaseForDiscovery]) -> DiscoveryResult: ...
