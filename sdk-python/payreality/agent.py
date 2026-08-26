"""The only class most developers using this SDK will ever import.

    from payreality import Agent

    agent = Agent(api_key="...", private_key="...", organization_id="...")
    decision = agent.authorize(
        principal="Finance Manager",
        operation="Approve",
        resource="Vendor Payment",
        resource_data={"amount": 85000, "vendor": "ABC Ltd"},
    )

Every piece of ED25519 signing, certificate management, and HTTP
plumbing this needs lives in the other modules in this package;
`Agent` is where they're wired together behind a small, stable surface.
"""

from __future__ import annotations

import json
from typing import Any

from . import auth, crypto
from .client import HttpClient
from .configuration import Configuration, CredentialStore
from .exceptions import ApiError, ConfigurationError
from .models import Decision, RegisteredAgent, Resolution

_SDK_VERSION = "0.4.0"  # kept in sync with pyproject.toml / __init__.__version__ by hand;
# not imported from there to avoid a circular import at package init time.
# Bumped 0.1.0 -> 0.2.0 for organization_id: a real breaking change under
# semver -- every operator-key call that previously worked now requires
# it (PayReality Enterprise v1.0, Milestone 2's platform-admin-only
# operator key).
# Bumped 0.2.0 -> 0.3.0 for bearer_token (BACKLOG_V1_CLOSURE.md's "SDK
# has no real auth beyond the Operator Key"): purely additive, not
# breaking -- every existing api_key-based call keeps working
# unmodified, this only adds a second, preferred way to authenticate
# administrative calls as a real, scoped identity.
# Bumped 0.3.0 -> 0.4.0 for authorize() (Domain Generalization
# Milestone), a real breaking change under semver: `resource` used to
# hold the action name (a naming mistake -- `operation` was accepted
# but never actually used as the Runtime Policy action) and
# `resource_data["amount"]` was required even for a non-financial
# action. `operation` now becomes the real action; `resource` now
# becomes the real, generic resource identifier
# (Intent.resource, db/models.py); `amount`/`currency` are optional.
# No real integration exists yet against the old shape (confirmed via
# this milestone's own audit), so the blast radius of this break is
# zero in practice, but it is disclosed here exactly like the two
# breaking bumps above.


class Agent:
    def __init__(
        self,
        api_key: str | None = None,
        bearer_token: str | None = None,
        private_key: str | None = None,
        organization_id: str | None = None,
        base_url: str = "https://api.aisecurewatch.com",
        timeout: float = 10.0,
        retry_count: int = 3,
        credentials_path=None,
    ):
        """`api_key` is the platform-wide Operator Key -- works, but
        authenticates as the admin bypass, not a real scoped identity.
        `bearer_token` is the alternative for administrative calls
        (register/rotate_keys/retire/get_decision): a session token
        (`POST /v1/auth/login`) or a scoped API key
        (`POST /v1/organization/api-keys`), either one accepted
        identically. Prefer `bearer_token` for anything beyond local
        development -- see Configuration's own docstring for the full
        reasoning. `authorize()` and `heartbeat()` need neither: they
        authenticate purely via this agent's own certificate signature."""
        config_kwargs: dict[str, Any] = dict(
            api_key=api_key,
            bearer_token=bearer_token,
            private_key=private_key,
            organization_id=organization_id,
            base_url=base_url,
            timeout=timeout,
            retry_count=retry_count,
        )
        if credentials_path is not None:
            config_kwargs["credentials_path"] = credentials_path
        self._config = Configuration(**config_kwargs)
        self._client = HttpClient(self._config)
        self._store = CredentialStore(self._config.credentials_path)

        self._private_key: str | None = private_key
        self._identity: RegisteredAgent | None = None
        if self._private_key:
            self._load_identity_from_store()

    # -- identity -----------------------------------------------------

    def _load_identity_from_store(self) -> None:
        public_key = crypto.public_key_from_private(self._private_key)
        record = self._store.get(public_key)
        if record is not None:
            self._identity = RegisteredAgent(**record)

    @property
    def is_registered(self) -> bool:
        """True once this Agent has a server-recognized identity, either
        from a `register()` call this session or loaded from a private
        key that was registered previously."""
        return self._identity is not None

    def _resolve_principal_id(self, name: str) -> tuple[str, str]:
        # Milestone 1 (Security & Authorization Hardening) gated
        # GET /v1/principals behind an organization/permission check;
        # this call was never updated to send credentials of any kind,
        # so it 401'd on every real deployment before this fix, masking
        # register()'s own organization_id requirement below (confirmed
        # in a Milestone-3-era SDK audit). admin_auth=True matches
        # the POST call's own, already-correct convention just below.
        principals = self._client.request("GET", "/v1/principals", admin_auth=True)
        for p in principals:
            if p["name"] == name:
                return p["id"], p["name"]
        created = self._client.request(
            "POST", "/v1/principals", json={"name": name}, admin_auth=True
        )
        return created["id"], created["name"]

    def register(
        self,
        name: str,
        principal: str,
        owner: str | None = None,
        description: str | None = None,
    ) -> RegisteredAgent:
        """Registers this agent's public key with PayReality. Generates
        a keypair automatically if this Agent wasn't constructed with an
        explicit `private_key`; either way, the private key never
        leaves this machine; only the public key is sent.

        Idempotent per key: calling this again with the same private
        key (e.g. on every process restart) returns the identity already
        on file instead of registering a second time.

        As of Phase 9 (AGENT_LIFECYCLE.md), a newly created agent starts
        in the "registered" state on the server, not "active": it isn't
        operational (can't sign Intents) until a separate activation
        step runs. This method still returns a ready-to-use identity in
        one call by chaining that activation automatically -- the
        alternative would have been a breaking change to this method's
        contract from Phase 8 (see SDK_AGENT_GUIDE.md's design-decisions
        section). Use the raw HTTP API directly, not this SDK, if you
        want registration and activation to be two distinct, separately
        reviewable steps (e.g. an approval gate between them).
        """
        if self._private_key is None:
            keypair = crypto.generate_keypair()
            self._private_key = keypair.private_key_b64
            public_key = keypair.public_key_b64
        else:
            public_key = crypto.public_key_from_private(self._private_key)

        existing = self._store.get(public_key)
        if existing is not None:
            self._identity = RegisteredAgent(**existing)
            return self._identity

        principal_id, principal_name = self._resolve_principal_id(principal)

        response = self._client.request(
            "POST",
            "/v1/agents",
            json={
                "name": name,
                "acting_for_principal_id": principal_id,
                "public_key": crypto.encode_public_key_for_wire(public_key),
                "owner": owner,
                "description": description,
            },
            admin_auth=True,
        )
        self._client.request(
            "POST", f"/v1/agents/{response['id']}/activate", json={}, admin_auth=True
        )

        identity = RegisteredAgent(
            agent_id=response["id"],
            certificate_id=response["certificate_id"],
            principal_id=principal_id,
            principal_name=principal_name,
            name=name,
            status="active",
        )
        self._store.save(public_key, identity.__dict__)
        self._identity = identity
        return identity

    def rotate_keys(self) -> RegisteredAgent:
        """Certificate rotation (CERTIFICATE_ROTATION.md), without the
        caller ever touching a key directly: generates a new ED25519 key
        pair locally, uploads only the new public key, and PayReality
        marks the old certificate 'rotated' (never deleted) while the
        new one becomes active. The old private key is discarded the
        moment this returns -- this SDK never persists more than one
        private key per Agent instance, matching SDK_SECURITY.md's "no
        private keys are ever stored by PayReality" for the server side,
        and simply not keeping old ones around on the client side either.

        Past Decisions and Evidence tied to Intents signed with the old
        key remain exactly as valid as they were before rotating; nothing
        about them references a certificate directly (AGENT_LIFECYCLE.md).
        """
        if self._identity is None:
            raise ConfigurationError(
                "This Agent has no registered identity yet. Call agent.register(...) first."
            )
        old_public_key = crypto.public_key_from_private(self._private_key)
        new_keypair = crypto.generate_keypair()

        response = self._client.request(
            "POST",
            f"/v1/agents/{self._identity.agent_id}/rotate",
            json={"new_public_key": crypto.encode_public_key_for_wire(new_keypair.public_key_b64)},
            admin_auth=True,
        )

        new_identity = RegisteredAgent(
            agent_id=self._identity.agent_id,
            certificate_id=response["id"],
            principal_id=self._identity.principal_id,
            principal_name=self._identity.principal_name,
            name=self._identity.name,
            status=self._identity.status,
        )
        self._private_key = new_keypair.private_key_b64
        self._identity = new_identity
        self._store.save(new_keypair.public_key_b64, new_identity.__dict__)
        self._store.delete(old_public_key)
        return new_identity

    def heartbeat(
        self,
        version: str | None = None,
        sdk_version: str | None = None,
        runtime: str | None = None,
    ) -> dict[str, Any]:
        """Reports this agent as alive (AGENT_LIFECYCLE.md's Agent
        Heartbeat). Signed the same way an Intent is, with this agent's
        own certificate -- not the shared operator key -- since a
        heartbeat is the agent asserting its own liveness, not an
        administrative action. `sdk_version` defaults to this package's
        own version if not given."""
        if self._identity is None:
            raise ConfigurationError(
                "This Agent has no registered identity yet. Call agent.register(...) first."
            )
        body = {
            "version": version,
            "sdk_version": sdk_version or f"payreality-python/{_SDK_VERSION}",
            "runtime": runtime,
        }
        body_bytes = json.dumps(body).encode("utf-8")
        headers = auth.signed_headers(body_bytes, self._identity.certificate_id, self._private_key)
        return self._client.request(
            "POST", f"/v1/agents/{self._identity.agent_id}/heartbeat",
            signed_body=body_bytes, headers=headers,
        )

    def retire(self, reason: str | None = None) -> RegisteredAgent:
        """Permanently removes this agent from operational use
        (AGENT_LIFECYCLE.md's Retired state, terminal). Historical
        Evidence is unaffected; this agent can no longer submit Intents
        or heartbeats afterward, from any Agent instance, not just this
        one -- retirement is a server-side, not local, action."""
        if self._identity is None:
            raise ConfigurationError(
                "This Agent has no registered identity yet. Call agent.register(...) first."
            )
        self._client.request(
            "POST", f"/v1/agents/{self._identity.agent_id}/retire",
            json={"reason": reason}, admin_auth=True,
        )
        retired_identity = RegisteredAgent(
            agent_id=self._identity.agent_id,
            certificate_id=self._identity.certificate_id,
            principal_id=self._identity.principal_id,
            principal_name=self._identity.principal_name,
            name=self._identity.name,
            status="retired",
        )
        self._identity = retired_identity
        public_key = crypto.public_key_from_private(self._private_key)
        self._store.save(public_key, retired_identity.__dict__)
        return retired_identity

    # -- authorization --------------------------------------------------

    def authorize(
        self,
        principal: str,
        operation: str,
        resource: str | None = None,
        resource_data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> Decision:
        """Authorizes one action, synchronously, in one call. Signs and
        sends the request itself; nothing about ED25519, headers, or
        timestamps is the caller's problem.

        `principal` is checked against the principal this agent was
        registered for (a local safety check, not sent to the server:
        PayReality already knows which principal a given certificate
        acts for from registration, see SDK_ARCHITECTURE.md) and raises
        `ConfigurationError` on a mismatch, catching a wrong-agent
        mistake before it ever reaches the network.

        `operation` becomes the Runtime Policy action this is evaluated
        against (normalized to lowercase/underscores: "Disable User" ->
        "disable_user"). `resource` is the real-world object the action
        concerns -- an opaque, organization-defined identifier such as
        "account:USR-829" or "invoice:INV-4821" (Intent.resource,
        db/models.py) -- never normalized, and entirely optional.

        `resource_data["amount"]`/`["currency"]` are the platform's
        existing financial fields, recognized when present but no
        longer required -- a non-financial action (`disable_user`,
        `employee_terminate`) supplies neither. `currency` defaults to
        "USD" only when `amount` is given and `currency` isn't.
        `vendor`/`counterparty` is optional. Everything else in
        `resource_data`, plus `metadata`, is recorded as Runtime
        Authority context.

        Domain Generalization Milestone (SDK 0.4.0): `resource` used to
        hold the action name and `amount` was required even for a
        non-financial action -- both fixed here; see this module's own
        version-history comments above for the full, disclosed breaking
        change.
        """
        if self._identity is None:
            raise ConfigurationError(
                "This Agent has no registered identity yet. Call agent.register(...) once, "
                "or construct Agent(private_key=...) with a private key that was already registered."
            )
        if self._identity.status in ("retired", "revoked"):
            raise ConfigurationError(
                f"This agent is locally recorded as '{self._identity.status}' and cannot authorize "
                "actions. This is a terminal state (AGENT_LIFECYCLE.md); register a new Agent instead."
            )
        if principal != self._identity.principal_name:
            raise ConfigurationError(
                f"This agent was registered for principal '{self._identity.principal_name}', "
                f"not '{principal}'. Register a separate Agent for each principal."
            )

        action = operation.strip().lower().replace(" ", "_")
        resource_data = resource_data or {}
        amount = resource_data.get("amount")
        currency = resource_data.get("currency")
        if amount is not None and currency is None:
            currency = "USD"
        counterparty = resource_data.get("counterparty") or resource_data.get("vendor")

        context = {
            k: v for k, v in resource_data.items() if k not in ("amount", "currency", "counterparty", "vendor")
        }
        if metadata:
            context["metadata"] = metadata

        body = {
            "agent_id": self._identity.agent_id,
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
        headers = auth.signed_headers(body_bytes, self._identity.certificate_id, self._private_key)

        response = self._client.request("POST", "/v1/intents", signed_body=body_bytes, headers=headers)
        decision = response["decision"]
        return Decision(
            outcome=decision["outcome"],
            decision_id=decision["decision_id"],
            evidence_id=response.get("evidence_id"),
            reason=decision.get("reason"),
            explanation=decision.get("reason"),
            status=response["status"],
            evaluated_mandates=tuple(decision.get("evaluated_mandates", [])),
        )

    def get_decision(self, decision_id: str) -> Decision:
        """Fetches the current state of a decision: useful for polling
        one that came back HUMAN_REVIEW until a human resolves it.

        Milestone 10: this call previously sent no authentication at
        all, matching a corresponding gap on the server side
        (MILESTONE_10_DECISION_SECURITY_AND_CLARITY_SUMMARY.md) that has
        now been closed -- GET /v1/decisions/{id} requires a credential.
        `admin_auth=True` attaches the same credential every other
        administrative call in this class already requires
        (register/activate/rotate/retire above, bearer_token or
        api_key+organization_id), so this doesn't introduce any new
        configuration requirement for an Agent that's already doing
        any of those."""
        response = self._client.request("GET", f"/v1/decisions/{decision_id}", admin_auth=True)
        resolution = None
        if response.get("resolution"):
            resolution = Resolution(
                resolution=response["resolution"]["resolution"],
                resolved_by=response["resolution"]["resolved_by"],
                reason=response["resolution"].get("reason"),
            )
        return Decision(
            outcome=response["outcome"],
            decision_id=response["id"],
            evidence_id=None,
            reason=response.get("reason"),
            explanation=response.get("reason"),
            status=response["status"],
            evaluated_mandates=tuple(response.get("evaluated_mandates", [])),
            resolution=resolution,
        )

    # -- diagnostics ------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """A thin wrapper over GET /health, useful for a startup check
        that the configured base_url is actually reachable."""
        try:
            return self._client.request("GET", "/health")
        except ApiError:
            raise

    def version(self) -> dict[str, Any]:
        """A thin wrapper over GET /version."""
        return self._client.request("GET", "/version")
