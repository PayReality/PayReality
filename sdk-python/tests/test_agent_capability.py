import pytest

from payreality import Agent
from payreality.exceptions import ConfigurationError


def test_request_capability_calls_the_issuance_endpoint_with_admin_auth(credentials_path, fake_http_client):
    agent = Agent(api_key="op-key", organization_id="org-1", credentials_path=credentials_path)
    agent._client = fake_http_client
    fake_http_client.queue_response({"token": "tok-abc", "capability_id": "cap-1", "expires_at": "2026-09-01T00:05:00Z"})

    capability = agent.request_capability("decision-1", audience="reference-adapter")

    call = fake_http_client.calls[-1]
    assert call["path"] == "/v1/decisions/decision-1/capability-token"
    assert call["admin_auth"] is True
    assert call["json"] == {"audience": "reference-adapter"}
    assert capability.token == "tok-abc"
    assert capability.capability_id == "cap-1"


def test_request_capability_passes_ttl_seconds_when_given(credentials_path, fake_http_client):
    agent = Agent(api_key="op-key", organization_id="org-1", credentials_path=credentials_path)
    agent._client = fake_http_client
    fake_http_client.queue_response({"token": "tok-abc", "capability_id": "cap-1", "expires_at": "2026-09-01T00:05:00Z"})

    agent.request_capability("decision-1", audience="reference-adapter", ttl_seconds=60)

    call = fake_http_client.calls[-1]
    assert call["json"] == {"audience": "reference-adapter", "ttl_seconds": 60}


def test_verify_capability_requires_api_key_not_bearer_token(credentials_path, fake_http_client):
    """Unlike every other administrative call, /v1/capability-tokens/verify
    accepts only the Operator Key, never a bearer_token -- this must be
    rejected locally, before any network call, exactly like retire()
    without registration."""
    agent = Agent(bearer_token="session-token-only", credentials_path=credentials_path)
    agent._client = fake_http_client

    with pytest.raises(ConfigurationError):
        agent.verify_capability("tok-abc", "reference-adapter", "vendor_payment", "supplier:123", {})

    assert fake_http_client.calls == []


def test_verify_capability_sends_the_operator_key_header_directly(credentials_path, fake_http_client):
    agent = Agent(api_key="op-key", credentials_path=credentials_path)
    agent._client = fake_http_client
    fake_http_client.queue_response(
        {"capability_id": "cap-1", "decision_id": "decision-1", "resource": "supplier:123", "constraints": {}}
    )

    consumed = agent.verify_capability("tok-abc", "reference-adapter", "vendor_payment", "supplier:123", {})

    call = fake_http_client.calls[-1]
    assert call["path"] == "/v1/capability-tokens/verify"
    assert call["admin_auth"] is False
    assert call["headers"] == {"X-PayReality-Operator-Key": "op-key"}
    assert call["json"]["token"] == "tok-abc"
    assert "environment" not in call["json"]
    assert "enforcement_binding_id" not in call["json"]
    assert consumed.decision_id == "decision-1"


def test_verify_capability_includes_optional_binding_fields_only_when_given(credentials_path, fake_http_client):
    agent = Agent(api_key="op-key", credentials_path=credentials_path)
    agent._client = fake_http_client
    fake_http_client.queue_response(
        {"capability_id": "cap-1", "decision_id": "decision-1", "resource": "supplier:123", "constraints": {}}
    )

    agent.verify_capability(
        "tok-abc", "reference-adapter", "vendor_payment", "supplier:123", {},
        environment="production", enforcement_binding_id="binding-1",
    )

    call = fake_http_client.calls[-1]
    assert call["json"]["environment"] == "production"
    assert call["json"]["enforcement_binding_id"] == "binding-1"
