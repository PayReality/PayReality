import dataclasses
import logging
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    AuthorityConflict,
    AuthorityCorpus,
    AuthorityGap,
    AuthorityOperation,
    AuthorityPrincipal,
    AuthorityQuestion,
    AuthorityRelationship,
    AuthorityResource,
)
from app.db.models import Organization, User
from app.db.session import get_db
from app.dependencies import get_current_organization, get_current_user_if_session, require_permission
from app.domain.ai_authority_builder.azure_foundry_provider import (
    AzureFoundryAuthorityGraphExtractionProvider,
)
from app.domain.ai_authority_builder.claude_provider import ClaudeAuthorityGraphExtractionProvider
from app.domain.ai_authority_builder.fake_provider import FakeAuthorityGraphExtractionProvider
from app.domain.ai_policy_builder.text_extraction import UnsupportedFormatError, detect_format
from app.domain.rbac.permissions import Permission
from app.schemas.ai_authority_builder import (
    AnswerQuestionRequest,
    ApproveGraphRequest,
    CompiledPolicySummaryResponse,
    ConflictResponse,
    CorpusResponse,
    CoverageResponse,
    GapResponse,
    GraphApprovalDiffResponse,
    GraphApprovalDiffSummary,
    GraphApprovalRef,
    GraphApprovalResponse,
    GraphDiffResponse,
    GraphSummaryResponse,
    MissingInformationItem,
    OperationResponse,
    PrincipalCandidateResponse,
    PrincipalResponse,
    ProviderStatusResponse,
    QuestionResponse,
    RelationshipResponse,
    ResolvePrincipalRequest,
    ResourceResponse,
)
from app.services import ai_authority_builder_service as svc
from app.services import runtime_policy_service
from app.services.ai_authority_builder_service import (
    AlreadyResolvedError,
    ApprovalNotFoundError,
    AuthorityPrincipalNotFoundError,
    AuthorityRelationshipNotFoundError,
    ConcurrentApprovalConflictError,
    CorpusNotFoundError,
    CrossOrganizationMatchError,
    NoPredecessorApprovalError,
    PrincipalNotFoundError,
    QuestionNotFoundError,
    RelationshipNotResolvableError,
    RelationshipNotResolvedError,
)

router = APIRouter(prefix="/v1/ai-authority-builder", tags=["ai-authority-builder"])


def _provider():
    # Authority Intelligence Program, Phase 1: Azure AI Foundry is
    # preferred once configured, but ANTHROPIC_API_KEY alone keeps
    # working exactly as before on any environment that hasn't had
    # modules/ai-foundry applied yet -- this ordering is what makes the
    # rollout backward-compatible rather than a breaking cutover.
    if settings.azure_ai_foundry_endpoint:
        return AzureFoundryAuthorityGraphExtractionProvider()
    if settings.anthropic_api_key:
        return ClaudeAuthorityGraphExtractionProvider()
    return FakeAuthorityGraphExtractionProvider()


def _corpus_to_response(corpus: AuthorityCorpus, document_count: int) -> CorpusResponse:
    return CorpusResponse(
        corpus_id=str(corpus.id),
        name=corpus.name,
        status=corpus.status,
        error=corpus.error,
        document_count=document_count,
        created_at=corpus.created_at,
    )


def _explainability_kwargs(row) -> dict:
    return {
        "clause_reference": row.clause_reference,
        "extraction_reasoning": row.extraction_reasoning,
        "detected_assumptions": list(row.detected_assumptions or []),
        "ambiguity_flags": list(row.ambiguity_flags or []),
    }


def _principal_to_response(p: AuthorityPrincipal) -> PrincipalResponse:
    return PrincipalResponse(
        id=str(p.id), name=p.name, role=p.role, reports_to=p.reports_to, confidence=p.confidence,
        source_excerpt=p.source_excerpt, source_location=p.source_location,
        resolved_principal_id=str(p.resolved_principal_id) if p.resolved_principal_id else None,
        **_explainability_kwargs(p),
    )


def _resource_to_response(r: AuthorityResource) -> ResourceResponse:
    return ResourceResponse(
        id=str(r.id), name=r.name, description=r.description, confidence=r.confidence,
        source_excerpt=r.source_excerpt, source_location=r.source_location,
        **_explainability_kwargs(r),
    )


def _operation_to_response(o: AuthorityOperation) -> OperationResponse:
    return OperationResponse(
        id=str(o.id), name=o.name, description=o.description, confidence=o.confidence,
        source_excerpt=o.source_excerpt, source_location=o.source_location,
        **_explainability_kwargs(o),
    )


def _relationship_to_response(r: AuthorityRelationship) -> RelationshipResponse:
    return RelationshipResponse(
        id=str(r.id), kind=r.kind, from_principal=r.from_principal, to_principal=r.to_principal,
        description=r.description, confidence=r.confidence,
        source_excerpt=r.source_excerpt, source_location=r.source_location,
        from_principal_id=str(r.from_principal_id) if r.from_principal_id else None,
        to_principal_id=str(r.to_principal_id) if r.to_principal_id else None,
        status=r.status,
        **_explainability_kwargs(r),
    )


def _conflict_to_response(c: AuthorityConflict) -> ConflictResponse:
    return ConflictResponse(
        id=str(c.id), description=c.description, reasoning=c.reasoning, confidence=c.confidence,
        conflict_type=c.conflict_type, reviewer_recommendation=c.reviewer_recommendation,
    )


def _gap_to_response(g: AuthorityGap) -> GapResponse:
    return GapResponse(
        id=str(g.id), description=g.description, confidence=g.confidence,
        source_excerpt=g.source_excerpt, source_location=g.source_location,
    )


def _question_to_response(q: AuthorityQuestion) -> QuestionResponse:
    return QuestionResponse(id=str(q.id), question=q.question, context=q.context, answered=q.answered, answer=q.answer)


@router.get("/status", response_model=ProviderStatusResponse)
def get_status():
    """Whether this deployment currently has a real provider configured
    (Azure AI Foundry or Anthropic), so the frontend can be honest with
    users about whether they're looking at real extraction or
    illustrative sample output."""
    return ProviderStatusResponse(
        ai_enabled=bool(settings.azure_ai_foundry_endpoint or settings.anthropic_api_key)
    )


@router.post(
    "/corpora", response_model=CorpusResponse, status_code=201,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
async def create_corpus(
    files: list[UploadFile],
    name: str = Form(...),
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_current_organization),
):
    """AI_AUTHORITY_BUILDER_ARCHITECTURE.md: every file in `files` is
    treated as one Authority Corpus and analyzed together, never
    document-by-document. Extraction runs synchronously, the same
    choice every extraction pipeline in this platform already makes.

    Authority-as-a-continuous-object, Stage E: the corpus is now scoped
    to the caller's organisation (get_current_organization already
    supports the Operator Key, session, and API-key paths identically to
    require_permission above). Everything discovered from it inherits
    that scope, which is what makes Principal resolution below safe to
    do automatically within an organisation and never across one."""
    corpus = svc.create_corpus(db, name=name, organization_id=organization.id)

    documents = []
    for file in files:
        try:
            format = detect_format(file.filename or "", file.content_type)
        except UnsupportedFormatError:
            raise HTTPException(status_code=422, detail=f"unsupported_format: {file.filename}")
        raw = await file.read()
        documents.append(svc.add_document(db, corpus, filename=file.filename or "document", format=format, raw=raw))

    try:
        svc.run_extraction(db, corpus, documents, _provider())
    except Exception:
        logging.getLogger("payreality.ai_authority_builder").exception(
            "extraction_failed corpus_id=%s", corpus.id
        )

    return _corpus_to_response(corpus, len(documents))


def _authorized_corpus(
    corpus_id: uuid.UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> AuthorityCorpus:
    """Milestone 1 (Security & Authorization Hardening): the single gate
    every corpus-scoped read endpoint below depends on. Every sub-resource
    (principals, resources, operations, relationships, conflicts, gaps,
    questions, coverage, missing-information, diff, approvals) is keyed
    purely off corpus_id with no organization column of its own, so
    gating here protects all of them transitively -- a corpus belonging
    to a different organization 404s identically to a corpus_id that
    doesn't exist at all, never distinguished, so this can't be used to
    probe for another org's corpus IDs."""
    try:
        corpus = svc.get_corpus(db, corpus_id)
    except CorpusNotFoundError:
        raise HTTPException(status_code=404, detail="corpus_not_found")
    if corpus.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="corpus_not_found")
    return corpus


def _corpus_owns(db: Session, corpus_id: uuid.UUID, organization_id: uuid.UUID) -> bool:
    corpus = db.get(AuthorityCorpus, corpus_id)
    return corpus is not None and corpus.organization_id == organization_id


def _authorized_authority_principal(
    authority_principal_id: uuid.UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> AuthorityPrincipal:
    """Milestone 3 (Enterprise Surface Isolation): the same "target
    object must belong to the caller's organization" gate _authorized_
    corpus already applies to corpus reads, extended to this discovery's
    OWN corpus -- `get_principal_candidates`/`resolve_principal` took no
    organization at all before this, verified and confirmed still true
    in MULTI_TENANT_ARCHITECTURE_VERIFICATION.md. A discovery whose
    corpus belongs to a different organization 404s identically to one
    that doesn't exist, matching _authorized_corpus's own convention."""
    discovery = db.get(AuthorityPrincipal, authority_principal_id)
    if discovery is None or not _corpus_owns(db, discovery.corpus_id, organization.id):
        raise HTTPException(status_code=404, detail="authority_principal_not_found")
    return discovery


def _authorized_relationship(
    relationship_id: uuid.UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> AuthorityRelationship:
    """Milestone 3: same gate as _authorized_authority_principal, for
    resolve_relationship/activate_relationship -- confirmed to have had
    no organization check of any kind before this."""
    relationship = db.get(AuthorityRelationship, relationship_id)
    if relationship is None or not _corpus_owns(db, relationship.corpus_id, organization.id):
        raise HTTPException(status_code=404, detail="relationship_not_found")
    return relationship


def _authorized_question(
    question_id: uuid.UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
) -> AuthorityQuestion:
    """Milestone 3: same gate, for answer_question -- confirmed to have
    had no organization check of any kind before this."""
    question = db.get(AuthorityQuestion, question_id)
    if question is None or not _corpus_owns(db, question.corpus_id, organization.id):
        raise HTTPException(status_code=404, detail="question_not_found")
    return question


@router.get(
    "/corpora", response_model=list[CorpusResponse],
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def list_corpora(
    organization: Organization = Depends(get_current_organization), db: Session = Depends(get_db)
):
    return [
        _corpus_to_response(c, len(svc.list_documents(db, c.id)))
        for c in svc.list_corpora(db)
        if c.organization_id == organization.id
    ]


@router.get(
    "/corpora/{corpus_id}", response_model=CorpusResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def get_corpus(corpus_id: uuid.UUID, corpus: AuthorityCorpus = Depends(_authorized_corpus), db: Session = Depends(get_db)):
    return _corpus_to_response(corpus, len(svc.list_documents(db, corpus_id)))


@router.get(
    "/corpora/{corpus_id}/summary", response_model=GraphSummaryResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def get_summary(
    corpus_id: uuid.UUID, corpus: AuthorityCorpus = Depends(_authorized_corpus), db: Session = Depends(get_db)
):
    """Counts only, matching AI_AUTHORITY_BUILDER_ARCHITECTURE.md's own
    example. Runtime Policy candidates are counted via the AI Policy
    Builder's own list_candidates(corpus_id=...), not a duplicated
    query."""
    from app.services import ai_policy_builder_service as policy_svc

    return GraphSummaryResponse(
        policy_count=len(policy_svc.list_candidates(db, corpus.organization_id, corpus_id=corpus_id)),
        principal_count=len(svc.list_principals(db, corpus_id)),
        resource_count=len(svc.list_resources(db, corpus_id)),
        operation_count=len(svc.list_operations(db, corpus_id)),
        relationship_count=len(svc.list_relationships(db, corpus_id)),
        conflict_count=len(svc.list_conflicts(db, corpus_id)),
        gap_count=len(svc.list_gaps(db, corpus_id)),
        question_count=len(svc.list_questions(db, corpus_id)),
    )


@router.get(
    "/corpora/{corpus_id}/principals", response_model=list[PrincipalResponse],
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def get_principals(corpus_id: uuid.UUID, _: AuthorityCorpus = Depends(_authorized_corpus), db: Session = Depends(get_db)):
    return [_principal_to_response(p) for p in svc.list_principals(db, corpus_id)]


@router.get(
    "/principals/{authority_principal_id}/candidates",
    response_model=list[PrincipalCandidateResponse],
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def get_principal_candidates(
    authority_principal_id: uuid.UUID,
    _: AuthorityPrincipal = Depends(_authorized_authority_principal),
    db: Session = Depends(get_db),
):
    """Stage E's reviewer workflow, step one: suggest, never apply.
    Empty list is a completely valid, common answer -- it means no
    existing Principal in this organisation matches by name, and the
    reviewer's next step is naturally 'create' rather than 'match'."""
    try:
        candidates = svc.find_principal_candidates(db, authority_principal_id)
    except AuthorityPrincipalNotFoundError:
        raise HTTPException(status_code=404, detail="authority_principal_not_found")
    return [
        PrincipalCandidateResponse(
            id=str(c.id), name=c.name, role=c.role,
            organization_id=str(c.organization_id) if c.organization_id else None,
        )
        for c in candidates
    ]


@router.post(
    "/principals/{authority_principal_id}/resolve",
    response_model=PrincipalResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def resolve_principal(
    authority_principal_id: uuid.UUID,
    body: ResolvePrincipalRequest,
    _: AuthorityPrincipal = Depends(_authorized_authority_principal),
    db: Session = Depends(get_db),
):
    """Stage E's reviewer workflow, step two: the only code path allowed
    to populate resolved_principal_id. Gated the same way promoting a
    candidate Rule already is -- this is the same kind of consequential,
    reviewed action."""
    try:
        principal_id = uuid.UUID(body.principal_id) if body.principal_id else None
        principal = svc.resolve_principal(
            db, authority_principal_id, action=body.action,
            principal_id=principal_id, name=body.name, role=body.role,
        )
    except AuthorityPrincipalNotFoundError:
        raise HTTPException(status_code=404, detail="authority_principal_not_found")
    except PrincipalNotFoundError:
        raise HTTPException(status_code=404, detail="principal_not_found")
    except AlreadyResolvedError:
        raise HTTPException(status_code=409, detail="already_resolved")
    except CrossOrganizationMatchError:
        raise HTTPException(status_code=409, detail="cross_organization_match")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    discovery = db.get(AuthorityPrincipal, authority_principal_id)
    return _principal_to_response(discovery)


@router.get(
    "/corpora/{corpus_id}/resources", response_model=list[ResourceResponse],
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def get_resources(corpus_id: uuid.UUID, _: AuthorityCorpus = Depends(_authorized_corpus), db: Session = Depends(get_db)):
    return [_resource_to_response(r) for r in svc.list_resources(db, corpus_id)]


@router.get(
    "/corpora/{corpus_id}/operations", response_model=list[OperationResponse],
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def get_operations(corpus_id: uuid.UUID, _: AuthorityCorpus = Depends(_authorized_corpus), db: Session = Depends(get_db)):
    return [_operation_to_response(o) for o in svc.list_operations(db, corpus_id)]


@router.get(
    "/corpora/{corpus_id}/relationships", response_model=list[RelationshipResponse],
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def get_relationships(corpus_id: uuid.UUID, _: AuthorityCorpus = Depends(_authorized_corpus), db: Session = Depends(get_db)):
    return [_relationship_to_response(r) for r in svc.list_relationships(db, corpus_id)]


@router.post(
    "/relationships/{relationship_id}/resolve",
    response_model=RelationshipResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def resolve_relationship(
    relationship_id: uuid.UUID,
    _: AuthorityRelationship = Depends(_authorized_relationship),
    db: Session = Depends(get_db),
):
    """Stage F, step one: mechanically derive from_principal_id/
    to_principal_id from Principals already resolved in Stage E. Safe to
    call more than once as more of a corpus's people get resolved."""
    try:
        relationship = svc.resolve_relationship(db, relationship_id)
    except AuthorityRelationshipNotFoundError:
        raise HTTPException(status_code=404, detail="relationship_not_found")
    except RelationshipNotResolvableError:
        raise HTTPException(status_code=409, detail="neither_party_resolved_yet")
    return _relationship_to_response(relationship)


@router.post(
    "/relationships/{relationship_id}/activate",
    response_model=RelationshipResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def activate_relationship(
    relationship_id: uuid.UUID,
    _: AuthorityRelationship = Depends(_authorized_relationship),
    db: Session = Depends(get_db),
):
    """Stage F, step two: the explicit decision that a resolved
    delegation should actually govern live enforcement. Only after this
    does authority_context_service start returning this edge as an
    active inbound delegation."""
    try:
        relationship = svc.activate_relationship(db, relationship_id)
    except AuthorityRelationshipNotFoundError:
        raise HTTPException(status_code=404, detail="relationship_not_found")
    except RelationshipNotResolvedError:
        raise HTTPException(status_code=409, detail="relationship_not_resolved")
    return _relationship_to_response(relationship)


@router.get(
    "/corpora/{corpus_id}/conflicts", response_model=list[ConflictResponse],
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def get_conflicts(corpus_id: uuid.UUID, _: AuthorityCorpus = Depends(_authorized_corpus), db: Session = Depends(get_db)):
    return [_conflict_to_response(c) for c in svc.list_conflicts(db, corpus_id)]


@router.get(
    "/corpora/{corpus_id}/gaps", response_model=list[GapResponse],
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def get_gaps(corpus_id: uuid.UUID, _: AuthorityCorpus = Depends(_authorized_corpus), db: Session = Depends(get_db)):
    return [_gap_to_response(g) for g in svc.list_gaps(db, corpus_id)]


@router.get(
    "/corpora/{corpus_id}/questions", response_model=list[QuestionResponse],
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def get_questions(corpus_id: uuid.UUID, _: AuthorityCorpus = Depends(_authorized_corpus), db: Session = Depends(get_db)):
    return [_question_to_response(q) for q in svc.list_questions(db, corpus_id)]


@router.post(
    "/questions/{question_id}/answer",
    response_model=QuestionResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def answer_question(
    question_id: uuid.UUID,
    body: AnswerQuestionRequest,
    _: AuthorityQuestion = Depends(_authorized_question),
    db: Session = Depends(get_db),
):
    try:
        question = svc.answer_question(db, question_id, body.answer)
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")
    return _question_to_response(question)


# --- Phase 3: Explainability & Human Review -----------------------------


@router.get(
    "/corpora/{corpus_id}/coverage", response_model=CoverageResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def get_coverage(corpus_id: uuid.UUID, _: AuthorityCorpus = Depends(_authorized_corpus), db: Session = Depends(get_db)):
    """Task 5: deterministic parsing statistics aggregated across this
    corpus's documents -- see AuthorityCorpusDocument's own columns and
    text_extraction.extract_text_with_coverage. Never an LLM's estimate
    of its own completeness."""
    return CoverageResponse(**svc.get_coverage(db, corpus_id))


@router.get(
    "/corpora/{corpus_id}/missing-information", response_model=list[MissingInformationItem],
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def get_missing_information(
    corpus_id: uuid.UUID, _: AuthorityCorpus = Depends(_authorized_corpus), db: Session = Depends(get_db)
):
    """Task 4: a deterministic, code-computed backstop for the model's
    own self-reported Gaps/Questions -- every item here is read directly
    from already-persisted rows, never re-asked of an LLM."""
    return [MissingInformationItem(**item) for item in svc.detect_missing_information(db, corpus_id)]


@router.get(
    "/corpora/{corpus_id}/diff", response_model=GraphDiffResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def get_graph_diff(corpus_id: uuid.UUID, _: AuthorityCorpus = Depends(_authorized_corpus), db: Session = Depends(get_db)):
    """Task 7: this corpus's candidate Authority Graph vs. the Authority
    Graph already in force for the same organisation. A deterministic
    comparison -- the model's job ended at extraction time."""
    try:
        diff = svc.get_graph_diff(db, corpus_id)
    except CorpusNotFoundError:
        raise HTTPException(status_code=404, detail="corpus_not_found")
    return GraphDiffResponse(**diff)


@router.post(
    "/corpora/{corpus_id}/approve",
    response_model=GraphApprovalResponse,
    status_code=201,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def approve_graph(
    corpus_id: uuid.UUID,
    body: ApproveGraphRequest,
    corpus: AuthorityCorpus = Depends(_authorized_corpus),
    db: Session = Depends(get_db),
    session_user: User | None = Depends(get_current_user_if_session),
):
    """Task 8: an ADDITIVE audit record of the reviewer's decision that
    this corpus's Authority Graph has been reviewed -- it does not
    itself promote, resolve, or activate anything (that stays exactly
    resolve_principal/resolve_relationship/activate_relationship/
    ai_policy_builder's promote_candidate -- the last of these gained an
    organization_id parameter and a cross-organization check in
    Milestone 2, Multi-Tenant Foundation, but this endpoint calls none
    of them directly and is otherwise unaffected). Gated by the same
    Permission.AUTHORITY_REVIEW every other reviewer action here
    already requires -- no new permission introduced.

    Milestone 3 (Enterprise Surface Isolation): this endpoint took a
    corpus_id but never verified it belonged to the caller's own
    organization -- confirmed the worst finding in
    MULTI_TENANT_ARCHITECTURE_VERIFICATION.md, since approval returns a
    full snapshot of another org's graph and writes a falsely-attributed
    audit record into that org's history. Now gated by the same
    _authorized_corpus dependency every corpus-scoped read already
    uses."""
    try:
        approval = svc.approve_graph(
            db, corpus_id,
            reviewer=session_user.name if session_user else "operator",
            approval_reason=body.approval_reason,
        )
    except CorpusNotFoundError:
        raise HTTPException(status_code=404, detail="corpus_not_found")
    except ConcurrentApprovalConflictError:
        raise HTTPException(status_code=409, detail="concurrent_approval_conflict")
    return GraphApprovalResponse(
        id=str(approval.id), corpus_id=str(approval.corpus_id), reviewer=approval.reviewer,
        version=approval.version, approval_reason=approval.approval_reason,
        graph_hash=approval.graph_hash, approved_at=approval.approved_at,
        predecessor_approval_id=str(approval.predecessor_approval_id) if approval.predecessor_approval_id else None,
        # A brand-new approval can never already have been superseded.
        superseded_by_approval_id=None,
    )


@router.get(
    "/corpora/{corpus_id}/approvals", response_model=list[GraphApprovalResponse],
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def list_approvals(
    corpus_id: uuid.UUID, _: AuthorityCorpus = Depends(_authorized_corpus), db: Session = Depends(get_db)
):
    """The immutable approval history for this corpus, newest first.
    superseded_by_approval_id is derived per-row from this same list
    (issue #5) rather than N extra queries: since every approval's
    predecessor_approval_id points at the corpus's real prior latest at
    creation time, "what superseded row X" is simply "the row in this
    list whose predecessor_approval_id equals X.id"."""
    approvals = svc.list_approvals(db, corpus_id)
    superseded_by: dict[uuid.UUID, uuid.UUID] = {
        a.predecessor_approval_id: a.id for a in approvals if a.predecessor_approval_id is not None
    }
    return [
        GraphApprovalResponse(
            id=str(a.id), corpus_id=str(a.corpus_id), reviewer=a.reviewer, version=a.version,
            approval_reason=a.approval_reason, graph_hash=a.graph_hash, approved_at=a.approved_at,
            predecessor_approval_id=str(a.predecessor_approval_id) if a.predecessor_approval_id else None,
            superseded_by_approval_id=str(superseded_by[a.id]) if a.id in superseded_by else None,
        )
        for a in approvals
    ]


def _diff_summary(diff) -> GraphApprovalDiffSummary:
    return GraphApprovalDiffSummary(
        principals_added=len(diff.principals.added),
        principals_removed=len(diff.principals.removed),
        principals_changed=len(diff.principals.changed),
        relationships_added=len(diff.relationships.added),
        relationships_removed=len(diff.relationships.removed),
        relationships_changed=len(diff.relationships.changed),
        conflicts_added=len(diff.conflicts.added),
        conflicts_removed=len(diff.conflicts.removed),
        conflicts_changed=len(diff.conflicts.changed),
        gaps_added=len(diff.gaps.added),
        gaps_removed=len(diff.gaps.removed),
        gaps_changed=len(diff.gaps.changed),
        coverage_changed=bool(diff.coverage.changed_fields),
    )


@router.get(
    "/corpora/{corpus_id}/approvals/{approval_id}/diff",
    response_model=GraphApprovalDiffResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def diff_graph_approval(
    corpus_id: uuid.UUID,
    approval_id: uuid.UUID,
    against: uuid.UUID | None = None,
    _: AuthorityCorpus = Depends(_authorized_corpus),
    db: Session = Depends(get_db),
):
    """Authority Graph Lineage & Versioning (issue #5): a deterministic,
    same-corpus comparison of two approved graph versions -- never an
    LLM-generated summary (domain/authority_graph/diff.py is pure,
    DB-free, LLM-free). Defaults to comparing approval_id against its
    own immediate predecessor; pass ?against=<approval_id> to compare
    against any other approval from the SAME corpus instead. A
    different-corpus (or different-organisation) `against`, or an
    approval_id with no predecessor and no explicit `against`, both
    404 -- the same "path segments must agree" discipline every other
    nested read here already applies, never a 500 or a nonsensical
    empty diff."""
    try:
        from_approval, to_approval, diff = svc.diff_graph_approvals(
            db, corpus_id, approval_id, against_approval_id=against,
        )
    except ApprovalNotFoundError:
        raise HTTPException(status_code=404, detail="approval_not_found")
    except NoPredecessorApprovalError:
        raise HTTPException(status_code=404, detail="no_predecessor_to_compare")
    return GraphApprovalDiffResponse(
        from_approval=GraphApprovalRef(
            id=str(from_approval.id), version=from_approval.version, approved_at=from_approval.approved_at,
        ),
        to_approval=GraphApprovalRef(
            id=str(to_approval.id), version=to_approval.version, approved_at=to_approval.approved_at,
        ),
        summary=_diff_summary(diff),
        principals=dataclasses.asdict(diff.principals),
        relationships=dataclasses.asdict(diff.relationships),
        conflicts=dataclasses.asdict(diff.conflicts),
        gaps=dataclasses.asdict(diff.gaps),
        coverage=dataclasses.asdict(diff.coverage),
    )


@router.get(
    "/corpora/{corpus_id}/approvals/{approval_id}/policies",
    response_model=list[CompiledPolicySummaryResponse],
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def list_policies_compiled_from_approval(
    corpus_id: uuid.UUID,
    approval_id: uuid.UUID,
    _: AuthorityCorpus = Depends(_authorized_corpus),
    db: Session = Depends(get_db),
):
    """Authority Graph -> RuntimePolicy Compilation Gate (issue #6),
    reverse traceability: every RuntimePolicy version whose lineage
    originates at this specific approval. 404s (not an empty list) if
    the approval doesn't exist or belongs to a different corpus than
    the one this URL names -- the same "path segments must agree"
    discipline every other nested read here already applies."""
    approval = svc.get_approval_by_id(db, approval_id)
    if approval is None or approval.corpus_id != corpus_id:
        raise HTTPException(status_code=404, detail="approval_not_found")
    return [
        CompiledPolicySummaryResponse(
            policy_key=str(p.policy_key), version=p.version,
            name=p.content.get("name", ""), status=p.status, created_at=p.created_at,
        )
        for p in runtime_policy_service.list_policies_compiled_from_approval(db, approval_id)
    ]
