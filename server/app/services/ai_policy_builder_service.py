"""AI Policy Builder's service layer (AI_POLICY_BUILDER_ARCHITECTURE.md):
upload storage, extraction orchestration, candidate CRUD, and promotion
into Policy Studio.

Imports domain/runtime_policy and services/runtime_policy_service only
through their existing public interfaces (validate(), create_policy()),
never modifying either: promotion builds a RuntimePolicy object itself
(a small, deliberate duplication of routers/runtime_policies.py's
_build_runtime_policy, chosen over importing a private function from a
router module or editing that file) and hands it to the unmodified
create_policy, exactly the one integration point
RUNTIME_POLICY_MAPPING.md describes.

This module has no import of, and no access to, deploy_policy, the OPA
client, or the policies table: "the AI must never deploy" is structural
here, not just a documented intent.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Authority,
    AuthorityCorpus,
    AuthorityPrincipal,
    Principal,
    PolicyExtractionCandidate,
    PolicyExtractionUpload,
    RuntimePolicyRecord,
)
from app.domain.ai_policy_builder.provider import CandidateRuntimePolicy, RuntimePolicyExtractionProvider
from app.domain.ai_policy_builder.text_extraction import extract_text
from app.domain.runtime_policy.conditions import Condition, ConditionSet, Operator
from app.domain.runtime_policy.constraints import Constraints, RiskLevel
from app.domain.runtime_policy.effects import Effect
from app.domain.runtime_policy.metadata import AuditTrail, Metadata
from app.domain.runtime_policy.runtime_policy import PolicyStatus, RuntimePolicy, Scope
from app.domain.runtime_policy.validators import ValidationResult, validate
from app.services import runtime_policy_service


class UploadNotFoundError(Exception):
    pass


class CandidateNotFoundError(Exception):
    pass


class CandidateNotPendingReviewError(Exception):
    pass


class CandidateValidationError(Exception):
    def __init__(self, result: ValidationResult):
        self.result = result
        super().__init__("candidate failed RuntimePolicy validation: " + "; ".join(e.message for e in result.errors))


class CrossOrganizationPromotionError(Exception):
    """Milestone 2 (Multi-Tenant Foundation, ADR Phase B4): fail-closed,
    the same posture ai_authority_builder_service.CrossOrganizationMatchError
    already established for the discovery-resolution side of this
    lifecycle -- a candidate whose corpus belongs to a different
    organization than the one promoting it is never silently promoted
    into that promoter's own organization. This is exactly the "three
    independent, non-cross-validated paths to organization" gap the ADR
    named; this is the first place any of the three are actually
    cross-checked against each other."""


def create_upload(db: Session, filename: str, format: str, raw: bytes) -> PolicyExtractionUpload:
    upload = PolicyExtractionUpload(
        id=uuid.uuid4(), filename=filename, format=format, content=raw, status="uploaded"
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return upload


def candidate_to_content(candidate: CandidateRuntimePolicy) -> dict:
    """CandidateRuntimePolicy -> the RuntimePolicyRequest-shaped dict
    stored as PolicyExtractionCandidate.content (RUNTIME_POLICY_MAPPING.md's
    "CandidateRuntimePolicy -> stored candidate content" table)."""
    tags = list(candidate.metadata_tags)
    if "ai-extracted" not in tags:
        tags.append("ai-extracted")
    return {
        "name": candidate.name,
        "description": None,
        "scope": {
            "principal": candidate.principal,
            "action": candidate.action,
            "agent": None,
            "resource": candidate.resource,
        },
        "conditions": [
            {"field": c.field, "operator": c.operator, "value": c.value} for c in candidate.conditions
        ],
        "effect": candidate.effect,
        "constraints": {
            "delegated_by": candidate.delegated_by,
            "expires": None,
            "evidence_required": candidate.evidence_required if candidate.evidence_required is not None else True,
            "risk_level": candidate.risk_level,
        },
        "metadata": {
            "owner": candidate.metadata_owner,
            "created_by": "ai_policy_builder",
            "tags": tags,
        },
    }


def run_extraction(
    db: Session, upload: PolicyExtractionUpload, provider: RuntimePolicyExtractionProvider
) -> PolicyExtractionUpload:
    """AI_EXTRACTION_PIPELINE.md Stages 2-4. On any failure, the upload
    transitions to failed and the caller may retry without re-uploading,
    the same recovery posture document_service.py already established for
    extraction_failed. Zero candidates from a successfully extracted (but
    empty or irrelevant) document is a valid outcome, not an error."""
    try:
        document_text = extract_text(upload.format, upload.content)
        candidates = provider.extract(document_text)
    except Exception as e:
        upload.status = "failed"
        upload.error = str(e)
        db.commit()
        raise

    for candidate in candidates:
        row = PolicyExtractionCandidate(
            id=uuid.uuid4(),
            upload_id=upload.id,
            content=candidate_to_content(candidate),
            confidence=candidate.confidence,
            missing_fields=list(candidate.missing_fields),
            source_excerpt=candidate.source_excerpt,
            source_location=candidate.source_location,
            status="pending_review",
        )
        db.add(row)

    upload.status = "extracted"
    db.commit()
    db.refresh(upload)
    return upload


def list_uploads(db: Session) -> list[PolicyExtractionUpload]:
    return list(db.scalars(select(PolicyExtractionUpload).order_by(PolicyExtractionUpload.uploaded_at.desc())))


def get_upload(db: Session, upload_id: uuid.UUID) -> PolicyExtractionUpload:
    upload = db.get(PolicyExtractionUpload, upload_id)
    if upload is None:
        raise UploadNotFoundError(str(upload_id))
    return upload


def list_candidates(
    db: Session,
    upload_id: uuid.UUID | None = None,
    corpus_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[PolicyExtractionCandidate]:
    """corpus_id filters to candidates discovered by the AI Authority
    Builder (AI_AUTHORITY_BUILDER_ARCHITECTURE.md); this function has no
    other knowledge of corpora, it just filters on the column."""
    stmt = select(PolicyExtractionCandidate).order_by(PolicyExtractionCandidate.created_at.desc())
    if upload_id is not None:
        stmt = stmt.where(PolicyExtractionCandidate.upload_id == upload_id)
    if corpus_id is not None:
        stmt = stmt.where(PolicyExtractionCandidate.corpus_id == corpus_id)
    if status is not None:
        stmt = stmt.where(PolicyExtractionCandidate.status == status)
    return list(db.scalars(stmt))


def get_candidate(db: Session, candidate_id: uuid.UUID) -> PolicyExtractionCandidate:
    candidate = db.get(PolicyExtractionCandidate, candidate_id)
    if candidate is None:
        raise CandidateNotFoundError(str(candidate_id))
    return candidate


def edit_candidate(db: Session, candidate_id: uuid.UUID, content: dict) -> PolicyExtractionCandidate:
    """Human review edits (AI_EXTRACTION_PIPELINE.md Stage 5), allowed
    only while pending_review: a promoted or dismissed candidate is a
    closed record of what was decided, not something to keep revising."""
    row = get_candidate(db, candidate_id)
    if row.status != "pending_review":
        raise CandidateNotPendingReviewError(f"cannot edit a candidate in status '{row.status}'")
    row.content = content
    db.commit()
    db.refresh(row)
    return row


def dismiss_candidate(db: Session, candidate_id: uuid.UUID) -> PolicyExtractionCandidate:
    row = get_candidate(db, candidate_id)
    if row.status != "pending_review":
        raise CandidateNotPendingReviewError(f"cannot dismiss a candidate in status '{row.status}'")
    row.status = "dismissed"
    db.commit()
    db.refresh(row)
    return row


def build_runtime_policy_from_candidate(content: dict, authority_id: str | None = None) -> RuntimePolicy:
    """RUNTIME_POLICY_MAPPING.md's "stored candidate content -> RuntimePolicy"
    table. Stamps a fresh AuditTrail(created=now()) up front: the exact
    field whose omission caused a real, since-fixed production bug in
    Policy Studio's own create path (see the commit that added the
    from_dict() partial-audit-merge regression test); this construction
    gets it right from the start.

    Authority-as-a-continuous-object, Stage G: `authority_id`, when the
    caller (promote_candidate) resolved one, is stamped onto the new
    policy's constraints alongside the existing free-text `delegated_by`
    -- never instead of it."""
    scope_data = content["scope"]
    constraints_data = content.get("constraints") or {}
    metadata_data = content.get("metadata") or {}
    risk_level = RiskLevel(constraints_data["risk_level"]) if constraints_data.get("risk_level") else None

    return RuntimePolicy(
        id=str(uuid.uuid4()),
        name=content["name"],
        description=content.get("description"),
        version=1,
        status=PolicyStatus.DRAFT,
        scope=Scope(
            principal=scope_data["principal"],
            action=scope_data["action"],
            agent=scope_data.get("agent"),
            resource=scope_data.get("resource"),
        ),
        conditions=ConditionSet(
            all=tuple(
                Condition(field=c["field"], operator=Operator(c["operator"]), value=c["value"])
                for c in content.get("conditions", [])
            )
        ),
        effect=Effect(content["effect"]),
        constraints=Constraints(
            delegated_by=constraints_data.get("delegated_by"),
            expires=None,
            evidence_required=constraints_data.get("evidence_required", True),
            risk_level=risk_level,
            authority_id=authority_id,
        ),
        metadata=Metadata(
            owner=metadata_data.get("owner"),
            created_by=metadata_data.get("created_by") or "ai_policy_builder",
            tags=tuple(metadata_data.get("tags", [])),
        ),
        audit=AuditTrail(created=datetime.now(timezone.utc)),
    )


def _infer_amount_limit(content: dict) -> float | None:
    """Reads a real upper-bound already present in the candidate's own
    conditions (an `amount` field compared with `<` or `<=`), never a
    guess. None, honestly, when no such condition exists -- the
    resulting Authority simply has no stated limit_amount, exactly like
    a real Delegation of Authority clause with no dollar cap."""
    for c in content.get("conditions", []):
        if c.get("field") == "amount" and c.get("operator") in ("<", "<="):
            try:
                return float(c["value"])
            except (TypeError, ValueError):
                return None
    return None


def _find_resolved_principal_for_candidate(db: Session, row: PolicyExtractionCandidate) -> Principal | None:
    """Authority-as-a-continuous-object, Stage G: only applies to
    candidates discovered by the AI Authority Builder (row.corpus_id is
    set) -- the single-document AI Policy Builder has no AuthorityPrincipal
    graph to resolve against, and correctly falls back to free text only,
    exactly as it always has. Matches the candidate's stated
    delegated_by (or, failing that, its scope.principal) against an
    AuthorityPrincipal in the same corpus that a reviewer has already
    resolved to a real Principal in Stage E -- never a fresh judgement
    made here."""
    if row.corpus_id is None:
        return None

    constraints_data = row.content.get("constraints") or {}
    scope_data = row.content.get("scope") or {}
    name = constraints_data.get("delegated_by") or scope_data.get("principal")
    if not name:
        return None

    stmt = (
        select(AuthorityPrincipal)
        .where(AuthorityPrincipal.corpus_id == row.corpus_id)
        .where(func.lower(AuthorityPrincipal.name) == name.strip().lower())
        .where(AuthorityPrincipal.resolved_principal_id.is_not(None))
    )
    discovery = db.scalar(stmt)
    if discovery is None:
        return None
    return db.get(Principal, discovery.resolved_principal_id)


def _create_authority_for_candidate(
    db: Session, row: PolicyExtractionCandidate, principal: Principal, reviewer_id: str | None
) -> Authority:
    """The Authority this promotion is exercising, created once, cited to
    its corpus and to the specific candidate's own source excerpt. Marked
    'approved' immediately: promoting a candidate is itself the reviewed,
    explicit human action (see AUTHORITY_REVIEW's gate on this endpoint)
    that a legacy-pipeline Authority would otherwise need a separate
    review step for."""
    scope_data = row.content.get("scope") or {}
    authority = Authority(
        corpus_id=row.corpus_id,
        principal_id=principal.id,
        scope=scope_data.get("action") or row.content.get("name") or "unspecified",
        limit_amount=_infer_amount_limit(row.content),
        currency=None,
        source_excerpt=row.source_excerpt,
        status="approved",
        reviewer_id=reviewer_id,
        reviewed_at=datetime.now(timezone.utc),
    )
    db.add(authority)
    db.flush()
    return authority


def promote_candidate(
    db: Session, candidate_id: uuid.UUID, organization_id: uuid.UUID | None, promoted_by: str | None = None
) -> tuple[RuntimePolicyRecord, str | None]:
    """AI_EXTRACTION_PIPELINE.md Stage 6. Builds the RuntimePolicy,
    validates it (domain/runtime_policy/validators.py, imported not
    modified), and on success calls the unmodified
    runtime_policy_service.create_policy: the one integration point
    between the AI Policy Builder and Policy Studio. Raises
    CandidateValidationError (never silently creates an invalid draft)
    if validation fails; the candidate stays pending_review so the
    reviewer can fix it and retry.

    Authority-as-a-continuous-object, Stage G: if this candidate came
    from the AI Authority Builder and its delegation resolves to a real,
    already-reviewed Principal (Stage E), a real Authority row is
    created here and referenced by the new policy's constraints.
    authority_id. If it doesn't resolve -- a single-document Policy
    Builder candidate, or a name that doesn't match any resolved
    Principal -- nothing here changes: the policy is created exactly as
    it always has been, with only the free-text delegated_by.

    Stage I.4: returns the resulting `authority_id` alongside the created
    record -- the value was already computed above, this only threads it
    out to the caller instead of discarding it.

    Milestone 2 (Multi-Tenant Foundation, ADR Phase B4): the new
    RuntimePolicy's organization is the candidate's own corpus's
    organization when it came from the AI Authority Builder's
    multi-document pipeline (Authority Intelligence's own established
    org lineage, threaded through rather than dropped at this exact
    handoff point -- the concrete break the ADR's dependency analysis
    found); `organization_id` (the promoting caller's own organization)
    is used only as a fallback for the single-document AI Policy
    Builder's upload-based path, which has no corpus and therefore no
    org lineage of its own to inherit. If a corpus's own organization
    disagrees with the promoting caller's, this fails closed
    (CrossOrganizationPromotionError) rather than silently picking one."""
    row = get_candidate(db, candidate_id)
    if row.status != "pending_review":
        raise CandidateNotPendingReviewError(f"cannot promote a candidate in status '{row.status}'")

    policy_organization_id = organization_id
    if row.corpus_id is not None:
        corpus = db.get(AuthorityCorpus, row.corpus_id)
        if corpus is not None and corpus.organization_id is not None:
            if organization_id is not None and corpus.organization_id != organization_id:
                raise CrossOrganizationPromotionError(
                    f"candidate {candidate_id}'s corpus belongs to organization "
                    f"{corpus.organization_id}, not the promoting caller's {organization_id}"
                )
            policy_organization_id = corpus.organization_id

    authority_id: str | None = None
    principal = _find_resolved_principal_for_candidate(db, row)
    if principal is not None:
        authority = _create_authority_for_candidate(db, row, principal, reviewer_id=promoted_by)
        authority_id = str(authority.id)

    policy = build_runtime_policy_from_candidate(row.content, authority_id=authority_id)
    result = validate(policy)
    if not result.ok:
        raise CandidateValidationError(result)

    created = runtime_policy_service.create_policy(db, policy, policy_organization_id)

    row.status = "promoted"
    row.promoted_policy_key = created.policy_key
    db.commit()
    db.refresh(row)
    return created, authority_id
