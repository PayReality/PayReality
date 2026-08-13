"""Unit tests for AzureFoundryRuntimePolicyExtractionProvider (Milestone
6, AI_PIPELINE_CONSOLIDATION_REVIEW.md): confirms it implements the exact
same RuntimePolicyExtractionProvider contract as
ClaudeRuntimePolicyExtractionProvider and FakeRuntimePolicyExtractionProvider,
via an injected fake AIProvider -- no network call, no real Azure AI
Foundry deployment needed for this file. Mirrors
test_azure_foundry_authority_provider.py's own structure exactly."""

from app.domain.ai_policy_builder.azure_foundry_provider import AzureFoundryRuntimePolicyExtractionProvider
from app.domain.ai_policy_builder.extraction_shared import TOOL_NAME, build_tool_schema, parse_candidates_input


class _FakeAIProvider:
    def __init__(self, data: dict):
        self._data = data
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
        return self._data


_SAMPLE_CANDIDATES_INPUT = {
    "candidates": [
        {
            "name": "Regional Controller vendor payment approval",
            "principal": "Regional Controller",
            "action": "vendor_payment",
            "effect": "allow",
            "confidence": 0.95,
            "source_excerpt": "The Regional Controller may approve vendor payments up to $50,000.",
            "source_location": "FILE: memo.txt, page 1",
            "conditions": [{"field": "amount", "operator": "<=", "value": 50000}],
        }
    ]
}


def test_extract_returns_candidates_built_from_the_providers_result():
    provider = AzureFoundryRuntimePolicyExtractionProvider(_FakeAIProvider(_SAMPLE_CANDIDATES_INPUT))

    candidates = provider.extract("some document text")

    assert len(candidates) == 1
    assert candidates[0].name == "Regional Controller vendor payment approval"
    assert candidates[0].principal == "Regional Controller"
    assert candidates[0].conditions[0].value == 50000


def test_extract_asks_for_the_same_tool_name_the_schema_defines():
    fake = _FakeAIProvider(_SAMPLE_CANDIDATES_INPUT)
    provider = AzureFoundryRuntimePolicyExtractionProvider(fake)

    provider.extract("document text")

    assert fake.calls[0]["schema_name"] == TOOL_NAME
    assert fake.calls[0]["user_content"] == "document text"
    assert fake.calls[0]["json_schema"] == build_tool_schema()


def test_extract_produces_the_same_shape_claude_and_fake_providers_produce():
    """Cross-provider consistency: given the same structured dict, every
    RuntimePolicyExtractionProvider implementation must produce
    identical candidates -- the whole point of sharing
    extraction_shared.parse_candidates_input across them."""
    expected = parse_candidates_input(_SAMPLE_CANDIDATES_INPUT)
    actual = AzureFoundryRuntimePolicyExtractionProvider(_FakeAIProvider(_SAMPLE_CANDIDATES_INPUT)).extract("x")

    assert actual == expected


def test_policy_builder_schema_has_no_rego_or_deploy_field():
    """Same structural guarantee the Authority Builder schema is already
    checked against -- confirmed here at the wire level for the Policy
    Builder schema too."""
    schema_str = str(build_tool_schema()).lower()
    assert "rego" not in schema_str
    assert "deploy" not in schema_str


def test_provider_selection_prefers_foundry_over_claude_and_fake():
    """routers/ai_policy_builder.py::_provider()'s own ordering,
    exercised directly rather than through the router, mirroring
    routers/ai_authority_builder.py's already-established precedent."""
    from app.config import settings
    from app.routers.ai_policy_builder import _provider
    from app.domain.ai_policy_builder.azure_foundry_provider import AzureFoundryRuntimePolicyExtractionProvider
    from app.domain.ai_policy_builder.claude_provider import ClaudeRuntimePolicyExtractionProvider
    from app.domain.ai_policy_builder.fake_provider import FakeRuntimePolicyExtractionProvider

    original_foundry = settings.azure_ai_foundry_endpoint
    original_anthropic = settings.anthropic_api_key
    try:
        settings.azure_ai_foundry_endpoint = "https://example-foundry.openai.azure.com"
        settings.anthropic_api_key = "sk-something"
        assert isinstance(_provider(), AzureFoundryRuntimePolicyExtractionProvider)

        settings.azure_ai_foundry_endpoint = ""
        assert isinstance(_provider(), ClaudeRuntimePolicyExtractionProvider)

        settings.anthropic_api_key = ""
        assert isinstance(_provider(), FakeRuntimePolicyExtractionProvider)
    finally:
        settings.azure_ai_foundry_endpoint = original_foundry
        settings.anthropic_api_key = original_anthropic
