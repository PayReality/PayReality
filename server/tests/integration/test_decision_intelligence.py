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

from app.db.models import (
    Base,
    DIAuditEvent,
    DIDiscoverySuggestion,
    DIImportJob,
    DIPattern,
    DIQuestion,
    Organization,
    User,
    UserSession,
)
from app.dependencies import require_permission
from app.domain.decision_intelligence.ai_discovery.fake_provider import FakeDiscoveryProvider
from app.domain.decision_intelligence.ai_discovery.provider import CaseForDiscovery, DiscoveryResult
from app.domain.decision_intelligence.rule_schema import Condition, RuleAction, RuleSchema
from app.domain.decision_intelligence.scoring import DEFAULT_WEIGHTS, InvalidScoringWeightsError
from app.domain.decision_intelligence.validation import RuleValidationError
from app.domain.rbac.permissions import Permission, Role, has_permission
from app.services import (
    di_answer_service,
    di_audit_service,
    di_case_service,
    di_discovery_service,
    di_import_service,
    di_pattern_service,
    di_question_service,
    di_replay_service,
    di_report_service,
    di_rule_service,
    di_scoring_config_service,
    di_workflow_service,
)
from app.services.di_answer_service import InvalidAnswerTransitionError, SeparationOfDutiesError
from app.services.di_case_service import CaseNotFoundError
from app.services.di_discovery_service import (
    DiscoveryRunNotFoundError,
    LinkedPatternNotAcceptedError,
    LinkedPatternNotFoundError,
    SuggestionNotFoundError,
    SuggestionNotPendingError,
)
from app.services.di_import_service import EmptyImportFileError
from app.services.di_question_service import QuestionNotFoundError
from app.services.di_rule_service import SourceAnswerNotApprovedError
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


def test_role_without_di_settings_manage_is_denied():
    """New permission (Feature: configurable scoring weights) --
    Governance Administrator (and Owner, via the full-permission
    catch-all) only, same as every other DI_*_MANAGE permission."""
    for role in (Role.REVIEWER, Role.AUDITOR, Role.EXECUTIVE, Role.AGENT_ADMIN):
        assert not has_permission(role, Permission.DI_SETTINGS_MANAGE)
    assert has_permission(Role.GOVERNANCE_ADMIN, Permission.DI_SETTINGS_MANAGE)
    assert has_permission(Role.OWNER, Permission.DI_SETTINGS_MANAGE)


async def test_reviewer_session_is_denied_di_settings_manage(db):
    org = _org(db)
    user = _user(db, org.id, role="reviewer")
    session = _session_for(db, user)
    checker = require_permission(Permission.DI_SETTINGS_MANAGE)
    with pytest.raises(HTTPException) as exc:
        await checker(x_payreality_operator_key=None, authorization=f"Bearer {session.id}", db=db)
    assert exc.value.status_code == 403


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


# --- G. CSV case import -----------------------------------------------------


_IMPORT_CSV = (
    "Ref,Decision,Amount,Notes\r\n"
    "CASE-1,{\"outcome\": \"approve\"},120,fine\r\n"
    "CASE-2,not valid json,90,\r\n"  # invalid human_decision JSON -> rejected
    ",,,\r\n"  # completely empty row -> rejected
    "CASE-1,{\"outcome\": \"approve\"},130,duplicate\r\n"  # duplicate ref within file -> rejected
)

_IMPORT_MAPPING = {"Ref": "external_ref", "Decision": "human_decision"}


def test_csv_import_creates_valid_cases_and_reports_invalid_rows(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)

    job = di_import_service.import_cases_from_csv(
        db, org.id, workflow.id, user.id, "cases.csv", _IMPORT_CSV, _IMPORT_MAPPING
    )

    assert job.status == "completed"
    assert job.total_rows == 4
    assert job.valid_rows == 1
    assert job.invalid_rows == 3
    assert job.completed_at is not None
    row_numbers_with_errors = {e["row_number"] for e in job.row_errors}
    assert row_numbers_with_errors == {2, 3, 4}

    cases, total = di_case_service.list_cases(db, org.id, workflow_id=workflow.id)
    assert total == 1
    assert cases[0].external_ref == "CASE-1"
    assert cases[0].human_decision == {"outcome": "approve"}
    assert cases[0].facts["Amount"] == 120
    assert cases[0].facts["Notes"] == "fine"


def test_csv_import_detects_duplicate_external_ref_against_an_existing_case(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    di_case_service.create_case(db, org.id, workflow.id, user.id, facts={}, external_ref="CASE-EXISTING")

    job = di_import_service.import_cases_from_csv(
        db, org.id, workflow.id, user.id, "cases.csv",
        "Ref,Amount\r\nCASE-EXISTING,50\r\n", {"Ref": "external_ref"},
    )

    assert job.valid_rows == 0
    assert job.invalid_rows == 1
    assert "duplicate_external_ref" in job.row_errors[0]["errors"][0]


def test_csv_import_raises_workflow_not_found_for_another_organizations_workflow(db):
    org_a = _org(db)
    org_b = _org(db)
    user_a = _user(db, org_a.id)
    user_b = _user(db, org_b.id)
    workflow_b = _workflow(db, org_b, user_b)

    with pytest.raises(WorkflowNotFoundError):
        di_import_service.import_cases_from_csv(
            db, org_a.id, workflow_b.id, user_a.id, "cases.csv", "Ref\r\nCASE-1\r\n", {"Ref": "external_ref"}
        )


def test_csv_import_with_no_data_rows_raises(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)

    with pytest.raises(EmptyImportFileError):
        di_import_service.import_cases_from_csv(
            db, org.id, workflow.id, user.id, "empty.csv", "Ref,Amount\r\n", {"Ref": "external_ref"}
        )


def test_csv_import_records_exactly_one_audit_event_per_job_not_per_row(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)

    job = di_import_service.import_cases_from_csv(
        db, org.id, workflow.id, user.id, "cases.csv", _IMPORT_CSV, _IMPORT_MAPPING
    )

    events = db.query(DIAuditEvent).filter(
        DIAuditEvent.entity_type == "DIImportJob", DIAuditEvent.entity_id == job.id
    ).all()
    assert len(events) == 1
    assert events[0].action == "import"
    assert events[0].new_value["valid_rows"] == 1


def test_list_and_get_import_jobs_are_scoped_to_organization(db):
    org_a = _org(db)
    org_b = _org(db)
    user_a = _user(db, org_a.id)
    user_b = _user(db, org_b.id)
    workflow_a = _workflow(db, org_a, user_a)
    workflow_b = _workflow(db, org_b, user_b)

    job_a = di_import_service.import_cases_from_csv(
        db, org_a.id, workflow_a.id, user_a.id, "a.csv", "Ref\r\nA-1\r\n", {"Ref": "external_ref"}
    )
    di_import_service.import_cases_from_csv(
        db, org_b.id, workflow_b.id, user_b.id, "b.csv", "Ref\r\nB-1\r\n", {"Ref": "external_ref"}
    )

    jobs_a, total_a = di_import_service.list_import_jobs(db, org_a.id)
    assert total_a == 1
    assert jobs_a[0].id == job_a.id

    from app.services.di_import_service import ImportJobNotFoundError

    with pytest.raises(ImportJobNotFoundError):
        di_import_service.get_import_job(db, job_a.id, org_b.id)


# --- H. Cross-workflow reports -----------------------------------------


def test_organization_overview_aggregates_real_counts_across_two_workflows(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow_1 = di_workflow_service.create_workflow(db, org.id, user.id, name="Refunds")
    workflow_2 = di_workflow_service.create_workflow(db, org.id, user.id, name="Escalations")

    di_case_service.create_case(db, org.id, workflow_1.id, user.id, facts={"a": 1})
    di_case_service.create_case(db, org.id, workflow_1.id, user.id, facts={"a": 2})
    di_case_service.create_case(db, org.id, workflow_2.id, user.id, facts={"a": 3})
    di_pattern_service.create_pattern(
        db, org.id, workflow_1.id, user.id, name="P1", description="d", category="other",
        proposed_explanation="e",
    )
    di_question_service.create_question(db, org.id, workflow_1.id, user.id, title="Q1")
    di_question_service.create_question(db, org.id, workflow_2.id, user.id, title="Q2")

    overview = di_report_service.get_organization_overview(db, org.id)

    assert overview["workflow_count"] == 2
    assert overview["total_cases"] == 3
    assert overview["total_patterns"] == 1
    assert overview["total_questions"] == 2

    by_id = {w["workflow_id"]: w for w in overview["by_workflow"]}
    assert by_id[workflow_1.id]["case_count"] == 2
    assert by_id[workflow_1.id]["pattern_count"] == 1
    assert by_id[workflow_2.id]["case_count"] == 1
    assert by_id[workflow_2.id]["pattern_count"] == 0


def test_organization_overview_is_scoped_to_organization(db):
    org_a = _org(db)
    org_b = _org(db)
    user_a = _user(db, org_a.id)
    user_b = _user(db, org_b.id)
    _workflow(db, org_a, user_a)
    workflow_b = _workflow(db, org_b, user_b)
    di_case_service.create_case(db, org_b.id, workflow_b.id, user_b.id, facts={})

    overview_a = di_report_service.get_organization_overview(db, org_a.id)
    assert overview_a["total_cases"] == 0
    assert overview_a["workflow_count"] == 1


def test_priority_questions_export_rows_include_real_linked_counts(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    case = di_case_service.create_case(db, org.id, workflow.id, user.id, facts={})
    question = di_question_service.create_question(db, org.id, workflow.id, user.id, title="Cutoff question")
    di_question_service.link_case(db, question.id, case.id, org.id)

    rows = di_report_service.get_priority_questions_export_rows(db, org.id)

    assert len(rows) == 1
    row = rows[0]
    assert row[1] == "Cutoff question"
    assert row[6] == 1  # linked_case_count


# --- I. Configurable scoring weights ----------------------------------


def test_changing_scoring_config_does_not_retroactively_alter_an_existing_scored_question(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    question = di_question_service.create_question(db, org.id, workflow.id, user.id, title="Q")
    di_question_service.update_question(
        db, question.id, org.id, user.id,
        reach_score=100, impact_score=0, risk_score=0, answerability_score=0, decision_sensitivity_score=0,
    )
    scored_before = di_question_service.score_question(db, question.id, org.id, user.id)
    assert scored_before.priority_score == 30.0  # DEFAULT_WEIGHTS: 0.30 * 100
    assert scored_before.scoring_version == "v1"

    # Now the organization configures custom weights that would produce a
    # very different score for identical dimension inputs.
    di_scoring_config_service.upsert_config(
        db, org.id, user.id,
        {"reach": 0.80, "impact": 0.05, "risk": 0.05, "answerability": 0.05, "decision_sensitivity": 0.05},
    )

    # The already-scored question's stored values are untouched.
    unchanged = di_question_service.get_question(db, question.id, org.id)
    assert unchanged.priority_score == 30.0
    assert unchanged.scoring_version == "v1"

    # Only an explicit re-score picks up the new config.
    rescored = di_question_service.score_question(db, question.id, org.id, user.id)
    assert rescored.priority_score == 80.0  # 0.80 * 100
    assert rescored.scoring_version == "v2"


def test_scoring_config_is_per_organization_and_defaults_when_unset(db):
    org_a = _org(db)
    org_b = _org(db)
    user_a = _user(db, org_a.id)

    weights_b, version_b = di_scoring_config_service.get_weights_and_version(db, org_b.id)
    assert weights_b == DEFAULT_WEIGHTS
    assert version_b == "v1"

    di_scoring_config_service.upsert_config(
        db, org_a.id, user_a.id,
        {"reach": 0.2, "impact": 0.2, "risk": 0.2, "answerability": 0.2, "decision_sensitivity": 0.2},
    )
    weights_a, version_a = di_scoring_config_service.get_weights_and_version(db, org_a.id)
    assert weights_a["reach"] == 0.2
    assert version_a == "v2"

    # org_b remains unaffected by org_a's configuration.
    weights_b_after, version_b_after = di_scoring_config_service.get_weights_and_version(db, org_b.id)
    assert weights_b_after == DEFAULT_WEIGHTS
    assert version_b_after == "v1"


def test_scoring_config_rejects_weights_that_do_not_sum_to_one(db):
    org = _org(db)
    user = _user(db, org.id)

    with pytest.raises(InvalidScoringWeightsError):
        di_scoring_config_service.upsert_config(
            db, org.id, user.id,
            {"reach": 0.5, "impact": 0.5, "risk": 0.5, "answerability": 0.5, "decision_sensitivity": 0.5},
        )

    # No config row was created by the rejected attempt.
    assert di_scoring_config_service.get_config(db, org.id) is None


def test_scoring_config_audit_event_is_recorded_on_update(db):
    org = _org(db)
    user = _user(db, org.id)

    config = di_scoring_config_service.upsert_config(
        db, org.id, user.id,
        {"reach": 0.2, "impact": 0.2, "risk": 0.2, "answerability": 0.2, "decision_sensitivity": 0.2},
    )

    events = db.query(DIAuditEvent).filter(
        DIAuditEvent.entity_type == "DIScoringConfig", DIAuditEvent.entity_id == config.id
    ).all()
    assert len(events) == 1
    assert events[0].action == "update"


# --- J. Server-side case search -----------------------------------------


def test_case_search_matches_external_ref_substring_case_insensitively(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    di_case_service.create_case(db, org.id, workflow.id, user.id, facts={}, external_ref="REFUND-1001")
    di_case_service.create_case(db, org.id, workflow.id, user.id, facts={}, external_ref="OTHER-2002")

    cases, total = di_case_service.list_cases(db, org.id, workflow_id=workflow.id, q="refund")

    assert total == 1
    assert cases[0].external_ref == "REFUND-1001"


def test_case_search_matches_against_facts_text(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    di_case_service.create_case(db, org.id, workflow.id, user.id, facts={"damage_type": "water damage"})
    di_case_service.create_case(db, org.id, workflow.id, user.id, facts={"damage_type": "fire"})

    cases, total = di_case_service.list_cases(db, org.id, workflow_id=workflow.id, q="water")

    assert total == 1
    assert cases[0].facts["damage_type"] == "water damage"


def test_case_search_is_scoped_to_organization(db):
    org_a = _org(db)
    org_b = _org(db)
    user_a = _user(db, org_a.id)
    user_b = _user(db, org_b.id)
    workflow_a = _workflow(db, org_a, user_a)
    workflow_b = _workflow(db, org_b, user_b)
    di_case_service.create_case(db, org_a.id, workflow_a.id, user_a.id, facts={}, external_ref="SHARED-REF")
    di_case_service.create_case(db, org_b.id, workflow_b.id, user_b.id, facts={}, external_ref="SHARED-REF")

    cases, total = di_case_service.list_cases(db, org_a.id, q="SHARED-REF")
    assert total == 1
    assert cases[0].organization_id == org_a.id


def test_case_search_with_no_query_returns_everything(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    di_case_service.create_case(db, org.id, workflow.id, user.id, facts={})
    di_case_service.create_case(db, org.id, workflow.id, user.id, facts={})

    cases, total = di_case_service.list_cases(db, org.id, workflow_id=workflow.id, q=None)
    assert total == 2


# --- K. AI-assisted discovery -----------------------------------------------


class _RaisingDiscoveryProvider:
    def discover(self, cases):
        raise RuntimeError("provider exploded")


def _conflicting_cases(db, org, workflow, user):
    """Two near-identical cases (differ only in `amount`) decided
    oppositely -- guaranteed to trigger FakeDiscoveryProvider's
    conflicting-outcome heuristic (confidence 'high', category
    'conflicting_rules', exactly one nested question)."""
    c1 = di_case_service.create_case(
        db, org.id, workflow.id, user.id, facts={"amount": 90, "photo": False},
        human_decision={"decision": "approve"},
    )
    c2 = di_case_service.create_case(
        db, org.id, workflow.id, user.id, facts={"amount": 95, "photo": False},
        human_decision={"decision": "deny"},
    )
    return c1, c2


def _run_discovery(db, org, workflow, user, provider=None):
    return di_discovery_service.create_and_run_discovery(
        db, org.id, workflow.id, user.id, provider or FakeDiscoveryProvider(), "fake",
    )


def _pattern_and_question_suggestions(db, org, run):
    suggestions = di_discovery_service.list_suggestions_for_run(db, run.id, org.id)
    patterns = [s for s in suggestions if s.kind == "pattern"]
    questions = [s for s in suggestions if s.kind == "question"]
    return patterns, questions


def test_discovery_run_with_fake_provider_produces_real_suggestions_from_persisted_cases(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    _conflicting_cases(db, org, workflow, user)

    run = _run_discovery(db, org, workflow, user)

    assert run.status == "completed"
    assert run.provider_used == "fake"
    assert run.cases_analyzed_count == 2
    assert run.error_message is None
    assert run.completed_at is not None

    patterns, questions = _pattern_and_question_suggestions(db, org, run)
    assert len(patterns) == 1
    pattern = patterns[0]
    assert pattern.status == "suggested"
    assert pattern.confidence == "high"
    assert pattern.category == "conflicting_rules"
    assert len(pattern.supporting_case_ids) == 2
    assert len(questions) == 1
    assert questions[0].linked_pattern_id == pattern.id


def test_discovery_run_is_bounded_to_max_discovery_cases(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    for i in range(di_discovery_service.MAX_DISCOVERY_CASES + 5):
        di_case_service.create_case(db, org.id, workflow.id, user.id, facts={"n": i})

    run = _run_discovery(db, org, workflow, user)

    assert run.cases_analyzed_count == di_discovery_service.MAX_DISCOVERY_CASES


def test_failed_provider_records_a_failed_run_with_error_message_and_no_suggestions(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    _conflicting_cases(db, org, workflow, user)

    run = _run_discovery(db, org, workflow, user, provider=_RaisingDiscoveryProvider())

    assert run.status == "failed"
    assert "provider exploded" in run.error_message
    patterns, questions = _pattern_and_question_suggestions(db, org, run)
    assert patterns == []
    assert questions == []


def test_discovery_run_start_and_complete_are_audited(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    _conflicting_cases(db, org, workflow, user)

    run = _run_discovery(db, org, workflow, user)

    events = di_audit_service.list_events_for_entity(db, org.id, "DIDiscoveryRun", run.id)
    actions = {e.action for e in events}
    assert "start" in actions
    assert "complete" in actions


def test_accept_pattern_suggestion_creates_real_pattern_with_linkage_and_audit_trail(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    c1, c2 = _conflicting_cases(db, org, workflow, user)
    run = _run_discovery(db, org, workflow, user)
    patterns, _questions = _pattern_and_question_suggestions(db, org, run)
    suggestion = patterns[0]

    created = di_discovery_service.accept_suggestion(db, suggestion.id, org.id, user.id)

    assert isinstance(created, DIPattern)
    assert created.source_suggestion_id == suggestion.id
    assert created.category == "conflicting_rules"
    linked_case_ids = set(di_pattern_service.list_linked_cases(db, created.id, org.id))
    assert linked_case_ids == {c1.id, c2.id}

    db.refresh(suggestion)
    assert suggestion.status == "accepted"
    assert suggestion.reviewed_by_user_id == user.id
    assert suggestion.reviewed_at is not None

    suggestion_events = di_audit_service.list_events_for_entity(db, org.id, "DIDiscoverySuggestion", suggestion.id)
    assert any(e.action == "accept" for e in suggestion_events)
    pattern_events = di_audit_service.list_events_for_entity(db, org.id, "DIPattern", created.id)
    assert any(e.action == "create" and e.new_value.get("source_suggestion_id") == str(suggestion.id) for e in pattern_events)


def test_accept_question_suggestion_linked_to_an_accepted_pattern_links_the_real_pattern(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    _conflicting_cases(db, org, workflow, user)
    run = _run_discovery(db, org, workflow, user)
    patterns, questions = _pattern_and_question_suggestions(db, org, run)
    pattern_suggestion, question_suggestion = patterns[0], questions[0]

    real_pattern = di_discovery_service.accept_suggestion(db, pattern_suggestion.id, org.id, user.id)
    created_question = di_discovery_service.accept_suggestion(db, question_suggestion.id, org.id, user.id)

    assert isinstance(created_question, DIQuestion)
    assert created_question.source_suggestion_id == question_suggestion.id
    linked_patterns = di_question_service.list_linked_patterns(db, created_question.id, org.id)
    assert [p.id for p in linked_patterns] == [real_pattern.id]


def test_accept_question_suggestion_linked_to_an_unaccepted_pattern_is_rejected(db):
    """The brief's own required rejection: never silently drop the link."""
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    _conflicting_cases(db, org, workflow, user)
    run = _run_discovery(db, org, workflow, user)
    patterns, questions = _pattern_and_question_suggestions(db, org, run)
    question_suggestion = questions[0]
    assert patterns[0].status == "suggested"  # deliberately not accepted first

    with pytest.raises(LinkedPatternNotAcceptedError):
        di_discovery_service.accept_suggestion(db, question_suggestion.id, org.id, user.id)

    # Nothing was created or mutated by the rejected attempt.
    db.refresh(question_suggestion)
    assert question_suggestion.status == "suggested"
    existing = db.query(DIQuestion).filter(DIQuestion.source_suggestion_id == question_suggestion.id).first()
    assert existing is None


def test_dismiss_suggestion_creates_nothing(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    _conflicting_cases(db, org, workflow, user)
    run = _run_discovery(db, org, workflow, user)
    patterns, _questions = _pattern_and_question_suggestions(db, org, run)
    suggestion = patterns[0]

    dismissed = di_discovery_service.dismiss_suggestion(db, suggestion.id, org.id, user.id)

    assert dismissed.status == "dismissed"
    assert dismissed.reviewed_by_user_id == user.id
    assert dismissed.reviewed_at is not None
    existing = db.query(DIPattern).filter(DIPattern.source_suggestion_id == suggestion.id).first()
    assert existing is None

    dismiss_events = di_audit_service.list_events_for_entity(db, org.id, "DIDiscoverySuggestion", suggestion.id)
    assert any(e.action == "dismiss" for e in dismiss_events)


def test_accepting_an_already_accepted_suggestion_is_rejected(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    _conflicting_cases(db, org, workflow, user)
    run = _run_discovery(db, org, workflow, user)
    patterns, _questions = _pattern_and_question_suggestions(db, org, run)
    suggestion = patterns[0]

    di_discovery_service.accept_suggestion(db, suggestion.id, org.id, user.id)

    with pytest.raises(SuggestionNotPendingError):
        di_discovery_service.accept_suggestion(db, suggestion.id, org.id, user.id)


def test_dismissing_an_already_dismissed_suggestion_is_rejected(db):
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    _conflicting_cases(db, org, workflow, user)
    run = _run_discovery(db, org, workflow, user)
    patterns, _questions = _pattern_and_question_suggestions(db, org, run)
    suggestion = patterns[0]

    di_discovery_service.dismiss_suggestion(db, suggestion.id, org.id, user.id)

    with pytest.raises(SuggestionNotPendingError):
        di_discovery_service.dismiss_suggestion(db, suggestion.id, org.id, user.id)


def test_cross_organization_suggestion_read_is_not_found(db):
    org_a = _org(db)
    org_b = _org(db)
    user_a = _user(db, org_a.id)
    user_b = _user(db, org_b.id)
    workflow_a = _workflow(db, org_a, user_a)
    _conflicting_cases(db, org_a, workflow_a, user_a)
    run = _run_discovery(db, org_a, workflow_a, user_a)
    patterns, _questions = _pattern_and_question_suggestions(db, org_a, run)
    suggestion = patterns[0]

    with pytest.raises(SuggestionNotFoundError):
        di_discovery_service.get_suggestion(db, suggestion.id, org_b.id)
    with pytest.raises(SuggestionNotFoundError):
        di_discovery_service.accept_suggestion(db, suggestion.id, org_b.id, user_b.id)


def test_cross_organization_discovery_run_read_is_not_found(db):
    org_a = _org(db)
    org_b = _org(db)
    user_a = _user(db, org_a.id)
    workflow_a = _workflow(db, org_a, user_a)
    _conflicting_cases(db, org_a, workflow_a, user_a)
    run = _run_discovery(db, org_a, workflow_a, user_a)

    with pytest.raises(DiscoveryRunNotFoundError):
        di_discovery_service.get_discovery_run(db, run.id, org_b.id)


def test_claude_discovery_response_round_trips_into_real_pattern_and_question_rows(db):
    """Exercises the Claude-shaped path end to end without a network call:
    a well-formed DiscoveryResult (the same type ClaudeDiscoveryProvider.
    discover returns after its own strict validation) persists and accepts
    identically to the fake provider's output -- the service layer has no
    special-casing per provider."""
    org = _org(db)
    user = _user(db, org.id)
    workflow = _workflow(db, org, user)
    case = di_case_service.create_case(
        db, org.id, workflow.id, user.id, facts={"amount": 10000}, human_decision={"decision": "deny"},
    )

    class _ScriptedProvider:
        def discover(self, cases: list[CaseForDiscovery]) -> DiscoveryResult:
            from app.domain.decision_intelligence.ai_discovery.provider import CandidatePattern, CandidateQuestion

            return DiscoveryResult(
                patterns=(
                    CandidatePattern(
                        title="High-value cases need an explicit threshold policy",
                        description="desc", rationale="rationale citing the case", confidence="medium",
                        category="unclear_policy", supporting_case_ids=(cases[0].id,),
                        questions=(
                            CandidateQuestion(
                                title="What threshold requires executive sign-off?",
                                description="qdesc", rationale="qrationale", supporting_case_ids=(cases[0].id,),
                            ),
                        ),
                    ),
                )
            )

    run = di_discovery_service.create_and_run_discovery(
        db, org.id, workflow.id, user.id, _ScriptedProvider(), "claude",
    )
    assert run.status == "completed"
    assert run.provider_used == "claude"

    patterns, questions = _pattern_and_question_suggestions(db, org, run)
    assert len(patterns) == 1 and len(questions) == 1
    assert patterns[0].category == "unclear_policy"

    created_pattern = di_discovery_service.accept_suggestion(db, patterns[0].id, org.id, user.id)
    assert di_pattern_service.list_linked_cases(db, created_pattern.id, org.id) == [case.id]
