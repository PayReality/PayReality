"""Unit tests for ClaudeDiscoveryProvider's strict response validation
(domain/decision_intelligence/ai_discovery/extraction_shared.py's
DiscoveryResponseModel + parse_discovery_response, and claude_provider.py's
bounded retry loop around them). Uses a hand-built fake Anthropic client,
the same "fake, not a mock" dependency-injection pattern
test_ai_provider.py's own docstring establishes for this codebase (no
mocking library). This never calls the real Anthropic API -- see the
module docstring on why a live call could not be verified this session
(no ANTHROPIC_API_KEY configured)."""

import json

import pytest

from app.domain.decision_intelligence.ai_discovery.claude_provider import ClaudeDiscoveryProvider
from app.domain.decision_intelligence.ai_discovery.extraction_shared import (
    MalformedDiscoveryResponseError,
    parse_discovery_response,
)
from app.domain.decision_intelligence.ai_discovery.provider import CaseForDiscovery


def _case(id, **kw):
    return CaseForDiscovery(
        id=id, facts=kw.get("facts", {}), escalation_reason=kw.get("escalation_reason"),
        human_decision=kw.get("human_decision"), outcome=kw.get("outcome"), status=kw.get("status", "open"),
    )


# --- parse_discovery_response: well-formed and malformed inputs ------------


def test_parse_accepts_a_well_formed_response():
    data = {
        "patterns": [
            {
                "title": "Conflicting decisions on near-identical cases",
                "description": "desc",
                "rationale": "rationale citing C1 and C2",
                "confidence": "high",
                "category": "conflicting_rules",
                "supporting_case_ids": ["C1", "C2"],
                "questions": [
                    {
                        "title": "What should determine this?",
                        "description": "qdesc",
                        "rationale": "qrationale",
                        "supporting_case_ids": ["C1"],
                    }
                ],
            }
        ]
    }
    result = parse_discovery_response(data, valid_case_ids={"C1", "C2"})
    assert len(result.patterns) == 1
    pattern = result.patterns[0]
    assert pattern.confidence == "high"
    assert pattern.supporting_case_ids == ("C1", "C2")
    assert len(pattern.questions) == 1
    assert pattern.questions[0].supporting_case_ids == ("C1",)


def test_parse_accepts_empty_patterns_list_as_a_valid_honest_result():
    result = parse_discovery_response({"patterns": []}, valid_case_ids={"C1"})
    assert result.patterns == ()


def test_parse_rejects_a_response_missing_required_fields():
    data = {"patterns": [{"title": "Missing everything else"}]}
    with pytest.raises(MalformedDiscoveryResponseError):
        parse_discovery_response(data, valid_case_ids={"C1"})


def test_parse_rejects_an_invalid_confidence_value():
    data = {
        "patterns": [
            {
                "title": "t", "description": "d", "rationale": "r",
                "confidence": "extremely-sure",  # not low/medium/high
                "category": "other",
                "supporting_case_ids": ["C1"],
            }
        ]
    }
    with pytest.raises(MalformedDiscoveryResponseError):
        parse_discovery_response(data, valid_case_ids={"C1"})


def test_parse_rejects_an_invalid_category_value():
    data = {
        "patterns": [
            {
                "title": "t", "description": "d", "rationale": "r",
                "confidence": "low", "category": "not_a_real_category",
                "supporting_case_ids": ["C1"],
            }
        ]
    }
    with pytest.raises(MalformedDiscoveryResponseError):
        parse_discovery_response(data, valid_case_ids={"C1"})


def test_parse_rejects_a_pattern_with_no_supporting_cases():
    data = {
        "patterns": [
            {
                "title": "t", "description": "d", "rationale": "r",
                "confidence": "low", "category": "other", "supporting_case_ids": [],
            }
        ]
    }
    with pytest.raises(MalformedDiscoveryResponseError):
        parse_discovery_response(data, valid_case_ids={"C1"})


def test_parse_rejects_a_fabricated_case_id_not_in_the_supplied_case_set():
    """The single most important check here: a model citing a case id it
    was never given must never be silently trusted."""
    data = {
        "patterns": [
            {
                "title": "t", "description": "d", "rationale": "r",
                "confidence": "high", "category": "conflicting_rules",
                "supporting_case_ids": ["C1", "C999-DOES-NOT-EXIST"],
            }
        ]
    }
    with pytest.raises(MalformedDiscoveryResponseError):
        parse_discovery_response(data, valid_case_ids={"C1", "C2"})


def test_parse_rejects_a_question_citing_a_fabricated_case_id():
    data = {
        "patterns": [
            {
                "title": "t", "description": "d", "rationale": "r",
                "confidence": "high", "category": "conflicting_rules", "supporting_case_ids": ["C1"],
                "questions": [
                    {"title": "q", "description": "d", "rationale": "r", "supporting_case_ids": ["GHOST"]}
                ],
            }
        ]
    }
    with pytest.raises(MalformedDiscoveryResponseError):
        parse_discovery_response(data, valid_case_ids={"C1"})


# --- ClaudeDiscoveryProvider: forced tool-use call + bounded retry ----------


class _FakeContentBlock:
    def __init__(self, type_, input_=None):
        self.type = type_
        self.input = input_


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeAnthropicMessages:
    """Records every call; returns one scripted response per call, in
    order -- enough to exercise the bounded retry loop deterministically."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


class _FakeAnthropicClient:
    def __init__(self, responses):
        self.messages = _FakeAnthropicMessages(responses)


def _well_formed_response():
    return _FakeMessage(
        content=[
            _FakeContentBlock(
                "tool_use",
                {
                    "patterns": [
                        {
                            "title": "t", "description": "d", "rationale": "r",
                            "confidence": "medium", "category": "missing_facts",
                            "supporting_case_ids": ["C1", "C2"],
                        }
                    ]
                },
            )
        ]
    )


def _malformed_response():
    return _FakeMessage(
        content=[_FakeContentBlock("tool_use", {"patterns": [{"title": "only a title"}]})]
    )


def test_claude_provider_returns_result_from_a_well_formed_first_response():
    client = _FakeAnthropicClient(responses=[_well_formed_response()])
    provider = ClaudeDiscoveryProvider(client=client)

    result = provider.discover([_case("C1"), _case("C2")])

    assert len(result.patterns) == 1
    assert client.messages.calls[0]["tool_choice"] == {"type": "tool", "name": "record_candidate_discovery_patterns"}
    # Only the five documented fields (plus case_id) are ever sent -- never
    # an organization_id/created_by_user_id/etc, even though CaseForDiscovery
    # itself doesn't carry those fields at all.
    sent_content = client.messages.calls[0]["messages"][0]["content"]
    sent_cases = json.loads(sent_content)
    assert set(sent_cases[0].keys()) == {"case_id", "facts", "escalation_reason", "human_decision", "outcome", "status"}


def test_claude_provider_retries_once_on_a_malformed_response_then_succeeds():
    client = _FakeAnthropicClient(responses=[_malformed_response(), _well_formed_response()])
    provider = ClaudeDiscoveryProvider(client=client)

    result = provider.discover([_case("C1"), _case("C2")])

    assert len(result.patterns) == 1
    assert len(client.messages.calls) == 2  # the first malformed attempt, then one retry


def test_claude_provider_raises_after_exhausting_bounded_retries():
    client = _FakeAnthropicClient(responses=[_malformed_response(), _malformed_response()])
    provider = ClaudeDiscoveryProvider(client=client)

    with pytest.raises(MalformedDiscoveryResponseError):
        provider.discover([_case("C1"), _case("C2")])

    assert len(client.messages.calls) == 2  # never a third, unbounded attempt


def test_claude_provider_treats_a_missing_tool_call_as_malformed_and_retries():
    no_tool_response = _FakeMessage(content=[_FakeContentBlock("text", None)])
    client = _FakeAnthropicClient(responses=[no_tool_response, _well_formed_response()])
    provider = ClaudeDiscoveryProvider(client=client)

    result = provider.discover([_case("C1"), _case("C2")])
    assert len(result.patterns) == 1
