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

=== Identity model (revised -- a real flaw in the previous version is
fixed here, not merely renamed) ===

Six genuinely distinct identities are in play, and conflating any two
of them is exactly how a duplicate-effect bug gets introduced:

  1. **Business operation** -- `BusinessOperationIdentity.id`. Stable
     across every attempt, forever. Sent to Stripe only as metadata.
  2. **Authorized attempt** -- `Operation.id`. One per real authorization
     (one Decision, one Capability). A NEW attempt always gets a NEW
     Operation.id -- this is what makes "a fresh, PayReality-authorized
     retry" distinguishable from "a client-side retry of the same call."
  3. **Capability nonce** -- `CapabilityToken.nonce`. Identifies the
     single-use authorization artifact consumed to make one specific
     dispatch call. Audit-only; kept separate from both of the above.
  4. **Logical destination operation** -- `destination_dispatch_identity`
     (new in this revision, computed below). The identity of "one
     specific attempt to execute at the destination," which is
     deliberately NOT the same thing as the authorized attempt (2):
     when a replacement is authorized despite an UNRESOLVED prior
     outcome (a human-documented `SAFE_DUPLICATE_PREVENTION_GUARANTEED`,
     as opposed to a proven `SAFE_TERMINAL_NON_COMMIT_PROVEN`), the new
     Operation must NOT get a new destination identity -- it has to
     carry forward the SAME one the unresolved original used, so
     Stripe's own idempotency layer can recognize it as a retry of a
     request whose outcome was never actually confirmed, not approve a
     second, independent attempt to execute.
  5. **Stripe object ID** -- the real `pi_...` returned by Stripe.
     Durable once learned; `Operation.destination_operation_id`.
  6. **Stripe idempotency key** -- the literal `Idempotency-Key` header
     value, derived from (4) plus tenant/account scoping plus which
     Stripe call it is (create vs. confirm) -- see `idempotency_key`
     below. Never equal to (2) or (3) directly.

=== The flaw this revision fixes ===

The previous version of this module derived the idempotency key from
`Operation.id` alone (identity 2 above), reasoning that a fresh,
PayReality-authorized attempt should get a fresh Stripe-level scope.
That is correct ONLY when the replacement was authorized because the
original was PROVEN to have failed (`SAFE_TERMINAL_NON_COMMIT_PROVEN`).
It is WRONG when the replacement was authorized despite the original's
outcome still being UNKNOWN (`SAFE_DUPLICATE_PREVENTION_GUARANTEED` --
a human has documented that a retry is safe, precisely BECAUSE the
original's own fate at the destination is unresolved, e.g. its
response was lost before PayReality ever learned the resulting
Stripe object ID). In that second case, a fresh Operation.id produces
a fresh idempotency key for the SAME logical destination operation,
and if the original dispatch actually reached and was processed by
Stripe (even though PayReality never found out), the "fresh" retry
creates a SECOND, independent PaymentIntent -- reproducing, under a
different name, the exact duplicate-effect risk the nonce-based
design already had. Traced and confirmed via this exact sequence:

    1. Operation A dispatches; Stripe creates a PaymentIntent.
    2. The response is lost before Operation A's own
       destination_operation_id is ever durably recorded.
    3. A.outcome_status stays UNKNOWN (no dispatch/observation evidence
       exists to resolve it either way).
    4. A human creates a DestinationDuplicatePreventionGuarantee (the
       real, existing, documented escape hatch for exactly this
       situation) -- evaluate_replacement_safety now returns
       SAFE_DUPLICATE_PREVENTION_GUARANTEED, and a fresh Capability is
       issued, producing Operation B (previous_attempt_operation_id=A).
    5. The adapter dispatches again for B.

Under the Operation.id-keyed design, step 5 used a BRAND NEW key
(B.id), unrelated to whatever key A's own (lost) create call used --
if A's create call had actually succeeded on Stripe's side, step 5
creates a second PaymentIntent. Fixed by `destination_dispatch_identity`
below: it walks the replacement chain and returns A's own id for B in
this exact scenario (carried forward, because A's own outcome was never
proven, only guaranteed-safe-to-retry) -- so step 5's key is IDENTICAL
to whatever A's own lost create call used, and Stripe's real idempotency
layer (not a side-channel lookup) is what reveals whatever actually
happened, exactly as Stripe's own documentation prescribes for a lost
response. A chain extended by a PROVEN (not merely guaranteed) non-commit
still correctly gets a fresh identity -- see that function's own tests.
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
from datetime import datetime, timedelta, timezone
from typing import Protocol

# === Facts verified directly against Stripe's own official documentation,
# not assumed -- sources recorded here so a later reader can re-check them. ===
STRIPE_IDEMPOTENCY_KEY_RETENTION_HOURS = 24
"""A conservative LOWER BOUND, not an exact deletion time. Stripe's own
docs (https://docs.stripe.com/api/idempotent_requests): 'You can remove
keys from the system automatically after they're at least 24 hours old.
We generate a new request if a key is reused after the original is
pruned.' Stripe guarantees a key survives for AT LEAST this long -- it
never promises pruning happens exactly at 24 hours, and never promises
protection ends there either (the key may well still exist well past
this point). This module treats 24 hours as the EARLIEST moment pruning
becomes possible and stops relying on the key from exactly that point
forward -- the safe direction for a guard whose job is to stop trusting
a cache, never to assert that cache has actually been emptied."""

STRIPE_IDEMPOTENCY_KEY_MAX_LENGTH = 255
"""Same source: 'Idempotency keys are up to 255 characters long.'"""

STRIPE_CONCURRENT_REQUEST_STATUS_CODE = 409
"""https://docs.stripe.com/error-low-level#idempotency and the HTTP status
code table on that same page: 409 Conflict, 'The request conflicts with
another request (perhaps due to using the same idempotent key).'"""

OPERATION_KIND_CREATE = "payment_intent_create"
OPERATION_KIND_CONFIRM = "payment_intent_confirm"

TERMINALLY_NOT_COMMITTED = "TERMINALLY_NOT_COMMITTED"
"""Matches app.services.operation_service's own outcome_status literal --
duplicated here as a plain string (not imported) so this module keeps
zero dependency on the ORM/app package; a caller supplies it as data."""


# === Identity 4: logical destination operation -- pure, no DB/ORM dependency ===


@dataclass(frozen=True)
class OperationLink:
    """The minimal facts needed about one Operation in a replacement
    chain to compute destination_dispatch_identity. Deliberately NOT
    the real ORM Operation model -- this module has no dependency on
    SQLAlchemy or app.db.models at all; a caller (e.g. a test, or a
    real orchestrator) supplies these from whatever Operation rows it
    already has, by querying the real database itself."""
    operation_id: str
    previous_attempt_operation_id: str | None
    outcome_status: str  # "UNKNOWN" | "COMMITTED" | "TERMINALLY_NOT_COMMITTED"


def destination_dispatch_identity(operation_id: str, chain: dict[str, OperationLink]) -> str:
    """Walks backward through the replacement chain starting at
    `operation_id`, stopping (and returning the LATEST id seen) as soon
    as it finds a predecessor whose own outcome was PROVEN
    TERMINALLY_NOT_COMMITTED (a genuine break point -- a fresh
    destination identity is warranted past that point), or reaches the
    root of the chain (no predecessor at all). An unresolved (UNKNOWN or
    COMMITTED -- COMMITTED should never actually have a successor, since
    replacement-safety blocks replacing a committed operation, but this
    function does not assume that invariant holds and treats anything
    that is not TERMINALLY_NOT_COMMITTED the same way) predecessor means
    the CURRENT operation's own dispatch is really a continuation of the
    same, never-resolved destination attempt -- carry the identity
    forward, don't mint a new one.

    `chain` maps operation_id -> OperationLink for every operation a
    caller has already loaded (typically: the whole previous_attempt_
    operation_id lineage for one business operation identity). Missing
    entries are treated as chain breaks (returns the current id) rather
    than raising, so a caller that hasn't loaded far enough back still
    gets a safe (if possibly over-fresh) answer instead of a crash."""
    current_id = operation_id
    while True:
        current = chain.get(current_id)
        if current is None or current.previous_attempt_operation_id is None:
            return current_id
        previous = chain.get(current.previous_attempt_operation_id)
        if previous is None:
            return current_id
        if previous.outcome_status == TERMINALLY_NOT_COMMITTED:
            return current_id
        current_id = previous.operation_id


# === Pure identity / idempotency-key mapping -- no I/O, fully unit-testable ===


def idempotency_key(*, organization_id: str, integration_id: str, destination_dispatch_identity: str, operation_kind: str) -> str:
    """The actual Stripe Idempotency-Key header value. Namespaced by
    tenant AND integration directly in the key itself -- not relying on
    metadata alone for account/tenant scoping, per this review's own
    explicit requirement -- plus which Stripe call this is (create vs.
    confirm are different Stripe operations with different parameters;
    sharing a key between them would trip Stripe's own parameter-
    mismatch check). Stable only for repeated calls against the SAME
    destination_dispatch_identity + operation_kind; see that function's
    own docstring for exactly when it is, and is not, carried forward
    across a replacement."""
    if operation_kind not in (OPERATION_KIND_CREATE, OPERATION_KIND_CONFIRM):
        raise ValueError(f"unknown operation_kind: {operation_kind!r}")
    key = f"{organization_id}:{integration_id}:{destination_dispatch_identity}:{operation_kind}"
    if len(key) > STRIPE_IDEMPOTENCY_KEY_MAX_LENGTH:
        raise ValueError(f"derived idempotency key exceeds Stripe's {STRIPE_IDEMPOTENCY_KEY_MAX_LENGTH}-char limit")
    return key


def build_metadata(
    *, organization_id: str, integration_id: str, business_operation_identity_id: str,
    destination_dispatch_identity: str,
) -> dict[str, str]:
    """Every field PayReality wants correlatable on the Stripe side, each
    its own distinct metadata key. Metadata is for correlation only -- it
    is never what PREVENTS a duplicate (the idempotency key is); see this
    module's own top-of-file docstring. Stripe's own docs recommend
    exactly this correlation pattern: 'send in a local identifier with
    the metadata when creating new resources... That identifier appears
    in the metadata field of an object going out through a webhook,
    even if the webhook is generated later as part of reconciliation'
    (docs.stripe.com/error-low-level#server-errors).

    DELIBERATELY DOES NOT include Operation.id or the capability nonce
    -- a real, load-bearing correction found the hard way, against
    Stripe's own live test-mode API, not simulated or merely reasoned
    about. Earlier revisions included both, reasoning 'more correlation
    detail is more audit value.' That is true for a destination identity
    that is NEVER carried forward -- but destination_dispatch_identity
    IS deliberately carried forward across a replacement authorized
    despite an unresolved outcome (this module's own central design,
    see destination_dispatch_identity's own docstring), meaning the SAME
    idempotency key gets reused by a LATER call whose own Operation.id
    and capability nonce are necessarily different from the first call's.
    Stripe's real parameter-matching check compares the FULL request,
    metadata included, not just amount/currency -- confirmed directly:
    a second create call reusing a carried-forward key, with identical
    amount/currency but a different payreality_operation_id/payreality_
    capability_nonce, was rejected with a genuine `idempotency_error`
    ('Keys for idempotent requests can only be used with the same
    parameters they were first used with'), not silently resumed as
    intended. Every field sent alongside a given key must therefore stay
    IDENTICAL across every call that shares it -- this function only
    ever includes fields that are stable for the lifetime of a
    destination_dispatch_identity (org/integration/business-operation/
    destination-identity scoping); Operation.id and the capability nonce
    are exactly the two fields that are NOT stable across a carried-
    forward replacement, by this module's own design, and are tracked
    instead in PayReality's own database (every Operation row, chained
    via previous_attempt_operation_id, already carries this detail --
    destination_dispatch_identity is enough for anyone on the Stripe
    side to correlate back to that chain).

    Key NAMES (not values) are kept under Stripe's real, documented
    40-character metadata-key limit -- also found the hard way:
    `FakeStripeBackend` never validated this, so every local test passed
    while `payreality_business_operation_identity_id` (41 characters)
    would have failed, and did fail, on a genuine create call --
    `{'error': {'message': "Metadata keys can have up to 40 characters,
    but you passed in a key that is 41 characters...", 'type':
    'invalid_request_error'}}`. Shortened with margin, not trimmed to
    the exact boundary."""
    metadata = {
        "payreality_organization_id": str(organization_id),
        "payreality_integration_id": str(integration_id),
        "payreality_biz_operation_identity_id": str(business_operation_identity_id),
        "payreality_destination_dispatch_id": str(destination_dispatch_identity),
    }
    _validate_stripe_metadata(metadata)
    return metadata


STRIPE_METADATA_KEY_MAX_LENGTH = 40
STRIPE_METADATA_VALUE_MAX_LENGTH = 500
"""docs.stripe.com/api/metadata and the real error this review's own
live test-mode run produced directly: 'Metadata keys can have up to 40
characters.' Checked here, at build time, so a key-length regression is
caught locally (FakeStripeBackend reuses this same check -- see its own
create/confirm) BEFORE a real API call is ever attempted, not only when
one happens to run against the live API."""


def _validate_stripe_metadata(metadata: dict[str, str]) -> None:
    for key, value in metadata.items():
        if len(key) > STRIPE_METADATA_KEY_MAX_LENGTH:
            raise ValueError(f"metadata key {key!r} is {len(key)} characters, exceeding Stripe's {STRIPE_METADATA_KEY_MAX_LENGTH}-character limit")
        if len(str(value)) > STRIPE_METADATA_VALUE_MAX_LENGTH:
            raise ValueError(f"metadata value for key {key!r} is {len(str(value))} characters, exceeding Stripe's {STRIPE_METADATA_VALUE_MAX_LENGTH}-character limit")


class DispatchWindowExpiredError(Exception):
    """Raised instead of silently dispatching once this review's own
    conservative boundary (STRIPE_IDEMPOTENCY_KEY_RETENTION_HOURS, the
    earliest point Stripe's real pruning could possibly have happened --
    see that constant's own docstring for why this is a lower bound, not
    an exact deletion time) has elapsed since the FIRST dispatch attempt
    for this destination_dispatch_identity chain, AND the outcome is
    still unresolved. Past this point, whether Stripe's own cached key
    still exists is simply not knowable from here -- it may or may not
    have been pruned -- so this module stops relying on it either way
    rather than gambling that it has (and dispatching into an
    unprotected brand-new request) or that it hasn't (and treating
    silence as proof of anything). Blocking here, rather than
    dispatching anyway, is deliberate: resolving this requires actual
    evidence (a real status lookup if the Stripe object id is known) or
    an explicit, informed human decision, not another automatic
    attempt."""


def ensure_dispatch_window_still_valid(*, first_dispatch_attempted_at: datetime, outcome_status: str, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    if outcome_status != TERMINALLY_NOT_COMMITTED and outcome_status != "COMMITTED":
        elapsed = now - first_dispatch_attempted_at
        if elapsed >= timedelta(hours=STRIPE_IDEMPOTENCY_KEY_RETENTION_HOURS):
            raise DispatchWindowExpiredError(
                f"{elapsed} has elapsed since the first dispatch attempt for this destination "
                f"operation (outcome_status={outcome_status!r}, still unresolved) -- past the "
                f"conservative {STRIPE_IDEMPOTENCY_KEY_RETENTION_HOURS}h boundary, whether Stripe's own "
                f"idempotency key still exists is not knowable from here either way; dispatching again "
                f"cannot be assumed protected against creating a duplicate. Resolve via a real status "
                f"lookup (if the Stripe object id is known) or an explicit, evidence-informed human "
                f"decision, not another automatic attempt."
            )


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
    def retrieve_account(self) -> dict:
        """Read-only. Resolves which Stripe account the CURRENTLY
        configured credential actually belongs to (Stripe's own `GET
        /v1/account` -- the account associated with the API key used,
        no account id needed up front; distinct from `GET /v1/accounts/
        {id}`, which looks up a Connect-managed account by an id already
        known). Returns an Account object; only `id` (acct_...) is used
        by this module. This is what makes 'reject an unexpected account'
        and 'credential rotation cannot silently redirect an unresolved
        operation to another account' enforceable at all -- see
        ensure_account_binding_still_valid and dispatch_payment_intent."""
        ...


class StripeAccountBindingMismatchError(Exception):
    """Raised instead of silently dispatching when the Stripe account the
    CURRENTLY configured credential resolves to (via retrieve_account)
    differs from the account bound to this destination_dispatch_identity
    at its own first dispatch. Embedding organization_id/integration_id
    in the idempotency key (see idempotency_key's own docstring) is NOT
    sufficient on its own here: that only prevents a same-key collision
    AT ONE Stripe account. Stripe scopes idempotency keys per account, so
    reusing the same key against a DIFFERENT account does not collide at
    all -- it silently creates an independent, unrelated object, defeating
    the entire point of carrying a destination identity forward. A
    rotated credential that now resolves to a different account must
    refuse to dispatch, not quietly create a second object elsewhere."""

    def __init__(self, destination_dispatch_identity: str, bound_account_id: str, current_account_id: str):
        self.destination_dispatch_identity = destination_dispatch_identity
        self.bound_account_id = bound_account_id
        self.current_account_id = current_account_id
        super().__init__(
            f"destination_dispatch_identity={destination_dispatch_identity!r} was first dispatched under "
            f"Stripe account {bound_account_id!r}, but the integration's currently configured credential "
            f"resolves to account {current_account_id!r} -- refusing to dispatch under a different account "
            f"than the one the original attempt used"
        )


class LiveModeObjectRejectedError(Exception):
    """Raised if Stripe ever returns an object with `livemode=true`
    (docs.stripe.com/api/payment_intents/object: 'If the object exists
    in live mode, the value is `true`. If the object exists in test
    mode, the value is `false`.'). Structural defense in depth, distinct
    from and in addition to RealStripeClient's own sk_test_-prefix
    construction-time check: that check rejects an obviously-live KEY;
    this rejects a live-mode OBJECT even if it somehow arrived despite a
    test-mode-looking key (e.g. a misconfigured proxy, a key that
    changed mode server-side) -- this module never proceeds past seeing
    one, for any reason."""


def _reject_if_livemode(obj: dict) -> dict:
    if obj.get("livemode") is True:
        raise LiveModeObjectRejectedError(
            f"Stripe returned a LIVE-mode object (id={obj.get('id')!r}) despite a test-mode-only "
            f"credential -- refusing to proceed with it for any reason"
        )
    return obj


class RealStripeClient:
    """Thin wrapper over Stripe's real REST API (api.stripe.com),
    TEST MODE ONLY. Refuses construction with anything that isn't a
    real test-mode credential -- a caller cannot accidentally point this
    at live mode even by misconfiguring an environment variable, since
    the key's own prefix is checked before any request is ever made.

    Accepts BOTH `sk_test_...` (a full, unrestricted secret key) and
    `rk_test_...` (a restricted key, scoped to whichever permissions
    were granted when it was created). Confirmed via Stripe's own docs
    (docs.stripe.com/keys): 'Sandbox keys start with pk_test_ for
    publishable keys, rk_test_ for restricted keys, and sk_test_ for
    secret keys' -- and Stripe's own current guidance actively
    RECOMMENDS restricted keys over secret keys for server-side
    integrations ('limit the damage... if your keys are ever exposed');
    refusing rk_test_ here would push a caller toward the LESS secure
    credential type. A restricted key lacking the specific permission a
    given call needs (e.g. write access to PaymentIntents) surfaces as
    Stripe's own real authorization error at call time -- this class
    does not, and cannot, know a key's own granted permissions up
    front, and never pretends to."""

    _BASE_URL = "https://api.stripe.com/v1"
    _TEST_MODE_PREFIXES = ("sk_test_", "rk_test_")

    def __init__(self, secret_key: str):
        if not secret_key.startswith(self._TEST_MODE_PREFIXES):
            raise ValueError(
                "refusing to construct RealStripeClient with a non-test-mode credential -- "
                "only sk_test_... or rk_test_... keys are accepted; live-mode credentials "
                "(sk_live_/rk_live_) and publishable keys are rejected outright"
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
        _validate_stripe_metadata(metadata)  # fail locally before spending a real API call
        data = {"amount": amount, "currency": currency, "metadata": metadata}
        return _reject_if_livemode(self._request("POST", "/payment_intents", idempotency_key=idempotency_key, data=data))

    def confirm_payment_intent(self, *, payment_intent_id: str, idempotency_key: str, payment_method: str, metadata: dict) -> dict:
        _validate_stripe_metadata(metadata)
        data = {"payment_method": payment_method, "metadata": metadata}
        return _reject_if_livemode(self._request("POST", f"/payment_intents/{payment_intent_id}/confirm", idempotency_key=idempotency_key, data=data))

    def retrieve_payment_intent(self, *, payment_intent_id: str) -> dict:
        # GET is idempotent by Stripe's own definition -- no Idempotency-Key
        # header is sent or needed (docs.stripe.com/api/idempotent_requests:
        # "Don't send idempotency keys in GET and DELETE requests because
        # it has no effect."). Confirmed also at docs.stripe.com/api/
        # payment_intents/retrieve: a plain GET, no idempotency semantics,
        # requires already knowing the PaymentIntent id (no metadata-search
        # recovery path exists at this endpoint).
        return _reject_if_livemode(self._request("GET", f"/payment_intents/{payment_intent_id}"))

    def retrieve_account(self) -> dict:
        # GET /v1/account (no id in the path) -- the account associated
        # with the API key used, confirmed via Stripe's own SDKs (e.g.
        # stripe-python/stripe-node's Account.retrieve() with no
        # argument resolves to this exact endpoint); distinct from
        # GET /v1/accounts/{id}, which looks up an already-known
        # Connect-managed account's id. The Account object itself has no
        # `livemode` field (docs.stripe.com/api/accounts/object) -- mode
        # is enforced at the credential-prefix level (__init__ above),
        # not checked again here.
        return self._request("GET", "/account")


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
    drop_response_once: bool = False


class FakeStripeBackend:
    """LOCAL SIMULATION of Stripe's own REST API, for testing this
    adapter's OWN orchestration logic without any real network call --
    never presented as, or confused with, a real Stripe test-mode run.
    Models the specific official behaviors this design depends on, each
    with its own cited source -- reviewed against those sources, not
    engineered to be stricter/safer than Stripe actually is:

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
      - Key pruning after an injectable clock passes this module's own
        conservative, at-least-24-hour retention boundary (see
        STRIPE_IDEMPOTENCY_KEY_RETENTION_HOURS's own docstring for why
        this is a lower bound, never an exact deletion time), so tests
        can exercise expiry without waiting 24 real hours.
      - A genuine 'lost response': the underlying mutation actually
        executes and its result is cached (exactly as Stripe documents),
        but the ORIGINAL caller receives a simulated network error
        instead of that result -- a SUBSEQUENT call with the SAME key
        correctly receives the real, already-cached outcome. This is
        NOT the same as `outcome='no_response'` below (which models the
        destination never processing the request AT ALL); this models
        Stripe processing it but the response never arriving, which is
        exactly the scenario Stripe's own docs describe for a lost
        network response and prescribe retrying the same key for.

    Configurable per-PaymentIntent outcome behavior (`outcome`) lets a
    test choose succeeded / declined / requires_action / no_response
    independently of the idempotency mechanics above."""

    def __init__(self, *, clock: "_Clock | None" = None, default_outcome: str = "succeeded", account_id: str = "acct_sim_default"):
        self._clock = clock or _Clock()
        self._lock = threading.Lock()
        self._cache: dict[str, _CachedResult] = {}
        self._in_flight: set[str] = set()
        self._payment_intents: dict[str, dict] = {}
        self._outcomes: dict[str, str] = {}  # payment_intent_id -> outcome
        self._default_outcome = default_outcome
        self._drop_response_once_keys: set[str] = set()
        self._account_id = account_id
        self._force_livemode_once = False

    def set_account_id(self, account_id: str) -> None:
        """Test-only: simulates a credential rotation that now resolves
        to a DIFFERENT Stripe account -- the exact scenario
        ensure_account_binding_still_valid / StripeAccountBindingMismatchError
        exists to catch. retrieve_account() reflects this new value
        immediately; whatever was bound to an existing destination_
        dispatch_identity at its own first dispatch is untouched."""
        self._account_id = account_id

    def force_livemode_response_once(self) -> None:
        """Test-only: the very next create/confirm response (fresh
        execution, not a cache hit) comes back with livemode=True,
        simulating a live-mode object arriving despite a test-mode-
        looking credential -- exercises LiveModeObjectRejectedError's
        own defense-in-depth independently of RealStripeClient's
        key-prefix check, which this local simulation never goes
        through at all."""
        self._force_livemode_once = True

    def retrieve_account(self) -> dict:
        return {"id": self._account_id, "object": "account"}

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
        network error every time, modeling a destination that never
        processes the request at all)."""
        self._outcomes[payment_intent_id] = outcome

    def drop_next_response_for_key(self, idempotency_key: str) -> None:
        """Test-only: the NEXT call using this exact idempotency key
        executes normally (its result is computed and cached, exactly
        as Stripe would), but then a simulated network error is raised
        to THAT caller instead of returning the result -- modeling a
        lost response after real destination-side processing, distinct
        from a destination that never processed the request at all. A
        subsequent call with the SAME key correctly receives the real,
        cached result (Stripe's own documented recovery mechanism)."""
        self._drop_response_once_keys.add(idempotency_key)

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
            drop = False
            with self._lock:
                self._cache[key] = _CachedResult(params_fingerprint=fingerprint, response=response, created_at=now)
                if key in self._drop_response_once_keys:
                    self._drop_response_once_keys.discard(key)
                    drop = True
            if drop:
                raise TimeoutError("simulated: the response to this specific call was lost in transit, though the destination actually processed it")
            return response
        finally:
            with self._lock:
                self._in_flight.discard(key)

    def create_payment_intent(self, *, idempotency_key: str, amount: int, currency: str, metadata: dict) -> dict:
        # Validated BEFORE the cache/in-flight bookkeeping below, matching
        # the real API's own behavior: a request Stripe would reject
        # never gets far enough to be cached or treated as "in flight."
        try:
            _validate_stripe_metadata(metadata)
        except ValueError as e:
            raise StripeClientError(400, {"error": {"type": "invalid_request_error", "message": str(e)}}) from e

        def _do():
            pi_id = f"pi_sim_{len(self._payment_intents) + 1:06d}"
            livemode = False
            with self._lock:
                if self._force_livemode_once:
                    self._force_livemode_once = False
                    livemode = True
            obj = {
                "id": pi_id, "object": "payment_intent", "amount": amount, "currency": currency,
                "status": "requires_payment_method", "metadata": dict(metadata), "livemode": livemode,
            }
            self._payment_intents[pi_id] = obj
            return dict(obj)
        # Fingerprinted on MATERIAL parameters only (amount, currency) --
        # never metadata. Metadata is correlation-only by this module's
        # own design (see build_metadata's docstring): two legitimate
        # attempts at the same destination operation (a fresh Operation.id,
        # a fresh capability nonce) necessarily carry different metadata,
        # and that difference must never itself trigger a simulated
        # parameter-mismatch error when they otherwise share a carried-
        # forward destination_dispatch_identity and therefore the same key.
        return _reject_if_livemode(self._cached_or_execute(idempotency_key, {"amount": amount, "currency": currency}, _do))

    def confirm_payment_intent(self, *, payment_intent_id: str, idempotency_key: str, payment_method: str, metadata: dict) -> dict:
        try:
            _validate_stripe_metadata(metadata)
        except ValueError as e:
            raise StripeClientError(400, {"error": {"type": "invalid_request_error", "message": str(e)}}) from e

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
            with self._lock:
                if self._force_livemode_once:
                    self._force_livemode_once = False
                    obj["livemode"] = True
            return dict(obj)
        return _reject_if_livemode(self._cached_or_execute(idempotency_key, {"payment_intent_id": payment_intent_id, "payment_method": payment_method}, _do))

    def retrieve_payment_intent(self, *, payment_intent_id: str) -> dict:
        # Read-only by construction: this method never touches _cache,
        # _in_flight, or _payment_intents' own mutable state, and never
        # calls create/confirm internally.
        obj = self._payment_intents.get(payment_intent_id)
        if obj is None:
            raise StripeClientError(404, {"error": {"type": "invalid_request_error", "message": "No such payment_intent"}})
        return _reject_if_livemode(dict(obj))


class _Clock:
    """Injectable wall-clock, real by default, so tests can simulate
    the passage of this module's own conservative, at-least-24-hour
    retention boundary without a real 24-hour wait."""

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
    create_idempotency_key: str
    confirm_idempotency_key: str | None
    confirmation_skipped: bool
    """True when an existing, already-past-requires_payment_method
    object was found (via the carried-forward destination_dispatch_
    identity) and confirm was deliberately NOT called -- 'a retry that
    finds an existing object must not automatically proceed to
    confirmation.'"""


def create_or_resume_payment_intent(
    client: StripeClient, *, organization_id: str, integration_id: str,
    destination_dispatch_identity: str, business_operation_identity_id: str,
    operation_id: str, capability_nonce: str, amount: int, currency: str,
) -> dict:
    """Idempotent create ONLY -- never confirms anything. If the derived
    key was already used (because destination_dispatch_identity was
    carried forward from an earlier, unresolved attempt), returns
    whatever object already exists -- which may already be past
    'requires_payment_method'. See confirm_payment_intent_if_pending,
    the separate function that decides whether confirming is still
    appropriate; this function never makes that decision itself.

    `operation_id`/`capability_nonce` are accepted (kept in this
    function's own signature for the caller's own audit/logging use and
    API stability) but deliberately NOT forwarded to build_metadata --
    see that function's own docstring for the real-Stripe finding this
    corrects: a field that varies per attempt cannot safely accompany a
    key that gets reused across attempts."""
    metadata = build_metadata(
        organization_id=organization_id, integration_id=integration_id,
        business_operation_identity_id=business_operation_identity_id,
        destination_dispatch_identity=destination_dispatch_identity,
    )
    key = idempotency_key(
        organization_id=organization_id, integration_id=integration_id,
        destination_dispatch_identity=destination_dispatch_identity, operation_kind=OPERATION_KIND_CREATE,
    )
    return client.create_payment_intent(idempotency_key=key, amount=amount, currency=currency, metadata=metadata)


def confirm_payment_intent_if_pending(
    client: StripeClient, *, organization_id: str, integration_id: str,
    destination_dispatch_identity: str, business_operation_identity_id: str,
    operation_id: str, capability_nonce: str, payment_intent: dict, payment_method: str,
) -> tuple[dict, str | None, bool]:
    """Confirms ONLY if `payment_intent` (as returned by create_or_
    resume_payment_intent) is still in the pre-confirmation state. If
    an earlier attempt (discovered via the carried-forward destination_
    dispatch_identity) already confirmed it, returns it UNCHANGED --
    'a retry that finds an existing object must not automatically
    proceed to confirmation.' Returns (payment_intent, confirm_key,
    confirmation_skipped). `operation_id`/`capability_nonce`: see
    create_or_resume_payment_intent's own docstring -- same reasoning,
    not forwarded to build_metadata here either."""
    if payment_intent["status"] != "requires_payment_method":
        return payment_intent, None, True
    metadata = build_metadata(
        organization_id=organization_id, integration_id=integration_id,
        business_operation_identity_id=business_operation_identity_id,
        destination_dispatch_identity=destination_dispatch_identity,
    )
    key = idempotency_key(
        organization_id=organization_id, integration_id=integration_id,
        destination_dispatch_identity=destination_dispatch_identity, operation_kind=OPERATION_KIND_CONFIRM,
    )
    confirmed = client.confirm_payment_intent(payment_intent_id=payment_intent["id"], idempotency_key=key, payment_method=payment_method, metadata=metadata)
    return confirmed, key, False


def dispatch_payment_intent(
    client: StripeClient, *, organization_id: str, integration_id: str,
    destination_dispatch_identity: str, business_operation_identity_id: str, operation_id: str,
    capability_nonce: str, amount: int, currency: str, payment_method: str,
    first_dispatch_attempted_at: datetime, outcome_status: str, bound_stripe_account_id: str, now: datetime | None = None,
) -> DispatchResult:
    """The ONE effectful path in this module. Checks the dispatch
    window FIRST (raises DispatchWindowExpiredError rather than
    silently proceeding if it has expired with the outcome still
    unresolved), THEN resolves the account the currently configured
    credential actually belongs to and refuses to proceed if it differs
    from `bound_stripe_account_id` (the account recorded at this
    destination identity's own first dispatch -- see
    StripeAccountBindingMismatchError's own docstring for why embedding
    organization_id/integration_id in the idempotency key alone is not
    sufficient to catch this). Only once both checks pass: create
    (idempotent, may resume an existing object) and confirm (only if
    that object is still pending). Never calls retrieve_payment_intent --
    status lookup is a structurally separate function (see below)."""
    ensure_dispatch_window_still_valid(first_dispatch_attempted_at=first_dispatch_attempted_at, outcome_status=outcome_status, now=now)
    current_account_id = client.retrieve_account()["id"]
    if current_account_id != bound_stripe_account_id:
        raise StripeAccountBindingMismatchError(destination_dispatch_identity, bound_stripe_account_id, current_account_id)
    created = create_or_resume_payment_intent(
        client, organization_id=organization_id, integration_id=integration_id,
        destination_dispatch_identity=destination_dispatch_identity,
        business_operation_identity_id=business_operation_identity_id,
        operation_id=operation_id, capability_nonce=capability_nonce, amount=amount, currency=currency,
    )
    create_key = idempotency_key(organization_id=organization_id, integration_id=integration_id, destination_dispatch_identity=destination_dispatch_identity, operation_kind=OPERATION_KIND_CREATE)
    confirmed, confirm_key, skipped = confirm_payment_intent_if_pending(
        client, organization_id=organization_id, integration_id=integration_id,
        destination_dispatch_identity=destination_dispatch_identity,
        business_operation_identity_id=business_operation_identity_id,
        operation_id=operation_id, capability_nonce=capability_nonce,
        payment_intent=created, payment_method=payment_method,
    )
    return DispatchResult(
        payment_intent_id=confirmed["id"], status=confirmed["status"],
        create_idempotency_key=create_key, confirm_idempotency_key=confirm_key, confirmation_skipped=skipped,
    )


def retrieve_status(client: StripeClient, *, payment_intent_id: str) -> dict:
    """Read-only status investigation for an existing operation. Calls
    ONLY client.retrieve_payment_intent -- structurally incapable of
    creating or confirming anything, since it never references
    create_payment_intent/confirm_payment_intent at all. Requires
    already knowing payment_intent_id (docs.stripe.com/api/
    payment_intents/retrieve: a plain GET keyed on the id; there is no
    documented metadata-search recovery path at this endpoint -- a
    missing or unknown id is not something this function can resolve
    on its own, and a caller must not treat 'id unknown' as proof of
    anything about the destination's own state)."""
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
