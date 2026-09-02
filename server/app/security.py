"""Operator authentication, request context/logging, security headers, and
per-client rate limiting.

`verify_operator_key` is the original single-shared-credential gate on
every mutating endpoint. RBAC.md added real per-user roles and
per-API-key permissions on top of this (see
`app.dependencies.require_permission`), but `verify_operator_key` itself
is unchanged and still works exactly as it always has: a present, correct
operator key is still a full bypass, so every existing integration built
against it keeps working with no changes required. `resolved_by` on a
decision resolution is still a free-text field (see
app.services.resolution_service) -- RBAC.md ties *access* to resolving a
decision to a real permission, not yet *attribution* of who resolved it.
"""

import hmac
import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import settings

access_logger = logging.getLogger("payreality.access")

_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_REQUESTS = 120
_request_log: dict[str, deque] = defaultdict(deque)


def verify_operator_key(x_payreality_operator_key: str = Header(...)) -> None:
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="operator_auth_not_configured")
    if not hmac.compare_digest(x_payreality_operator_key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="invalid_operator_key")


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(key: str, log_store: dict[str, deque], window_seconds: float, max_requests: int) -> bool:
    """The same sliding-window check `observability_middleware` applies
    to every request, extracted so a specific endpoint can apply a
    SECOND, stricter limit on top of it against its own dedicated
    `log_store` (never sharing `_request_log`, so a burst against one
    endpoint can't exhaust another's budget). Returns True if the
    request is allowed (and records it); False if the limit is
    exceeded (nothing recorded for the rejected attempt). In-process
    only, the same disclosed limitation `_request_log` itself already
    has (resets on restart, not shared across workers/instances)."""
    now = time.monotonic()
    log = log_store[key]
    while log and now - log[0] > window_seconds:
        log.popleft()
    if len(log) >= max_requests:
        return False
    log.append(now)
    return True


async def observability_middleware(request: Request, call_next):
    """Rate limiting, request id, access logging, security headers, and the
    last-resort 500 handler, in one middleware.

    This intentionally is NOT split into several stacked
    `app.middleware("http")` (BaseHTTPMiddleware) layers: Starlette's
    BaseHTTPMiddleware has a documented history of losing exceptions across
    multiple stacked instances (the exception raised by the route handler
    never reaches an outer layer's except block, producing an empty
    response body instead of a clean JSON 500, verified locally while
    building this). One middleware, one try/except around call_next, is the
    reliable version of the same behavior.
    """
    key = _client_key(request)
    if not check_rate_limit(key, _request_log, _RATE_LIMIT_WINDOW_SECONDS, _RATE_LIMIT_MAX_REQUESTS):
        return JSONResponse(status_code=429, content={"detail": "rate_limit_exceeded"})

    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    start = time.monotonic()

    try:
        response = await call_next(request)
    except Exception:
        access_logger.exception(
            "unhandled_exception request_id=%s method=%s path=%s",
            request_id,
            request.method,
            request.url.path,
        )
        response = JSONResponse(status_code=500, content={"detail": "internal_error"})

    duration_ms = (time.monotonic() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if settings.environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"

    access_logger.info(
        "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response
