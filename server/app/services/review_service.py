import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Authority, Principal

KNOWN_CURRENCIES = frozenset({"USD", "EUR", "GBP", "CAD", "AUD", "JPY"})


@dataclass(frozen=True)
class AuthorityWithFlags:
    authority: Authority
    validation_flags: list[str]


def _compute_flags(authority: Authority, all_pending: list[Authority]) -> list[str]:
    """spec 12.4 Stage 4: advisory flags shown to the reviewer, never used
    to auto-reject (spec 12.4 Stage 4's recovery strategy)."""
    flags: list[str] = []
    if authority.limit_amount is not None and authority.limit_amount < 0:
        flags.append("negative_amount")
    if authority.currency and authority.currency.upper() not in KNOWN_CURRENCIES:
        flags.append("unrecognized_currency")
    for other in all_pending:
        if other.id == authority.id:
            continue
        if (
            other.principal_id == authority.principal_id
            and other.scope == authority.scope
            and other.status == "approved"
        ):
            flags.append(f"duplicate_of:{other.id}")
    return flags


def list_authorities_for_review(
    db: Session,
    organization_id: uuid.UUID,
    document_id: uuid.UUID | None = None,
    status: str | None = None,
) -> list[AuthorityWithFlags]:
    """Milestone 12 (MILESTONE_12_POLICY_API_SECURITY_SUMMARY.md):
    `organization_id` is new and required -- this previously queried
    every organization's Authority rows unscoped. Authority has no
    organization_id column of its own (it predates multi-tenancy); the
    ownership chain is Authority.principal_id -> Principal.organization_id,
    the same chain Agent/Decision ownership already resolves through
    elsewhere in this codebase, applied here via a join rather than a
    per-row lookup since this is a list endpoint."""
    stmt = select(Authority).join(Principal, Authority.principal_id == Principal.id).where(
        Principal.organization_id == organization_id
    )
    if document_id is not None:
        stmt = stmt.where(Authority.document_id == document_id)
    if status is not None:
        stmt = stmt.where(Authority.status == status)
    authorities = list(db.scalars(stmt))

    # Flags are computed against all approved authorities system-wide, not
    # just the current filtered set, so duplicate detection works across
    # documents (spec 12.4 Stage 4's "unknown_principal"/"duplicate_of"
    # examples aren't scoped to a single document) -- but "system-wide"
    # must still mean "within this organization," never across tenants:
    # unscoped here would leak another organization's authority id into
    # this response's own duplicate_of:{id} flag, a real, subtler leak
    # this fix closes alongside the main listing query.
    all_approved = list(
        db.scalars(
            select(Authority)
            .join(Principal, Authority.principal_id == Principal.id)
            .where(Authority.status == "approved", Principal.organization_id == organization_id)
        )
    )

    return [
        AuthorityWithFlags(authority=a, validation_flags=_compute_flags(a, all_approved))
        for a in authorities
    ]
