"""Trusted Integration Architecture, Phase 2: the trusted-Adapter
runtime path. Additive alongside intent_service.submit_intent (the
Agent-direct path, completely unchanged) -- this is where an approved
Integration Contract, mediated through an authenticated
IntegrationIdentity and an active EnforcementBinding, actually
participates in a real Runtime Authority request for the first time.

Trust claim, stated precisely (do not overclaim beyond this): an
authenticated IntegrationIdentity attests that it observed the external
operation and constructed the canonical Intent using an approved
Integration Contract. This does not mathematically prove the Adapter's
own code is bug-free, that it sits on every possible execution path, or
that the external operation ever executed. PayReality remains a PDP.

Every pre-evaluation trust failure below (section 25) raises
IntegrationRejectionError or AdapterReplayDetectedError -- never DENY,
never a Decision row, never Evidence claiming an evaluation that never
happened. Once those checks pass, evaluation and Evidence are produced
by the exact same shared core (intent_service._evaluate_and_record)
Agent-direct Intents already use -- there is no second decision engine,
no duplicated evaluation logic, anywhere in this module.
"""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Agent, Decision, Evidence, Intent, IntegrationContractVersion, IntegrationIdentity, Principal
from app.domain.decision.source import normalize_source
from app.services import enforcement_binding_service, intent_service, operation_identity_service

logger = logging.getLogger("payreality.integration_runtime")


class IntegrationRejectionError(Exception):
    """A pre-evaluation trust failure on the Adapter-mediated runtime
    path -- the request is untrustworthy before Runtime Authority is
    ever reached. Never DENY, never a Decision, never Evidence."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class AdapterReplayDetectedError(Exception):
    """The (integration_identity_id, nonce) pair has already been used
    -- a DB-enforced invariant (idx_intents_integration_identity_nonce)
    entirely separate from, and never weakening, Agent-direct's own
    (agent_id, nonce) replay protection. Means only "do not accept the
    same authenticated request again" -- this is authentication-level
    replay protection, not business-operation idempotency (that is
    ExternalOperationConflictError / the idempotent-return path below,
    Phase 3)."""


class ExternalOperationConflictError(Exception):
    """Trusted Integration Architecture, Phase 3 (section 27): this
    external_operation_id has already been accepted, scoped to this
    (integration, environment), with a DIFFERENT authority-relevant
    canonical meaning than the current request. A pre-evaluation
    integration conflict -- never evaluated, never a new Decision, never
    Evidence claiming an evaluation that never happened. Deliberately
    does not carry the mismatched canonical values themselves (section
    27: do not disclose sensitive canonical values unnecessarily)."""

    def __init__(self, external_operation_id: str):
        self.external_operation_id = external_operation_id
        super().__init__(
            f"external_operation_id {external_operation_id!r} already recorded with different "
            "authority-relevant semantics for this integration/environment"
        )


_ELIGIBLE_ORIGIN_AGENT_STATUSES = ("active",)

# The one context key server-resolved trust injects -- reserved so a
# caller can never smuggle its own value in under the same name.
_RESERVED_CONTEXT_KEYS = frozenset({"environment"})


def _check_structural_field(field_name: str, contract_path: str | None, value: Any) -> None:
    """Section 21: PayReality cannot independently reconstruct the
    original external payload, so it cannot cryptographically prove an
    extracted value corresponds to the real source -- but it CAN and
    must enforce structural consistency between what the Contract
    declares extractable and what the Adapter actually attested."""
    if contract_path is None and value is not None:
        raise IntegrationRejectionError(f"unexpected_{field_name}_not_declared_by_contract")
    if contract_path is not None and value is None:
        raise IntegrationRejectionError(f"missing_required_{field_name}_declared_by_contract")


def _resolve_active_binding(db: Session, binding_id: uuid.UUID, organization_id: uuid.UUID, identity_id: uuid.UUID):
    try:
        binding = enforcement_binding_service.get_binding(db, binding_id, organization_id)
    except enforcement_binding_service.EnforcementBindingNotFoundError:
        raise IntegrationRejectionError("enforcement_binding_not_found")
    # A binding that exists but belongs to a different Integration
    # Identity looks exactly like "not found" to this caller -- the
    # same cross-tenant-looks-like-not-found convention this codebase
    # already applies to organizations, never revealing that a
    # different identity's binding exists.
    if binding.integration_identity_id != identity_id:
        raise IntegrationRejectionError("enforcement_binding_not_found")
    if binding.status != "active":
        raise IntegrationRejectionError(f"enforcement_binding_not_active:{binding.status}")
    return binding


def _resolve_origin_agent(db: Session, agent_id: uuid.UUID, organization_id: uuid.UUID, binding_id: uuid.UUID) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise IntegrationRejectionError("origin_agent_not_found")
    principal = db.get(Principal, agent.acting_for_principal_id)
    if principal is None or principal.organization_id != organization_id:
        raise IntegrationRejectionError("origin_agent_not_found")
    if agent.status not in _ELIGIBLE_ORIGIN_AGENT_STATUSES:
        raise IntegrationRejectionError(f"origin_agent_not_eligible:{agent.status}")
    if not enforcement_binding_service.is_agent_allowed(db, binding_id, agent_id):
        raise IntegrationRejectionError("origin_agent_not_allowed_for_binding")
    return agent


def _load_operation_result(db: Session, existing_intent: Intent) -> tuple[Intent, Decision, Evidence]:
    """Reconstructs the (Intent, Decision, Evidence) triple for an
    idempotent return -- never re-evaluated, never re-resolved. One
    Decision per Intent throughout this codebase (Decision.intent_id),
    so a single scalar lookup is correct, not merely convenient."""
    decision = db.scalar(select(Decision).where(Decision.intent_id == existing_intent.id))
    evidence = intent_service.get_earliest_evidence_for_decision(db, decision.id)
    return existing_intent, decision, evidence


def _resolve_existing_or_conflict(
    db: Session, existing: Intent, fingerprint: str, external_operation_id: str,
) -> tuple[Intent, Decision, Evidence]:
    if existing.canonical_operation_fingerprint == fingerprint:
        logger.info(
            "operation_identity_result=IDEMPOTENT_RETURN integration_id=%s environment=%s external_operation_id=%s",
            existing.integration_id, existing.environment, external_operation_id,
        )
        return _load_operation_result(db, existing)
    logger.warning(
        "operation_identity_result=CONFLICT integration_id=%s environment=%s external_operation_id=%s",
        existing.integration_id, existing.environment, external_operation_id,
    )
    raise ExternalOperationConflictError(external_operation_id)


def submit_attested_intent(
    db: Session,
    identity: IntegrationIdentity,
    *,
    enforcement_binding_id: uuid.UUID,
    origin_agent_id: uuid.UUID,
    source_operation: str,
    action: str,
    resource: str | None,
    amount: float | None,
    currency: str | None,
    counterparty: str | None,
    context: dict,
    requested_at: datetime,
    nonce: str,
    correlation_id: str | None,
    external_operation_id: str,
) -> tuple[Intent, "Decision", "Evidence"]:  # noqa: F821 -- forward refs, real types imported in intent_service
    # Section 29: format validation is stateless and independent of
    # trust -- checked first, before any DB lookup, so a malformed id
    # fails the same way regardless of which identity/binding sent it.
    # Folded into the same IntegrationRejectionError taxonomy as every
    # other pre-evaluation failure in this module (section 15's own
    # list) rather than a separate exception type the router would need
    # to know about.
    try:
        operation_identity_service.validate_external_operation_id(external_operation_id)
    except operation_identity_service.InvalidExternalOperationIdError as e:
        raise IntegrationRejectionError(f"invalid_external_operation_id:{e}")

    if identity.status != "active":
        # Defense in depth, matching AgentNotOperationalError's own
        # precedent: verify_integration_identity_signature already
        # blocks a revoked/retired identity (its certificate is no
        # longer 'active'), but a *suspended* identity's certificate is
        # untouched by suspension (mirroring Agent's own suspend_agent)
        # -- this is the one status this check actually needs to catch
        # in real traffic.
        raise IntegrationRejectionError(f"integration_identity_not_active:{identity.status}")

    organization_id = identity.organization_id
    binding = _resolve_active_binding(db, enforcement_binding_id, organization_id, identity.id)
    agent = _resolve_origin_agent(db, origin_agent_id, organization_id, binding.id)

    contract_version = db.get(IntegrationContractVersion, binding.integration_contract_version_id)
    if contract_version is None or contract_version.organization_id != organization_id:
        raise IntegrationRejectionError("contract_version_not_found")

    # Section 19/20: no dynamic lookup, no fallback, no HUMAN_REVIEW for
    # ambiguity -- a mismatch here means the request itself is
    # untrustworthy, full stop.
    if source_operation != contract_version.source_operation:
        raise IntegrationRejectionError("source_operation_mismatch")
    if action != contract_version.canonical_action:
        raise IntegrationRejectionError("canonical_action_mismatch")

    _check_structural_field("resource", contract_version.resource_path, resource)
    _check_structural_field("amount", contract_version.amount_path, amount)
    _check_structural_field("currency", contract_version.currency_path, currency)
    _check_structural_field("fact_subject", contract_version.fact_subject_path, counterparty)

    # Section 22: trusted context filtering -- the mandatory rule. Only
    # keys explicitly bound by the approved Contract may reach Runtime
    # Authority; "environment" is reserved for the server's own
    # trusted, Binding-resolved value, never caller-suppliable.
    reserved_collision = _RESERVED_CONTEXT_KEYS & set(context.keys())
    if reserved_collision:
        raise IntegrationRejectionError(f"reserved_context_key_supplied:{sorted(reserved_collision)}")
    bound_keys = set(contract_version.context_bindings.keys())
    supplied_keys = set(context.keys())
    unexpected_keys = supplied_keys - bound_keys
    if unexpected_keys:
        raise IntegrationRejectionError(f"unexpected_context_keys:{sorted(unexpected_keys)}")
    missing_keys = bound_keys - supplied_keys
    if missing_keys:
        raise IntegrationRejectionError(f"missing_required_context_keys:{sorted(missing_keys)}")

    # Section 10: the caller cannot choose or override environment --
    # it is copied from the server-resolved, active Binding, and (per
    # the reserved-key check above) the caller never supplied one of
    # its own to conflict with it in the first place.
    final_context = {**context, "environment": binding.environment}

    # Trusted Integration Architecture, Phase 3: the idempotency check
    # itself. Placed here, deliberately -- after every integration-trust
    # check above has already succeeded (section 15: a request that
    # fails validation never reaches this point, so it can never poison
    # external_operation_id), and strictly before Runtime Truth/Trusted
    # Enterprise Fact resolution or policy evaluation, both of which
    # only happen inside intent_service._evaluate_and_record below
    # (sections 36/37: a matching retry must re-resolve neither).
    fingerprint = operation_identity_service.compute_canonical_operation_fingerprint(
        origin_agent_id=agent.id,
        contract_content_hash=contract_version.content_hash,
        source_operation=source_operation,
        canonical_action=action,
        resource=resource,
        amount=amount,
        currency=currency,
        fact_subject=counterparty,
        trusted_context=context,
    )

    # Fast path: the overwhelmingly common case (a real retry) never
    # needs to construct an Intent or attempt an insert at all. Read-
    # only, so it is not by itself the concurrency guarantee -- that is
    # the real, DB-enforced partial unique index below, re-checked the
    # same way after a racing IntegrityError.
    existing = operation_identity_service.find_existing_operation(
        db, contract_version.integration_id, binding.environment, external_operation_id,
    )
    if existing is not None:
        return _resolve_existing_or_conflict(db, existing, fingerprint, external_operation_id)

    intent = Intent(
        agent_id=agent.id,
        correlation_id=correlation_id,
        action=action,
        amount=amount,
        currency=currency,
        counterparty=counterparty,
        resource=resource,
        source=normalize_source(None),
        context=final_context,
        nonce=nonce,
        requested_at=requested_at,
        integration_identity_id=identity.id,
        enforcement_binding_id=binding.id,
        integration_contract_version_id=contract_version.id,
        external_operation_id=external_operation_id,
        integration_id=contract_version.integration_id,
        canonical_operation_fingerprint=fingerprint,
        environment=binding.environment,
    )
    db.add(intent)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        # Section 18/19: a genuinely concurrent racer may have committed
        # the same (integration, environment, external_operation_id)
        # scope between our fast-path read above and this flush -- or
        # this may be an ordinary Adapter-nonce replay (section 24,
        # unrelated to operation identity). Disambiguated by re-querying
        # for the specific row the operation-scope index would have
        # produced: if it now exists, this was an operation-scope race,
        # resolved exactly like the fast path above (return the winner's
        # Decision on a matching fingerprint, conflict on a mismatched
        # one); if it still does not exist, the collision could only
        # have been the (integration_identity_id, nonce) index, so this
        # is a real replay.
        existing = operation_identity_service.find_existing_operation(
            db, contract_version.integration_id, binding.environment, external_operation_id,
        )
        if existing is not None:
            return _resolve_existing_or_conflict(db, existing, fingerprint, external_operation_id)
        raise AdapterReplayDetectedError(f"{identity.id}:{nonce}") from e

    decision, evidence = intent_service._evaluate_and_record(
        db, intent, agent, action, amount, currency, counterparty, resource, final_context, requested_at,
        integration_provenance={
            "integration_identity_id": str(identity.id),
            "enforcement_binding_id": str(binding.id),
            "integration_contract_version_id": str(contract_version.id),
            "integration_contract_content_hash": contract_version.content_hash,
            "environment": binding.environment,
            "source_operation": source_operation,
            "external_operation_id": external_operation_id,
            "canonical_operation_fingerprint": fingerprint,
        },
    )
    logger.info(
        "operation_identity_result=NEW integration_id=%s environment=%s external_operation_id=%s",
        contract_version.integration_id, binding.environment, external_operation_id,
    )
    return intent, decision, evidence
