"""Post-audit implementation, Priority 1: the organisation kill-switch
gap. Before this fix, a deactivated Organization was already blocked
from Capability issuance/consumption (capability_service.
TenantNotActiveError, Phase 6.1) but nothing stopped it from
authenticating, submitting Intents (Agent-direct or IntegrationIdentity-
mediated), or receiving real ALLOW/DENY/HUMAN_REVIEW decisions in the
meantime.

The fix lives at the narrowest shared boundary each runtime path
actually has:

  - app.dependencies.get_current_organization (nearly every
    organisation-scoped session/API-key/operator-key route: RuntimePolicy
    creation, Agent registration, capability issuance/consumption,
    resolve_decision, ...).
  - intent_service.submit_intent (the Agent-direct runtime path, which
    authenticates via Certificate signature and never goes through
    get_current_organization at all).
  - integration_runtime_service.submit_attested_intent (the
    IntegrationIdentity-mediated runtime path, same reason).

Real SQLite + real ephemeral OPA throughout, the same established
convention as test_reference_enforcement_demonstration.py and
test_tenant_scoped_verification.py, whose fixtures this file mirrors
directly: the real, unmodified get_current_organization/require_permission
dependency functions are called directly (this repository has no
FastAPI TestClient convention), and the real submit_intent/
submit_attested_intent/capability_service functions are exercised
end to end, not re-implemented.

Administrative recovery (routers/organization_lifecycle.py) is
deliberately untouched by this fix -- it resolves an arbitrary
organization directly via organization_lifecycle_service.get_organization,
never through get_current_organization -- and this file proves that
directly too.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import Agent, ApiKey, Base, CapabilityToken, Intent, Organization, Principal, User, UserSession
from app.dependencies import get_current_organization, require_permission
from app.domain.decision import engine as decision_engine
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64
from app.domain.rbac.permissions import Permission, Role
from app.domain.runtime_policy.conditions import ConditionSet
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import (
    auth_service,
    capability_service,
    enforcement_binding_service as binding_svc,
    integration_contract_service as contract_svc,
    integration_identity_service as identity_svc,
    integration_runtime_service as runtime_svc,
    intent_service,
    organization_lifecycle_service as lifecycle_svc,
    runtime_policy_service as policy_svc,
    signing_key_service,
)

settings.evidence_signing_key_b64 = "1xq9xsxyr3A1bfh7IJGO3Rd32FvkAhr5AnlnjWZlbuI="
decision_engine.evaluate.__defaults__ = (5000,)

ACTION = "vendor_payment"
RESOURCE = "supplier:123"
SOURCE_OPERATION = "SubmitVendorPayment"
AUDIENCE = "reference-pep"


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
    if "opa_url" not in request.fixturenames:
        yield
        return
    opa_url = request.getfixturevalue("opa_url")
    original = settings.opa_url
    settings.opa_url = opa_url
    try:
        yield
    finally:
        settings.opa_url = original


def _org(db, name="Org A", status="active"):
    org = Organization(id=uuid.uuid4(), name=name, status=status)
    db.add(org)
    db.commit()
    return org


def _api_key(db, org_id, role=Role.GOVERNANCE_ADMIN):
    raw_key, key_hash, key_prefix = auth_service.generate_api_key()
    row = ApiKey(id=uuid.uuid4(), organization_id=org_id, name="test key", key_hash=key_hash, key_prefix=key_prefix, role=role.value)
    db.add(row)
    db.commit()
    return raw_key


def _user_and_session(db, org_id, role="governance_admin"):
    """flush (not commit), matching test_decision_security_boundary.py's
    own fix for the SQLite timezone-stripping issue: commit's
    expire_on_commit=True would force a lossy reload of `expires_at`
    that loses the timezone SQLite never round-trips, breaking
    auth_service's own aware-datetime comparison (a SQLite-only
    artifact, not a real bug)."""
    user = User(id=uuid.uuid4(), organization_id=org_id, email=f"{role}@example.com", name=role.title(), password_hash="x", role=role)
    db.add(user)
    db.flush()
    session = UserSession(id=uuid.uuid4(), user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    db.add(session)
    db.flush()
    return user, session


def _resolve_organization(db, *, api_key=None, session_id=None, operator_key=None, organization_id_header=None):
    """Calls the real, unmodified get_current_organization dependency
    directly -- the exact function every organisation-scoped router
    already depends on."""
    token = api_key or (str(session_id) if session_id else None)
    authorization = f"Bearer {token}" if token else None
    return get_current_organization(
        x_payreality_operator_key=operator_key, x_payreality_organization_id=organization_id_header,
        authorization=authorization, db=db,
    )


def _check_permission(db, permission, *, api_key=None):
    authorization = f"Bearer {api_key}" if api_key else None
    check = require_permission(permission)
    asyncio.run(check(x_payreality_operator_key=None, authorization=authorization, db=db))


def _deploy_allow_policy(db, org_id, opa_url, principal="alice", action=ACTION, resource=RESOURCE):
    policy = RuntimePolicy(
        id=str(uuid.uuid4()), name="test allow policy", version=1, status=PolicyStatus.DRAFT,
        scope=Scope(principal=principal, action=action, resource=resource),
        conditions=ConditionSet(all=()), effect=Effect.ALLOW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = policy_svc.create_policy(db, policy, org_id)
    policy_svc.submit_for_review(db, row.policy_key, org_id)
    policy_svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = policy_svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    policy_svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)


def _agent(db, org_id, name="alice"):
    principal = Principal(id=uuid.uuid4(), name=name, organization_id=org_id)
    db.add(principal)
    db.commit()
    agent = Agent(id=uuid.uuid4(), name=f"{name} agent", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    return principal, agent


def _integration_scenario(db, org_id, opa_url):
    """Mirrors test_reference_enforcement_demonstration.py's own
    _scenario helper, an ALLOW-outcome variant (that file's own
    HUMAN_REVIEW scenario isn't needed for this file's purpose)."""
    identity, _cert = identity_svc.register_integration_identity(db, org_id, "Reference Adapter", "ed25519:base64:AAAA")
    identity = identity_svc.activate_integration_identity(db, identity.id, org_id)
    integration = contract_svc.create_integration(db, org_id, "Reference System")
    contract_version = contract_svc.create_contract_version(
        db, integration.id, org_id, SOURCE_OPERATION, ACTION,
        resource_path="supplier.id", amount_path=None, currency_path=None,
        fact_subject_path=None, context_bindings={},
    )
    contract_version = contract_svc.validate_contract_version(db, contract_version.id, org_id)
    contract_version = contract_svc.approve_contract_version(db, contract_version.id, org_id, approver="governance-admin@example.com")

    _principal, agent = _agent(db, org_id, name="FinanceAgent01")
    binding = binding_svc.create_draft_binding(db, org_id, identity.id, contract_version.id, "demo", agent_ids=[agent.id])
    binding = binding_svc.activate_binding(db, binding.id, org_id)

    _deploy_allow_policy(db, org_id, opa_url, principal="FinanceAgent01")
    return identity, binding, agent


# === A. get_current_organization: the shared authentication boundary ========


def test_active_organization_resolves_normally_via_api_key(db):
    org = _org(db, status="active")
    key = _api_key(db, org.id)
    resolved = _resolve_organization(db, api_key=key)
    assert resolved.id == org.id
    _check_permission(db, Permission.CAPABILITY_VERIFY, api_key=key)  # must not raise


@pytest.mark.parametrize("status", ["deactivated", "archived"])
def test_non_active_organization_is_rejected_via_api_key(db, status):
    org = _org(db, status=status)
    key = _api_key(db, org.id)
    with pytest.raises(HTTPException) as excinfo:
        _resolve_organization(db, api_key=key)
    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == "organization_not_active"


def test_non_active_organization_is_rejected_via_session_token(db):
    org = _org(db, status="deactivated")
    _user, session = _user_and_session(db, org.id)
    with pytest.raises(HTTPException) as excinfo:
        _resolve_organization(db, session_id=session.id)
    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == "organization_not_active"


def test_non_active_organization_is_rejected_via_operator_key_with_explicit_org_header(db):
    """The operator key names an arbitrary organisation explicitly via
    X-PayReality-Organization-Id -- resolved through this same shared
    dependency for ordinary org-scoped business routes (RuntimePolicy
    create, Agent registration, ...), which must reject a non-active
    target the same as a session/API-key caller would. This is distinct
    from routers/organization_lifecycle.py's own recovery endpoints,
    which never call get_current_organization at all (see section D)."""
    org = _org(db, status="deactivated")
    settings.admin_api_key = "test-operator-key"
    try:
        with pytest.raises(HTTPException) as excinfo:
            _resolve_organization(db, operator_key="test-operator-key", organization_id_header=str(org.id))
        assert excinfo.value.status_code == 403
        assert excinfo.value.detail == "organization_not_active"
    finally:
        settings.admin_api_key = None


def test_active_organization_is_unaffected_via_operator_key(db):
    org = _org(db, status="active")
    settings.admin_api_key = "test-operator-key"
    try:
        resolved = _resolve_organization(db, operator_key="test-operator-key", organization_id_header=str(org.id))
        assert resolved.id == org.id
    finally:
        settings.admin_api_key = None


# === B. Agent-direct Intent submission =======================================


def test_active_organization_agent_direct_intent_submission_still_succeeds(db, opa_url):
    org = _org(db, status="active")
    _principal, agent = _agent(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)
    _intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action=ACTION, amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource=RESOURCE,
    )
    assert decision.outcome == "ALLOW"


@pytest.mark.parametrize("status", ["deactivated", "archived"])
def test_non_active_organization_agent_direct_intent_submission_is_rejected(db, opa_url, status):
    org = _org(db, status="active")  # deploy the policy while still active
    _principal, agent = _agent(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)
    org.status = status
    db.commit()

    with pytest.raises(intent_service.OrganizationNotActiveError):
        intent_service.submit_intent(
            db, agent=agent, action=ACTION, amount=None, currency=None, counterparty=None,
            context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
            resource=RESOURCE,
        )

    # No Intent row was created at all -- the same "reject before any
    # row exists" precedent AgentRevokedError/AgentRetiredError already
    # hold themselves to.
    rows = db.scalars(select(Intent).where(Intent.agent_id == agent.id)).all()
    assert rows == []


# === C. IntegrationIdentity-mediated Intent submission =======================


def test_active_organization_integration_identity_mediated_submission_still_succeeds(db, opa_url):
    org = _org(db, status="active")
    identity, binding, agent = _integration_scenario(db, org.id, opa_url)
    _intent, decision, _evidence = runtime_svc.submit_attested_intent(
        db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
        source_operation=SOURCE_OPERATION, action=ACTION, resource=RESOURCE,
        amount=None, currency=None, counterparty=None, context={}, requested_at=datetime.now(timezone.utc),
        nonce=uuid.uuid4().hex, correlation_id=None, external_operation_id=uuid.uuid4().hex,
    )
    assert decision.outcome == "ALLOW"


def test_deactivated_organization_integration_identity_mediated_submission_is_rejected(db, opa_url):
    org = _org(db, status="active")  # set up the scenario while still active
    identity, binding, agent = _integration_scenario(db, org.id, opa_url)
    org.status = "deactivated"
    db.commit()

    with pytest.raises(runtime_svc.IntegrationRejectionError) as excinfo:
        runtime_svc.submit_attested_intent(
            db, identity, enforcement_binding_id=binding.id, origin_agent_id=agent.id,
            source_operation=SOURCE_OPERATION, action=ACTION, resource=RESOURCE,
            amount=None, currency=None, counterparty=None, context={}, requested_at=datetime.now(timezone.utc),
            nonce=uuid.uuid4().hex, correlation_id=None, external_operation_id=uuid.uuid4().hex,
        )
    assert excinfo.value.reason.startswith("organization_not_active")

    rows = db.scalars(select(Intent).where(Intent.agent_id == agent.id)).all()
    assert rows == []


# === D. Capability issuance/consumption: pre-existing defence-in-depth ======
# (capability_service.py's own _check_organization_active/TenantNotActiveError,
# Phase 6.1, is untouched by this fix -- these two tests are a regression
# proof that it still fires, not a new mechanism.)


def test_deactivated_organization_capability_issuance_is_still_blocked(db, opa_url):
    org = _org(db, status="active")
    _principal, agent = _agent(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)
    _intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action=ACTION, amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource=RESOURCE,
    )
    assert decision.outcome == "ALLOW"

    org.status = "deactivated"
    db.commit()

    with pytest.raises(capability_service.TenantNotActiveError):
        capability_service.issue_capability_for_decision(db, org.id, decision.id, audience=AUDIENCE)


def test_deactivated_organization_capability_consumption_is_still_blocked(db, opa_url):
    org = _org(db, status="active")
    _principal, agent = _agent(db, org.id)
    _deploy_allow_policy(db, org.id, opa_url)
    _intent, decision, _evidence = intent_service.submit_intent(
        db, agent=agent, action=ACTION, amount=None, currency=None, counterparty=None,
        context={}, requested_at=datetime.now(timezone.utc), nonce=uuid.uuid4().hex, correlation_id=None,
        resource=RESOURCE,
    )
    issued = capability_service.issue_capability_for_decision(db, org.id, decision.id, audience=AUDIENCE)

    org.status = "deactivated"
    db.commit()

    with pytest.raises(capability_service.TenantNotActiveError):
        capability_service.verify_and_consume_capability(
            db, issued.token, AUDIENCE, ACTION, RESOURCE, {},
        )

    row = db.get(CapabilityToken, issued.capability_id)
    assert row.consumed_at is None, "a rejected consumption attempt must not mark the token consumed"


# === E. Human resolution: blocked at the same shared dependency ============


def test_deactivated_organization_blocks_the_route_a_human_resolution_would_use(db):
    """resolution_service.resolve_decision itself takes an already-
    resolved organization_id and has no status check of its own -- by
    design, so the invariant lives in exactly one place
    (get_current_organization) rather than being re-implemented in every
    service resolve_decision's own router also depends on. Proving the
    dependency rejects the caller before the route body would ever run
    is the correct, honest way to test this given that architecture."""
    org = _org(db, status="deactivated")
    _user, session = _user_and_session(db, org.id, role="governance_admin")
    with pytest.raises(HTTPException) as excinfo:
        _resolve_organization(db, session_id=session.id)
    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == "organization_not_active"


# === F. Platform-administrator recovery is unaffected ========================


def test_platform_administrator_can_still_inspect_and_reactivate_a_deactivated_organization(db):
    """routers/organization_lifecycle.py resolves an arbitrary
    organization directly via organization_lifecycle_service.
    get_organization, never through get_current_organization -- this
    fix must not, and does not, block that path."""
    org = _org(db, status="active")
    lifecycle_svc.deactivate_organization(db, org.id, actor="ops@example.com")

    fetched = lifecycle_svc.get_organization(db, org.id)
    assert fetched.status == "deactivated"

    reactivated = lifecycle_svc.reactivate_organization(db, org.id)
    assert reactivated.status == "active"


def test_platform_administrator_can_still_archive_a_deactivated_organization(db):
    org = _org(db, status="active")
    lifecycle_svc.deactivate_organization(db, org.id)
    archived = lifecycle_svc.archive_organization(db, org.id, actor="ops@example.com")
    assert archived.status == "archived"

    # And, after reactivation is no longer possible (archived is
    # terminal), the organisation can still be inspected.
    fetched = lifecycle_svc.get_organization(db, org.id)
    assert fetched.status == "archived"
