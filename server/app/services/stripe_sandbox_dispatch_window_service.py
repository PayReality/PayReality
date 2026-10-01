"""Stripe sandbox review: durable, race-safe persistence for a
destination_dispatch_identity's own first-dispatch timestamp and bound
Stripe account id -- see app.db.stripe_sandbox_models.
StripeSandboxDispatchWindow's own docstring for why this exists as a
separate table/module, and scripts/stripe_sandbox_adapter.py's own
ensure_dispatch_window_still_valid / StripeAccountBindingMismatchError
for what consumes the values this module persists.

This module owns ONLY durable storage -- no business logic is
duplicated here. destination_dispatch_identity's own chain-walk, the
24h-conservative window check, and the live account-binding check all
remain in the adapter itself (pure, no DB/ORM dependency); this service
is the thin, DB-dependent layer a real caller uses to get-or-set the one
row each of those checks needs."""

import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.stripe_sandbox_models import StripeSandboxDispatchWindow


def get_or_record_dispatch_window(
    db: Session, organization_id: uuid.UUID, destination_dispatch_identity: uuid.UUID, *,
    stripe_account_id: str, attempted_at: datetime | None = None,
) -> StripeSandboxDispatchWindow:
    """Set-once, race-safe: the FIRST caller for a given destination_
    dispatch_identity durably records attempted_at and stripe_account_id;
    every later caller -- a genuine retry, a replacement that carries
    the same identity forward, or a genuinely concurrent racer -- reads
    back exactly what that first caller recorded, never overwriting it.
    `stripe_account_id`/`attempted_at` passed by a losing or later caller
    are silently ignored once a row already exists -- the row's own
    primary-key uniqueness constraint (not application-level locking) is
    what makes the race safe, mirroring this codebase's own established
    create_operation_for_decision / resolve_or_create_business_operation_
    identity pattern: pre-check, insert, catch the loser's IntegrityError,
    re-read whatever the winner actually wrote.

    The returned row's own first_dispatch_attempted_at is always
    normalized to a timezone-AWARE UTC value before returning, regardless
    of backend: SQLite (this test suite's own backing store) does not
    round-trip timezone-aware DateTime values -- a value stored tz-aware
    comes back naive, which would otherwise crash
    ensure_dispatch_window_still_valid's own `now - first_dispatch_
    attempted_at` arithmetic (naive minus aware raises TypeError).
    Postgres's DateTime(timezone=True) does not have this gap (same
    pattern operation_service.py's own evaluate_replacement_safety
    already normalizes against for retention_until); normalizing here,
    once, for every caller is correct either way and never persisted
    back as a write."""
    existing = db.get(StripeSandboxDispatchWindow, destination_dispatch_identity)
    if existing is not None:
        return _with_aware_timestamp(existing)

    row = StripeSandboxDispatchWindow(
        destination_dispatch_identity=destination_dispatch_identity,
        organization_id=organization_id,
        bound_stripe_account_id=stripe_account_id,
        first_dispatch_attempted_at=attempted_at or datetime.now(timezone.utc),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(StripeSandboxDispatchWindow, destination_dispatch_identity)
        if existing is None:
            raise  # pragma: no cover -- a UNIQUE violation with no row to explain it is unexpected
        return _with_aware_timestamp(existing)
    db.refresh(row)
    return _with_aware_timestamp(row)


def _with_aware_timestamp(window: StripeSandboxDispatchWindow) -> StripeSandboxDispatchWindow:
    if window.first_dispatch_attempted_at.tzinfo is None:
        window.first_dispatch_attempted_at = window.first_dispatch_attempted_at.replace(tzinfo=timezone.utc)
    return window
