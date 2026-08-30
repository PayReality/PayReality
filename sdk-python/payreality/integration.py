"""Trusted Integration Architecture, Phase 2: the higher-assurance
runtime helper a customer-operated Adapter uses to submit an attested
Intent through PayReality's separately authenticated trusted-Adapter
path (POST /v1/integration-runtime/intents). Additive alongside
`Agent.authorize()` -- that class, and the Agent-direct path it calls,
are entirely unchanged.

`Adapter` authenticates as an IntegrationIdentity, never as an Agent.
It does not observe the real external operation it describes -- the
caller (the customer's own Adapter code, which does observe it) is
what attests the operation happened and supplies the canonical values;
this class only signs and transmits that attestation using the same
ED25519 discipline `Agent.authorize()` already uses (crypto.py/auth.py,
unchanged).

Trust claim, stated precisely -- do not read this class as proving
more than this: a successful `attest()` call means PayReality verified
that an authenticated Integration Identity, acting under an active
Enforcement Binding, attests to having observed this operation and
constructed this Intent using an approved Integration Contract. It
does not mean the external system actually executed the operation, that
the Adapter's own code is free of bugs, or that no other path to the
same effect exists.
"""

from __future__ import annotations

import json
from typing import Any

from . import auth
from .client import HttpClient
from .configuration import Configuration
from .exceptions import ConfigurationError
from .models import Decision


class ContractShape:
    """Optional, purely local declaration of which fields THIS
    Adapter's pinned Integration Contract version actually declares --
    lets `Adapter.attest()` reject an obviously-wrong call (a context
    key, or a resource/amount/currency/counterparty value, the Contract
    doesn't declare) before ever making a network request. Mirrors the
    same field-path presence/absence rule
    server/app/services/integration_runtime_service.py enforces
    authoritatively (Phase 1's resource_path/amount_path/currency_path/
    fact_subject_path/context_bindings -- not a new mapping language of
    its own). Purely a local convenience: the server's own check is
    what actually matters and remains authoritative even if this is
    never supplied, or has gone stale relative to the Contract."""

    def __init__(
        self,
        *,
        has_resource: bool = False,
        has_amount: bool = False,
        has_currency: bool = False,
        has_fact_subject: bool = False,
        context_keys: frozenset[str] = frozenset(),
    ):
        self.has_resource = has_resource
        self.has_amount = has_amount
        self.has_currency = has_currency
        self.has_fact_subject = has_fact_subject
        self.context_keys = frozenset(context_keys)

    def check(self, *, resource, amount, currency, counterparty, context: dict[str, Any]) -> None:
        def _check(name: str, declared: bool, value: Any) -> None:
            if declared and value is None:
                raise ConfigurationError(
                    f"this Integration Contract declares an extraction path for {name}; a value is required"
                )
            if not declared and value is not None:
                raise ConfigurationError(
                    f"this Integration Contract declares no extraction path for {name}; do not supply a value"
                )

        _check("resource", self.has_resource, resource)
        _check("amount", self.has_amount, amount)
        _check("currency", self.has_currency, currency)
        _check("fact_subject (counterparty)", self.has_fact_subject, counterparty)

        supplied = set(context.keys())
        unexpected = supplied - self.context_keys
        if unexpected:
            raise ConfigurationError(
                f"context keys not declared by this Integration Contract's context_bindings: {sorted(unexpected)}"
            )
        missing = self.context_keys - supplied
        if missing:
            raise ConfigurationError(
                f"missing context keys this Integration Contract's context_bindings require: {sorted(missing)}"
            )


class Adapter:
    def __init__(
        self,
        integration_identity_id: str,
        certificate_id: str,
        private_key: str,
        base_url: str = "https://api.aisecurewatch.com",
        timeout: float = 10.0,
        retry_count: int = 3,
        contract_shape: ContractShape | None = None,
    ):
        """`integration_identity_id`/`certificate_id` identify this
        Adapter's registered IntegrationIdentity and its currently
        active certificate -- registering an IntegrationIdentity and
        rotating its certificate are administrative actions performed
        via the raw HTTP API (or a future admin SDK surface), not part
        of this class, which is purely the runtime-attestation path.
        `private_key` never leaves this process. `contract_shape`, if
        given, enables the local pre-flight check `ContractShape`
        documents; omit it to skip that check and rely solely on the
        server's own authoritative validation."""
        self._integration_identity_id = integration_identity_id
        self._certificate_id = certificate_id
        self._private_key = private_key
        self._contract_shape = contract_shape
        self._client = HttpClient(Configuration(base_url=base_url, timeout=timeout, retry_count=retry_count))

    def attest(
        self,
        *,
        enforcement_binding_id: str,
        origin_agent_id: str,
        source_operation: str,
        action: str,
        resource: str | None = None,
        amount: float | None = None,
        currency: str | None = None,
        counterparty: str | None = None,
        context: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> Decision:
        """Constructs, signs, and submits one attested Intent through
        the trusted-Adapter runtime path.

        `origin_agent_id` names the logical Agent whose authority is
        being evaluated -- this call attests it observed that Agent's
        operation via `enforcement_binding_id`'s allowed-Agent list; it
        does not authenticate as that Agent, and PayReality still
        verifies (server-side) that the named Agent is actually allowed
        under this exact Binding. `source_operation`/`action` must
        exactly match the Binding's pinned Integration Contract version
        or the request is rejected before evaluation, not routed to
        human review.

        This method does not itself observe the external operation it
        describes, and its return value is not proof that operation
        executed -- see this module's own docstring for the full,
        deliberately unsoftened trust claim.
        """
        context = context or {}
        if self._contract_shape is not None:
            self._contract_shape.check(
                resource=resource, amount=amount, currency=currency, counterparty=counterparty, context=context,
            )

        body = {
            "integration_identity_id": self._integration_identity_id,
            "enforcement_binding_id": enforcement_binding_id,
            "origin_agent_id": origin_agent_id,
            "source_operation": source_operation,
            "action": action,
            "resource": resource,
            "amount": amount,
            "currency": currency,
            "counterparty": counterparty,
            "context": context,
            "requested_at": auth.utc_now_iso(),
            "nonce": auth.new_nonce(),
            "correlation_id": correlation_id,
        }
        body_bytes = json.dumps(body).encode("utf-8")
        headers = auth.signed_headers(body_bytes, self._certificate_id, self._private_key)

        response = self._client.request(
            "POST", "/v1/integration-runtime/intents", signed_body=body_bytes, headers=headers,
        )
        decision = response["decision"]
        return Decision(
            outcome=decision["outcome"],
            decision_id=decision["decision_id"],
            evidence_id=response.get("evidence_id"),
            reason=decision.get("reason"),
            explanation=decision.get("reason"),
            status=response["status"],
            evaluated_mandates=tuple(decision.get("evaluated_mandates", [])),
            correlation_id=response.get("correlation_id"),
        )
