# SDK Architecture

## What this phase is, and isn't

This is the first official PayReality SDK: a Python package (`sdk-python/payreality/`, version 0.5.0) that wraps the existing HTTP API (`docs/API_SPECIFICATION.md`) so a developer never has to hand-implement ED25519 signing, certificate management, request headers, or retry logic. It consumes `POST /v1/principals`, `POST /v1/agents`, `POST /v1/agents/{id}/activate`, `POST /v1/agents/{id}/rotate`, `POST /v1/agents/{id}/retire`, `POST /v1/agents/{id}/heartbeat`, `POST /v1/intents`, `GET /v1/decisions/{id}`, `GET /health`, and `GET /version` exactly as they exist today. Nothing in the Runtime Engine, Compiler V2, OPA, Evidence, Policy Studio, or either AI Policy Builder changed to make this possible; this SDK is a client, not a platform change.

**As of 0.5.0, the SDK also covers the Trusted Adapter path** (`payreality.integration.Adapter`, see the dedicated section below) — this file previously described only the agent-direct surface, which was an omission this pass corrected, not a change to the SDK itself.

**Also part of the current 0.5.0 surface, undocumented in this file until this pass**: `Agent.request_capability()`/`Agent.verify_capability()`, covering Capability Authorization for a Decision from either runtime path (Trusted Integration Architecture Phase 5). See the dedicated section below.

## Package layout

```
sdk-python/
  payreality/
    __init__.py       public exports: Agent, Decision, RegisteredAgent, exceptions (NOT Capability/ConsumedCapability, see the Capability Authorization section below)
    agent.py           Agent: register(), rotate_keys(), heartbeat(), retire(), authorize(), get_decision(), wait_for_resolution(), health(), version(), request_capability(), verify_capability()
    integration.py     Adapter: attest(), the Trusted Adapter path, POST /v1/integration-runtime/intents. ContractShape: the request shape an Action Mapping expects.
    auth.py            nonce/timestamp generation, header assembly
    client.py           the one place that makes an HTTP request; owns retries and exception mapping
    crypto.py           ED25519 keygen and signing (PyNaCl)
    exceptions.py       the exception hierarchy
    models.py           Decision, Resolution, RegisteredAgent, Capability, ConsumedCapability (plain dataclasses)
    retry.py             retry policy: what's retryable, backoff schedule
    configuration.py     Configuration + the local credential store
  tests/               80 tests, all mocked (no network), see SDK_REFERENCE.md's testing note
  examples/            4 runnable scripts
```

This layout is deliberately generic where it can be: `client.py`'s retry/exception-mapping logic and `configuration.py`'s credential store are not PayReality-specific ideas, and a future Node/Java/Go/.NET SDK (explicitly out of scope for this phase) can follow the same shape without needing to invent its own design from scratch.

## How `authorize()` maps onto the wire format

The public interface is expressed in PayReality's universal vocabulary (`UNIVERSAL_RUNTIME_AUTHORITY.md`: Principal, Operation, Resource), and as of the Domain Generalization Milestone (SDK 0.4.0) that vocabulary is a real, honest mapping onto today's wire format (`docs/API_SPECIFICATION.md`'s `SubmitIntentRequest`: `agent_id`, `action`, `resource`, `amount`, `currency`, `counterparty`, `context`), not a workaround for a field the server doesn't have yet. `agent.py::authorize()` maps the interface onto the wire in four specific ways:

1. **`operation` becomes `action`.** `"Approve"`/`"Disable User"` is normalized (lowercased, spaces to underscores) to `"approve"`/`"disable_user"`, which is what the Decision Engine actually evaluates a policy's `Scope.action` against. An `operation` that doesn't match any policy's scope is not an SDK error: the request still gets sent, and the Decision Engine's own existing, correct behavior is to escalate an unrecognized action to `HUMAN_REVIEW` rather than silently allow it (`examples/approve_invoice.py` demonstrates this directly, on purpose, rather than only showing a happy path).

2. **`resource` is sent as-is, as the wire's real `resource` field.** `"Vendor Payment"`, `"account:USR-829"`, `"invoice:INV-4821"` -- an opaque, organization-defined identifier for the real-world object the action concerns (`Intent.resource`, `server/app/db/models.py`), never normalized, and entirely optional. Before this milestone, `resource` was the field being misused to derive `action` from (see this SDK's own changelog in `agent.py`'s module docstring for the disclosed 0.3.0 -> 0.4.0 breaking change); it is not derived from anything now, it is the resource identifier.

3. **`principal` is a local safety check, not a request field.** `SubmitIntentRequest` has no `principal` field: the server already knows which principal a given agent's certificate acts for, resolved from `agent.acting_for_principal_id` at registration time (`server/app/services/intent_service.py::submit_intent` never takes a principal argument). Sending a redundant principal on every call would just be ignored by the server, so instead `authorize()` checks the passed `principal` against the principal this specific `Agent` was registered for, and raises `ConfigurationError` on a mismatch. This turns a parameter that would otherwise be pure decoration into a real guard against a wrong-agent mistake.

4. **`resource_data` is decomposed into the wire's actual fields.** `amount`/`currency` are optional, not required -- a non-financial action (`disable_user`, `employee_terminate`) supplies neither; `currency` defaults to `"USD"` only when `amount` is given and `currency` isn't. `vendor`/`counterparty` (either key works) maps to the wire's `counterparty`. Everything else in `resource_data`, plus `metadata`, lands in `context` as Runtime Authority context -- never silently dropped, and never required just to make a non-financial call.

## The Trusted Adapter path (`payreality.integration.Adapter`)

A second, separate identity type from `Agent` — see [SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md](SPECIFICATION/50_TRUSTED_INTEGRATION_ARCHITECTURE.md) for the full mechanism this wraps. `Adapter` authenticates as an `IntegrationIdentity` (an already-registered Trusted Connection), not as an Agent, using `integration_identity_id` and `certificate_id`. `Adapter.attest()` takes `enforcement_binding_id` (the Runtime Connection), `origin_agent_id` (which allow-listed Agent this report is on behalf of), `source_operation`, `action`, and a caller-supplied `external_operation_id` (validated client-side — max 256 chars, mirroring the server's own `operation_identity_service` rules, so a malformed id fails fast instead of round-tripping to the server first) — then signs and POSTs to `/v1/integration-runtime/intents`.

**Registration and certificate rotation for the Trusted Connection itself are deliberately not part of this class** — those are administrative actions (`POST /v1/integration-identities`, `.../activate`, `.../rotate`, etc.), performed via the raw HTTP API or the Admin UI (Settings → Integrations), not through the SDK's `Adapter` object. `Adapter` is the runtime-attestation client; it assumes the Trusted Connection, Runtime Connection, and Action Mapping already exist and are approved/active.

`Adapter.attest()` returns the same `Decision`/outcome shape `Agent.authorize()` does — `ALLOW`/`DENY`/`HUMAN_REVIEW`, and the same `wait_for_resolution()`-style polling applies for a `HUMAN_REVIEW` result. It raises a distinct exception for an **integration rejection** (a pre-evaluation trust failure — invalid connection, agent not allow-listed, mapping mismatch) versus a normal `DENY`, matching the server-side distinction exactly (§50.8 of the specification above) — do not catch these two the same way in application code, they mean categorically different things.

## Capability Authorization (`agent.request_capability()` / `agent.verify_capability()`)

Both methods live on `Agent`, never on `Adapter`, even though `request_capability()` also covers a Decision produced by `Adapter.attest()`: requesting or verifying a Capability is an administrative operation authenticated by the caller's own operator credential, not by an Agent's or a Trusted Connection's signing key, so it belongs with the other administrative methods on `Agent` regardless of which runtime path produced the underlying Decision.

`request_capability()` wraps `POST /v1/decisions/{id}/capability-token`, gated by the same `admin_auth` (`api_key`+`organization_id`, or `bearer_token`) every other administrative method on this class already requires. For a Decision from the Trusted-Adapter path, the server re-checks live, at the moment of issuance, that the underlying Trusted Connection and Runtime Connection are still active; this SDK does not duplicate that check client-side, it only surfaces the resulting `ApiError` (HTTP 409) if either has since been suspended, revoked, or retired.

`verify_capability()` wraps `POST /v1/capability-tokens/verify` and is the one method on `Agent` with a different authentication requirement from the rest of the class: it accepts only `api_key` (the platform Operator Key), never `bearer_token`, because the caller here is modeled as a reference enforcement checkpoint (a trusted internal/platform-level caller with no human RBAC session), the same primitive `process_due_schedules` uses server-side, not a scoped per-organization identity. Calling it on an `Agent` configured with only `bearer_token` raises `ConfigurationError` before any network call.

**Both models it returns, `Capability` and `ConsumedCapability`, are absent from `payreality/__init__.py`'s `__all__`.** They exist and work exactly as documented in `SDK_REFERENCE.md`, importable as `payreality.models.Capability`/`payreality.models.ConsumedCapability`, but `from payreality import Capability` fails with an `ImportError` today. This is a real gap in this pass's own polish, not a deliberate design choice, and is disclosed here rather than glossed over.

## Identity and the local credential store

An agent's `agent_id` and `certificate_id` are server-assigned identifiers a developer should never have to copy and paste (`configuration.py::CredentialStore`). Registration is idempotent per ED25519 key: the store is keyed by public key (deterministically derivable from a private key, so the SDK can recognize "have I registered this exact key before?" without a network call), and `register()` called a second time with the same key returns the cached identity instead of hitting the network again. This makes `register()` safe to call on every process start, matching how a real deployment would actually use it.

## What `api_key` actually is today

The requested `Agent(api_key=..., private_key=...)` constructor maps `api_key` onto the existing operator-key mechanism (`X-PayReality-Operator-Key`, the same shared administrative credential every other mutating action in this platform already uses). `register()` needs it (creating a new Agent or Principal is an administrative action); `authorize()` does not (it authenticates purely via the agent's own ED25519 signature, exactly like every other signed Intent submission today). `SDK_SECURITY.md` covers the operational implications of this directly and honestly, including that this is presently a single shared secret, not a per-developer credential.

## Why sync-only, for now

The requested example (`agent.authorize(...)` called directly, no `await`) is synchronous, and every SDK most developers compare this to for "feel" (Stripe, OpenAI, Supabase, Anthropic) ships a synchronous client as the default surface. Building only a sync client for this phase, with an async variant as a clearly-scoped future addition, keeps this phase's surface area matched to what was actually asked for.

## What was actually verified, and what wasn't

The 56-test suite in `sdk-python/tests/` runs against mocked HTTP (`unittest.mock`/`requests_mock`-style fixtures), never a real network call, and all 56 pass. That verifies the SDK's own logic: signature construction matches what the server's verification code expects (checked directly against `server/app/domain/auth/signature.py`'s verification function, not just re-implemented and trusted), retry/backoff behavior, header assembly, exception mapping, and the credential store's idempotency.

`Agent.health()` and `Agent.version()` were confirmed live against real production (`GET https://api.aisecurewatch.com/health` returned `{"status": "ok"}`; `GET /version` returned the commit this SDK was pushed in as the currently-deployed backend commit). A full mutating round trip (using the stored admin operator key to call `register()` and submit one real signed `authorize()`) was attempted and blocked by the environment's permission controls before any request left the machine, so it remains unverified. That gap is stated plainly rather than assumed to have passed, matching this project's established practice (see `POLICY_STUDIO_ARCHITECTURE.md`'s equivalent note on the Deploy action) of being explicit about what was unit-tested versus what was actually exercised live.

## Retry and error mapping, one sentence each

Retried: connection failures, timeouts, and 5xx responses, with capped exponential backoff (`retry.py`). Never retried: 401, 403, and any other 4xx (`422` validation failures included), since none of these can succeed by trying again unmodified. Every failure path, network or HTTP, is mapped onto one of the exceptions in `exceptions.py` before it reaches calling code (`client.py::_raise_for_response`); a developer using this SDK never sees a raw `requests` exception or a bare status code.

Note this is a different layer from `wait_for_resolution()`'s own polling loop (Human Review Continuation milestone, issue #10): `retry.py`'s retries happen *inside* a single `get_decision()` call, for a transient failure of that one HTTP request; `wait_for_resolution()`'s loop happens *around* repeated, successful `get_decision()` calls, waiting for the decision itself to change state. The two don't duplicate each other -- a single poll inside `wait_for_resolution()` still gets `retry.py`'s normal transient-failure handling for free.

## Design note: webhooks (NOT BUILT / NOT PART OF CURRENT RUNTIME CONTRACT)

Human Review Continuation (issue #10) considered, and deliberately did not build, a push mechanism (webhook or callback) for decision resolution. This section exists so the option is written down, not forgotten -- it describes a shape a future milestone *could* take, not something this SDK, the server, or any shipped contract currently does. Nothing below is implemented; no endpoint, no config field, no delivery code exists anywhere in this repository.

**Why polling was chosen instead, for now:** the machine-continuation contract this milestone had to ship is narrow -- an AI asks for authorization, gets `HUMAN_REVIEW`, and later needs to reliably learn the final resolution. Bounded polling (`wait_for_resolution()`) satisfies that completely, with a synchronous, single-call surface and no new server-side infrastructure (no delivery queue, no retry-on-failed-delivery logic, no signature scheme for inbound webhook payloads, no endpoint-registration UI). A webhook is a strictly larger commitment: it turns PayReality from "a service you call and poll" into "a service that calls you back reliably," which drags in exactly the orchestration-platform concerns (delivery guarantees, ordering, replay protection, dead-lettering, per-organization endpoint management) this milestone was explicitly told to stay away from.

**What a future design would need to answer, if ever pursued:** how a callback URL gets registered per-organization or per-agent; what payload shape and signing scheme it would use (likely reusing the existing Ed25519 Evidence-signing key, not a new secret); at-least-once vs. exactly-once delivery semantics and how a caller would deduplicate; retry/backoff for a caller's endpoint being briefly unreachable; and whether it would replace polling or simply supplement it (bounded polling remains useful as a fallback even if a webhook exists, since a caller's endpoint can always be down when the resolution actually happens). None of these questions are answered here on purpose -- answering them prematurely, without a real caller who needs push delivery, is exactly the scope creep this note exists to head off.
