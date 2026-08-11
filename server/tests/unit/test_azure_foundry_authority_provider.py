"""Unit tests for AzureFoundryAuthorityGraphExtractionProvider (Authority
Intelligence Program, Phase 1): confirms it implements the exact same
AuthorityGraphExtractionProvider contract as
ClaudeAuthorityGraphExtractionProvider and FakeAuthorityGraphExtractionProvider,
via an injected fake AIProvider -- no network call, no real Azure AI
Foundry deployment needed for this file."""

from app.domain.ai_authority_builder.azure_foundry_provider import (
    AzureFoundryAuthorityGraphExtractionProvider,
)
from app.domain.ai_authority_builder.extraction_shared import TOOL_NAME


class _FakeAIProvider:
    def __init__(self, graph_input: dict):
        self._graph_input = graph_input
        self.calls = []

    def generate_structured(self, *, system_prompt, user_content, json_schema, schema_name, max_tokens=8192):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_content": user_content,
                "json_schema": json_schema,
                "schema_name": schema_name,
                "max_tokens": max_tokens,
            }
        )
        return self._graph_input


_SAMPLE_GRAPH_INPUT = {
    "policies": [],
    "principals": [
        {
            "name": "CFO",
            "role": "Finance",
            "reports_to": None,
            "confidence": 0.9,
            "source_excerpt": "The CFO may approve.",
            "source_location": "FILE: memo.txt, page 1",
        }
    ],
    "resources": [],
    "operations": [],
    "relationships": [],
    "conflicts": [],
    "gaps": [],
    "questions": [],
}


def test_extract_returns_an_authority_graph_built_from_the_providers_result():
    provider = AzureFoundryAuthorityGraphExtractionProvider(_FakeAIProvider(_SAMPLE_GRAPH_INPUT))

    graph = provider.extract("some corpus text")

    assert len(graph.principals) == 1
    assert graph.principals[0].name == "CFO"
    assert graph.principals[0].source_excerpt == "The CFO may approve."


def test_extract_asks_for_the_same_tool_name_the_schema_defines():
    fake = _FakeAIProvider(_SAMPLE_GRAPH_INPUT)
    provider = AzureFoundryAuthorityGraphExtractionProvider(fake)

    provider.extract("corpus text")

    assert fake.calls[0]["schema_name"] == TOOL_NAME
    assert fake.calls[0]["user_content"] == "corpus text"
    assert "known_actions" not in fake.calls[0]["system_prompt"]  # already interpolated, not a raw template


def test_extract_produces_the_same_shape_claude_and_fake_providers_produce():
    """Cross-provider consistency: given the same structured dict, every
    AuthorityGraphExtractionProvider implementation must produce an
    identical AuthorityGraph -- the whole point of sharing
    extraction_shared.parse_graph_input across them."""
    from app.domain.ai_authority_builder.extraction_shared import parse_graph_input

    expected = parse_graph_input(_SAMPLE_GRAPH_INPUT)
    actual = AzureFoundryAuthorityGraphExtractionProvider(_FakeAIProvider(_SAMPLE_GRAPH_INPUT)).extract("x")

    assert actual == expected


def test_azure_foundry_provider_schema_has_no_rego_or_deploy_field():
    """Same structural guarantee test_ai_authority_builder.py already
    checks on the dataclasses -- here confirmed against the actual JSON
    Schema this provider sends to the model, so the guarantee holds at
    the wire level too, not only in the Python types."""
    from app.domain.ai_authority_builder.extraction_shared import build_tool_schema

    schema_str = str(build_tool_schema()).lower()
    assert "rego" not in schema_str
    assert "deploy" not in schema_str
