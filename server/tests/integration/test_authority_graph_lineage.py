"""Authority Graph Lineage & Versioning (GitHub issue #5): real-
infrastructure tests (real SQLite-backed models) for approval predecessor/
supersession lineage and deterministic same-corpus version diffing.
Deliberately duplicates test_authority_graph_compilation_gate.py's own
setup helpers rather than sharing a conftest, matching this repo's
established discipline for these integration test files.
"""

import ast
import inspect
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.models import (
    AuthorityConflict,
    AuthorityCorpus,
    AuthorityGap,
    AuthorityGraphApproval,
    AuthorityPrincipal,
    AuthorityRelationship,
    Base,
    Organization,
)
from app.domain.authority_graph.diff import diff_graph_snapshots
from app.domain.decision import engine as decision_engine
from app.services import ai_authority_builder_service as authority_svc
from app.services.ai_authority_builder_service import (
    ApprovalNotFoundError,
    ConcurrentApprovalConflictError,
    NoPredecessorApprovalError,
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


@pytest.fixture()
def org(db):
    o = Organization(id=uuid.uuid4(), name="Meridian Industrial")
    db.add(o)
    db.commit()
    return o


@pytest.fixture()
def corpus(db, org):
    c = AuthorityCorpus(id=uuid.uuid4(), name="Delegation of Authority Policy", status="extracted", organization_id=org.id)
    db.add(c)
    db.commit()
    return c


def _principal(db, corpus_id, name, role=None) -> AuthorityPrincipal:
    row = AuthorityPrincipal(id=uuid.uuid4(), corpus_id=corpus_id, name=name, role=role, confidence=0.95)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _relationship(db, corpus_id, kind, from_name, to_name, status="active") -> AuthorityRelationship:
    row = AuthorityRelationship(
        id=uuid.uuid4(), corpus_id=corpus_id, kind=kind, from_principal=from_name, to_principal=to_name,
        status=status, confidence=0.9,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _conflict(db, corpus_id, description, conflict_type=None) -> AuthorityConflict:
    row = AuthorityConflict(
        id=uuid.uuid4(), corpus_id=corpus_id, description=description, confidence=0.8, conflict_type=conflict_type,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _gap(db, corpus_id, description) -> AuthorityGap:
    row = AuthorityGap(id=uuid.uuid4(), corpus_id=corpus_id, description=description, confidence=0.7)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _approve(db, corpus_id, reviewer="test-reviewer", reason=None) -> AuthorityGraphApproval:
    return authority_svc.approve_graph(db, corpus_id, reviewer=reviewer, approval_reason=reason)


# --- 1-3. Predecessor chain -------------------------------------------------


def test_first_approval_has_no_predecessor(db, corpus):
    approval = _approve(db, corpus.id)
    assert approval.predecessor_approval_id is None


def test_second_approval_points_to_first(db, corpus):
    first = _approve(db, corpus.id)
    second = _approve(db, corpus.id)
    assert second.predecessor_approval_id == first.id


def test_third_approval_points_to_second(db, corpus):
    first = _approve(db, corpus.id)
    second = _approve(db, corpus.id)
    third = _approve(db, corpus.id)
    assert second.predecessor_approval_id == first.id
    assert third.predecessor_approval_id == second.id
    assert third.version == 3


# --- 4-6. Corpus/org locality ------------------------------------------------


def test_predecessor_is_same_corpus(db, org):
    corpus_a = AuthorityCorpus(id=uuid.uuid4(), name="Corpus A", status="extracted", organization_id=org.id)
    corpus_b = AuthorityCorpus(id=uuid.uuid4(), name="Corpus B", status="extracted", organization_id=org.id)
    db.add_all([corpus_a, corpus_b])
    db.commit()

    a1 = _approve(db, corpus_a.id)
    b1 = _approve(db, corpus_b.id)
    a2 = _approve(db, corpus_a.id)

    assert a1.predecessor_approval_id is None
    assert b1.predecessor_approval_id is None
    assert a2.predecessor_approval_id == a1.id


def test_unrelated_corpus_never_becomes_predecessor(db, org):
    """Two corpora approved in an interleaved order -- corpus B's single
    approval must never be picked up as corpus A's predecessor just
    because it happened in between A's two approvals."""
    corpus_a = AuthorityCorpus(id=uuid.uuid4(), name="Corpus A", status="extracted", organization_id=org.id)
    corpus_b = AuthorityCorpus(id=uuid.uuid4(), name="Corpus B", status="extracted", organization_id=org.id)
    db.add_all([corpus_a, corpus_b])
    db.commit()

    a1 = _approve(db, corpus_a.id)
    _approve(db, corpus_b.id)
    a2 = _approve(db, corpus_a.id)

    assert a2.predecessor_approval_id == a1.id


def test_cross_org_approval_never_becomes_predecessor(db):
    org_a = Organization(id=uuid.uuid4(), name="Org A")
    org_b = Organization(id=uuid.uuid4(), name="Org B")
    db.add_all([org_a, org_b])
    db.commit()
    corpus_a = AuthorityCorpus(id=uuid.uuid4(), name="Corpus A", status="extracted", organization_id=org_a.id)
    corpus_b = AuthorityCorpus(id=uuid.uuid4(), name="Corpus B", status="extracted", organization_id=org_b.id)
    db.add_all([corpus_a, corpus_b])
    db.commit()

    _approve(db, corpus_b.id)
    a1 = _approve(db, corpus_a.id)

    assert a1.predecessor_approval_id is None


# --- 7. Supersession (reverse lookup) ---------------------------------------


def test_superseded_by_resolves_correctly(db, corpus):
    first = _approve(db, corpus.id)
    assert authority_svc.get_superseding_approval(db, first) is None

    second = _approve(db, corpus.id)
    assert authority_svc.get_superseding_approval(db, first).id == second.id
    assert authority_svc.get_superseding_approval(db, second) is None


# --- 8-18. Deterministic diff, per category ---------------------------------


def test_principal_addition_detected(db, corpus):
    _principal(db, corpus.id, "David Okonkwo")
    v1 = _approve(db, corpus.id)
    _principal(db, corpus.id, "Sarah Mokoena")
    v2 = _approve(db, corpus.id)

    diff = diff_graph_snapshots(v1.evidence_snapshot, v2.evidence_snapshot)
    assert len(diff.principals.added) == 1
    assert diff.principals.added[0]["name"] == "Sarah Mokoena"
    assert diff.principals.removed == ()
    assert diff.principals.changed == ()


def test_principal_removal_detected(db, corpus):
    _principal(db, corpus.id, "David Okonkwo")
    legacy = _principal(db, corpus.id, "Legacy Procurement Manager")
    v1 = _approve(db, corpus.id)
    db.delete(legacy)
    db.commit()
    v2 = _approve(db, corpus.id)

    diff = diff_graph_snapshots(v1.evidence_snapshot, v2.evidence_snapshot)
    assert len(diff.principals.removed) == 1
    assert diff.principals.removed[0]["name"] == "Legacy Procurement Manager"
    assert diff.principals.added == ()


def test_principal_modification_detected(db, corpus):
    """Stable identity (I/J from the pre-implementation audit): the row
    is mutated in place, not recreated, so this is genuinely a
    "changed" entry, not a remove+add pair."""
    david = _principal(db, corpus.id, "David Okonkwo", role="Finance Manager")
    v1 = _approve(db, corpus.id)
    david.role = "Senior Finance Manager"
    db.commit()
    v2 = _approve(db, corpus.id)

    diff = diff_graph_snapshots(v1.evidence_snapshot, v2.evidence_snapshot)
    assert diff.principals.added == () and diff.principals.removed == ()
    assert len(diff.principals.changed) == 1
    changed = diff.principals.changed[0]
    assert changed.id == str(david.id)
    role_change = next(f for f in changed.changed_fields if f.field == "role")
    assert role_change.before == "Finance Manager"
    assert role_change.after == "Senior Finance Manager"


def test_relationship_addition_detected(db, corpus):
    _principal(db, corpus.id, "David Okonkwo")
    _principal(db, corpus.id, "Sarah Mokoena")
    v1 = _approve(db, corpus.id)
    _relationship(db, corpus.id, "escalation", "Sarah Mokoena", "David Okonkwo")
    v2 = _approve(db, corpus.id)

    diff = diff_graph_snapshots(v1.evidence_snapshot, v2.evidence_snapshot)
    assert len(diff.relationships.added) == 1
    assert diff.relationships.added[0]["kind"] == "escalation"


def test_relationship_removal_detected(db, corpus):
    rel = _relationship(db, corpus.id, "delegation", "David Okonkwo", "AP Agent")
    v1 = _approve(db, corpus.id)
    db.delete(rel)
    db.commit()
    v2 = _approve(db, corpus.id)

    diff = diff_graph_snapshots(v1.evidence_snapshot, v2.evidence_snapshot)
    assert len(diff.relationships.removed) == 1
    assert diff.relationships.removed[0]["from_principal"] == "David Okonkwo"


def test_relationship_modification_detected(db, corpus):
    rel = _relationship(db, corpus.id, "delegation", "David Okonkwo", "AP Agent", status="proposed")
    v1 = _approve(db, corpus.id)
    rel.status = "active"
    db.commit()
    v2 = _approve(db, corpus.id)

    diff = diff_graph_snapshots(v1.evidence_snapshot, v2.evidence_snapshot)
    assert len(diff.relationships.changed) == 1
    status_change = next(f for f in diff.relationships.changed[0].changed_fields if f.field == "status")
    assert status_change.before == "proposed"
    assert status_change.after == "active"


def test_conflict_introduced(db, corpus):
    v1 = _approve(db, corpus.id)
    _conflict(db, corpus.id, "Two policies both claim authority over vendor_payment.", conflict_type="authority")
    v2 = _approve(db, corpus.id)

    diff = diff_graph_snapshots(v1.evidence_snapshot, v2.evidence_snapshot)
    assert len(diff.conflicts.added) == 1
    assert diff.conflicts.removed == ()


def test_conflict_resolved(db, corpus):
    conflict = _conflict(db, corpus.id, "Two policies both claim authority over vendor_payment.")
    v1 = _approve(db, corpus.id)
    db.delete(conflict)
    db.commit()
    v2 = _approve(db, corpus.id)

    diff = diff_graph_snapshots(v1.evidence_snapshot, v2.evidence_snapshot)
    assert len(diff.conflicts.removed) == 1
    assert diff.conflicts.added == ()


def test_gap_introduced(db, corpus):
    v1 = _approve(db, corpus.id)
    _gap(db, corpus.id, "No approver stated for purchase orders over R100,000.")
    v2 = _approve(db, corpus.id)

    diff = diff_graph_snapshots(v1.evidence_snapshot, v2.evidence_snapshot)
    assert len(diff.gaps.added) == 1


def test_gap_resolved(db, corpus):
    gap = _gap(db, corpus.id, "No approver stated for purchase orders over R100,000.")
    v1 = _approve(db, corpus.id)
    db.delete(gap)
    db.commit()
    v2 = _approve(db, corpus.id)

    diff = diff_graph_snapshots(v1.evidence_snapshot, v2.evidence_snapshot)
    assert len(diff.gaps.removed) == 1


def test_coverage_change(db, corpus):
    from app.db.models import AuthorityCorpusDocument

    v1 = _approve(db, corpus.id)
    doc = AuthorityCorpusDocument(
        id=uuid.uuid4(), corpus_id=corpus.id, filename="doa.pdf", format="pdf", content=b"text",
        clauses_analysed=4, clauses_ignored=0, tables_extracted=1, images_skipped=0,
    )
    db.add(doc)
    db.commit()
    v2 = _approve(db, corpus.id)

    diff = diff_graph_snapshots(v1.evidence_snapshot, v2.evidence_snapshot)
    assert diff.coverage.changed_fields != ()


# --- 19-21. Determinism, purity ---------------------------------------------


def test_identical_snapshots_produce_empty_diff(db, corpus):
    _principal(db, corpus.id, "David Okonkwo")
    v1 = _approve(db, corpus.id)
    v2 = _approve(db, corpus.id)  # nothing changed on the corpus in between

    diff = diff_graph_snapshots(v1.evidence_snapshot, v2.evidence_snapshot)
    assert diff.principals.added == () and diff.principals.removed == () and diff.principals.changed == ()
    assert diff.relationships.added == () and diff.relationships.removed == () and diff.relationships.changed == ()
    assert diff.conflicts.added == () and diff.conflicts.removed == () and diff.conflicts.changed == ()
    assert diff.gaps.added == () and diff.gaps.removed == () and diff.gaps.changed == ()
    assert diff.coverage.changed_fields == ()


def test_diff_deterministic(db, corpus):
    _principal(db, corpus.id, "David Okonkwo")
    v1 = _approve(db, corpus.id)
    _principal(db, corpus.id, "Sarah Mokoena")
    v2 = _approve(db, corpus.id)

    first = diff_graph_snapshots(v1.evidence_snapshot, v2.evidence_snapshot)
    second = diff_graph_snapshots(v1.evidence_snapshot, v2.evidence_snapshot)
    assert first == second


def test_diff_does_not_mutate_inputs(db, corpus):
    _principal(db, corpus.id, "David Okonkwo")
    v1 = _approve(db, corpus.id)
    _principal(db, corpus.id, "Sarah Mokoena")
    v2 = _approve(db, corpus.id)

    import copy

    before_a = copy.deepcopy(v1.evidence_snapshot)
    before_b = copy.deepcopy(v2.evidence_snapshot)
    diff_graph_snapshots(v1.evidence_snapshot, v2.evidence_snapshot)
    assert v1.evidence_snapshot == before_a
    assert v2.evidence_snapshot == before_b


def test_diff_module_has_no_db_llm_or_network_dependency():
    """Structural guarantee, matching test_authority_graph_compilation_
    gate.py's own proof for the gate: the diff module's source imports
    nothing that could reach the database, an LLM, or the network."""
    diff_module = __import__("app.domain.authority_graph.diff", fromlist=["x"])
    tree = ast.parse(inspect.getsource(diff_module))
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)
    forbidden = ("httpx", "requests", "anthropic", "openai", "azure", "boto3", "sqlalchemy", "app.db", "app.services")
    assert not any(any(f in name for f in forbidden) for name in imported_names), imported_names


# --- 24-25. Cross-corpus / cross-org diff rejection --------------------------


def test_diff_against_another_corpus_rejected(db, org):
    corpus_a = AuthorityCorpus(id=uuid.uuid4(), name="Corpus A", status="extracted", organization_id=org.id)
    corpus_b = AuthorityCorpus(id=uuid.uuid4(), name="Corpus B", status="extracted", organization_id=org.id)
    db.add_all([corpus_a, corpus_b])
    db.commit()
    a1 = _approve(db, corpus_a.id)
    b1 = _approve(db, corpus_b.id)

    with pytest.raises(ApprovalNotFoundError):
        authority_svc.diff_graph_approvals(db, corpus_a.id, a1.id, against_approval_id=b1.id)


def test_diff_against_another_organization_impossible(db):
    org_a = Organization(id=uuid.uuid4(), name="Org A")
    org_b = Organization(id=uuid.uuid4(), name="Org B")
    db.add_all([org_a, org_b])
    db.commit()
    corpus_a = AuthorityCorpus(id=uuid.uuid4(), name="Corpus A", status="extracted", organization_id=org_a.id)
    corpus_b = AuthorityCorpus(id=uuid.uuid4(), name="Corpus B", status="extracted", organization_id=org_b.id)
    db.add_all([corpus_a, corpus_b])
    db.commit()
    a1 = _approve(db, corpus_a.id)
    b1 = _approve(db, corpus_b.id)

    with pytest.raises(ApprovalNotFoundError):
        authority_svc.diff_graph_approvals(db, corpus_a.id, a1.id, against_approval_id=b1.id)


def test_diff_with_no_predecessor_and_no_explicit_against_raises(db, corpus):
    v1 = _approve(db, corpus.id)
    with pytest.raises(NoPredecessorApprovalError):
        authority_svc.diff_graph_approvals(db, corpus.id, v1.id)


def test_diff_defaults_to_immediate_predecessor(db, corpus):
    _principal(db, corpus.id, "David Okonkwo")
    v1 = _approve(db, corpus.id)
    _principal(db, corpus.id, "Sarah Mokoena")
    v2 = _approve(db, corpus.id)

    from_approval, to_approval, diff = authority_svc.diff_graph_approvals(db, corpus.id, v2.id)
    assert from_approval.id == v1.id
    assert to_approval.id == v2.id
    assert len(diff.principals.added) == 1


def test_diff_supports_an_explicit_against_approval_from_the_same_corpus(db, corpus):
    v1 = _approve(db, corpus.id)
    _principal(db, corpus.id, "Sarah Mokoena")
    v2 = _approve(db, corpus.id)
    _principal(db, corpus.id, "Priya Chandrasekaran")
    v3 = _approve(db, corpus.id)

    from_approval, to_approval, diff = authority_svc.diff_graph_approvals(
        db, corpus.id, v3.id, against_approval_id=v1.id,
    )
    assert from_approval.id == v1.id
    assert to_approval.id == v3.id
    assert len(diff.principals.added) == 2


# --- 26. RuntimePolicy compiled from graph version listing (regression) -----


def test_approving_a_new_graph_version_does_not_alter_runtime_policies_from_the_old_one(db, corpus):
    """R/S from the pre-implementation audit, re-confirmed after this
    milestone's changes: approve_graph remains purely additive."""
    from app.db.models import RuntimePolicyRecord

    v1 = _approve(db, corpus.id)
    policy = RuntimePolicyRecord(
        id=uuid.uuid4(), policy_key=uuid.uuid4(), version=1, status="draft",
        content={"name": "p"}, organization_id=corpus.organization_id, source_graph_approval_id=v1.id,
    )
    db.add(policy)
    db.commit()

    _approve(db, corpus.id)  # v2

    db.refresh(policy)
    assert policy.source_graph_approval_id == v1.id
    assert policy.status == "draft"


# --- 40. Concurrent approval race --------------------------------------------


def test_racing_approvals_are_retried_not_left_as_an_unhandled_integrity_error(db, corpus, monkeypatch):
    """Simulates the race the pre-implementation audit flagged: two
    approve_graph calls computing the same next version because neither
    has committed yet. Forces the loser's first attempt to collide with
    an already-committed row (the same effect a true concurrent commit
    would have), and proves it recovers via retry with the correct
    predecessor, rather than surfacing the DB's IntegrityError."""
    v1 = _approve(db, corpus.id)

    original_commit = db.commit
    calls = {"n": 0}

    def _commit_with_first_call_colliding():
        calls["n"] += 1
        if calls["n"] == 1:
            # Simulate a second, faster caller having already taken
            # version 2 by the time this attempt tries to commit.
            db.rollback()
            other_session_insert = AuthorityGraphApproval(
                id=uuid.uuid4(), corpus_id=corpus.id, reviewer="racing-caller", version=2,
                predecessor_approval_id=v1.id, evidence_snapshot={}, graph_hash="x",
            )
            db.add(other_session_insert)
            original_commit()
            raise IntegrityError("simulated race", params=None, orig=Exception("duplicate"))
        return original_commit()

    monkeypatch.setattr(db, "commit", _commit_with_first_call_colliding)

    result = authority_svc.approve_graph(db, corpus.id, reviewer="second-caller")
    assert result.version == 3
    assert result.predecessor_approval_id is not None


def test_approve_graph_gives_up_after_max_attempts_with_a_clean_error(db, corpus, monkeypatch):
    """Bounds the retry loop explicitly -- never an infinite loop, even
    under a pathological, permanently-racing scenario."""
    _approve(db, corpus.id)

    def _always_collide():
        raise IntegrityError("simulated permanent race", params=None, orig=Exception("duplicate"))

    monkeypatch.setattr(db, "commit", _always_collide)

    with pytest.raises(ConcurrentApprovalConflictError):
        authority_svc.approve_graph(db, corpus.id, reviewer="unlucky-caller")


# --- Approval not found / cross-corpus read guard ----------------------------


def test_get_approval_for_corpus_rejects_wrong_corpus(db, org):
    corpus_a = AuthorityCorpus(id=uuid.uuid4(), name="Corpus A", status="extracted", organization_id=org.id)
    corpus_b = AuthorityCorpus(id=uuid.uuid4(), name="Corpus B", status="extracted", organization_id=org.id)
    db.add_all([corpus_a, corpus_b])
    db.commit()
    b1 = _approve(db, corpus_b.id)

    with pytest.raises(ApprovalNotFoundError):
        authority_svc.get_approval_for_corpus(db, corpus_a.id, b1.id)


def test_get_approval_for_corpus_rejects_nonexistent_approval(db, corpus):
    with pytest.raises(ApprovalNotFoundError):
        authority_svc.get_approval_for_corpus(db, corpus.id, uuid.uuid4())


# --- Issue #5's own explicit acceptance criterion ---------------------------


def test_editing_a_live_principal_after_approval_never_alters_the_approved_snapshot(db, corpus):
    """evidence_snapshot is a genuine value copy, not a live reference --
    confirmed by actually mutating the row afterward and re-fetching the
    approval fresh from the database, not just re-reading the in-memory
    object this session already holds."""
    david = _principal(db, corpus.id, "David Okonkwo", role="Finance Manager")
    david_id = david.id
    approval = _approve(db, corpus.id)
    approval_id = approval.id

    david.role = "Chief Financial Officer"
    david.name = "David O. Okonkwo"
    db.commit()

    db.expunge_all()
    reloaded = authority_svc.get_approval_by_id(db, approval_id)
    saved_principal = next(p for p in reloaded.evidence_snapshot["principals"] if p["id"] == str(david_id))
    assert saved_principal["role"] == "Finance Manager"
    assert saved_principal["name"] == "David Okonkwo"
