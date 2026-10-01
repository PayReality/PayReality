"""Stripe sandbox review: durable, set-once bookkeeping for the
destination idempotency-protection window and the Stripe account a
destination_dispatch_identity (scripts/stripe_sandbox_adapter.py) is
bound to.

A separate module/table from app.db.models, not because this data is
conceptually unrelated to Operation -- it is -- but because this
session's own working directory already carries unrelated, uncommitted
changes to models.py from a different in-progress branch, and this
repo's own established convention is to never touch another
workstream's dirty files. Defining a new table here, importing only
`Base` from app.db.models (never modifying that file), keeps this
addition fully isolated while still sharing the same Base.metadata, the
same database, and the same migration chain as every other table.
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class StripeSandboxDispatchWindow(Base):
    """One row per destination_dispatch_identity -- the ROOT Operation.id
    of a replacement chain, per destination_dispatch_identity's own
    definition in scripts/stripe_sandbox_adapter.py. Written exactly
    once, at the first real dispatch attempt for that identity (via
    app.services.stripe_sandbox_dispatch_window_service.
    get_or_record_dispatch_window's own atomic, race-safe insert), and
    never updated after.

    `first_dispatch_attempted_at` anchors ensure_dispatch_window_still_
    valid's own 24h-conservative guard to the real moment dispatch was
    first attempted -- deliberately NOT Operation.created_at (set at
    issuance time, before an Agent has necessarily even consumed the
    Capability, let alone actually called the destination -- measuring
    from there is anchored to capability issuance, not first dispatch,
    which is exactly the wrong anchor this review's own task calls out)
    and NOT Operation.updated_at (bumped by any later, unrelated change
    to that row, including a manual adjudication long after -- "ensure
    concurrent attempts cannot reset it" rules out anything that can
    move once set).

    `bound_stripe_account_id` records which real Stripe account (Account.
    id, resolved via GET /v1/account) that first dispatch actually used.
    A later dispatch attempt under a DIFFERENT account (e.g. a rotated
    credential now pointing at a different Stripe account) is refused by
    dispatch_payment_intent's own live check, never silently resumed --
    carrying a destination identity forward only means anything against
    the SAME account the original attempt actually used; Stripe scopes
    idempotency keys per account, so reusing the same key against a
    different account would not collide, it would silently create an
    independent object."""

    __tablename__ = "stripe_sandbox_dispatch_windows"

    destination_dispatch_identity: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    bound_stripe_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    first_dispatch_attempted_at: Mapped[datetime] = mapped_column(nullable=False)
