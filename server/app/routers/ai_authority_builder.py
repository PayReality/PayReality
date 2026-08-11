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
from app.db.models import Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.ai_authority_builder.azure_foundry_provider import (
    AzureFoundryAuthorityGraphExtractionProvider,
)
from app.domain.ai_authority_builder.claude_provider import ClaudeAuthorityGraphExtractionProvider
from app.domain.ai_authority_builder.fake_provider import FakeAuthorityGraphExtractionProvider
from app.domain.ai_policy_builder.text_extraction import UnsupportedFormatError, detect_format
from app.domain.rbac.permissions import Permission
from app.schemas.ai_authority_builder import (
    AnswerQuestionRequest,
    ConflictResponse,
    CorpusResponse,
    GapResponse,
    GraphSummaryResponse,
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
from app.services.ai_authority_builder_service import (
    AlreadyResolvedError,
    AuthorityPrincipalNotFoundError,
    AuthorityRelationshipNotFoundError,
    CorpusNotFoundError,
    CrossOrganizationMatchError,
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


def _principal_to_response(p: AuthorityPrincipal) -> PrincipalResponse:
    return PrincipalResponse(
        id=str(p.id), name=p.name, role=p.role, reports_to=p.reports_to, confidence=p.confidence,
        source_excerpt=p.source_excerpt, source_location=p.source_location,
        resolved_principal_id=str(p.resolved_principal_id) if p.resolved_principal_id else None,
    )


def _resource_to_response(r: AuthorityResource) -> ResourceResponse:
    return ResourceResponse(
        id=str(r.id), name=r.name, description=r.description, confidence=r.confidence,
        source_excerpt=r.source_excerpt, source_location=r.source_location,
    )


def _operation_to_response(o: AuthorityOperation) -> OperationResponse:
    return OperationResponse(
        id=str(o.id), name=o.name, description=o.description, confidence=o.confidence,
        source_excerpt=o.source_excerpt, source_location=o.source_location,
    )


def _relationship_to_response(r: AuthorityRelationship) -> RelationshipResponse:
    return RelationshipResponse(
        id=str(r.id), kind=r.kind, from_principal=r.from_principal, to_principal=r.to_principal,
        description=r.description, confidence=r.confidence,
        source_excerpt=r.source_excerpt, source_location=r.source_location,
        from_principal_id=str(r.from_principal_id) if r.from_principal_id else None,
        to_principal_id=str(r.to_principal_id) if r.to_principal_id else None,
        status=r.status,
    )


def _conflict_to_response(c: AuthorityConflict) -> ConflictResponse:
    return ConflictResponse(id=str(c.id), description=c.description, reasoning=c.reasoning, confidence=c.confidence)


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


@router.get("/corpora", response_model=list[CorpusResponse])
def list_corpora(db: Session = Depends(get_db)):
    return [_corpus_to_response(c, len(svc.list_documents(db, c.id))) for c in svc.list_corpora(db)]


@router.get("/corpora/{corpus_id}", response_model=CorpusResponse)
def get_corpus(corpus_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        corpus = svc.get_corpus(db, corpus_id)
    except CorpusNotFoundError:
        raise HTTPException(status_code=404, detail="corpus_not_found")
    return _corpus_to_response(corpus, len(svc.list_documents(db, corpus_id)))


@router.get("/corpora/{corpus_id}/summary", response_model=GraphSummaryResponse)
def get_summary(corpus_id: uuid.UUID, db: Session = Depends(get_db)):
    """Counts only, matching AI_AUTHORITY_BUILDER_ARCHITECTURE.md's own
    example. Runtime Policy candidates are counted via the AI Policy
    Builder's own list_candidates(corpus_id=...), not a duplicated
    query."""
    from app.services import ai_policy_builder_service as policy_svc

    return GraphSummaryResponse(
        policy_count=len(policy_svc.list_candidates(db, corpus_id=corpus_id)),
        principal_count=len(svc.list_principals(db, corpus_id)),
        resource_count=len(svc.list_resources(db, corpus_id)),
        operation_count=len(svc.list_operations(db, corpus_id)),
        relationship_count=len(svc.list_relationships(db, corpus_id)),
        conflict_count=len(svc.list_conflicts(db, corpus_id)),
        gap_count=len(svc.list_gaps(db, corpus_id)),
        question_count=len(svc.list_questions(db, corpus_id)),
    )


@router.get("/corpora/{corpus_id}/principals", response_model=list[PrincipalResponse])
def get_principals(corpus_id: uuid.UUID, db: Session = Depends(get_db)):
    return [_principal_to_response(p) for p in svc.list_principals(db, corpus_id)]


@router.get(
    "/principals/{authority_principal_id}/candidates",
    response_model=list[PrincipalCandidateResponse],
)
def get_principal_candidates(authority_principal_id: uuid.UUID, db: Session = Depends(get_db)):
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
    authority_principal_id: uuid.UUID, body: ResolvePrincipalRequest, db: Session = Depends(get_db)
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


@router.get("/corpora/{corpus_id}/resources", response_model=list[ResourceResponse])
def get_resources(corpus_id: uuid.UUID, db: Session = Depends(get_db)):
    return [_resource_to_response(r) for r in svc.list_resources(db, corpus_id)]


@router.get("/corpora/{corpus_id}/operations", response_model=list[OperationResponse])
def get_operations(corpus_id: uuid.UUID, db: Session = Depends(get_db)):
    return [_operation_to_response(o) for o in svc.list_operations(db, corpus_id)]


@router.get("/corpora/{corpus_id}/relationships", response_model=list[RelationshipResponse])
def get_relationships(corpus_id: uuid.UUID, db: Session = Depends(get_db)):
    return [_relationship_to_response(r) for r in svc.list_relationships(db, corpus_id)]


@router.post(
    "/relationships/{relationship_id}/resolve",
    response_model=RelationshipResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def resolve_relationship(relationship_id: uuid.UUID, db: Session = Depends(get_db)):
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
def activate_relationship(relationship_id: uuid.UUID, db: Session = Depends(get_db)):
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


@router.get("/corpora/{corpus_id}/conflicts", response_model=list[ConflictResponse])
def get_conflicts(corpus_id: uuid.UUID, db: Session = Depends(get_db)):
    return [_conflict_to_response(c) for c in svc.list_conflicts(db, corpus_id)]


@router.get("/corpora/{corpus_id}/gaps", response_model=list[GapResponse])
def get_gaps(corpus_id: uuid.UUID, db: Session = Depends(get_db)):
    return [_gap_to_response(g) for g in svc.list_gaps(db, corpus_id)]


@router.get("/corpora/{corpus_id}/questions", response_model=list[QuestionResponse])
def get_questions(corpus_id: uuid.UUID, db: Session = Depends(get_db)):
    return [_question_to_response(q) for q in svc.list_questions(db, corpus_id)]


@router.post(
    "/questions/{question_id}/answer",
    response_model=QuestionResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def answer_question(question_id: uuid.UUID, body: AnswerQuestionRequest, db: Session = Depends(get_db)):
    try:
        question = svc.answer_question(db, question_id, body.answer)
    except QuestionNotFoundError:
        raise HTTPException(status_code=404, detail="question_not_found")
    return _question_to_response(question)
