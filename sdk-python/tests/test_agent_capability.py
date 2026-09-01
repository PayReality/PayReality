from payreality import Agent


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


def test_request_capability_from_review_calls_the_post_review_endpoint(credentials_path, fake_http_client):
    agent = Agent(api_key="op-key", organization_id="org-1", credentials_path=credentials_path)
    agent._client = fake_http_client
    fake_http_client.queue_response({"token": "tok-abc", "capability_id": "cap-1", "expires_at": "2026-09-01T00:05:00Z"})

    capability = agent.request_capability_from_review("decision-1", audience="reference-adapter")

    call = fake_http_client.calls[-1]
    assert call["path"] == "/v1/decisions/decision-1/capability-token/from-review"
    assert call["admin_auth"] is True
    assert call["json"] == {"audience": "reference-adapter"}
    assert capability.token == "tok-abc"


def test_request_capability_from_review_passes_ttl_seconds_when_given(credentials_path, fake_http_client):
    agent = Agent(api_key="op-key", organization_id="org-1", credentials_path=credentials_path)
    agent._client = fake_http_client
    fake_http_client.queue_response({"token": "tok-abc", "capability_id": "cap-1", "expires_at": "2026-09-01T00:05:00Z"})

    agent.request_capability_from_review("decision-1", audience="reference-adapter", ttl_seconds=60)

    call = fake_http_client.calls[-1]
    assert call["json"] == {"audience": "reference-adapter", "ttl_seconds": 60}


def test_verify_capability_uses_admin_auth_like_every_other_administrative_call(credentials_path, fake_http_client):
    """Trusted Integration Architecture, Phase 6.1 (Production
    Authorization Assurance, Part B): this endpoint is now tenant-scoped,
    the same as every other administrative call in this class --
    admin_auth's own preference order (a real, organisation-bound
    bearer_token first, the platform Operator Key as a fallback), not a
    hand-rolled Operator-Key-only header. See verify_capability's own
    docstring for the full reasoning."""
    agent = Agent(bearer_token="scoped-api-key", credentials_path=credentials_path)
    agent._client = fake_http_client
    fake_http_client.queue_response(
        {"capability_id": "cap-1", "decision_id": "decision-1", "resource": "supplier:123", "constraints": {}}
    )

    consumed = agent.verify_capability("tok-abc", "reference-adapter", "vendor_payment", "supplier:123", {})

    call = fake_http_client.calls[-1]
    assert call["path"] == "/v1/capability-tokens/verify"
    assert call["admin_auth"] is True
    assert call["json"]["token"] == "tok-abc"
    assert "environment" not in call["json"]
    assert "enforcement_binding_id" not in call["json"]
    assert consumed.decision_id == "decision-1"


def test_verify_capability_also_works_with_the_operator_key_fallback(credentials_path, fake_http_client):
    """The Operator Key still works here -- admin_auth=True's own
    documented fallback, preserved deliberately, not silently broken."""
    agent = Agent(api_key="op-key", organization_id="org-1", credentials_path=credentials_path)
    agent._client = fake_http_client
    fake_http_client.queue_response(
        {"capability_id": "cap-1", "decision_id": "decision-1", "resource": "supplier:123", "constraints": {}}
    )

    consumed = agent.verify_capability("tok-abc", "reference-adapter", "vendor_payment", "supplier:123", {})

    call = fake_http_client.calls[-1]
    assert call["admin_auth"] is True
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
