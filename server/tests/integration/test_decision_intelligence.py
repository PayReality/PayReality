"""Decision Intelligence: integration regression tests against a real,
in-memory relational database (SQLAlchemy models, real Alembic-equivalent
schema via Base.metadata.create_all), matching this codebase's own
established "real infrastructure, no mocks, no TestClient" convention
(test_decision_security_boundary.py, test_decision_history.py) --
service functions and `require_permission`'s returned checker are called
directly, never through an HTTP client.

Covers: the full question lifecycle (propose -> link pattern/case ->
score -> submit -> answer submitted -> answer approved by a DIFFERENT
user than its author, and rejected with the SAME user raising
SeparationOfDutiesError), rule creation from an approved answer, a rule
version from an UNAPPROVED answer being rejected by validation, a real
replay run against persisted cases with its stored DIReplayCaseResult
rows and summary counts asserted, organization isolation (a cross-org
caller gets a NotFoundError, never silent empty data), permission
enforcement (Reviewer cannot approve an answer; a role without
DI_REPLAY_RUN cannot start a replay), and an audit event recorded for an
approval.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB, UUID as PG_UUID
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, DIAuditEvent, Organization, User, UserSession
from app.dependencies import require_permission
from app.domain.decision_intelligence.rule_schema import Condition, RuleAction, RuleSchema
from app.domain.rbac.permissions import Permission, Role, has_permission
from app.services import (
    di_answer_service,
    di_case_service,
    di_pattern_service,
    di_question_service,
    di_replay_service,
    di_rule_service,
    di_workflow_service,
)
from app.services.di_answer_service import InvalidAnswerTransitionError, SeparationOfDutiesError
from app.services.di_case_service import CaseNotFoundError
from app.services.di_question_service import QuestionNotFoundError
from app.services.di_rule_service import RuleValidationError, SourceAnswerNotApprovedError
from app.services.di_workflow_service import WorkflowNotFoundError


@compiles(PG_JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(element, compiler, **kw):
    return "JSON"


@compiles(PG_UUID, "sqlite")
def _uuid_as_char_on_sqlite(element, compiler, **kw):
    return "CHAR(36)"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    # Matches test_decision_security_boundary.py's own fixture: this
    # partial unique index (postgresql_where=...) is Postgres-specific;
    # discarded for the sqlite DDL pass and restored immediately after so
    # the in-memory metadata object itself is left exactly as every other
    # test file expects it.
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


def _org(db) -> Organization:
    org = Organization(id=uuid.uuid4(), name="Test Org")
    db.add(org)
    db.flush()
    return org


def _user(db, organization_id, role="governance_admin", email=None) -> User:
    user = User(
        id=uuid.uuid4(), organization_id=organization_id, email=email or f"{uuid.uuid4().hex}@example.com",
        name="Test User", password_hash="x", role=role,
    )
    db.add(user)
    db.flush()
    return user


def _session_for(db, user: User) -> UserSession:
    session = UserSession(
        id=uuid.uuid4(), user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    db.add(session)
    db.flush()
    return session


def _workflow(db, org, user):
    return di_workflow_service.create_workflow(db, org.id, user.id, name="Refund Approvals")


def _rule_schema_dict(field="amount", operator="lte", value=1000, decision="approve") -> dict:
    return RuleSchema(
        root_condition=Condition(field=field, operator=operator, value=value),
        action=RuleAction(decision=decision, human_review_required=False),
    ).model_dump()


# --- A. Full question lifecycle --------------------------------------------


def test_full_question_lifecycle(db):
    org = _org(db)
    proposer = _user(db, org.id, role="governance_admin")
    author = _user(db, org.id, role="reviewer")
    approver = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, proposer)

    case = di_case_service.create_case(
        db, org.id, workflow.id, proposer.id, facts={"amount": 500}, human_decision={"decision": "approve"}
    )
    pattern = di_pattern_service.create_pattern(
        db, org.id, workflow.id, proposer.id, name="Missing cutoff", description="desc",
        category="unclear_policy", proposed_explanation="no cutoff defined",
    )
    question = di_question_service.create_question(
        db, org.id, workflow.id, proposer.id, title="What's the refund cutoff?"
    )
    assert question.status == "proposed"

    di_question_service.link_pattern(db, question.id, pattern.id, org.id)
    di_question_service.link_case(db, question.id, case.id, org.id)
    detail_patterns = di_question_service.list_linked_patterns(db, question.id, org.id)
    detail_cases = di_question_service.list_linked_cases(db, question.id, org.id)
    assert [p.id for p in detail_patterns] == [pattern.id]
    assert detail_cases == [case.id]

    # Score: missing until all five dimensions are assessed.
    scored = di_question_service.score_question(db, question.id, org.id, proposer.id)
    assert scored.priority_score is None

    question = di_question_service.update_question(
        db, question.id, org.id, proposer.id,
        reach_score=80, impact_score=80, risk_score=60, answerability_score=90, decision_sensitivity_score=70,
    )
    scored = di_question_service.score_question(db, question.id, org.id, proposer.id)
    assert scored.priority_score is not None
    assert scored.scoring_version == "v1"

    question = di_question_service.submit_for_review(db, question.id, org.id, proposer.id)
    assert question.status == "awaiting_answer"

    answer = di_answer_service.create_draft_answer(db, question.id, org.id, author.id, content="Cutoff is 30 days")
    assert answer.status == "draft"

    answer = di_answer_service.submit_answer(db, answer.id, org.id, author.id)
    assert answer.status == "submitted"
    question_after_submit = di_question_service.get_question(db, question.id, org.id)
    assert question_after_submit.status == "answer_submitted"

    # Same user cannot approve their own answer.
    with pytest.raises(SeparationOfDutiesError):
        di_answer_service.approve_answer(db, answer.id, org.id, author.id)

    approved = di_answer_service.approve_answer(db, answer.id, org.id, approver.id)
    assert approved.status == "approved"
    assert approved.approver_user_id == approver.id
    question_after_approval = di_question_service.get_question(db, question.id, org.id)
    assert question_after_approval.status == "approved"


def test_reject_with_same_user_as_author_raises_separation_of_duties(db):
    org = _org(db)
    proposer = _user(db, org.id)
    author = _user(db, org.id, role="reviewer")
    workflow = _workflow(db, org, proposer)
    question = di_question_service.create_question(db, org.id, workflow.id, proposer.id, title="Q1")
    answer = di_answer_service.create_draft_answer(db, question.id, org.id, author.id, content="A1")
    di_answer_service.submit_answer(db, answer.id, org.id, author.id)

    with pytest.raises(SeparationOfDutiesError):
        di_answer_service.reject_answer(db, answer.id, org.id, author.id, reason="disagree")


def test_reject_by_a_different_user_succeeds_and_returns_question_to_awaiting_answer(db):
    org = _org(db)
    proposer = _user(db, org.id)
    author = _user(db, org.id, role="reviewer")
    reviewer = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, proposer)
    question = di_question_service.create_question(db, org.id, workflow.id, proposer.id, title="Q1")
    answer = di_answer_service.create_draft_answer(db, question.id, org.id, author.id, content="A1")
    di_answer_service.submit_answer(db, answer.id, org.id, author.id)

    rejected = di_answer_service.reject_answer(db, answer.id, org.id, reviewer.id, reason="needs more detail")
    assert rejected.status == "rejected"
    question_after = di_question_service.get_question(db, question.id, org.id)
    assert question_after.status == "awaiting_answer"


def test_answer_cannot_be_submitted_twice(db):
    org = _org(db)
    proposer = _user(db, org.id)
    author = _user(db, org.id)
    workflow = _workflow(db, org, proposer)
    question = di_question_service.create_question(db, org.id, workflow.id, proposer.id, title="Q1")
    answer = di_answer_service.create_draft_answer(db, question.id, org.id, author.id, content="A1")
    di_answer_service.submit_answer(db, answer.id, org.id, author.id)

    with pytest.raises(InvalidAnswerTransitionError):
        di_answer_service.submit_answer(db, answer.id, org.id, author.id)


def test_supersede_creates_a_new_immutable_version_and_marks_previous_superseded(db):
    org = _org(db)
    proposer = _user(db, org.id)
    author = _user(db, org.id, role="reviewer")
    approver = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, proposer)
    question = di_question_service.create_question(db, org.id, workflow.id, proposer.id, title="Q1")
    answer = di_answer_service.create_draft_answer(db, question.id, org.id, author.id, content="A1")
    di_answer_service.submit_answer(db, answer.id, org.id, author.id)
    approved = di_answer_service.approve_answer(db, answer.id, org.id, approver.id)

    new_version = di_answer_service.supersede_answer(
        db, approved.id, org.id, author.id, content="A1 revised"
    )
    assert new_version.version == 2
    assert new_version.previous_version_id == approved.id
    assert new_version.status == "draft"

    original_reloaded = di_answer_service.get_answer(db, approved.id, org.id)
    assert original_reloaded.status == "superseded"


# --- B. Decision rule creation from an approved answer --------------------


def _approved_answer(db, org, workflow, author, approver):
    proposer = author
    question = di_question_service.create_question(db, org.id, workflow.id, proposer.id, title="Q-rule")
    answer = di_answer_service.create_draft_answer(db, question.id, org.id, author.id, content="A-rule")
    di_answer_service.submit_answer(db, answer.id, org.id, author.id)
    return di_answer_service.approve_answer(db, answer.id, org.id, approver.id), question


def test_create_rule_from_an_approved_answer_succeeds(db):
    org = _org(db)
    author = _user(db, org.id, role="reviewer")
    approver = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, approver)
    approved_answer, _ = _approved_answer(db, org, workflow, author, approver)

    rule = di_rule_service.create_rule(
        db, org.id, workflow.id, approver.id, "Refund rule", approved_answer.id, _rule_schema_dict()
    )
    assert rule.status == "draft"
    assert rule.current_version_id is not None
    version = di_rule_service.get_current_version(db, rule)
    assert version.version == 1


def test_create_rule_from_an_unapproved_answer_is_rejected(db):
    org = _org(db)
    author = _user(db, org.id, role="reviewer")
    workflow = _workflow(db, org, author)
    question = di_question_service.create_question(db, org.id, workflow.id, author.id, title="Q-draft")
    draft_answer = di_answer_service.create_draft_answer(db, question.id, org.id, author.id, content="still a draft")

    with pytest.raises(SourceAnswerNotApprovedError):
        di_rule_service.create_rule(
            db, org.id, workflow.id, author.id, "Premature rule", draft_answer.id, _rule_schema_dict()
        )


def test_validate_rule_version_from_an_unapproved_answer_is_rejected(db):
    """Even if a rule was created from an approved answer, a NEW version
    created afterward must be re-validated against the (possibly since-
    changed) answer status -- validation never trusts creation-time state."""
    org = _org(db)
    author = _user(db, org.id, role="reviewer")
    approver = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, approver)
    approved_answer, _ = _approved_answer(db, org, workflow, author, approver)
    rule = di_rule_service.create_rule(
        db, org.id, workflow.id, approver.id, "Rule", approved_answer.id, _rule_schema_dict()
    )

    # Supersede the answer -- the ORIGINAL approved answer object is now
    # 'superseded', not 'approved'.
    di_answer_service.supersede_answer(db, approved_answer.id, org.id, author.id, content="revised")

    with pytest.raises(RuleValidationError):
        di_rule_service.validate_rule(db, rule.id, org.id, approver.id)


def test_validate_rule_succeeds_for_a_well_formed_rule_from_an_approved_answer(db):
    org = _org(db)
    author = _user(db, org.id, role="reviewer")
    approver = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, approver)
    approved_answer, _ = _approved_answer(db, org, workflow, author, approver)
    rule = di_rule_service.create_rule(
        db, org.id, workflow.id, approver.id, "Rule", approved_answer.id, _rule_schema_dict()
    )

    validated = di_rule_service.validate_rule(db, rule.id, org.id, approver.id)
    assert validated.status == "validated"


def test_rule_test_endpoint_service_runs_against_supplied_facts_without_persisting(db):
    org = _org(db)
    author = _user(db, org.id, role="reviewer")
    approver = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, approver)
    approved_answer, _ = _approved_answer(db, org, workflow, author, approver)
    rule = di_rule_service.create_rule(
        db, org.id, workflow.id, approver.id, "Rule", approved_answer.id, _rule_schema_dict(value=1000)
    )

    result = di_rule_service.test_rule(db, rule.id, org.id, case_facts={"amount": 500})
    assert result.matched is True
    assert result.decision == "approve"

    # No DIReplayRun/DIReplayCaseResult rows were written by a mere test.
    from app.db.models import DIReplayRun

    assert db.query(DIReplayRun).count() == 0


# --- C. Replay execution -------------------------------------------------


def test_replay_run_against_persisted_cases_records_correct_results_and_summary(db):
    org = _org(db)
    author = _user(db, org.id, role="reviewer")
    approver = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, approver)
    approved_answer, source_question = _approved_answer(db, org, workflow, author, approver)
    rule = di_rule_service.create_rule(
        db, org.id, workflow.id, approver.id, "Rule", approved_answer.id, _rule_schema_dict(value=1000)
    )
    version = di_rule_service.get_current_version(db, rule)

    case_agree = di_case_service.create_case(
        db, org.id, workflow.id, approver.id, facts={"amount": 500}, human_decision={"decision": "approve"}
    )
    case_disagree = di_case_service.create_case(
        db, org.id, workflow.id, approver.id, facts={"amount": 500}, human_decision={"decision": "deny"}
    )
    case_missing = di_case_service.create_case(
        db, org.id, workflow.id, approver.id, facts={}, human_decision=None
    )

    replay_run = di_replay_service.create_and_run_replay(
        db, org.id, workflow.id, version.id, approver.id,
        case_ids=[case_agree.id, case_disagree.id, case_missing.id],
    )
    assert replay_run.status == "completed"
    assert replay_run.summary["total_cases"] == 3
    assert replay_run.summary["counts"]["agrees_with_baseline"] == 1
    assert replay_run.summary["counts"]["disagrees_with_baseline"] == 1
    assert replay_run.summary["counts"]["missing_data"] == 1

    results, total = di_replay_service.list_replay_case_results(db, replay_run.id, org.id)
    assert total == 3
    by_case = {r.case_id: r for r in results}
    assert by_case[case_agree.id].outcome_category == "agrees_with_baseline"
    assert by_case[case_disagree.id].outcome_category == "disagrees_with_baseline"
    assert by_case[case_missing.id].outcome_category == "missing_data"

    # Completing a replay advances the originating question's status.
    question = di_question_service.get_question(db, source_question.id, org.id)
    assert question.status == "replay_completed"

    # An audit event was written for the replay start.
    audit_events = db.query(DIAuditEvent).filter(
        DIAuditEvent.entity_type == "DIReplayRun", DIAuditEvent.entity_id == replay_run.id
    ).all()
    assert any(e.action == "start" for e in audit_events)


def test_replay_outcome_category_is_never_described_as_correctness(db):
    """Structural guard for the brief's own naming discipline: nothing in
    the stored result or its fixed vocabulary may read as a correctness
    claim -- only the six defined, agreement-based category strings."""
    from app.domain.decision_intelligence.replay_executor import OUTCOME_CATEGORIES

    for category in OUTCOME_CATEGORIES:
        assert "correct" not in category
        assert "right" not in category
        assert "wrong" not in category


# --- D. Organization isolation --------------------------------------------


def test_cross_organization_workflow_read_is_not_found_not_empty(db):
    org_a = _org(db)
    org_b = _org(db)
    user_a = _user(db, org_a.id)
    workflow_a = _workflow(db, org_a, user_a)

    with pytest.raises(WorkflowNotFoundError):
        di_workflow_service.get_workflow(db, workflow_a.id, org_b.id)


def test_cross_organization_case_read_is_not_found(db):
    org_a = _org(db)
    org_b = _org(db)
    user_a = _user(db, org_a.id)
    workflow_a = _workflow(db, org_a, user_a)
    case_a = di_case_service.create_case(db, org_a.id, workflow_a.id, user_a.id, facts={})

    with pytest.raises(CaseNotFoundError):
        di_case_service.get_case(db, case_a.id, org_b.id)


def test_cross_organization_question_read_is_not_found(db):
    org_a = _org(db)
    org_b = _org(db)
    user_a = _user(db, org_a.id)
    workflow_a = _workflow(db, org_a, user_a)
    question_a = di_question_service.create_question(db, org_a.id, workflow_a.id, user_a.id, title="Q")

    with pytest.raises(QuestionNotFoundError):
        di_question_service.get_question(db, question_a.id, org_b.id)


def test_cross_organization_case_cannot_be_linked_to_another_orgs_workflow(db):
    """A case genuinely belonging to Org A can never be filed under Org
    B's workflow, even if Org B's caller somehow knew the case id."""
    org_a = _org(db)
    org_b = _org(db)
    user_a = _user(db, org_a.id)
    user_b = _user(db, org_b.id)
    workflow_b = _workflow(db, org_b, user_b)

    with pytest.raises(WorkflowNotFoundError):
        di_case_service.create_case(db, org_a.id, workflow_b.id, user_a.id, facts={})


def test_replay_cannot_run_against_another_organizations_rule_version(db):
    org_a = _org(db)
    org_b = _org(db)
    author_a = _user(db, org_a.id, role="reviewer")
    approver_a = _user(db, org_a.id, role="governance_admin")
    workflow_a = _workflow(db, org_a, approver_a)
    approved_answer_a, _ = _approved_answer(db, org_a, workflow_a, author_a, approver_a)
    rule_a = di_rule_service.create_rule(
        db, org_a.id, workflow_a.id, approver_a.id, "Rule A", approved_answer_a.id, _rule_schema_dict()
    )
    version_a = di_rule_service.get_current_version(db, rule_a)

    user_b = _user(db, org_b.id)
    workflow_b = _workflow(db, org_b, user_b)

    with pytest.raises(di_replay_service.RuleVersionNotFoundError):
        di_replay_service.create_and_run_replay(db, org_b.id, workflow_b.id, version_a.id, user_b.id)


# --- E. Permission enforcement --------------------------------------------


def test_reviewer_cannot_approve_an_answer():
    """REVIEWER holds DI_ANSWER_SUBMIT but not DI_ANSWER_APPROVE (RBAC's
    own separation of duties), independent of the service-layer
    SeparationOfDutiesError check exercised elsewhere in this file."""
    assert has_permission(Role.REVIEWER, Permission.DI_ANSWER_SUBMIT)
    assert not has_permission(Role.REVIEWER, Permission.DI_ANSWER_APPROVE)


async def test_reviewer_session_is_denied_di_answer_approve(db):
    org = _org(db)
    user = _user(db, org.id, role="reviewer")
    session = _session_for(db, user)
    checker = require_permission(Permission.DI_ANSWER_APPROVE)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)
    assert exc.value.status_code == 403
    assert exc.value.detail == "permission_denied"


async def test_governance_admin_session_is_allowed_di_answer_approve(db):
    org = _org(db)
    user = _user(db, org.id, role="governance_admin")
    session = _session_for(db, user)
    checker = require_permission(Permission.DI_ANSWER_APPROVE)
    await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)  # must not raise


def test_role_without_di_replay_run_is_denied():
    for role in (Role.REVIEWER, Role.AUDITOR, Role.EXECUTIVE, Role.AGENT_ADMIN):
        assert not has_permission(role, Permission.DI_REPLAY_RUN)
    assert has_permission(Role.GOVERNANCE_ADMIN, Permission.DI_REPLAY_RUN)


async def test_auditor_session_is_denied_di_replay_run(db):
    org = _org(db)
    user = _user(db, org.id, role="auditor")
    session = _session_for(db, user)
    checker = require_permission(Permission.DI_REPLAY_RUN)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)
    assert exc.value.status_code == 403


# --- F. Audit event on approval --------------------------------------------


def test_audit_event_is_recorded_for_an_answer_approval(db):
    org = _org(db)
    author = _user(db, org.id, role="reviewer")
    approver = _user(db, org.id, role="governance_admin")
    workflow = _workflow(db, org, approver)
    question = di_question_service.create_question(db, org.id, workflow.id, author.id, title="Q")
    answer = di_answer_service.create_draft_answer(db, question.id, org.id, author.id, content="A")
    di_answer_service.submit_answer(db, answer.id, org.id, author.id)
    di_answer_service.approve_answer(db, answer.id, org.id, approver.id)

    events = db.query(DIAuditEvent).filter(
        DIAuditEvent.entity_type == "DIAnswer", DIAuditEvent.entity_id == answer.id, DIAuditEvent.action == "approve"
    ).all()
    assert len(events) == 1
    assert events[0].actor_user_id == approver.id
    assert events[0].organization_id == org.id
