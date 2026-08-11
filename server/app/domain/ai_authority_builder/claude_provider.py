"""Claude-backed AuthorityGraphExtractionProvider. One forced tool-use
call per corpus, extending domain/ai_policy_builder/claude_provider.py's
pattern (and its structural "never generates Rego, never deploys"
guarantee: no field in this schema, across any of the eight categories,
is a Rego field, a code field, or a deploy/activate instruction) to
the full Authority Graph.

Authority Intelligence Program, Phase 1: the prompt, tool schema, and
result-parsing logic that used to live in this file are now shared with
domain/ai_authority_builder/azure_foundry_provider.py via
extraction_shared.py, so a second provider never has to duplicate them.
This class's own behavior -- what it asks the model, how it authenticates
(still a direct Anthropic API key, unchanged), and what it returns -- is
otherwise identical to before this extraction.
"""

import anthropic

from app.config import settings
from app.domain.ai_authority_builder.extraction_shared import (
    TOOL_NAME,
    build_system_prompt,
    build_tool_schema,
    parse_graph_input,
)
from app.domain.ai_authority_builder.provider import AuthorityGraph


class ClaudeAuthorityGraphExtractionProvider:
    def __init__(self, client: anthropic.Anthropic | None = None):
        self._client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def extract(self, corpus_text: str) -> AuthorityGraph:
        tool = {"name": TOOL_NAME, "description": "Record everything discovered about this organisation's authority structure across the whole corpus.", "input_schema": build_tool_schema()}

        response = self._client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=8192,
            system=build_system_prompt(),
            tools=[tool],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": corpus_text}],
        )

        graph_input = {}
        for block in response.content:
            if block.type == "tool_use":
                graph_input = block.input
                break

        return parse_graph_input(graph_input)
