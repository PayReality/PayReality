"""runtime policy lifecycle: archived status, activation/deprecation columns, lifecycle events, activation schedules

Revision ID: f1c8b3d6a4e7
Revises: e8a4c1f6d92b
Create Date: 2026-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f1c8b3d6a4e7'
down_revision: Union[str, Sequence[str], None] = 'e8a4c1f6d92b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Runtime Policy Lifecycle (Phase 5, RUNTIME_POLICY_LIFECYCLE.md):
    every column added to runtime_policy_records is nullable and
    additive -- no existing row changes shape, no existing query result
    changes, for any environment on any prior schema version. The status
    CHECK constraint is widened to add 'archived' as an eighth allowed
    value; every previously-valid status string remains valid.
    """
    op.add_column('runtime_policy_records', sa.Column('activated_by', sa.Text(), nullable=True))
    op.add_column('runtime_policy_records', sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('runtime_policy_records', sa.Column('activation_reason', sa.Text(), nullable=True))
    op.add_column('runtime_policy_records', sa.Column('effective_from', sa.DateTime(timezone=True), nullable=True))
    op.add_column('runtime_policy_records', sa.Column('effective_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('runtime_policy_records', sa.Column('deprecated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('runtime_policy_records', sa.Column('deprecation_reason', sa.Text(), nullable=True))
    op.add_column('runtime_policy_records', sa.Column('rollback_of_version', sa.Integer(), nullable=True))

    op.drop_constraint('ck_runtime_policy_records_status', 'runtime_policy_records', type_='check')
    op.create_check_constraint(
        'ck_runtime_policy_records_status',
        'runtime_policy_records',
        "status IN ('draft','pending_review','approved','rejected','compiled','active','retired','archived')",
    )

    op.create_table(
        'runtime_policy_lifecycle_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('policy_key', sa.UUID(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.Text(), nullable=False),
        sa.Column('actor', sa.Text(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('payload', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('event_hash', sa.Text(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('created','edited','submitted','approved','rejected',"
            "'compiled','activated','activation_blocked','scheduled','schedule_cancelled',"
            "'rolled_back','deprecated','archived','retired')",
            name='ck_runtime_policy_lifecycle_events_event_type',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_runtime_policy_lifecycle_events_policy_key', 'runtime_policy_lifecycle_events', ['policy_key']
    )

    op.create_table(
        'policy_activation_schedules',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('policy_key', sa.UUID(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('effective_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), server_default='pending', nullable=False),
        sa.Column('created_by', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('execution_error', sa.Text(), nullable=True),
        sa.CheckConstraint("action IN ('activate','retire')", name='ck_policy_activation_schedules_action'),
        sa.CheckConstraint(
            "status IN ('pending','executed','failed','cancelled')",
            name='ck_policy_activation_schedules_status',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_policy_activation_schedules_policy_key', 'policy_activation_schedules', ['policy_key']
    )
    op.create_index(
        'idx_policy_activation_schedules_status', 'policy_activation_schedules', ['status']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_policy_activation_schedules_status', table_name='policy_activation_schedules')
    op.drop_index('idx_policy_activation_schedules_policy_key', table_name='policy_activation_schedules')
    op.drop_table('policy_activation_schedules')

    op.drop_index('idx_runtime_policy_lifecycle_events_policy_key', table_name='runtime_policy_lifecycle_events')
    op.drop_table('runtime_policy_lifecycle_events')

    op.drop_constraint('ck_runtime_policy_records_status', 'runtime_policy_records', type_='check')
    op.create_check_constraint(
        'ck_runtime_policy_records_status',
        'runtime_policy_records',
        "status IN ('draft','pending_review','approved','rejected','compiled','active','retired')",
    )

    op.drop_column('runtime_policy_records', 'rollback_of_version')
    op.drop_column('runtime_policy_records', 'deprecation_reason')
    op.drop_column('runtime_policy_records', 'deprecated_at')
    op.drop_column('runtime_policy_records', 'effective_until')
    op.drop_column('runtime_policy_records', 'effective_from')
    op.drop_column('runtime_policy_records', 'activation_reason')
    op.drop_column('runtime_policy_records', 'activated_at')
    op.drop_column('runtime_policy_records', 'activated_by')
