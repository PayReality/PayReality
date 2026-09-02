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
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from .agent import Agent
from .models import ConsumedCapability

T = TypeVar("T")


class CapabilityEnforcer:
    """Configured once per enforcement checkpoint (the same scope one
    real customer-operated PEP already has): which organisation's
    Capabilities it verifies (via `agent`'s own credentials), which
    named audience it presents itself as, and optionally which
    environment/Runtime Connection it expects. `enforce()` is then
    called once per proposed downstream operation, naming exactly what
    that operation is (`action`/`resource`/`constraints`) so it can be
    checked against the Capability's own signed claim, not assumed."""

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
