import pytest

from payreality import Agent, crypto
from payreality.configuration import CredentialStore
from payreality.exceptions import ConfigurationError


def _registered_agent(credentials_path, fake_http_client):
    agent = Agent(api_key="op-key", credentials_path=credentials_path)
    agent._client = fake_http_client
    fake_http_client.queue_response([{"id": "p-1", "name": "Finance Manager"}])
    fake_http_client.queue_response({"id": "a-1", "certificate_id": "c-1"})
    fake_http_client.queue_response({})  # activate
    agent.register(name="AP Bot", principal="Finance Manager")
    return agent


def test_rotate_keys_without_registration_raises_configuration_error(credentials_path, fake_http_client):
    agent = Agent(api_key="op-key", credentials_path=credentials_path)
    agent._client = fake_http_client
    with pytest.raises(ConfigurationError):
        agent.rotate_keys()


def test_rotate_keys_uploads_only_the_new_public_key(credentials_path, fake_http_client):
    agent = _registered_agent(credentials_path, fake_http_client)
    old_private_key = agent._private_key
    fake_http_client.queue_response({"id": "c-2", "agent_id": "a-1", "status": "active"})

    new_identity = agent.rotate_keys()

    rotate_call = fake_http_client.calls[-1]
    assert rotate_call["path"] == "/v1/agents/a-1/rotate"
    assert rotate_call["admin_auth"] is True
    assert rotate_call["json"]["new_public_key"].startswith("ed25519:base64:")
    assert old_private_key not in str(rotate_call["json"])

    assert new_identity.certificate_id == "c-2"
    assert new_identity.agent_id == "a-1"
    assert agent._private_key != old_private_key


def test_rotate_keys_re_keys_the_local_credential_store(credentials_path, fake_http_client):
    agent = _registered_agent(credentials_path, fake_http_client)
    old_public_key = crypto.public_key_from_private(agent._private_key)
    fake_http_client.queue_response({"id": "c-2", "agent_id": "a-1", "status": "active"})

    agent.rotate_keys()

    store = CredentialStore(credentials_path)
    assert store.get(old_public_key) is None  # old key's entry is gone
    new_public_key = crypto.public_key_from_private(agent._private_key)
    record = store.get(new_public_key)
    assert record["certificate_id"] == "c-2"


def test_rotate_keys_preserves_principal_and_name(credentials_path, fake_http_client):
    agent = _registered_agent(credentials_path, fake_http_client)
    fake_http_client.queue_response({"id": "c-2", "agent_id": "a-1", "status": "active"})

    new_identity = agent.rotate_keys()

    assert new_identity.principal_id == "p-1"
    assert new_identity.principal_name == "Finance Manager"
    assert new_identity.name == "AP Bot"
