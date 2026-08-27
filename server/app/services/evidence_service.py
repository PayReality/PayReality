import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, nullsfirst, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Evidence
from app.domain.evidence.signing import (
    Signature,
    payload_hash,
    public_key_b64_from_signing_key_b64,
    verify_payload,
)
from app.services import signing_key_service

logger = logging.getLogger("payreality.evidence")


class EvidenceNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class ChainVerificationResult:
    """PHASE_5_EVIDENCE.md: the result of checking an Organisation-scoped
    range of Evidence, both per-record signature validity (the existing
    guarantee) and previous_hash continuity (new -- the property that
    catches a deleted or reordered record, which signature-only
    verification cannot)."""

    total: int
    invalid_signatures: tuple[uuid.UUID, ...] = field(default_factory=tuple)
    broken_links: tuple[uuid.UUID, ...] = field(default_factory=tuple)

    @property
    def intact(self) -> bool:
        return not self.invalid_signatures and not self.broken_links


def get_evidence(db: Session, evidence_id: uuid.UUID, organization_id: uuid.UUID) -> Evidence | None:
    """Milestone 1 (Security & Authorization Hardening): org-scoped by
    construction. A record belonging to a different organisation is
    treated identically to a record that doesn't exist -- never
    distinguished from a genuine 404 -- so this can't be used to probe
    for another org's evidence IDs."""
    evidence = db.get(Evidence, evidence_id)
    if evidence is None or evidence.organization_id != organization_id:
        return None
    return evidence


def list_evidence(
    db: Session, organization_id: uuid.UUID, decision_id: uuid.UUID | None = None
) -> list[Evidence]:
    stmt = select(Evidence).where(Evidence.organization_id == organization_id)
    if decision_id is not None:
        stmt = stmt.where(Evidence.decision_id == decision_id)
    return list(db.scalars(stmt.order_by(Evidence.created_at)))


def count_evidence_by_status(db: Session, organization_id: uuid.UUID | None) -> dict[str, int]:
    """Product Experience Remediation Milestone 1 (Assurance): a real
    COUNT/GROUP BY over the already-indexed `status` column -- the
    "N of M verified" figure Assurance needs, without re-running
    signature/chain verification (that stays a separate, on-demand
    operation via verify_chain/GET /v1/evidence/chain/verify, not
    something the summary recomputes on every load)."""
    rows = db.execute(
        select(Evidence.status, func.count())
        .where(Evidence.organization_id == organization_id)
        .group_by(Evidence.status)
    ).all()
    return {status: count for status, count in rows}


def verify_evidence(db: Session, evidence_id: uuid.UUID, organization_id: uuid.UUID) -> tuple[bool, str]:
    """spec 17.5. A False result is a P1-severity signal for the caller to
    surface, not something this function itself escalates: verification
    is a query, not an alerting action.

    Resolves the public key by `evidence.key_id` through the signing-key
    registry (EVIDENCE_KEY_ROTATION.md), not from whatever key is
    currently configured: this is what keeps a record verifiable across
    a key rotation. Falling back to deriving from the current key when
    a key_id has no registry entry is a defensive safety net (should not
    happen once `ensure_current_key_registered` has run at least once),
    never a regression from this table's pre-registry behavior.

    Milestone 1 (Security & Authorization Hardening): org-scoped the same
    way get_evidence/list_evidence now are -- a caller cannot use this to
    learn whether an evidence_id belonging to another organisation
    exists, let alone whether its signature is valid.
    """
    evidence = db.get(Evidence, evidence_id)
    if evidence is None or evidence.organization_id != organization_id:
        raise EvidenceNotFoundError(str(evidence_id))

    public_key = signing_key_service.get_public_key_for_key_id(db, evidence.key_id)
    if public_key is None:
        logger.warning(
            "signing_key_registry_miss evidence_id=%s key_id=%s: falling back to the "
            "currently configured key. This should not happen once the registry has "
            "been seeded; investigate if it recurs.",
            evidence_id, evidence.key_id,
        )
        public_key = public_key_b64_from_signing_key_b64(settings.evidence_signing_key_b64)
    signature = Signature(algorithm="ed25519", key_id=evidence.key_id, value=evidence.signature)
    valid = verify_payload(evidence.payload, signature, public_key)
    return valid, evidence.key_id


def verify_chain(
    db: Session, organization_id: uuid.UUID | None, since: datetime | None = None
) -> ChainVerificationResult:
    """PHASE_5_EVIDENCE.md: checks an Organisation-scoped range of
    Evidence for both per-record signature validity (verify_evidence,
    unchanged) and previous_hash continuity -- the property that catches
    a deleted or reordered record, which signature-only verification
    cannot: a deleted record breaks the link at the exact gap it left,
    even though every remaining record's own signature still checks out.

    v1 (pre-chaining) records never had a previous_hash field at all;
    their absence of the field is expected, never treated as a break.

    Ordering (PayReality 1.0 Audit finding G01, chain-ordering follow-up):
    `sequence` (services/intent_service.py's real, monotonic, per-
    organization write ordinal, assigned under the same lock that
    serializes concurrent appends) is the primary sort key, ascending
    with nulls sorted first -- `created_at`/`id` alone are not reliable
    tiebreakers, since two records appended close together can share a
    timestamp, and `id` (a random UUID) has no relationship to true
    write order. Historical rows predating this column are still
    ordered among themselves by created_at/id exactly as before -- the
    same ambiguity that already existed for them, not newly introduced.
    """
    stmt = select(Evidence).where(Evidence.organization_id == organization_id)
    if since is not None:
        stmt = stmt.where(Evidence.created_at >= since)
    stmt = stmt.order_by(nullsfirst(Evidence.sequence), Evidence.created_at, Evidence.id)
    records = list(db.scalars(stmt))

    invalid_signatures: list[uuid.UUID] = []
    broken_links: list[uuid.UUID] = []

    # Seed expected_previous from whatever precedes this range (if
    # anything), so a real gap right at the range's own boundary is
    # still caught, not silently assumed fine just because verification
    # started mid-chain. Uses `sequence` (true write order), not
    # `created_at`, whenever the boundary record has one -- a `since`
    # cutoff landing on two records that share a timestamp would
    # otherwise let the real predecessor slip past the `<` comparison
    # unnoticed, exactly the ordering ambiguity `sequence` exists to
    # remove (see this function's own docstring).
    expected_previous: str | None = None
    if records:
        preceding_stmt = select(Evidence).where(Evidence.organization_id == organization_id)
        if records[0].sequence is not None:
            preceding_stmt = preceding_stmt.where(Evidence.sequence < records[0].sequence)
            preceding_stmt = preceding_stmt.order_by(Evidence.sequence.desc())
        else:
            preceding_stmt = preceding_stmt.where(Evidence.created_at < records[0].created_at)
            preceding_stmt = preceding_stmt.order_by(Evidence.created_at.desc(), Evidence.id.desc())
        preceding = db.scalar(preceding_stmt.limit(1))
        expected_previous = payload_hash(preceding.payload) if preceding is not None else None

    for record in records:
        # Milestone 3 (Enterprise Surface Isolation): verify_evidence's
        # organization_id argument was omitted here -- a guaranteed
        # TypeError for any organization with at least one Evidence
        # record, confirmed in MULTI_TENANT_ARCHITECTURE_VERIFICATION.md.
        # `record` was already resolved above by this same organization_id
        # filter, so this can never raise EvidenceNotFoundError.
        valid, _ = verify_evidence(db, record.id, organization_id)
        if not valid:
            invalid_signatures.append(record.id)

        if "previous_hash" in record.payload:
            if record.payload.get("previous_hash") != expected_previous:
                broken_links.append(record.id)

        expected_previous = payload_hash(record.payload)

    return ChainVerificationResult(
        total=len(records),
        invalid_signatures=tuple(invalid_signatures),
        broken_links=tuple(broken_links),
    )
