"""Product Experience V3.2, Part C ("Draft with AI"): turns one natural-
language instruction into a structured, validated proposal for the
manual Runtime Policy builder. The central invariant (section 31): AI
interprets and proposes, humans establish authority. Nothing in this
module ever saves, publishes, approves, or activates a RuntimePolicy --
every function here returns a proposal object for the caller (the
router, then the frontend builder) to show as a diff the user must
explicitly apply, exactly the same posture domain/capability/token.py's
own module docstring already established for a different kind of
artifact this platform is careful never to overstate.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Organization
from app.domain.ai_policy_builder.provider import CandidateRuntimePolicy
from app.domain.ai_provider.azure_foundry_provider import AzureAIFoundryProvider
from app.domain.ai_provider.interface import AIProvider
from app.domain.compiler_v2.compiler_v2 import FINANCIAL_VOCABULARY
from app.domain.policy_drafting.schema import TOOL_NAME, build_system_prompt, build_tool_schema, parse_draft_result
from app.services import agent_service, enterprise_system_service
from app.services.ai_policy_builder_service import candidate_to_content


class AIDraftingNotConfiguredError(Exception):
    """Section 46: no fake chatbot ships to a real user. Raised, never
    silently degraded into keyword matching, when no AI provider is
    configured in this environment at all."""


@dataclass(frozen=True)
class UnknownEntity:
    field: str
    value: str


@dataclass(frozen=True)
class DraftProposal:
    """What the router returns to the frontend: the exact fields the
    manual builder's own RuntimePolicyRequest shape needs (section 38 --
    "transformed into a constrained structured proposal matching the
    existing builder schema"), plus what could not be confidently
    resolved. `content` is None whenever `clarifying_question` or any
    `unknown_entities` are present -- the frontend must never let a user
    apply a proposal this service itself flagged as incomplete or
    unverifiable (section 37/47)."""

    content: dict | None
    clarifying_question: str | None
    unknown_entities: tuple[UnknownEntity, ...] = field(default_factory=tuple)
    requires_additional_policies: bool = False
    additional_policies_note: str | None = None
    confidence: float | None = None
    missing_fields: tuple[str, ...] = field(default_factory=tuple)


def _provider() -> AIProvider:
    if settings.azure_ai_foundry_endpoint:
        return AzureAIFoundryProvider()
    raise AIDraftingNotConfiguredError(
        "No AI provider is configured in this environment (AZURE_AI_FOUNDRY_ENDPOINT is unset). "
        "The manual builder remains fully usable without it."
    )


def _validate_entities(
    db: Session, organization_id: uuid.UUID, candidate: CandidateRuntimePolicy, agent_name: str | None
) -> list[UnknownEntity]:
    """Section 37: the model may only reference organisational entities
    that actually exist. Every check here is a real, deterministic
    database/vocabulary lookup -- never something the model itself
    decided (section 47)."""
    unknown: list[UnknownEntity] = []

    if candidate.action not in FINANCIAL_VOCABULARY.known_actions:
        unknown.append(UnknownEntity(field="action", value=candidate.action))

    principals = agent_service.list_principals(db, organization_id)
    if not any(p.name == candidate.principal for p in principals):
        unknown.append(UnknownEntity(field="principal", value=candidate.principal))

    if agent_name:
        agents, _total = agent_service.list_agents(db, organization_id, q=agent_name, limit=50)
        if not any(a.name == agent_name for a, _cert in agents):
            unknown.append(UnknownEntity(field="agent", value=agent_name))

    return unknown


def draft_or_edit(
    db: Session,
    organization: Organization,
    instruction: str,
    current_draft: dict | None,
    provider: AIProvider | None = None,
) -> DraftProposal:
    """Section 34/35: both Draft (current_draft is None) and Edit
    (current_draft is the builder's current RuntimePolicyRequest-shaped
    form state) go through this one function -- an edit is simply a draft
    instruction evaluated with the existing draft as additional context,
    never a structurally different code path a security boundary could
    diverge from. `provider` is injectable (a fake in tests, the real
    factory in production) matching the exact pattern
    AzureFoundryRuntimePolicyExtractionProvider.__init__ already uses."""
    provider = provider or _provider()

    user_content = f"Instruction: {instruction}"
    if current_draft:
        user_content = (
            f"The rule currently being edited (JSON): {current_draft}\n\n"
            f"Apply this instruction to it: {instruction}"
        )

    data = provider.generate_structured(
        system_prompt=build_system_prompt(),
        user_content=user_content,
        json_schema=build_tool_schema(),
        schema_name=TOOL_NAME,
        max_tokens=2048,
    )
    result = parse_draft_result(data)

    if result.proposal is None:
        return DraftProposal(
            content=None,
            clarifying_question=result.clarifying_question,
            requires_additional_policies=result.requires_additional_policies,
            additional_policies_note=result.additional_policies_note,
        )

    unknown_entities = _validate_entities(db, organization.id, result.proposal, result.proposal_agent)
    if unknown_entities:
        return DraftProposal(
            content=None,
            clarifying_question=None,
            unknown_entities=tuple(unknown_entities),
            requires_additional_policies=result.requires_additional_policies,
            additional_policies_note=result.additional_policies_note,
            confidence=result.proposal.confidence,
            missing_fields=result.proposal.missing_fields,
        )

    content = candidate_to_content(result.proposal)
    content["scope"]["agent"] = result.proposal_agent
    content["metadata"]["created_by"] = "draft_with_ai"

    return DraftProposal(
        content=content,
        clarifying_question=None,
        requires_additional_policies=result.requires_additional_policies,
        additional_policies_note=result.additional_policies_note,
        confidence=result.proposal.confidence,
        missing_fields=result.proposal.missing_fields,
    )


def explain(
    db: Session,
    organization: Organization,
    current_draft: dict,
    deterministic_summary: str,
    question: str | None,
    provider: AIProvider | None = None,
) -> str:
    """Section 49: anchored in a real, deterministic description of the
    rule (`deterministic_summary`, the exact same sentence
    describePolicy.ts already renders live in the builder -- computed
    once, in the frontend, and passed through here rather than
    re-implemented a second time in Python, so the two can never drift),
    never the model's own independent reconstruction of what the rule
    means. The model elaborates on a question about already-true
    structured facts; it never re-derives those facts itself."""
    provider = provider or _provider()
    prompt = (
        f"This Runtime Policy, in plain English, is: {deterministic_summary}\n\n"
        f"Structured rule (JSON, the actual source of truth): {current_draft}\n\n"
        f"Question: {question or 'What does this rule mean, in a sentence or two?'}"
    )
    data = provider.generate_structured(
        system_prompt=(
            "You explain an existing, already-decided Runtime Policy to the person reviewing it. "
            "Explain only what the structured rule and plain-English summary given to you actually state. "
            "Never speculate about organisational context you were not given. Be concise: two to four sentences."
        ),
        user_content=prompt,
        json_schema={"type": "object", "properties": {"explanation": {"type": "string"}}, "required": ["explanation"]},
        schema_name="record_explanation",
        max_tokens=512,
    )
    return data.get("explanation", deterministic_summary)
