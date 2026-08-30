"""Trusted Integration Architecture, Phase 2: EnforcementBinding's own
draft/edit/allow-list/activation/retirement lifecycle, its activation
prerequisites (section 12), its interaction with Phase 1's Contract
retirement guard (section 14), and organisation isolation. Real
SQLite throughout, following test_integration_contract_lifecycle.py's
own established convention -- no OPA, no concurrency needed here (see
test_enforcement_binding_concurrency.py for the real-Postgres proof of
the single-ACTIVE-binding-per-scope invariant).
"""

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.db.models import Agent, Base, EnforcementBinding, Organization, Principal
from app.services import (
    enforcement_binding_service as svc,
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
)
from app.services.enforcement_binding_service import (
    BindingInvalidTransitionError,
    BindingValidationError,
    EnforcementBindingNotFoundError,
)
from app.services.integration_contract_service import ContractVersionHasActiveBindingError
from app.services.integration_identity_service import IntegrationIdentityNotFoundError


@compiles(PG_JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _uuid_as_char_on_sqlite(element, compiler, **kw):
    return "CHAR(36)"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    policies_table = Base.metadata.tables["policies"]
    partial_index = next(i for i in policies_table.indexes if i.name == "idx_policies_single_active_per_org")
    policies_table.indexes.discard(partial_index)
    try:
        Base.metadata.create_all(engine)
    finally:
        policies_table.indexes.add(partial_index)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def org(db):
    org = Organization(id=uuid.uuid4(), name="Org A")
    db.add(org)
    db.commit()
    return org


@pytest.fixture()
def other_org(db):
    org = Organization(id=uuid.uuid4(), name="Org B")
    db.add(org)
    db.commit()
    return org


def _identity(db, org_id, name="Reference SAP Adapter", activate=True):
    identity, _cert = identity_svc.register_integration_identity(db, org_id, name, "ed25519:base64:AAAA")
    if activate:
        identity = identity_svc.activate_integration_identity(db, identity.id, org_id)
    return identity


def _approved_contract_version(db, org_id, source_operation="ChangeSupplierBankDetails", **kw):
    integration = contract_svc.create_integration(db, org_id, "SAP S/4HANA (reference)")
    version = contract_svc.create_contract_version(db, integration.id, org_id, source_operation, "vendor_payment", **kw)
    version = contract_svc.validate_contract_version(db, version.id, org_id)
    return contract_svc.approve_contract_version(db, version.id, org_id, approver="governance-admin@example.com")


def _principal(db, org_id, name="Finance"):
    principal = Principal(id=uuid.uuid4(), name=name, organization_id=org_id)
    db.add(principal)
    db.commit()
    return principal


def _agent(db, principal_id, name="AP Invoice Agent", status="active"):
    agent = Agent(id=uuid.uuid4(), name=name, acting_for_principal_id=principal_id, status=status)
    db.add(agent)
    db.commit()
    return agent


def _draft(db, org_id, environment="production", agent_ids=None):
    identity = _identity(db, org_id)
    contract_version = _approved_contract_version(db, org_id)
    principal = _principal(db, org_id)
    agent = _agent(db, principal.id)
    binding = svc.create_draft_binding(
        db, org_id, identity.id, contract_version.id, environment,
        agent_ids=agent_ids if agent_ids is not None else [agent.id],
    )
    return binding, identity, contract_version, agent


# --- Draft creation ------------------------------------------------------


def test_create_draft_binding_denormalizes_integration_and_source_operation(db, org):
    binding, _identity, contract_version, _agent = _draft(db, org.id)
    assert binding.status == "draft"
    assert binding.integration_id == contract_version.integration_id
    assert binding.source_operation == contract_version.source_operation


def test_create_draft_requires_environment(db, org):
    identity = _identity(db, org.id)
    contract_version = _approved_contract_version(db, org.id)
    with pytest.raises(BindingValidationError):
        svc.create_draft_binding(db, org.id, identity.id, contract_version.id, "")


def test_create_draft_rejects_cross_org_identity(db, org, other_org):
    identity = _identity(db, other_org.id)
    contract_version = _approved_contract_version(db, org.id)
    with pytest.raises(IntegrationIdentityNotFoundError):
        svc.create_draft_binding(db, org.id, identity.id, contract_version.id, "production")


def test_create_draft_rejects_cross_org_contract_version(db, org, other_org):
    identity = _identity(db, org.id)
    contract_version = _approved_contract_version(db, other_org.id)
    with pytest.raises(contract_svc.ContractVersionNotFoundError):
        svc.create_draft_binding(db, org.id, identity.id, contract_version.id, "production")


def test_create_draft_does_not_require_contract_to_be_approved_yet(db, org):
    """Section 12's activation prerequisites are deliberately not
    required merely to sketch out a draft -- a Contract may still be
    mid-review when a Binding is first drafted."""
    identity = _identity(db, org.id)
    integration = contract_svc.create_integration(db, org.id, "SAP S/4HANA (reference)")
    still_draft_version = contract_svc.create_contract_version(
        db, integration.id, org.id, "ChangeSupplierBankDetails", "vendor_payment",
    )
    binding = svc.create_draft_binding(db, org.id, identity.id, still_draft_version.id, "production")
    assert binding.status == "draft"


# --- Editing (DRAFT only) -------------------------------------------------


def test_edit_draft_updates_only_supplied_fields(db, org):
    binding, _identity, _cv, _agent = _draft(db, org.id, environment="staging")
    edited = svc.edit_draft_binding(db, binding.id, org.id, environment="production")
    assert edited.environment == "production"


def test_cannot_edit_an_active_binding(db, org):
    binding, _identity, _cv, _agent = _draft(db, org.id)
    active = svc.activate_binding(db, binding.id, org.id)
    with pytest.raises(BindingInvalidTransitionError):
        svc.edit_draft_binding(db, active.id, org.id, environment="staging")


def test_edit_draft_rejects_empty_environment(db, org):
    binding, _identity, _cv, _agent = _draft(db, org.id)
    with pytest.raises(BindingValidationError):
        svc.edit_draft_binding(db, binding.id, org.id, environment="")


# --- Allowed-agent management (DRAFT only) --------------------------------


def test_add_and_remove_allowed_agent_while_draft(db, org):
    binding, _identity, _cv, agent = _draft(db, org.id, agent_ids=[])
    svc.add_allowed_agent(db, binding.id, org.id, agent.id)
    assert [a.id for a in svc.list_allowed_agents(db, binding.id, org.id)] == [agent.id]
    svc.remove_allowed_agent(db, binding.id, org.id, agent.id)
    assert svc.list_allowed_agents(db, binding.id, org.id) == []


def test_add_allowed_agent_rejects_agent_from_a_different_organization(db, org, other_org):
    binding, _identity, _cv, _draft_agent = _draft(db, org.id, agent_ids=[])
    other_principal = _principal(db, other_org.id, "Other Org Finance")
    other_agent = _agent(db, other_principal.id, "Other Org Agent")
    with pytest.raises(BindingValidationError):
        svc.add_allowed_agent(db, binding.id, org.id, other_agent.id)


def test_cannot_edit_allowed_agents_once_active(db, org):
    binding, _identity, _cv, agent = _draft(db, org.id)
    active = svc.activate_binding(db, binding.id, org.id)
    with pytest.raises(BindingInvalidTransitionError):
        svc.add_allowed_agent(db, active.id, org.id, agent.id)
    with pytest.raises(BindingInvalidTransitionError):
        svc.remove_allowed_agent(db, active.id, org.id, agent.id)


# --- Activation prerequisites (section 12) --------------------------------


def test_activate_requires_integration_identity_active(db, org):
    identity = _identity(db, org.id, activate=False)  # stays 'registered'
    contract_version = _approved_contract_version(db, org.id)
    principal = _principal(db, org.id)
    agent = _agent(db, principal.id)
    binding = svc.create_draft_binding(db, org.id, identity.id, contract_version.id, "production", agent_ids=[agent.id])
    with pytest.raises(BindingValidationError):
        svc.activate_binding(db, binding.id, org.id)


def test_activate_requires_contract_version_approved(db, org):
    identity = _identity(db, org.id)
    integration = contract_svc.create_integration(db, org.id, "SAP S/4HANA (reference)")
    unapproved_version = contract_svc.create_contract_version(
        db, integration.id, org.id, "ChangeSupplierBankDetails", "vendor_payment",
    )
    principal = _principal(db, org.id)
    agent = _agent(db, principal.id)
    binding = svc.create_draft_binding(
        db, org.id, identity.id, unapproved_version.id, "production", agent_ids=[agent.id],
    )
    with pytest.raises(BindingValidationError):
        svc.activate_binding(db, binding.id, org.id)


def test_activate_requires_a_nonempty_allow_list(db, org):
    binding, _identity, _cv, _agent = _draft(db, org.id, agent_ids=[])
    with pytest.raises(BindingValidationError):
        svc.activate_binding(db, binding.id, org.id)


def test_activate_requires_every_allowed_agent_to_be_eligible(db, org):
    principal = _principal(db, org.id)
    ineligible_agent = _agent(db, principal.id, status="suspended")
    identity = _identity(db, org.id)
    contract_version = _approved_contract_version(db, org.id)
    binding = svc.create_draft_binding(
        db, org.id, identity.id, contract_version.id, "production", agent_ids=[ineligible_agent.id],
    )
    with pytest.raises(BindingValidationError):
        svc.activate_binding(db, binding.id, org.id)


def test_successful_activation_sets_active_and_activated_at(db, org):
    binding, _identity, _cv, _agent = _draft(db, org.id)
    activated = svc.activate_binding(db, binding.id, org.id)
    assert activated.status == "active"
    assert activated.activated_at is not None


def test_cannot_activate_a_non_draft_binding_twice(db, org):
    binding, _identity, _cv, _agent = _draft(db, org.id)
    svc.activate_binding(db, binding.id, org.id)
    with pytest.raises(BindingInvalidTransitionError):
        svc.activate_binding(db, binding.id, org.id)


# --- Exactly one ACTIVE binding per scope ---------------------------------
#
# NOTE: "activating a second binding for the exact same scope retires the
# prior one" is proven against real PostgreSQL, in
# test_enforcement_binding_concurrency.py, not here. Even a single-
# threaded version of that test creates two DRAFT rows sharing the same
# (integration_identity_id, integration_id, source_operation,
# environment) tuple before either is activated -- and
# idx_enforcement_bindings_single_active_per_scope's `postgresql_where`
# clause is ignored on SQLite, which materializes a plain, non-partial
# UNIQUE across those four columns instead, rejecting the second DRAFT
# outright even though two DRAFTs sharing a scope is completely legal
# (only one may ever be ACTIVE at a time). Same class of divergence as
# test_integration_identity_certificate_postgres.py's own note.


def test_two_different_environments_can_both_be_active_at_once(db, org):
    identity = _identity(db, org.id)
    contract_version = _approved_contract_version(db, org.id)
    principal = _principal(db, org.id)
    agent = _agent(db, principal.id)

    staging = svc.create_draft_binding(
        db, org.id, identity.id, contract_version.id, "staging", agent_ids=[agent.id],
    )
    production = svc.create_draft_binding(
        db, org.id, identity.id, contract_version.id, "production", agent_ids=[agent.id],
    )
    svc.activate_binding(db, staging.id, org.id)
    svc.activate_binding(db, production.id, org.id)

    assert svc.get_binding(db, staging.id, org.id).status == "active"
    assert svc.get_binding(db, production.id, org.id).status == "active"


# --- Retirement ------------------------------------------------------------


def test_retire_requires_active_status(db, org):
    binding, _identity, _cv, _agent = _draft(db, org.id)
    with pytest.raises(BindingInvalidTransitionError):
        svc.retire_binding(db, binding.id, org.id)


def test_explicit_retirement(db, org):
    binding, _identity, _cv, _agent = _draft(db, org.id)
    svc.activate_binding(db, binding.id, org.id)
    retired = svc.retire_binding(db, binding.id, org.id)
    assert retired.status == "retired"
    assert retired.retired_at is not None


def test_retired_binding_remains_queryable_historically(db, org):
    binding, _identity, _cv, _agent = _draft(db, org.id)
    svc.activate_binding(db, binding.id, org.id)
    svc.retire_binding(db, binding.id, org.id)
    still_there = db.scalar(select(EnforcementBinding).where(EnforcementBinding.id == binding.id))
    assert still_there is not None
    assert still_there.status == "retired"


# --- Interaction with Phase 1's Contract retirement (section 14) ----------


def test_contract_version_retirement_is_blocked_while_an_active_binding_references_it(db, org):
    binding, _identity, contract_version, _agent = _draft(db, org.id)
    svc.activate_binding(db, binding.id, org.id)
    with pytest.raises(ContractVersionHasActiveBindingError):
        contract_svc.retire_contract_version(db, contract_version.id, org.id)


def test_contract_version_retirement_succeeds_once_the_binding_is_retired_first(db, org):
    binding, _identity, contract_version, _agent = _draft(db, org.id)
    svc.activate_binding(db, binding.id, org.id)
    svc.retire_binding(db, binding.id, org.id)
    retired_version = contract_svc.retire_contract_version(db, contract_version.id, org.id)
    assert retired_version.status == "retired"


def test_contract_version_retirement_is_unaffected_by_a_draft_binding_referencing_it(db, org):
    """Only an ACTIVE binding blocks retirement -- a draft one, which
    never participates in runtime evaluation, does not."""
    _binding, _identity, contract_version, _agent = _draft(db, org.id)
    retired_version = contract_svc.retire_contract_version(db, contract_version.id, org.id)
    assert retired_version.status == "retired"


# --- Cross-org isolation ---------------------------------------------------


def test_binding_cross_org_access_is_not_found(db, org, other_org):
    binding, _identity, _cv, _agent = _draft(db, org.id)
    with pytest.raises(EnforcementBindingNotFoundError):
        svc.get_binding(db, binding.id, other_org.id)


def test_list_bindings_never_crosses_organizations(db, org, other_org):
    _draft(db, org.id)
    _draft(db, other_org.id)
    assert len(svc.list_bindings(db, org.id)) == 1
    assert len(svc.list_bindings(db, other_org.id)) == 1
