"""Claude-backed DiscoveryProvider. Prompt/schema/rendering/validation
live in extraction_shared.py (mirroring domain/ai_policy_builder/
claude_provider.py's own split); this file's only job is "call Claude,
then validate and bound-retry on a malformed response."

Timeout/retry posture deliberately matches domain/ai_policy_builder/
claude_provider.py and domain/ai_authority_builder/claude_provider.py
exactly: neither sibling configures a custom network timeout or a
transport-level retry count, relying entirely on the `anthropic` SDK's
own defaults (a generous default request timeout, plus the SDK's own
built-in retry of transient errors) -- so this provider does the same,
rather than inventing a bound neither sibling actually has.

The bounded retry loop below is a SEPARATE, new concern the brief
explicitly asked for that neither sibling implements: retrying when the
model's response fails strict schema/grounding validation
(extraction_shared.MalformedDiscoveryResponseError), not retrying a
network failure. MAX_ATTEMPTS=2 (one real attempt plus one retry) is a
deliberately small, explicit bound -- never an unbounded retry loop."""

import anthropic

from app.config import settings
from app.domain.decision_intelligence.ai_discovery.extraction_shared import (
    TOOL_NAME,
    MalformedDiscoveryResponseError,
    build_system_prompt,
    build_tool_schema,
    format_cases_for_prompt,
    parse_discovery_response,
)
from app.domain.decision_intelligence.ai_discovery.provider import CaseForDiscovery, DiscoveryResult

MAX_ATTEMPTS = 2


class ClaudeDiscoveryProvider:
    def __init__(self, client: anthropic.Anthropic | None = None):
        self._client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def discover(self, cases: list[CaseForDiscovery]) -> DiscoveryResult:
        valid_case_ids = {c.id for c in cases}
        user_content = format_cases_for_prompt(cases)
        tool = {
            "name": TOOL_NAME,
            "description": (
                "Record every candidate Pattern (and its candidate Questions) you found across the "
                "given cases. Never invent a case_id; every supporting_case_ids entry must come from "
                "the cases you were given."
            ),
            "input_schema": build_tool_schema(),
        }

        last_error: Exception = MalformedDiscoveryResponseError("discovery produced no result")
        for _attempt in range(MAX_ATTEMPTS):
            response = self._client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=4096,
                system=build_system_prompt(),
                tools=[tool],
                tool_choice={"type": "tool", "name": TOOL_NAME},
                messages=[{"role": "user", "content": user_content}],
            )

            tool_input = None
            for block in response.content:
                if block.type == "tool_use":
                    tool_input = block.input
                    break

            if tool_input is None:
                last_error = MalformedDiscoveryResponseError("model response did not call the required tool")
                continue

            try:
                return parse_discovery_response(tool_input, valid_case_ids)
            except MalformedDiscoveryResponseError as e:
                last_error = e
                continue

        raise last_error
