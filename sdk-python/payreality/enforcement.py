"""Integration Kit v1, Part C: a reference Capability-enforcement
component, so a customer's own enforcement checkpoint doesn't have to
hand-write the verify-and-consume lifecycle (the way
`scripts/reference_enforcement_adapter.py` in the platform repo does,
as a single-shot CLI script with its own hand-rolled HTTP calls).

`CapabilityEnforcer` is a plain, framework-agnostic Python callable
wrapper -- not an ASGI/FastAPI-specific dependency, not a new ecosystem.
It composes with `Agent.verify_capability()` unchanged: every Phase
5.1/6/6.1 guarantee (single-use, tenant-scoped, freshness-rechecked,
replay-rejected, no auto-renewal) is inherited by construction, because
this is the exact same code path, not a reimplementation of it.

What this does NOT do: it does not parse or verify a Capability token's
signature itself (that's the server's own job, via the real API call);
it does not decide what "the downstream operation" is (the caller
already knows -- see `enforce()`'s own arguments); and it never calls
the downstream handler except after `verify_capability()` has already
returned successfully. `downstream`'s own return value and the fact
that the Capability was consumed are two distinct things this module
never conflates -- see `enforce()`'s own docstring.

Post-audit implementation, Priority 4 (the pluggable enforcement
boundary): `EnforcementAdapter` below is the stable contract this SDK's
own `CapabilityEnforcer` implements, not the only thing PayReality will
ever accept as an enforcement checkpoint. A future adapter for Microsoft's
Agent Governance Toolkit, an Envoy filter, a customer's own API gateway,
or a destination-native connector can implement this exact same shape
(receive/extract the attempted action, present the Capability, verify it,
consume it exactly once, call downstream only on success, return a
structured result) without PayReality's own authority-domain logic (Runtime
Authority, the Authority Graph, Capability issuance itself) ever having to
change to accommodate it. See tests/test_enforcement_contract.py in this
package's own test suite for the executable version of this contract,
run today against `CapabilityEnforcer` -- the one concrete implementation
that exists.

Bypass limitation, stated honestly and not softened: PayReality cannot
prevent execution paths that the customer does not route through an
enforcement point. Nothing in this module, or in any conforming adapter,
changes that -- a downstream system reachable by some other path entirely
(a direct database write, a different API, a human with production
access) is simply outside what any PEP, PayReality's own reference one
included, can see or stop.

Atomicity, stated honestly and not overclaimed: verifying and consuming a
Capability is a single atomic operation on PayReality's own side (the
server-side UPDATE ... WHERE consumed_at IS NULL this composes with). It
is NOT, and this module makes no claim that it is, part of a single
distributed transaction with whatever `downstream` does next -- if
`downstream` raises after a successful consumption, the Capability stays
consumed; PayReality has no rollback mechanism for that, because it was
never a party to `downstream`'s own transaction in the first place. A
caller that needs true all-or-nothing semantics across both must design
for that itself (e.g. an idempotent downstream operation, or its own
compensating action), not assume this module provides it.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, TypeVar, runtime_checkable

from .agent import Agent
from .models import ConsumedCapability

T = TypeVar("T")


@runtime_checkable
class EnforcementAdapter(Protocol):
    """The stable PayReality-side enforcement contract (Priority 4). Any
    object exposing these two methods, with this exact behavior, is a
    conforming enforcement adapter -- structural typing (`Protocol`), not
    inheritance, so an adapter never needs to depend on this SDK's own
    class hierarchy, only match its shape. `CapabilityEnforcer` below is
    the one reference implementation; see this module's own top-level
    docstring for what a future adapter (Microsoft's toolkit, Envoy, a
    customer gateway) would need to satisfy to conform.

    Required behavior for any conformant implementation, verified by
    tests/test_enforcement_contract.py's own reusable contract-test
    suite:

      1. `verify()` presents the Capability to PayReality and returns a
         `ConsumedCapability` only on a real, successful verify-and-
         consume -- signature, issuer, tenant, audience, expiration, and
         exact-action/resource/constraint binding are all checked
         server-side; a mismatch on any of them raises a typed exception,
         never a silent False/None.
      2. Consumption is atomic and single-use: a second presentation of
         an already-consumed token must fail, never succeed twice.
      3. `enforce()` calls `downstream` if, and only if, `verify()`
         succeeded -- never before, never on any rejection path.
      4. An exception `downstream` itself raises propagates unchanged;
         the Capability's own consumed state is not affected by it (see
         this module's own "Atomicity" note above).
      5. Whatever correlation/external-operation identifier the caller's
         own downstream operation needs is the caller's responsibility to
         thread through `downstream`'s own closure or the `constraints`
         dict -- this contract does not invent a second identifier
         scheme."""

    def verify(
        self, token: str, *, action: str, resource: str, constraints: dict[str, Any], principal: str | None = None,
    ) -> ConsumedCapability: ...

    def enforce(
        self, token: str, *, action: str, resource: str, constraints: dict[str, Any],
        downstream: Callable[[ConsumedCapability], T], principal: str | None = None,
    ) -> T: ...


class CapabilityEnforcer:
    """Configured once per enforcement checkpoint (the same scope one
    real customer-operated PEP already has): which organisation's
    Capabilities it verifies (via `agent`'s own credentials), which
    named audience it presents itself as, and optionally which
    environment/Runtime Connection it expects. `enforce()` is then
    called once per proposed downstream operation, naming exactly what
    that operation is (`action`/`resource`/`constraints`) so it can be
    checked against the Capability's own signed claim, not assumed.

    The reference implementation of `EnforcementAdapter` (above) -- the
    one this SDK ships and the one every enforcement-boundary test in
    this package's own test suite exercises. Not the only implementation
    PayReality will ever accept; see `EnforcementAdapter`'s own docstring."""

    def __init__(
        self,
        *,
        agent: Agent,
        audience: str,
        environment: str | None = None,
        enforcement_binding_id: str | None = None,
    ):
        self._agent = agent
        self._audience = audience
        self._environment = environment
        self._enforcement_binding_id = enforcement_binding_id

    def verify(
        self,
        token: str,
        *,
        action: str,
        resource: str,
        constraints: dict[str, Any],
        principal: str | None = None,
    ) -> ConsumedCapability:
        """Verifies and consumes `token` against this checkpoint's
        configured audience/environment/binding and the caller-supplied
        action/resource/constraints/principal describing the proposed
        operation. Raises one of `payreality.exceptions`'s typed
        Capability exceptions on any mismatch, expiry, replay, or
        inactive-trust condition -- see `Agent.verify_capability()`'s
        own docstring for the full list. Never calls anything else;
        pair with `enforce()` if you want the downstream call wired in
        automatically."""
        return self._agent.verify_capability(
            token,
            self._audience,
            action,
            resource,
            constraints,
            environment=self._environment,
            enforcement_binding_id=self._enforcement_binding_id,
            principal=principal,
        )

    def enforce(
        self,
        token: str,
        *,
        action: str,
        resource: str,
        constraints: dict[str, Any],
        downstream: Callable[[ConsumedCapability], T],
        principal: str | None = None,
    ) -> T:
        """Verifies and consumes `token`, then -- only if that succeeds
        -- calls `downstream(consumed_capability)` and returns whatever
        it returns. If verification fails, `downstream` is never called
        and the typed exception propagates unchanged: there is no
        partial-success path.

        `downstream`'s return value is handed back exactly as-is. It is
        never inspected, wrapped, or treated as additional proof of
        anything -- a successful return from `enforce()` means the
        Capability was consumed and `downstream` ran without raising;
        it does not mean, and this method makes no claim, that whatever
        `downstream` did actually completed correctly on its own terms.
        Consuming a Capability and a downstream operation succeeding
        remain two separate facts."""
        consumed = self.verify(token, action=action, resource=resource, constraints=constraints, principal=principal)
        return downstream(consumed)

    def wrap(self, downstream: Callable[[ConsumedCapability], T]) -> Callable[..., T]:
        """Decorator form of `enforce()`, for a downstream handler you'd
        rather define once and reuse: `wrapped = enforcer.wrap(my_handler)`,
        then call `wrapped(token, action=..., resource=..., constraints=...)`
        wherever the original enforcement call would have gone. `my_handler`
        itself keeps the exact same signature `enforce()`'s own `downstream`
        argument already requires -- this is pure convenience, not a second
        mechanism."""

        def wrapped(
            token: str,
            *,
            action: str,
            resource: str,
            constraints: dict[str, Any],
            principal: str | None = None,
        ) -> T:
            return self.enforce(
                token, action=action, resource=resource, constraints=constraints,
                downstream=downstream, principal=principal,
            )

        return wrapped
