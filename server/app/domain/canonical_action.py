"""Post-audit implementation, Priority 3: the canonical-action contract
between a trusted Adapter and PayReality, formalized as an explicit,
versioned, named structure.

Deliberately NOT a generic external-payload canonicalizer: this repository
already confirmed (Priority-3 audit) that PayReality never parses a raw
adapter payload itself -- the caller (the Adapter, or the SDK's
HttpApiAdapterTemplate on the caller's own infrastructure) already supplies
pre-canonicalized action/resource/amount/currency values, and
IntegrationContractVersion's *_path columns are used only for a
structural presence/absence check (integration_runtime_service.
_check_structural_field), never real field extraction. This module does
not change that boundary. What it adds is a single, explicit, hashable
representation of "the canonical action PayReality actually evaluated",
so a future Capability, execution receipt, or reconciliation record has
one stable thing to bind against, rather than re-deriving it ad hoc from
whichever individual columns happen to be convenient at the time.

Deliberately does NOT touch operation_identity_service.
compute_canonical_operation_fingerprint's own hashed field set: that
function's fingerprint is already persisted on real Intent rows
(Intent.canonical_operation_fingerprint) and answers a narrower, different
question ("is this a resubmission of the same real-world operation",
scoped to exactly the fields section 6 of PHASE_3 already named, excluding
external_operation_id/organization_id/environment because those are
already the DB-level idempotency scope). This module's own digest answers
a broader question -- "what is the complete, unique, addressable identity
of this specific authorized action" -- and is additive: changing it can
never invalidate an already-persisted canonical_operation_fingerprint or
break a real Adapter's legitimate idempotent retry.

Trust statement, unchanged (do not overclaim beyond this): PayReality
verifies that an authenticated trusted adapter submitted a canonical
action under an approved contract. This does not prove the adapter's own
code is bug-free, that it observes every execution path, or that the
downstream action ever executed.
"""

from __future__ import annotations

import decimal
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

CANONICAL_ACTION_SCHEMA_VERSION = 1
_SUPPORTED_SCHEMA_VERSIONS = frozenset({1})


class UnsupportedCanonicalActionSchemaVersionError(Exception):
    """Fail closed on a version this build doesn't know how to interpret,
    rather than silently evaluating it under today's rules and getting the
    wrong answer for a schema that hasn't been written yet."""

    def __init__(self, schema_version: Any):
        self.schema_version = schema_version
        super().__init__(f"unsupported canonical action schema_version={schema_version!r}")


class MissingRequiredCanonicalActionFieldError(Exception):
    """One of the fields the contract requires for every canonical action
    (organization_id, agent_id, action, integration_identity_id,
    integration_contract_version_id, contract_content_hash, environment,
    external_operation_id) was not supplied."""

    def __init__(self, field_name: str):
        self.field_name = field_name
        super().__init__(f"missing required canonical action field: {field_name}")


def _normalize_amount(amount: float | None) -> str | None:
    """Mirrors operation_identity_service._normalize_amount's own
    Decimal-quantize approach exactly (never a float-rounding
    normalization, which would reintroduce the binary-imprecision this
    exists to avoid): 100.1, 100.10, and 100.099999999999 (a plausible
    float artifact) all normalize identically. Kept as its own small,
    tolerated duplication rather than a cross-module import of that
    function's own private helper -- the same "small duplication is fine,
    a shared cross-cutting dependency is not" precedent this codebase
    already applies elsewhere (e.g. _resolve_chain_scope)."""
    if amount is None:
        return None
    return str(decimal.Decimal(str(amount)).quantize(decimal.Decimal("0.01"), rounding=decimal.ROUND_HALF_UP))


_REQUIRED_FIELDS = (
    "organization_id", "agent_id", "action", "integration_identity_id",
    "integration_contract_version_id", "contract_content_hash", "environment",
    "external_operation_id",
)


@dataclass(frozen=True)
class CanonicalAction:
    """The canonical action contract, v1. Every field the Adapter-mediated
    runtime path (integration_runtime_service.submit_attested_intent) has
    already independently validated by the time this is constructed --
    this dataclass names and binds them together, it does not re-validate
    trust decisions already made (schema version and required-field
    presence are the only checks this module itself performs; see
    build_canonical_action).

    Material fields (participate in canonical_digest(), material_fields()):
    schema_version, organization_id, agent_id, principal, action, resource,
    amount, currency, integration_identity_id, integration_contract_version_id,
    contract_content_hash, environment, external_operation_id -- exactly
    the fields that change WHAT was authorized.

    Non-material fields (recorded, never hashed): observed_at (when, not
    what), source_request_digest and declared_task_reference (optional,
    purely informational passthrough -- present so a future declared-vs-
    observed correlation model has somewhere to record a reference without
    this milestone building any comparison logic against it; see
    DECLARED_VS_OBSERVED_RECONCILIATION.md)."""

    schema_version: int
    organization_id: uuid.UUID
    agent_id: uuid.UUID
    action: str
    integration_identity_id: uuid.UUID
    integration_contract_version_id: uuid.UUID
    contract_content_hash: str
    environment: str
    external_operation_id: str
    observed_at: datetime
    principal: str | None = None
    resource: str | None = None
    amount: float | None = None
    currency: str | None = None
    source_request_digest: str | None = None
    declared_task_reference: str | None = None

    def material_fields(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "organization_id": str(self.organization_id),
            "agent_id": str(self.agent_id),
            "principal": self.principal,
            "action": self.action,
            "resource": self.resource,
            "amount": _normalize_amount(self.amount),
            "currency": self.currency,
            "integration_identity_id": str(self.integration_identity_id),
            "integration_contract_version_id": str(self.integration_contract_version_id),
            "contract_content_hash": self.contract_content_hash,
            "environment": self.environment,
            "external_operation_id": self.external_operation_id,
        }

    def canonical_digest(self) -> str:
        """Deterministic canonical JSON (sorted keys, no whitespace,
        matching operation_identity_service.compute_canonical_operation_
        fingerprint's own established shape), then SHA-256. Two
        CanonicalAction instances with identical material fields always
        produce identical digests, regardless of construction order or
        which non-material fields (observed_at, source_request_digest,
        declared_task_reference) differ between them."""
        canonical = json.dumps(self.material_fields(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_canonical_action(
    *,
    organization_id: uuid.UUID,
    agent_id: uuid.UUID,
    action: str,
    integration_identity_id: uuid.UUID,
    integration_contract_version_id: uuid.UUID,
    contract_content_hash: str,
    environment: str,
    external_operation_id: str,
    observed_at: datetime,
    schema_version: int = CANONICAL_ACTION_SCHEMA_VERSION,
    principal: str | None = None,
    resource: str | None = None,
    amount: float | None = None,
    currency: str | None = None,
    source_request_digest: str | None = None,
    declared_task_reference: str | None = None,
) -> CanonicalAction:
    """The one constructor this module exposes -- fails closed on an
    unsupported schema_version or a missing required field, rather than
    silently building a CanonicalAction whose digest can never be
    meaningfully compared against anything."""
    if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedCanonicalActionSchemaVersionError(schema_version)

    required = {
        "organization_id": organization_id, "agent_id": agent_id, "action": action,
        "integration_identity_id": integration_identity_id,
        "integration_contract_version_id": integration_contract_version_id,
        "contract_content_hash": contract_content_hash, "environment": environment,
        "external_operation_id": external_operation_id,
    }
    for name, value in required.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            raise MissingRequiredCanonicalActionFieldError(name)

    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)

    return CanonicalAction(
        schema_version=schema_version,
        organization_id=organization_id,
        agent_id=agent_id,
        principal=principal,
        action=action,
        resource=resource,
        amount=amount,
        currency=currency,
        integration_identity_id=integration_identity_id,
        integration_contract_version_id=integration_contract_version_id,
        contract_content_hash=contract_content_hash,
        environment=environment,
        external_operation_id=external_operation_id,
        observed_at=observed_at,
        source_request_digest=source_request_digest,
        declared_task_reference=declared_task_reference,
    )
