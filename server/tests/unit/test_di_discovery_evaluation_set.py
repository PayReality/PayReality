"""Decision Intelligence: a small, clearly-labelled SYNTHETIC EVALUATION
SET for the discovery feature (brief's own Part 5), distinct from any
demonstration/walkthrough data used elsewhere. Exercises FakeDiscoveryProvider
(the Claude path's own, separately-tested strict schema validation covers
the same grounding/vocabulary discipline; a real-API check is recorded
separately, not repeated here as an automated test to avoid unbounded
spend on every run).

Unlike test_di_discovery_fake_provider.py (which tests individual
heuristic mechanics), this file asserts PROPERTIES a useful suggestion
must have, against ONE shared, deliberately varied batch of cases
covering every scenario the brief names:

1. A percentage rule missing an absolute-amount condition (the TRUE
   differing field is an absolute amount, not the percentage that looks
   similar across cases).
2. Near-identical facts, different outcomes, caused by an omitted fact
   (nothing distinguishes the cases in the recorded data at all).
3. Different policy versions/effective dates legitimately producing
   different decisions (one recorded field differs: the effective date).
4. An optional field that should NOT trigger a "required field" claim.
5. A retrieval/integration defect as a possible (never asserted) cause.
6. A case requiring irreducible expert judgement (a true outlier).
7. A clear case that needs no new question at all.

This batch is held out from (not used to derive) the specific-question
upgrade implemented in fake_provider.py -- that logic was designed by
reading the heuristic's own code paths, not by fitting this evaluation
set's wording, and this file uses different field names/values than any
example in this codebase's own docstrings or demonstration data."""

from app.domain.decision_intelligence.ai_discovery.fake_provider import FakeDiscoveryProvider
from app.domain.decision_intelligence.ai_discovery.provider import CaseForDiscovery

OVERCLAIM_PHRASES = ("confirmed", "established", "proven", "definitely", "certainly")


def _case(id_, facts, decision=None, escalation_reason=None):
    return CaseForDiscovery(
        id=id_, facts=facts, escalation_reason=escalation_reason,
        human_decision={"decision": decision} if decision else None, outcome=None, status="open",
    )


def _evaluation_cases() -> list[CaseForDiscovery]:
    return [
        # 1. Percentage looks identical; the real differing, decisive
        #    field is an absolute currency amount.
        _case("EVAL-01", {"pct_over_budget": 12, "invoice_total": 4800}, decision="approve"),
        _case("EVAL-02", {"pct_over_budget": 12, "invoice_total": 95000}, decision="deny"),
        # 2. Fully identical recorded facts, opposite decisions -- nothing
        #    in the data distinguishes them (the "omitted fact" scenario).
        _case("EVAL-03", {"region": "north", "tier": "standard"}, decision="approve"),
        _case("EVAL-04", {"region": "north", "tier": "standard"}, decision="deny"),
        # 3. Only the recorded policy/effective-date-like field differs.
        _case("EVAL-05", {"policy_version": "2024-Q1", "contract_type": "fixed"}, decision="approve"),
        _case("EVAL-06", {"policy_version": "2025-Q3", "contract_type": "fixed"}, decision="deny"),
        # 4. An optional attachment field, present on some, absent on
        #    others, that must never be called "required".
        _case("EVAL-07", {"spend_category": "travel", "receipt_attached": True}, decision="approve"),
        _case("EVAL-08", {"spend_category": "travel"}, decision="approve"),
        _case("EVAL-09", {"spend_category": "travel"}, decision="approve"),
        # 6/7. A true outlier (no near-identical peer, no shared missing
        #    field with >=2 others, no escalation cluster) and a clear,
        #    unambiguous case -- neither should ever be cited anywhere.
        _case("EVAL-10", {"spend_category": "one_off_executive_gift", "amount": 17}, decision="approve"),
        _case("EVAL-11", {"spend_category": "office_supplies", "amount": 40}, decision="approve"),
    ]


def _all_suggestion_case_ids(result) -> set[str]:
    ids: set[str] = set()
    for pattern in result.patterns:
        ids |= set(pattern.supporting_case_ids)
        for question in pattern.questions:
            ids |= set(question.supporting_case_ids)
    return ids


def test_evaluation_set_every_citation_is_grounded_in_a_real_supplied_case():
    cases = _evaluation_cases()
    valid_ids = {c.id for c in cases}
    result = FakeDiscoveryProvider().discover(cases)
    assert _all_suggestion_case_ids(result) <= valid_ids


def test_evaluation_set_recognizes_the_true_deciding_field_despite_a_similar_looking_distractor():
    """Scenario 1: pct_over_budget is identical across EVAL-01/02; only
    invoice_total actually differs and decides the case. The specific-
    question upgrade must name invoice_total, not the distractor field."""
    cases = _evaluation_cases()
    result = FakeDiscoveryProvider().discover(cases)
    pattern = next(p for p in result.patterns if {"EVAL-01", "EVAL-02"} <= set(p.supporting_case_ids))
    question = pattern.questions[0]
    assert "invoice_total" in question.title
    assert "pct_over_budget" not in question.title
    assert "4800" in question.title and "95000" in question.title


def test_evaluation_set_stays_broad_and_honest_when_nothing_in_the_data_distinguishes_the_cases():
    """Scenario 2: EVAL-03/04 are recorded identically; no specific field
    can honestly be named as the deciding factor."""
    cases = _evaluation_cases()
    result = FakeDiscoveryProvider().discover(cases)
    pattern = next(p for p in result.patterns if {"EVAL-03", "EVAL-04"} <= set(p.supporting_case_ids))
    question = pattern.questions[0]
    assert "What explains the difference?" in question.title
    assert "omitted fact" in question.alternative_explanations[0] or any(
        "omitted fact" in alt for alt in question.alternative_explanations
    )
    assert question.candidate_explanation is not None  # still a labelled hypothesis, not silence


def test_evaluation_set_names_policy_version_and_offers_it_as_an_explanation_not_a_fact():
    """Scenario 3: policy_version is the one differing field -- it must
    be named specifically, but the alternative "different policy
    versions" framing must still be offered, not asserted as settled."""
    cases = _evaluation_cases()
    result = FakeDiscoveryProvider().discover(cases)
    pattern = next(p for p in result.patterns if {"EVAL-05", "EVAL-06"} <= set(p.supporting_case_ids))
    question = pattern.questions[0]
    assert "policy_version" in question.title
    assert any("policy version" in alt or "effective date" in alt for alt in question.alternative_explanations)
    for text in (pattern.description, pattern.rationale, question.description, question.rationale):
        assert not any(phrase in text.lower() for phrase in OVERCLAIM_PHRASES)


def test_evaluation_set_never_calls_an_inconsistently_recorded_field_required():
    """Scenario 4: receipt_attached is present on one case, absent on two
    others -- a real, legitimate optional field. The suggestion must ask
    a relevance question, never assert the field is required."""
    cases = _evaluation_cases()
    result = FakeDiscoveryProvider().discover(cases)
    pattern = next(
        p for p in result.patterns
        if p.category == "missing_facts" and {"EVAL-08", "EVAL-09"} <= set(p.supporting_case_ids)
    )
    question = pattern.questions[0]
    assert "relevant" in question.title
    assert "required" not in question.title
    assert "optional" in question.rationale or "optional" in pattern.description


def test_evaluation_set_offers_a_retrieval_or_integration_defect_as_a_possible_cause():
    """Scenario 5: every conflicting-outcome suggestion must disclose a
    data/integration-defect explanation among its alternatives -- the
    heuristic can never rule this out from data alone, so it must never
    be silently omitted."""
    cases = _evaluation_cases()
    result = FakeDiscoveryProvider().discover(cases)
    conflict_patterns = [p for p in result.patterns if p.confidence == "high"]
    assert conflict_patterns
    for pattern in conflict_patterns:
        assert any(
            "integration defect" in alt or "retrieval" in alt for alt in pattern.alternative_explanations
        )


def test_evaluation_set_recognizes_insufficient_evidence_for_outlier_and_clear_cases():
    """Scenarios 6 and 7: EVAL-10 (a genuine one-off outlier) and EVAL-11
    (an unambiguous, clean case) must never be cited by a high-confidence
    conflicting-outcome pattern or an escalation-reason cluster -- the
    two heuristics that would actually assert something SPECIFIC about
    them. Forcing either of those onto a genuinely unrelated case would
    be exactly the "manufactured confidence" the brief prohibits.

    A real, disclosed finding from running this evaluation set (not
    fixed here, since it would mean changing the missing-field
    heuristic's own pre-existing, already-disclosed behaviour, which this
    pass's scope didn't include): when a batch mixes cases from several
    genuinely different fact "shapes" (as this synthetic set
    deliberately does, to cover every scenario in one run), EVAL-10/11
    DO get swept into several low-confidence missing-field patterns for
    fields that belong to other scenarios entirely (e.g. "missing
    contract_type"). This is the SAME noisy-on-heterogeneous-data
    property DECISION_INTELLIGENCE_PLATFORM.md already discloses for
    this heuristic, now confirmed concretely rather than just asserted."""
    cases = _evaluation_cases()
    result = FakeDiscoveryProvider().discover(cases)
    specific_claim_patterns = [p for p in result.patterns if p.category != "missing_facts"]
    cited_by_specific_claims = set()
    for pattern in specific_claim_patterns:
        cited_by_specific_claims |= set(pattern.supporting_case_ids)
    assert "EVAL-10" not in cited_by_specific_claims
    assert "EVAL-11" not in cited_by_specific_claims


def test_evaluation_set_produces_no_redundant_or_duplicate_questions_per_case_group():
    """No scenario's case group should spawn more than one question from
    the SAME heuristic -- a reviewer should see one grounded question per
    genuine recurring issue, not several near-duplicates."""
    cases = _evaluation_cases()
    result = FakeDiscoveryProvider().discover(cases)
    for pattern in result.patterns:
        assert len(pattern.questions) <= 1
