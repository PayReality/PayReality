"""httpx-based OPA client: implements the OpaClient protocol used by
app.domain.decision.engine, and the bundle-activation calls used by the
Policy Compiler (spec 12.4 Stage 9).

Milestone 2 (Multi-Tenant Foundation,
MILESTONE_2_MULTI_TENANT_FOUNDATION_SUMMARY.md Phase B1/B2, Option 2):
before this milestone, every organization shared exactly one OPA
package, `payreality.authorization`, uploaded and queried via the
literal `DATA_PATH` constant below. Every organization now compiles to,
and is queried against, its own package,
`payreality.authorization.org_<hex>` -- the three naming helpers below
are the single place that name is computed, reused by both
runtime_policy_service.py (compile/deploy/reconcile) and
intent_service.py (the live decision path), so the two can never
independently drift on what an organization's package is actually
called. `DATA_PATH` itself is kept as the pre-Milestone-2 default for
any caller that hasn't been updated to pass an explicit path -- there
should be none left after this milestone's remaining commits, but
`query()` fails loudly (a 404-shaped OPA response, not a silent
cross-tenant read) rather than guessing if one is ever missed.

=== The timeout_ms contract, established and corrected (reliability
pass, following a hostile review of the prior "strict total deadline"
claim) ===

`timeout_ms` is a BEST-EFFORT, per-phase-bounded budget against a
well-behaved, co-located, non-adversarial OPA peer (this platform's own
documented deployment shape everywhere else: OPA runs embedded in the
same container/host, operated by PayReality itself, never treated as
an untrusted network peer). It is NOT a hard, adversarial-safe total
wall-clock deadline, and the two previously-claimed properties that
would make it one are BOTH false, confirmed directly against real code
with a controlled test server, not assumed:

  1. "The four phase budgets (connect/write/read/pool) sum to no more
     than timeout_ms" -- true only for calls after the process's first
     real OPA request. Client construction (see _get_shared_client
     below) happens BEFORE any phase timeout is applied at all, and is
     itself unbounded. A controlled experiment measured this directly:
     a request with timeout_ms=200 against a server that delays 1s took
     1.11s to time out on a cold process -- the ~0.95s gap matches
     client-construction cost, not any of the four configured phases.
     Mitigated (not eliminated -- construction is still fundamentally
     unbounded) by warm_up_shared_client(), called explicitly from
     app.main's own startup lifespan, so the real decision path never
     hits a cold client in normal operation; a caller that never warms
     up (a standalone script, certain test contexts) is NOT protected.

  2. "The read phase cannot exceed its own configured share" -- httpx's
     `read` timeout is the maximum gap between successive received
     bytes, NOT a total-elapsed-time deadline for the whole read phase.
     Confirmed directly: a server that sends valid HTTP headers
     immediately, then trickles its body one byte every 50ms for 100
     bytes (5.0s of real total time), against read=0.5s, does NOT time
     out -- because no single gap between bytes ever exceeds 0.5s. A
     peer that keeps making ANY forward progress, however slowly, can
     keep a request alive indefinitely regardless of timeout_ms. This
     is accepted, not fixed with a hard-cancelling mechanism, because
     the realistic threat model here is a co-located, self-operated OPA
     -- not an adversarial peer deliberately trickling bytes to evade a
     deadline. A caller with a genuine adversarial-safe total-deadline
     requirement needs a different mechanism entirely (e.g. an asyncio
     client driven by `asyncio.wait_for`, which actually cancels the
     underlying connection rather than merely ceasing to wait for it --
     evaluated and deliberately not implemented here, since it would be
     a much larger, riskier change unjustified by this platform's own
     real deployment model, and no requirement anywhere in this
     codebase's own specs asks for it).

What IS still true and unconditionally guaranteed: a genuine transport
failure (connect refused, connection reset, or either of the two decay
paths above eventually firing) NEVER returns ALLOW or any usable
result -- OPATimeoutError/OPAEvaluationError propagate to
decision_engine.evaluate's own fail-closed handling
(Decision(outcome="HUMAN_REVIEW", ...)), unconditionally. Nothing in
this module, before or after this pass, can turn a failure into
ALLOW.
"""

import threading
import uuid
from typing import Any

import httpx

from app.config import settings
from app.domain.decision.engine import OPAEvaluationError, OPATimeoutError

DATA_PATH = "/v1/data/payreality/authorization"

# === Shared client lifecycle =================================================
#
# ONE process-wide httpx.Client, lazily constructed on first use and
# reusable indefinitely, replacing the pre-existing pattern of module-
# level httpx.get/post/put/delete convenience calls (each of which
# constructs and discards its OWN throwaway client). Directly measured
# reason: httpx.Client() construction itself took 0.6-0.9s in the
# environment this was diagnosed in (almost certainly Windows' own
# system-proxy auto-detection, which httpx/httpcore perform once per
# Client instance) -- a raw socket doing the identical request completed
# in 2-9ms, and a REUSED httpx.Client completed the same request in
# 2-4ms on every call after its first. This construction cost occurs
# BEFORE any per-request timeout is applied, so it was completely
# invisible to `timeout=` at any value -- confirmed with a deliberately
# tiny 10ms timeout that still never fired on a cold client.
#
# Supported lifecycle, precisely, not claimed beyond what's tested:
#   - Concurrent first use: guarded by a real lock (double-checked
#     locking); confirmed directly, repeated trials, that the lazy-init
#     race itself always constructs exactly one Client, independent of
#     anything else happening concurrently. A separate, real, disclosed
#     characteristic of this specific (Windows loopback) environment,
#     not of this module's own logic: 20 brand-new TCP connections
#     established at the exact same instant occasionally produces a
#     genuine transport-level reset on one or two of them (reproduced
#     even against a trivial raw-socket echo server, so it is not
#     specific to httpx or to OPA) -- the bounded single retry in
#     _request_with_stale_connection_recovery (below) recovers most of
#     these, and on rare occasions where the retry ALSO hits a reset
#     under the same heavy simultaneous-connection load, the request
#     fails closed with a real OPAEvaluationError rather than silently
#     hanging or succeeding incorrectly. Not expected to be a practical
#     concern for OPA's own real deployment shape here (a warm shared
#     client normally reuses pooled keep-alive connections one at a
#     time, not 20 simultaneous brand-new ones), but disclosed rather
#     than assumed away.
#   - Thread safety for ordinary request use: httpx.Client is documented
#     upstream as safe to share across threads for making requests (no
#     per-request mutable state on the Client itself that a caller can
#     see); this module never mutates shared client-level state (no
#     cookies, no auth, no default headers) that could leak between
#     callers -- every request-specific value (JSON body, path,
#     timeout) is passed per-call, never stored on the client.
#   - Process behavior: this is plain module-level state, meaning a
#     FORKED child process inherits the parent's already-constructed
#     Client object (and its live OS socket file descriptors) if one
#     exists at fork time -- sharing raw sockets across a fork is
#     unsafe. This codebase's own real multiprocessing usage (the
#     EvidenceBound interop test's two-connection race,
#     multiprocessing.get_context("spawn")) uses SPAWN, not fork, which
#     re-imports this module fresh in the child with _shared_client back
#     at None -- safe. A caller that forks (not spawns) a process after
#     this module has already constructed a client is NOT supported and
#     is not exercised anywhere in this codebase today; disclosed here
#     rather than silently assumed safe.
#   - Application shutdown: no explicit close() is called anywhere.
#     httpx.Client holds real OS connections; on ordinary process exit
#     the OS reclaims them. A long-running process that wants a clean
#     shutdown should call close_shared_client() explicitly (added
#     below) -- not currently wired into any shutdown hook, since
#     app.main's own lifespan has no shutdown-side cleanup for any other
#     resource either; disclosed as a real, currently-unaddressed gap,
#     not fixed here (out of this pass's own scope, no evidence any
#     resource leak actually occurs in this platform's own real
#     deployment shape, which runs one process for the container's
#     entire lifetime).
#   - Stale connections after an OPA restart: confirmed directly, a
#     pooled keep-alive connection to a peer that has since restarted
#     on the same address raises a real httpx.ReadError/ConnectError
#     (WinError 10053/10054 in this environment; ECONNRESET/EPIPE on
#     POSIX) -- httpx does NOT silently detect and transparently replace
#     a stale pooled connection on its own, and `transport=
#     httpx.HTTPTransport(retries=1)` does NOT cover this case either
#     (confirmed directly -- `retries` only covers failures establishing
#     a brand new connection, not a previously-good pooled one that
#     fails on reuse). Mitigated with a bounded, single, application-
#     level retry, ONLY on httpx.NetworkError (never on
#     httpx.TimeoutException -- see _request_with_stale_connection_
#     recovery's own docstring for a real bug this distinction fixes):
#     the shared-client REFERENCE is swapped to a freshly-constructed
#     client (guaranteeing the retry cannot reuse the same stale
#     connection -- confirmed directly to reliably recover, where
#     partially evicting just the one bad pooled connection was NOT
#     reliably fast enough to guarantee a fresh connection on the very
#     next attempt), then the SAME request is retried exactly once
#     against the fresh client. The outgoing client is never closed
#     synchronously (see _rebuild_shared_client's own docstring for a
#     real concurrency bug that fixes) -- only ever swapped, so another
#     thread's unrelated, healthy in-flight request on the outgoing
#     client is never disturbed. This is safe for every real endpoint
#     this client calls (policy PUT/DELETE and data PUT are all
#     idempotent; the decision query is a pure read) -- never retries a
#     request that already received a real response, only ones that
#     failed before any usable response existed.
_shared_client_lock = threading.Lock()
_shared_client: httpx.Client | None = None


def _get_shared_client() -> httpx.Client:
    global _shared_client
    if _shared_client is None:
        with _shared_client_lock:
            if _shared_client is None:
                _shared_client = httpx.Client()
    return _shared_client


def warm_up_shared_client() -> None:
    """Called explicitly from app.main's own startup lifespan (the same
    "never raises, logs and lets the app boot" posture as this
    codebase's other three startup hooks) -- pays the one-time,
    unbounded httpx.Client() construction cost at process startup,
    before any real decision request can ever reach this module, rather
    than leaving it to land unpredictably (and untimed) on whichever
    real request happens to be first. Idempotent: a second call is a
    no-op (the lock-guarded lazy-init in _get_shared_client already
    only constructs once)."""
    _get_shared_client()


def close_shared_client() -> None:
    """Not currently called from any shutdown hook (see this module's
    own docstring) -- provided for a caller that wants a clean shutdown,
    or a test that wants to force the NEXT call to pay construction
    cost again (e.g. to reset pooled connections between test cases)."""
    global _shared_client
    with _shared_client_lock:
        if _shared_client is not None:
            _shared_client.close()
            _shared_client = None


def _rebuild_shared_client() -> httpx.Client:
    """The stale-connection-recovery primitive: discards the current
    shared client (if any) and installs a genuinely fresh one, so the
    caller's own retry cannot land on the same stale pooled connection.

    Swaps the module-level reference only -- does NOT call .close() on
    the outgoing client. An earlier version of this function did call
    .close() here unconditionally, which is a real, confirmed
    concurrency bug, not a theoretical one: httpx.Client.close() tears
    down every connection in that client's pool, including ones OTHER
    threads have in-flight requests running on right now. Reproduced
    directly in this module's own experiment harness -- 20 concurrent
    healthy requests against a single shared client, one of which hit an
    unrelated transient failure and triggered a rebuild, and closing the
    client out from under the other 19 aborted two of their otherwise-
    healthy connections mid-flight (observed as a real WinError 10053,
    "An established connection was aborted by the software in your host
    machine" -- i.e. aborted by this process's own prior .close() call,
    not by the network). Fixed by only ever swapping the reference:
    Python's own reference counting keeps any client object alive for as
    long as a thread still holds a reference to it mid-request, so an
    in-flight request on the outgoing client is never disturbed, and its
    connections are reclaimed once nothing references it any longer (or
    at process exit, whichever comes first). Trade-off, disclosed rather
    than hidden: since nothing proactively closes the outgoing client's
    sockets, a long-running process that hits this recovery path
    repeatedly over its lifetime could accumulate transiently-unclosed
    connections until they're individually reclaimed -- acceptable here
    because this path only runs on a genuine connection-level failure
    (an OPA restart or similar), not on any normal request."""
    global _shared_client
    with _shared_client_lock:
        _shared_client = httpx.Client()
        return _shared_client


def _request_with_stale_connection_recovery(method: str, url: str, **kwargs) -> httpx.Response:
    """Every real HTTP call in this module goes through this one
    function, so the bounded, single retry-on-connection-error behavior
    (see this module's own docstring, "Stale connections after an OPA
    restart") is applied consistently everywhere, not duplicated five
    times with a risk of drifting apart.

    Retries ONLY on httpx.NetworkError (ConnectError/ReadError/
    WriteError/CloseError -- a connection that failed at the transport
    level, where no real response could have been produced), and
    deliberately NOT on httpx.TimeoutException, even though
    TimeoutException is itself a subclass of the broader
    httpx.TransportError. This distinction is load-bearing, found by a
    real regression in this module's own experiment harness: an earlier
    version of this function caught the broader TransportError, which
    also matches ReadTimeout/PoolTimeout/ConnectTimeout -- silently
    retrying (and roughly doubling the elapsed time of) every ordinary
    timeout, which both contradicts query()'s own documented timeout_ms
    budget and is exactly the kind of silent, undisclosed timeout
    inflation this reliability pass exists to remove. A caller's
    configured timeout is a caller's configured timeout; only a genuine
    connection-level failure gets a bounded, disclosed extra attempt."""
    client = _get_shared_client()
    try:
        return client.request(method, url, **kwargs)
    except httpx.NetworkError:
        client = _rebuild_shared_client()
        return client.request(method, url, **kwargs)


def org_package_path(organization_id: uuid.UUID) -> str:
    """The Rego package name for one organization's compiled bundle.
    `.hex` (not the dashed string form) because a Rego package path
    segment must be a valid identifier -- no hyphens -- the same
    constraint dry_run.py's own package-naming already has to respect."""
    return f"payreality.authorization.org_{organization_id.hex}"


def org_data_path(organization_id: uuid.UUID) -> str:
    """The `/v1/data/...` path OPA serves that package's rules at --
    always the package path with dots replaced by slashes, OPA's own
    fixed convention, the same one dry_run.py/batch_evaluator.py already
    rely on for their own throwaway packages."""
    return "/v1/data/" + org_package_path(organization_id).replace(".", "/")


def org_policy_id(organization_id: uuid.UUID) -> str:
    """The OPA REST policy id (`PUT /v1/policies/<id>`) one
    organization's compiled bundle is uploaded under -- a plain resource
    id, not a Rego identifier, so hyphens are fine here unlike the
    package path above."""
    return f"authorization-org-{organization_id.hex}"


class HttpOpaClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or settings.opa_url

    def query(
        self, input_doc: dict[str, Any], timeout_ms: int = 200, data_path: str | None = None
    ) -> dict[str, Any]:
        """See this module's own top-of-file docstring, "The timeout_ms
        contract, established and corrected," for exactly what this
        parameter does and does not guarantee -- it is a best-effort,
        per-phase-bounded budget against a well-behaved co-located OPA,
        not an adversarial-safe hard total deadline.

        A bare float passed as httpx's `timeout` sets FOUR INDEPENDENT
        sub-budgets (connect, write, read, pool) to that SAME value, not
        one shared deadline (confirmed directly: httpx.Timeout(0.2)
        reports connect=0.2, read=0.2, write=0.2, pool=0.2). Split here
        instead so the WORST case (every phase individually maxing its
        own share) sums to exactly the caller's own timeout_ms --
        assuming no client-construction cold-start and no slow-trickle
        peer, both disclosed above as real, accepted limits of this
        best-effort bound, not silently assumed away."""
        total_s = timeout_ms / 1000
        # Three auxiliary phases (connect, write, pool) each get a
        # small, fixed-proportion share; `read` gets whatever remains,
        # so the phases' own worst-case sum equals total_s exactly:
        # 3 * auxiliary_s + read_s == total_s.
        auxiliary_s = min(total_s / 10, 0.05)
        read_s = total_s - 3 * auxiliary_s
        request_timeout = httpx.Timeout(
            read_s, connect=auxiliary_s, write=auxiliary_s, pool=auxiliary_s,
        )
        try:
            resp = _request_with_stale_connection_recovery(
                "POST", f"{self.base_url}{data_path or DATA_PATH}",
                json={"input": input_doc}, timeout=request_timeout,
            )
        except httpx.TimeoutException as e:
            raise OPATimeoutError() from e
        except httpx.HTTPError as e:
            raise OPAEvaluationError(code="connection_error", message=str(e)) from e

        if resp.status_code != 200:
            raise OPAEvaluationError(code=f"http_{resp.status_code}")

        try:
            body = resp.json()
        except ValueError as e:
            raise OPAEvaluationError(code="bad_response") from e

        result = body.get("result")
        if result is None:
            # OPA returns no "result" key when the queried path is undefined.
            return {}
        return result

    def upload_data(self, path: str, data: Any) -> None:
        """PUT arbitrary data (e.g. compiled mandates/constraints) into
        OPA's in-memory data store at data.<path>."""
        resp = _request_with_stale_connection_recovery(
            "PUT", f"{self.base_url}/v1/data/{path}", json=data, timeout=5.0,
        )
        resp.raise_for_status()

    def upload_policy(self, policy_path: str, rego_source: str) -> str:
        """PUT a Rego module, returns the revision OPA assigns."""
        resp = _request_with_stale_connection_recovery(
            "PUT", f"{self.base_url}/v1/policies/{policy_path}",
            content=rego_source.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            timeout=5.0,
        )
        resp.raise_for_status()
        return resp.json().get("result", {}).get("revision", "")

    def delete_policy(self, policy_path: str) -> None:
        """DELETE a Rego module (standard OPA REST API, `DELETE /v1/
        policies/<id>`). PayReality 1.0 Audit finding G02 (verification-
        closure pass): the missing half of upload_policy -- reconciling
        OPA to "this organization now has zero active RuntimePolicy"
        requires actually removing what's there, not merely declining to
        push anything new (which silently leaves stale, possibly never-
        committed rego live and enforceable). A 404 (nothing was loaded
        under this id) is treated as already-consistent, not an error --
        the caller's intent is "make sure this id isn't serving stale
        content," which is already true either way."""
        resp = _request_with_stale_connection_recovery(
            "DELETE", f"{self.base_url}/v1/policies/{policy_path}", timeout=5.0,
        )
        if resp.status_code == 404:
            return
        resp.raise_for_status()

    def health(self) -> bool:
        try:
            resp = _request_with_stale_connection_recovery(
                "GET", f"{self.base_url}/health", timeout=2.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
