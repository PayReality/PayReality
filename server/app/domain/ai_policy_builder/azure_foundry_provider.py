"""Azure AI Foundry-backed RuntimePolicyExtractionProvider (Milestone 6,
AI_PIPELINE_CONSOLIDATION_REVIEW.md). Implements the exact same
RuntimePolicyExtractionProvider Protocol as
ClaudeRuntimePolicyExtractionProvider and FakeRuntimePolicyExtractionProvider
(domain/ai_policy_builder/provider.py) -- the router and service layer
that call `.extract(document_text)` never know or care which one they got.

Uses the same shared prompt/schema/parsing as the Claude provider
(extraction_shared.py) so both providers are guaranteed to ask for and
interpret candidates identically; the only thing that differs is which
AIProvider does the actual model call. Mirrors
domain/ai_authority_builder/azure_foundry_provider.py's own adapter
exactly, since both now sit on the same shared, vendor-neutral
domain/ai_provider seam -- this is what makes Azure AI Foundry, not
Anthropic, the one canonical AI provider for every AI ingestion pipeline
this platform has.
"""

from app.domain.ai_policy_builder.extraction_shared import TOOL_NAME, build_system_prompt, build_tool_schema, parse_candidates_input
from app.domain.ai_policy_builder.provider import CandidateRuntimePolicy
from app.domain.ai_provider.azure_foundry_provider import AzureAIFoundryProvider
from app.domain.ai_provider.interface import AIProvider


class AzureFoundryRuntimePolicyExtractionProvider:
    def __init__(self, provider: AIProvider | None = None):
        self._provider: AIProvider = provider or AzureAIFoundryProvider()

    def extract(self, document_text: str) -> list[CandidateRuntimePolicy]:
        data = self._provider.generate_structured(
            system_prompt=build_system_prompt(),
            user_content=document_text,
            json_schema=build_tool_schema(),
            schema_name=TOOL_NAME,
            max_tokens=4096,
        )
        return parse_candidates_input(data)
