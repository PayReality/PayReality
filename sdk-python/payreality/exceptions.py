"""Every error this SDK can raise. A developer using this SDK should
never see a raw `requests.exceptions.*` or an unhandled HTTP status
code; every failure path is mapped to one of these before it reaches
calling code.
"""

from __future__ import annotations

from typing import Any


class PayRealityError(Exception):
    """Base class for every exception this SDK raises. Catch this if you
    want to handle any PayReality-related failure without enumerating
    every specific subclass."""


class ConfigurationError(PayRealityError):
    """Raised when the SDK is asked to do something it doesn't have
    enough information for: no api_key configured, no registered agent
    identity yet (call `agent.register()` first), a `principal` passed
    to `authorize()` that doesn't match the principal this agent was
    registered for, and similar local, pre-flight problems. Never
    reaches the network."""


class AuthenticationError(PayRealityError):
    """The server rejected the request's credentials: an invalid or
    missing api_key on `register()`/`health()`/`version()`. Distinct
    from `InvalidSignature`, which is specifically about a signed
    `authorize()` call."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class InvalidSignature(PayRealityError):
    """The server rejected an `authorize()` call's signature: an unknown
    or revoked certificate, a signature that doesn't verify, or a
    request outside the replay-protection time window. This should not
    happen in normal use; it usually means the locally stored private
    key no longer matches what the server has on file, or the local
    clock has drifted enough to fall outside the signing window."""

    def __init__(self, message: str, status_code: int | None = None, reason: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason


class NetworkError(PayRealityError):
    """A request never got a response at all: DNS failure, connection
    refused, or every retry attempt timed out. Wraps the underlying
    `requests` exception rather than letting it escape directly."""

    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.__cause__ = cause


class ApiError(PayRealityError):
    """A catch-all for a server response this SDK doesn't have a more
    specific exception for: an unexpected 4xx/5xx, or a 2xx whose body
    doesn't parse as expected. Carries the raw status code and response
    body so a caller can still inspect what happened."""

    def __init__(self, message: str, status_code: int, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class AuthorizationDenied(PayRealityError):
    """Raised only by `Decision.raise_for_outcome()`, never by
    `authorize()` itself: a DENY is a normal, expected outcome of a real
    authorization check, not an exceptional program state. This
    exception exists for callers who prefer exception-flow control
    (`decision.raise_for_outcome()`) over checking `decision.allowed`."""

    def __init__(self, decision):
        self.decision = decision
        super().__init__(decision.reason or "Authorization denied.")


class HumanReviewRequired(PayRealityError):
    """Raised only by `Decision.raise_for_outcome()`: the action was
    routed to a human reviewer rather than allowed or denied outright.
    `decision.decision_id` identifies which decision to poll (via
    `agent.get_decision()`) once it's resolved."""

    def __init__(self, decision):
        self.decision = decision
        super().__init__(decision.reason or "This action requires human review.")


class CapabilityTokenExpiredError(AuthenticationError):
    """`verify_capability()` only: the Capability's own signed `expires_at`
    has passed. Distinct from a bad verifier credential -- the caller's
    own auth was fine, the token itself is simply too old to consume."""


class InvalidCapabilityTokenError(AuthenticationError):
    """`verify_capability()` only: the token failed signature
    verification, or doesn't decode as a capability token at all
    (corrupted, truncated, or not a PayReality token). Not the same as
    an expired token, and not the same as the verifier's own credentials
    being rejected."""


class CapabilityTenantMismatchError(AuthenticationError):
    """`verify_capability()` only: the Capability was issued for a
    different organization than the one this verifier is authenticated
    as. See Trusted Integration Phase 6.1 -- a verifier scoped to one
    organization can never consume another organization's Capability."""


class CapabilityAudienceMismatchError(AuthenticationError):
    """`verify_capability()` only: the Capability was issued for a
    different `audience` (a different named enforcement checkpoint) than
    the one presented here."""


class CapabilityNotFoundError(ApiError):
    """`verify_capability()` only: no issued Capability matches this
    token's hash at all -- not "wrong," simply unknown to PayReality."""


class CapabilityConstraintMismatchError(ApiError):
    """`verify_capability()` only: the presented `action`, `resource`,
    `constraints`, or `principal` doesn't match exactly what the
    Capability was issued for. PayReality does not report which specific
    field mismatched (by design -- see domain/capability/token.py); treat
    any of the four as a possible cause."""


class CapabilityBindingMismatchError(ApiError):
    """`verify_capability()` only: the presented `environment` or
    `enforcement_binding_id` doesn't match what the Capability was issued
    for."""


class CapabilityAlreadyConsumedError(ApiError):
    """`verify_capability()` only: this exact Capability was already
    consumed once, by this call or a concurrent/earlier one. Single-use
    is enforced at the database level -- this is the replay/race signal,
    never a sign the first consumption failed."""


class CapabilityTrustNotActiveError(ApiError):
    """`verify_capability()` only: consumption was refused because a live
    identity or binding the Capability depends on is no longer active --
    the originating Agent, the Organization (tenant), the Trusted
    Integration identity, or the Enforcement Binding, rechecked
    immediately before consumption (Trusted Integration Phase 6.1). The
    Capability itself was never marked consumed by this failed attempt;
    a later attempt is checked against whatever state exists at that
    time. `str(exc)` names which specific one failed."""


class ResolutionTimeoutError(PayRealityError):
    """Raised only by `agent.wait_for_resolution()`: the bounded polling
    window elapsed with the decision still `HUMAN_REVIEW`/pending. Not
    raised by `authorize()` or `get_decision()`, and never means the
    decision failed -- it may still resolve later; `.decision` carries
    the last-known state (still pending) so the caller can decide
    whether to keep waiting, poll manually, or give up."""

    def __init__(self, decision, timeout: float):
        self.decision = decision
        self.timeout = timeout
        super().__init__(
            f"Decision {decision.decision_id} was still pending after {timeout:.0f}s. "
            "It may still resolve later -- this is not a failure of the decision itself."
        )
