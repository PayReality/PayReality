"""product lifecycle vertical slice: operations and destination duplicate prevention guarantees

Revision ID: a7c3e9f1b5d6
Revises: f3a5c7e9b1d4
Create Date: 2026-09-29 00:00:00.000001

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e9f1b5d6'
down_revision: Union[str, Sequence[str], None] = 'f3a5c7e9b1d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Product lifecycle vertical slice (app/services/operation_service.py):
    two new, additive tables -- no existing table or column is modified.
    `operations` tracks a real-world attempted operation separately from
    its (single-use, spent-after-one-consumption) Capability, so it can
    keep being queried and updated by later observation evidence long
    after the Capability itself is gone. `destination_duplicate_
    prevention_guarantees` is the one, deliberately human-documented way
    (besides a TERMINALLY_NOT_COMMITTED operation) a replacement attempt
    is ever reported safe -- see Operation/DestinationDuplicatePrevention
    Guarantee's own docstrings in app/db/models.py for the full reasoning.
    """
    op.create_table(
        'operations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('decision_id', sa.UUID(), nullable=False),
        sa.Column('capability_id', sa.UUID(), nullable=True),
        sa.Column('material_action_digest', sa.Text(), nullable=False),
        sa.Column('destination', sa.Text(), nullable=True),
        sa.Column('destination_operation_id', sa.Text(), nullable=True),
        sa.Column('state', sa.Text(), server_default='AUTHORIZED', nullable=False),
        sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['decision_id'], ['decisions.id']),
        sa.ForeignKeyConstraint(['capability_id'], ['capability_tokens.id']),
        sa.CheckConstraint(
            "state IN ('AUTHORIZED','DISPATCHED','COMMITTED','TERMINALLY_NOT_COMMITTED','OUTCOME_UNKNOWN')",
            name='ck_operations_state',
        ),
        sa.UniqueConstraint('decision_id', name='uq_operations_decision'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_operations_organization', 'operations', ['organization_id'])
    op.create_index('idx_operations_destination_operation', 'operations', ['destination_operation_id'])

    op.create_table(
        'destination_duplicate_prevention_guarantees',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('operation_id', sa.UUID(), nullable=False),
        sa.Column('destination', sa.Text(), nullable=False),
        sa.Column('scope_description', sa.Text(), nullable=False),
        sa.Column('retention_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('documented_by', sa.Text(), nullable=False),
        sa.Column('documented_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['operation_id'], ['operations.id']),
        sa.UniqueConstraint('operation_id', name='uq_duplicate_prevention_operation'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_duplicate_prevention_organization', 'destination_duplicate_prevention_guarantees', ['organization_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_duplicate_prevention_organization', table_name='destination_duplicate_prevention_guarantees')
    op.drop_table('destination_duplicate_prevention_guarantees')
    op.drop_index('idx_operations_destination_operation', table_name='operations')
    op.drop_index('idx_operations_organization', table_name='operations')
    op.drop_table('operations')
