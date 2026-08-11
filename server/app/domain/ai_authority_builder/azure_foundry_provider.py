"""Azure AI Foundry-backed AuthorityGraphExtractionProvider (Authority
Intelligence Program, Phase 1). Implements the exact same
AuthorityGraphExtractionProvider Protocol as
ClaudeAuthorityGraphExtractionProvider and FakeAuthorityGraphExtractionProvider
(domain/ai_authority_builder/provider.py) -- the router and service layer
that call `.extract(corpus_text)` never know or care which one they got.

Uses the same shared prompt/schema/parsing as the Claude provider
(extraction_shared.py) so both providers are guaranteed to ask for and
interpret the same eight categories identically; the only thing that
differs between them is which AIProvider does the actual model call.
"""

from app.domain.ai_authority_builder.extraction_shared import (
    build_system_prompt,
    build_tool_schema,
    parse_graph_input,
)
from app.domain.ai_authority_builder.provider import AuthorityGraph
from app.domain.ai_provider.azure_foundry_provider import AzureAIFoundryProvider
from app.domain.ai_provider.interface import AIProvider

TOOL_NAME = "record_authority_graph"


class AzureFoundryAuthorityGraphExtractionProvider:
    def __init__(self, provider: AIProvider | None = None):
        self._provider: AIProvider = provider or AzureAIFoundryProvider()

    def extract(self, corpus_text: str) -> AuthorityGraph:
        graph_input = self._provider.generate_structured(
            system_prompt=build_system_prompt(),
            user_content=corpus_text,
            json_schema=build_tool_schema(),
            schema_name=TOOL_NAME,
            max_tokens=8192,
        )
        return parse_graph_input(graph_input)
