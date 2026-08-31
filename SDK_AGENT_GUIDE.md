# SDK Agent Guide

Phase 9 (AGENT_LIFECYCLE.md) added three methods to `payreality.Agent`: `rotate_keys()`, `heartbeat()`, and `retire()`. None of them expose ED25519, certificates, or HTTP headers to the calling code, the same design bar `register()`/`authorize()` were already held to in Phase 8 (SDK_ARCHITECTURE.md).

## Rotating keys

```python
from payreality import Agent

agent = Agent(api_key="...", private_key=stored_private_key)
new_identity = agent.rotate_keys()
print(new_identity.certificate_id)  # the new certificate's ID
```

`rotate_keys()` generates a new ED25519 key pair locally, uploads only the new public key (`POST /agents/{id}/rotate`, the same shared operator credential `register()` already uses), and updates this `Agent` instance to sign with the new key from this point on. The old private key is discarded the moment this call returns; this SDK never keeps more than one private key per `Agent` around, on top of the platform itself never storing one at all (SDK_SECURITY.md). The local credential store (keyed by public key) drops the old entry and adds one under the new key, so a future `Agent(private_key=...)` constructed with the new key still loads correctly.

Nothing about past decisions changes: every Evidence record produced before rotation stays exactly as valid as it was (CERTIFICATE_ROTATION.md verifies this directly against the schema, not just by assertion).

## Heartbeat

```python
agent.heartbeat(version="1.4.0", runtime="Azure Foundry")
```

Reports this agent as alive. Unlike `register()`/`rotate_keys()`/`retire()`, this is **not** authenticated with the shared operator key: it's signed with the agent's own certificate, the same way `authorize()` signs an Intent, because a heartbeat is the agent asserting its own liveness, not an administrative action. All three parameters (`version`, `sdk_version`, `runtime`) are optional; `sdk_version` defaults to this package's own actual version (`payreality-python/0.5.0` as of this writing — `agent.py`'s `_SDK_VERSION` constant, not a hardcoded literal, so this default tracks the real installed package version automatically) if not given. Call it however often makes sense for your deployment (e.g. once per process start, or on a timer); there's no minimum interval enforced, though see AGENT_DIRECTORY.md's Healthy/Warning/Offline thresholds (5 / 30 minutes) for how often actually matters to the dashboard.

## Retiring an agent

```python
agent.retire(reason="decommissioned, replaced by v2")
```

Permanently removes this agent from operational use. This is a server-side, terminal action, not a local flag: once retired, no `Agent` instance signing with this identity's key, not just this one Python object, can submit Intents or heartbeats again. Historical Evidence is unaffected. Calling `agent.authorize(...)` on an `Agent` this process itself just retired fails immediately with `ConfigurationError`, without a network round trip: `RegisteredAgent.status` is updated locally to `"retired"` as part of `retire()`, and `authorize()` checks it before doing anything else.

## Design decision: why `register()` didn't become two calls

The platform's own registration flow changed this phase: a newly created Agent starts in a `registered` state, not operational, until a separate activation step runs (AGENT_LIFECYCLE.md). The literal, most "honest" SDK change would have been to require `agent.register()` then a new `agent.activate()` before `authorize()` would work.

That wasn't done, deliberately. Phase 9's own spec lists exactly four SDK methods this phase should add or already have: `register()`, `rotate_keys()`, `heartbeat()`, `retire()` -- no `activate()`. Read together with Phase 8's success criterion ("install and start using in under 5 minutes... no manual signing/headers/cryptography knowledge required"), the conclusion is that `register()` should still hand back a ready-to-use identity in one call. So `register()` now makes two HTTP calls under the hood (create, then activate), both using the same operator credential it already required, and returns a `RegisteredAgent` with `status="active"`.

This is a real, named trade-off, not a free lunch: a developer using the raw HTTP API directly (not this SDK) gets the more realistic two-step enterprise flow, with room for a human approval gate between registration and activation. A developer using this SDK gets the one-call convenience Phase 8 promised, at the cost of that gate not existing for them. If a future need arises for the SDK to support a reviewed-activation workflow, that's an additive method (e.g. `Agent(..., auto_activate=False)`), not a reason to revisit this default.

## What's still true from Phase 8

`api_key` is still today's single shared operator credential (SDK_SECURITY.md); `rotate_keys()` and `retire()` both use it the same way `register()` already did, for the same reason (creating, activating, rotating, and retiring an agent are all administrative actions). `heartbeat()` is the one lifecycle method that doesn't need it, exactly like `authorize()` didn't. Nothing in this phase changes that credential model; see SDK_SECURITY.md and AGENT_LIFECYCLE.md's known-gaps notes for the standing plan to replace it with scoped, per-developer credentials.
