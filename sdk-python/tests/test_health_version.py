from payreality import Agent


def test_health_calls_the_public_health_endpoint(credentials_path, fake_http_client):
    agent = Agent(credentials_path=credentials_path)
    agent._client = fake_http_client
    fake_http_client.queue_response({"status": "ok"})

    result = agent.health()

    assert result == {"status": "ok"}
    assert fake_http_client.calls[0]["path"] == "/health"
    assert fake_http_client.calls[0]["admin_auth"] is False


def test_version_calls_the_public_version_endpoint(credentials_path, fake_http_client):
    agent = Agent(credentials_path=credentials_path)
    agent._client = fake_http_client
    fake_http_client.queue_response({"version": "0.1.0", "commit": "abc123"})

    result = agent.version()

    assert result["commit"] == "abc123"
    assert fake_http_client.calls[0]["path"] == "/version"
