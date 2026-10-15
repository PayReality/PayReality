"""Decision Intelligence: AI-assisted discovery of recurring uncertainty
patterns and candidate priority questions (DIDiscoveryRun,
DIDiscoverySuggestion -- domain/decision_intelligence/ai_discovery/).

HARD, NON-NEGOTIABLE CONSTRAINT (the entire point of this feature, not a
convention to be relaxed later): `create_and_run_discovery` NEVER writes a
real DIPattern or DIQuestion row -- only DIDiscoverySuggestion rows, which
carry zero authority on their own. The ONLY path from a suggestion to a
real, authoritative Pattern/Question is `accept_suggestion`, an explicit,
separately-permissioned human action. There is no "auto-accept above
confidence X" anywhere in this module, and there must never be one added
here without a product decision to relax this constraint outright.

Runs synchronously, in the same request as its own creation -- matching
di_replay_service.create_and_run_replay's own documented choice at this
product's scale (see that module's docstring for the identical reasoning;
a provider call here is bounded by MAX_DISCOVERY_CASES below, not an
unbounded live stream)."""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DICase, DIDiscoveryRun, DIDiscoverySuggestion, DIPattern, DIQuestion
from app.domain.decision_intelligence.ai_discovery.provider import CaseForDiscovery, DiscoveryProvider
from app.services import di_audit_service, di_case_service, di_pattern_service, di_question_service, di_workflow_service

# Demo-scale bound (brief's own explicit requirement: no silent unbounded
# processing). Reuses this module's own already-established default page
# size -- di_case_service.list_cases/di_pattern_service.list_patterns/
# di_question_service.list_questions/di_replay_service's own
# list endpoints all default to limit=100 -- rather than inventing a new
# number: a discovery run analyses at most the 100 most recently created
# cases in its workflow. This is a real, server-enforced bound (not a
# frontend-only convenience default); a workflow with more than 100 cases
# still only has its most recent 100 considered per run.
MAX_DISCOVERY_CASES = 100


class DiscoveryRunNotFoundError(Exception):
    pass


class SuggestionNotFoundError(Exception):
    pass


class SuggestionNotPendingError(Exception):
    def __init__(self, suggestion_id: uuid.UUID, status: str):
        self.suggestion_id = suggestion_id
        self.status = status
        super().__init__(f"suggestion {suggestion_id} is already '{status}', not 'suggested'")


class LinkedPatternNotFoundError(Exception):
    pass


class LinkedPatternNotAcceptedError(Exception):
    """The brief's own required rejection: a 'question'-kind suggestion
    whose linked_pattern_id points at a sibling 'pattern'-kind suggestion
    that has not itself been accepted yet is rejected outright, never
    silently accepted with the link dropped."""

    def __init__(self, linked_suggestion_id: uuid.UUID, status: str):
        self.linked_suggestion_id = linked_suggestion_id
        self.status = status
        super().__init__(
            f"linked pattern suggestion {linked_suggestion_id} is '{status}', not 'accepted' -- "
            "accept that pattern suggestion first"
        )


def _case_for_discovery(case: DICase) -> CaseForDiscovery:
    """The one, narrow mapping from a real DICase row to this feature's
    provider-facing input shape -- see provider.CaseForDiscovery's own
    docstring for exactly which fields are (and are deliberately are not)
    carried across."""
    return CaseForDiscovery(
        id=str(case.id),
        facts=case.facts or {},
        escalation_reason=case.escalation_reason,
        human_decision=case.human_decision,
        outcome=case.outcome,
        status=case.status,
    )


def create_and_run_discovery(
    db: Session,
    organization_id: uuid.UUID,
    workflow_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    provider: DiscoveryProvider,
    provider_used: str,
) -> DIDiscoveryRun:
    """Creates a DIDiscoveryRun, loads up to MAX_DISCOVERY_CASES of this
    workflow's own cases (most recently created first, the same ordering
    di_case_service.list_cases already uses everywhere else), calls
    `provider.discover(...)`, and persists its result as
    DIDiscoverySuggestion rows -- never a real DIPattern/DIQuestion (see
    this module's own docstring). A provider failure (e.g. Claude raising
    after exhausting its own bounded retries) is caught and recorded as a
    'failed' run with `error_message`, never left to crash the request or
    to silently report zero suggestions as if the run had genuinely found
    none."""
    di_workflow_service.get_workflow(db, workflow_id, organization_id)

    cases, _total = di_case_service.list_cases(
        db, organization_id, workflow_id=workflow_id, limit=MAX_DISCOVERY_CASES
    )

    run = DIDiscoveryRun(
        organization_id=organization_id,
        workflow_id=workflow_id,
        provider_used=provider_used,
        status="pending",
        created_by_user_id=created_by_user_id,
    )
    db.add(run)
    db.flush()

    di_audit_service.record_event(
        db, organization_id, created_by_user_id, action="start", entity_type="DIDiscoveryRun", entity_id=run.id,
        new_value={"workflow_id": str(workflow_id), "provider_used": provider_used, "cases_considered": len(cases)},
    )
    db.commit()
    db.refresh(run)

    run.status = "running"
    db.commit()

    try:
        result = provider.discover([_case_for_discovery(c) for c in cases])
    except Exception as e:  # noqa: BLE001 -- a provider failure must fail this run, never crash the request
        run.status = "failed"
        run.error_message = str(e)
        run.cases_analyzed_count = len(cases)
        run.completed_at = datetime.now(timezone.utc)
        db.commit()
        di_audit_service.record_event(
            db, organization_id, created_by_user_id, action="fail", entity_type="DIDiscoveryRun",
            entity_id=run.id, new_value={"error_message": run.error_message},
        )
        db.commit()
        db.refresh(run)
        return run

    suggestion_count = 0
    for pattern in result.patterns:
        pattern_row = DIDiscoverySuggestion(
            discovery_run_id=run.id,
            kind="pattern",
            title=pattern.title,
            description=pattern.description,
            supporting_case_ids=list(pattern.supporting_case_ids),
            rationale=pattern.rationale,
            confidence=pattern.confidence,
            category=pattern.category,
            alternative_explanations=list(pattern.alternative_explanations) or None,
        )
        db.add(pattern_row)
        db.flush()
        suggestion_count += 1

        for question in pattern.questions:
            # A question with no case ids of its own (CandidateQuestion.
            # supporting_case_ids may legitimately be empty -- see that
            # dataclass's own docstring) inherits its parent pattern's
            # evidence rather than being persisted ungrounded.
            question_case_ids = list(question.supporting_case_ids) or list(pattern.supporting_case_ids)
            db.add(
                DIDiscoverySuggestion(
                    discovery_run_id=run.id,
                    kind="question",
                    title=question.title,
                    description=question.description,
                    supporting_case_ids=question_case_ids,
                    rationale=question.rationale,
                    confidence=None,  # CandidateQuestion is deliberately never confidence-scored
                    category=None,  # DIQuestion has no category of its own
                    linked_pattern_id=pattern_row.id,
                    candidate_explanation=question.candidate_explanation,
                    alternative_explanations=list(question.alternative_explanations) or None,
                    missing_evidence=list(question.missing_evidence) or None,
                    potential_impact=question.potential_impact,
                )
            )
            suggestion_count += 1

    run.status = "completed"
    run.cases_analyzed_count = len(cases)
    run.completed_at = datetime.now(timezone.utc)
    db.commit()

    di_audit_service.record_event(
        db, organization_id, created_by_user_id, action="complete", entity_type="DIDiscoveryRun", entity_id=run.id,
        new_value={"cases_analyzed_count": len(cases), "suggestion_count": suggestion_count},
    )
    db.commit()
    db.refresh(run)
    return run


def get_discovery_run(db: Session, discovery_run_id: uuid.UUID, organization_id: uuid.UUID) -> DIDiscoveryRun:
    run = db.get(DIDiscoveryRun, discovery_run_id)
    if run is None or run.organization_id != organization_id:
        raise DiscoveryRunNotFoundError(str(discovery_run_id))
    return run


def list_discovery_runs(
    db: Session,
    organization_id: uuid.UUID,
    workflow_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[DIDiscoveryRun], int]:
    stmt = select(DIDiscoveryRun).where(DIDiscoveryRun.organization_id == organization_id)
    if workflow_id is not None:
        stmt = stmt.where(DIDiscoveryRun.workflow_id == workflow_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(DIDiscoveryRun.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt)), total


def list_suggestions_for_run(
    db: Session, discovery_run_id: uuid.UUID, organization_id: uuid.UUID
) -> list[DIDiscoverySuggestion]:
    get_discovery_run(db, discovery_run_id, organization_id)  # raises if wrong org / missing
    stmt = (
        select(DIDiscoverySuggestion)
        .where(DIDiscoverySuggestion.discovery_run_id == discovery_run_id)
        .order_by(DIDiscoverySuggestion.created_at)
    )
    return list(db.scalars(stmt))


def get_suggestion(db: Session, suggestion_id: uuid.UUID, organization_id: uuid.UUID) -> DIDiscoverySuggestion:
    suggestion = db.get(DIDiscoverySuggestion, suggestion_id)
    if suggestion is None:
        raise SuggestionNotFoundError(str(suggestion_id))
    run = db.get(DIDiscoveryRun, suggestion.discovery_run_id)
    if run is None or run.organization_id != organization_id:
        raise SuggestionNotFoundError(str(suggestion_id))
    return suggestion


def _resolve_linked_real_pattern_id(
    db: Session, suggestion: DIDiscoverySuggestion, organization_id: uuid.UUID
) -> uuid.UUID:
    """Resolves a 'question'-kind suggestion's `linked_pattern_id` to a
    real DIPattern id, or raises -- never silently drops the link (the
    brief's own explicit requirement). See DIDiscoverySuggestion's model
    docstring (app/db/models.py) for why `linked_pattern_id` isn't a plain
    foreign key: it may point at either a sibling DIDiscoverySuggestion
    (the only case either shipped provider actually produces -- a pattern
    and its own resolving question, proposed together in the same run) or
    directly at a real, already-accepted DIPattern (the brief's own stated
    "may itself be... an already-accepted real Pattern" case, for a future
    provider that cross-references prior acceptances -- not one either
    shipped provider populates this way today)."""
    linked_id = suggestion.linked_pattern_id

    sibling = db.get(DIDiscoverySuggestion, linked_id)
    if sibling is not None and sibling.kind == "pattern":
        sibling_run = db.get(DIDiscoveryRun, sibling.discovery_run_id)
        if sibling_run is None or sibling_run.organization_id != organization_id:
            raise LinkedPatternNotFoundError(str(linked_id))
        if sibling.status != "accepted":
            raise LinkedPatternNotAcceptedError(linked_id, sibling.status)
        real_pattern = db.scalar(select(DIPattern).where(DIPattern.source_suggestion_id == sibling.id))
        if real_pattern is None:
            # Unreachable in practice -- accept_suggestion always creates
            # the real Pattern in the same transaction it marks the
            # sibling 'accepted' -- but fail loudly, not silently, if it
            # ever happens (e.g. a future direct DB edit).
            raise LinkedPatternNotFoundError(str(linked_id))
        return real_pattern.id

    real_pattern = db.get(DIPattern, linked_id)
    if real_pattern is not None and real_pattern.organization_id == organization_id:
        return real_pattern.id

    raise LinkedPatternNotFoundError(str(linked_id))


#: Beyond this many other workflow cases scanned for a "potentially
#: affected" match, stop -- the same demo-scale bound discipline as
#: MAX_DISCOVERY_CASES above, so accepting one suggestion can never touch
#: an unbounded number of rows.
MAX_POTENTIALLY_AFFECTED_SCAN = 200


def _compute_potentially_affected(
    db: Session, organization_id: uuid.UUID, workflow_id: uuid.UUID, supporting_case_ids: list[uuid.UUID]
) -> list[tuple[uuid.UUID, str]]:
    """An explicit, reviewable relevance criterion, not a model inference:
    find every recorded fact key on which the cited (supporting) cases
    don't all agree -- either a differing value or one case recording it
    and another not (the same "differing" notion fake_provider's own
    heuristics already use). Any OTHER case in the same workflow that
    records at least one of those same keys shares the exact condition
    this suggestion is about, so answering the question could plausibly
    affect it too -- "potentially", never "will". Returns
    (case_id, reason) pairs; the reason names the specific shared key(s),
    so a reviewer can check the claim directly rather than trust a label.

    Deliberately simple and bounded (brief's own instruction: no new
    enterprise graph or complex subsystem) -- this is one query plus one
    set-membership check per candidate case, nothing more."""
    supporting_cases = [db.get(DICase, cid) for cid in supporting_case_ids]
    supporting_cases = [c for c in supporting_cases if c is not None]
    if not supporting_cases:
        return []

    all_keys: set[str] = set()
    for c in supporting_cases:
        all_keys |= set((c.facts or {}).keys())

    differing_keys = sorted(
        k for k in all_keys
        if len({json.dumps((c.facts or {}).get(k), sort_keys=True, default=str) for c in supporting_cases}) > 1
    )
    if not differing_keys:
        return []

    supporting_ids = {c.id for c in supporting_cases}
    other_cases, _ = di_case_service.list_cases(
        db, organization_id, workflow_id=workflow_id, limit=MAX_POTENTIALLY_AFFECTED_SCAN
    )

    affected: list[tuple[uuid.UUID, str]] = []
    for case in other_cases:
        if case.id in supporting_ids:
            continue
        shared = sorted(k for k in differing_keys if k in (case.facts or {}))
        if shared:
            affected.append(
                (case.id, f"shares fact key(s) {', '.join(shared)}, which distinguished the cited cases")
            )
    return affected


def _link_cases_with_relevance(
    link_fn, db: Session, parent_id: uuid.UUID, organization_id: uuid.UUID,
    workflow_id: uuid.UUID, supporting_case_ids: list[uuid.UUID],
) -> None:
    """Shared by both the pattern and question branches of
    accept_suggestion: link every cited case as "supporting", then
    compute and link "potentially_affected" cases via the explicit
    predicate above. Never silently overwrites an existing link's kind
    (link_case is a no-op on an existing row) -- a case already linked by
    a prior action keeps whatever kind it already has."""
    for case_id in supporting_case_ids:
        link_fn(db, parent_id, case_id, organization_id, kind="supporting", reason="cited by discovery suggestion")
    for case_id, reason in _compute_potentially_affected(db, organization_id, workflow_id, supporting_case_ids):
        link_fn(db, parent_id, case_id, organization_id, kind="potentially_affected", reason=reason)


def accept_suggestion(
    db: Session, suggestion_id: uuid.UUID, organization_id: uuid.UUID, actor_user_id: uuid.UUID
) -> DIPattern | DIQuestion:
    """Creates a REAL, authoritative DIPattern or DIQuestion from a
    DIDiscoverySuggestion -- the ONLY path by which this feature's output
    ever becomes authoritative (see this module's own top-of-file
    docstring). The created row's `source_suggestion_id` is the queryable
    trace back to the suggestion (and, via it, the DIDiscoveryRun) it came
    from, per the brief's own requirement.

    Every linked-pattern resolution (see `_resolve_linked_real_pattern_id`)
    happens BEFORE any row is created or mutated, so a rejection here (an
    unaccepted sibling pattern suggestion, or no resolvable pattern at
    all) leaves nothing half-committed."""
    suggestion = get_suggestion(db, suggestion_id, organization_id)
    if suggestion.status != "suggested":
        raise SuggestionNotPendingError(suggestion_id, suggestion.status)

    run = get_discovery_run(db, suggestion.discovery_run_id, organization_id)
    case_ids = [uuid.UUID(cid) for cid in suggestion.supporting_case_ids]

    if suggestion.kind == "pattern":
        pattern = DIPattern(
            organization_id=organization_id,
            workflow_id=run.workflow_id,
            created_by_user_id=actor_user_id,
            name=suggestion.title,
            description=suggestion.description,
            category=suggestion.category or "other",
            proposed_explanation=suggestion.rationale,
            alternative_explanations=suggestion.alternative_explanations,
            confidence=suggestion.confidence,
            source_suggestion_id=suggestion.id,
        )
        db.add(pattern)
        db.flush()
        _link_cases_with_relevance(
            di_pattern_service.link_case, db, pattern.id, organization_id, run.workflow_id, case_ids
        )
        created, entity_type = pattern, "DIPattern"
    else:
        linked_real_pattern_id = None
        if suggestion.linked_pattern_id is not None:
            # Resolved up front, before any mutation -- see docstring.
            linked_real_pattern_id = _resolve_linked_real_pattern_id(db, suggestion, organization_id)

        question = DIQuestion(
            organization_id=organization_id,
            workflow_id=run.workflow_id,
            created_by_user_id=actor_user_id,
            title=suggestion.title,
            description=suggestion.description,
            source_suggestion_id=suggestion.id,
            candidate_explanation=suggestion.candidate_explanation,
            alternative_explanations=suggestion.alternative_explanations,
            missing_evidence=suggestion.missing_evidence,
            potential_impact=suggestion.potential_impact,
        )
        db.add(question)
        db.flush()
        _link_cases_with_relevance(
            di_question_service.link_case, db, question.id, organization_id, run.workflow_id, case_ids
        )
        if linked_real_pattern_id is not None:
            di_question_service.link_pattern(db, question.id, linked_real_pattern_id, organization_id)
        created, entity_type = question, "DIQuestion"

    suggestion.status = "accepted"
    suggestion.reviewed_by_user_id = actor_user_id
    suggestion.reviewed_at = datetime.now(timezone.utc)
    db.add(suggestion)

    di_audit_service.record_event(
        db, organization_id, actor_user_id, action="accept", entity_type="DIDiscoverySuggestion",
        entity_id=suggestion.id,
        new_value={"created_entity_type": entity_type, "created_entity_id": str(created.id)},
    )
    di_audit_service.record_event(
        db, organization_id, actor_user_id, action="create", entity_type=entity_type, entity_id=created.id,
        new_value={
            "source_suggestion_id": str(suggestion.id),
            "source_discovery_run_id": str(run.id),
        },
    )
    db.commit()
    db.refresh(created)
    return created


def dismiss_suggestion(
    db: Session, suggestion_id: uuid.UUID, organization_id: uuid.UUID, actor_user_id: uuid.UUID
) -> DIDiscoverySuggestion:
    """Marks a suggestion 'dismissed' -- final, like `accept_suggestion`
    (a suggestion is reviewed exactly once; there is no "un-dismiss").
    Creates nothing: the brief's own explicit requirement that dismissing
    a suggestion must never create a real Pattern/Question, not even a
    draft one."""
    suggestion = get_suggestion(db, suggestion_id, organization_id)
    if suggestion.status != "suggested":
        raise SuggestionNotPendingError(suggestion_id, suggestion.status)

    suggestion.status = "dismissed"
    suggestion.reviewed_by_user_id = actor_user_id
    suggestion.reviewed_at = datetime.now(timezone.utc)
    db.add(suggestion)

    di_audit_service.record_event(
        db, organization_id, actor_user_id, action="dismiss", entity_type="DIDiscoverySuggestion",
        entity_id=suggestion.id, new_value={"status": "dismissed"},
    )
    db.commit()
    db.refresh(suggestion)
    return suggestion
