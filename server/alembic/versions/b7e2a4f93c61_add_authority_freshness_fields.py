"""add authority freshness fields

Revision ID: b7e2a4f93c61
Revises: a3f6c9d18b52
Create Date: 2026-08-25 09:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e2a4f93c61'
down_revision: Union[str, Sequence[str], None] = 'a3f6c9d18b52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_EVENT_TYPES = (
    "'created','edited','submitted','approved','rejected',"
    "'compiled','activated','activation_blocked','scheduled','schedule_cancelled',"
    "'rolled_back','deprecated','archived','retired'"
)
_NEW_EVENT_TYPES = _OLD_EVENT_TYPES + ",'attested'"


def upgrade() -> None:
    """Upgrade schema."""
    # All nullable and additive -- every existing RuntimePolicyRecord row
    # simply has no freshness data yet, rather than a fabricated value.
    op.add_column('runtime_policy_records', sa.Column('last_attested_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('runtime_policy_records', sa.Column('next_review_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('runtime_policy_records', sa.Column('review_cadence_days', sa.Integer(), nullable=True))
    op.add_column('runtime_policy_records', sa.Column('authority_expires_at', sa.DateTime(timezone=True), nullable=True))

    # Widen the existing event_type CHECK constraint to allow 'attested'.
    op.drop_constraint('ck_runtime_policy_lifecycle_events_event_type', 'runtime_policy_lifecycle_events', type_='check')
    op.create_check_constraint(
        'ck_runtime_policy_lifecycle_events_event_type',
        'runtime_policy_lifecycle_events',
        f"event_type IN ({_NEW_EVENT_TYPES})",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_runtime_policy_lifecycle_events_event_type', 'runtime_policy_lifecycle_events', type_='check')
    op.create_check_constraint(
        'ck_runtime_policy_lifecycle_events_event_type',
        'runtime_policy_lifecycle_events',
        f"event_type IN ({_OLD_EVENT_TYPES})",
    )
    op.drop_column('runtime_policy_records', 'authority_expires_at')
    op.drop_column('runtime_policy_records', 'review_cadence_days')
    op.drop_column('runtime_policy_records', 'next_review_at')
    op.drop_column('runtime_policy_records', 'last_attested_at')
