from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Organization
from app.db.session import get_db
from app.dependencies import get_current_organization, require_permission
from app.domain.evidence.signing import public_key_b64_from_signing_key_b64
from app.domain.rbac.permissions import Permission
from app.schemas.evidence import (
    ChainVerificationResponse,
    EvidenceResponse,
    SigningKeyHistoryEntry,
    VerificationKeyHistoryResponse,
    VerificationKeyResponse,
    VerifyEvidenceResponse,
)
from app.services import evidence_service, signing_key_service
from app.services.evidence_service import EvidenceNotFoundError

router = APIRouter(prefix="/v1/evidence", tags=["evidence"])


@router.get("/verification-key", response_model=VerificationKeyResponse)
def get_verification_key():
    """Publishes the *currently active* ED25519 public key so a regulator,
    insurer, or auditor can verify a recent Evidence signature
    independently (offline, with no access to this server or its private
    key) rather than only being able to trust this API's own POST
    /verify result. If verifying a record signed under an older,
    rotated key, use GET /verification-keys instead (EVIDENCE_KEY_ROTATION.md)."""
    return VerificationKeyResponse(
        key_id=settings.evidence_signing_key_id,
        algorithm="ed25519",
        public_key_b64=public_key_b64_from_signing_key_b64(settings.evidence_signing_key_b64),
    )


@router.get("/verification-keys", response_model=VerificationKeyHistoryResponse)
def get_verification_key_history(db: Session = Depends(get_db)):
    """The full signing-key history, active and retired
    (EVIDENCE_KEY_ROTATION.md): what makes any Evidence or Agent
    Lifecycle audit event independently verifiable offline regardless of
    when it was signed, not just records signed under whichever key is
    active today."""
    keys = signing_key_service.list_signing_keys(db)
    return VerificationKeyHistoryResponse(
        keys=[
            SigningKeyHistoryEntry(
                key_id=k.key_id,
                algorithm="ed25519",
                public_key_b64=k.public_key_b64,
                created_at=k.created_at,
                retired_at=k.retired_at,
                active=k.retired_at is None,
            )
            for k in keys
        ]
    )


@router.get(
    "/{evidence_id}", response_model=EvidenceResponse,
    dependencies=[Depends(require_permission(Permission.EVIDENCE_VIEW))],
)
def get_evidence(
    evidence_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """spec 19.6. Milestone 1 (Security & Authorization Hardening):
    permission-gated and org-scoped -- a record belonging to a different
    organisation 404s identically to one that doesn't exist."""
    evidence = evidence_service.get_evidence(db, evidence_id, organization.id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="evidence_not_found")
    return EvidenceResponse.from_model(evidence)


@router.get(
    "", response_model=list[EvidenceResponse],
    dependencies=[Depends(require_permission(Permission.EVIDENCE_VIEW))],
)
def list_evidence(
    decision_id: UUID | None = None,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """spec 19.6. Milestone 1: permission-gated and org-scoped."""
    return [
        EvidenceResponse.from_model(e)
        for e in evidence_service.list_evidence(db, organization.id, decision_id)
    ]


@router.post(
    "/{evidence_id}/verify", response_model=VerifyEvidenceResponse,
    dependencies=[Depends(require_permission(Permission.EVIDENCE_VIEW))],
)
def verify_evidence(
    evidence_id: UUID,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """spec 19.7 / 17.5. A False result indicates tampering or corruption
    and must be treated as a P1 operational incident by the caller.
    Milestone 1: permission-gated and org-scoped, same as get/list above."""
    try:
        valid, key_id = evidence_service.verify_evidence(db, evidence_id, organization.id)
    except EvidenceNotFoundError:
        raise HTTPException(status_code=404, detail="evidence_not_found")

    return VerifyEvidenceResponse(
        evidence_id=evidence_id,
        valid=valid,
        verified_at=datetime.now(timezone.utc),
        key_id=key_id,
    )


@router.get(
    "/chain/verify", response_model=ChainVerificationResponse,
    dependencies=[Depends(require_permission(Permission.EVIDENCE_VIEW))],
)
def verify_chain(
    since: datetime | None = None,
    organization: Organization = Depends(get_current_organization),
    db: Session = Depends(get_db),
):
    """PHASE_5_EVIDENCE.md: independent verification of an Organisation-
    scoped chain -- checks both per-record signature validity and
    previous_hash continuity, catching a deleted or reordered record
    that per-record verification alone cannot.

    Milestone 11 (MILESTONE_11_SECURITY_BOUNDARY_COMPLETION_SUMMARY.md):
    this endpoint previously took `organization_id` as a plain,
    caller-supplied query parameter with no authentication at all --
    confirmed live-reachable, a CRITICAL finding from the Milestone 10
    sweep. `organization_id` is no longer accepted from the request at
    all (not merely ignored): it is now derived exclusively from the
    caller's authenticated identity, the same `Depends(get_current_organization)`
    plus `Permission.EVIDENCE_VIEW` pattern get_evidence/list_evidence/
    verify_evidence above already use, so an authenticated caller can
    only ever verify their own organisation's chain. This necessarily
    ends the endpoint's previous framing as a credential-free tool for
    an outside third party (the docstring's own former "auditor,
    regulator, insurer... with only the published verification key"
    story) and the previously-reachable organization_id=None scope
    (evidence for a Principal with no organisation assigned) -- no
    authenticated caller's own organisation is ever None, so that scope
    is now simply unreachable here, never silently granted to whichever
    caller asks first. A genuinely credential-free third-party
    verification story, if still wanted, is a different mechanism (e.g.
    a signed, evidence-specific export the organisation explicitly
    generates) and is out of this milestone's scope, not decided here."""
    result = evidence_service.verify_chain(db, organization.id, since=since)
    return ChainVerificationResponse(
        organization_id=organization.id,
        total=result.total,
        intact=result.intact,
        invalid_signatures=list(result.invalid_signatures),
        broken_links=list(result.broken_links),
    )
