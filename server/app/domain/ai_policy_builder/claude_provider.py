"""Claude-backed RuntimePolicyExtractionProvider. Prompt/schema/parsing
now live in extraction_shared.py (Milestone 6), shared with
azure_foundry_provider.py -- this file's only remaining job is "call
Claude," matching domain/ai_authority_builder's own provider split.
"""

import anthropic

from app.config import settings
from app.domain.ai_policy_builder.extraction_shared import TOOL_NAME, build_system_prompt, build_tool_schema, parse_candidates_input
from app.domain.ai_policy_builder.provider import CandidateRuntimePolicy


class ClaudeRuntimePolicyExtractionProvider:
    def __init__(self, client: anthropic.Anthropic | None = None):
        self._client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def extract(self, document_text: str) -> list[CandidateRuntimePolicy]:
        tool = {
            "name": TOOL_NAME,
            "description": "Record every candidate Runtime Policy found in the document, each tagged with its source location and your own confidence in it.",
            "input_schema": build_tool_schema(),
        }
        response = self._client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            system=build_system_prompt(),
            tools=[tool],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": document_text}],
        )

        candidates: list[CandidateRuntimePolicy] = []
        for block in response.content:
            if block.type == "tool_use":
                candidates.extend(parse_candidates_input(block.input))
        return candidates
