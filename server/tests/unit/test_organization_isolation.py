"""Milestone 1 (Security & Authorization Hardening): the first
multi-organization isolation regression tests in this codebase. Before
this milestone, `grep -rlni "organization\\|tenant" server/tests/`
returned zero matches anywhere.

Follows this project's own established convention (test_enterprise_
system_resolution.py, test_policy_compilation_ordering.py) for testing
DB-touching service functions without a real database: a minimal fake
Session that answers scalar/scalars/get with pre-wired results, never
touching a real database. Where the property under test is "the SQL
statement itself carries an organization filter" rather than a return
value, the test asserts against the statement text directly, the same
approach test_policy_compilation_ordering.py already uses for its own
ORDER BY assertions.

Each test below constructs two organizations (ORG_A, ORG_B) and proves a
caller resolved to one cannot read or write a row that resolves to the
other -- the exact class of gap closed in this milestone's preceding
commits.
"""

import uuid

import pytest
from fastapi import HTTPException

from app.services import agent_service, evidence_service, organization_structure_service as org_svc
from app.services.evidence_service import EvidenceNotFoundError
from app.services.organization_structure_service import (
    BusinessUnitNotFoundError,
    DepartmentNotFoundError,
    TeamNotFoundError,
)

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()


class _FakeSession:
    """Never touches a real database; a fixed return value per call is
    enough, matching test_enterprise_system_resolution.py's own
    `_FakeSession` docstring reasoning."""

    def __init__(self, scalar_results=None, scalars_results=None, get_results=None):
        self._scalar_results = list(scalar_results or [])
        self._scalars_results = list(scalars_results or [])
        self._get_results = dict(get_results or {})
        self.statements = []
        self.committed = 0

    def scalar(self, stmt):
        self.statements.append(stmt)
        return self._scalar_results.pop(0) if self._scalar_results else None

    def scalars(self, stmt):
        self.statements.append(stmt)
        return self._scalars_results.pop(0) if self._scalars_results else []

    def get(self, model, id):
        return self._get_results.get(str(id))

    def commit(self):
        self.committed += 1

    def refresh(self, obj):
        pass


class _FakeEvidence:
    def __init__(self, id, organization_id):
        self.id = id
        self.organization_id = organization_id


class _FakeBusinessUnit:
    def __init__(self, id, organization_id):
        self.id = id
        self.organization_id = organization_id


class _FakeDepartment:
    def __init__(self, id, business_unit_id):
        self.id = id
        self.business_unit_id = business_unit_id


class _FakeTeam:
    def __init__(self, id, department_id):
        self.id = id
        self.department_id = department_id


class _FakeCorpus:
    def __init__(self, id, organization_id):
        self.id = id
        self.organization_id = organization_id


class _FakeAuthorityPrincipal:
    def __init__(self, id, corpus_id):
        self.id = id
        self.corpus_id = corpus_id


class _FakeAuthorityRelationship:
    def __init__(self, id, corpus_id):
        self.id = id
        self.corpus_id = corpus_id


class _FakeAuthorityQuestion:
    def __init__(self, id, corpus_id):
        self.id = id
        self.corpus_id = corpus_id


# --- Evidence -----------------------------------------------------------


def test_get_evidence_returns_none_for_a_different_organizations_record():
    evidence_id = uuid.uuid4()
    db = _FakeSession(get_results={str(evidence_id): _FakeEvidence(evidence_id, ORG_B)})
    assert evidence_service.get_evidence(db, evidence_id, ORG_A) is None


def test_get_evidence_returns_the_record_for_the_matching_organization():
    evidence_id = uuid.uuid4()
    record = _FakeEvidence(evidence_id, ORG_A)
    db = _FakeSession(get_results={str(evidence_id): record})
    assert evidence_service.get_evidence(db, evidence_id, ORG_A) is record


def test_verify_evidence_raises_not_found_for_a_different_organizations_record():
    evidence_id = uuid.uuid4()
    db = _FakeSession(get_results={str(evidence_id): _FakeEvidence(evidence_id, ORG_B)})
    with pytest.raises(EvidenceNotFoundError):
        evidence_service.verify_evidence(db, evidence_id, ORG_A)


def test_list_evidence_statement_filters_by_organization_id():
    db = _FakeSession(scalars_results=[[]])
    evidence_service.list_evidence(db, ORG_A)
    assert len(db.statements) == 1
    assert f"'{ORG_A.hex}'" in str(db.statements[0].compile(compile_kwargs={"literal_binds": True}))


# --- Organization structure (BusinessUnit / Department / Team) ----------


def test_business_unit_organization_id_resolves_the_owning_org():
    unit_id = uuid.uuid4()
    db = _FakeSession(get_results={str(unit_id): _FakeBusinessUnit(unit_id, ORG_A)})
    assert org_svc.business_unit_organization_id(db, unit_id) == ORG_A


def test_department_organization_id_walks_through_its_business_unit():
    department_id, business_unit_id = uuid.uuid4(), uuid.uuid4()
    db = _FakeSession(
        get_results={
            str(department_id): _FakeDepartment(department_id, business_unit_id),
            str(business_unit_id): _FakeBusinessUnit(business_unit_id, ORG_B),
        }
    )
    assert org_svc.department_organization_id(db, department_id) == ORG_B


def test_team_organization_id_walks_through_department_and_business_unit():
    team_id, department_id, business_unit_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db = _FakeSession(
        get_results={
            str(team_id): _FakeTeam(team_id, department_id),
            str(department_id): _FakeDepartment(department_id, business_unit_id),
            str(business_unit_id): _FakeBusinessUnit(business_unit_id, ORG_A),
        }
    )
    assert org_svc.team_organization_id(db, team_id) == ORG_A


def test_update_business_unit_rejects_a_different_organizations_unit():
    unit_id = uuid.uuid4()
    db = _FakeSession(get_results={str(unit_id): _FakeBusinessUnit(unit_id, ORG_B)})
    with pytest.raises(BusinessUnitNotFoundError):
        org_svc.update_business_unit(db, unit_id, ORG_A, "New Name")


def test_create_department_rejects_a_business_unit_from_a_different_organization():
    business_unit_id = uuid.uuid4()
    db = _FakeSession(get_results={str(business_unit_id): _FakeBusinessUnit(business_unit_id, ORG_B)})
    with pytest.raises(BusinessUnitNotFoundError):
        org_svc.create_department(db, ORG_A, business_unit_id, "Finance")


def test_update_department_rejects_a_department_from_a_different_organization():
    department_id, business_unit_id = uuid.uuid4(), uuid.uuid4()
    db = _FakeSession(
        get_results={
            str(department_id): _FakeDepartment(department_id, business_unit_id),
            str(business_unit_id): _FakeBusinessUnit(business_unit_id, ORG_B),
        }
    )
    with pytest.raises(DepartmentNotFoundError):
        org_svc.update_department(db, department_id, ORG_A, "New Name")


def test_create_team_rejects_a_department_from_a_different_organization():
    department_id, business_unit_id = uuid.uuid4(), uuid.uuid4()
    db = _FakeSession(
        get_results={
            str(department_id): _FakeDepartment(department_id, business_unit_id),
            str(business_unit_id): _FakeBusinessUnit(business_unit_id, ORG_B),
        }
    )
    with pytest.raises(DepartmentNotFoundError):
        org_svc.create_team(db, ORG_A, department_id, "Payments")


def test_update_team_rejects_a_team_from_a_different_organization():
    team_id, department_id, business_unit_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db = _FakeSession(
        get_results={
            str(team_id): _FakeTeam(team_id, department_id),
            str(department_id): _FakeDepartment(department_id, business_unit_id),
            str(business_unit_id): _FakeBusinessUnit(business_unit_id, ORG_B),
        }
    )
    with pytest.raises(TeamNotFoundError):
        org_svc.update_team(db, team_id, ORG_A, "New Name")


def test_list_departments_statement_filters_by_organization_id():
    db = _FakeSession(scalars_results=[[]])
    org_svc.list_departments(db, ORG_A)
    compiled = str(db.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert f"'{ORG_A.hex}'" in compiled


def test_list_teams_statement_filters_by_organization_id():
    db = _FakeSession(scalars_results=[[]])
    org_svc.list_teams(db, ORG_A)
    compiled = str(db.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert f"'{ORG_A.hex}'" in compiled


# --- Principals -----------------------------------------------------------


def test_create_principal_rejects_a_business_unit_from_a_different_organization():
    business_unit_id = uuid.uuid4()
    db = _FakeSession(get_results={str(business_unit_id): _FakeBusinessUnit(business_unit_id, ORG_B)})
    with pytest.raises(BusinessUnitNotFoundError):
        agent_service.create_principal(db, name="Some Agent", organization_id=ORG_A, business_unit_id=business_unit_id)


def test_list_principals_statement_filters_by_organization_id():
    db = _FakeSession(scalars_results=[[]])
    agent_service.list_principals(db, ORG_A)
    compiled = str(db.statements[0].compile(compile_kwargs={"literal_binds": True}))
    assert f"'{ORG_A.hex}'" in compiled


# --- AI Authority Builder --------------------------------------------------


def test_authorized_corpus_rejects_a_corpus_from_a_different_organization(monkeypatch):
    from app.routers import ai_authority_builder

    corpus_id = uuid.uuid4()
    monkeypatch.setattr(ai_authority_builder.svc, "get_corpus", lambda db, cid: _FakeCorpus(cid, ORG_B))

    class _Org:
        id = ORG_A

    with pytest.raises(HTTPException) as exc_info:
        ai_authority_builder._authorized_corpus(corpus_id, organization=_Org(), db=None)
    assert exc_info.value.status_code == 404


def test_authorized_corpus_accepts_a_corpus_from_the_matching_organization(monkeypatch):
    from app.routers import ai_authority_builder

    corpus_id = uuid.uuid4()
    fake_corpus = _FakeCorpus(corpus_id, ORG_A)
    monkeypatch.setattr(ai_authority_builder.svc, "get_corpus", lambda db, cid: fake_corpus)

    class _Org:
        id = ORG_A

    assert ai_authority_builder._authorized_corpus(corpus_id, organization=_Org(), db=None) is fake_corpus


# Milestone 3 (Enterprise Surface Isolation): get_principal_candidates,
# resolve_principal, resolve_relationship, activate_relationship, and
# answer_question previously had NO organization check of any kind --
# confirmed in MULTI_TENANT_ARCHITECTURE_VERIFICATION.md. Each now
# depends on a new gate (_authorized_authority_principal/
# _authorized_relationship/_authorized_question) resolving the target
# row's OWN corpus and comparing its organization_id to the caller's,
# the same "cross-organization access looks like not-found" discipline
# _authorized_corpus already established.


class _Org:
    id = ORG_A


def test_authorized_authority_principal_rejects_a_discovery_whose_corpus_is_a_different_organization():
    from app.routers import ai_authority_builder

    authority_principal_id, corpus_id = uuid.uuid4(), uuid.uuid4()
    discovery = _FakeAuthorityPrincipal(authority_principal_id, corpus_id)
    db = _FakeSession(get_results={
        str(authority_principal_id): discovery, str(corpus_id): _FakeCorpus(corpus_id, ORG_B),
    })
    with pytest.raises(HTTPException) as exc_info:
        ai_authority_builder._authorized_authority_principal(authority_principal_id, organization=_Org(), db=db)
    assert exc_info.value.status_code == 404


def test_authorized_authority_principal_accepts_a_discovery_whose_corpus_matches():
    from app.routers import ai_authority_builder

    authority_principal_id, corpus_id = uuid.uuid4(), uuid.uuid4()
    discovery = _FakeAuthorityPrincipal(authority_principal_id, corpus_id)
    db = _FakeSession(get_results={
        str(authority_principal_id): discovery, str(corpus_id): _FakeCorpus(corpus_id, ORG_A),
    })
    result = ai_authority_builder._authorized_authority_principal(authority_principal_id, organization=_Org(), db=db)
    assert result is discovery


def test_authorized_authority_principal_404s_when_the_discovery_does_not_exist():
    from app.routers import ai_authority_builder

    with pytest.raises(HTTPException) as exc_info:
        ai_authority_builder._authorized_authority_principal(uuid.uuid4(), organization=_Org(), db=_FakeSession())
    assert exc_info.value.status_code == 404


def test_authorized_relationship_rejects_a_relationship_whose_corpus_is_a_different_organization():
    from app.routers import ai_authority_builder

    relationship_id, corpus_id = uuid.uuid4(), uuid.uuid4()
    relationship = _FakeAuthorityRelationship(relationship_id, corpus_id)
    db = _FakeSession(get_results={
        str(relationship_id): relationship, str(corpus_id): _FakeCorpus(corpus_id, ORG_B),
    })
    with pytest.raises(HTTPException) as exc_info:
        ai_authority_builder._authorized_relationship(relationship_id, organization=_Org(), db=db)
    assert exc_info.value.status_code == 404


def test_authorized_relationship_accepts_a_relationship_whose_corpus_matches():
    from app.routers import ai_authority_builder

    relationship_id, corpus_id = uuid.uuid4(), uuid.uuid4()
    relationship = _FakeAuthorityRelationship(relationship_id, corpus_id)
    db = _FakeSession(get_results={
        str(relationship_id): relationship, str(corpus_id): _FakeCorpus(corpus_id, ORG_A),
    })
    assert ai_authority_builder._authorized_relationship(relationship_id, organization=_Org(), db=db) is relationship


def test_authorized_question_rejects_a_question_whose_corpus_is_a_different_organization():
    from app.routers import ai_authority_builder

    question_id, corpus_id = uuid.uuid4(), uuid.uuid4()
    question = _FakeAuthorityQuestion(question_id, corpus_id)
    db = _FakeSession(get_results={
        str(question_id): question, str(corpus_id): _FakeCorpus(corpus_id, ORG_B),
    })
    with pytest.raises(HTTPException) as exc_info:
        ai_authority_builder._authorized_question(question_id, organization=_Org(), db=db)
    assert exc_info.value.status_code == 404


def test_authorized_question_accepts_a_question_whose_corpus_matches():
    from app.routers import ai_authority_builder

    question_id, corpus_id = uuid.uuid4(), uuid.uuid4()
    question = _FakeAuthorityQuestion(question_id, corpus_id)
    db = _FakeSession(get_results={
        str(question_id): question, str(corpus_id): _FakeCorpus(corpus_id, ORG_A),
    })
    assert ai_authority_builder._authorized_question(question_id, organization=_Org(), db=db) is question


def test_approve_graph_endpoint_now_depends_on_authorized_corpus():
    """approve_graph took a corpus_id but no organization dependency at
    all -- the worst finding in MULTI_TENANT_ARCHITECTURE_VERIFICATION.md
    (a full cross-org graph snapshot plus a forged audit record). Asserts
    the fix is actually wired onto the endpoint's own signature, not just
    that _authorized_corpus itself works (already covered above)."""
    import inspect

    from app.routers import ai_authority_builder

    sig = inspect.signature(ai_authority_builder.approve_graph)
    assert sig.parameters["corpus"].default.dependency is ai_authority_builder._authorized_corpus


def test_get_principal_candidates_and_resolve_principal_endpoints_require_authorization():
    import inspect

    from app.routers import ai_authority_builder

    for fn in (ai_authority_builder.get_principal_candidates, ai_authority_builder.resolve_principal):
        sig = inspect.signature(fn)
        assert sig.parameters["_"].default.dependency is ai_authority_builder._authorized_authority_principal


def test_resolve_and_activate_relationship_endpoints_require_authorization():
    import inspect

    from app.routers import ai_authority_builder

    for fn in (ai_authority_builder.resolve_relationship, ai_authority_builder.activate_relationship):
        sig = inspect.signature(fn)
        assert sig.parameters["_"].default.dependency is ai_authority_builder._authorized_relationship


def test_answer_question_endpoint_requires_authorization():
    import inspect

    from app.routers import ai_authority_builder

    sig = inspect.signature(ai_authority_builder.answer_question)
    assert sig.parameters["_"].default.dependency is ai_authority_builder._authorized_question
