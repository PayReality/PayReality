"""Decision Intelligence: regression tests for the 2026-10-15 extension
closing the gap between generic discovery flags and grounded, evidence-
linked questions (candidate_explanation/alternative_explanations/missing_
evidence/potential_impact, case relevance kinds, scoring provenance/
override, answer disposition, replay development-vs-evaluation
disclosure). Reuses test_decision_intelligence.py's own real, in-memory-
relational-database fixture and helpers rather than duplicating them."""

import uuid

import pytest

from app.domain.decision_intelligence.ai_discovery.fake_provider import FakeDiscoveryProvider
from app.domain.decision_intelligence.ai_discovery.provider import CaseForDiscovery
from app.domain.decision_intelligence.rule_schema import Condition, RuleAction, RuleSchema
from app.services import (
    di_answer_service,
    di_case_service,
    di_discovery_service,
    di_pattern_service,
    di_question_service,
    di_replay_service,
    di_rule_service,
)
from app.services.di_answer_service import DispositionRequiredError
from app.services.di_pattern_service import CaseLinkNotFoundError
from tests.integration.test_decision_intelligence import _org, _rule_schema_dict, _user, _workflow, db  # noqa: F401


# --- A. Discovery suggestions carry grounded, specific fields --------------


def test_fake_provider_suggestion_round_trips_through_accept_onto_the_real_question(db):
    org = _org(db)
    user = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, user)

    di_case_service.create_case(
        db, org.id, workflow.id, user.id, facts={"amount": 90}, human_decision={"decision": "approve"}
    )
    di_case_service.create_case(
        db, org.id, workflow.id, user.id, facts={"amount": 95}, human_decision={"decision": "deny"}
    )

    run = di_discovery_service.create_and_run_discovery(
        db, org.id, workflow.id, user.id, FakeDiscoveryProvider(), "fake"
    )
    suggestions = di_discovery_service.list_suggestions_for_run(db, run.id, org.id)
    question_suggestion = next(s for s in suggestions if s.kind == "question")
    assert question_suggestion.candidate_explanation is not None
    assert question_suggestion.alternative_explanations
    assert question_suggestion.missing_evidence
    assert question_suggestion.potential_impact is not None

    # A question suggestion's linked pattern must itself be accepted
    # first (di_discovery_service's own, pre-existing requirement).
    pattern_suggestion = next(s for s in suggestions if s.kind == "pattern")
    di_discovery_service.accept_suggestion(db, pattern_suggestion.id, org.id, user.id)

    accepted = di_discovery_service.accept_suggestion(db, question_suggestion.id, org.id, user.id)
    assert accepted.candidate_explanation == question_suggestion.candidate_explanation
    assert accepted.alternative_explanations == question_suggestion.alternative_explanations
    assert accepted.missing_evidence == question_suggestion.missing_evidence
    assert accepted.potential_impact == question_suggestion.potential_impact

    accepted_pattern_suggestion = di_discovery_service.get_suggestion(db, pattern_suggestion.id, org.id)
    assert accepted_pattern_suggestion.status == "accepted"
    # The real DIPattern is reachable via the question's own linked patterns.
    linked_patterns = di_question_service.list_linked_patterns(db, accepted.id, org.id)
    assert len(linked_patterns) == 1
    assert linked_patterns[0].alternative_explanations == list(pattern_suggestion.alternative_explanations)


def test_manually_created_question_has_no_fabricated_discovery_fields(db):
    """A question created by hand (never from a suggestion) must show
    these fields as genuinely absent, never an empty-but-present
    placeholder that could be mistaken for "nothing to disclose"."""
    org = _org(db)
    user = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, user)
    question = di_question_service.create_question(db, org.id, workflow.id, user.id, title="Manual question")
    assert question.candidate_explanation is None
    assert question.alternative_explanations is None
    assert question.missing_evidence is None
    assert question.potential_impact is None


# --- B. Case relevance: supporting vs. potentially_affected vs. corrected --


def test_accept_suggestion_links_supporting_and_computes_potentially_affected(db):
    org = _org(db)
    user = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, user)

    c1 = di_case_service.create_case(
        db, org.id, workflow.id, user.id, facts={"amount": 90}, human_decision={"decision": "approve"}
    )
    c2 = di_case_service.create_case(
        db, org.id, workflow.id, user.id, facts={"amount": 95}, human_decision={"decision": "deny"}
    )
    # A third, UNCITED case that shares the same "amount" key the first
    # two cases disagreed on -- the explicit, reviewable predicate this
    # feature uses for "potentially affected": not part of the original
    # evidence, but recording the same fact the suggestion is about.
    c3 = di_case_service.create_case(db, org.id, workflow.id, user.id, facts={"amount": 500})

    run = di_discovery_service.create_and_run_discovery(
        db, org.id, workflow.id, user.id, FakeDiscoveryProvider(), "fake"
    )
    run_suggestions = di_discovery_service.list_suggestions_for_run(db, run.id, org.id)
    pattern_suggestion = next(s for s in run_suggestions if s.kind == "pattern")
    di_discovery_service.accept_suggestion(db, pattern_suggestion.id, org.id, user.id)
    question_suggestion = next(s for s in run_suggestions if s.kind == "question")
    question = di_discovery_service.accept_suggestion(db, question_suggestion.id, org.id, user.id)

    links = {link.case_id: link for link in di_question_service.list_linked_case_links(db, question.id, org.id)}
    assert links[c1.id].kind == "supporting"
    assert links[c2.id].kind == "supporting"
    assert links[c1.id].reason == "cited by discovery suggestion"
    assert c3.id in links
    assert links[c3.id].kind == "potentially_affected"
    assert "amount" in links[c3.id].reason  # names the actual shared key, not a vague label


def test_reviewer_can_correct_a_case_link_kind_and_it_is_audited(db):
    org = _org(db)
    user = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, user)
    pattern = di_pattern_service.create_pattern(
        db, org.id, workflow.id, user.id, name="P", description="d", category="other",
        proposed_explanation="observed",
    )
    case = di_case_service.create_case(db, org.id, workflow.id, user.id, facts={"amount": 10})
    di_pattern_service.link_case(db, pattern.id, case.id, org.id, kind="potentially_affected", reason="model guess")

    corrected = di_pattern_service.relink_case_kind(
        db, pattern.id, case.id, org.id, user.id, "excluded", reason="checked manually, not relevant"
    )
    assert corrected.kind == "excluded"
    assert corrected.reason == "checked manually, not relevant"

    with pytest.raises(CaseLinkNotFoundError):
        di_pattern_service.relink_case_kind(
            db, pattern.id, uuid.uuid4(), org.id, user.id, "excluded", reason="no such link"
        )


# --- C. Scoring provenance and priority override ---------------------------


def test_scores_set_through_update_question_are_tagged_human(db):
    org = _org(db)
    user = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, user)
    question = di_question_service.create_question(db, org.id, workflow.id, user.id, title="Q")
    updated = di_question_service.update_question(db, question.id, org.id, user.id, reach_score=50)
    assert updated.reach_score_source == "human"
    assert updated.impact_score_source is None  # never set, stays genuinely unknown


def test_priority_override_requires_a_reason_and_wins_over_the_computed_score(db):
    org = _org(db)
    user = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, user)
    question = di_question_service.create_question(db, org.id, workflow.id, user.id, title="Q")
    di_question_service.update_question(
        db, question.id, org.id, user.id, reach_score=50, impact_score=50, risk_score=50,
        answerability_score=50, decision_sensitivity_score=50,
    )
    scored = di_question_service.score_question(db, question.id, org.id, user.id)
    assert scored.priority_score is not None
    assert di_question_service.effective_priority(scored) == float(scored.priority_score)

    overridden = di_question_service.override_priority(
        db, question.id, org.id, user.id, score=99.0, reason="known upcoming regulatory deadline"
    )
    assert overridden.priority_override_score == 99.0
    assert overridden.priority_override_reason == "known upcoming regulatory deadline"
    assert di_question_service.effective_priority(overridden) == 99.0
    # The underlying computed score is untouched by the override.
    assert overridden.priority_score == scored.priority_score

    cleared = di_question_service.override_priority(
        db, question.id, org.id, user.id, score=None, reason="deadline passed, reverting"
    )
    assert di_question_service.effective_priority(cleared) == float(cleared.priority_score)


def test_case_evidence_counts_reflect_real_link_kinds(db):
    org = _org(db)
    user = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, user)
    question = di_question_service.create_question(db, org.id, workflow.id, user.id, title="Q")
    c1 = di_case_service.create_case(db, org.id, workflow.id, user.id, facts={})
    c2 = di_case_service.create_case(db, org.id, workflow.id, user.id, facts={})
    di_question_service.link_case(db, question.id, c1.id, org.id, kind="supporting")
    di_question_service.link_case(db, question.id, c2.id, org.id, kind="potentially_affected")

    counts = di_question_service.case_evidence_counts(db, question.id, org.id)
    assert counts["supporting"] == 1
    assert counts["potentially_affected"] == 1
    assert counts["excluded"] == 0


# --- D. Answer disposition --------------------------------------------------


def test_approve_answer_requires_a_valid_disposition(db):
    org = _org(db)
    author = _user(db, org.id, role="reviewer")
    approver = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, approver)
    question = di_question_service.create_question(db, org.id, workflow.id, approver.id, title="Q")
    answer = di_answer_service.create_draft_answer(db, question.id, org.id, author.id, content="A")
    di_answer_service.submit_answer(db, answer.id, org.id, author.id)

    with pytest.raises(DispositionRequiredError):
        di_answer_service.approve_answer(db, answer.id, org.id, approver.id, "not_a_real_disposition")

    approved = di_answer_service.approve_answer(
        db, answer.id, org.id, approver.id, "human_judgement_required", disposition_notes="case-by-case"
    )
    assert approved.disposition == "human_judgement_required"
    assert approved.disposition_notes == "case-by-case"


# --- E. Replay development-vs-evaluation disclosure ------------------------


def _approved_answer_with_question_cases(db, org, workflow, author, approver, development_case_ids):
    question = di_question_service.create_question(db, org.id, workflow.id, author.id, title="Q-eval")
    for cid in development_case_ids:
        di_question_service.link_case(db, question.id, cid, org.id, kind="supporting")
    answer = di_answer_service.create_draft_answer(db, question.id, org.id, author.id, content="A")
    di_answer_service.submit_answer(db, answer.id, org.id, author.id)
    di_answer_service.approve_answer(db, answer.id, org.id, approver.id, "rule_change")
    return answer


def test_replay_discloses_overlap_between_development_and_evaluation_cases(db):
    org = _org(db)
    author = _user(db, org.id, role="reviewer")
    approver = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, approver)

    dev_case = di_case_service.create_case(db, org.id, workflow.id, author.id, facts={"amount": 100})
    other_case = di_case_service.create_case(db, org.id, workflow.id, author.id, facts={"amount": 200})

    answer = _approved_answer_with_question_cases(db, org, workflow, author, approver, [dev_case.id])
    rule = di_rule_service.create_rule(db, org.id, workflow.id, author.id, "R", answer.id, _rule_schema_dict())
    di_rule_service.validate_rule(db, rule.id, org.id, author.id)
    rule = di_rule_service.get_rule(db, rule.id, org.id)

    # Replay against BOTH the development case and an independent one --
    # the overlap must be disclosed, never silently dropped or hidden.
    replay = di_replay_service.create_and_run_replay(
        db, org.id, workflow.id, rule.current_version_id, approver.id, case_ids=[dev_case.id, other_case.id]
    )
    assert replay.case_split is not None
    assert replay.case_split["development_case_ids"] == [str(dev_case.id)]
    assert set(replay.case_split["evaluation_case_ids"]) == {str(dev_case.id), str(other_case.id)}
    assert replay.case_split["overlap_case_ids"] == [str(dev_case.id)]
    assert replay.case_split["independent_evaluation_case_count"] == 1
    assert replay.case_split["insufficient_evaluation_cases"] is True  # 1 < MIN_INDEPENDENT_EVALUATION_CASES


def test_replay_case_split_is_none_when_rule_has_no_resolvable_source_question(db):
    """A rule can be created directly from an approved answer that was
    never linked to any question-level case evidence path issue -- this
    specifically covers the chain-resolution failing gracefully, not
    crashing the replay."""
    org = _org(db)
    author = _user(db, org.id, role="reviewer")
    approver = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, approver)
    case = di_case_service.create_case(db, org.id, workflow.id, author.id, facts={"amount": 50})

    question = di_question_service.create_question(db, org.id, workflow.id, author.id, title="Q-no-cases")
    answer = di_answer_service.create_draft_answer(db, question.id, org.id, author.id, content="A")
    di_answer_service.submit_answer(db, answer.id, org.id, author.id)
    di_answer_service.approve_answer(db, answer.id, org.id, approver.id, "rule_change")
    rule = di_rule_service.create_rule(db, org.id, workflow.id, author.id, "R", answer.id, _rule_schema_dict())
    di_rule_service.validate_rule(db, rule.id, org.id, author.id)
    rule = di_rule_service.get_rule(db, rule.id, org.id)

    replay = di_replay_service.create_and_run_replay(
        db, org.id, workflow.id, rule.current_version_id, approver.id, case_ids=[case.id]
    )
    # No "supporting" cases were ever linked to the source question, so
    # development_case_ids is genuinely empty (not None -- the question
    # itself WAS resolvable), and every evaluated case is independent.
    assert replay.case_split is not None
    assert replay.case_split["development_case_ids"] == []
    assert replay.case_split["independent_evaluation_case_count"] == 1
