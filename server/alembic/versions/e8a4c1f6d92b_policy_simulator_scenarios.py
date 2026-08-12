"""runtime policy simulator: simulation_scenarios table

Revision ID: e8a4c1f6d92b
Revises: c3e7f21a9b04
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e8a4c1f6d92b'
down_revision: Union[str, Sequence[str], None] = 'c3e7f21a9b04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Authority Intelligence Program, Phase 4 (POLICY_SIMULATOR.md): a new,
    standalone table. Only a saved scenario's definition is persisted --
    its actual outcome is always computed live, never stored, so this
    migration adds no column anywhere for a simulated decision itself.
    """
    op.create_table(
        'simulation_scenarios',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('policy_key', sa.UUID(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('input', postgresql.JSONB(), nullable=False),
        sa.Column('expected_outcome', sa.Text(), nullable=False),
        sa.Column('created_by', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "expected_outcome IN ('ALLOW','DENY','HUMAN_REVIEW')",
            name='ck_simulation_scenarios_expected_outcome',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_simulation_scenarios_policy_key', 'simulation_scenarios', ['policy_key']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_simulation_scenarios_policy_key', table_name='simulation_scenarios')
    op.drop_table('simulation_scenarios')
