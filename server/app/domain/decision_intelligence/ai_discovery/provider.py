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
    the pattern's."""

    title: str
    description: str
    rationale: str
    supporting_case_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CandidatePattern:
    """One candidate recurring-uncertainty grouping of cases, with zero or
    more candidate questions that would resolve it. `confidence` is a
    human-readable low/medium/high label, matching DIPattern.confidence's
    own precedent exactly -- never a fabricated statistical score. Every
    shipped provider (fake and Claude) is honest that this is a heuristic/
    model self-report, never a trained model's calibrated confidence."""

    title: str
    description: str
    rationale: str
    confidence: str  # "low" | "medium" | "high"
    supporting_case_ids: tuple[str, ...]
    questions: tuple[CandidateQuestion, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DiscoveryResult:
    patterns: tuple[CandidatePattern, ...] = field(default_factory=tuple)


class DiscoveryProvider(Protocol):
    def discover(self, cases: list[CaseForDiscovery]) -> DiscoveryResult: ...
