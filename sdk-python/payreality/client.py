"""The one place in the SDK that makes an HTTP request. Every public
method on `Agent` goes through this; it owns retries, timeouts, JSON
encoding, and mapping a server response (or a network failure) onto the
exception hierarchy in exceptions.py. No caller of this module ever
sees a raw `requests` exception or a bare status code.
"""

from __future__ import annotations

import json as json_module
from typing import Any

import requests

from .configuration import Configuration
from .exceptions import ApiError, AuthenticationError, InvalidSignature, NetworkError
from .retry import RetryPolicy, is_retryable_exception, is_retryable_status, sleep_before_retry


class HttpClient:
    def __init__(self, config: Configuration, session: requests.Session | None = None):
        self._config = config
        self._session = session or requests.Session()
        self._retry_policy = RetryPolicy(max_retries=config.retry_count)

    def _url(self, path: str) -> str:
        return f"{self._config.base_url}{path}"

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        signed_body: bytes | None = None,
        operator_auth: bool = False,
    ) -> dict[str, Any]:
        """`signed_body`, if given, is sent verbatim as the request body
        (the exact bytes that were signed); otherwise `json` is encoded
        normally. `operator_auth=True` attaches the configured api_key
        as the operator-key header this platform's administrative
        endpoints already require (SDK_SECURITY.md), plus (PayReality
        Enterprise v1.0, Milestone 2) the target organization the
        operator key is now required to name explicitly -- it is
        platform-admin-only and has no organization of its own."""
        request_headers = dict(headers or {})
        if operator_auth:
            if not self._config.api_key:
                raise AuthenticationError(
                    "This call requires an api_key. Pass Agent(api_key=...) or set PAYREALITY_API_KEY."
                )
            if not self._config.organization_id:
                raise AuthenticationError(
                    "This call requires an organization_id. Pass Agent(organization_id=...) -- "
                    "the operator key is platform-admin-only and must name its target organization "
                    "explicitly on every call."
                )
            request_headers["X-PayReality-Operator-Key"] = self._config.api_key
            request_headers["X-PayReality-Organization-Id"] = self._config.organization_id

        if signed_body is not None:
            body = signed_body
            request_headers.setdefault("Content-Type", "application/json")
        elif json is not None:
            body = json_module.dumps(json).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        else:
            body = None

        last_exception: Exception | None = None
        attempts = self._retry_policy.max_retries + 1
        for attempt in range(attempts):
            try:
                response = self._session.request(
                    method,
                    self._url(path),
                    data=body,
                    headers=request_headers,
                    timeout=self._config.timeout,
                )
            except Exception as exc:  # requests.exceptions.* all inherit from RequestException
                last_exception = exc
                if is_retryable_exception(exc) and attempt < attempts - 1:
                    sleep_before_retry(self._retry_policy, attempt)
                    continue
                raise NetworkError(f"Could not reach PayReality: {exc}", cause=exc) from exc

            if response.status_code < 300:
                if not response.content:
                    return {}
                return response.json()

            if is_retryable_status(response.status_code) and attempt < attempts - 1:
                sleep_before_retry(self._retry_policy, attempt)
                continue

            self._raise_for_response(response)

        # Unreachable in practice (the loop above always returns or
        # raises), but keeps type checkers happy and fails loudly rather
        # than silently returning None if it ever were reached.
        raise NetworkError("Exhausted retries with no response.", cause=last_exception)

    def _raise_for_response(self, response: requests.Response) -> None:
        try:
            body = response.json()
        except ValueError:
            body = response.text

        detail = body.get("detail") if isinstance(body, dict) else body

        if response.status_code == 401:
            if isinstance(detail, str) and "signature" in detail.lower():
                raise InvalidSignature(f"Signature rejected: {detail}", status_code=401, reason=detail)
            raise AuthenticationError(f"Authentication failed: {detail}", status_code=401)
        if response.status_code == 403:
            raise AuthenticationError(f"Not permitted: {detail}", status_code=403)

        raise ApiError(
            f"PayReality API returned {response.status_code}: {detail}",
            status_code=response.status_code,
            body=body,
        )
