from payreality import Agent
from payreality.configuration import CredentialStore


def _agent(credentials_path, fake_http_client, private_key=None):
    agent = Agent(api_key="op-key", private_key=private_key, credentials_path=credentials_path)
    agent._client = fake_http_client  # bypass real HTTP entirely
    return agent


def test_register_creates_principal_if_it_does_not_exist(credentials_path, fake_http_client):
    agent = _agent(credentials_path, fake_http_client)
    fake_http_client.queue_response([])  # GET /v1/principals: none exist yet
    fake_http_client.queue_response({"id": "p-1", "name": "Finance Manager"})  # POST /v1/principals
    fake_http_client.queue_response({"id": "a-1", "certificate_id": "c-1"})  # POST /v1/agents
    fake_http_client.queue_response({})  # POST /v1/agents/a-1/activate

    result = agent.register(name="AP Bot", principal="Finance Manager")

    assert result.agent_id == "a-1"
    assert result.certificate_id == "c-1"
    assert result.principal_id == "p-1"
    assert result.principal_name == "Finance Manager"
    assert result.status == "active"
    assert agent.is_registered is True

    principal_list_call = fake_http_client.calls[0]
    assert principal_list_call["path"] == "/v1/principals"
    # PayReality Enterprise v1.0 (Milestone 1) gated this GET behind an
    # organization/permission check; this call previously sent no
    # credentials at all and 401'd on every real deployment.
    assert principal_list_call["operator_auth"] is True

    principal_create_call = fake_http_client.calls[1]
    assert principal_create_call["path"] == "/v1/principals"
    assert principal_create_call["operator_auth"] is True

    agent_create_call = fake_http_client.calls[2]
    assert agent_create_call["path"] == "/v1/agents"
    assert agent_create_call["json"]["acting_for_principal_id"] == "p-1"
    assert agent_create_call["json"]["public_key"].startswith("ed25519:base64:")
    assert agent_create_call["operator_auth"] is True

    activate_call = fake_http_client.calls[3]
    assert activate_call["path"] == "/v1/agents/a-1/activate"
    assert activate_call["operator_auth"] is True


def test_register_reuses_existing_principal_by_name(credentials_path, fake_http_client):
    agent = _agent(credentials_path, fake_http_client)
    fake_http_client.queue_response([{"id": "p-9", "name": "Finance Manager"}])  # already exists
    fake_http_client.queue_response({"id": "a-1", "certificate_id": "c-1"})
    fake_http_client.queue_response({})  # activate

    result = agent.register(name="AP Bot", principal="Finance Manager")

    assert result.principal_id == "p-9"
    # 3 calls: list principals, create agent, activate (no principal creation)
    assert len(fake_http_client.calls) == 3


def test_register_persists_private_key_locally_never_sends_it(credentials_path, fake_http_client):
    agent = _agent(credentials_path, fake_http_client)
    fake_http_client.queue_response([{"id": "p-1", "name": "Finance Manager"}])
    fake_http_client.queue_response({"id": "a-1", "certificate_id": "c-1"})
    fake_http_client.queue_response({})  # activate

    agent.register(name="AP Bot", principal="Finance Manager")

    for call in fake_http_client.calls:
        payload = str(call["json"])
        assert agent._private_key not in payload  # private key never appears in any request body

    store = CredentialStore(credentials_path)
    from payreality import crypto

    public_key = crypto.public_key_from_private(agent._private_key)
    record = store.get(public_key)
    assert record["agent_id"] == "a-1"


def test_register_is_idempotent_for_the_same_key(credentials_path, fake_http_client):
    agent = _agent(credentials_path, fake_http_client)
    fake_http_client.queue_response([{"id": "p-1", "name": "Finance Manager"}])
    fake_http_client.queue_response({"id": "a-1", "certificate_id": "c-1"})
    fake_http_client.queue_response({})  # activate
    first = agent.register(name="AP Bot", principal="Finance Manager")

    calls_after_first = len(fake_http_client.calls)
    second = agent.register(name="AP Bot", principal="Finance Manager")

    assert second == first
    assert len(fake_http_client.calls) == calls_after_first  # no new network calls


def test_constructing_agent_with_a_previously_registered_private_key_loads_identity(
    credentials_path, fake_http_client
):
    first_agent = _agent(credentials_path, fake_http_client)
    fake_http_client.queue_response([{"id": "p-1", "name": "Finance Manager"}])
    fake_http_client.queue_response({"id": "a-1", "certificate_id": "c-1"})
    fake_http_client.queue_response({})  # activate
    registered = first_agent.register(name="AP Bot", principal="Finance Manager")

    # A brand new Agent instance, constructed with the same private key,
    # should recognize it was already registered without any network call.
    second_agent = Agent(
        api_key="op-key", private_key=first_agent._private_key, credentials_path=credentials_path
    )
    assert second_agent.is_registered is True
    assert second_agent._identity == registered
