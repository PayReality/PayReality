"""Trusted Enterprise Facts (PAYREALITY_FUTURE_VISION.md Part A,
ENTERPRISE_KNOWLEDGE_ARCHITECTURE.md / ..._DECISION_RECORD.md): the
minimum service needed for Runtime Authority to evaluate facts
originating outside the authorization request itself, safely.

Security model, stated once here rather than re-derived at each call
site: a fact is usable only when (1) its source belongs to the same
organization, (2) its source is active, (3) its signature verifies
against that source's own registered public key, (4) the fact has not
expired, and (5) there is no unresolved contradiction with another
currently-trusted fact for the same (organization, subject, key).
Missing, expired, or contradictory all resolve to the same place:
unknown, which the existing Runtime Authority fail-closed path already
handles -- this module never invents a new outcome for facts.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EnterpriseFact, FactSource
from app.domain.evidence.signing import Signature, verify_payload


class FactSourceNotFoundError(Exception):
    pass


class FactSourceRevokedError(Exception):
    pass


class InvalidFactSignatureError(Exception):
    pass


class FactReplayError(Exception):
    """A previously accepted attestation (same source_id + nonce)
    resubmitted as if it were fresh -- mirrors Intent's own
    UNIQUE(agent_id, nonce) replay defense exactly."""


class FactConflictError(Exception):
    """Two currently-unexpired, currently-trusted facts for the same
    (organization, subject, key) disagree. Never arbitrated here or by
    an LLM -- surfaced so the caller resolves to unknown/fail-closed,
    the same discipline this platform already applies to conflicting
    Runtime Policies at compile time."""

    def __init__(self, key: str, values: list):
        self.key = key
        self.values = values
        super().__init__(f"conflicting trusted facts for key={key!r}: {values!r}")


@dataclass(frozen=True)
class CanonicalFactAttestation:
    """The exact, minimal set of fields a fact signature must bind, per
    PAYREALITY_FUTURE_VISION.md Part A's security-critical canonical
    payload: organization_id, source_id, subject, key, value,
    observed_at, expires_at, nonce. No field is added beyond this list
    -- each one already directly prevents a substitution attack (swap
    the org, swap the source, swap the subject/key/value, replay past
    expiry, or replay the same nonce) and nothing else is security
    relevant to a fact considered in isolation."""

    organization_id: str
    source_id: str
    subject: str | None
    key: str
    value: object
    observed_at: str
    expires_at: str
    nonce: str

    def to_dict(self) -> dict:
        return {
            "organization_id": self.organization_id,
            "source_id": self.source_id,
            "subject": self.subject,
            "key": self.key,
            "value": self.value,
            "observed_at": self.observed_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
        }


def register_fact_source(
    db: Session, organization_id: uuid.UUID, name: str, public_key_b64: str
) -> FactSource:
    source = FactSource(organization_id=organization_id, name=name, public_key=public_key_b64)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def revoke_fact_source(db: Session, organization_id: uuid.UUID, source_id: uuid.UUID) -> FactSource:
    source = db.get(FactSource, source_id)
    if source is None or source.organization_id != organization_id:
        raise FactSourceNotFoundError(str(source_id))
    source.status = "revoked"
    source.revoked_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(source)
    return source


def ingest_fact(
    db: Session,
    organization_id: uuid.UUID,
    source_id: uuid.UUID,
    subject: str | None,
    key: str,
    value: object,
    observed_at: datetime,
    expires_at: datetime,
    nonce: str,
    signature_b64: str,
) -> EnterpriseFact:
    """Verifies the source's identity and signature BEFORE anything is
    persisted -- a forged or tampered attestation is rejected at
    ingestion, never stored and relied on later. Deliberately does not
    accept an unsigned, caller-self-attested fact at all: the only
    ingestion path this function offers requires a real signature
    verified against a registered FactSource's own public key, so an
    agent requesting authorization can never supply a consequential
    external fact about itself (supplier_approved, budget_available,
    approval_granted, goods_received) as if it were an independent
    attestation."""
    source = db.get(FactSource, source_id)
    if source is None or source.organization_id != organization_id:
        raise FactSourceNotFoundError(str(source_id))
    if source.status != "active":
        raise FactSourceRevokedError(str(source_id))

    attestation = CanonicalFactAttestation(
        organization_id=str(organization_id),
        source_id=str(source_id),
        subject=subject,
        key=key,
        value=value,
        observed_at=observed_at.isoformat(),
        expires_at=expires_at.isoformat(),
        nonce=nonce,
    )
    signature = Signature(algorithm="ed25519", key_id=str(source_id), value=signature_b64)
    if not verify_payload(attestation.to_dict(), signature, source.public_key):
        raise InvalidFactSignatureError(str(source_id))

    fact = EnterpriseFact(
        organization_id=organization_id,
        source_id=source_id,
        subject=subject,
        key=key,
        value=value,
        observed_at=observed_at,
        expires_at=expires_at,
        attestation_type="signed",
        signature=signature_b64,
        key_id=str(source_id),
        nonce=nonce,
    )
    db.add(fact)
    try:
        db.flush()
    except Exception as e:
        db.rollback()
        raise FactReplayError(f"{source_id}:{nonce}") from e
    db.commit()
    db.refresh(fact)
    return fact


def resolve_facts(
    db: Session,
    organization_id: uuid.UUID,
    subjects_and_keys: list[tuple[str | None, str]],
    now: datetime | None = None,
) -> list[EnterpriseFact]:
    """Resolves each requested (subject, key) to the single, currently-
    trusted EnterpriseFact row for it -- only from currently-active
    sources, only unexpired, never guessing between two currently-
    trusted, contradictory values. Returns the real rows (not just
    values) so a caller can bind full provenance -- source, observed_at,
    expires_at -- into Evidence, not only the resolved value.

    A (subject, key) with no matching row simply contributes nothing to
    the result; this is this function's only way of saying "unknown".
    Callers (intent_service.py) must treat an absent key as unresolved
    and let the existing fail-closed path handle it, never assume
    False/None/0 means anything.

    Cross-tenant facts (a different organization_id) can never be
    returned: every query below filters on organization_id, matching
    every other tenant-isolation boundary in this codebase."""
    now = now or datetime.now(timezone.utc)
    resolved: list[EnterpriseFact] = []
    for subject, key in subjects_and_keys:
        stmt = (
            select(EnterpriseFact)
            .join(FactSource, EnterpriseFact.source_id == FactSource.id)
            .where(
                EnterpriseFact.organization_id == organization_id,
                EnterpriseFact.subject == subject,
                EnterpriseFact.key == key,
                EnterpriseFact.expires_at > now,
                FactSource.status == "active",
            )
        )
        rows = list(db.scalars(stmt))
        if not rows:
            continue
        distinct_values = {_stable_repr(r.value) for r in rows}
        if len(distinct_values) > 1:
            raise FactConflictError(key, [r.value for r in rows])
        resolved.append(rows[0])
    return resolved


def _stable_repr(value: object) -> str:
    import json

    return json.dumps(value, sort_keys=True)
