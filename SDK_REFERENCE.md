# SDK Reference

## `payreality.Agent`

### `Agent(api_key=None, bearer_token=None, private_key=None, organization_id=None, base_url="https://api.aisecurewatch.com", timeout=10.0, retry_count=3, credentials_path=None)`

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `api_key` | `str` | One of `api_key`/`bearer_token`, for `register()`, `rotate_keys()`, `retire()`, `get_decision()` | The platform-wide Operator Key, maps to `X-PayReality-Operator-Key`. Needs `organization_id` set alongside it, since the Operator Key belongs to no single organization. Not needed for `authorize()` or `heartbeat()`, which authenticate purely via the agent's own certificate signature. |
| `bearer_token` | `str` | One of `api_key`/`bearer_token`, for the same administrative calls above | A session token (`POST /v1/auth/login`'s `token`) or a scoped API key (`POST /v1/organization/api-keys`'s `raw_key`), either accepted identically -- maps to `Authorization: Bearer <token>`. Preferred over `api_key`: authenticates as a real, scoped, auditable identity instead of the admin bypass, and needs no `organization_id`, since the token already resolves to its own organization server-side. Checked first if both are configured. |
| `private_key` | `str` (base64) | No | If given, the SDK looks up whether this exact key was already registered (see `SDK_ARCHITECTURE.md`'s credential store). If omitted, `register()` generates one. |
| `organization_id` | `str` | Only alongside `api_key` | The organization the Operator Key should act on behalf of for this call. Ignored if `bearer_token` is set. |
| `base_url` | `str` | No | Defaults to production. Override for a local or staging server. |
| `timeout` | `float` | No | Per-attempt request timeout, in seconds. Raises `ConfigurationError` if `<= 0`. |
| `retry_count` | `int` | No | Number of retries after the first attempt for retryable failures. Raises `ConfigurationError` if negative. |
| `credentials_path` | `str` or `Path` | No | Where the local identity file lives. Defaults to `~/.payreality/credentials.json`, or `$PAYREALITY_HOME/credentials.json` if that environment variable is set. |

### `agent.register(name, principal, owner=None, description=None) -> RegisteredAgent`

Registers this agent's public key with PayReality. Resolves `principal` by name (creates it via `POST /v1/principals` if it doesn't already exist), generates a keypair if none was configured, calls `POST /v1/agents`, and persists the result locally. **Idempotent per private key**: calling this again with the same key returns the cached `RegisteredAgent` without a network call.

Raises `AuthenticationError` if neither `api_key` nor `bearer_token` was configured, or the one configured was rejected.

### `agent.authorize(principal, operation, resource, resource_data, metadata=None, correlation_id=None) -> Decision`

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `principal` | `str` | Yes | Must exactly match the principal this `Agent` was registered for. Raises `ConfigurationError` on a mismatch (checked locally, never sent to the server; see `SDK_ARCHITECTURE.md`). |
| `operation` | `str` | Yes | Recorded in the resulting Evidence record's context. Not yet enforced by the Decision Engine (`SDK_ARCHITECTURE.md`). |
| `resource` | `str` | Yes | Normalized (lowercased, spaces to underscores) into the Decision Engine's `action`. `"Vendor Payment"` -> `"vendor_payment"`. |
| `resource_data` | `dict` | Yes | Must include `amount`. May include `currency` (defaults to `"USD"`), `vendor` or `counterparty` (either key), and anything else, which is preserved in the Evidence record's context. |
| `metadata` | `dict` | No | Merged into context alongside `resource_data`'s extra keys. |
| `correlation_id` | `str` | No | Passed straight through to `SubmitIntentRequest.correlation_id`, for correlating this call with your own system's records. |

Returns a `Decision`. Never raises for `ALLOW`/`DENY`/`HUMAN_REVIEW`; those are all normal outcomes. Raises `ConfigurationError` if this `Agent` isn't registered yet, if `principal` doesn't match, or if `resource_data` is missing `amount`. Raises `InvalidSignature`, `NetworkError`, or `ApiError` for anything that goes wrong at the HTTP layer (see below).

### `agent.get_decision(decision_id) -> Decision`

Fetches the current state of a decision (`GET /v1/decisions/{id}`), including its `resolution` if a `HUMAN_REVIEW` decision has since been resolved. A single, one-shot fetch -- see "Polling contract" below for the exact response shape, and `wait_for_resolution()` below for a bounded helper that calls this repeatedly for you.

### `agent.wait_for_resolution(decision_id, timeout=300.0, poll_interval=2.0, max_poll_interval=30.0) -> Decision`

Blocks, calling `get_decision()` repeatedly, until a `HUMAN_REVIEW` decision is resolved or `timeout` seconds elapse. The bounded, synchronous version of the manual `while True: ... time.sleep(2)` loop shown in `SDK_QUICKSTART.md`.

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `decision_id` | `str` | Yes | The decision to wait on -- typically `decision.decision_id` from an `authorize()` call that returned `HUMAN_REVIEW`. |
| `timeout` | `float` | No | Total wall-clock seconds to wait, not an iteration count -- correct regardless of how the poll interval grows. Raises `ConfigurationError` if `<= 0`. |
| `poll_interval` | `float` | No | Seconds between the first two polls. Raises `ConfigurationError` if `<= 0`. |
| `max_poll_interval` | `float` | No | Ceiling the interval backs off to. Each poll multiplies the interval by 1.5x, capped here, so a long wait doesn't hammer the API every 2 seconds indefinitely. |

If the decision is already final on the very first check -- already resolved, or was never `HUMAN_REVIEW` at all (an immediate `ALLOW`/`DENY`) -- it returns that `Decision` immediately, with no sleep and no polling loop: this call is safe to make defensively on any `decision_id`, not just ones you know are still pending. Otherwise it polls until the decision resolves, or raises `ResolutionTimeoutError` (carrying the last-known, still-pending `Decision`) once `timeout` elapses -- it never loops forever, never spawns a background thread, and never retries beyond the given timeout.

This method only ever reads decision state. It never executes, confirms, or implies that the downstream business action ran -- that remains entirely the caller's own responsibility, exactly as it is for `authorize()`'s `ALLOW` outcome. It also never touches webhooks or any push mechanism -- see "Design note: webhooks" in `SDK_ARCHITECTURE.md` for why that's deliberately not built.

### `agent.health() -> dict`

Thin wrapper over `GET /health`. Returns the raw response body.

### `agent.version() -> dict`

Thin wrapper over `GET /version`. Returns the raw response body (`{"version": ..., "commit": ...}`).

### `agent.is_registered -> bool`

`True` once this `Agent` has a server-recognized identity, from a `register()` call this session or loaded from a previously-registered private key.

### `agent.request_capability(decision_id, audience, ttl_seconds=None) -> payreality.models.Capability`

Requests a Capability Authorization for a Decision whose `outcome` is `ALLOW` (`POST /v1/decisions/{id}/capability-token`). An administrative call, authenticated the same way as `register()`/`rotate_keys()`/`retire()`/`get_decision()` (`api_key` + `organization_id`, or `bearer_token`), not the Agent's own signing key.

Works identically whether `decision_id` names an Agent-direct decision (from `authorize()`) or a Trusted Adapter-mediated one (from `payreality.integration.Adapter.attest()`); call it from your own orchestration code once you already have a `Decision`, never from inside an `Adapter` itself, which authenticates with a different credential this endpoint does not accept.

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `decision_id` | `str` | Yes | Must resolve to a Decision whose `outcome` is `ALLOW`. |
| `audience` | `str` | Yes | Names the enforcement checkpoint (PEP) this Capability is for. Only a `verify_capability()` call presenting this exact audience can consume it. |
| `ttl_seconds` | `int` | No | Overrides the server's default expiry window. |

Raises `ApiError` (HTTP 409) if the decision is not `ALLOW`, or, for an Adapter-mediated decision, if the underlying `IntegrationIdentity` (Trusted Connection) or `EnforcementBinding` (Runtime Connection) is no longer active, the server's live re-check at issuance time, not merely a check of the decision's historical provenance. Requesting and later consuming a Capability is not proof the downstream enterprise action executed; see `payreality.models.Capability`/`ConsumedCapability` below.

Phase 5.1: also raises `ApiError` (HTTP 409) if this Decision already has a Capability — `capability_already_issued` (still valid), `capability_already_consumed_for_decision`, or `capability_expired_not_renewed`. One authority authorization lifecycle produces at most one currently usable Capability, ever; a repeated or concurrent call never mints a second one.

### `agent.request_capability_from_review(decision_id, audience, ttl_seconds=None) -> payreality.models.Capability`

Requests a Capability Authorization for a Decision whose `outcome` is `HUMAN_REVIEW` and which an authorized reviewer has since approved via `resolve_decision()` or the dashboard's review queue (`POST /v1/decisions/{id}/capability-token/from-review`, Trusted Integration Phase 5.1). Same authentication as `request_capability()` above. The original Decision is never rewritten — it still reports `outcome == "HUMAN_REVIEW"` forever; this authorizes continuation of that specific business operation based on the separate, linked review resolution.

Raises `ApiError` (HTTP 409) `decision_not_human_review` if the Decision isn't `HUMAN_REVIEW`, `review_not_resolved` if no resolution exists yet, `review_not_approved` if the resolution is `"denied"` — plus every precondition and error code `request_capability()` already raises (live status re-checks, the three idempotency outcomes above), via the same underlying issuance path.

### `agent.verify_capability(token, audience, action, resource, constraints, environment=None, enforcement_binding_id=None, principal=None) -> payreality.models.ConsumedCapability`

The customer-controlled enforcement checkpoint's own call: online verify-and-consume, atomic, single-use (`POST /v1/capability-tokens/verify`). Every argument after `token` must match exactly what the Capability was issued for, or this raises `ApiError` with a specific status: `401` expired or invalid signature, `403` wrong audience or wrong tenant, `409` constraint/binding/live-status mismatch or already consumed, `404` unknown token.

`environment`/`enforcement_binding_id`/`principal` are all optional: pass any of them if your own checkpoint knows which Runtime Connection, environment, or Agent it expects, to additionally pin that expectation against the Capability's own signed claim. Omit all three to skip those specific checks, the same behavior this method already had for an Agent-direct Capability before this addition.

Trusted Integration Architecture, Phase 6.1 (Production Authorization Assurance): also raises `ApiError` `403 capability_tenant_mismatch` if the Capability was signed for a different organisation than this `Agent` is authenticated for, and `409 origin_agent_not_active` / `409 integration_identity_not_active` / `409 enforcement_binding_not_active` / `409 tenant_not_active` if a live freshness recheck at consumption time fails (an identity the Capability depends on was revoked since it was issued).

**Authentication now matches every other administrative call in this class**: `verify_capability()` uses the same `admin_auth=True` preference order as `request_capability()`/`request_capability_from_review()` -- a `bearer_token` (a real, organisation-scoped `ApiKey` whose role holds `Permission.CAPABILITY_VERIFY`) first, the platform Operator Key (`api_key`, still requiring `organization_id`) as a fallback. Before Phase 6.1 this method accepted only the Operator Key; a reference enforcement checkpoint should now hold its own scoped credential instead of the platform-wide one.

A successful return proves a valid Capability was presented and consumed exactly once, at this moment. It does not prove the downstream enterprise action that follows actually executed.

## `payreality.integration.Adapter`

The Trusted Adapter runtime path (0.5.0+) — a separate identity type from `Agent`. See [SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md](SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md) for the mechanism this wraps, and [SDK_ARCHITECTURE.md](SDK_ARCHITECTURE.md) for how it fits alongside `Agent`.

### `Adapter(integration_identity_id, certificate_id, private_key, base_url="https://api.aisecurewatch.com", timeout=10.0, retry_count=3, contract_shape=None)`

`integration_identity_id`/`certificate_id` identify this Adapter's already-registered Trusted Connection and its currently active certificate — registering a Trusted Connection or rotating its certificate is an administrative action performed via the raw HTTP API or the Admin UI, not part of this class. `private_key` never leaves this process. `contract_shape` (a `ContractShape` instance) is an optional, purely local pre-flight check — it can reject an obviously-wrong call (a field the pinned Action Mapping doesn't declare) before a network round trip; the server's own check remains authoritative regardless of whether this is supplied.

### `adapter.attest(*, enforcement_binding_id, origin_agent_id, source_operation, action, external_operation_id, resource=None, amount=None, currency=None, counterparty=None, context=None, correlation_id=None) -> Decision`

Constructs, signs, and submits one attested Intent through the trusted-Adapter runtime path (`POST /v1/integration-runtime/intents`).

- `enforcement_binding_id` — the Runtime Connection to submit through.
- `origin_agent_id` — the Agent this call attests observed operation is on behalf of. This does **not** authenticate as that Agent; PayReality independently verifies, server-side, that the named Agent is actually on this Runtime Connection's allow-list.
- `source_operation`/`action` — must exactly match the Runtime Connection's pinned Action Mapping version, or the request is rejected before evaluation (an integration rejection, never routed to `HUMAN_REVIEW`).
- `external_operation_id` — **required**. The stable identifier of the real external business operation. Calling `attest()` again with the same id and the same authority-relevant values (origin Agent, action, resource, amount, currency, counterparty, and mapping-bound context) returns the *original* Decision, not a new evaluation; the same id with different authority-relevant values raises a conflict exception instead. Client-side pre-validated (max 256 characters, non-empty) before any network call; the server's own validation remains authoritative.
- Returns the same `Decision` shape `agent.authorize()` does — `ALLOW`/`DENY`/`HUMAN_REVIEW`, and `wait_for_resolution()`-style polling applies identically for a `HUMAN_REVIEW` result.
- Raises a distinct exception for an **integration rejection** (invalid connection, agent not allow-listed, mapping mismatch, operation-id conflict) — never the same exception a `DENY` produces. Application code must not treat the two the same way: a `DENY` means PayReality evaluated a legitimate request and said no; an integration rejection means there was no legitimate request to evaluate.

### `ContractShape(*, has_resource=False, has_amount=False, has_currency=False, has_fact_subject=False, context_keys=frozenset())`

Optional, purely local declaration of which fields this Adapter's pinned Action Mapping actually extracts — mirrors the same presence/absence rule the server enforces authoritatively. Never required; omitting it just means `attest()`'s local pre-flight check is skipped and every field passes straight through to the server's own (authoritative) validation.

## `payreality.Decision`

| Attribute | Type | Notes |
|---|---|---|
| `outcome` | `str` | `"ALLOW"`, `"DENY"`, or `"HUMAN_REVIEW"` |
| `decision_id` | `str` | |
| `evidence_id` | `str \| None` | `None` from `get_decision()`, since that endpoint doesn't return one; always set from `authorize()`. |
| `reason` | `str \| None` | |
| `explanation` | `str \| None` | Currently an alias for `reason` (see `SDK_ARCHITECTURE.md`'s honesty note: today's API has one human-readable field, not two). |
| `status` | `str` | `"RESOLVED"` or `"PENDING"` |
| `evaluated_mandates` | `tuple[str, ...]` | Despite the name, holds matched RuntimePolicy policy_key strings, not real Mandate ids -- kept for backward compatibility. `evaluated_mandate_ids` (server-side `Decision`/`GetDecisionResponse`, not yet in this SDK's `Decision` model) is the correctly-named field holding real `mandates.id` values, additive alongside this one. |
| `resolution` | `Resolution \| None` | Set only once a `HUMAN_REVIEW` decision has been resolved and re-fetched via `get_decision()`. |
| `correlation_id` | `str \| None` | Echoed back exactly as you passed it to `authorize()`, or `None` if you didn't pass one. Trace/correlation metadata only -- see "correlation_id: what it is, and what it deliberately isn't" below. |
| `created_at` | `str \| None` | ISO-8601 timestamp the underlying Intent was submitted at. `None` only if the server response omitted it (should not happen in practice). |

**Retrieving Evidence and the Authorization Receipt**: there is no dedicated `get_evidence()`/`get_receipt()` SDK method today — `Decision.evidence_id` gives you the id, and a caller must fetch `GET /v1/evidence/{evidence_id}` or `GET /v1/decisions/{decision_id}/receipt` directly (session-token or Operator-Key authenticated, same as any other admin-facing endpoint). This is a real, disclosed gap in the SDK's current surface, not a design choice being defended.

Properties: `.allowed`, `.denied`, `.requires_human_review` (all `bool`), `.pending` (`bool`, `status == "PENDING"`).

Method: `.raise_for_outcome()`: raises `AuthorizationDenied` on `DENY`, `HumanReviewRequired` on `HUMAN_REVIEW`, does nothing on `ALLOW`.

## `payreality.models.Capability` and `payreality.models.ConsumedCapability`

What `agent.request_capability()` and `agent.verify_capability()` return, respectively. **Neither is exported from the top-level `payreality` package** (`payreality/__init__.py`'s own `__all__` does not list them, unlike `Decision`/`RegisteredAgent`/`Resolution`): import them as `from payreality.models import Capability, ConsumedCapability`, not `from payreality import Capability`. This is a real, disclosed gap in this SDK's current surface, not a design choice being defended.

**`Capability`**: `token` (`str`, the full, opaque, signed artifact to hand to whatever enforcement checkpoint enforces `audience`; this SDK never inspects or decodes it), `capability_id` (`str`), `expires_at` (`str`, ISO-8601).

**`ConsumedCapability`**: `capability_id` (`str`), `decision_id` (`str`), `resource` (`str`), `constraints` (`dict`), the exact values the Capability was bound to, for the caller's own record.

Neither model carries a field claiming the downstream enterprise action executed. Issuing a `Capability`, and a checkpoint later consuming it into a `ConsumedCapability`, are both proof that an authorization step happened, never proof of what happened afterward.

## `payreality.RegisteredAgent`

`agent_id`, `certificate_id`, `principal_id`, `principal_name`, `name`: all `str`.

## `payreality.Resolution`

`resolution` (`"approved"` or `"denied"`), `resolved_by` (`str`), `reason` (`str | None`), `resolved_at` (`str | None`, ISO-8601 timestamp of when the human resolved it).

Note what's deliberately absent: there is no field claiming the downstream business action executed. `resolution == "approved"` means a human approved the *request* PayReality evaluated -- it says nothing about whether your code went on to actually perform the payment, the account change, or whatever the request represented. That remains entirely your own responsibility to track, exactly as it already is for an outright `ALLOW`.

## Exceptions

All inherit from `payreality.PayRealityError`.

| Exception | Raised when |
|---|---|
| `ConfigurationError` | A local, pre-flight problem: missing registration, principal mismatch, missing `amount`, invalid `timeout`/`retry_count`. Never reaches the network. |
| `AuthenticationError` | Neither `api_key` nor `bearer_token` was configured for an administrative call, or the server rejected the one that was (401/403). Has `.status_code`. |
| `InvalidSignature` | `authorize()`'s signature was rejected (unknown/revoked certificate, bad signature, outside the replay window). Has `.status_code` and `.reason`. |
| `NetworkError` | Every retry attempt failed to get a response at all (DNS, connection, or timeout). Has `.__cause__` set to the underlying `requests` exception. |
| `ApiError` | Any other non-2xx response, including validation failures (422) and policy-adjacent 4xx/5xx not otherwise mapped. Has `.status_code` and `.body`. |
| `AuthorizationDenied` | Only from `Decision.raise_for_outcome()` on a `DENY`. Has `.decision`. |
| `HumanReviewRequired` | Only from `Decision.raise_for_outcome()` on a `HUMAN_REVIEW`. Has `.decision`. |
| `ResolutionTimeoutError` | Only from `wait_for_resolution()`, when `timeout` elapses with the decision still pending. Has `.decision` (the last-known, still-pending `Decision`) and `.timeout` (`float`). Not a failure of the decision itself -- it may still resolve later; poll again or call `wait_for_resolution()` again to keep waiting. |

## Polling contract: `GET /v1/decisions/{id}`

The exact contract `get_decision()` and `wait_for_resolution()` are built on, spelled out precisely enough to implement your own poller in another language if you need to.

**Endpoint:** `GET /v1/decisions/{decision_id}`, authenticated the same way as every other administrative call (`api_key` + `organization_id`, or `bearer_token`).

**Response states**, distinguished by the `status` field:

1. **`status: "PENDING"`** -- the decision is `HUMAN_REVIEW` and still unresolved. `resolution` is `null`.
2. **`status: "RESOLVED"`, `resolution` present** -- a `HUMAN_REVIEW` decision that a human has since approved or denied. `resolution.resolution` is `"approved"` or `"denied"`; `resolution.resolved_by`, `.reason`, and `.created_at` (the resolution timestamp) are also present. **`outcome` itself is still, and will always be, `"HUMAN_REVIEW"`** -- resolving a decision never rewrites its original outcome; the resolution is a separate, permanent record layered on top. Never write code that expects `outcome` to become `"ALLOW"`/`"DENY"` after a resolution -- check `resolution.resolution` instead.
3. **`status: "RESOLVED"`, `resolution` absent (`null`)** -- the decision was `ALLOW` or `DENY` outright; there was never a human review step to resolve.

**Error responses:** `401` (no/invalid credentials), `403` (credentials valid but for a different organization than the decision belongs to -- deliberately indistinguishable from `404` for a genuinely nonexistent decision, so a cross-organization caller learns nothing about a decision's existence), `404` (no such decision, or it belongs to a different organization). The SDK raises `AuthenticationError` for `401`/`403` and `ApiError` for `404` from a raw `get_decision()` call.

**Interval, backoff, and max-wait guidance:** `wait_for_resolution()`'s defaults (start at 2s, back off 1.5x per attempt, cap at 30s, total timeout 300s) are reasonable defaults for a human-review turnaround measured in minutes, not seconds -- don't poll faster than every 1-2 seconds in your own implementation; the resolution isn't going to arrive faster than a human can click a button.

**Idempotency:** `GET /v1/decisions/{id}` is a pure read -- calling it any number of times, from any number of processes, is always safe and has no side effects. There is no "consume" semantic; the same resolved decision returns the same resolution forever.

**Resume after restart:** because polling is just a read, there's no session or subscription to reconnect -- if your process crashes and restarts, call `get_decision(decision_id)` (or `wait_for_resolution(decision_id)`) again with the same `decision_id` you already had, and you'll get the current state immediately, including a resolution that happened while your process was down. You don't need to have been "listening" for the resolution to happen; nothing is lost by not polling continuously.

## `correlation_id`: what it is, and what it deliberately isn't

`correlation_id` is trace/correlation metadata only -- an id you supply so you can match a PayReality decision back to your own system's own record of the same job (a queue message id, a workflow run id, whatever your system already uses). PayReality stores it, echoes it back on `authorize()`, `get_decision()`, and the Authorization Receipt, and does nothing else with it.

Specifically, it is **not**: an authority signal (it never influences whether a request is `ALLOW`/`DENY`/`HUMAN_REVIEW`), a security credential (it's never checked against anything, never used for access control), or a policy selector (no policy can match on it, and none should be written to try). Treat it exactly like a request id in a logging system -- useful for you to grep by later, invisible to the decision itself.

## Testing note

The SDK's own test suite (`sdk-python/tests/`, 101 tests, including `test_agent_capability.py` added alongside `request_capability()`/`verify_capability()`, extended for `request_capability_from_review()` in Phase 5.1 and for `verify_capability()`'s tenant-scoped `admin_auth` model in Phase 6.1) mocks every HTTP call; none of it makes a real network request. "100% passing" describes every test in that suite passing, not 100% line coverage of the package, a distinction worth being precise about rather than implying a stronger guarantee than what was actually measured.
