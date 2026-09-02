"""Developer Distribution & Sandbox v1: real, end-to-end proof that the
new sandbox path works and stays isolated. Real SQLite + real ephemeral
OPA (this repo's own established convention), calling the actual router
function directly (this repo has no FastAPI TestClient precedent --
see test_tenant_scoped_verification.py's own docstring for why) with a
real, minimally-populated Starlette `Request` (not a mock) so the real
rate-limiting code path (`security.check_rate_limit`, keyed off the
request's own client address) actually runs.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.config import settings
from app.db.models import Agent, Base, IntegrationIdentity, Organization, Principal, RuntimePolicyRecord
from app.domain.decision import engine as decision_engine
from app.routers.sandbox import _sandbox_create_log, create_sandbox_organization
from app.schemas.sandbox import CreateSandboxRequest
from app.services import (
    agent_service,
    integration_identity_service,
    organization_lifecycle_service as org_lifecycle_svc,
    runtime_policy_service as policy_svc,
    sandbox_limits,
)

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)


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


@pytest.fixture(autouse=True)
def _point_settings_at_ephemeral_opa(request):
    opa_url = request.getfixturevalue("opa_url")
    original = settings.opa_url
    settings.opa_url = opa_url
    try:
        yield
    finally:
        settings.opa_url = original


@pytest.fixture(autouse=True)
def _reset_sandbox_rate_limit_log():
    """The sandbox creation rate limiter (`_sandbox_create_log`) is a
    module-level, in-process store, exactly like the general one it's
    modeled on -- reset between tests so one test's requests never
    count against another's budget."""
    _sandbox_create_log.clear()
    yield
    _sandbox_create_log.clear()


def _fake_request(client_ip: str = "203.0.113.5") -> Request:
    """A real, minimally-populated Starlette Request (not a mock) --
    just enough ASGI scope for `security._client_key` to resolve a
    client address from, the only thing this router reads off it."""
    scope = {
        "type": "http",
        "client": (client_ip, 12345),
        "headers": [],
        "method": "POST",
        "path": "/v1/sandbox/organizations",
        "query_string": b"",
    }
    return Request(scope)


def _create_sandbox(db, email="dev@example.com", client_ip="203.0.113.5", name=None):
    body = CreateSandboxRequest(email=email, name=name)
    return create_sandbox_organization(body, _fake_request(client_ip), db)


# --- Happy path: real backend, real Decision --------------------------------


def test_sandbox_creation_provisions_org_agent_ready_starter_policy(db):
    response = _create_sandbox(db)

    org = db.get(Organization, uuid.UUID(response.organization_id))
    assert org.environment == "sandbox"
    assert org.status == "active"

    policy = db.scalar(
        __import__("sqlalchemy").select(RuntimePolicyRecord).where(
            RuntimePolicyRecord.policy_key == uuid.UUID(response.starter_policy_key)
        )
    )
    # "active" confirms the full create -> submit -> approve -> compile ->
    # deploy lifecycle actually ran end to end, not just "approved" (which
    # would mean deploy never happened).
    assert policy.status == "active"


def test_sandbox_starter_policy_produces_a_real_allow_decision(db, opa_url):
    """Not a mocked/fake Decision -- the real intent_service pipeline,
    the real compiled OPA bundle, exactly like every other Decision in
    this codebase."""
    from app.services import intent_service

    response = _create_sandbox(db)
    organization_id = uuid.UUID(response.organization_id)

    principal = Principal(id=uuid.uuid4(), name="Sandbox Principal", organization_id=organization_id)
    db.add(principal)
    db.commit()
    agent = agent_service.create_agent(
        db, name="Sandbox Test Agent", acting_for_principal_id=principal.id,
        organization_id=organization_id, public_key="ed25519:base64:AAAA",
    )[0]
    agent_service.activate_agent(db, agent.id)

    _intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action="purchase_order_create", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
    )
    assert decision.outcome == "ALLOW"


# --- One-per-email and rate limiting -----------------------------------


def test_second_sandbox_for_the_same_email_is_refused(db):
    _create_sandbox(db, email="dupe@example.com")
    with pytest.raises(Exception) as excinfo:
        _create_sandbox(db, email="dupe@example.com", client_ip="203.0.113.6")
    assert "409" in str(excinfo.value) or "sandbox_already_exists" in str(excinfo.value)


def test_sandbox_creation_rate_limit_is_enforced(db):
    ip = "198.51.100.9"
    for i in range(3):
        _create_sandbox(db, email=f"burst{i}@example.com", client_ip=ip)
    with pytest.raises(Exception) as excinfo:
        _create_sandbox(db, email="burst-over-limit@example.com", client_ip=ip)
    assert "429" in str(excinfo.value) or "rate_limit" in str(excinfo.value)


def test_rate_limit_is_scoped_per_ip_not_global(db):
    ip_a = "198.51.100.10"
    for i in range(3):
        _create_sandbox(db, email=f"a{i}@example.com", client_ip=ip_a)
    # A different IP has its own, untouched budget.
    response = _create_sandbox(db, email="b0@example.com", client_ip="198.51.100.11")
    assert response.organization_id


# --- Resource caps -------------------------------------------------------


def test_sandbox_agent_cap_is_enforced(db):
    response = _create_sandbox(db, email="caps-agent@example.com")
    organization_id = uuid.UUID(response.organization_id)
    principal = Principal(id=uuid.uuid4(), name="P", organization_id=organization_id)
    db.add(principal)
    db.commit()

    for i in range(sandbox_limits.MAX_AGENTS_PER_SANDBOX):
        agent_service.create_agent(
            db, name=f"Agent {i}", acting_for_principal_id=principal.id,
            organization_id=organization_id, public_key=f"ed25519:base64:AAA{i}",
        )

    with pytest.raises(sandbox_limits.SandboxLimitExceededError):
        agent_service.create_agent(
            db, name="One too many", acting_for_principal_id=principal.id,
            organization_id=organization_id, public_key="ed25519:base64:OVER",
        )


def test_sandbox_integration_identity_cap_is_enforced(db):
    response = _create_sandbox(db, email="caps-ii@example.com")
    organization_id = uuid.UUID(response.organization_id)

    for i in range(sandbox_limits.MAX_INTEGRATION_IDENTITIES_PER_SANDBOX):
        integration_identity_service.register_integration_identity(
            db, organization_id, f"Identity {i}", f"ed25519:base64:BBB{i}",
        )

    with pytest.raises(sandbox_limits.SandboxLimitExceededError):
        integration_identity_service.register_integration_identity(
            db, organization_id, "One too many", "ed25519:base64:OVER",
        )


def test_production_organization_is_never_capped(db):
    """The cap only ever applies to environment == 'sandbox' -- a real
    production organization (the default) is never limited by it."""
    org = Organization(name="Real Customer", environment="production")
    db.add(org)
    db.commit()
    principal = Principal(id=uuid.uuid4(), name="P", organization_id=org.id)
    db.add(principal)
    db.commit()

    for i in range(sandbox_limits.MAX_AGENTS_PER_SANDBOX + 2):
        agent_service.create_agent(
            db, name=f"Agent {i}", acting_for_principal_id=principal.id,
            organization_id=org.id, public_key=f"ed25519:base64:CCC{i}",
        )
    # No exception -- production is uncapped.


# --- Hostile: tenant isolation for sandbox orgs specifically ---------------


def test_sandbox_org_cannot_see_a_different_sandbox_orgs_agents(db):
    response_a = _create_sandbox(db, email="tenant-a@example.com")
    response_b = _create_sandbox(db, email="tenant-b@example.com", client_ip="203.0.113.7")
    org_a_id = uuid.UUID(response_a.organization_id)
    org_b_id = uuid.UUID(response_b.organization_id)

    principal_a = Principal(id=uuid.uuid4(), name="P-A", organization_id=org_a_id)
    db.add(principal_a)
    db.commit()
    agent_a, _ = agent_service.create_agent(
        db, name="Org A Agent", acting_for_principal_id=principal_a.id,
        organization_id=org_a_id, public_key="ed25519:base64:AGENTA",
    )

    agents_visible_to_b, _total = agent_service.list_agents(db, organization_id=org_b_id)
    assert agent_a.id not in [a.id for a, _cert in agents_visible_to_b]


def test_sandbox_org_cannot_see_a_production_orgs_agents(db):
    sandbox_response = _create_sandbox(db, email="sandbox-vs-prod@example.com")
    sandbox_org_id = uuid.UUID(sandbox_response.organization_id)

    prod_org = Organization(name="Real Customer", environment="production")
    db.add(prod_org)
    db.commit()
    prod_principal = Principal(id=uuid.uuid4(), name="Prod P", organization_id=prod_org.id)
    db.add(prod_principal)
    db.commit()
    prod_agent, _ = agent_service.create_agent(
        db, name="Prod Agent", acting_for_principal_id=prod_principal.id,
        organization_id=prod_org.id, public_key="ed25519:base64:PRODAGENT",
    )

    agents_visible_to_sandbox, _total = agent_service.list_agents(db, organization_id=sandbox_org_id)
    assert prod_agent.id not in [a.id for a, _cert in agents_visible_to_sandbox]


def test_sandbox_api_key_resolves_only_its_own_organization(db):
    """The credential the sandbox endpoint hands back can never resolve
    to a different organization -- proves the exact "sandbox credential
    used against production" hostile scenario is not possible by
    construction (ApiKey -> organization_id is fixed at creation, the
    same tenant-scoping every other credential already has)."""
    from app.db.models import ApiKey
    from app.services import auth_service

    response = _create_sandbox(db, email="key-scope@example.com")
    key_row = db.scalar(
        __import__("sqlalchemy").select(ApiKey).where(ApiKey.organization_id == uuid.UUID(response.organization_id))
    )
    assert key_row is not None
    resolved_org_id = auth_service.resolve_organization_id_for_token(db, response.api_key)
    assert str(resolved_org_id) == response.organization_id


# --- Stale sandbox cleanup ------------------------------------------------


def test_stale_sandbox_cleanup_only_touches_old_sandbox_orgs(db):
    fresh_sandbox = _create_sandbox(db, email="fresh@example.com")
    stale_sandbox = _create_sandbox(db, email="stale@example.com", client_ip="203.0.113.8")

    stale_org = db.get(Organization, uuid.UUID(stale_sandbox.organization_id))
    stale_org.created_at = datetime.now(timezone.utc) - timedelta(days=30)
    db.commit()

    prod_org = Organization(name="Real Customer", environment="production")
    prod_org.created_at = datetime.now(timezone.utc) - timedelta(days=365)
    db.add(prod_org)
    db.commit()

    archived = org_lifecycle_svc.archive_stale_sandbox_organizations(db, older_than_days=14)
    archived_ids = {o.id for o in archived}

    assert stale_org.id in archived_ids
    assert uuid.UUID(fresh_sandbox.organization_id) not in archived_ids
    assert prod_org.id not in archived_ids
    db.refresh(prod_org)
    assert prod_org.status == "active"  # never touched
