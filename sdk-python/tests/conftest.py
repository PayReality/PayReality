import json as json_module

import pytest
import requests


class FakeResponse:
    """A minimal stand-in for `requests.Response`, just enough of the
    surface `client.HttpClient` actually touches."""

    def __init__(self, status_code: int, json_body=None, text: str = ""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text if json_body is None else json_module.dumps(json_body)
        self.content = self.text.encode("utf-8")

    def json(self):
        if self._json_body is None:
            raise ValueError("no JSON body")
        return self._json_body


class FakeSession:
    """Programmable stand-in for `requests.Session`. Queue up responses
    (or exceptions) with `.queue_response()`/`.queue_exception()`, then
    every call records what was actually sent in `.calls` so tests can
    assert on headers/body/URL without touching the network."""

    def __init__(self):
        self._queue = []
        self.calls = []

    def queue_response(self, status_code: int, json_body=None):
        self._queue.append(("response", FakeResponse(status_code, json_body)))

    def queue_exception(self, exc: Exception):
        self._queue.append(("exception", exc))

    def request(self, method, url, data=None, headers=None, timeout=None):
        self.calls.append(
            {"method": method, "url": url, "data": data, "headers": headers, "timeout": timeout}
        )
        if not self._queue:
            raise AssertionError("FakeSession has no more queued responses/exceptions")
        kind, value = self._queue.pop(0)
        if kind == "exception":
            raise value
        return value


@pytest.fixture
def fake_session():
    return FakeSession()


@pytest.fixture
def credentials_path(tmp_path):
    return tmp_path / "credentials.json"


class FakeHttpClient:
    """A drop-in replacement for `client.HttpClient` used to test `Agent`
    in isolation from real HTTP: queue up what each call should return,
    keyed by call order, and inspect `.calls` afterward."""

    def __init__(self):
        self._queue = []
        self.calls = []

    def queue_response(self, response):
        self._queue.append(response)

    def request(self, method, path, *, json=None, headers=None, signed_body=None, admin_auth=False):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "json": json,
                "headers": headers,
                "signed_body": signed_body,
                "admin_auth": admin_auth,
            }
        )
        return self._queue.pop(0)


@pytest.fixture
def fake_http_client():
    return FakeHttpClient()
