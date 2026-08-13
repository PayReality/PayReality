import json

import pytest

from payreality import Agent
from payreality.exceptions import ConfigurationError


def _registered_agent(credentials_path, fake_http_client):
    agent = Agent(api_key="op-key", credentials_path=credentials_path)
    agent._client = fake_http_client
    fake_http_client.queue_response([{"id": "p-1", "name": "Finance Manager"}])
    fake_http_client.queue_response({"id": "a-1", "certificate_id": "c-1"})
    fake_http_client.queue_response({})  # activate
    agent.register(name="AP Bot", principal="Finance Manager")
    return agent


def test_heartbeat_without_registration_raises_configuration_error(credentials_path, fake_http_client):
    agent = Agent(api_key="op-key", credentials_path=credentials_path)
    agent._client = fake_http_client
    with pytest.raises(ConfigurationError):
        agent.heartbeat()


def test_heartbeat_is_signed_not_operator_authenticated(credentials_path, fake_http_client):
    agent = _registered_agent(credentials_path, fake_http_client)
    fake_http_client.queue_response({"agent_id": "a-1", "last_seen_at": "2026-01-01T00:00:00Z", "health": "healthy"})

    result = agent.heartbeat(version="1.2.3", runtime="Azure Foundry")

    call = fake_http_client.calls[-1]
    assert call["path"] == "/v1/agents/a-1/heartbeat"
    assert call["operator_auth"] is False
    assert call["headers"]["X-PayReality-Key-Id"] == "c-1"
    assert "X-PayReality-Signature" in call["headers"]

    body = json.loads(call["signed_body"])
    assert body["version"] == "1.2.3"
    assert body["runtime"] == "Azure Foundry"
    assert body["sdk_version"].startswith("payreality-python/")

    assert result["health"] == "healthy"


def test_heartbeat_defaults_sdk_version_to_this_package(credentials_path, fake_http_client):
    agent = _registered_agent(credentials_path, fake_http_client)
    fake_http_client.queue_response({"agent_id": "a-1", "last_seen_at": "2026-01-01T00:00:00Z", "health": "healthy"})

    agent.heartbeat()

    body = json.loads(fake_http_client.calls[-1]["signed_body"])
    assert body["sdk_version"] == "payreality-python/0.2.0"
