import requests

from payreality.client import HttpClient
from payreality.configuration import Configuration
from payreality.exceptions import ApiError, AuthenticationError, InvalidSignature, NetworkError


def _client(fake_session, **config_kwargs):
    config = Configuration(**config_kwargs)
    return HttpClient(config, session=fake_session)


def test_successful_get_returns_parsed_json(fake_session):
    fake_session.queue_response(200, {"status": "ok"})
    client = _client(fake_session)
    result = client.request("GET", "/health")
    assert result == {"status": "ok"}
    assert fake_session.calls[0]["method"] == "GET"
    assert fake_session.calls[0]["url"].endswith("/health")


def test_empty_2xx_body_returns_empty_dict(fake_session):
    fake_session.queue_response(204, None)
    client = _client(fake_session)
    assert client.request("POST", "/v1/decisions/x/resolve") == {}


def test_admin_auth_attaches_configured_api_key_and_organization_id_headers(fake_session):
    fake_session.queue_response(201, {"id": "a-1"})
    client = _client(fake_session, api_key="secret-op-key", organization_id="org-1")
    client.request("POST", "/v1/agents", json={"name": "x"}, admin_auth=True)
    assert fake_session.calls[0]["headers"]["X-PayReality-Operator-Key"] == "secret-op-key"
    assert fake_session.calls[0]["headers"]["X-PayReality-Organization-Id"] == "org-1"


def test_admin_auth_attaches_configured_bearer_token_as_authorization_header(fake_session):
    fake_session.queue_response(201, {"id": "a-1"})
    client = _client(fake_session, bearer_token="pr_live_abc123")
    client.request("POST", "/v1/agents", json={"name": "x"}, admin_auth=True)
    assert fake_session.calls[0]["headers"]["Authorization"] == "Bearer pr_live_abc123"
    assert "X-PayReality-Operator-Key" not in fake_session.calls[0]["headers"]


def test_admin_auth_bearer_token_needs_no_organization_id(fake_session):
    """Unlike api_key, a bearer_token (session token or scoped API key)
    already resolves to its own organization server-side."""
    fake_session.queue_response(201, {"id": "a-1"})
    client = _client(fake_session, bearer_token="pr_live_abc123")  # no organization_id configured
    client.request("POST", "/v1/agents", json={}, admin_auth=True)
    assert fake_session.calls[0]["headers"]["Authorization"] == "Bearer pr_live_abc123"


def test_admin_auth_prefers_bearer_token_over_api_key_when_both_configured(fake_session):
    fake_session.queue_response(201, {"id": "a-1"})
    client = _client(
        fake_session, bearer_token="pr_live_abc123", api_key="secret-op-key", organization_id="org-1"
    )
    client.request("POST", "/v1/agents", json={}, admin_auth=True)
    assert fake_session.calls[0]["headers"]["Authorization"] == "Bearer pr_live_abc123"
    assert "X-PayReality-Operator-Key" not in fake_session.calls[0]["headers"]


def test_admin_auth_without_any_credential_raises_authentication_error(fake_session):
    client = _client(fake_session)  # neither bearer_token nor api_key configured
    try:
        client.request("POST", "/v1/agents", json={}, admin_auth=True)
        assert False, "expected AuthenticationError"
    except AuthenticationError:
        pass
    assert fake_session.calls == []  # never even attempted the network call


def test_admin_auth_api_key_without_organization_id_raises_authentication_error(fake_session):
    client = _client(fake_session, api_key="secret-op-key")  # no organization_id configured
    try:
        client.request("POST", "/v1/agents", json={}, admin_auth=True)
        assert False, "expected AuthenticationError"
    except AuthenticationError:
        pass
    assert fake_session.calls == []  # never even attempted the network call


def test_signed_body_is_sent_verbatim_not_re_serialized(fake_session):
    fake_session.queue_response(200, {"decision": {}})
    client = _client(fake_session)
    raw = b'{"exact":"bytes"}'
    client.request("POST", "/v1/intents", signed_body=raw, headers={"X-PayReality-Key-Id": "c-1"})
    assert fake_session.calls[0]["data"] == raw
    assert fake_session.calls[0]["headers"]["X-PayReality-Key-Id"] == "c-1"


def test_401_with_signature_in_detail_raises_invalid_signature(fake_session):
    fake_session.queue_response(401, {"detail": "invalid_signature"})
    client = _client(fake_session)
    try:
        client.request("POST", "/v1/intents", json={})
        assert False, "expected InvalidSignature"
    except InvalidSignature as e:
        assert e.status_code == 401


def test_401_without_signature_wording_raises_authentication_error(fake_session):
    fake_session.queue_response(401, {"detail": "invalid_key_id"})
    client = _client(fake_session)
    try:
        client.request("POST", "/v1/intents", json={})
        assert False, "expected AuthenticationError"
    except AuthenticationError:
        pass


def test_403_raises_authentication_error(fake_session):
    fake_session.queue_response(403, {"detail": "agent_revoked"})
    client = _client(fake_session)
    try:
        client.request("POST", "/v1/intents", json={})
        assert False, "expected AuthenticationError"
    except AuthenticationError as e:
        assert e.status_code == 403


def test_422_raises_api_error_not_retried(fake_session):
    fake_session.queue_response(422, {"detail": "validation error"})
    client = _client(fake_session, retry_count=3)
    try:
        client.request("POST", "/v1/intents", json={})
        assert False, "expected ApiError"
    except ApiError as e:
        assert e.status_code == 422
    assert len(fake_session.calls) == 1  # never retried


def test_500_is_retried_then_succeeds(fake_session, monkeypatch):
    monkeypatch.setattr("payreality.retry.time.sleep", lambda _seconds: None)
    fake_session.queue_response(500, {"detail": "boom"})
    fake_session.queue_response(500, {"detail": "boom"})
    fake_session.queue_response(200, {"status": "ok"})
    client = _client(fake_session, retry_count=3)
    result = client.request("GET", "/health")
    assert result == {"status": "ok"}
    assert len(fake_session.calls) == 3


def test_500_exhausts_retries_and_raises_api_error(fake_session, monkeypatch):
    monkeypatch.setattr("payreality.retry.time.sleep", lambda _seconds: None)
    for _ in range(4):  # retry_count=3 means 4 total attempts
        fake_session.queue_response(500, {"detail": "still down"})
    client = _client(fake_session, retry_count=3)
    try:
        client.request("GET", "/health")
        assert False, "expected ApiError"
    except ApiError as e:
        assert e.status_code == 500
    assert len(fake_session.calls) == 4


def test_connection_error_is_retried_then_succeeds(fake_session, monkeypatch):
    monkeypatch.setattr("payreality.retry.time.sleep", lambda _seconds: None)
    fake_session.queue_exception(requests.exceptions.ConnectionError("refused"))
    fake_session.queue_response(200, {"status": "ok"})
    client = _client(fake_session, retry_count=3)
    assert client.request("GET", "/health") == {"status": "ok"}


def test_connection_error_exhausted_raises_network_error(fake_session, monkeypatch):
    monkeypatch.setattr("payreality.retry.time.sleep", lambda _seconds: None)
    for _ in range(2):  # retry_count=1 means 2 total attempts
        fake_session.queue_exception(requests.exceptions.ConnectionError("refused"))
    client = _client(fake_session, retry_count=1)
    try:
        client.request("GET", "/health")
        assert False, "expected NetworkError"
    except NetworkError:
        pass


def test_timeout_is_retryable(fake_session, monkeypatch):
    monkeypatch.setattr("payreality.retry.time.sleep", lambda _seconds: None)
    fake_session.queue_exception(requests.exceptions.Timeout("slow"))
    fake_session.queue_response(200, {"status": "ok"})
    client = _client(fake_session, retry_count=3)
    assert client.request("GET", "/health") == {"status": "ok"}


def test_validation_error_is_never_retried_even_with_retries_available(fake_session):
    fake_session.queue_response(422, {"detail": "bad input"})
    client = _client(fake_session, retry_count=5)
    try:
        client.request("POST", "/v1/intents", json={})
    except ApiError:
        pass
    assert len(fake_session.calls) == 1
