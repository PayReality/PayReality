"""The AI Provider Interface (Authority Intelligence Program, Phase 1):
the one seam between Authority Intelligence and any specific LLM vendor.

Nothing above this interface -- the router, the Authority Intelligence
Service, the AuthorityGraphExtractionProvider implementations -- is
allowed to import a vendor SDK type or call a vendor SDK directly.
Everything below it (AzureAIFoundryProvider today; an Anthropic-,
OpenAI-, or local-model-backed implementation later) only has to satisfy
this one method to be a drop-in replacement, per the program's own
architecture: "Authority Intelligence Service -> AI Provider Interface
-> Azure AI Foundry Provider."

The shape is deliberately vendor-neutral rather than modeled on any one
SDK's own request/response format (e.g. Anthropic's "tool_use" blocks):
a system prompt, the content to reason over, a JSON Schema describing
the structured result, and a name for that result -- concepts every
major provider's structured-output/function-calling feature can express,
without this interface committing to any one of their specific wire
formats.
"""

from typing import Protocol


class AIProvider(Protocol):
    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_content: str,
        json_schema: dict,
        schema_name: str,
        max_tokens: int = 8192,
    ) -> dict:
        """Return the model's structured output as a plain dict matching
        json_schema. Implementations must force structured output (tool
        use / function calling / equivalent) rather than asking the model
        to describe JSON in prose and parsing it -- the same reliability
        guarantee domain/ai_authority_builder/claude_provider.py already
        established for this program's one existing caller."""
        ...
