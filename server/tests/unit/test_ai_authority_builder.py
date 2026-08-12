"""Unit tests for the AI Authority Builder's pure, DB-free core:
build_corpus_text() and the fake provider's structural guarantees. The
DB-dependent parts (corpus/document storage, extraction orchestration,
per-category listing) genuinely require a live database session and are
verified against the real deployed Postgres instance instead (see
AI_AUTHORITY_BUILDER_ARCHITECTURE.md), the same split every other
service test file in this platform already established."""

from app.db.models import AuthorityCorpusDocument
from app.domain.ai_authority_builder.fake_provider import FakeAuthorityGraphExtractionProvider
from app.domain.ai_authority_builder.provider import (
    AuthorityGraph,
    CandidateConflict,
    CandidateGap,
    CandidateOperation,
    CandidatePrincipal,
    CandidateQuestion,
    CandidateRelationship,
    CandidateResource,
)
from app.services.ai_authority_builder_service import (
    _reviewer_recommendation,
    build_corpus_text,
    detect_circular_delegations,
)


def _doc(filename, format, content):
    return AuthorityCorpusDocument(filename=filename, format=format, content=content)


def test_build_corpus_text_wraps_each_file_with_its_own_header():
    docs = [_doc("memo.txt", "text", b"The Controller may approve up to $50,000.")]
    text = build_corpus_text(docs)
    assert "=== FILE: memo.txt ===" in text
    assert "$50,000" in text


def test_build_corpus_text_treats_multiple_files_as_one_corpus():
    """AI_AUTHORITY_BUILDER_ARCHITECTURE.md: "never analyse documents
    independently." The concatenated text must contain both files'
    content in one string, so a single extraction call sees both."""
    docs = [
        _doc("doa.txt", "text", b"The Regional Controller may approve vendor payments up to $50,000."),
        _doc("approval_matrix.csv", "csv", b"role,limit\nRegional Controller,75000\n"),
    ]
    text = build_corpus_text(docs)
    assert "=== FILE: doa.txt ===" in text
    assert "=== FILE: approval_matrix.csv ===" in text
    assert "$50,000" in text
    assert "75000" in text
    assert text.index("doa.txt") < text.index("approval_matrix.csv")


def test_build_corpus_text_empty_list_is_empty_string():
    assert build_corpus_text([]) == ""


def test_fake_provider_returns_a_populated_graph_with_citations():
    graph = FakeAuthorityGraphExtractionProvider().extract("irrelevant text")
    assert len(graph.policies) == 1
    assert len(graph.principals) == 1
    assert len(graph.resources) == 1
    assert len(graph.operations) == 1
    assert len(graph.relationships) == 1
    assert len(graph.gaps) == 1
    assert len(graph.questions) == 1
    for p in graph.principals:
        assert p.source_excerpt
        assert p.source_location
        assert 0.0 <= p.confidence <= 1.0


def test_fake_provider_accepts_a_custom_graph():
    custom = AuthorityGraph(
        principals=(
            CandidatePrincipal(name="CFO", confidence=0.5, source_excerpt="e", source_location="page 1"),
        ),
        resources=(
            CandidateResource(name="Invoice", confidence=0.5, source_excerpt="e", source_location="page 1"),
        ),
        operations=(
            CandidateOperation(name="Approve", confidence=0.5, source_excerpt="e", source_location="page 1"),
        ),
        relationships=(
            CandidateRelationship(
                kind="escalation", from_principal="Manager", to_principal="CFO",
                confidence=0.5, source_excerpt="e", source_location="page 1",
            ),
        ),
        conflicts=(CandidateConflict(description="conflict", confidence=0.5),),
        gaps=(CandidateGap(description="gap", confidence=0.5),),
        questions=(CandidateQuestion(question="Who approves this?"),),
    )
    graph = FakeAuthorityGraphExtractionProvider(custom).extract("text")
    assert graph == custom


def test_authority_graph_has_no_rego_or_deploy_field_anywhere():
    """Structural check backing AI_AUTHORITY_BUILDER_ARCHITECTURE.md's
    "the AI can never deploy, never generate Rego": none of the eight
    category dataclasses have a field for either, across the whole
    graph, not just the Policies category."""
    for cls in (
        AuthorityGraph,
        CandidatePrincipal,
        CandidateResource,
        CandidateOperation,
        CandidateRelationship,
        CandidateConflict,
        CandidateGap,
        CandidateQuestion,
    ):
        field_names = cls.__dataclass_fields__.keys()
        assert not any(
            "rego" in f.lower() or "deploy" in f.lower() or "activate" in f.lower() for f in field_names
        ), f"{cls.__name__} has a field suggesting Rego or deployment"


def test_relationship_kind_is_constrained_to_three_values_in_the_fake_default():
    graph = FakeAuthorityGraphExtractionProvider().extract("text")
    for rel in graph.relationships:
        assert rel.kind in ("delegation", "escalation", "inheritance")


# --- Phase 3: Conflict Workspace, deterministic detection ---------------


def _delegation(a, b):
    return CandidateRelationship(
        kind="delegation", from_principal=a, to_principal=b, confidence=0.9,
        source_excerpt="e", source_location="l",
    )


def test_detect_circular_delegations_finds_a_three_hop_cycle():
    graph = AuthorityGraph(relationships=(_delegation("A", "B"), _delegation("B", "C"), _delegation("C", "A")))
    conflicts = detect_circular_delegations(graph)
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "circular_delegation"
    assert conflicts[0].confidence == 1.0
    assert "a -> b -> c -> a" in conflicts[0].description.lower()


def test_detect_circular_delegations_finds_nothing_in_a_normal_hierarchy():
    graph = AuthorityGraph(relationships=(_delegation("CFO", "Treasury Head"), _delegation("Treasury Head", "Treasury Manager")))
    assert detect_circular_delegations(graph) == []


def test_detect_circular_delegations_ignores_escalation_edges():
    """An escalation pointing back up a delegation chain is normal
    hierarchy, not a circular delegation -- only `delegation`-kind edges
    are considered."""
    graph = AuthorityGraph(
        relationships=(
            _delegation("CFO", "Treasury Head"),
            CandidateRelationship(
                kind="escalation", from_principal="Treasury Head", to_principal="CFO",
                confidence=0.9, source_excerpt="e", source_location="l",
            ),
        )
    )
    assert detect_circular_delegations(graph) == []


def test_detect_circular_delegations_deduplicates_the_same_cycle():
    """Two delegation edges that form one cycle produce exactly one
    conflict, not one per starting node walked."""
    graph = AuthorityGraph(relationships=(_delegation("A", "B"), _delegation("B", "A")))
    assert len(detect_circular_delegations(graph)) == 1


def test_reviewer_recommendation_always_recommends_human_review():
    """This platform never auto-resolves a conflict -- every
    recommendation must contain "Human Review", regardless of type or
    confidence; only the wording varies."""
    for conflict_type in (None, "authority", "threshold", "role", "policy", "delegation", "circular_delegation"):
        for confidence in (0.5, 0.95):
            assert "Human Review" in _reviewer_recommendation(conflict_type, confidence)


def test_reviewer_recommendation_flags_circular_delegation_distinctly():
    assert _reviewer_recommendation("circular_delegation", 0.99) == "Human Review Required -- Circular Delegation"


def test_reviewer_recommendation_flags_low_confidence_distinctly():
    assert "Low Confidence" in _reviewer_recommendation("threshold", 0.5)
    assert "Low Confidence" not in _reviewer_recommendation("threshold", 0.95)
