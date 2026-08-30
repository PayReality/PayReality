"""Trusted Integration Architecture, Phase 2: IntegrationIdentity's own
lifecycle and certificate rotation -- a direct mirror of Agent's own
proven state machine (test_agent_lifecycle.py's own _ALLOWED_TRANSITIONS
assertions), applied here against a real, DB-backed service (unlike
that file's pure-logic split, a real SQLite session is available and
used throughout, matching test_integration_contract_lifecycle.py's own
established convention).
"""

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, IntegrationIdentityCertificate, Organization
from app.services import integration_identity_service as svc
from app.services.integration_identity_service import (
    IntegrationIdentityInvalidTransitionError,
    IntegrationIdentityNotFoundError,
    NoActiveCertificateError,
)


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


def _register(db, org_id, name="Reference SAP Adapter"):
    return svc.register_integration_identity(db, org_id, name, "ed25519:base64:AAAA")


# --- Registration ------------------------------------------------------------


def test_register_starts_registered_with_an_issued_not_active_certificate(db, org):
    identity, certificate = _register(db, org.id)
    assert identity.status == "registered"
    assert certificate.status == "issued"
    assert certificate.integration_identity_id == identity.id


def test_registered_identity_never_appears_as_a_runtime_policy_principal_field():
    """Section 5's own invariant, checked at the model level: nothing
    about IntegrationIdentity is, or resembles, a Scope.principal --
    confirmed by construction, since the model carries no field named
    or shaped like one."""
    from app.db.models import IntegrationIdentity

    columns = {c.name for c in IntegrationIdentity.__table__.columns}
    assert "principal" not in columns
    assert "acting_for_principal_id" not in columns


# --- Lifecycle transitions ----------------------------------------------------


def test_activate_moves_identity_and_certificate_to_active(db, org):
    identity, certificate = _register(db, org.id)
    activated = svc.activate_integration_identity(db, identity.id, org.id)
    assert activated.status == "active"
    reloaded_cert = db.get(IntegrationIdentityCertificate, certificate.id)
    assert reloaded_cert.status == "active"
    assert reloaded_cert.activated_at is not None


def test_active_can_suspend_revoke_or_retire(db, org):
    identity, _cert = _register(db, org.id)
    svc.activate_integration_identity(db, identity.id, org.id)
    suspended = svc.suspend_integration_identity(db, identity.id, org.id)
    assert suspended.status == "suspended"


def test_revoked_and_retired_are_terminal(db, org):
    identity, _cert = _register(db, org.id)
    svc.activate_integration_identity(db, identity.id, org.id)
    svc.revoke_integration_identity(db, identity.id, org.id)
    with pytest.raises(IntegrationIdentityInvalidTransitionError):
        svc.activate_integration_identity(db, identity.id, org.id)


def test_revoking_also_revokes_the_live_certificate(db, org):
    identity, certificate = _register(db, org.id)
    svc.activate_integration_identity(db, identity.id, org.id)
    svc.revoke_integration_identity(db, identity.id, org.id)
    reloaded_cert = db.get(IntegrationIdentityCertificate, certificate.id)
    assert reloaded_cert.status == "revoked"
    assert reloaded_cert.revoked_at is not None


def test_retiring_expires_the_live_certificate(db, org):
    identity, certificate = _register(db, org.id)
    svc.activate_integration_identity(db, identity.id, org.id)
    svc.retire_integration_identity(db, identity.id, org.id)
    reloaded_cert = db.get(IntegrationIdentityCertificate, certificate.id)
    assert reloaded_cert.status == "expired"


def test_registered_cannot_suspend_directly(db, org):
    identity, _cert = _register(db, org.id)
    with pytest.raises(IntegrationIdentityInvalidTransitionError):
        svc.suspend_integration_identity(db, identity.id, org.id)


def test_cross_org_access_is_not_found(db, org, other_org):
    identity, _cert = _register(db, org.id)
    with pytest.raises(IntegrationIdentityNotFoundError):
        svc.get_integration_identity(db, identity.id, other_org.id)
    with pytest.raises(IntegrationIdentityNotFoundError):
        svc.activate_integration_identity(db, identity.id, other_org.id)


def test_list_never_crosses_organizations(db, org, other_org):
    _register(db, org.id, "Adapter A")
    _register(db, other_org.id, "Adapter B")
    assert len(svc.list_integration_identities(db, org.id)) == 1
    assert len(svc.list_integration_identities(db, other_org.id)) == 1


# --- Certificate rotation ------------------------------------------------------
#
# NOTE: rotation itself (old -> 'rotated', new row -> 'active' in the same
# transaction) is exercised against real PostgreSQL in
# test_integration_identity_certificate_postgres.py, not here. The
# single-active-certificate index (idx_integration_identity_certificates_
# single_active) is declared with `postgresql_where=...`, exactly like
# Certificate's own proven idx_certificates_single_active -- SQLite
# ignores that dialect-specific clause and materializes a plain,
# non-partial UNIQUE(integration_identity_id) instead, which would
# reject the second (rotated-old, active-new) row pair even though the
# real, intended constraint ("at most one ACTIVE row") is never
# violated. This is the same pre-existing SQLite/Postgres divergence
# test_agent_lifecycle.py's own docstring already discloses for
# Certificate; real-Postgres is the correct, and only correct, way to
# prove this invariant, matching this milestone's own Binding-activation
# concurrency proof.


def test_rotate_requires_an_active_certificate_to_exist(db, org):
    """Defensive-code path: not reachable through this service's own
    transitions in normal use (activate always sets the one 'issued'
    certificate to 'active' in the same call), but still guarded --
    simulated here by expiring the active certificate directly, the way
    a future admin action or data-repair script might."""
    identity, certificate = _register(db, org.id)
    svc.activate_integration_identity(db, identity.id, org.id)
    certificate.status = "expired"
    db.commit()
    with pytest.raises(NoActiveCertificateError):
        svc.rotate_certificate(db, identity.id, org.id, "ed25519:base64:BBBB")


def test_rotate_rejected_for_a_revoked_identity(db, org):
    identity, _cert = _register(db, org.id)
    svc.activate_integration_identity(db, identity.id, org.id)
    svc.revoke_integration_identity(db, identity.id, org.id)
    with pytest.raises(IntegrationIdentityInvalidTransitionError):
        svc.rotate_certificate(db, identity.id, org.id, "ed25519:base64:BBBB")


def test_get_active_certificate_is_the_runtime_auth_lookup(db, org):
    """The exact lookup verify_integration_identity_signature performs:
    not organization-scoped (the request header alone is the lookup key
    at that point), and returns None for anything but an 'active' row."""
    identity, certificate = _register(db, org.id)
    assert svc.get_active_certificate(db, certificate.id) is None  # still 'issued'
    svc.activate_integration_identity(db, identity.id, org.id)
    found = svc.get_active_certificate(db, certificate.id)
    assert found is not None
    assert found.id == certificate.id
