#!/usr/bin/env python3
"""Stripe test-mode sandbox adapter -- REFERENCE / PROOF OF MECHANISM,
matching scripts/reference_enforcement_adapter.py's own established
posture in this repository: not a production integration, not a
general-purpose Stripe SDK, proves exactly one thing (this codebase's
own lifecycle model correctly tracks a real destination's real state
machine) and is careful never to claim more.

The one authorized action this adapter dispatches: one PaymentIntent,
created then confirmed in Stripe TEST MODE ONLY, for an already-
authorized, already-consumed PayReality Capability. See
STRIPE_SANDBOX_IMPLEMENTATION_PLAN.md for the full design and
STRIPE_SANDBOX_HANDOFF.md for why PaymentIntent creation, confirmation,
payment success, and settlement are four distinct things this module's
own naming is careful never to conflate.

=== Corrected identity and idempotency-key mapping ===

An earlier version of this plan proposed reusing CapabilityToken.nonce
directly as the Stripe idempotency key. That was wrong: a nonce
identifies an AUTHORIZATION ARTIFACT (one Capability, consumed exactly
once); a fresh, PayReality-authorized retry of the same real-world
operation mints a brand-new Capability with a brand-new nonce while
still referring to the same destination operation, so reusing the
nonce would give every single attempt -- legitimate or not -- its own
fresh Stripe-level scope, defeating destination-side idempotency
entirely. Verified against Stripe's own official documentation (see
the module-level constants below for the exact facts and their
sources), the corrected mapping is:

  - The STABLE, audit/correlation identity (constant across every
    attempt at the same real-world operation, including a fresh
    authorized retry) is BusinessOperationIdentity.id -- already
    tenant/integration/action/destination-scoped by its own existing DB
    unique constraint, reused rather than re-derived. Sent to Stripe
    only as `metadata`, never as the idempotency key itself.
  - The actual Stripe Idempotency-Key header is derived from
    (Operation.id, operation_kind) -- stable only for repeated calls
    against the SAME attempt (a client-side retry of one dispatch), and
    deliberately DIFFERENT for a new, PayReality-authorized attempt
    (which gets its own new Operation.id), so Stripe correctly attempts
    a fresh charge rather than replaying a stale/declined cached result.
  - CapabilityToken.nonce and Operation.id are kept as separate audit
    fields (both sent as metadata), never conflated with each other or
    with the idempotency key.

Long-term protection against re-attempting an already-resolved business
operation is deliberately NOT this module's job, and not Stripe's
idempotency key's job either (it is pruned after 24 hours) -- it is
app.services.operation_service.evaluate_replacement_safety's job,
already implemented and already tested elsewhere in this codebase. This
module only ever dispatches an already-authorized, already-consumed
Capability; it never decides whether a new attempt should be allowed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

# === Facts verified directly against Stripe's own official documentation,
# not assumed -- sources recorded here so a later reader can re-check them. ===
STRIPE_IDEMPOTENCY_KEY_RETENTION_HOURS = 24
"""https://docs.stripe.com/api/idempotent_requests : 'You can remove keys
from the system automatically after they're at least 24 hours old. We
generate a new request if a key is reused after the original is pruned.'"""

STRIPE_IDEMPOTENCY_KEY_MAX_LENGTH = 255
"""Same source: 'Idempotency keys are up to 255 characters long.'"""

STRIPE_CONCURRENT_REQUEST_STATUS_CODE = 409
"""https://docs.stripe.com/error-low-level#idempotency and the HTTP status
code table on that same page: 409 Conflict, 'The request conflicts with
another request (perhaps due to using the same idempotent key).'"""

OPERATION_KIND_CREATE = "payment_intent_create"
OPERATION_KIND_CONFIRM = "payment_intent_confirm"


# === Pure identity / idempotency-key mapping -- no I/O, fully unit-testable ===


def destination_operation_identity(business_operation_identity_id: str) -> str:
    """The stable, audit/correlation identity for one real-world
    operation -- constant across every attempt, original or retried,
    at the SAME business operation. Sent to Stripe only as metadata
    (see build_metadata below); never used as the idempotency key
    itself -- see this module's own docstring for exactly why that
    distinction matters."""
    return str(business_operation_identity_id)


def idempotency_key(operation_id: str, operation_kind: str) -> str:
    """The actual Stripe Idempotency-Key header value: stable only for
    repeated calls against the SAME attempt (the same Operation row),
    and always distinct between a 'create' and a 'confirm' call (they
    are different Stripe operations with different parameters -- reuse
    between them would trip Stripe's own parameter-mismatch check)."""
    if operation_kind not in (OPERATION_KIND_CREATE, OPERATION_KIND_CONFIRM):
        raise ValueError(f"unknown operation_kind: {operation_kind!r}")
    key = f"{operation_id}:{operation_kind}"
    if len(key) > STRIPE_IDEMPOTENCY_KEY_MAX_LENGTH:
        raise ValueError(f"derived idempotency key exceeds Stripe's {STRIPE_IDEMPOTENCY_KEY_MAX_LENGTH}-char limit")
    return key


def build_metadata(
    *, organization_id: str, integration_id: str, business_operation_identity_id: str,
    operation_id: str, capability_nonce: str,
) -> dict[str, str]:
    """Every field PayReality wants correlatable on the Stripe side,
    each kept as its own distinct metadata key -- capability nonce and
    attempt id (Operation.id) are NEVER merged into one field, per this
    review's own explicit requirement to keep them separate audit
    fields. Stripe's own docs recommend exactly this pattern: 'send in
    a local identifier with the metadata when creating new resources...
    That identifier appears in the metadata field of an object going
    out through a webhook, even if the webhook is generated later as
    part of reconciliation' (docs.stripe.com/error-low-level#server-errors)."""
    return {
        "payreality_organization_id": str(organization_id),
        "payreality_integration_id": str(integration_id),
        "payreality_business_operation_identity_id": destination_operation_identity(business_operation_identity_id),
        "payreality_operation_id": str(operation_id),
        "payreality_capability_nonce": str(capability_nonce),
    }


# === Stripe client abstraction -- one real implementation, one local
# simulation, sharing the same interface so orchestration logic is
# identical and testable regardless of which backs it. ===


class StripeClientError(Exception):
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.body = body
        super().__init__(f"stripe_error status={status_code} body={body}")


class StripeClient(Protocol):
    def create_payment_intent(self, *, idempotency_key: str, amount: int, currency: str, metadata: dict) -> dict: ...
    def confirm_payment_intent(self, *, payment_intent_id: str, idempotency_key: str, payment_method: str, metadata: dict) -> dict: ...
    def retrieve_payment_intent(self, *, payment_intent_id: str) -> dict:
        """Read-only. Must never create or confirm anything -- this is
        the one method any status-lookup caller is allowed to use."""
        ...


class RealStripeClient:
    """Thin wrapper over Stripe's real REST API (api.stripe.com),
    TEST MODE ONLY. Refuses construction with anything that isn't a
    real sk_test_ secret key -- a caller cannot accidentally point this
    at live mode even by misconfiguring an environment variable, since
    the key's own prefix is checked before any request is ever made."""

    _BASE_URL = "https://api.stripe.com/v1"

    def __init__(self, secret_key: str):
        if not secret_key.startswith("sk_test_"):
            raise ValueError(
                "refusing to construct RealStripeClient with a non-test-mode secret key -- "
                "only sk_test_... keys are accepted; live-mode credentials are rejected outright"
            )
        self._secret_key = secret_key

    def _request(self, method: str, path: str, *, idempotency_key: str | None = None, data: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._secret_key}"}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        body = None
        if data is not None:
            flat = _flatten_stripe_params(data)
            body = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in flat.items()).encode("ascii")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(f"{self._BASE_URL}{path}", data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise StripeClientError(e.code, json.loads(e.read())) from e

    def create_payment_intent(self, *, idempotency_key: str, amount: int, currency: str, metadata: dict) -> dict:
        data = {"amount": amount, "currency": currency, "metadata": metadata}
        return self._request("POST", "/payment_intents", idempotency_key=idempotency_key, data=data)

    def confirm_payment_intent(self, *, payment_intent_id: str, idempotency_key: str, payment_method: str, metadata: dict) -> dict:
        data = {"payment_method": payment_method, "metadata": metadata}
        return self._request("POST", f"/payment_intents/{payment_intent_id}/confirm", idempotency_key=idempotency_key, data=data)

    def retrieve_payment_intent(self, *, payment_intent_id: str) -> dict:
        # GET is idempotent by Stripe's own definition -- no Idempotency-Key
        # header is sent or needed (docs.stripe.com/api/idempotent_requests:
        # "Don't send idempotency keys in GET and DELETE requests because
        # it has no effect.").
        return self._request("GET", f"/payment_intents/{payment_intent_id}")


def _flatten_stripe_params(data: dict, prefix: str = "") -> dict:
    """Stripe's form-encoded API wants metadata as metadata[key]=value,
    not a JSON blob -- a small, real encoding detail, not a simulation."""
    flat = {}
    for key, value in data.items():
        full_key = f"{prefix}[{key}]" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten_stripe_params(value, full_key))
        else:
            flat[full_key] = value
    return flat


def build_real_client_from_env() -> RealStripeClient | None:
    """Returns a real client ONLY when BOTH a real test-mode secret key
    AND an explicit execution switch are present in the environment --
    the double-gate this review's own task requires. Returns None
    (never a client, never a partial/implicit default) if either is
    missing, so a caller can check `is None` and skip real-Stripe steps
    honestly rather than accidentally proceeding."""
    secret_key = os.environ.get("STRIPE_TEST_SECRET_KEY", "")
    execute = os.environ.get("STRIPE_SANDBOX_EXECUTE", "").strip().lower() == "true"
    if not secret_key or not execute:
        return None
    return RealStripeClient(secret_key)


@dataclass
class _CachedResult:
    params_fingerprint: str
    response: dict
    created_at: float


class FakeStripeBackend:
    """LOCAL SIMULATION of Stripe's own REST API, for testing this
    adapter's OWN orchestration logic without any real network call --
    never presented as, or confused with, a real Stripe test-mode run.
    Models the specific official behaviors this design depends on,
    each with its own cited source:

      - Idempotency-key result caching, including caching a 'declined'
        or otherwise non-success result (docs.stripe.com/api/
        idempotent_requests: 'saving the resulting status code and
        body of the first request... regardless of whether it
        succeeds or fails').
      - Parameter-mismatch on key reuse -> error, never silent
        reprocessing (same source: 'compares incoming parameters...
        and errors if they're not the same').
      - A concurrent request under the same still-executing key ->
        409 (docs.stripe.com/error-low-level#idempotency, HTTP status
        table: 409 Conflict).
      - Key pruning after an injectable clock passes the real 24-hour
        retention window, so tests can exercise expiry without waiting
        24 real hours.

    Configurable per-PaymentIntent outcome behavior (`outcome`) lets a
    test choose succeeded / declined / requires_action / no_response
    (simulating a destination that never replies) independently of the
    idempotency mechanics above."""

    def __init__(self, *, clock: "_Clock | None" = None, default_outcome: str = "succeeded"):
        self._clock = clock or _Clock()
        self._lock = threading.Lock()
        self._cache: dict[str, _CachedResult] = {}
        self._in_flight: set[str] = set()
        self._payment_intents: dict[str, dict] = {}
        self._outcomes: dict[str, str] = {}  # payment_intent_id -> outcome
        self._default_outcome = default_outcome

    def set_default_outcome(self, outcome: str) -> None:
        """Test-only configuration: what ANY PaymentIntent resolves to
        once confirmed, unless overridden per-id via set_outcome below.
        Exists because a real caller cannot know a PaymentIntent's own
        id before creating it, so a test that wants a non-'succeeded'
        outcome on a PaymentIntent's very first confirm call (not a
        second, re-confirmed call after the fact) needs to configure
        this before dispatching at all, not after."""
        self._default_outcome = outcome

    def set_outcome(self, payment_intent_id: str, outcome: str) -> None:
        """Test-only configuration: what this SPECIFIC PaymentIntent
        resolves to once confirmed, overriding the default above. One of
        'succeeded', 'declined', 'requires_action', 'no_response'
        (confirm call simply never completes -- raises a simulated
        network error every time)."""
        self._outcomes[payment_intent_id] = outcome

    def _params_fingerprint(self, data: dict) -> str:
        return json.dumps(data, sort_keys=True)

    def _cached_or_execute(self, key: str, params: dict, execute):
        fingerprint = self._params_fingerprint(params)
        with self._lock:
            now = self._clock.now()
            cached = self._cache.get(key)
            if cached is not None and (now - cached.created_at) >= STRIPE_IDEMPOTENCY_KEY_RETENTION_HOURS * 3600:
                # Real behavior: "We generate a new request if a key is
                # reused after the original is pruned." The key is simply
                # forgotten -- not an error, not a special "expired" flag.
                del self._cache[key]
                cached = None
            if cached is not None:
                if cached.params_fingerprint != fingerprint:
                    raise StripeClientError(400, {"error": {"type": "idempotency_error", "message": "Keys for idempotent requests can only be used with the same parameters they were first used with"}})
                return cached.response
            if key in self._in_flight:
                raise StripeClientError(
                    STRIPE_CONCURRENT_REQUEST_STATUS_CODE,
                    {"error": {"type": "idempotency_error", "message": "A request is currently being processed with this idempotency key"}},
                )
            self._in_flight.add(key)
        try:
            response = execute()
            with self._lock:
                self._cache[key] = _CachedResult(params_fingerprint=fingerprint, response=response, created_at=now)
            return response
        finally:
            with self._lock:
                self._in_flight.discard(key)

    def create_payment_intent(self, *, idempotency_key: str, amount: int, currency: str, metadata: dict) -> dict:
        def _do():
            pi_id = f"pi_sim_{len(self._payment_intents) + 1:06d}"
            obj = {
                "id": pi_id, "object": "payment_intent", "amount": amount, "currency": currency,
                "status": "requires_payment_method", "metadata": dict(metadata), "livemode": False,
            }
            self._payment_intents[pi_id] = obj
            return dict(obj)
        return self._cached_or_execute(idempotency_key, {"amount": amount, "currency": currency, "metadata": metadata}, _do)

    def confirm_payment_intent(self, *, payment_intent_id: str, idempotency_key: str, payment_method: str, metadata: dict) -> dict:
        def _do():
            outcome = self._outcomes.get(payment_intent_id, self._default_outcome)
            if outcome == "no_response":
                raise TimeoutError("simulated: destination never responded to the confirm call")
            obj = self._payment_intents[payment_intent_id]
            obj["payment_method"] = payment_method
            obj["metadata"] = {**obj["metadata"], **metadata}
            if outcome == "succeeded":
                obj["status"] = "succeeded"
            elif outcome == "declined":
                obj["status"] = "canceled"
                obj["cancellation_reason"] = "declined_by_fake_backend"
            elif outcome == "requires_action":
                obj["status"] = "requires_action"
            else:
                raise ValueError(f"unknown simulated outcome: {outcome!r}")
            return dict(obj)
        return self._cached_or_execute(idempotency_key, {"payment_intent_id": payment_intent_id, "payment_method": payment_method}, _do)

    def retrieve_payment_intent(self, *, payment_intent_id: str) -> dict:
        # Read-only by construction: this method never touches _cache,
        # _in_flight, or _payment_intents' own mutable state, and never
        # calls create/confirm internally.
        obj = self._payment_intents.get(payment_intent_id)
        if obj is None:
            raise StripeClientError(404, {"error": {"type": "invalid_request_error", "message": "No such payment_intent"}})
        return dict(obj)


class _Clock:
    """Injectable wall-clock, real by default, so tests can simulate
    the passage of Stripe's own 24-hour idempotency-key retention
    window without a real 24-hour wait."""

    def __init__(self):
        self._offset = 0.0

    def now(self) -> float:
        return time.time() + self._offset

    def advance(self, seconds: float) -> None:
        self._offset += seconds


# === Orchestration -- the adapter's own actual behavior ===


@dataclass
class DispatchResult:
    payment_intent_id: str
    status: str
    idempotency_key_used: str


def dispatch_payment_intent(
    client: StripeClient, *, organization_id: str, integration_id: str,
    business_operation_identity_id: str, operation_id: str, capability_nonce: str,
    amount: int, currency: str, payment_method: str,
) -> DispatchResult:
    """The ONE effectful path in this module: create, then confirm, a
    PaymentIntent for an already-authorized, already-consumed
    Capability. Never calls retrieve_payment_intent -- status lookup is
    a structurally separate function (see below), so a caller that only
    imports/uses that one literally cannot reach this code path."""
    metadata = build_metadata(
        organization_id=organization_id, integration_id=integration_id,
        business_operation_identity_id=business_operation_identity_id,
        operation_id=operation_id, capability_nonce=capability_nonce,
    )
    create_key = idempotency_key(operation_id, OPERATION_KIND_CREATE)
    created = client.create_payment_intent(idempotency_key=create_key, amount=amount, currency=currency, metadata=metadata)

    confirm_key = idempotency_key(operation_id, OPERATION_KIND_CONFIRM)
    confirmed = client.confirm_payment_intent(
        payment_intent_id=created["id"], idempotency_key=confirm_key, payment_method=payment_method, metadata=metadata,
    )
    return DispatchResult(payment_intent_id=confirmed["id"], status=confirmed["status"], idempotency_key_used=confirm_key)


def retrieve_status(client: StripeClient, *, payment_intent_id: str) -> dict:
    """Read-only status investigation for an existing operation. Calls
    ONLY client.retrieve_payment_intent -- structurally incapable of
    creating or confirming anything, since it never references
    create_payment_intent/confirm_payment_intent at all."""
    return client.retrieve_payment_intent(payment_intent_id=payment_intent_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status-of", metavar="PAYMENT_INTENT_ID", help="Read-only: look up an existing PaymentIntent's status and exit.")
    args = parser.parse_args(argv)

    client = build_real_client_from_env()
    if client is None:
        print(
            "STRIPE_TEST_SECRET_KEY and STRIPE_SANDBOX_EXECUTE=true must both be set to run "
            "this adapter against real Stripe test mode. Neither value is printed or required "
            "here beyond checking they are set -- see STRIPE_SANDBOX_IMPLEMENTATION_PLAN.md for "
            "secure local setup instructions.",
            file=sys.stderr,
        )
        return 2

    if args.status_of:
        result = retrieve_status(client, payment_intent_id=args.status_of)
        print(json.dumps(result, indent=2))
        return 0

    print(
        "This CLI entry point only supports --status-of (read-only lookup) today. "
        "Dispatching a new PaymentIntent requires a real, already-consumed PayReality "
        "Capability's own identifiers, wired in by whatever orchestrates the full lifecycle "
        "(see server/tests/integration/test_stripe_sandbox_operation_lifecycle.py for the "
        "reference orchestration, exercised against the local simulation in this module).",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
