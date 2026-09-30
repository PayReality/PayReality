# OPA Client Reliability Review

A verification pass over `server/app/opa_client.py`: what `timeout_ms` actually
guarantees, the shared HTTP client's real lifecycle, and a real, instrumented
investigation of the backend test suite's own reliability. Every claim below
was checked directly against real code, a real controlled test server, or a
real instrumented full-suite run -- not assumed or carried forward from an
earlier, unverified report.

## Section 1: what `timeout_ms` actually guarantees

The prior pass's own documentation claimed that splitting a caller's
`timeout_ms` across httpx's four independent phase budgets (connect/write/
read/pool) produces a strict total deadline: "the worst case sums to no more
than timeout_ms." That claim is **false**, confirmed directly with a
controlled, raw-socket test server (not assumed):

1. **Client construction is outside any per-request timeout.**
   `httpx.Client()` construction cost 0.6-0.9s in this environment (almost
   certainly Windows' own system-proxy auto-detection, performed once per
   `Client` instance) -- and this cost occurs *before* httpx's own per-request
   timeout clock starts. A cold-process request with `timeout_ms=200` against
   a 1s-delayed server measured 1.11s to raise `OPATimeoutError`, while the
   identical request against a pre-warmed client measured 0.16s, matching the
   intended budget.

2. **The read-phase timeout does not bound total elapsed time.** httpx/httpcore's
   `read` timeout is the maximum gap *between* received bytes, not a deadline
   for the whole read phase. A server that sends valid headers immediately,
   then trickles its body one byte every 50ms (5.0s of real total time),
   against a configured `read=0.5s`, does not time out -- no single gap ever
   exceeds 0.5s.

**Corrected contract** (now the module's own docstring in `opa_client.py`):
`timeout_ms` is a **best-effort, per-phase-bounded budget against a
well-behaved, co-located, non-adversarial OPA peer** -- this platform's own
real deployment shape everywhere else. It is **not** a strict,
adversarial-safe total deadline. A caller with a genuine hard-cancelling
requirement would need a different mechanism (an `asyncio` client driven by
`asyncio.wait_for`, which actually cancels the underlying connection) --
evaluated and deliberately not implemented, since it is a materially larger,
riskier change unjustified by OPA's real, self-operated, co-located
deployment model, and nothing in this codebase's own specs asks for it.

**Mitigation implemented:** an explicit `warm_up_shared_client()` function,
called from `app/main.py`'s startup `lifespan` (same fail-open, log-and-continue
posture as the app's four existing startup hooks), so the unbounded
construction cost is paid once at process boot, never on a live decision
request in normal operation. It does not protect a caller that never runs the
real app lifespan (a standalone script, some test contexts).

## Section 2: shared HTTP client lifecycle

`_shared_client` is one process-wide, lazily-constructed `httpx.Client`,
reused across every `HttpOpaClient` instance and request.

- **Concurrent first use:** guarded by real double-checked locking. Confirmed
  directly, repeated trials: the lazy-init race itself always constructs
  exactly one client, independent of anything else happening concurrently.
- **A real, disclosed, environment-specific characteristic** (not a defect in
  this module): 20 brand-new TCP connections established at the same instant
  on this Windows loopback environment occasionally produce a genuine
  transport-level reset on one or two of them -- reproduced even against a
  trivial raw-socket echo server, so it is not specific to httpx or OPA.
- **Thread safety:** `httpx.Client` is documented upstream as safe to share
  across threads; this module never stores request-specific state (headers,
  auth, cookies) on the shared client itself, so nothing can leak between
  callers.
- **Process behavior:** this is plain module-level state. A **forked** child
  process would inherit an already-open client's live socket file
  descriptors -- unsafe, and not supported. This codebase's own real
  multiprocessing usage uses `spawn`, not `fork` (confirmed by reading the
  one real multiprocessing call site), which re-imports this module fresh in
  the child -- safe.
- **Shutdown:** no shutdown hook currently closes `_shared_client`. Disclosed
  as a real, unaddressed gap (matches this app's own real deployment shape:
  one process for the container's entire lifetime, no evidence of an actual
  leak), not fixed in this pass.
- **Stale connections after an OPA restart:** confirmed directly -- a pooled
  keep-alive connection to a peer that has since restarted raises a real
  `httpx.ReadError`/`ConnectError` (`WinError 10053`/`10054` in this
  environment; `ECONNRESET`/`EPIPE` on POSIX). `httpx.HTTPTransport(retries=1)`
  does **not** cover this (it only covers failures establishing a brand-new
  connection, not a previously-good pooled one failing on reuse; confirmed
  directly).

**Mitigation implemented:** every real HTTP call now goes through
`_request_with_stale_connection_recovery`, which retries exactly once, and
only on `httpx.NetworkError` (never on `httpx.TimeoutException`, even though
`TimeoutException` is itself a subclass of the broader `httpx.TransportError`
-- this distinction is load-bearing; see "Two real bugs" below), by
**swapping** the shared-client reference to a freshly-constructed client,
never by closing the outgoing one synchronously.

### Two real bugs found and fixed while building this

1. **Timeouts were being silently retried.** The first version of the retry
   caught the broad `httpx.TransportError`, which also matches
   `ReadTimeout`/`PoolTimeout`/`ConnectTimeout`. Every ordinary timeout was
   silently retried, roughly doubling (or worse, under pool contention)
   its real elapsed time -- directly contradicting the caller's own configured
   budget. Fixed by narrowing the catch to `httpx.NetworkError`, which
   structurally excludes every `TimeoutException` subclass (confirmed via
   `issubclass` checks against the real httpx exception hierarchy).

2. **The rebuild closed a client other threads were still using.** The first
   version of `_rebuild_shared_client()` called `.close()` on the outgoing
   client before installing the new one. `httpx.Client.close()` tears down
   *every* connection in that client's pool, including ones other threads
   have healthy, unrelated, in-flight requests running on right now.
   Reproduced directly: 20 concurrent healthy requests against a single
   shared client, one of which hit an unrelated transient reset and
   triggered a rebuild -- closing the client under the other 19 aborted two
   of their otherwise-healthy connections (`WinError 10053`, i.e. aborted by
   this process's own prior `.close()` call, not by the network). Fixed by
   only ever swapping the module-level reference, never closing the outgoing
   client synchronously -- Python's own reference counting keeps it alive for
   any thread still mid-request on it.

Both are now covered by permanent regression tests in
`server/tests/integration/test_opa_client_reliability.py`.

## Section 3: controlled-server testing and fail-closed verification

A raw-socket test harness (not a framework, for byte-level control over
exactly when and how many bytes are sent) exercised: a slow initial response,
a byte-at-a-time trickle, a connection held open with zero bytes ever sent,
an immediate connection reset, pool contention, 20 concurrent requests, and
server-restart recovery. Findings are summarized in Sections 1-2 above and
are now permanent tests (9 tests, `test_opa_client_reliability.py`, stable
across 5+ consecutive local runs).

**Fail-closed, verified through the real decision path** (not just the raw
client): `app.domain.decision.engine.evaluate` was called directly against a
real `HttpOpaClient` pointed at the controlled server, for a timeout, a
connection reset, and an "OPA responded but gave no explicit `allow: true`"
case. Every one resolved to `Decision(outcome="HUMAN_REVIEW")`. Reading
`evaluate`'s own code confirms why this is structural, not incidental: both
`OPATimeoutError` and `OPAEvaluationError` are caught in dedicated branches
that construct `Decision(outcome="HUMAN_REVIEW", ...)`, and no other branch
can be reached without an explicit `allow: true` from a real OPA response --
there is no code path from a timeout or transport failure to `ALLOW`.

## Section 4: the full-suite investigation

The prior report's own explanation for four then-unexplained full-suite
failures -- "roughly seven hours, possibly explained by environment
pause/resume" -- was explicitly flagged as unconfirmed and not to be trusted.
It was investigated with real instrumentation, not repeated
without a hypothesis:

- Per-test start/end timestamps (via pytest hooks).
- An independent heartbeat thread, ticking every 2s for the whole session,
  regardless of what any test thread was doing -- a gap here is real evidence
  the process (or its environment) was not scheduled, as distinct from
  something inside the process merely being slow.
- Every real `HttpOpaClient.query` call, logged with its elapsed time and
  outcome.
- The OPA subprocess's own PID, captured at launch, to confirm whether the
  same process served the whole run.

**Result of the one instrumented run** (real Postgres enabled, 1,240 tests):
**1,239 passed, 1 failed, in 19 minutes 6 seconds (1,146.32s).** Not seven
hours, and not four failures -- a full, real run in this environment takes
under twenty minutes end to end.

The one failure (`test_historical_policy_binding.py::
test_historical_stability_decision_survives_later_policy_version`) accounted
for 457 of the run's 1,146 total seconds (roughly 40% of the entire suite's
wall-clock time) by itself. The instrumentation pinpointed the exact cause:
a single OPA query, `timeout_ms=5000`, took **441.2 seconds** before finally
raising `OPATimeoutError` -- and the independent heartbeat thread, doing
nothing but `time.sleep(2)`, also went silent for that same ~441-second
window (the only gap over 6 seconds anywhere in the entire 3,300-line,
19-minute instrumentation log). The OPA subprocess itself was launched
exactly once for the whole session and never restarted.

Tracing the query's own logged `base_url` explained the mechanism precisely,
independent of the heartbeat-gap evidence: the stalled call went to
`http://localhost:8181` (`settings.opa_url`'s hardcoded default), **not** the
test's own real, ephemeral OPA server (`http://127.0.0.1:<port>`, provided by
the `opa_url` pytest fixture). The test file's `_submit()` helper called
`intent_service.submit_intent(...)` without ever passing an OPA URL override,
unlike every one of that same file's own `deploy_policy(..., opa_url=opa_url)`
calls -- `submit_intent` had no such parameter at all, so it silently fell
back to `settings.opa_url`. Most attempts against that wrong, generally-unused
address failed fast (masked by `_submit`'s own 6-attempt retry loop, whose
docstring misattributed the cause to "the ephemeral OPA occasionally
flaking" -- it never touched the ephemeral OPA at all); once, whatever is
sometimes reachable at `localhost:8181` on this machine did not fail fast,
and the request hung for over seven real minutes. This is consistent with
this same session's other findings of real, occasional loopback interference
on this specific development machine (Section 2's `WinError 10053`/`10054`
resets) -- a related but distinct manifestation of the same underlying
environmental characteristic, not a new one.

**Fixed:** `intent_service._evaluate_and_record` and `submit_intent` gained
an optional `opa_url: str | None = None` parameter (default preserves every
other existing caller unchanged, including the Adapter-mediated path in
`integration_runtime_service.py`), threaded through to the `HttpOpaClient`
construction. `test_historical_policy_binding.py`'s `_submit()` now requires
and passes it. Re-run after the fix: all 6 tests in that file pass in 8.29s
total (the previously-failing test alone: 1.23s, down from 457.42s).

**On "four remaining failures" vs. "one":** this session's own real run found
one failure, not four. Whether the prior report's other three were the same
latent `_submit`/`submit_intent` wiring gap (plausible, since it manifests
non-deterministically depending on what, if anything, is reachable at
`localhost:8181` at a given moment) cannot be confirmed -- that run's own
logs were not preserved. Reported honestly as unconfirmed, not assumed.

A second, confirmatory full-suite run (same instrumentation) was performed
after the fix, since the first run's own result directly motivated a specific,
testable change -- not a repeat without cause. Its result is recorded in the
final report / commit message, not duplicated here.

## What this review does not establish

- No claim that PayReality is "production ready." This pass is scoped to
  `opa_client.py`'s own reliability and one real full-suite investigation, not
  a general audit.
- The environment-specific loopback interference (Sections 2-4) is disclosed,
  not fixed -- its root cause (most likely security/network software
  intercepting loopback HTTP traffic on this specific machine) is outside
  this codebase's control.
- Application shutdown cleanup of `_shared_client` remains unimplemented,
  disclosed as a known, low-risk gap.
