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


@dataclass(frozen=True)
class CapabilityTokenPayload:
    """The full, security-relevant, signed assertion. Every field here
    is bound by the signature -- none of it is advisory metadata a
    verifier could safely ignore."""

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
) -> IssuedCapabilityToken:
    """Issues a token for an eligible ALLOW decision. `resource` and
    `constraints` are bound to the EXACT values actually evaluated --
    never a category or a range -- so a verifier can catch any deviation
    at execution time (Part C's own worked example: a token evaluated
    for amount=48,000/resource=invoice-123 must reject amount=49,000 or
    resource=invoice-456 outright)."""
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
) -> VerifiedCapability:
    """Signature, expiry, audience, and exact-parameter binding, in that
    order -- a signature check happens before anything else is trusted
    (including the claimed audience/resource inside the payload itself).
    Never raises for "this token happens to be for a different
    decision" as a distinct case from any other mismatch: every failure
    here is fail-closed rejection, not a spectrum of trust."""
    now = now or datetime.now(timezone.utc)
    payload, signature_b64, key_id = _decode_token(token)

    from app.domain.evidence.signing import Signature

    if not verify_payload(payload.to_dict(), Signature(algorithm="ed25519", key_id=key_id, value=signature_b64), public_key_b64):
        raise InvalidCapabilityTokenError("signature verification failed")

    expires_at = datetime.fromisoformat(payload.expires_at)
    if now > expires_at:
        raise CapabilityTokenExpiredError(payload.expires_at)

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

    return VerifiedCapability(payload=payload, token_hash=token_hash(token))
