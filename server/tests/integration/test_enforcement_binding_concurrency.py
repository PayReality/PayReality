"""Trusted Integration Architecture, Phase 2: real-PostgreSQL proof
that the "exactly one ACTIVE EnforcementBinding per (integration_
identity_id, integration_id, source_operation, environment) scope"
invariant actually holds -- both the ordinary, single-threaded
"activating binding 2 retires binding 1" replacement, and genuinely
concurrent activation attempts racing for the same scope's single slot.

Uses the project's own existing docker-compose Postgres service via the
`postgres_url` fixture (tests/integration/conftest.py) and this repo's
established "force the exact interleaving deterministically, via a
threading.Barrier, never rely on timing" convention (see
test_integration_contract_concurrency.py, test_runtime_policy_
deployment_concurrency.py).
"""

import threading
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models import Agent, EnforcementBinding, Organization, Principal
from app.services import (
    enforcement_binding_service as svc,
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
)
from app.services.enforcement_binding_service import ConcurrentActivationConflictError


@pytest.fixture()
def engine(postgres_url):
    return create_engine(postgres_url)


@pytest.fixture()
def SessionLocal(engine):
    return sessionmaker(bind=engine)


@pytest.fixture()
def db(SessionLocal):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def org(db):
    org = Organization(id=uuid.uuid4(), name="Org Enforcement Binding Concurrency")
    db.add(org)
    db.commit()
    return org


def _setup_scope(db, org_id):
    identity, _cert = identity_svc.register_integration_identity(
        db, org_id, "Reference SAP Adapter", "ed25519:base64:AAAA",
    )
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)
    integration = contract_svc.create_integration(db, org_id, "SAP S/4HANA (reference)")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, "ChangeSupplierBankDetails", "vendor_payment",
    )
    contract_version = contract_svc.validate_contract_version(db, contract_version.id, org_id)
    contract_version = contract_svc.approve_contract_version(db, contract_version.id, org_id, approver="governance-admin@example.com")
    principal = Principal(id=uuid.uuid4(), name="Finance", organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="AP Invoice Agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    return identity, contract_version, agent


def test_activating_a_second_binding_for_the_same_scope_retires_the_first(db, org):
    identity, contract_version, agent = _setup_scope(db, org.id)

    binding1 = svc.create_draft_binding(
        db, org.id, identity.id, contract_version.id, "production", agent_ids=[agent.id],
    )
    binding1 = svc.activate_binding(db, binding1.id, org.id)

    binding2 = svc.create_draft_binding(
        db, org.id, identity.id, contract_version.id, "production", agent_ids=[agent.id],
    )
    binding2 = svc.activate_binding(db, binding2.id, org.id)

    reloaded_binding1 = svc.get_binding(db, binding1.id, org.id)
    assert reloaded_binding1.status == "retired"
    assert reloaded_binding1.retired_at is not None
    assert svc.get_binding(db, binding2.id, org.id).status == "active"

    active_rows = list(
        db.scalars(
            select(EnforcementBinding).where(
                EnforcementBinding.integration_identity_id == identity.id,
                EnforcementBinding.integration_id == contract_version.integration_id,
                EnforcementBinding.source_operation == contract_version.source_operation,
                EnforcementBinding.environment == "production",
                EnforcementBinding.status == "active",
            )
        )
    )
    assert len(active_rows) == 1, "the real partial-unique index must never allow two active bindings for one scope"


def _activate_in_new_session(SessionLocal, binding_id, org_id, results, errors):
    session = SessionLocal()
    try:
        row = svc.activate_binding(session, binding_id, org_id)
        results.append(row.id)
    except Exception as e:  # pragma: no cover -- surfaced via the assertion below, never swallowed
        errors.append(e)
    finally:
        session.close()


def test_two_concurrent_activations_for_the_same_scope_never_both_end_active(db, SessionLocal, org):
    """Two already-DRAFT bindings for the identical scope, both racing
    to activate at genuinely the same instant. Exactly one must win the
    single ACTIVE slot; the other either loses honestly (retiring the
    winner's predecessor doesn't apply here since neither was active
    yet, so the loser's own attempt must itself observe the invariant
    and never leave two rows active) or exhausts its bounded retries
    with the typed ConcurrentActivationConflictError -- never a raw
    IntegrityError, and never two simultaneously ACTIVE rows."""
    identity, contract_version, agent = _setup_scope(db, org.id)

    binding1 = svc.create_draft_binding(
        db, org.id, identity.id, contract_version.id, "production", agent_ids=[agent.id],
    )
    binding2 = svc.create_draft_binding(
        db, org.id, identity.id, contract_version.id, "production", agent_ids=[agent.id],
    )

    barrier = threading.Barrier(2)
    real_attempt = svc._activate_binding_attempt

    def synchronized_attempt(*args, **kwargs):
        tid = threading.get_ident()
        if tid not in synchronized_attempt._synced:
            synchronized_attempt._synced.add(tid)
            barrier.wait(timeout=30)
        return real_attempt(*args, **kwargs)

    synchronized_attempt._synced = set()
    svc._activate_binding_attempt = synchronized_attempt

    results: list = []
    errors: list = []
    try:
        t1 = threading.Thread(target=_activate_in_new_session, args=(SessionLocal, binding1.id, org.id, results, errors))
        t2 = threading.Thread(target=_activate_in_new_session, args=(SessionLocal, binding2.id, org.id, results, errors))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)
    finally:
        svc._activate_binding_attempt = real_attempt

    for e in errors:
        assert isinstance(e, ConcurrentActivationConflictError), (
            f"only the typed give-up error is an acceptable failure under contention, got: {e!r}"
        )

    active_rows = list(
        db.scalars(
            select(EnforcementBinding).where(
                EnforcementBinding.integration_identity_id == identity.id,
                EnforcementBinding.integration_id == contract_version.integration_id,
                EnforcementBinding.source_operation == contract_version.source_operation,
                EnforcementBinding.environment == "production",
                EnforcementBinding.status == "active",
            )
        )
    )
    assert len(active_rows) <= 1, f"never more than one active binding for one scope, got {len(active_rows)}"
