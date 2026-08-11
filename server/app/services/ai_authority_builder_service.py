"""AI Authority Builder's service layer
(AI_AUTHORITY_BUILDER_ARCHITECTURE.md): corpus storage, extraction
orchestration across an Authority Graph's eight categories, and
per-category listing/answering. Runtime Policy candidates reuse
services/ai_policy_builder_service.py's promote_candidate,
dismiss_candidate, edit_candidate, and get_candidate completely
unmodified: this module never duplicates that logic, only stores
corpus-derived candidates in the same table those functions already
operate on.
"""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AuthorityConflict,
    AuthorityCorpus,
    AuthorityCorpusDocument,
    AuthorityGap,
    AuthorityOperation,
    AuthorityPrincipal,
    AuthorityQuestion,
    AuthorityRelationship,
    AuthorityResource,
    PolicyExtractionCandidate,
    Principal,
)
from app.domain.ai_authority_builder.provider import AuthorityGraph, AuthorityGraphExtractionProvider
from app.domain.ai_policy_builder.text_extraction import extract_text
from app.services import authority_intelligence_service
from app.services.ai_policy_builder_service import candidate_to_content


class CorpusNotFoundError(Exception):
    pass


class QuestionNotFoundError(Exception):
    pass


class AuthorityPrincipalNotFoundError(Exception):
    pass


class AlreadyResolvedError(Exception):
    """Stage E's 'never overwrite existing Principals automatically':
    once a discovery has a resolved_principal_id, resolving it again is
    refused rather than silently replacing the link. A reviewer who
    genuinely wants to change it must be an explicit, separate action
    this service does not yet expose, deliberately -- the audit's
    ownership of that decision matters more than the convenience."""


class PrincipalNotFoundError(Exception):
    pass


class CrossOrganizationMatchError(Exception):
    """Fail-closed, matching AuthorityRelationship's own
    cross_org_approved precedent (PHASE_1_AUTHORITY_MODEL.md): a
    discovery from one organisation's corpus is never silently matched
    to a Principal belonging to a different organisation."""


def create_corpus(
    db: Session, name: str, organization_id: uuid.UUID | None = None
) -> AuthorityCorpus:
    # Authority-as-a-continuous-object, Stage E: organization_id is what
    # scopes every later resolution (Principal matching, and eventually
    # Authority/Mandate creation) to the right tenant. Optional so any
    # caller that predates this change keeps working, but the router now
    # always supplies it via get_current_organization.
    corpus = AuthorityCorpus(
        id=uuid.uuid4(), name=name, status="uploaded", organization_id=organization_id
    )
    db.add(corpus)
    db.commit()
    db.refresh(corpus)
    return corpus


def add_document(db: Session, corpus: AuthorityCorpus, filename: str, format: str, raw: bytes) -> AuthorityCorpusDocument:
    doc = AuthorityCorpusDocument(
        id=uuid.uuid4(), corpus_id=corpus.id, filename=filename, format=format, content=raw
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Authority Intelligence Program, Phase 1: best-effort, additive.
    # Postgres (above) remains the write that must succeed for this
    # function to succeed at all; Blob Storage and Azure AI Search are
    # populated afterward and never block or fail this call -- neither
    # because they aren't configured for this environment yet, nor
    # because this particular document's text couldn't be extracted
    # (see authority_intelligence_service's own docstring for the same
    # posture on its own two functions).
    try:
        blob_path = authority_intelligence_service.upload_document_to_blob(
            corpus.id, doc.id, filename, raw
        )
        if blob_path:
            doc.blob_path = blob_path
            db.commit()
            db.refresh(doc)
        authority_intelligence_service.index_document(
            corpus.id, doc.id, filename, format, extract_text(format, raw), blob_path
        )
    except Exception:
        logging.getLogger("payreality.authority_intelligence").exception(
            "authority_intelligence_ingestion_failed corpus_id=%s document_id=%s", corpus.id, doc.id
        )
    return doc


def build_corpus_text(documents: list[AuthorityCorpusDocument]) -> str:
    """Concatenates every document's own marked-up text
    (domain/ai_policy_builder/text_extraction.py, reused unchanged) under
    a per-file header, so the model sees the whole corpus as one body of
    evidence rather than analysing documents independently
    (AI_AUTHORITY_BUILDER_ARCHITECTURE.md)."""
    parts = []
    for doc in documents:
        text = extract_text(doc.format, doc.content)
        parts.append(f"=== FILE: {doc.filename} ===\n{text}")
    return "\n\n".join(parts)


def run_extraction(
    db: Session, corpus: AuthorityCorpus, documents: list[AuthorityCorpusDocument], provider: AuthorityGraphExtractionProvider
) -> AuthorityCorpus:
    """AI_AUTHORITY_BUILDER_ARCHITECTURE.md's corpus extraction. On any
    failure, the corpus transitions to failed and the caller may retry
    without re-uploading, the same recovery posture every extraction
    pipeline in this platform already follows. Zero findings in any
    category is a valid outcome, not an error."""
    try:
        # Authority Intelligence Program, Phase 1: retrieve through Azure
        # AI Search when it's configured and has this corpus indexed;
        # otherwise fall back to the original, always-available Postgres
        # read (build_corpus_text, unchanged and still directly tested).
        corpus_text = authority_intelligence_service.retrieve_corpus_text(corpus.id)
        if corpus_text is None:
            corpus_text = build_corpus_text(documents)
        graph: AuthorityGraph = provider.extract(corpus_text)
    except Exception as e:
        corpus.status = "failed"
        corpus.error = str(e)
        db.commit()
        raise

    for policy in graph.policies:
        db.add(
            PolicyExtractionCandidate(
                id=uuid.uuid4(),
                upload_id=None,
                corpus_id=corpus.id,
                content=candidate_to_content(policy),
                confidence=policy.confidence,
                missing_fields=list(policy.missing_fields),
                source_excerpt=policy.source_excerpt,
                source_location=policy.source_location,
                status="pending_review",
            )
        )

    for p in graph.principals:
        db.add(
            AuthorityPrincipal(
                id=uuid.uuid4(), corpus_id=corpus.id, name=p.name, role=p.role, reports_to=p.reports_to,
                confidence=p.confidence, source_excerpt=p.source_excerpt, source_location=p.source_location,
            )
        )

    for r in graph.resources:
        db.add(
            AuthorityResource(
                id=uuid.uuid4(), corpus_id=corpus.id, name=r.name, description=r.description,
                confidence=r.confidence, source_excerpt=r.source_excerpt, source_location=r.source_location,
            )
        )

    for o in graph.operations:
        db.add(
            AuthorityOperation(
                id=uuid.uuid4(), corpus_id=corpus.id, name=o.name, description=o.description,
                confidence=o.confidence, source_excerpt=o.source_excerpt, source_location=o.source_location,
            )
        )

    for rel in graph.relationships:
        db.add(
            AuthorityRelationship(
                id=uuid.uuid4(), corpus_id=corpus.id, kind=rel.kind,
                from_principal=rel.from_principal, to_principal=rel.to_principal,
                description=rel.description, confidence=rel.confidence,
                source_excerpt=rel.source_excerpt, source_location=rel.source_location,
            )
        )

    for c in graph.conflicts:
        db.add(
            AuthorityConflict(
                id=uuid.uuid4(), corpus_id=corpus.id, description=c.description,
                reasoning=c.reasoning, confidence=c.confidence,
            )
        )

    for g in graph.gaps:
        db.add(
            AuthorityGap(
                id=uuid.uuid4(), corpus_id=corpus.id, description=g.description, confidence=g.confidence,
                source_excerpt=g.source_excerpt, source_location=g.source_location,
            )
        )

    for q in graph.questions:
        db.add(
            AuthorityQuestion(
                id=uuid.uuid4(), corpus_id=corpus.id, question=q.question, context=q.context,
            )
        )

    corpus.status = "extracted"
    db.commit()
    db.refresh(corpus)
    return corpus


def list_corpora(db: Session) -> list[AuthorityCorpus]:
    return list(db.scalars(select(AuthorityCorpus).order_by(AuthorityCorpus.created_at.desc())))


def get_corpus(db: Session, corpus_id: uuid.UUID) -> AuthorityCorpus:
    corpus = db.get(AuthorityCorpus, corpus_id)
    if corpus is None:
        raise CorpusNotFoundError(str(corpus_id))
    return corpus


def list_documents(db: Session, corpus_id: uuid.UUID) -> list[AuthorityCorpusDocument]:
    return list(
        db.scalars(select(AuthorityCorpusDocument).where(AuthorityCorpusDocument.corpus_id == corpus_id))
    )


def _list(db: Session, model, corpus_id: uuid.UUID):
    return list(db.scalars(select(model).where(model.corpus_id == corpus_id).order_by(model.created_at.desc())))


def list_principals(db: Session, corpus_id: uuid.UUID) -> list[AuthorityPrincipal]:
    return _list(db, AuthorityPrincipal, corpus_id)


def list_resources(db: Session, corpus_id: uuid.UUID) -> list[AuthorityResource]:
    return _list(db, AuthorityResource, corpus_id)


def list_operations(db: Session, corpus_id: uuid.UUID) -> list[AuthorityOperation]:
    return _list(db, AuthorityOperation, corpus_id)


def list_relationships(db: Session, corpus_id: uuid.UUID) -> list[AuthorityRelationship]:
    return _list(db, AuthorityRelationship, corpus_id)


def list_conflicts(db: Session, corpus_id: uuid.UUID) -> list[AuthorityConflict]:
    return _list(db, AuthorityConflict, corpus_id)


def list_gaps(db: Session, corpus_id: uuid.UUID) -> list[AuthorityGap]:
    return _list(db, AuthorityGap, corpus_id)


def list_questions(db: Session, corpus_id: uuid.UUID) -> list[AuthorityQuestion]:
    return _list(db, AuthorityQuestion, corpus_id)


def answer_question(db: Session, question_id: uuid.UUID, answer: str) -> AuthorityQuestion:
    question = db.get(AuthorityQuestion, question_id)
    if question is None:
        raise QuestionNotFoundError(str(question_id))
    question.answer = answer
    question.answered = True
    db.commit()
    db.refresh(question)
    return question


# --- Stage E: Principal Resolution ------------------------------------
#
# AuthorityPrincipal is a discovery: a name, a role, a reporting line,
# extracted from a real document and cited to it, but by design (see the
# model's own docstring, AI_AUTHORITY_BUILDER_ARCHITECTURE.md) not a
# first-class identity. This section is the resolver that was designed
# for but never built: match the discovery against a real Principal
# already in this organisation, or, if the reviewer confirms none
# exists, create one. Nothing here is automatic. A discovery's
# resolved_principal_id is only ever set by an explicit reviewer action.


def _get_authority_principal(db: Session, authority_principal_id: uuid.UUID) -> AuthorityPrincipal:
    row = db.get(AuthorityPrincipal, authority_principal_id)
    if row is None:
        raise AuthorityPrincipalNotFoundError(str(authority_principal_id))
    return row


def find_principal_candidates(
    db: Session, authority_principal_id: uuid.UUID
) -> list[Principal]:
    """Suggests, never applies. A case-insensitive name match within the
    discovery's own corpus organisation (or, if the corpus predates
    Stage E and has no organisation, among Principals that likewise have
    none set) -- exactly the same fail-closed posture
    AuthorityRelationship's cross_org_approved already established for
    the analogous problem."""
    discovery = _get_authority_principal(db, authority_principal_id)
    corpus = db.get(AuthorityCorpus, discovery.corpus_id)
    organization_id = corpus.organization_id if corpus else None

    stmt = select(Principal).where(func.lower(Principal.name) == discovery.name.strip().lower())
    stmt = stmt.where(Principal.organization_id == organization_id)
    return list(db.scalars(stmt))


def resolve_principal(
    db: Session,
    authority_principal_id: uuid.UUID,
    action: str,
    principal_id: uuid.UUID | None = None,
    name: str | None = None,
    role: str | None = None,
) -> Principal:
    """The reviewer's confirmed decision, and the only code path allowed
    to set resolved_principal_id. `action="match"` links to an existing
    Principal (rejecting a cross-organisation match, fail-closed).
    `action="create"` makes a new, real Principal from this discovery,
    inheriting the corpus's organisation and this discovery's role
    unless the reviewer overrides either."""
    discovery = _get_authority_principal(db, authority_principal_id)
    if discovery.resolved_principal_id is not None:
        raise AlreadyResolvedError(str(authority_principal_id))

    corpus = db.get(AuthorityCorpus, discovery.corpus_id)
    organization_id = corpus.organization_id if corpus else None

    if action == "match":
        if principal_id is None:
            raise ValueError("principal_id is required to match an existing Principal")
        principal = db.get(Principal, principal_id)
        if principal is None:
            raise PrincipalNotFoundError(str(principal_id))
        if principal.organization_id is not None and principal.organization_id != organization_id:
            raise CrossOrganizationMatchError(
                f"principal {principal_id} belongs to a different organisation than this corpus"
            )
    elif action == "create":
        principal = Principal(
            name=(name or discovery.name),
            role=(role or discovery.role),
            organization_id=organization_id,
        )
        db.add(principal)
        db.flush()
    else:
        raise ValueError(f"unknown resolution action: {action!r}")

    discovery.resolved_principal_id = principal.id
    db.commit()
    db.refresh(principal)
    return principal


# --- Stage F: Delegated Authority Resolution --------------------------
#
# AuthorityRelationship already carries from_principal_id/to_principal_id
# (PHASE_1_AUTHORITY_MODEL.md); nothing in the codebase has ever written
# to them. This section finishes that design: once the people on both
# ends of a discovered relationship have themselves been resolved to
# real Principals (Stage E), the relationship's own FKs can be derived
# mechanically -- no new judgement is being made, only propagating a
# judgement a reviewer already confirmed. Making the relationship
# actually count in live enforcement (status "proposed" -> "active") is
# kept a separate, explicit step.


class AuthorityRelationshipNotFoundError(Exception):
    pass


class RelationshipNotResolvableError(Exception):
    """Raised when one or both named parties have no corresponding,
    already-resolved AuthorityPrincipal in the same corpus yet. The
    caller should resolve those Principals first (Stage E) rather than
    this function guessing or inferring a match on its own."""


class RelationshipNotResolvedError(Exception):
    """Raised by activate_relationship: a relationship's FKs must be
    resolved before it can be activated. Prevents a delegation with an
    unknown party from ever silently becoming live."""


def _match_resolved_principal_id(
    db: Session, corpus_id: uuid.UUID, name: str
) -> uuid.UUID | None:
    stmt = (
        select(AuthorityPrincipal)
        .where(AuthorityPrincipal.corpus_id == corpus_id)
        .where(func.lower(AuthorityPrincipal.name) == name.strip().lower())
        .where(AuthorityPrincipal.resolved_principal_id.is_not(None))
    )
    match = db.scalar(stmt)
    return match.resolved_principal_id if match else None


def resolve_relationship(
    db: Session, relationship_id: uuid.UUID
) -> AuthorityRelationship:
    """Derives from_principal_id/to_principal_id from already-resolved
    AuthorityPrincipal rows in the same corpus. Idempotent and safe to
    call repeatedly, including before both sides are resolvable -- it
    fills in whichever side it can and leaves the other null rather than
    failing outright, so resolving principals one at a time still makes
    incremental progress visible."""
    relationship = db.get(AuthorityRelationship, relationship_id)
    if relationship is None:
        raise AuthorityRelationshipNotFoundError(str(relationship_id))

    from_id = _match_resolved_principal_id(db, relationship.corpus_id, relationship.from_principal)
    to_id = _match_resolved_principal_id(db, relationship.corpus_id, relationship.to_principal)

    if from_id is None and to_id is None:
        raise RelationshipNotResolvableError(str(relationship_id))

    if from_id is not None:
        relationship.from_principal_id = from_id
    if to_id is not None:
        relationship.to_principal_id = to_id
    db.commit()
    db.refresh(relationship)
    return relationship


def activate_relationship(db: Session, relationship_id: uuid.UUID) -> AuthorityRelationship:
    """The explicit reviewer decision that a resolved delegation should
    actually govern live enforcement. Only once this runs does
    authority_context_service._active_inbound_delegations start
    returning this edge -- resolving names into ids and deciding the
    delegation is real are kept deliberately separate."""
    relationship = db.get(AuthorityRelationship, relationship_id)
    if relationship is None:
        raise AuthorityRelationshipNotFoundError(str(relationship_id))
    if relationship.from_principal_id is None or relationship.to_principal_id is None:
        raise RelationshipNotResolvedError(str(relationship_id))
    relationship.status = "active"
    db.commit()
    db.refresh(relationship)
    return relationship
