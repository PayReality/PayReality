"""Trusted Integration Architecture, Phase 2: EnforcementBinding is the
runtime-deployment object -- "this Adapter, in this environment, is
approved to use this exact Integration Contract version for these
explicitly allowed Agents." Contract approval (Phase 1) is deployment-
neutral; activating a Binding here is the actual deployment moment.

Despite the name, none of this makes PayReality a PEP. Every function
below only ever governs what PayReality's own Runtime Authority
evaluation is willing to accept as trusted input -- it never reaches
out to, enforces against, or observes any external system.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Agent, EnforcementBinding, EnforcementBindingAgent, IntegrationContractVersion
from app.services import integration_contract_service, integration_identity_service


class EnforcementBindingNotFoundError(Exception):
    pass


class BindingInvalidTransitionError(Exception):
    def __init__(self, from_status: str, action: str):
        self.from_status = from_status
        self.action = action
        super().__init__(f"cannot {action} a binding in status '{from_status}'")


class BindingValidationError(Exception):
    """A deterministic activation-prerequisite failure (section 12) --
    identity not active, contract not approved, an allowed agent not
    eligible, empty allow-list, cross-organization reference, etc."""


class ConcurrentActivationConflictError(Exception):
    """Raised only after every bounded retry attempt at atomically
    retiring the prior ACTIVE binding for a scope and activating this
    one has collided -- the same bounded-retry discipline already
    established for deploy_policy (G02) and Contract-version creation
    (Phase 1)."""


MAX_ACTIVATION_ATTEMPTS = 3

_ELIGIBLE_AGENT_STATUSES = ("active",)


def _resolve_contract_version(db: Session, contract_version_id: uuid.UUID, organization_id: uuid.UUID):
    return integration_contract_service.get_contract_version(db, contract_version_id, organization_id)


def create_draft_binding(
    db: Session, organization_id: uuid.UUID, integration_identity_id: uuid.UUID,
    integration_contract_version_id: uuid.UUID, environment: str,
    agent_ids: list[uuid.UUID] | None = None, created_by: str | None = None,
) -> EnforcementBinding:
    """DRAFT. Only organization-ownership is validated here (identity,
    contract version, and every named agent must belong to this same
    organization) -- APPROVED/active/eligibility checks are all
    activation-time concerns (section 12), deliberately not required
    to even begin drafting a binding, since a Contract may still be
    mid-review when a binding is first sketched out."""
    if not environment or not environment.strip():
        raise BindingValidationError("environment is required")

    # Raises IntegrationIdentityNotFoundError / ContractVersionNotFoundError
    # (both org-scoped lookups) if either belongs to a different
    # organization or doesn't exist -- the same "cross-org looks like
    # not-found" convention this codebase already uses everywhere else.
    integration_identity_service.get_integration_identity(db, integration_identity_id, organization_id)
    contract_version = _resolve_contract_version(db, integration_contract_version_id, organization_id)

    binding = EnforcementBinding(
        organization_id=organization_id,
        integration_identity_id=integration_identity_id,
        integration_contract_version_id=integration_contract_version_id,
        integration_id=contract_version.integration_id,
        source_operation=contract_version.source_operation,
        environment=environment,
        status="draft",
        created_by=created_by,
    )
    db.add(binding)
    db.flush()

    for agent_id in agent_ids or []:
        _add_allowed_agent_row(db, binding, agent_id, organization_id)

    db.commit()
    db.refresh(binding)
    return binding


def get_binding(db: Session, binding_id: uuid.UUID, organization_id: uuid.UUID) -> EnforcementBinding:
    binding = db.scalar(
        select(EnforcementBinding).where(
            EnforcementBinding.id == binding_id, EnforcementBinding.organization_id == organization_id,
        )
    )
    if binding is None:
        raise EnforcementBindingNotFoundError(str(binding_id))
    return binding


def list_bindings(db: Session, organization_id: uuid.UUID) -> list[EnforcementBinding]:
    return list(
        db.scalars(
            select(EnforcementBinding)
            .where(EnforcementBinding.organization_id == organization_id)
            .order_by(EnforcementBinding.created_at)
        )
    )


_UNSET = object()


def edit_draft_binding(
    db: Session, binding_id: uuid.UUID, organization_id: uuid.UUID,
    *, integration_identity_id: Any = _UNSET, integration_contract_version_id: Any = _UNSET,
    environment: Any = _UNSET,
) -> EnforcementBinding:
    binding = get_binding(db, binding_id, organization_id)
    if binding.status != "draft":
        raise BindingInvalidTransitionError(binding.status, "edit")

    if integration_identity_id is not _UNSET:
        integration_identity_service.get_integration_identity(db, integration_identity_id, organization_id)
        binding.integration_identity_id = integration_identity_id
    if integration_contract_version_id is not _UNSET:
        contract_version = _resolve_contract_version(db, integration_contract_version_id, organization_id)
        binding.integration_contract_version_id = integration_contract_version_id
        binding.integration_id = contract_version.integration_id
        binding.source_operation = contract_version.source_operation
    if environment is not _UNSET:
        if not environment or not str(environment).strip():
            raise BindingValidationError("environment is required")
        binding.environment = environment

    db.commit()
    db.refresh(binding)
    return binding


_VALID_ENFORCEMENT_ASSURANCE_LEVELS = ("ADVISORY", "CAPABILITY_REQUIRED")


class InvalidEnforcementAssuranceError(Exception):
    pass


def set_enforcement_assurance(
    db: Session, binding_id: uuid.UUID, organization_id: uuid.UUID, enforcement_assurance: str,
) -> EnforcementBinding:
    """Trusted Integration Architecture, Phase 5 (sections 30/31): a
    customer-declared, never independently verified, label of what this
    Binding's own downstream checkpoint claims to require. Deliberately
    NOT restricted to `draft` status like edit_draft_binding's own
    authority-relevant fields above -- this label carries no authority
    meaning at all (Runtime Authority's own evaluation never reads it),
    so changing it on an already-ACTIVE binding changes nothing about
    what that binding actually does, only what it declares about its
    own downstream checkpoint. Only ADVISORY and CAPABILITY_REQUIRED are
    accepted: DECLARED_DECISION_CHECK, VERIFIED, and
    REGISTERED_EXTERNAL_PEP have no real implementation behind them in
    this phase and must never be settable (section 32)."""
    if enforcement_assurance not in _VALID_ENFORCEMENT_ASSURANCE_LEVELS:
        raise InvalidEnforcementAssuranceError(
            f"enforcement_assurance must be one of {_VALID_ENFORCEMENT_ASSURANCE_LEVELS}, got {enforcement_assurance!r}"
        )
    binding = get_binding(db, binding_id, organization_id)
    binding.enforcement_assurance = enforcement_assurance
    db.commit()
    db.refresh(binding)
    return binding


def _add_allowed_agent_row(db: Session, binding: EnforcementBinding, agent_id: uuid.UUID, organization_id: uuid.UUID) -> None:
    from app.db.models import Principal  # local import: avoids a module-level cycle with agent-facing services

    agent = db.get(Agent, agent_id)
    if agent is None:
        raise BindingValidationError(f"agent {agent_id} not found")
    principal = db.get(Principal, agent.acting_for_principal_id)
    if principal is None or principal.organization_id != organization_id:
        raise BindingValidationError(f"agent {agent_id} does not belong to this organization")
    existing = db.scalar(
        select(EnforcementBindingAgent).where(
            EnforcementBindingAgent.enforcement_binding_id == binding.id,
            EnforcementBindingAgent.agent_id == agent_id,
        )
    )
    if existing is None:
        db.add(EnforcementBindingAgent(enforcement_binding_id=binding.id, agent_id=agent_id))


def add_allowed_agent(
    db: Session, binding_id: uuid.UUID, organization_id: uuid.UUID, agent_id: uuid.UUID,
) -> EnforcementBinding:
    binding = get_binding(db, binding_id, organization_id)
    if binding.status != "draft":
        raise BindingInvalidTransitionError(binding.status, "edit allowed agents on")
    _add_allowed_agent_row(db, binding, agent_id, organization_id)
    db.commit()
    db.refresh(binding)
    return binding


def remove_allowed_agent(
    db: Session, binding_id: uuid.UUID, organization_id: uuid.UUID, agent_id: uuid.UUID,
) -> EnforcementBinding:
    binding = get_binding(db, binding_id, organization_id)
    if binding.status != "draft":
        raise BindingInvalidTransitionError(binding.status, "edit allowed agents on")
    row = db.scalar(
        select(EnforcementBindingAgent).where(
            EnforcementBindingAgent.enforcement_binding_id == binding_id,
            EnforcementBindingAgent.agent_id == agent_id,
        )
    )
    if row is not None:
        db.delete(row)
    db.commit()
    db.refresh(binding)
    return binding


def list_allowed_agents(db: Session, binding_id: uuid.UUID, organization_id: uuid.UUID) -> list[Agent]:
    get_binding(db, binding_id, organization_id)  # org-ownership check
    return list(
        db.scalars(
            select(Agent)
            .join(EnforcementBindingAgent, EnforcementBindingAgent.agent_id == Agent.id)
            .where(EnforcementBindingAgent.enforcement_binding_id == binding_id)
        )
    )


def is_agent_allowed(db: Session, binding_id: uuid.UUID, agent_id: uuid.UUID) -> bool:
    """The actual runtime membership check (section 7) -- a plain,
    fast existence query against the join table, no organization
    re-check needed here since the caller (integration_runtime_service)
    has already resolved both the binding and the agent within the
    same organization by this point."""
    return (
        db.scalar(
            select(EnforcementBindingAgent.id).where(
                EnforcementBindingAgent.enforcement_binding_id == binding_id,
                EnforcementBindingAgent.agent_id == agent_id,
            )
        )
        is not None
    )


def activate_binding(db: Session, binding_id: uuid.UUID, organization_id: uuid.UUID) -> EnforcementBinding:
    """draft -> active. Full section-12 activation prerequisites, then
    an atomic, concurrency-safe transaction that retires whichever
    Binding was previously ACTIVE for this exact (integration_identity_id,
    integration_id, source_operation, environment) scope and activates
    this one -- the one place in the whole Trusted Integration
    Architecture where "exactly one current meaning" is a real runtime
    invariant, enforced by a real partial-unique DB index
    (idx_enforcement_bindings_single_active_per_scope) plus a bounded
    retry on the racing IntegrityError, mirroring deploy_policy's own
    established pattern for the identical class of problem."""
    for _attempt in range(MAX_ACTIVATION_ATTEMPTS):
        try:
            return _activate_binding_attempt(db, binding_id, organization_id)
        except IntegrityError:
            db.rollback()
            continue
    raise ConcurrentActivationConflictError(str(binding_id))


def _activate_binding_attempt(db: Session, binding_id: uuid.UUID, organization_id: uuid.UUID) -> EnforcementBinding:
    binding = get_binding(db, binding_id, organization_id)
    if binding.status != "draft":
        raise BindingInvalidTransitionError(binding.status, "activate")

    identity = integration_identity_service.get_integration_identity(
        db, binding.integration_identity_id, organization_id
    )
    if identity.status != "active":
        raise BindingValidationError(f"integration identity is not active (status={identity.status!r})")

    contract_version = _resolve_contract_version(db, binding.integration_contract_version_id, organization_id)
    if contract_version.status != "approved":
        raise BindingValidationError(f"contract version is not approved (status={contract_version.status!r})")
    if contract_version.organization_id != organization_id or identity.organization_id != organization_id:
        raise BindingValidationError("contract version and integration identity must belong to the same organization")

    allowed_agents = list_allowed_agents(db, binding_id, organization_id)
    if not allowed_agents:
        raise BindingValidationError("a binding cannot be activated with an empty allowed-agent list")
    for agent in allowed_agents:
        if agent.status not in _ELIGIBLE_AGENT_STATUSES:
            raise BindingValidationError(
                f"agent {agent.id} is not currently eligible for use (status={agent.status!r})"
            )

    # Atomic replacement: retire whichever Binding currently holds this
    # exact scope's single ACTIVE slot, in the same transaction as
    # activating this one -- never two separate commits, which would
    # leave a real (if narrow) window where either both or neither is
    # active.
    prior_active = db.scalar(
        select(EnforcementBinding).where(
            EnforcementBinding.status == "active",
            EnforcementBinding.integration_identity_id == binding.integration_identity_id,
            EnforcementBinding.integration_id == binding.integration_id,
            EnforcementBinding.source_operation == binding.source_operation,
            EnforcementBinding.environment == binding.environment,
        )
    )
    now = datetime.now(timezone.utc)
    if prior_active is not None and prior_active.id != binding.id:
        prior_active.status = "retired"
        prior_active.retired_at = now
        # Flushed here, before activating `binding` below: SQLAlchemy's
        # unit of work does not guarantee this UPDATE is issued before
        # the one that follows just because it was set first in Python
        # -- both are plain UPDATEs on the same table with no FK
        # ordering to rely on (unlike deploy_policy's own retire-then-
        # INSERT shape). Without this explicit flush, the two updates
        # can be issued in the opposite order, transiently leaving BOTH
        # rows 'active' and tripping the real, non-deferred partial
        # unique index (idx_enforcement_bindings_single_active_per_scope)
        # even though the end state is correct -- reproduced directly
        # against real PostgreSQL before this fix.
        db.flush()

    binding.status = "active"
    binding.activated_at = now
    db.commit()
    db.refresh(binding)
    return binding


def retire_binding(db: Session, binding_id: uuid.UUID, organization_id: uuid.UUID) -> EnforcementBinding:
    """active -> retired. Explicit only. A retired Binding's historical
    Intents remain fully queryable forever; retiring a Binding never
    touches anything it already produced."""
    binding = get_binding(db, binding_id, organization_id)
    if binding.status != "active":
        raise BindingInvalidTransitionError(binding.status, "retire")
    binding.status = "retired"
    binding.retired_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(binding)
    return binding


def has_active_binding_for_contract_version(db: Session, contract_version_id: uuid.UUID) -> bool:
    """Trusted Integration Architecture, Phase 2's new constraint on
    Phase 1's own retirement function (section 14): an APPROVED Contract
    version referenced by an ACTIVE Binding must not be retired."""
    return (
        db.scalar(
            select(EnforcementBinding.id).where(
                EnforcementBinding.integration_contract_version_id == contract_version_id,
                EnforcementBinding.status == "active",
            )
        )
        is not None
    )
