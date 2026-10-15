"""Unit tests for FakeDiscoveryProvider's three heuristics
(domain/decision_intelligence/ai_discovery/fake_provider.py), each against
a small, hand-constructed case set where the expected finding is known in
advance -- not just "it returns something." Mirrors this codebase's own
house style for provider tests (test_ai_policy_builder_provider.py): no
mocking library, dependency-injected/constructed inputs, exact assertions."""

from app.domain.decision_intelligence.ai_discovery.fake_provider import FakeDiscoveryProvider
from app.domain.decision_intelligence.ai_discovery.provider import CaseForDiscovery


def _case(id, facts=None, escalation_reason=None, human_decision=None, outcome=None, status="open"):
    return CaseForDiscovery(
        id=id, facts=facts or {}, escalation_reason=escalation_reason,
        human_decision=human_decision, outcome=outcome, status=status,
    )


# --- Conflicting-outcome detection (the priority heuristic) ----------------


def test_conflicting_outcome_detects_near_identical_facts_with_opposite_decisions():
    cases = [
        _case("C1", facts={"amount": 90, "photo": False}, human_decision={"decision": "approve"}),
        _case("C2", facts={"amount": 95, "photo": False}, human_decision={"decision": "deny"}),
    ]
    result = FakeDiscoveryProvider().discover(cases)

    conflict_patterns = [p for p in result.patterns if p.confidence == "high"]
    assert len(conflict_patterns) == 1
    pattern = conflict_patterns[0]
    assert set(pattern.supporting_case_ids) == {"C1", "C2"}
    assert "amount" in pattern.title
    assert len(pattern.questions) == 1
    assert set(pattern.questions[0].supporting_case_ids) == {"C1", "C2"}


def test_conflicting_outcome_requires_facts_to_actually_differ_by_at_most_one_field():
    """Two cases differing in TWO fields are not "near-identical", even if
    their decisions also disagree -- this must not fire."""
    cases = [
        _case("C1", facts={"amount": 90, "tier": "standard"}, human_decision={"decision": "approve"}),
        _case("C2", facts={"amount": 500, "tier": "vip"}, human_decision={"decision": "deny"}),
    ]
    result = FakeDiscoveryProvider().discover(cases)
    assert not any(p.confidence == "high" for p in result.patterns)


def test_conflicting_outcome_requires_decisions_to_actually_differ():
    """Identical facts and the SAME decision is just corroborating
    evidence, not a conflict -- must not fire."""
    cases = [
        _case("C1", facts={"amount": 90}, human_decision={"decision": "approve"}),
        _case("C2", facts={"amount": 95}, human_decision={"decision": "approve"}),
    ]
    result = FakeDiscoveryProvider().discover(cases)
    assert not any(p.confidence == "high" for p in result.patterns)


def test_conflicting_outcome_ignores_cases_with_no_recorded_decision():
    cases = [
        _case("C1", facts={"amount": 90}, human_decision=None),
        _case("C2", facts={"amount": 95}, human_decision=None),
    ]
    result = FakeDiscoveryProvider().discover(cases)
    assert not any(p.confidence == "high" for p in result.patterns)


def test_conflicting_outcome_merges_a_transitive_chain_into_one_group():
    cases = [
        _case("C1", facts={"amount": 90}, human_decision={"decision": "approve"}),
        _case("C2", facts={"amount": 95}, human_decision={"decision": "deny"}),
        _case("C3", facts={"amount": 100}, human_decision={"decision": "approve"}),
    ]
    result = FakeDiscoveryProvider().discover(cases)
    conflict_patterns = [p for p in result.patterns if p.confidence == "high"]
    assert len(conflict_patterns) == 1
    assert set(conflict_patterns[0].supporting_case_ids) == {"C1", "C2", "C3"}


def test_conflicting_outcome_on_identical_facts_reads_as_a_real_finding_not_a_bug():
    """Disclosed bug, fixed: when two cases' recorded facts match in full
    (zero differing fields), the generated text must describe that real
    finding plainly, never the previous "no recorded fields" placeholder
    phrase, which read as nonsense rather than a finding."""
    cases = [
        _case("C1", facts={"amount": 90, "tier": "gold"}, human_decision={"decision": "approve"}),
        _case("C2", facts={"amount": 90, "tier": "gold"}, human_decision={"decision": "deny"}),
    ]
    result = FakeDiscoveryProvider().discover(cases)
    conflict_patterns = [p for p in result.patterns if p.confidence == "high"]
    assert len(conflict_patterns) == 1
    pattern = conflict_patterns[0]
    assert "no recorded fields" not in pattern.title
    assert "no recorded fields" not in pattern.description
    assert "no recorded fields" not in pattern.rationale
    assert "identical" in pattern.title.lower()


def test_conflicting_outcome_never_asserts_a_specific_cause():
    """The observation (matching facts, different decisions) must be
    surfaced as a question, never as an asserted cause such as "the
    organisation has not settled" or a forced conflicting_rules category,
    since the real cause could equally be an omitted fact, a legitimate
    exception, a data error, or something else not yet known."""
    cases = [
        _case("C1", facts={"amount": 90}, human_decision={"decision": "approve"}),
        _case("C2", facts={"amount": 95}, human_decision={"decision": "deny"}),
    ]
    result = FakeDiscoveryProvider().discover(cases)
    pattern = next(p for p in result.patterns if p.confidence == "high")
    assert pattern.category == "other"
    assert "not settled" not in pattern.rationale
    assert "not an inferred correlation" not in pattern.rationale
    # Exactly one differing field ("amount") with exactly two distinct
    # values (90 vs 95) is grounded enough to earn a specific question
    # naming the actual field and values, rather than the generic "what
    # explains the difference" wording -- see test_di_discovery_fake_
    # provider.py::test_conflicting_outcome_question_stays_broad_when_
    # not_specifically_grounded for the case where it must stay broad.
    question = pattern.questions[0]
    assert "amount" in question.title
    assert "90" in question.title and "95" in question.title
    assert question.candidate_explanation is not None
    assert len(question.alternative_explanations) >= 3
    assert len(question.missing_evidence) >= 1
    assert question.potential_impact is not None


def test_conflicting_outcome_question_stays_broad_when_not_specifically_grounded():
    """Three cases with the same single differing field but THREE distinct
    values don't support naming "value A vs value B" as the deciding
    comparison -- the question must stay at the observation-level wording
    instead of fabricating a narrower claim the data doesn't support."""
    cases = [
        _case("C1", facts={"amount": 90}, human_decision={"decision": "approve"}),
        _case("C2", facts={"amount": 95}, human_decision={"decision": "deny"}),
        _case("C3", facts={"amount": 100}, human_decision={"decision": "escalate"}),
    ]
    result = FakeDiscoveryProvider().discover(cases)
    pattern = next(p for p in result.patterns if p.confidence == "high")
    assert "What explains the difference?" in pattern.questions[0].title
    assert pattern.questions[0].candidate_explanation is not None


# --- Missing-field grouping -------------------------------------------------


def test_missing_field_groups_cases_that_omit_a_field_others_record():
    cases = [
        _case("C1", facts={"amount": 100, "photo_evidence_provided": True}),
        _case("C2", facts={"amount": 50}),  # missing photo_evidence_provided
        _case("C3", facts={"amount": 75}),  # missing photo_evidence_provided
    ]
    result = FakeDiscoveryProvider().discover(cases)

    missing_patterns = [p for p in result.patterns if p.confidence == "medium" and "photo_evidence_provided" in p.title]
    assert len(missing_patterns) == 1
    pattern = missing_patterns[0]
    assert set(pattern.supporting_case_ids) == {"C2", "C3"}
    assert pattern.questions[0].title.startswith("Is 'photo_evidence_provided' relevant")


def test_missing_field_never_asserts_the_field_is_required():
    """The heuristic has no schema telling it which fields are mandatory
    vs. legitimately optional (DICase.facts is schema-less); this is true
    even for a field present on most cases, so the generated text must
    always hedge on relevance rather than assert the field is required,
    regardless of how common it is."""
    cases = [
        _case("C1", facts={"amount": 100, "secondary_contact": "a@example.com"}),
        _case("C2", facts={"amount": 50, "secondary_contact": "b@example.com"}),
        _case("C3", facts={"amount": 75, "secondary_contact": "c@example.com"}),
        _case("C4", facts={"amount": 60}),  # legitimately has no secondary contact
        _case("C5", facts={"amount": 65}),
    ]
    result = FakeDiscoveryProvider().discover(cases)
    pattern = next(p for p in result.patterns if "secondary_contact" in p.title)
    assert "required" not in pattern.description.lower() or "not yet known" in pattern.description.lower()
    assert "legitimately optional" in pattern.description
    assert "optional" in pattern.rationale
    assert pattern.questions[0].title == "Is 'secondary_contact' relevant to deciding this kind of case?"


def test_missing_field_requires_the_field_to_be_present_on_at_least_one_case():
    """A key nobody ever sets isn't a "sometimes missing" signal -- it's
    just an unused field. Must not fire."""
    cases = [
        _case("C1", facts={"amount": 100}),
        _case("C2", facts={"amount": 50}),
    ]
    result = FakeDiscoveryProvider().discover(cases)
    assert result.patterns == ()


def test_missing_field_requires_at_least_two_cases_missing_it():
    cases = [
        _case("C1", facts={"amount": 100, "photo": True}),
        _case("C2", facts={"amount": 50, "photo": True}),
        _case("C3", facts={"amount": 75}),  # only one case missing 'photo'
    ]
    result = FakeDiscoveryProvider().discover(cases)
    assert not any("photo" in p.title for p in result.patterns)


def test_missing_field_treats_a_null_value_the_same_as_an_absent_key():
    cases = [
        _case("C1", facts={"amount": 100, "photo": True}),
        _case("C2", facts={"amount": 50, "photo": None}),
        _case("C3", facts={"amount": 75, "photo": None}),
    ]
    result = FakeDiscoveryProvider().discover(cases)
    missing_patterns = [p for p in result.patterns if "photo" in p.title]
    assert len(missing_patterns) == 1
    assert set(missing_patterns[0].supporting_case_ids) == {"C2", "C3"}


# --- Escalation-reason matching ---------------------------------------------


def test_escalation_reason_clusters_cases_with_shared_significant_words():
    cases = [
        _case("C1", facts={}, escalation_reason="customer disputes the late delivery fee"),
        _case("C2", facts={}, escalation_reason="customer disputes a late delivery charge"),
    ]
    result = FakeDiscoveryProvider().discover(cases)

    escalation_patterns = [p for p in result.patterns if p.confidence == "low"]
    assert len(escalation_patterns) == 1
    assert set(escalation_patterns[0].supporting_case_ids) == {"C1", "C2"}


def test_escalation_reason_does_not_cluster_unrelated_reasons():
    cases = [
        _case("C1", facts={}, escalation_reason="customer disputes the late delivery fee"),
        _case("C2", facts={}, escalation_reason="supplier shipped the wrong product entirely"),
    ]
    result = FakeDiscoveryProvider().discover(cases)
    assert not any(p.confidence == "low" for p in result.patterns)


def test_escalation_reason_ignores_cases_with_no_escalation_reason():
    cases = [
        _case("C1", facts={}, escalation_reason=None),
        _case("C2", facts={}, escalation_reason=""),
    ]
    result = FakeDiscoveryProvider().discover(cases)
    assert result.patterns == ()


def test_escalation_reason_requires_at_least_two_cases_in_a_cluster():
    cases = [_case("C1", facts={}, escalation_reason="a one-off unique complaint about packaging")]
    result = FakeDiscoveryProvider().discover(cases)
    assert result.patterns == ()


# --- Cross-cutting ----------------------------------------------------------


def test_discover_with_no_cases_returns_no_patterns():
    result = FakeDiscoveryProvider().discover([])
    assert result.patterns == ()


def test_every_pattern_has_at_least_two_supporting_cases():
    """A single case is an observation, never a "recurring" pattern --
    true across all three heuristics at once on a combined, realistic set."""
    cases = [
        _case("C1", facts={"amount": 90, "photo": False}, human_decision={"decision": "approve"}),
        _case("C2", facts={"amount": 95, "photo": False}, human_decision={"decision": "deny"}),
        _case("C3", facts={"amount": 500}),
        _case("C4", facts={"amount": 10000}, escalation_reason="unique one-off issue"),
    ]
    result = FakeDiscoveryProvider().discover(cases)
    for pattern in result.patterns:
        assert len(pattern.supporting_case_ids) >= 2
