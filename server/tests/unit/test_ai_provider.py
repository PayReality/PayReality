"""Unit tests for the AI Provider Interface (Authority Intelligence
Program, Phase 1): AzureAIFoundryProvider's request/response translation,
tested with an injected fake client -- the same dependency-injection
pattern every provider in this codebase already uses (no mocking
library, matching this test suite's own house style). The live call
against a real Azure AI Foundry deployment is verified against the real
deployed resource instead, the same split test_ai_authority_builder.py's
own docstring already establishes for its DB-dependent parts."""

import json

from app.domain.ai_provider.azure_foundry_provider import (
    AzureAIFoundryProvider,
    AzureFoundryProviderError,
)


class _FakeFunctionCall:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, function: _FakeFunctionCall):
        self.function = function


class _FakeMessage:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, message: _FakeMessage):
        self.message = message


class _FakeResponse:
    def __init__(self, choices):
        self.choices = choices


class _FakeChatCompletionsClient:
    """Records exactly what it was called with, returns a scripted
    response -- the same "hand-built fake, not a mock" pattern
    ClaudeAuthorityGraphExtractionProvider's own tests would use if they
    existed (they don't; this is the first)."""

    def __init__(self, response=None):
        self.calls = []
        self._response = response

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


def _response_with_tool_call(name: str, arguments: dict) -> _FakeResponse:
    return _FakeResponse(
        choices=[_FakeChoice(_FakeMessage([_FakeToolCall(_FakeFunctionCall(name, json.dumps(arguments)))]))]
    )


def test_generate_structured_returns_the_forced_tool_calls_arguments():
    client = _FakeChatCompletionsClient(
        response=_response_with_tool_call("record_thing", {"found": ["a", "b"]})
    )
    provider = AzureAIFoundryProvider(client=client)

    result = provider.generate_structured(
        system_prompt="system",
        user_content="content",
        json_schema={"type": "object"},
        schema_name="record_thing",
    )

    assert result == {"found": ["a", "b"]}


def test_generate_structured_forces_the_named_tool_via_tool_choice():
    client = _FakeChatCompletionsClient(response=_response_with_tool_call("record_thing", {}))
    provider = AzureAIFoundryProvider(client=client)

    provider.generate_structured(
        system_prompt="s", user_content="c", json_schema={"type": "object"}, schema_name="record_thing"
    )

    assert client.calls[0]["tool_choice"] == {"type": "function", "function": {"name": "record_thing"}}
    assert client.calls[0]["tools"][0]["function"]["name"] == "record_thing"
    assert client.calls[0]["tools"][0]["function"]["parameters"] == {"type": "object"}


def test_generate_structured_raises_if_the_model_never_calls_the_tool():
    """An extraction with no result is an error, not a valid empty
    result -- the same posture claude_provider.py already takes when
    Anthropic doesn't return a tool_use block."""
    client = _FakeChatCompletionsClient(response=_FakeResponse(choices=[_FakeChoice(_FakeMessage([]))]))
    provider = AzureAIFoundryProvider(client=client)

    try:
        provider.generate_structured(
            system_prompt="s", user_content="c", json_schema={}, schema_name="record_thing"
        )
        assert False, "expected AzureFoundryProviderError"
    except AzureFoundryProviderError:
        pass
