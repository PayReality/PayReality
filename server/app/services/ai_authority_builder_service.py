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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    Authority,
    AuthorityConflict,
    AuthorityCorpus,
    AuthorityCorpusDocument,
    AuthorityGap,
    AuthorityGraphApproval,
    AuthorityOperation,
    AuthorityPrincipal,
    AuthorityQuestion,
    AuthorityRelationship,
    AuthorityResource,
    PolicyExtractionCandidate,
    Principal,
)
from app.domain.ai_authority_builder.provider import (
    AuthorityGraph,
    AuthorityGraphExtractionProvider,
    CandidateConflict,
)
from app.domain.authority_graph.diff import GraphSnapshotDiff, diff_graph_snapshots
from app.domain.decision.scope_vocabulary import KNOWN_SCOPES
from app.domain.evidence.signing import payload_hash
from app.domain.ai_policy_builder.text_extraction import extract_text, extract_text_with_coverage
from app.services import authority_intelligence_service
from app.services.ai_policy_builder_service import _infer_amount_limit, candidate_to_content


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
            corpus.id, doc.id, filename, raw, organization_id=corpus.organization_id
        )
        if blob_path:
            doc.blob_path = blob_path
            db.commit()
            db.refresh(doc)
        text, coverage = extract_text_with_coverage(format, raw)
        # Coverage Analysis (Phase 3): deterministic parsing statistics,
        # persisted alongside the document regardless of whether Blob/
        # Search ingestion above succeeded -- coverage describes what the
        # parser itself saw, not what got indexed.
        doc.clauses_analysed = coverage.clauses_analysed
        doc.clauses_ignored = coverage.clauses_ignored
        doc.tables_extracted = coverage.tables_extracted
        doc.images_skipped = coverage.images_skipped
        db.commit()
        db.refresh(doc)
        authority_intelligence_service.index_document(
            corpus.id, doc.id, filename, format, text, blob_path, organization_id=corpus.organization_id
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
        corpus_text = authority_intelligence_service.retrieve_corpus_text(
            corpus.id, organization_id=corpus.organization_id
        )
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
                clause_reference=policy.clause_reference,
                extraction_reasoning=policy.extraction_reasoning,
                detected_assumptions=list(policy.detected_assumptions),
                ambiguity_flags=list(policy.ambiguity_flags),
            )
        )

    for p in graph.principals:
        db.add(
            AuthorityPrincipal(
                id=uuid.uuid4(), corpus_id=corpus.id, name=p.name, role=p.role, reports_to=p.reports_to,
                confidence=p.confidence, source_excerpt=p.source_excerpt, source_location=p.source_location,
                clause_reference=p.clause_reference, extraction_reasoning=p.extraction_reasoning,
                detected_assumptions=list(p.detected_assumptions), ambiguity_flags=list(p.ambiguity_flags),
            )
        )

    for r in graph.resources:
        db.add(
            AuthorityResource(
                id=uuid.uuid4(), corpus_id=corpus.id, name=r.name, description=r.description,
                confidence=r.confidence, source_excerpt=r.source_excerpt, source_location=r.source_location,
                clause_reference=r.clause_reference, extraction_reasoning=r.extraction_reasoning,
                detected_assumptions=list(r.detected_assumptions), ambiguity_flags=list(r.ambiguity_flags),
            )
        )

    for o in graph.operations:
        db.add(
            AuthorityOperation(
                id=uuid.uuid4(), corpus_id=corpus.id, name=o.name, description=o.description,
                confidence=o.confidence, source_excerpt=o.source_excerpt, source_location=o.source_location,
                clause_reference=o.clause_reference, extraction_reasoning=o.extraction_reasoning,
                detected_assumptions=list(o.detected_assumptions), ambiguity_flags=list(o.ambiguity_flags),
            )
        )

    for rel in graph.relationships:
        db.add(
            AuthorityRelationship(
                id=uuid.uuid4(), corpus_id=corpus.id, kind=rel.kind,
                from_principal=rel.from_principal, to_principal=rel.to_principal,
                description=rel.description, confidence=rel.confidence,
                source_excerpt=rel.source_excerpt, source_location=rel.source_location,
                clause_reference=rel.clause_reference, extraction_reasoning=rel.extraction_reasoning,
                detected_assumptions=list(rel.detected_assumptions), ambiguity_flags=list(rel.ambiguity_flags),
            )
        )

    # Conflict Workspace (Phase 3): the model's own reported conflicts,
    # PLUS deterministic circular-delegation detection over the same
    # graph -- independent confirmation, not a duplicate of the same
    # judgment. reviewer_recommendation is computed for every conflict
    # here, in Python, never asked of the model (see AuthorityConflict's
    # own docstring for why).
    all_conflicts = list(graph.conflicts) + detect_circular_delegations(graph)
    for c in all_conflicts:
        db.add(
            AuthorityConflict(
                id=uuid.uuid4(), corpus_id=corpus.id, description=c.description,
                reasoning=c.reasoning, confidence=c.confidence, conflict_type=c.conflict_type,
                reviewer_recommendation=_reviewer_recommendation(c.conflict_type, c.confidence),
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


# --- Phase 3: Conflict Workspace, deterministic detection --------------


def detect_circular_delegations(graph: AuthorityGraph) -> list[CandidateConflict]:
    """Deterministic graph-cycle detection over this extraction's own
    `delegation`-kind relationships (by extracted name, before principal
    resolution -- the whole point is to catch this before a reviewer has
    to resolve anything). Deliberately restricted to `delegation` edges:
    an escalation edge pointing back up a delegation chain is normal
    hierarchy, not a cycle -- see EXPLAINABILITY_MODEL.md's Conflict
    Workspace section. Never asks the model to do this: a human-authored
    corpus can name far more principals than a model can reliably trace
    a multi-hop cycle across in one pass, so this is checked in code,
    with confidence=1.0 because it is a graph fact, not a probabilistic
    claim."""
    edges: dict[str, set[str]] = {}
    for rel in graph.relationships:
        if rel.kind != "delegation":
            continue
        edges.setdefault(rel.from_principal.strip().lower(), set()).add(rel.to_principal.strip().lower())

    found: list[CandidateConflict] = []
    seen_cycles: set[frozenset] = set()

    def dfs(node: str, path: list[str], visiting: frozenset) -> None:
        if node in visiting:
            # `path` already ends with `node` -- the caller appends the
            # neighbor before recursing, so slicing from its first
            # occurrence is the whole cycle already closed.
            cycle = path[path.index(node):]
            key = frozenset(cycle)
            if key not in seen_cycles:
                seen_cycles.add(key)
                found.append(
                    CandidateConflict(
                        description=f"Circular delegation detected: {' -> '.join(cycle)}.",
                        confidence=1.0,
                        reasoning="Detected by deterministic delegation-chain analysis (graph cycle "
                        "detection), not the extraction model.",
                        conflict_type="circular_delegation",
                    )
                )
            return
        for neighbor in edges.get(node, ()):
            dfs(neighbor, path + [neighbor], visiting | {node})

    for start in edges:
        dfs(start, [start], frozenset())

    return found


def _reviewer_recommendation(conflict_type: str | None, confidence: float) -> str:
    """Never asked of the model -- computed deterministically from
    conflict_type/confidence, so this column is always populated from
    auditable Python logic (Phase 3's "only deterministic evidence
    stored" security principle). Every conflict recommends human review
    (this platform never auto-resolves one); the wording differs only to
    tell a reviewer which conflicts to look at first."""
    if conflict_type == "circular_delegation":
        return "Human Review Required -- Circular Delegation"
    if confidence < 0.7:
        return "Human Review -- Low Confidence, Verify Manually"
    return "Human Review"


# --- Phase 3: Missing Information Detection -----------------------------


def detect_missing_information(db: Session, corpus_id: uuid.UUID) -> list[dict]:
    """Deterministic, code-computed pass over already-persisted rows --
    independent of, and a backstop for, the model's own self-reported
    Gaps/Questions (EXPLAINABILITY_MODEL.md's Missing Information
    Detection section). Every item here is read directly from stored
    data, never re-asked of an LLM."""
    items: list[dict] = []

    principals = list_principals(db, corpus_id)
    for p in principals:
        if not p.reports_to:
            items.append({
                "category": "unknown_reporting_line",
                "subject": p.name,
                "description": f"No reporting line stated for {p.name}.",
            })

    policies = list(
        db.scalars(select(PolicyExtractionCandidate).where(PolicyExtractionCandidate.corpus_id == corpus_id))
    )
    principal_by_name = {p.name.strip().lower(): p for p in principals}
    policy_principal_names: set[str] = set()
    for row in policies:
        scope = row.content.get("scope") or {}
        principal_name, action = scope.get("principal"), scope.get("action")
        if principal_name:
            policy_principal_names.add(principal_name.strip().lower())
        if action in KNOWN_SCOPES and _infer_amount_limit(row.content) is None:
            items.append({
                "category": "unknown_spending_limit",
                "subject": principal_name,
                "description": f"No numeric spending limit stated for {principal_name}'s {action} authority.",
            })
        constraints = row.content.get("constraints") or {}
        if not constraints.get("delegated_by"):
            holder = principal_by_name.get((principal_name or "").strip().lower())
            if holder is not None and holder.reports_to:
                items.append({
                    "category": "missing_delegation",
                    "subject": principal_name,
                    "description": f"{principal_name} exercises {action} authority but no delegation "
                    "source is stated.",
                })

    relationships = list_relationships(db, corpus_id)
    for rel in relationships:
        if rel.from_principal_id is None or rel.to_principal_id is None:
            items.append({
                "category": "undefined_approver",
                "subject": f"{rel.from_principal} -> {rel.to_principal}",
                "description": f"{rel.from_principal} -> {rel.to_principal} ({rel.kind}) has not been "
                "resolved to real, known Principals.",
            })
        if rel.status == "active" and rel.to_principal.strip().lower() not in policy_principal_names:
            items.append({
                "category": "missing_policy",
                "subject": rel.to_principal,
                "description": f"{rel.to_principal} has an active delegation but no Runtime Policy "
                "candidate governs their authority.",
            })

    return items


# --- Phase 3: Coverage Analysis -----------------------------------------


def get_coverage(db: Session, corpus_id: uuid.UUID) -> dict:
    """Aggregates the deterministic, parser-level CoverageStats each
    document already recorded at upload time (add_document ->
    extract_text_with_coverage) -- never an LLM's self-report of its own
    completeness. `sections_unsupported` is honestly 0: every document
    that reached this corpus parsed successfully by definition (an
    unsupported format is rejected before a document row is ever
    created, see routers/ai_authority_builder.py's create_corpus)."""
    documents = list_documents(db, corpus_id)
    clauses_analysed = sum(d.clauses_analysed or 0 for d in documents)
    clauses_ignored = sum(d.clauses_ignored or 0 for d in documents)
    tables_extracted = sum(d.tables_extracted or 0 for d in documents)
    images_skipped = sum(d.images_skipped or 0 for d in documents)
    total = clauses_analysed + clauses_ignored
    return {
        "documents_processed": len(documents),
        "clauses_analysed": clauses_analysed,
        "clauses_ignored": clauses_ignored,
        "tables_extracted": tables_extracted,
        "images_skipped": images_skipped,
        "sections_unsupported": 0,
        "coverage_percent": round(100.0 * clauses_analysed / total, 1) if total else 100.0,
    }


# --- Phase 3: Graph Diff -------------------------------------------------


def get_graph_diff(db: Session, corpus_id: uuid.UUID) -> dict:
    """Task 7: this corpus's candidate graph vs. the Authority Graph
    already in force for the same organisation -- a deterministic set/
    value comparison, since the model already did its extraction job;
    diffing is not a second extraction task."""
    corpus = get_corpus(db, corpus_id)
    candidate_principals = list_principals(db, corpus_id)
    candidate_policies = list(
        db.scalars(select(PolicyExtractionCandidate).where(PolicyExtractionCandidate.corpus_id == corpus_id))
    )

    new_authorities: list[dict] = []
    changed_reporting_lines: list[dict] = []
    changed_responsibilities: list[dict] = []
    for p in candidate_principals:
        if p.resolved_principal_id is None:
            new_authorities.append({"name": p.name, "role": p.role})
            continue
        prior = db.scalar(
            select(AuthorityPrincipal)
            .where(AuthorityPrincipal.resolved_principal_id == p.resolved_principal_id)
            .where(AuthorityPrincipal.corpus_id != corpus_id)
            .order_by(AuthorityPrincipal.created_at.desc())
        )
        if prior is None:
            continue
        if (prior.reports_to or "").strip().lower() != (p.reports_to or "").strip().lower():
            changed_reporting_lines.append({
                "name": p.name, "previous_reports_to": prior.reports_to, "new_reports_to": p.reports_to,
            })
        if (prior.role or "").strip().lower() != (p.role or "").strip().lower():
            changed_responsibilities.append({
                "name": p.name, "previous_role": prior.role, "new_role": p.role,
            })

    new_thresholds: list[dict] = []
    changed_thresholds: list[dict] = []
    candidate_scope_keys: set[tuple[str, str]] = set()
    for row in candidate_policies:
        scope = row.content.get("scope") or {}
        principal_name, action = scope.get("principal"), scope.get("action")
        if not principal_name or not action:
            continue
        candidate_scope_keys.add((principal_name.strip().lower(), action))
        new_limit = _infer_amount_limit(row.content)
        existing = db.scalar(
            select(Authority)
            .join(Principal, Authority.principal_id == Principal.id)
            .where(func.lower(Principal.name) == principal_name.strip().lower())
            .where(Authority.scope == action)
            .where(Authority.status == "approved")
            .order_by(Authority.created_at.desc())
        )
        if existing is None:
            new_thresholds.append({"principal": principal_name, "action": action, "limit": new_limit})
        else:
            previous_limit = float(existing.limit_amount) if existing.limit_amount is not None else None
            if previous_limit != new_limit:
                changed_thresholds.append({
                    "principal": principal_name, "action": action,
                    "previous_limit": previous_limit, "new_limit": new_limit,
                })

    removed_authorities: list[dict] = []
    if corpus.organization_id is not None:
        existing_for_org = list(
            db.scalars(
                select(Authority)
                .join(Principal, Authority.principal_id == Principal.id)
                .where(Principal.organization_id == corpus.organization_id)
                .where(Authority.status == "approved")
            )
        )
        for a in existing_for_org:
            principal = db.get(Principal, a.principal_id)
            if principal is None:
                continue
            key = (principal.name.strip().lower(), a.scope)
            if key not in candidate_scope_keys:
                removed_authorities.append({"principal": principal.name, "action": a.scope})

    return {
        "new_authorities": new_authorities,
        "removed_authorities": removed_authorities,
        "new_thresholds": new_thresholds,
        "changed_thresholds": changed_thresholds,
        "changed_reporting_lines": changed_reporting_lines,
        "changed_responsibilities": changed_responsibilities,
    }


# --- Phase 3: Approval Audit ---------------------------------------------


def _corpus_evidence_snapshot(db: Session, corpus_id: uuid.UUID) -> dict:
    """Everything a reviewer saw when they approved this graph, captured
    as plain data -- never a reference that could later change
    underneath the approval record. Field order doesn't matter here:
    canonicalize() (domain/evidence/signing.py, reused unchanged) sorts
    keys before hashing, exactly as it already does for Decision
    Evidence."""
    return {
        "principals": [
            {"id": str(p.id), "name": p.name, "role": p.role, "reports_to": p.reports_to,
             "confidence": p.confidence, "resolved_principal_id": str(p.resolved_principal_id) if p.resolved_principal_id else None}
            for p in list_principals(db, corpus_id)
        ],
        "relationships": [
            {"id": str(r.id), "kind": r.kind, "from_principal": r.from_principal, "to_principal": r.to_principal,
             "status": r.status, "confidence": r.confidence}
            for r in list_relationships(db, corpus_id)
        ],
        "conflicts": [
            {"id": str(c.id), "description": c.description, "conflict_type": c.conflict_type,
             "reviewer_recommendation": c.reviewer_recommendation, "confidence": c.confidence}
            for c in list_conflicts(db, corpus_id)
        ],
        "gaps": [{"id": str(g.id), "description": g.description} for g in list_gaps(db, corpus_id)],
        "coverage": get_coverage(db, corpus_id),
    }


class ConcurrentApprovalConflictError(Exception):
    """Raised only after MAX_APPROVAL_VERSION_ATTEMPTS racing
    approve_graph calls for the same corpus all collided on the same
    computed version number -- practically unreachable in real usage,
    but bounds the retry loop explicitly rather than looping forever
    (this codebase's own established discipline; see the SDK's
    wait_for_resolution() and resolve_decision's own IntegrityError ->
    clean-error translation, Human Review Continuation milestone, issue
    #10)."""


class ApprovalNotFoundError(Exception):
    """Raised when an approval_id doesn't exist, OR exists but belongs
    to a different corpus than the one named alongside it -- the same
    "path segments must agree, and don't distinguish the two cases in
    the response" discipline list_policies_compiled_from_approval's own
    router handler already applies, reused here rather than inventing a
    second signal for what is the same information-hiding concern."""


class NoPredecessorApprovalError(Exception):
    """Raised by diff_graph_approvals when no explicit `against` approval
    was given and the target approval has no predecessor (it's the
    first approved version for its corpus) -- there is nothing to
    compare it to."""


MAX_APPROVAL_VERSION_ATTEMPTS = 3


def approve_graph(
    db: Session, corpus_id: uuid.UUID, reviewer: str, approval_reason: str | None = None
) -> AuthorityGraphApproval:
    """Task 8: an ADDITIVE audit record of the reviewer's "I have
    reviewed this corpus's Authority Graph" decision. Deliberately does
    NOT itself promote, resolve, or activate anything -- the existing,
    unmodified per-item workflow (resolve_principal, resolve_relationship,
    activate_relationship, ai_policy_builder_service.promote_candidate)
    is what does that, exactly as before this phase. This function only
    ever appends a new, immutable row; corpus_id+version is unique, so
    calling it again for the same corpus creates the next version rather
    than overwriting anything.

    Authority Graph Lineage & Versioning (issue #5): also stamps
    predecessor_approval_id to the corpus's real latest approval at the
    moment of this call (None for a corpus's first approval) -- never
    changed afterward, same immutability discipline as every other
    field here.

    Concurrency: two concurrent calls for the same corpus can both read
    the same "current latest" row before either commits, computing the
    same next version number. The uq_authority_graph_approvals_corpus_version
    constraint -- not a lock -- is what actually prevents both from
    persisting; no row locking exists anywhere in this codebase
    (deliberately, per this repo's own established preference for
    optimistic, DB-constraint-enforced safety over distributed locks).
    The loser's IntegrityError is caught below and the version/
    predecessor recomputed and retried, bounded at
    MAX_APPROVAL_VERSION_ATTEMPTS -- never an unhandled 500, and never
    an infinite loop."""
    for _attempt in range(MAX_APPROVAL_VERSION_ATTEMPTS):
        latest = get_latest_approval_for_corpus(db, corpus_id)
        version = (latest.version if latest else 0) + 1
        snapshot = _corpus_evidence_snapshot(db, corpus_id)
        approval = AuthorityGraphApproval(
            id=uuid.uuid4(),
            corpus_id=corpus_id,
            reviewer=reviewer,
            version=version,
            predecessor_approval_id=latest.id if latest else None,
            evidence_snapshot=snapshot,
            approval_reason=approval_reason,
            graph_hash=payload_hash(snapshot),
        )
        db.add(approval)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        db.refresh(approval)
        return approval
    raise ConcurrentApprovalConflictError(str(corpus_id))


def list_approvals(db: Session, corpus_id: uuid.UUID) -> list[AuthorityGraphApproval]:
    return list(
        db.scalars(
            select(AuthorityGraphApproval)
            .where(AuthorityGraphApproval.corpus_id == corpus_id)
            .order_by(AuthorityGraphApproval.version.desc())
        )
    )


def get_latest_approval_for_corpus(db: Session, corpus_id: uuid.UUID) -> AuthorityGraphApproval | None:
    """Authority Graph -> RuntimePolicy Compilation Gate (issue #6): the
    single-row fetch `list_approvals` never provided (that function
    always returns the full history). The compilation gate always
    compiles against the latest approved version for a corpus -- there
    is no UI or API today to pin promotion to an older, superseded
    approval, and this milestone does not add one."""
    return db.scalar(
        select(AuthorityGraphApproval)
        .where(AuthorityGraphApproval.corpus_id == corpus_id)
        .order_by(AuthorityGraphApproval.version.desc())
        .limit(1)
    )


def get_approval_by_id(db: Session, approval_id: uuid.UUID) -> AuthorityGraphApproval | None:
    return db.get(AuthorityGraphApproval, approval_id)


def get_approval_for_corpus(db: Session, corpus_id: uuid.UUID, approval_id: uuid.UUID) -> AuthorityGraphApproval:
    """Authority Graph Lineage & Versioning (issue #5): the org/corpus-
    scoped read every diff/lineage caller needs, and get_approval_by_id
    alone does not provide -- that function will happily return an
    approval belonging to a different corpus (or a different
    organisation entirely) than the one named in the URL. Raises
    ApprovalNotFoundError, not a distinguishable "wrong corpus" signal,
    for both "doesn't exist" and "exists but belongs elsewhere" -- a
    caller must never learn that a real approval id exists in a corpus
    it can't otherwise see."""
    approval = get_approval_by_id(db, approval_id)
    if approval is None or approval.corpus_id != corpus_id:
        raise ApprovalNotFoundError(str(approval_id))
    return approval


def diff_graph_approvals(
    db: Session,
    corpus_id: uuid.UUID,
    approval_id: uuid.UUID,
    against_approval_id: uuid.UUID | None = None,
) -> tuple[AuthorityGraphApproval, AuthorityGraphApproval, GraphSnapshotDiff]:
    """Authority Graph Lineage & Versioning (issue #5): a deterministic,
    same-corpus comparison of two approved graph versions. Returns
    (from_approval, to_approval, diff) so a caller can read both
    approvals' own metadata (version, approved_at) alongside the diff
    itself without a second query.

    Defaults `against_approval_id` to `approval_id`'s own
    predecessor_approval_id when not given -- comparing a version
    against the one immediately before it, the common case a reviewer
    actually wants. Raises NoPredecessorApprovalError if there is none
    (this is the corpus's first approved version) and no explicit
    `against` was given -- there is nothing to compare it to.

    An explicit `against_approval_id` may name ANY other approval from
    the SAME corpus, not just the immediate predecessor -- get_approval_
    for_corpus's own corpus check applies to it exactly as it does to
    approval_id, so a cross-corpus (or cross-organisation) `against`
    404s the same way a cross-corpus approval_id already does. Lineage
    stays corpus-local; this is never relaxed for the "against" side."""
    to_approval = get_approval_for_corpus(db, corpus_id, approval_id)
    if against_approval_id is not None:
        from_approval = get_approval_for_corpus(db, corpus_id, against_approval_id)
    elif to_approval.predecessor_approval_id is not None:
        from_approval = get_approval_for_corpus(db, corpus_id, to_approval.predecessor_approval_id)
    else:
        raise NoPredecessorApprovalError(str(approval_id))
    diff = diff_graph_snapshots(from_approval.evidence_snapshot, to_approval.evidence_snapshot)
    return from_approval, to_approval, diff


def get_superseding_approval(db: Session, approval: AuthorityGraphApproval) -> AuthorityGraphApproval | None:
    """The approval, if any, whose predecessor_approval_id points back
    at this one -- deliberately derived by reverse lookup rather than a
    second stored field (see the model's own docstring for why).
    Uniqueness of (corpus_id, version) plus every approval always
    pointing at the corpus's actual prior latest at the time it was
    created together guarantee at most one match."""
    return db.scalar(
        select(AuthorityGraphApproval).where(
            AuthorityGraphApproval.predecessor_approval_id == approval.id
        )
    )
