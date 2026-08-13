import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Organization, PolicyExtractionCandidate, PolicyExtractionUpload, User
from app.db.session import get_db
from app.dependencies import get_current_organization, get_current_user_if_session, require_permission
from app.domain.ai_policy_builder.claude_provider import ClaudeRuntimePolicyExtractionProvider
from app.domain.ai_policy_builder.fake_provider import FakeRuntimePolicyExtractionProvider
from app.domain.ai_policy_builder.text_extraction import UnsupportedFormatError, detect_format
from app.domain.rbac.permissions import Permission
from app.schemas.ai_policy_builder import (
    CandidateResponse,
    EditCandidateRequest,
    ProviderStatusResponse,
    PromoteCandidateResponse,
    UploadResponse,
    ValidationErrorSchema,
)
from app.services import ai_policy_builder_service as svc
from app.services.ai_policy_builder_service import (
    CandidateNotFoundError,
    CandidateNotPendingReviewError,
    CandidateValidationError,
    CrossOrganizationPromotionError,
    UploadNotFoundError,
)

router = APIRouter(prefix="/v1/ai-policy-builder", tags=["ai-policy-builder"])


def _provider():
    if settings.anthropic_api_key:
        return ClaudeRuntimePolicyExtractionProvider()
    return FakeRuntimePolicyExtractionProvider()


def _upload_to_response(upload: PolicyExtractionUpload) -> UploadResponse:
    return UploadResponse(
        upload_id=str(upload.id),
        filename=upload.filename,
        format=upload.format,
        status=upload.status,
        error=upload.error,
        uploaded_at=upload.uploaded_at,
    )


def candidate_to_response(candidate: PolicyExtractionCandidate) -> CandidateResponse:
    return CandidateResponse(
        candidate_id=str(candidate.id),
        upload_id=str(candidate.upload_id) if candidate.upload_id else None,
        corpus_id=str(candidate.corpus_id) if candidate.corpus_id else None,
        content=candidate.content,
        confidence=candidate.confidence,
        missing_fields=list(candidate.missing_fields),
        source_excerpt=candidate.source_excerpt,
        source_location=candidate.source_location,
        status=candidate.status,
        promoted_policy_key=str(candidate.promoted_policy_key) if candidate.promoted_policy_key else None,
        created_at=candidate.created_at,
    )


@router.get("/status", response_model=ProviderStatusResponse)
def get_status():
    """Whether this deployment currently has a real Anthropic key
    configured, so the frontend can be honest with users about whether
    they're looking at real extraction or illustrative sample output."""
    return ProviderStatusResponse(ai_enabled=bool(settings.anthropic_api_key))


@router.post(
    "/uploads",
    response_model=UploadResponse,
    status_code=201,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
async def upload(file: UploadFile, db: Session = Depends(get_db)):
    """AI_EXTRACTION_PIPELINE.md Stage 1. Extraction (Stages 2-4) runs
    synchronously here, the same choice document_service.py's DoA upload
    already made, for the same reason: no job-queue infrastructure exists
    in this pilot, and a failed extraction is cheap to retry since the
    document is already stored."""
    try:
        format = detect_format(file.filename or "", file.content_type)
    except UnsupportedFormatError:
        raise HTTPException(status_code=422, detail="unsupported_format")

    raw = await file.read()
    row = svc.create_upload(db, filename=file.filename or "document", format=format, raw=raw)

    try:
        svc.run_extraction(db, row, _provider())
    except Exception:
        logging.getLogger("payreality.ai_policy_builder").exception(
            "extraction_failed upload_id=%s", row.id
        )

    return _upload_to_response(row)


@router.get("/uploads", response_model=list[UploadResponse])
def list_uploads(db: Session = Depends(get_db)):
    return [_upload_to_response(u) for u in svc.list_uploads(db)]


@router.get("/uploads/{upload_id}", response_model=UploadResponse)
def get_upload(upload_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        row = svc.get_upload(db, upload_id)
    except UploadNotFoundError:
        raise HTTPException(status_code=404, detail="upload_not_found")
    return _upload_to_response(row)


@router.get("/uploads/{upload_id}/candidates", response_model=list[CandidateResponse])
def list_candidates_for_upload(upload_id: uuid.UUID, db: Session = Depends(get_db)):
    return [candidate_to_response(c) for c in svc.list_candidates(db, upload_id=upload_id)]


@router.get("/candidates", response_model=list[CandidateResponse])
def list_candidates(
    status: str | None = None,
    upload_id: uuid.UUID | None = None,
    corpus_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
):
    return [
        candidate_to_response(c)
        for c in svc.list_candidates(db, upload_id=upload_id, corpus_id=corpus_id, status=status)
    ]


@router.get("/candidates/{candidate_id}", response_model=CandidateResponse)
def get_candidate(candidate_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        row = svc.get_candidate(db, candidate_id)
    except CandidateNotFoundError:
        raise HTTPException(status_code=404, detail="candidate_not_found")
    return candidate_to_response(row)


@router.put(
    "/candidates/{candidate_id}",
    response_model=CandidateResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def edit_candidate(candidate_id: uuid.UUID, body: EditCandidateRequest, db: Session = Depends(get_db)):
    try:
        row = svc.edit_candidate(db, candidate_id, body.content.model_dump())
    except CandidateNotFoundError:
        raise HTTPException(status_code=404, detail="candidate_not_found")
    except CandidateNotPendingReviewError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return candidate_to_response(row)


@router.post(
    "/candidates/{candidate_id}/dismiss",
    response_model=CandidateResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def dismiss_candidate(candidate_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        row = svc.dismiss_candidate(db, candidate_id)
    except CandidateNotFoundError:
        raise HTTPException(status_code=404, detail="candidate_not_found")
    except CandidateNotPendingReviewError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return candidate_to_response(row)


@router.post(
    "/candidates/{candidate_id}/promote",
    response_model=PromoteCandidateResponse,
    dependencies=[Depends(require_permission(Permission.AUTHORITY_REVIEW))],
)
def promote_candidate(
    candidate_id: uuid.UUID,
    db: Session = Depends(get_db),
    session_user: User | None = Depends(get_current_user_if_session),
    organization: Organization = Depends(get_current_organization),
):
    """AI_EXTRACTION_PIPELINE.md Stage 6: the one integration point with
    Policy Studio. Never deploys, never compiles; the result is a new
    draft RuntimePolicy at the very start of its own review lifecycle.

    Authority-as-a-continuous-object, Stage G: when a real session user
    promotes a candidate, their name is recorded as the new Authority's
    reviewer (if one is created) -- the same identity pattern Stage D
    already established for approvals, extended to this reviewed action."""
    try:
        created, authority_id = svc.promote_candidate(
            db, candidate_id, organization.id,
            promoted_by=session_user.name if session_user else None,
        )
    except CandidateNotFoundError:
        raise HTTPException(status_code=404, detail="candidate_not_found")
    except CandidateNotPendingReviewError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except CrossOrganizationPromotionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except CandidateValidationError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "validation_failed",
                "errors": [
                    ValidationErrorSchema(field=err.field, code=err.code, message=err.message).model_dump()
                    for err in e.result.errors
                ],
            },
        )
    return PromoteCandidateResponse(
        policy_key=str(created.policy_key), version=created.version, status=created.status,
        authority_id=authority_id,
    )
