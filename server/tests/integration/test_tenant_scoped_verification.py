"""Trusted Integration Architecture, Phase 6.1 (Production Authorization
Assurance), Part B: Tenant Scoped Verification Identity.

Real SQLite + real ephemeral OPA, mirroring test_authorization_
freshness.py's own fixtures. Exercises the ACTUAL auth boundary, not a
mocked stand-in: real `ApiKey` rows (created the same way
auth_service.generate_api_key/hash_api_key would produce them), passed
through the real, unmodified `app.dependencies.get_current_organization`
and `app.dependencies.require_permission` functions -- the exact same
functions routers/capability_tokens.py's own endpoint depends on -- not
a re-implementation of what they're supposed to do. This repository has
no existing FastAPI TestClient-based test convention (grepped for one
before writing this file; none exists), and wiring one correctly would
also need to stub or skip this app's lifespan startup hooks (signing-key
registration, owner bootstrap, OPA reconciliation), which call
SessionLocal() directly rather than through the get_db dependency this
file can otherwise cleanly override -- calling the two real dependency
functions directly exercises their real logic (hash lookup, role
resolution, has_permission, organization resolution) without that
unrelated complexity, while still never mocking auth_service or
has_permission themselves.
"""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, ApiKey, Base, Organization, Principal
from app.dependencies import get_current_organization, require_permission
from app.domain.capability import token as capability_token
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64
from app.domain.rbac.permissions import Permission, Role
from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import auth_service, capability_service, intent_service, runtime_policy_service as policy_svc, signing_key_service

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
    signing_key_service.ensure_current_key_registered(
        session, settings.evidence_signing_key_id,
        public_key_b64_from_signing_key_b64(settings.evidence_signing_key_b64),
    )
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


def _org(db, name):
    org = Organization(id=uuid.uuid4(), name=name)
    db.add(org)
    db.commit()
    return org


def _api_key(db, org_id, role=Role.GOVERNANCE_ADMIN, revoked=False):
    """Mirrors auth_service.generate_api_key()'s own real hashing --
    the raw key returned here is exactly what a real caller would send
    as `Authorization: Bearer <raw_key>`."""
    raw_key, key_hash, key_prefix = auth_service.generate_api_key()
    row = ApiKey(
        id=uuid.uuid4(), organization_id=org_id, name="test key", key_hash=key_hash,
        key_prefix=key_prefix, role=role.value,
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    )
    db.add(row)
    db.commit()
    return raw_key


def _allow_decision(db, org_id, opa_url):
    principal = Principal(id=uuid.uuid4(), name="alice", organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name="AP Invoice Agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="test policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal="alice", action="vendor_payment", resource="supplier:123"),
        conditions=ConditionSet(all=()), effect=Effect.ALLOW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    _intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action="vendor_payment", amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource="supplier:123",
    )
    assert decision.outcome == "ALLOW"
    return decision


def _resolve_organization(db, *, api_key=None, operator_key=None, organization_id_header=None):
    """Calls the real, unmodified get_current_organization dependency
    directly -- see this file's own module docstring for why direct
    calls, not a full ASGI/TestClient round trip."""
    authorization = f"Bearer {api_key}" if api_key else None
    return get_current_organization(
        x_payreality_operator_key=operator_key, x_payreality_organization_id=organization_id_header,
        authorization=authorization, db=db,
    )


def _check_permission(db, permission, *, api_key=None, operator_key=None):
    """Calls the real, unmodified require_permission(...) dependency
    closure directly (it's an async function)."""
    authorization = f"Bearer {api_key}" if api_key else None
    check = require_permission(permission)
    asyncio.run(check(x_payreality_operator_key=operator_key, authorization=authorization, db=db))


# === The real auth boundary: get_current_organization + require_permission ==


def test_valid_api_key_resolves_its_own_organization_and_passes_the_permission_check(db):
    org = _org(db, "Org A")
    key = _api_key(db, org.id)

    resolved = _resolve_organization(db, api_key=key)
    assert resolved.id == org.id

    _check_permission(db, Permission.CAPABILITY_VERIFY, api_key=key)  # must not raise


def test_revoked_api_key_fails_both_checks(db):
    org = _org(db, "Org A")
    key = _api_key(db, org.id, revoked=True)

    with pytest.raises(HTTPException) as excinfo:
        _resolve_organization(db, api_key=key)
    assert excinfo.value.status_code == 401

    with pytest.raises(HTTPException) as excinfo:
        _check_permission(db, Permission.CAPABILITY_VERIFY, api_key=key)
    assert excinfo.value.status_code == 401


def test_api_key_with_a_role_lacking_the_permission_is_denied(db):
    org = _org(db, "Org A")
    key = _api_key(db, org.id, role=Role.AUDITOR)  # Auditor holds no capability permissions

    with pytest.raises(HTTPException) as excinfo:
        _check_permission(db, Permission.CAPABILITY_VERIFY, api_key=key)
    assert excinfo.value.status_code == 403


def test_operator_key_requires_an_explicit_target_organization(db):
    org = _org(db, "Org A")
    settings.admin_api_key = "test-operator-key"
    try:
        with pytest.raises(HTTPException) as excinfo:
            _resolve_organization(db, operator_key="test-operator-key")
        assert excinfo.value.status_code == 400

        resolved = _resolve_organization(db, operator_key="test-operator-key", organization_id_header=str(org.id))
        assert resolved.id == org.id

        _check_permission(db, Permission.CAPABILITY_VERIFY, operator_key="test-operator-key")  # must not raise
    finally:
        settings.admin_api_key = None


# === The actual cross-tenant verification/consumption boundary ==============


def test_tenant_a_verifier_cannot_consume_tenant_bs_capability(db, opa_url):
    """Section 12's own primary hostile test, through the real service
    boundary: an ApiKey genuinely resolved to Org A's own organization
    (via the real, unmocked get_current_organization) presents Org B's
    real, validly-issued, validly-signed Capability. Token-hash
    knowledge alone must not be enough."""
    org_a = _org(db, "Org A")
    org_b = _org(db, "Org B")
    decision_b = _allow_decision(db, org_b.id, opa_url)
    issued_b = capability_service.issue_capability_for_decision(db, org_b.id, decision_b.id, audience="reference-pep")

    key_a = _api_key(db, org_a.id)
    resolved_org = _resolve_organization(db, api_key=key_a)
    assert resolved_org.id == org_a.id

    with pytest.raises(capability_token.CapabilityTenantMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued_b.token, "reference-pep", "vendor_payment", "supplier:123", {},
            expected_organization_id=resolved_org.id,
        )

    from app.db.models import CapabilityToken
    row = db.get(CapabilityToken, issued_b.capability_id)
    assert row.consumed_at is None, "a cross-tenant attempt must not consume the token either"


def test_correct_tenant_verifier_succeeds(db, opa_url):
    org = _org(db, "Org A")
    decision = _allow_decision(db, org.id, opa_url)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")

    key = _api_key(db, org.id)
    resolved_org = _resolve_organization(db, api_key=key)

    consumed = capability_service.verify_and_consume_capability(
        db, issued.token, "reference-pep", "vendor_payment", "supplier:123", {},
        expected_organization_id=resolved_org.id,
    )
    assert str(consumed.decision_id) == str(decision.id)


def test_operator_key_targeting_the_wrong_organization_also_fails_the_tenant_check(db, opa_url):
    """The Operator Key is not exempt from the tenant boundary -- it
    must still name a real target organisation, and that organisation
    is still checked against the token's own signed claim, same as any
    ApiKey."""
    org_a = _org(db, "Org A")
    org_b = _org(db, "Org B")
    decision_b = _allow_decision(db, org_b.id, opa_url)
    issued_b = capability_service.issue_capability_for_decision(db, org_b.id, decision_b.id, audience="reference-pep")

    settings.admin_api_key = "test-operator-key"
    try:
        resolved_org = _resolve_organization(db, operator_key="test-operator-key", organization_id_header=str(org_a.id))
        with pytest.raises(capability_token.CapabilityTenantMismatchError):
            capability_service.verify_and_consume_capability(
                db, issued_b.token, "reference-pep", "vendor_payment", "supplier:123", {},
                expected_organization_id=resolved_org.id,
            )
    finally:
        settings.admin_api_key = None


def test_wrong_audience_still_fails_alongside_tenant_scoping(db, opa_url):
    org = _org(db, "Org A")
    decision = _allow_decision(db, org.id, opa_url)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")
    key = _api_key(db, org.id)
    resolved_org = _resolve_organization(db, api_key=key)

    with pytest.raises(capability_token.CapabilityAudienceMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "a-different-audience", "vendor_payment", "supplier:123", {},
            expected_organization_id=resolved_org.id,
        )


def test_wrong_environment_still_fails_alongside_tenant_scoping(db, opa_url):
    org = _org(db, "Org A")
    decision = _allow_decision(db, org.id, opa_url)
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience="reference-pep")
    key = _api_key(db, org.id)
    resolved_org = _resolve_organization(db, api_key=key)

    with pytest.raises(capability_token.CapabilityBindingMismatchError):
        capability_service.verify_and_consume_capability(
            db, issued.token, "reference-pep", "vendor_payment", "supplier:123", {},
            environment="production", expected_organization_id=resolved_org.id,
        )
