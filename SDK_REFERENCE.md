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

Fetches the current state of a decision (`GET /v1/decisions/{id}`), including its `resolution` if a `HUMAN_REVIEW` decision has since been resolved. Useful for polling.

### `agent.health() -> dict`

Thin wrapper over `GET /health`. Returns the raw response body.

### `agent.version() -> dict`

Thin wrapper over `GET /version`. Returns the raw response body (`{"version": ..., "commit": ...}`).

### `agent.is_registered -> bool`

`True` once this `Agent` has a server-recognized identity, from a `register()` call this session or loaded from a previously-registered private key.

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

Properties: `.allowed`, `.denied`, `.requires_human_review` (all `bool`), `.pending` (`bool`, `status == "PENDING"`).

Method: `.raise_for_outcome()`: raises `AuthorizationDenied` on `DENY`, `HumanReviewRequired` on `HUMAN_REVIEW`, does nothing on `ALLOW`.

## `payreality.RegisteredAgent`

`agent_id`, `certificate_id`, `principal_id`, `principal_name`, `name`: all `str`.

## `payreality.Resolution`

`resolution` (`"approved"` or `"denied"`), `resolved_by` (`str`), `reason` (`str | None`).

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

## Testing note

The SDK's own test suite (`sdk-python/tests/`, 72 tests) mocks every HTTP call; none of it makes a real network request. "100% passing" describes every test in that suite passing, not 100% line coverage of the package, a distinction worth being precise about rather than implying a stronger guarantee than what was actually measured.
