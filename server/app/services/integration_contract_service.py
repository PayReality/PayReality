"""Trusted Integration Architecture, Phase 1 (TRUSTED_INTEGRATION_
ARCHITECTURE.md, Founder Decisions & Design Closure Addendum): the
Integration Contract kernel.

This module answers exactly one question: "has a human with governance
authority approved a deterministic mapping from one external system's
one real operation onto PayReality's canonical vocabulary?" It stores
and validates that mapping. It does not execute it.

Nothing in this module is consumed by intent_service.submit_intent, the
Decision Engine, Evidence, or the Authorization Receipt -- creating an
Integration or approving a Contract version has zero effect on any
existing runtime behavior in this milestone. Phase 2 is what will
eventually read an APPROVED IntegrationContractVersion at Intent-
construction time; until Phase 2 ships EnforcementBinding, an APPROVED
version means only "reviewed and eligible for future binding," never
"in use," "enforced," or "protecting anything."

Authority-relevant context decision (locked now, enforced in Phase 2,
per the addendum's own field-integrity correction): once Phase 2 wires
a trusted Adapter's runtime construction of a canonical Intent, ONLY
context keys explicitly present in an APPROVED version's own
`context_bindings` may be extracted from the observed operation and
allowed to influence Runtime Authority. Any other caller-provided
context may exist as non-authoritative metadata, but must never reach
a RuntimePolicy Condition as if it were trusted-mapped -- this is
exactly the guard against an Agent smuggling an untrusted value into
policy evaluation after PayReality has already claimed the mapping is
trusted. This module's schema (context_bindings as an explicit,
individually-approved map, not a blanket passthrough) is shaped so that
rule is enforceable later; nothing here enforces it yet, since no
runtime filter exists to enforce.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Integration, IntegrationContractVersion
from app.domain.compiler_v2.compiler_v2 import GENERIC_VOCABULARY


class IntegrationNotFoundError(Exception):
    pass


class ContractVersionNotFoundError(Exception):
    pass


class ContractInvalidTransitionError(Exception):
    def __init__(self, from_status: str, action: str):
        self.from_status = from_status
        self.action = action
        super().__init__(f"cannot {action} a contract version in status '{from_status}'")


class ContractValidationError(Exception):
    """A deterministic, structural problem with the mapping itself --
    never raised for anything requiring a live external system, AI
    judgment, or an existing RuntimePolicy to already exist (the
    Contract represents approved semantic meaning independently of
    whichever policies happen to exist today, per the architecture
    report's own &sect;11)."""


class ContractVersionHasActiveBindingError(Exception):
    """Trusted Integration Architecture, Phase 2: Phase 1 allowed
    explicit retirement freely because no runtime Binding existed yet
    to depend on an APPROVED version. Now that EnforcementBinding
    exists, an APPROVED version referenced by an ACTIVE Binding must not
    be retired -- the caller must retire or replace the active Binding
    first. Historical RETIRED Bindings may continue referencing RETIRED
    Contract versions forever; nothing about a Binding's own history
    is affected by this check."""


class ConcurrentVersionConflictError(Exception):
    """Raised only after every bounded retry attempt at allocating the
    next monotonic version for one (integration_id, source_operation)
    tuple has collided -- practically unreachable outside deliberately
    adversarial concurrency, mirroring the same bounded-retry discipline
    already established for deploy_policy's own version/active-slot
    race (runtime_policy_service.py, PayReality 1.0 Audit finding G02)."""


# --- Deterministic field-path / context-key syntax -------------------------
#
# A dotted, simple-identifier path -- "supplier.bank_account.iban" is
# valid, "supplier..iban" or ".iban" or "supplier.iban." are not.
# Deliberately NOT a transformation language: no functions, no
# expressions, no wildcards, no array indexing. If a real integration
# ever needs more than one-hop-per-field deterministic extraction, that
# real need is the signal to widen this deliberately later, not to
# pre-build a generic mapper now (Trusted Integration Architecture
# report, Do-Not-Build list).
_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")

# A canonical context key is a single simple identifier, never a path --
# it's the bare key a RuntimePolicy Condition would reference as
# "context.<key>"; the ".context." prefix itself is a Condition-authoring
# concern (compiler_v2.py's own _CONTEXT_FIELD_PREFIX), not part of the
# key stored here.
_CONTEXT_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

MAX_VERSION_CREATE_ATTEMPTS = 3

# The exact fields whose values determine what the mapping MEANS.
# Deliberately excludes `version` (identifies the historical row, not
# its meaning) and every lifecycle/provenance field (status, timestamps,
# approved_by, source_schema_fingerprint) -- see IntegrationContractVersion's
# own docstring in db/models.py for the full reasoning. Two separately
# versioned rows with byte-equivalent values for exactly these fields
# hash identically.
_HASHED_SEMANTIC_FIELDS = (
    "source_operation", "canonical_action", "resource_path",
    "fact_subject_path", "amount_path", "currency_path", "context_bindings",
)


def _compute_content_hash(semantic: dict[str, Any]) -> str:
    """Canonical JSON (sorted keys, no incidental whitespace) over
    exactly _HASHED_SEMANTIC_FIELDS, then SHA-256 -- the same "hash the
    canonical serialization" shape already used for compiled policy
    bundles (compiler_v2's own bundle_hash). `sort_keys=True` recurses
    into nested dicts, so `context_bindings`' own key order (a plain
    dict, insertion order otherwise significant to Python) never
    changes the resulting hash."""
    canonical = json.dumps(
        {key: semantic[key] for key in _HASHED_SEMANTIC_FIELDS},
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_semantic_fields(
    source_operation: str, canonical_action: str,
    resource_path: str | None, fact_subject_path: str | None,
    amount_path: str | None, currency_path: str | None,
    context_bindings: dict[str, Any],
) -> None:
    """Deterministic only -- never touches a live external system, an
    LLM, or an existing RuntimePolicy. Every check here is a pure
    function of the values themselves."""
    if not isinstance(source_operation, str) or not source_operation.strip():
        raise ContractValidationError("source_operation is required")
    if not isinstance(canonical_action, str) or not GENERIC_VOCABULARY.is_valid_action(canonical_action):
        raise ContractValidationError(
            f"canonical_action {canonical_action!r} is not a recognized action"
        )
    for field_name, path in (
        ("resource_path", resource_path), ("fact_subject_path", fact_subject_path),
        ("amount_path", amount_path), ("currency_path", currency_path),
    ):
        if path is not None and (not isinstance(path, str) or not _PATH_RE.match(path)):
            raise ContractValidationError(f"{field_name} is not a well-formed field path: {path!r}")
    if not isinstance(context_bindings, dict):
        raise ContractValidationError("context_bindings must be an object of {canonical_key: source_path}")
    for key, path in context_bindings.items():
        if not isinstance(key, str) or not _CONTEXT_KEY_RE.match(key):
            raise ContractValidationError(f"context_bindings key is not a valid canonical context key: {key!r}")
        if not isinstance(path, str) or not _PATH_RE.match(path):
            raise ContractValidationError(f"context_bindings[{key!r}] is not a well-formed field path: {path!r}")


# --- Integration -------------------------------------------------------------


def create_integration(
    db: Session, organization_id: uuid.UUID, external_system_label: str, created_by: str | None = None,
) -> Integration:
    if not external_system_label or not external_system_label.strip():
        raise ContractValidationError("external_system_label is required")
    integration = Integration(
        organization_id=organization_id, external_system_label=external_system_label, created_by=created_by,
    )
    db.add(integration)
    db.commit()
    db.refresh(integration)
    return integration


def get_integration(db: Session, integration_id: uuid.UUID, organization_id: uuid.UUID) -> Integration:
    integration = db.scalar(
        select(Integration).where(Integration.id == integration_id, Integration.organization_id == organization_id)
    )
    if integration is None:
        raise IntegrationNotFoundError(str(integration_id))
    return integration


def list_integrations(db: Session, organization_id: uuid.UUID) -> list[Integration]:
    return list(
        db.scalars(
            select(Integration).where(Integration.organization_id == organization_id).order_by(Integration.created_at)
        )
    )


# --- IntegrationContractVersion ----------------------------------------------


def create_contract_version(
    db: Session, integration_id: uuid.UUID, organization_id: uuid.UUID,
    source_operation: str, canonical_action: str,
    resource_path: str | None = None, fact_subject_path: str | None = None,
    amount_path: str | None = None, currency_path: str | None = None,
    context_bindings: dict[str, Any] | None = None,
    source_schema_fingerprint: str | None = None,
    created_by: str | None = None,
) -> IntegrationContractVersion:
    """Always DRAFT. Version is allocated under a bounded retry (see
    _create_contract_version_attempt below), never a naive
    read-then-insert that can surface a raw IntegrityError to the
    caller under real concurrent creation for the same
    (integration_id, source_operation) -- the same discipline already
    established for deploy_policy's own version/active-slot race
    (runtime_policy_service.py, PayReality 1.0 Audit finding G02)."""
    get_integration(db, integration_id, organization_id)  # raises IntegrationNotFoundError; enforces org ownership
    context_bindings = context_bindings or {}
    _validate_semantic_fields(
        source_operation, canonical_action, resource_path, fact_subject_path,
        amount_path, currency_path, context_bindings,
    )

    for _attempt in range(MAX_VERSION_CREATE_ATTEMPTS):
        try:
            return _create_contract_version_attempt(
                db, integration_id, organization_id, source_operation, canonical_action,
                resource_path, fact_subject_path, amount_path, currency_path,
                context_bindings, source_schema_fingerprint, created_by,
            )
        except IntegrityError:
            db.rollback()
            continue
    raise ConcurrentVersionConflictError(f"{integration_id}:{source_operation}")


def _create_contract_version_attempt(
    db: Session, integration_id: uuid.UUID, organization_id: uuid.UUID,
    source_operation: str, canonical_action: str,
    resource_path: str | None, fact_subject_path: str | None,
    amount_path: str | None, currency_path: str | None,
    context_bindings: dict[str, Any], source_schema_fingerprint: str | None,
    created_by: str | None,
) -> IntegrationContractVersion:
    next_version = (
        db.scalar(
            select(func.max(IntegrationContractVersion.version)).where(
                IntegrationContractVersion.integration_id == integration_id,
                IntegrationContractVersion.source_operation == source_operation,
            )
        )
        or 0
    ) + 1
    row = IntegrationContractVersion(
        integration_id=integration_id, organization_id=organization_id,
        source_operation=source_operation, version=next_version,
        canonical_action=canonical_action, resource_path=resource_path,
        fact_subject_path=fact_subject_path, amount_path=amount_path, currency_path=currency_path,
        context_bindings=context_bindings, source_schema_fingerprint=source_schema_fingerprint,
        status="draft", created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_contract_version(
    db: Session, version_id: uuid.UUID, organization_id: uuid.UUID,
) -> IntegrationContractVersion:
    row = db.scalar(
        select(IntegrationContractVersion).where(
            IntegrationContractVersion.id == version_id,
            IntegrationContractVersion.organization_id == organization_id,
        )
    )
    if row is None:
        raise ContractVersionNotFoundError(str(version_id))
    return row


def list_contract_versions(
    db: Session, integration_id: uuid.UUID, organization_id: uuid.UUID,
) -> list[IntegrationContractVersion]:
    get_integration(db, integration_id, organization_id)
    return list(
        db.scalars(
            select(IntegrationContractVersion)
            .where(
                IntegrationContractVersion.integration_id == integration_id,
                IntegrationContractVersion.organization_id == organization_id,
            )
            .order_by(IntegrationContractVersion.source_operation, IntegrationContractVersion.version)
        )
    )


_UNSET = object()


def edit_draft_contract_version(
    db: Session, version_id: uuid.UUID, organization_id: uuid.UUID,
    *,
    source_operation: Any = _UNSET, canonical_action: Any = _UNSET,
    resource_path: Any = _UNSET, fact_subject_path: Any = _UNSET,
    amount_path: Any = _UNSET, currency_path: Any = _UNSET,
    context_bindings: Any = _UNSET, source_schema_fingerprint: Any = _UNSET,
) -> IntegrationContractVersion:
    """DRAFT is the only mutable status. `_UNSET` (not `None`) marks
    "caller didn't supply this field" so an explicit `None` (e.g.
    clearing an optional path) is distinguishable from "leave unchanged"
    -- the same PATCH-semantics distinction FastAPI's own
    `exclude_unset` gives the router layer."""
    row = get_contract_version(db, version_id, organization_id)
    if row.status != "draft":
        raise ContractInvalidTransitionError(row.status, "edit")

    if source_operation is not _UNSET:
        row.source_operation = source_operation
    if canonical_action is not _UNSET:
        row.canonical_action = canonical_action
    if resource_path is not _UNSET:
        row.resource_path = resource_path
    if fact_subject_path is not _UNSET:
        row.fact_subject_path = fact_subject_path
    if amount_path is not _UNSET:
        row.amount_path = amount_path
    if currency_path is not _UNSET:
        row.currency_path = currency_path
    if context_bindings is not _UNSET:
        row.context_bindings = context_bindings if context_bindings is not None else {}
    if source_schema_fingerprint is not _UNSET:
        row.source_schema_fingerprint = source_schema_fingerprint

    _validate_semantic_fields(
        row.source_operation, row.canonical_action, row.resource_path, row.fact_subject_path,
        row.amount_path, row.currency_path, row.context_bindings,
    )
    db.commit()
    db.refresh(row)
    return row


def validate_contract_version(
    db: Session, version_id: uuid.UUID, organization_id: uuid.UUID,
) -> IntegrationContractVersion:
    """draft -> validated. Computes and freezes content_hash. Every
    field this milestone can check deterministically (recognized
    action, well-formed paths, well-formed context bindings) is
    re-checked here even though create/edit already validated on write
    -- validation is the one place a caller can rely on the mapping
    being re-confirmed correct, immutable, and hash-stamped."""
    row = get_contract_version(db, version_id, organization_id)
    if row.status != "draft":
        raise ContractInvalidTransitionError(row.status, "validate")

    _validate_semantic_fields(
        row.source_operation, row.canonical_action, row.resource_path, row.fact_subject_path,
        row.amount_path, row.currency_path, row.context_bindings,
    )
    row.content_hash = _compute_content_hash(
        {
            "source_operation": row.source_operation, "canonical_action": row.canonical_action,
            "resource_path": row.resource_path, "fact_subject_path": row.fact_subject_path,
            "amount_path": row.amount_path, "currency_path": row.currency_path,
            "context_bindings": row.context_bindings,
        }
    )
    row.status = "validated"
    row.validated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def approve_contract_version(
    db: Session, version_id: uuid.UUID, organization_id: uuid.UUID, approver: str,
) -> IntegrationContractVersion:
    """validated -> approved. Founder Decisions & Design Closure
    Addendum's lifecycle correction: this NEVER retires any other
    version of the same (integration_id, source_operation) -- multiple
    APPROVED versions may legitimately coexist (e.g. production still
    pinned to v1 while staging trials v2). Selecting exactly one
    APPROVED version to actually use belongs entirely to Phase 2's
    EnforcementBinding, which does not exist yet. Approval never
    deploys, never touches OPA, never touches RuntimePolicy, never
    touches any Agent -- it only records that a governance-authorized
    human reviewed and accepted this exact, already-immutable mapping."""
    row = get_contract_version(db, version_id, organization_id)
    if row.status != "validated":
        raise ContractInvalidTransitionError(row.status, "approve")

    row.status = "approved"
    row.approved_by = approver
    row.approved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def retire_contract_version(
    db: Session, version_id: uuid.UUID, organization_id: uuid.UUID,
) -> IntegrationContractVersion:
    """approved -> retired. Explicit only -- never automatic, never
    triggered by a newer version's approval (see approve_contract_
    version above). The historical record is never deleted; RETIRED is
    a terminal, permanently-queryable state, exactly like a retired
    Policy row.

    Phase 1 has no EnforcementBinding, so there is nothing yet that
    could depend on this version at runtime -- this function
    deliberately does not check for or reject a hypothetical dependent
    binding. Phase 2, which introduces EnforcementBinding, is where that
    check (or an explicit decision not to make retirement block on it)
    belongs; building a fake check against a table that doesn't exist
    yet would be pure speculation."""
    row = get_contract_version(db, version_id, organization_id)
    if row.status != "approved":
        raise ContractInvalidTransitionError(row.status, "retire")

    # Deferred import: enforcement_binding_service imports THIS module
    # (to resolve the pinned Contract version at binding-creation/
    # activation time), so a module-level import here would be circular.
    # Resolved at call time instead -- Phase 1 has no Binding concept and
    # never reaches this branch at all in practice for a Phase-1-only
    # deployment, since has_active_binding_for_contract_version always
    # returns False when the enforcement_bindings table is empty.
    from app.services import enforcement_binding_service

    if enforcement_binding_service.has_active_binding_for_contract_version(db, version_id):
        raise ContractVersionHasActiveBindingError(
            f"{version_id} is referenced by an active EnforcementBinding; retire or replace that binding first"
        )

    row.status = "retired"
    row.retired_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row
