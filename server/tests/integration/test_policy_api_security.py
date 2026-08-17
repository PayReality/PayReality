"""Milestone 12 (MILESTONE_12_POLICY_API_SECURITY_SUMMARY.md): adversarial
regression tests for the policy API authorization boundary Milestone 11's
sweep found broken -- GET /v1/policies, /v1/policies/documents, and
/v1/policies/authorities had zero authentication and no organisation
scoping at all, confirmed live-exploitable in production. Same
real-infrastructure discipline as every prior milestone's suite: a real
ephemeral OPA server, a real SQLite-backed database running the actual
production models.

Also proves, honestly rather than by omission, the one real residual
limitation this milestone's fix cannot close: `documents` has no
organization_id column at all (it predates multi-tenancy), so
list_documents is authentication- and permission-gated but not, and
cannot yet be, per-organisation isolated -- see test_list_documents_
has_no_per_organization_isolation_a_known_limitation below.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import (
    Agent,
    Authority,
    Base,
    Document,
    Organization,
    Principal,
    User,
    UserSession,
)
from app.dependencies import require_permission
from app.domain.decision import engine as decision_engine
from app.domain.rbac.permissions import Permission
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.services import document_service, policy_service, review_service
from app.services import runtime_policy_service as svc

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


def _org_with_agent(db, name="Org A"):
    org = Organization(id=uuid.uuid4(), name=name)
    db.add(org)
    db.flush()
    principal = Principal(id=uuid.uuid4(), name=f"alice-{name}", organization_id=org.id)
    db.add(principal)
    db.flush()
    agent = Agent(id=uuid.uuid4(), name=f"agent-{name}", acting_for_principal_id=principal.id, status="active")
    db.add(agent)
    db.commit()
    return org, principal, agent


def _deploy_policy(db, org_id, opa_url, threshold=50000) -> uuid.UUID:
    policy = RuntimePolicy(
        id=str(uuid.uuid4()),
        name="vendor_payment policy",
        version=1,
        status=PolicyStatus.DRAFT,
        scope=Scope(principal="alice", action="vendor_payment"),
        conditions=ConditionSet(all=(Condition(field="amount", operator=Operator.LTE, value=threshold),)),
        effect=Effect.ALLOW,
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )
    row = svc.create_policy(db, policy, org_id)
    svc.submit_for_review(db, row.policy_key, org_id)
    svc.approve(db, row.policy_key, org_id, approver="test-suite")
    result = svc.compile_policy(db, row.policy_key, org_id)
    assert result.ok, f"compile failed: {result.diagnostics}"
    svc.deploy_policy(db, row.policy_key, org_id, opa_url=opa_url)
    return row.policy_key


def _user_and_session(db, org_id, role: str):
    user = User(
        id=uuid.uuid4(), organization_id=org_id, email=f"{role}-{uuid.uuid4().hex[:6]}@example.com",
        name=role.title(), password_hash="x", role=role,
    )
    db.add(user)
    db.flush()
    session = UserSession(id=uuid.uuid4(), user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
    db.add(session)
    db.flush()
    return user, session


# =========================================================================
# A/B/C: unauthenticated fails
# =========================================================================


async def test_a_unauthenticated_list_policies_returns_401(db):
    checker = require_permission(Permission.RUNTIME_POLICY_VIEW)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=None, db=db)
    assert exc.value.status_code == 401


async def test_b_unauthenticated_list_documents_returns_401(db):
    checker = require_permission(Permission.AUDIT_EXPORT)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=None, db=db)
    assert exc.value.status_code == 401


async def test_c_unauthenticated_list_authorities_returns_401(db):
    checker = require_permission(Permission.AUTHORITY_REVIEW)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=None, db=db)
    assert exc.value.status_code == 401


# =========================================================================
# I: insufficient permission fails
# =========================================================================


async def test_i_list_policies_denied_without_runtime_policy_view(db, opa_url):
    """REVIEWER lacks RUNTIME_POLICY_VIEW (domain/rbac/permissions.py)."""
    org, _, _ = _org_with_agent(db, "Org A")
    _, session = _user_and_session(db, org.id, "reviewer")
    checker = require_permission(Permission.RUNTIME_POLICY_VIEW)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)
    assert exc.value.status_code == 403


async def test_i_list_documents_denied_without_audit_export(db):
    """AGENT_ADMIN lacks AUDIT_EXPORT (Owner-only permission)."""
    org, _, _ = _org_with_agent(db, "Org A")
    _, session = _user_and_session(db, org.id, "agent_admin")
    checker = require_permission(Permission.AUDIT_EXPORT)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)
    assert exc.value.status_code == 403


async def test_i_list_authorities_denied_without_authority_review(db):
    """AUDITOR has RUNTIME_POLICY_VIEW/EVIDENCE_VIEW/DECISIONS_VIEW/AGENT_VIEW/
    ASSURANCE_VIEW but not AUTHORITY_REVIEW."""
    org, _, _ = _org_with_agent(db, "Org A")
    _, session = _user_and_session(db, org.id, "auditor")
    checker = require_permission(Permission.AUTHORITY_REVIEW)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)
    assert exc.value.status_code == 403


# =========================================================================
# D/E/F: policy listing organisation isolation
# =========================================================================


def test_def_org_a_sees_only_its_own_policies_never_org_bs(db, opa_url):
    org_a, _, _ = _org_with_agent(db, "Org A")
    org_b, _, _ = _org_with_agent(db, "Org B")
    _deploy_policy(db, org_a.id, opa_url, threshold=50000)
    _deploy_policy(db, org_b.id, opa_url, threshold=75000)

    policies_a = policy_service.list_policies(db, org_a.id)
    policies_b = policy_service.list_policies(db, org_b.id)

    assert len(policies_a) == 1
    assert len(policies_b) == 1
    assert policies_a[0].id != policies_b[0].id
    assert policies_a[0].organization_id == org_a.id
    assert policies_b[0].organization_id == org_b.id
    # F: org A's result set never contains org B's real, known policy UUID,
    # even though both exist in the same database at the same time.
    assert policies_b[0].id not in {p.id for p in policies_a}
    assert policies_a[0].id not in {p.id for p in policies_b}


# =========================================================================
# G: policy documents -- honest limitation, not a false guarantee
# =========================================================================


def test_g_list_documents_has_no_per_organization_isolation_a_known_limitation(db):
    """`documents` has no organization_id column (it predates
    multi-tenancy) -- there is no ownership chain to scope by without a
    schema change, out of this milestone's scope. This test documents
    that limitation explicitly, in code, rather than silently omitting
    it: an authenticated, AUDIT_EXPORT-permitted caller sees ALL
    documents regardless of which organisation (if any) is later found
    to be associated with them via an Authority. The real security fix
    here is authentication + the most restrictive existing permission,
    not organisation isolation, which is structurally impossible today."""
    doc = Document(id=uuid.uuid4(), name="legacy.pdf", content=b"x", status="extracted")
    db.add(doc)
    db.commit()

    documents = document_service.list_documents(db)
    assert any(d.id == doc.id for d in documents), (
        "confirms the real, disclosed limitation: list_documents cannot "
        "be organisation-scoped, so it is gated by permission alone"
    )


def test_g_second_document_relationship_path_has_the_same_limitation(db):
    """Milestone 13 (MILESTONE_13_LEGACY_DOCUMENT_TENANCY_SUMMARY.md)'s
    forensic audit found a second, independent nullable FK to
    documents.id -- Principal.source_document_id (models.py, present
    since the initial migration) -- that Milestone 12's own audit missed
    (it only traced Authority.document_id). No code anywhere ever sets
    this column (confirmed: zero `Document(...)` constructions exist in
    application code at all), so it poses no live risk today, but any
    future schema decision for `documents` must account for BOTH paths,
    not just the one through Authority. This test proves the same
    disclosed limitation holds via this second path too: a document
    reachable only through a specific organisation's Principal is still
    visible to every other organisation via the unscoped list."""
    org, principal, _ = _org_with_agent(db, "Org A")
    doc = Document(id=uuid.uuid4(), name="cited-by-principal.pdf", content=b"x", status="extracted")
    db.add(doc)
    db.flush()
    principal.source_document_id = doc.id
    db.commit()

    documents = document_service.list_documents(db)
    assert any(d.id == doc.id for d in documents), (
        "the same structural limitation applies regardless of which FK "
        "path a document is reachable through"
    )


# =========================================================================
# H: policy authorities organisation isolation
# =========================================================================


def _document(db):
    """ck_authorities_has_a_source requires document_id or corpus_id --
    Document itself has no organisation concept (see test_g above), so
    any real or fake document_id satisfies the constraint identically;
    which one is used has no bearing on the org-isolation this test is
    actually about."""
    doc = Document(id=uuid.uuid4(), name="source.pdf", content=b"x", status="extracted")
    db.add(doc)
    db.flush()
    return doc


def test_h_org_a_cannot_see_org_bs_authorities(db):
    org_a, principal_a, _ = _org_with_agent(db, "Org A")
    org_b, principal_b, _ = _org_with_agent(db, "Org B")
    doc = _document(db)

    authority_a = Authority(
        id=uuid.uuid4(), document_id=doc.id, principal_id=principal_a.id, scope="vendor_payment",
        limit_amount=50000, currency="USD", status="pending_review",
    )
    authority_b = Authority(
        id=uuid.uuid4(), document_id=doc.id, principal_id=principal_b.id, scope="vendor_payment",
        limit_amount=75000, currency="USD", status="pending_review",
    )
    db.add_all([authority_a, authority_b])
    db.commit()

    items_a = review_service.list_authorities_for_review(db, org_a.id)
    items_b = review_service.list_authorities_for_review(db, org_b.id)

    assert [i.authority.id for i in items_a] == [authority_a.id]
    assert [i.authority.id for i in items_b] == [authority_b.id]


def test_h_duplicate_flag_still_works_within_the_same_organization(db):
    """`_compute_flags`'s duplicate_of match is keyed on principal_id
    equality, which (a real Principal always belonging to exactly one
    organisation) can never itself coincide across two different
    organisations -- so the "all approved authorities" cross-check
    review_service.list_authorities_for_review now scopes by
    organisation_id was never exploitable as a direct cross-org id leak
    the way a first read of "system-wide" might suggest. It was scoped
    anyway, for the same reason every other Authority query in this
    function now is: a query touching this table should never scan
    another organisation's rows at all, leak or not. This test proves
    that tightening didn't silently break the real, intra-organisation
    duplicate detection spec 12.4 Stage 4 actually depends on."""
    org_a, principal_a, _ = _org_with_agent(db, "Org A")
    doc = _document(db)

    approved = Authority(
        id=uuid.uuid4(), document_id=doc.id, principal_id=principal_a.id, scope="vendor_payment",
        limit_amount=50000, currency="USD", status="approved",
    )
    pending_duplicate = Authority(
        id=uuid.uuid4(), document_id=doc.id, principal_id=principal_a.id, scope="vendor_payment",
        limit_amount=50000, currency="USD", status="pending_review",
    )
    db.add_all([approved, pending_duplicate])
    db.commit()

    items = review_service.list_authorities_for_review(db, org_a.id)
    pending_item = next(i for i in items if i.authority.id == pending_duplicate.id)
    assert f"duplicate_of:{approved.id}" in pending_item.validation_flags
