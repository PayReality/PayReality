"""trusted integration architecture phase 5.1: capability issuance idempotency

Revision ID: d4e8b1a6f2c9
Revises: b7d3a4f0e5c2
Create Date: 2026-09-01 12:00:00.000000

"""
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e8b1a6f2c9'
down_revision: Union[str, Sequence[str], None] = 'b7d3a4f0e5c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def choose_row_to_keep(rows: list[Any]) -> Any:
    """Pure decision logic, factored out of upgrade() specifically so it
    can be unit-tested directly with plain row-like objects -- no
    database, no Alembic migration context needed (see
    tests/unit/test_capability_issuance_idempotency_migration.py).

    `rows` are every capability_tokens row for one duplicated
    decision_id, each exposing `.id`, `.consumed_at`, `.issued_at`.
    Raises ValueError if more than one was independently consumed (the
    caller is expected to treat that as fatal, not resolvable here).
    See upgrade()'s own docstring for the full reasoning."""
    consumed = sorted((r for r in rows if r.consumed_at is not None), key=lambda r: r.consumed_at)
    if len(consumed) > 1:
        raise ValueError(
            f"{len(consumed)} independently consumed rows for the same decision_id -- "
            "a genuine double-issuance/double-consumption event, not resolvable automatically."
        )
    if consumed:
        return consumed[0]
    return max(rows, key=lambda r: r.issued_at)


def upgrade() -> None:
    """Upgrade schema.

    Trusted Integration Architecture, Phase 5.1 (Capability Issuance
    Idempotency): a real, confirmed-by-test gap in the code this
    migration's own commit closes let repeated or concurrent requests
    against the same Decision mint multiple independently valid
    Capabilities -- nothing in the schema stopped it (`decision_id` had
    only a plain, non-unique index). This migration replaces that index
    with a real uniqueness guarantee: one Decision, at most one
    Capability row, ever (see db/models.py's CapabilityToken and
    services/capability_service.py's own docstrings for the full
    reasoning).

    Before adding the constraint, any pre-existing duplicate issuances
    for the same decision_id are resolved first, since the constraint
    cannot be added while duplicates exist. Preference order: the
    earliest-CONSUMED row wins (that is the one a real downstream system
    actually redeemed -- deleting it would invalidate real history,
    exactly what section 27 of this milestone's own brief forbids); with
    no consumed row, the most-recently-ISSUED one wins, matching what
    intent_service.get_latest_capability_for_decision (and therefore
    every Receipt/Decision-Detail read) already treats as the
    authoritative one today. If more than one duplicate for the same
    decision was ever independently consumed -- the literal "two
    executable permissions for one operation" scenario this whole
    milestone exists to prevent -- this migration deliberately refuses
    to guess and aborts instead, surfacing the exact decision_id for a
    human to investigate; silently deleting evidence of a genuine
    double-consumption event would be the wrong kind of "safe."
    """
    bind = op.get_bind()
    meta = sa.MetaData()
    capability_tokens = sa.Table("capability_tokens", meta, autoload_with=bind)
    c = capability_tokens.c

    duplicate_decision_ids = [
        row[0]
        for row in bind.execute(
            sa.select(c.decision_id).group_by(c.decision_id).having(sa.func.count() > 1)
        )
    ]

    for decision_id in duplicate_decision_ids:
        rows = list(
            bind.execute(
                sa.select(c.id, c.consumed_at, c.issued_at)
                .where(c.decision_id == decision_id)
                .order_by(c.issued_at.desc())
            )
        )
        try:
            keep = choose_row_to_keep(rows)
        except ValueError as e:
            raise RuntimeError(
                f"capability_tokens: decision_id={decision_id}: {e} Investigate manually "
                "before re-running this migration."
            ) from e
        delete_ids = [r.id for r in rows if r.id != keep.id]
        bind.execute(capability_tokens.delete().where(c.id.in_(delete_ids)))

    op.drop_index("idx_capability_tokens_decision", table_name="capability_tokens")
    op.create_unique_constraint(
        "uq_capability_tokens_decision", "capability_tokens", ["decision_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_capability_tokens_decision", "capability_tokens", type_="unique")
    op.create_index("idx_capability_tokens_decision", "capability_tokens", ["decision_id"])
