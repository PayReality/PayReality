"""Integration Kit v1, Part B: a generic, configuration-driven Trusted
Adapter template, so a customer wiring PayReality into their own HTTP
receiver (a webhook handler, an internal API, a queue consumer callback
-- anything that hands this template one already-received payload as a
plain dict) doesn't have to hand-roll the attestation call themselves.

This is pure productization over `payreality.integration.Adapter`, which
already does the real work correctly (signing, IntegrationIdentity auth,
external_operation_id idempotency) -- `HttpApiAdapterTemplate` never
reimplements any of that; it only adds configuration-driven field
extraction in front of the existing `Adapter.attest()` call.

Only one template ships in Integration Kit v1: the transport-agnostic
"receive a payload as a dict, extract fields per configuration" shape,
named for its most common trigger (an HTTP webhook/API call). The same
shape covers a message-queue consumer or a reverse-proxy/gateway plugin
equally well -- they all reduce to "some trigger hands you a payload
dict" -- but this milestone ships and tests only the one class; it does
not ship separate webhook/queue/gateway subclasses. See
INTEGRATION_KIT.md for what's documented-but-not-built.

What this class deliberately does NOT do (Integration Kit v1, section 8):
- It never lets the incoming payload choose `action` or `source_operation`
  -- both are fixed at configuration time, pinned to an already-approved
  Integration Contract. A payload can supply field VALUES (an amount, a
  resource id); it can never supply which canonical action is being
  attested.
- It never creates or approves an Integration Contract, Runtime
  Connection, or IntegrationIdentity. Those are administrative setup,
  performed via the real API/service layer before this class is ever
  constructed (see INTEGRATION_KIT.md's Adapter Template guide).
- It never falls back to Agent-direct semantics if trusted-adapter
  context is missing or invalid -- a missing required field is a
  configuration error, raised before any network call, never a silent
  downgrade.
"""

from __future__ import annotations

from typing import Any, Callable

from .exceptions import ConfigurationError
from .integration import Adapter, ContractShape
from .models import Decision

FieldSource = "str | Callable[[dict[str, Any]], Any]"


def _resolve(payload: dict[str, Any], source: str | Callable[[dict[str, Any]], Any] | None) -> Any:
    """Resolves one configured field source against one incoming
    payload. A string is a dotted path (`"payment.amount"` ->
    `payload["payment"]["amount"]`); a callable is invoked with the raw
    payload for anything a dotted path can't express. `None` (the field
    wasn't configured at all) always resolves to `None` -- distinguishing
    "not configured" from "configured but missing in this payload" is
    the caller's job (see `AdapterFieldRules.resolve_required`)."""
    if source is None:
        return None
    if callable(source):
        return source(payload)
    current: Any = payload
    for part in source.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


class AdapterFieldRules:
    """Configuration, not code: declares how to pull each Intent field
    out of a customer's own payload shape, and which fields are fixed
    (never read from the payload at all) versus extracted.

    `source_operation`/`action` are always fixed -- see this module's
    own docstring for why. `external_operation_id_source` is required:
    this template never invents one (the same discipline
    `payreality.integration.Adapter.attest()` already documents)."""

    def __init__(
        self,
        *,
        source_operation: str,
        action: str,
        external_operation_id_source: "str | Callable[[dict[str, Any]], Any]",
        origin_agent_id: str | None = None,
        origin_agent_id_source: "str | Callable[[dict[str, Any]], Any] | None" = None,
        resource_source: "str | Callable[[dict[str, Any]], Any] | None" = None,
        amount_source: "str | Callable[[dict[str, Any]], Any] | None" = None,
        currency_source: "str | Callable[[dict[str, Any]], Any] | None" = None,
        counterparty_source: "str | Callable[[dict[str, Any]], Any] | None" = None,
        context_sources: "dict[str, str | Callable[[dict[str, Any]], Any]] | None" = None,
        correlation_id_source: "str | Callable[[dict[str, Any]], Any] | None" = None,
    ):
        if origin_agent_id is not None and origin_agent_id_source is not None:
            raise ConfigurationError(
                "set exactly one of origin_agent_id (fixed) or origin_agent_id_source "
                "(extracted per payload), not both"
            )
        if origin_agent_id is None and origin_agent_id_source is None:
            raise ConfigurationError(
                "origin_agent_id or origin_agent_id_source is required -- this template never "
                "infers which Agent's authority is being evaluated"
            )
        self.source_operation = source_operation
        self.action = action
        self.external_operation_id_source = external_operation_id_source
        self.origin_agent_id = origin_agent_id
        self.origin_agent_id_source = origin_agent_id_source
        self.resource_source = resource_source
        self.amount_source = amount_source
        self.currency_source = currency_source
        self.counterparty_source = counterparty_source
        self.context_sources = context_sources or {}
        self.correlation_id_source = correlation_id_source

    def resolve_origin_agent_id(self, payload: dict[str, Any]) -> str:
        if self.origin_agent_id is not None:
            return self.origin_agent_id
        value = _resolve(payload, self.origin_agent_id_source)
        if not isinstance(value, str) or not value:
            raise ConfigurationError(
                "origin_agent_id_source did not resolve to a non-empty string for this payload"
            )
        return value

    def resolve_external_operation_id(self, payload: dict[str, Any]) -> str:
        value = _resolve(payload, self.external_operation_id_source)
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(
                "external_operation_id_source did not resolve to a non-empty string for this "
                "payload -- refusing to submit an attestation with no stable operation identity"
            )
        return value

    def resolve_optional_fields(self, payload: dict[str, Any]) -> dict[str, Any]:
        context = {k: _resolve(payload, v) for k, v in self.context_sources.items()}
        missing_context = [k for k, v in context.items() if v is None]
        if missing_context:
            raise ConfigurationError(
                f"context field(s) {sorted(missing_context)} did not resolve for this payload"
            )
        return {
            "resource": _resolve(payload, self.resource_source),
            "amount": _resolve(payload, self.amount_source),
            "currency": _resolve(payload, self.currency_source),
            "counterparty": _resolve(payload, self.counterparty_source),
            "context": context,
            "correlation_id": _resolve(payload, self.correlation_id_source),
        }


class HttpApiAdapterTemplate:
    """The generic Trusted Adapter template. Construct once per
    (IntegrationIdentity, Runtime Connection, Integration Contract)
    combination -- exactly the scope one real Trusted Adapter deployment
    already has -- then call `.handle(payload)` once per real attempted
    enterprise operation your own receiving code observes.

    This class does not receive the operation itself (it doesn't open a
    socket, register a webhook route, or poll a queue): your own code
    does that, and hands the resulting payload here as a plain dict.
    That division of responsibility is deliberate -- see this module's
    own docstring on what a generic template does and does not do."""

    def __init__(
        self,
        *,
        integration_identity_id: str,
        certificate_id: str,
        private_key: str,
        enforcement_binding_id: str,
        fields: AdapterFieldRules,
        base_url: str = "https://api.aisecurewatch.com",
        timeout: float = 10.0,
        retry_count: int = 3,
        contract_shape: ContractShape | None = None,
    ):
        self._adapter = Adapter(
            integration_identity_id=integration_identity_id,
            certificate_id=certificate_id,
            private_key=private_key,
            base_url=base_url,
            timeout=timeout,
            retry_count=retry_count,
            contract_shape=contract_shape,
        )
        self._enforcement_binding_id = enforcement_binding_id
        self._fields = fields

    def handle(self, payload: dict[str, Any]) -> Decision:
        """Extracts every configured field from `payload`, fails closed
        (`ConfigurationError`, never a network call) if a required one
        is missing, then submits the real attested Intent through
        `Adapter.attest()` unchanged. Returns the same real `Decision`
        `attest()` returns -- Allow, Deny, or Human Review, with real
        Evidence behind it."""
        origin_agent_id = self._fields.resolve_origin_agent_id(payload)
        external_operation_id = self._fields.resolve_external_operation_id(payload)
        optional = self._fields.resolve_optional_fields(payload)
        return self._adapter.attest(
            enforcement_binding_id=self._enforcement_binding_id,
            origin_agent_id=origin_agent_id,
            source_operation=self._fields.source_operation,
            action=self._fields.action,
            external_operation_id=external_operation_id,
            **optional,
        )
