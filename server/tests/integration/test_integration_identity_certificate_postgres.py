"""Trusted Integration Architecture, Phase 2: real-PostgreSQL proof of
IntegrationIdentityCertificate rotation and its single-active-
certificate invariant (idx_integration_identity_certificates_single_
active) -- the exact same partial-unique-index pattern already proven
for Agent's own Certificate (idx_certificates_single_active), needed
here for the same reason: `postgresql_where=...` is ignored on SQLite,
which materializes a plain, non-partial UNIQUE(integration_identity_id)
instead and would reject a legitimate rotated-old/active-new row pair
that never actually violates the real, intended constraint. See
test_integration_identity_lifecycle.py's own note for the full
explanation of why this lives here instead.

Uses the project's own existing docker-compose Postgres service via the
`postgres_url` fixture (tests/integration/conftest.py) -- skips cleanly
if Postgres isn't reachable.
"""

import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.models import IntegrationIdentityCertificate, Organization
from app.services import integration_identity_service as svc
from app.services.integration_identity_service import NoActiveCertificateError


@pytest.fixture()
def engine(postgres_url):
    return create_engine(postgres_url)


@pytest.fixture()
def db(engine):
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def org(db):
    org = Organization(id=uuid.uuid4(), name="Org Integration Identity Certificate Postgres")
    db.add(org)
    db.commit()
    return org


def test_rotate_certificate_activates_new_and_never_deletes_old(db, org):
    identity, old_cert = svc.register_integration_identity(db, org.id, "Reference SAP Adapter", "ed25519:base64:AAAA")
    svc.activate_integration_identity(db, identity.id, org.id)

    new_cert = svc.rotate_certificate(db, identity.id, org.id, "ed25519:base64:BBBB")

    assert new_cert.status == "active"
    assert new_cert.public_key == "ed25519:base64:BBBB"
    reloaded_old = db.get(IntegrationIdentityCertificate, old_cert.id)
    assert reloaded_old.status == "rotated"
    assert reloaded_old.rotated_at is not None
    still_there = db.scalar(
        select(IntegrationIdentityCertificate).where(IntegrationIdentityCertificate.id == old_cert.id)
    )
    assert still_there is not None


def test_only_one_active_certificate_at_a_time_db_enforced(db, org):
    identity, _old_cert = svc.register_integration_identity(db, org.id, "Reference SAP Adapter", "ed25519:base64:AAAA")
    svc.activate_integration_identity(db, identity.id, org.id)
    svc.rotate_certificate(db, identity.id, org.id, "ed25519:base64:BBBB")
    svc.rotate_certificate(db, identity.id, org.id, "ed25519:base64:CCCC")

    active_certs = [c for c in svc.list_certificates(db, identity.id) if c.status == "active"]
    assert len(active_certs) == 1

    db_rows = list(
        db.scalars(
            select(IntegrationIdentityCertificate).where(
                IntegrationIdentityCertificate.integration_identity_id == identity.id,
                IntegrationIdentityCertificate.status == "active",
            )
        )
    )
    assert len(db_rows) == 1, "the real partial-unique index must never allow two active certificates for one identity"


def test_rotate_requires_an_active_certificate_to_exist(db, org):
    identity, certificate = svc.register_integration_identity(db, org.id, "Reference SAP Adapter", "ed25519:base64:AAAA")
    svc.activate_integration_identity(db, identity.id, org.id)
    certificate.status = "expired"
    db.commit()
    with pytest.raises(NoActiveCertificateError):
        svc.rotate_certificate(db, identity.id, org.id, "ed25519:base64:BBBB")
