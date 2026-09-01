"""Capability Authorization Protocol (PAYREALITY_FUTURE_VISION.md Part
C): a short-lived, signed capability binding a specific ALLOW decision
to a specific proposed execution, verified by a reference enforcement
adapter before it acts.

Pure module: no DB, no network -- reuses domain/evidence/signing.py's
canonicalize()/sign_payload()/verify_payload() unchanged, the same
Ed25519 machinery already used for Evidence and Agent Lifecycle audit
events, rather than introducing a second cryptographic primitive.

Explicitly scoped as PART OF A DEMONSTRATION PROTOCOL, not enterprise-
wide enforcement infrastructure (PAYREALITY_FUTURE_VISION.md Part C's
own verdict): a capability token is a transport and proof mechanism,
not an enforcement location on its own. It only produces real bypass
resistance when paired with a genuine enforcement point (an API
gateway, a sidecar, an orchestration step, or a direct target-system
integration) that actually refuses to execute without a valid one --
none of which this module builds or claims to build. What this module
gives is a cryptographically tight, single-resource, single-amount,
single-expiry, single-use binding between a decision and an execution
attempt, for whatever enforcement point chooses to check it.
"""

import base64
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.domain.evidence.signing import canonicalize, sign_payload, verify_payload


class InvalidCapabilityTokenError(Exception):
    """Signature invalid, malformed, or otherwise unusable. Distinct from
    the specific rejection reasons below so a caller can always fail
    closed on any of them without special-casing."""


class CapabilityTokenExpiredError(Exception):
    pass


class CapabilityAudienceMismatchError(Exception):
    pass


class CapabilityConstraintMismatchError(Exception):
    """The proposed execution's actual parameters (resource, amount, ...)
    do not match exactly what this token was issued for -- e.g. an
    amount = 48,000 token must not authorize amount = 49,000, and a
    resource = invoice-123 token must not authorize resource = invoice-456."""


class CapabilityBindingMismatchError(Exception):
    """Trusted Integration Architecture, Phase 5 (section 9): a
    capability issued under one Runtime Connection or environment does
    not verify as belonging to another. Raised only when the verifier
    actually supplies an expectation to check (a caller that does not
    know or does not care which connection/environment issued a
    capability may omit these, exactly as every Agent-direct verifier
    already does)."""


class CapabilityTenantMismatchError(Exception):
    """Phase 6.1, Part B (Tenant Scoped Verification Identity): a
    Capability signed for one organization does not verify against a
    caller authenticated for a different one. Kept as its own distinct
    exception, not folded into CapabilityBindingMismatchError, since
    tenant scope is a different KIND of boundary (who may verify
    anything at all here) from a Runtime-Connection/environment
    preference (which specific capability a PEP expects) -- section 12's
    own explicit hostile-test list treats them as separate cases, and
    this codebase's own "meaningful classification, not one ambiguous
    generic error" discipline (section 7) applies here too."""


@dataclass(frozen=True)
class CapabilityTokenPayload:
    """The full, security-relevant, signed assertion. Every field here
    is bound by the signature -- none of it is advisory metadata a
    verifier could safely ignore.

    Trusted Integration Architecture, Phase 5: the five
    trusted-integration fields below are additive and optional (None
    for every Agent-direct capability). When a capability is issued for
    an Adapter-mediated decision, they bind it to the exact Runtime
    Connection (`enforcement_binding_id`), Action Mapping version
    (`integration_contract_version_id`), and business operation
    (`external_operation_id`) that produced it -- so a capability issued
    under one Runtime Connection cannot silently verify as belonging to
    another, and so a PEP that knows which connection it enforces can
    pin its own expectation against the token's own signed claim."""

    decision_id: str
    organization_id: str
    principal: str
    action: str
    resource: str
    constraints: dict[str, Any]
    policy_version: int | None
    fact_hashes: list[str]
    issued_at: str
    expires_at: str
    nonce: str
    audience: str
    integration_identity_id: str | None = None
    enforcement_binding_id: str | None = None
    integration_contract_version_id: str | None = None
    environment: str | None = None
    external_operation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "organization_id": self.organization_id,
            "principal": self.principal,
            "action": self.action,
            "resource": self.resource,
            "constraints": self.constraints,
            "policy_version": self.policy_version,
            "fact_hashes": sorted(self.fact_hashes),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
            "audience": self.audience,
            "integration_identity_id": self.integration_identity_id,
            "enforcement_binding_id": self.enforcement_binding_id,
            "integration_contract_version_id": self.integration_contract_version_id,
            "environment": self.environment,
            "external_operation_id": self.external_operation_id,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "CapabilityTokenPayload":
        return CapabilityTokenPayload(
            decision_id=data["decision_id"],
            organization_id=data["organization_id"],
            principal=data["principal"],
            action=data["action"],
            resource=data["resource"],
            constraints=data["constraints"],
            policy_version=data.get("policy_version"),
            fact_hashes=list(data.get("fact_hashes", [])),
            issued_at=data["issued_at"],
            expires_at=data["expires_at"],
            nonce=data["nonce"],
            audience=data["audience"],
            integration_identity_id=data.get("integration_identity_id"),
            enforcement_binding_id=data.get("enforcement_binding_id"),
            integration_contract_version_id=data.get("integration_contract_version_id"),
            environment=data.get("environment"),
            external_operation_id=data.get("external_operation_id"),
        )


@dataclass(frozen=True)
class IssuedCapabilityToken:
    payload: CapabilityTokenPayload
    signature_b64: str
    key_id: str
    token: str  # base64 of the canonical payload + signature, what a caller actually holds
    token_hash: str  # sha256 of `token`, what gets persisted -- never the token itself


def _encode_token(payload: CapabilityTokenPayload, signature_b64: str, key_id: str) -> str:
    envelope = {"payload": payload.to_dict(), "signature": signature_b64, "key_id": key_id}
    return base64.b64encode(canonicalize(envelope)).decode("ascii")


def _decode_token(token: str) -> tuple[CapabilityTokenPayload, str, str]:
    import json

    try:
        envelope = json.loads(base64.b64decode(token))
        payload = CapabilityTokenPayload.from_dict(envelope["payload"])
        return payload, envelope["signature"], envelope["key_id"]
    except Exception as e:
        raise InvalidCapabilityTokenError("malformed token") from e


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_capability_token(
    *,
    decision_id: uuid.UUID,
    organization_id: uuid.UUID,
    principal: str,
    action: str,
    resource: str,
    constraints: dict[str, Any],
    policy_version: int | None,
    fact_hashes: list[str],
    audience: str,
    ttl_seconds: int,
    signing_key_b64: str,
    key_id: str,
    now: datetime | None = None,
    integration_identity_id: uuid.UUID | None = None,
    enforcement_binding_id: uuid.UUID | None = None,
    integration_contract_version_id: uuid.UUID | None = None,
    environment: str | None = None,
    external_operation_id: str | None = None,
) -> IssuedCapabilityToken:
    """Issues a token for an eligible ALLOW decision. `resource` and
    `constraints` are bound to the EXACT values actually evaluated --
    never a category or a range -- so a verifier can catch any deviation
    at execution time (Part C's own worked example: a token evaluated
    for amount=48,000/resource=invoice-123 must reject amount=49,000 or
    resource=invoice-456 outright). The five trusted-integration
    keyword arguments are None for every Agent-direct decision."""
    now = now or datetime.now(timezone.utc)
    expires_at = now.timestamp() + ttl_seconds
    payload = CapabilityTokenPayload(
        decision_id=str(decision_id),
        organization_id=str(organization_id),
        principal=principal,
        action=action,
        resource=resource,
        constraints=constraints,
        policy_version=policy_version,
        fact_hashes=fact_hashes,
        issued_at=now.isoformat(),
        expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        nonce=secrets.token_hex(16),
        audience=audience,
        integration_identity_id=str(integration_identity_id) if integration_identity_id else None,
        enforcement_binding_id=str(enforcement_binding_id) if enforcement_binding_id else None,
        integration_contract_version_id=str(integration_contract_version_id) if integration_contract_version_id else None,
        environment=environment,
        external_operation_id=external_operation_id,
    )
    signature = sign_payload(payload.to_dict(), signing_key_b64, key_id)
    token = _encode_token(payload, signature.value, key_id)
    return IssuedCapabilityToken(
        payload=payload, signature_b64=signature.value, key_id=key_id,
        token=token, token_hash=token_hash(token),
    )


@dataclass(frozen=True)
class VerifiedCapability:
    payload: CapabilityTokenPayload
    token_hash: str


def verify_capability_token(
    token: str,
    *,
    public_key_b64: str,
    expected_audience: str,
    expected_action: str,
    expected_resource: str,
    expected_constraints: dict[str, Any],
    now: datetime | None = None,
    expected_environment: str | None = None,
    expected_enforcement_binding_id: uuid.UUID | None = None,
    expected_principal: str | None = None,
    expected_organization_id: uuid.UUID | None = None,
) -> VerifiedCapability:
    """Signature, expiry, tenant, audience, exact-parameter, then
    binding, in that order -- a signature check happens before anything
    else is trusted (including the claimed audience/resource inside the
    payload itself). Never raises for "this token happens to be for a
    different decision" as a distinct case from any other mismatch:
    every failure here is fail-closed rejection, not a spectrum of
    trust.

    `expected_principal`/`expected_environment`/`expected_enforcement_
    binding_id`/`expected_organization_id` (sections 6/9, and Phase 6.1
    section 10) are optional: a caller that does not supply one skips
    that specific check, exactly the same backward-compatible shape
    every other optional binding in this codebase uses. A caller that
    DOES supply one is checked against the token's own signed claim,
    never against live database state -- the token's claim is what was
    actually true at issuance, and that is what a PEP is verifying.
    `principal` was already part of the signed payload before Phase
    5.1 (populated from the Decision's own Evidence); this adds the
    ability to actually check it, closing a real gap a hostile review
    of that milestone's own new bindings found: a PEP had no way to
    assert "this capability must belong to this specific Agent" as
    something distinct from whatever the resource/action/constraints
    happen to imply.

    `expected_organization_id` (Phase 6.1, Part B): checked before
    audience, deliberately -- a caller authenticated for the wrong
    tenant should learn nothing else about a token it has no business
    inspecting, not even whether the audience it guessed happens to
    match. The real, production-facing verification endpoint
    (routers/capability_tokens.py) always supplies this now (it always
    has a real, authenticated organization to check against); it stays
    optional here purely so this function itself, and any other
    internal caller with no organization context of its own, is
    unaffected."""
    now = now or datetime.now(timezone.utc)
    payload, signature_b64, key_id = _decode_token(token)

    from app.domain.evidence.signing import Signature

    if not verify_payload(payload.to_dict(), Signature(algorithm="ed25519", key_id=key_id, value=signature_b64), public_key_b64):
        raise InvalidCapabilityTokenError("signature verification failed")

    expires_at = datetime.fromisoformat(payload.expires_at)
    if now > expires_at:
        raise CapabilityTokenExpiredError(payload.expires_at)

    if expected_organization_id is not None and payload.organization_id != str(expected_organization_id):
        raise CapabilityTenantMismatchError(
            f"token organization_id={payload.organization_id!r} expected={str(expected_organization_id)!r}"
        )

    if payload.audience != expected_audience:
        raise CapabilityAudienceMismatchError(f"token audience={payload.audience!r} expected={expected_audience!r}")

    if payload.action != expected_action:
        raise CapabilityConstraintMismatchError(f"action mismatch: token={payload.action!r} execution={expected_action!r}")

    if payload.resource != expected_resource:
        raise CapabilityConstraintMismatchError(f"resource mismatch: token={payload.resource!r} execution={expected_resource!r}")

    if payload.constraints != expected_constraints:
        raise CapabilityConstraintMismatchError(
            f"constraints mismatch: token={payload.constraints!r} execution={expected_constraints!r}"
        )

    if expected_principal is not None and payload.principal != expected_principal:
        raise CapabilityConstraintMismatchError(
            f"principal mismatch: token={payload.principal!r} expected={expected_principal!r}"
        )

    if expected_environment is not None and payload.environment != expected_environment:
        raise CapabilityBindingMismatchError(
            f"environment mismatch: token={payload.environment!r} expected={expected_environment!r}"
        )

    if expected_enforcement_binding_id is not None and payload.enforcement_binding_id != str(expected_enforcement_binding_id):
        raise CapabilityBindingMismatchError(
            f"enforcement_binding mismatch: token={payload.enforcement_binding_id!r} "
            f"expected={str(expected_enforcement_binding_id)!r}"
        )

    return VerifiedCapability(payload=payload, token_hash=token_hash(token))
