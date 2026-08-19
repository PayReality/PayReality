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


def test_retire_without_registration_raises_configuration_error(credentials_path, fake_http_client):
    agent = Agent(api_key="op-key", credentials_path=credentials_path)
    agent._client = fake_http_client
    with pytest.raises(ConfigurationError):
        agent.retire()


def test_retire_calls_the_retire_endpoint_with_admin_auth(credentials_path, fake_http_client):
    agent = _registered_agent(credentials_path, fake_http_client)
    fake_http_client.queue_response({})

    agent.retire(reason="decommissioned")

    call = fake_http_client.calls[-1]
    assert call["path"] == "/v1/agents/a-1/retire"
    assert call["admin_auth"] is True
    assert call["json"]["reason"] == "decommissioned"


def test_retire_marks_the_local_identity_retired(credentials_path, fake_http_client):
    agent = _registered_agent(credentials_path, fake_http_client)
    fake_http_client.queue_response({})

    retired = agent.retire()

    assert retired.status == "retired"
    assert agent._identity.status == "retired"


def test_authorize_after_retire_fails_locally_without_a_network_call(credentials_path, fake_http_client):
    agent = _registered_agent(credentials_path, fake_http_client)
    fake_http_client.queue_response({})
    agent.retire()
    calls_after_retire = len(fake_http_client.calls)

    with pytest.raises(ConfigurationError):
        agent.authorize(
            principal="Finance Manager",
            operation="Approve",
            resource="Vendor Payment",
            resource_data={"amount": 100},
        )

    # No new HTTP call: rejected locally before ever reaching the network.
    assert len(fake_http_client.calls) == calls_after_retire
